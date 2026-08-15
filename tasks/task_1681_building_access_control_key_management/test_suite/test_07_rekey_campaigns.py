"""Rekey campaigns: estimate vs final cost variants, emergency surcharge branch,
successor-subtree minting, the re-pinning cascade, and approval guards."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    assert_timestamp_equals,
    create_building,
    create_credential,
    create_door,
    create_key_node,
    create_person,
    get_campaign,
    get_credential,
    get_door,
    get_key_node,
    get_incident_for_credential,
    get_success_data,
    issue_credential,
    list_charges,
    list_work_orders,
    set_clock,
    setup_approved_campaign,
    setup_building_with_chain,
    setup_lost_credential_incident,
    setup_tower_campaign_approved,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["security_admin_headers"]
DESK = TEST_USERS["front_desk_headers"]
OFFICER = TEST_USERS["security_officer_headers"]


# ---------------------------------------------------------------------------
# Corner: campaign guards
# ---------------------------------------------------------------------------

def test_campaign_cancel_with_active_work_rejected(api):
    """PRD §3.5: "Cancellation runs from `PROPOSED` or `APPROVED` (elsewhere,
    `ERR_CAMPAIGN_INVALID_STATE`); cancelling an `APPROVED` campaign
    additionally requires that no linked work order be `IN_PROGRESS` (else
    `ERR_CAMPAIGN_HAS_ACTIVE_WORK`) and cascades every linked `OPEN` work order
    to `CANCELLED`."
    PRD §3.5: "A campaign moves `APPROVED` → `IN_PROGRESS` automatically the
    moment its first linked work order starts, and `IN_PROGRESS` → `COMPLETED`
    automatically once every linked work order is `COMPLETED` or `CANCELLED`
    with at least one `COMPLETED`."

    Design: Corner/state_machines/campaign_cancel_with_active_work_rejected
    """
    ctx = setup_approved_campaign("Cancel House", clock="2026-08-01T09:00:00Z")
    campaign = ctx["campaign"]
    wo = ctx["work_orders"][0]
    validate_success(api.start_work_order(wo["id"], OFFICER))
    assert get_campaign(campaign["id"])["status"] == "IN_PROGRESS"

    resp = api.cancel_rekey_campaign(campaign["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_CAMPAIGN_HAS_ACTIVE_WORK)
    assert get_campaign(campaign["id"])["status"] == "IN_PROGRESS"


def test_campaign_approve_twice_rejected(api):
    """PRD §3.5: "Approval (`PROPOSED` → `APPROVED`, `SecurityAdmin` only) runs
    three guards: the campaign must be `PROPOSED` (else
    `ERR_CAMPAIGN_INVALID_STATE`); the refreshed `affected_door_count` must be
    greater than 0 (else `ERR_REKEY_SCOPE_EMPTY`); and when an `incident_id` is
    attached, that incident must be in `UNDER_REVIEW` or `RESOLVED` — an
    incident still `OPEN` yields `ERR_INCIDENT_NOT_REVIEWED`."

    Design: Corner/validations/campaign_approve_twice_rejected
    """
    ctx = setup_approved_campaign("Twice Approve House", with_issued_credential=False)
    campaign = ctx["campaign"]

    resp = api.approve_rekey_campaign(campaign["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_CAMPAIGN_INVALID_STATE)
    orders = list_work_orders(campaign_id=campaign["id"])
    assert len(orders) == 1, "no duplicate work-order minting on rejected approve"


def test_campaign_bill_person_without_target_rejected(api):
    """PRD §3.5: "A `SecurityAdmin` proposes one with a `building_id`, a
    `key_node_id` naming the scope root, an optional originating `incident_id`,
    a `bill_to` of `BUILDING` (the default) or `PERSON`, and a `bill_person_id`
    that is required exactly when `bill_to` is `PERSON` — supplying it with
    `BUILDING`, or omitting it with `PERSON`, is `ERR_BILL_TARGET_INVALID`."

    Design: Corner/validations/campaign_bill_person_without_target_rejected
    """
    ctx = setup_building_with_chain("Bill House")
    resp = api.create_rekey_campaign(
        {"building_id": ctx["building"]["id"], "key_node_id": ctx["change"]["id"],
         "bill_to": "PERSON"},
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_BILL_TARGET_INVALID)


def test_front_desk_cannot_approve_rekey_campaign(api):
    """PRD §2.1: "`SecurityAdmin` is the superset role: it alone creates
    buildings, key nodes, and doors; patches doors; creates, patches, and
    deletes access groups; terminates staff and vendors; creates, approves, and
    cancels rekey campaigns; voids charges; and sets the logical clock."
    PRD §2.1: "A request whose role is not permitted for the endpoint, or whose
    ownership check fails, is rejected with `ERR_FORBIDDEN` (HTTP 403)."

    Design: Corner/roles/front_desk_cannot_approve_rekey_campaign
    """
    ctx = setup_building_with_chain("RBAC House 2", with_door=True)
    resp = api.create_rekey_campaign(
        {"building_id": ctx["building"]["id"], "key_node_id": ctx["change"]["id"]},
        ADMIN,
    )
    campaign = validate_success(resp, expected_status=201)

    resp = api.approve_rekey_campaign(campaign["id"], DESK)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
    assert get_campaign(campaign["id"])["status"] == "PROPOSED"


# ---------------------------------------------------------------------------
# Difficulty: empty-scope boundary on approval
# ---------------------------------------------------------------------------

def _setup_empty_scope_campaign():
    ctx = setup_building_with_chain("Empty Scope House")
    set_clock("2026-08-01T09:00:00Z")
    resp = api_client.create_rekey_campaign(
        {"building_id": ctx["building"]["id"], "key_node_id": ctx["change"]["id"]},
        ADMIN,
    )
    campaign = validate_success(resp, expected_status=201)
    ctx["campaign"] = campaign
    return ctx


def test_rekey_approve_empty_scope_computes_zero_doors(api):
    """PRD §3.5: "`affected_door_count` counts doors whose `key_node_id` lies in
    the scope subtree with `core_status` `ACTIVE` or `REKEY_REQUIRED`,
    `affected_credential_count` counts credentials pinned in the subtree with
    `status` `ISSUED`, and `estimated_cost_cents` is the building's
    `base_fee_cents` plus `per_door_fee_cents` times the affected door count
    plus `per_key_reissue_fee_cents` times the affected credential count."

    Design: Difficulty/boundary_precision_check/rekey_approve_empty_scope_boundary
    """
    ctx = _setup_empty_scope_campaign()
    campaign = ctx["campaign"]
    assert campaign["affected_door_count"] == 0
    assert campaign["status"] == "PROPOSED"


def test_rekey_approve_empty_scope_rejected(api):
    """PRD §3.5: "Approval (`PROPOSED` → `APPROVED`, `SecurityAdmin` only) runs
    three guards: the campaign must be `PROPOSED` (else
    `ERR_CAMPAIGN_INVALID_STATE`); the refreshed `affected_door_count` must be
    greater than 0 (else `ERR_REKEY_SCOPE_EMPTY`); and when an `incident_id` is
    attached, that incident must be in `UNDER_REVIEW` or `RESOLVED` — an
    incident still `OPEN` yields `ERR_INCIDENT_NOT_REVIEWED`."

    Design: Difficulty/boundary_precision_check/rekey_approve_empty_scope_boundary
    """
    ctx = _setup_empty_scope_campaign()
    campaign = ctx["campaign"]

    resp = api.approve_rekey_campaign(campaign["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_REKEY_SCOPE_EMPTY)
    assert get_campaign(campaign["id"])["status"] == "PROPOSED"
    assert list_work_orders(campaign_id=campaign["id"]) == []


# ---------------------------------------------------------------------------
# Difficulty: approval gated on the linked incident leaving OPEN
# ---------------------------------------------------------------------------

def _setup_campaign_with_open_incident():
    ctx = setup_lost_credential_incident("Gate House", with_door=True)
    building, change, incident = ctx["building"], ctx["change"], ctx["incident"]
    resp = api_client.create_rekey_campaign(
        {"building_id": building["id"], "key_node_id": change["id"],
         "incident_id": incident["id"]},
        ADMIN,
    )
    campaign = validate_success(resp, expected_status=201)
    ctx["campaign"] = campaign
    return ctx


def test_campaign_approve_requires_reviewed_incident_rejected(api):
    """PRD §3.5: "Approval (`PROPOSED` → `APPROVED`, `SecurityAdmin` only) runs
    three guards: the campaign must be `PROPOSED` (else
    `ERR_CAMPAIGN_INVALID_STATE`); the refreshed `affected_door_count` must be
    greater than 0 (else `ERR_REKEY_SCOPE_EMPTY`); and when an `incident_id` is
    attached, that incident must be in `UNDER_REVIEW` or `RESOLVED` — an
    incident still `OPEN` yields `ERR_INCIDENT_NOT_REVIEWED`."

    Design: Difficulty/cross_entity_state_dependency/campaign_approve_requires_reviewed_incident
    """
    ctx = _setup_campaign_with_open_incident()
    campaign = ctx["campaign"]
    assert ctx["incident"]["status"] == "OPEN"

    resp = api.approve_rekey_campaign(campaign["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_INCIDENT_NOT_REVIEWED)
    assert get_campaign(campaign["id"])["status"] == "PROPOSED"


def test_campaign_approve_requires_reviewed_incident_no_successors_minted(api):
    """PRD §3.5: "Approval refreshes the scope counts and estimate, then mints
    the successor subtree: for every node in the scope subtree, processed in
    order of level depth ascending then `label` ascending, a new `KeyNode` is
    created with the same `level`, a `label` equal to the original label
    suffixed with `-R` followed by the campaign's `rekey_seq`, a `parent_id`
    pointing at the successor of the original node's parent (null for the scope
    root), `supersedes_node_id` set to the original node's id, and `status`
    `ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/campaign_approve_requires_reviewed_incident
    """
    ctx = _setup_campaign_with_open_incident()
    campaign, change = ctx["campaign"], ctx["change"]

    resp = api.approve_rekey_campaign(campaign["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_INCIDENT_NOT_REVIEWED)

    successors = get_success_data(
        api.list_key_nodes(ADMIN, params={"supersedes_node_id": change["id"]})
    )
    assert successors == [], "rejected approval must not mint a successor subtree"


# ---------------------------------------------------------------------------
# Difficulty: estimate vs final variant divergence (in-hours completion)
# ---------------------------------------------------------------------------

def _complete_tower_in_hours_with_cancel(ctx):
    """Cancel the D-2A order, then complete D-1A and D-1B at 10:00 (in business
    hours) with actual_cost_cents 7000 each."""
    wo1, wo2, wo3 = ctx["work_orders"]
    validate_success(api_client.cancel_work_order(wo3["id"], OFFICER))
    set_clock("2026-08-01T10:00:00Z")
    validate_success(api_client.start_work_order(wo1["id"], OFFICER))
    validate_success(api_client.complete_work_order(wo1["id"], {"actual_cost_cents": 7000}, OFFICER))
    validate_success(api_client.start_work_order(wo2["id"], OFFICER))
    validate_success(api_client.complete_work_order(wo2["id"], {"actual_cost_cents": 7000}, OFFICER))


def test_rekey_campaign_estimate_variant_snapshot(api):
    """PRD §3.5: "The new campaign starts `PROPOSED`, is assigned its
    per-building `rekey_seq`, and immediately computes its estimate:
    `affected_door_count` counts doors whose `key_node_id` lies in the scope
    subtree with `core_status` `ACTIVE` or `REKEY_REQUIRED`,
    `affected_credential_count` counts credentials pinned in the subtree with
    `status` `ISSUED`, and `estimated_cost_cents` is the building's
    `base_fee_cents` plus `per_door_fee_cents` times the affected door count
    plus `per_key_reissue_fee_cents` times the affected credential count."
    PRD §3.5: "The estimate is forward-looking — it snapshots current scope
    counts at standard rates and never applies the emergency surcharge."

    Design: Difficulty/dual_variant_calc/rekey_campaign_estimate_vs_final_divergence
    """
    ctx = setup_tower_campaign_approved()
    campaign = ctx["campaign"]
    # 3 doors in subtree(M1); only FB-1 ISSUED (MK-1 already LOST):
    # 15000 + 7500*3 + 2500*1 = 40000.
    assert campaign["affected_door_count"] == 3
    assert campaign["affected_credential_count"] == 1
    assert campaign["estimated_cost_cents"] == 40000


def test_rekey_campaign_final_variant_diverges_from_estimate(api):
    """PRD §3.5: "Completion stamps `completed_at`, retires every node in the
    scope subtree (`ACTIVE` or `COMPROMISED` → `RETIRED`), and computes
    `final_cost_cents` from what actually happened: the door portion is the
    building's `base_fee_cents` plus the sum of `actual_cost_cents` over linked
    work orders in `COMPLETED` status (cancelled orders drop out); if
    `completed_at`'s UTC time-of-day falls outside the half-open business-hours
    interval from `business_open_utc` (inclusive) to `business_close_utc`
    (exclusive), that door-portion subtotal is multiplied by one plus
    `emergency_surcharge_pct` hundredths and rounded half-up to integer cents,
    the surcharge being rounded exactly once; the key portion is the sum of
    `amount_cents` over the campaign's linked `KEY_REISSUE` charges; and
    `final_cost_cents` is the door portion plus the key portion."
    PRD §3.5: "Completion also creates a `Charge` of `kind` `REKEY_CAMPAIGN` in
    `DRAFT` whose `amount_cents` equals that door portion and whose `person_id`
    is the campaign's `bill_person_id` when `bill_to` is `PERSON`, null
    otherwise."

    Design: Difficulty/dual_variant_calc/rekey_campaign_estimate_vs_final_divergence
    """
    ctx = setup_tower_campaign_approved()
    campaign, s1, f1 = ctx["campaign"], ctx["s1"], ctx["f1"]
    _complete_tower_in_hours_with_cancel(ctx)

    final = get_campaign(campaign["id"])
    assert final["status"] == "COMPLETED"
    # Door portion 15000 + 7000 + 7000 = 29000 (cancelled D-2A order drops out;
    # 10:00 is inside [08:00, 18:00) so no surcharge); key portion 2500.
    assert final["final_cost_cents"] == 31500

    rekey_charges = list_charges(campaign_id=campaign["id"], kind="REKEY_CAMPAIGN")
    assert len(rekey_charges) == 1
    assert rekey_charges[0]["amount_cents"] == 29000
    assert rekey_charges[0]["person_id"] == s1["id"]

    key_charges = list_charges(campaign_id=campaign["id"], kind="KEY_REISSUE")
    assert len(key_charges) == 1
    assert key_charges[0]["amount_cents"] == 2500
    assert key_charges[0]["person_id"] == s1["id"]

    f1_after = get_credential(f1["id"])
    assert f1_after["status"] == "DEACTIVATED"
    assert f1_after["deactivated_reason"] == "REKEY"


# ---------------------------------------------------------------------------
# Difficulty: conditional emergency-surcharge branch in the final variant
# ---------------------------------------------------------------------------

def _complete_all_tower_orders_after_hours(ctx):
    """Complete all three orders at 20:30 (outside business hours) with
    actual_cost_cents 8000 each."""
    set_clock("2026-08-01T20:30:00Z")
    for wo in ctx["work_orders"]:
        validate_success(api_client.start_work_order(wo["id"], OFFICER))
        validate_success(api_client.complete_work_order(wo["id"], {"actual_cost_cents": 8000}, OFFICER))


def test_rekey_final_cost_emergency_branch_applied(api):
    """PRD §3.5: "if `completed_at`'s UTC time-of-day falls outside the
    half-open business-hours interval from `business_open_utc` (inclusive) to
    `business_close_utc` (exclusive), that door-portion subtotal is multiplied
    by one plus `emergency_surcharge_pct` hundredths and rounded half-up to
    integer cents, the surcharge being rounded exactly once; the key portion is
    the sum of `amount_cents` over the campaign's linked `KEY_REISSUE` charges;
    and `final_cost_cents` is the door portion plus the key portion."

    Design: Difficulty/combinatorial_formula/rekey_final_cost_conditional_emergency_branch
    """
    ctx = setup_tower_campaign_approved()
    campaign = ctx["campaign"]
    _complete_all_tower_orders_after_hours(ctx)

    final = get_campaign(campaign["id"])
    assert final["status"] == "COMPLETED"
    # Door portion round_half_up((15000 + 8000*3) * 1.20) = 46800; key 2500.
    assert final["final_cost_cents"] == 49300
    assert_timestamp_equals(final["completed_at"], "2026-08-01T20:30:00Z")


def test_rekey_final_cost_emergency_branch_charge_amount(api):
    """PRD §3.5: "Completion also creates a `Charge` of `kind` `REKEY_CAMPAIGN`
    in `DRAFT` whose `amount_cents` equals that door portion and whose
    `person_id` is the campaign's `bill_person_id` when `bill_to` is `PERSON`,
    null otherwise."
    PRD §2.6: "Where a percentage uplift applies (the administrative surcharge
    on forfeiture lines, the emergency surcharge on a rekey's door portion), the
    multiplied value is rounded half-up to integer cents; the rekey door portion
    is rounded exactly once, and forfeiture lines are rounded per line before
    any summing."

    Design: Difficulty/combinatorial_formula/rekey_final_cost_conditional_emergency_branch
    """
    ctx = setup_tower_campaign_approved()
    campaign, s1 = ctx["campaign"], ctx["s1"]
    _complete_all_tower_orders_after_hours(ctx)

    rekey_charges = list_charges(campaign_id=campaign["id"], kind="REKEY_CAMPAIGN")
    assert len(rekey_charges) == 1
    assert rekey_charges[0]["amount_cents"] == 46800
    assert rekey_charges[0]["person_id"] == s1["id"]
    assert rekey_charges[0]["status"] == "DRAFT"


# ---------------------------------------------------------------------------
# Difficulty: work-order completion re-pinning cascade (3 hops)
# ---------------------------------------------------------------------------

def _complete_single_door_rekey():
    ctx = setup_approved_campaign("Cascade Tower", clock="2026-08-01T10:00:00Z")
    wo = ctx["work_orders"][0]
    validate_success(api_client.start_work_order(wo["id"], OFFICER))
    validate_success(api_client.complete_work_order(wo["id"], {"actual_cost_cents": 7000}, OFFICER))
    return ctx


def test_rekey_completion_cascade_repins_door(api):
    """PRD §3.5: "Completing an `IN_PROGRESS` order records the supplied
    `actual_cost_cents` (required at completion), returns the door to
    `OPERATIONAL`, and — for `REKEY` orders only — fires the re-pinning cascade:
    hop 1 re-pins the door by setting `key_node_id` to `target_key_node_id`,
    rotating `bitting_code` to the target node's label, and restoring
    `core_status` to `ACTIVE`;"

    Design: Difficulty/transitive_cascade/rekey_completion_cascade_repin_deactivate_bill
    """
    ctx = _complete_single_door_rekey()
    door, change = ctx["door"], ctx["change"]

    successors = get_success_data(
        api.list_key_nodes(ADMIN, params={"supersedes_node_id": change["id"]})
    )
    assert len(successors) == 1, "approval must mint exactly one successor for C1"
    successor = successors[0]

    door_after = get_door(door["id"])
    assert door_after["core_status"] == "ACTIVE"
    assert door_after["key_node_id"] == successor["id"]
    assert door_after["bitting_code"] == successor["label"]
    assert door_after["hardware_status"] == "OPERATIONAL"


def test_rekey_completion_cascade_deactivates_credentials_and_bills(api):
    """PRD §3.5: "hop 2, caused by hop 1, deactivates every credential pinned to
    the door's pre-rekey node that is not already `DEACTIVATED`, stamping
    `deactivated_reason` `REKEY`; hop 3, caused by hop 2, creates for each
    credential that was `ISSUED` at the moment of deactivation a `Charge` of
    `kind` `KEY_REISSUE` in `DRAFT` status with `amount_cents` equal to the
    building's `per_key_reissue_fee_cents`, the `campaign_id` set, and
    `person_id` per the campaign's `bill_to` rule."
    PRD §3.5: "Completion stamps `completed_at`, retires every node in the scope
    subtree (`ACTIVE` or `COMPROMISED` → `RETIRED`), and computes
    `final_cost_cents` from what actually happened:"

    Design: Difficulty/transitive_cascade/rekey_completion_cascade_repin_deactivate_bill
    """
    ctx = _complete_single_door_rekey()
    campaign, cred, change = ctx["campaign"], ctx["credential"], ctx["change"]

    cred_after = get_credential(cred["id"])
    assert cred_after["status"] == "DEACTIVATED"
    assert cred_after["deactivated_reason"] == "REKEY"

    key_charges = list_charges(campaign_id=campaign["id"], kind="KEY_REISSUE")
    assert len(key_charges) == 1
    assert key_charges[0]["amount_cents"] == 2500
    assert key_charges[0]["person_id"] is None  # bill_to defaults to BUILDING
    assert key_charges[0]["status"] == "DRAFT"

    final = get_campaign(campaign["id"])
    assert final["status"] == "COMPLETED"
    # Door portion 15000 + 7000 = 22000 (in-hours); key portion 2500.
    assert final["final_cost_cents"] == 24500
    assert get_key_node(change["id"])["status"] == "RETIRED"


# ---------------------------------------------------------------------------
# Difficulty: report-lost compromise cascade flags the whole subtree
# ---------------------------------------------------------------------------

def _setup_two_master_subtrees():
    building = create_building("Subtree Tower")
    set_clock("2026-08-01T09:00:00Z")
    gm = create_key_node(building["id"], "GRAND_MASTER", "GM")
    m1 = create_key_node(building["id"], "MASTER", "M1", parent_id=gm["id"])
    m2 = create_key_node(building["id"], "MASTER", "M2", parent_id=gm["id"])
    c1 = create_key_node(building["id"], "CHANGE", "C1", parent_id=m1["id"])
    c2 = create_key_node(building["id"], "CHANGE", "C2", parent_id=m2["id"])
    d1 = create_door(building["id"], c1["id"], "D-1A")
    d2 = create_door(building["id"], c1["id"], "D-1B")
    d3 = create_door(building["id"], c2["id"], "D-2A")
    s1 = create_person(building["id"], "Staff One", "STAFF")
    mk1 = create_credential(building["id"], m1["id"], "MK-1", "METAL_KEY")
    issue_credential(mk1["id"], s1["id"])
    return {"building": building, "gm": gm, "m1": m1, "m2": m2, "c1": c1, "c2": c2,
            "d1": d1, "d2": d2, "d3": d3, "s1": s1, "mk1": mk1}


def test_report_lost_compromises_node_and_flags_subtree_doors(api):
    """PRD §3.4: "Hop 1 flips the credential's own `KeyNode` from `ACTIVE` to
    `COMPROMISED` (a no-op if the node is already `COMPROMISED` or `RETIRED`).
    Hop 2, caused by hop 1, sets `core_status` to `REKEY_REQUIRED` on every door
    whose `key_node_id` lies in the compromised node's subtree, including the
    node itself."

    Design: Difficulty/transitive_cascade/report_lost_compromise_cascade_flags_subtree
    """
    ctx = _setup_two_master_subtrees()
    lost = validate_success(api.report_lost_credential(ctx["mk1"]["id"], DESK))
    assert lost["status"] == "LOST"

    assert get_key_node(ctx["m1"]["id"])["status"] == "COMPROMISED"
    assert get_door(ctx["d1"]["id"])["core_status"] == "REKEY_REQUIRED"
    assert get_door(ctx["d2"]["id"])["core_status"] == "REKEY_REQUIRED"
    # Sibling subtree untouched.
    assert get_door(ctx["d3"]["id"])["core_status"] == "ACTIVE"
    assert get_key_node(ctx["m2"]["id"])["status"] == "ACTIVE"


def test_report_lost_opens_incident_with_responsible_holder(api):
    """PRD §3.4: "Hop 3, also caused by hop 1, opens an `Incident` with `type`
    `LOST_CREDENTIAL`, `status` `OPEN`, the `credential_id` of the lost
    credential, and `responsible_person_id` set to the credential's
    `holder_person_id` at the moment of the report."
    PRD §3.2: "A report stamps `lost_at` to now and deliberately retains
    `holder_person_id` for audit and settlement."

    Design: Difficulty/transitive_cascade/report_lost_compromise_cascade_flags_subtree
    """
    ctx = _setup_two_master_subtrees()
    lost = validate_success(api.report_lost_credential(ctx["mk1"]["id"], DESK))
    assert lost["holder_person_id"] == ctx["s1"]["id"]
    assert_timestamp_equals(lost["lost_at"], "2026-08-01T09:00:00Z")

    incident = get_incident_for_credential(ctx["mk1"]["id"])
    assert incident["type"] == "LOST_CREDENTIAL"
    assert incident["status"] == "OPEN"
    assert incident["responsible_person_id"] == ctx["s1"]["id"]
