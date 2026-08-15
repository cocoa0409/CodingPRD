"""Crate design lifecycle, wood-batch ledger, and ISPM-15 stamp custody (PRD §2.7, §3.2, §3.3, §3.4)."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    get_success_data, assert_version_incremented,
    create_packing_job_payload, create_item_payload,
    create_design_payload, approve_design_payload,
    create_wood_batch_payload, pack_crate_payload,
    create_customer, create_job, add_item, create_wood_batch,
    submit_and_approve_design, accept_quote,
    setup_quoted_job_with_item, setup_job_with_approved_design,
    setup_packing_job_with_crate, setup_sealed_crate,
    setup_two_packed_crates_one_stamp,
    assert_crate_design, assert_wood_batch, assert_crate,
    assert_wood_ledger_invariants,
)
from test_helpers import TEST_USERS

SR = TEST_USERS["sales_rep_headers"]
CD = TEST_USERS["crating_designer_headers"]
SF = TEST_USERS["shop_foreman_headers"]
CO = TEST_USERS["compliance_officer_headers"]


# ---------------------------------------------------------------------------
# Crate design revision cycle (difficulty: non_linear_state_machine)
# ---------------------------------------------------------------------------

def test_design_revision_cycle_returns_rejected_design_to_draft(api):
    """PRD §3.2: "The designer may revise a `REJECTED` design, returning it to `DRAFT` with `revision` incremented by one and all geometry recomputed from the item's current dimensions."
    PRD §3.2: "Rejection records the payload's `reason` into the design's `reject_reason` and leaves the design `REJECTED`."

    Design: Difficulty/non_linear_state_machine/crate_design_revision_cycle
    """
    _, _, item = setup_quoted_job_with_item(item_overrides={
        "description": "Gearbox", "weight_kg": 50, "fragile_class": "DELICATE",
        "declared_value_cents": 80000,
    })
    design = get_success_data(api_client.create_design(
        item["id"], create_design_payload(item["version"]), CD))
    get_success_data(api_client.submit_design(design["id"], CD))
    rejected = get_success_data(api_client.reject_design(
        design["id"], {"reason": "insufficient clearance"}, CO))
    assert rejected["status"] == "REJECTED"
    assert rejected["reject_reason"] == "insufficient clearance"

    revised = validate_success(api_client.revise_design(design["id"], CD), 200)
    assert revised["status"] == "DRAFT", "the loop edge REJECTED -> DRAFT"
    assert revised["revision"] == 2, "revision increments by one on revise"


def test_design_revision_cycle_completes_and_reserves_wood(api):
    """PRD §3.2: "On approval the design pins that `wood_batch_id`, the batch's `reserved_board_feet` increases by the required footage".
    PRD §3.2: "A `ComplianceOfficer` then approves or rejects it; attempts from any other source state are rejected with `ERR_DESIGN_INVALID_STATE`."

    Design: Difficulty/non_linear_state_machine/crate_design_revision_cycle
    """
    _, _, item = setup_quoted_job_with_item(item_overrides={
        "description": "Gearbox", "weight_kg": 50, "fragile_class": "DELICATE",
        "declared_value_cents": 80000,
    })
    batch = create_wood_batch(received_board_feet=5000, stamps_acquired=4)
    design = get_success_data(api_client.create_design(
        item["id"], create_design_payload(item["version"]), CD))
    get_success_data(api_client.submit_design(design["id"], CD))
    get_success_data(api_client.reject_design(design["id"], {"reason": "insufficient clearance"}, CO))
    get_success_data(api_client.revise_design(design["id"], CD))
    get_success_data(api_client.submit_design(design["id"], CD))
    approved = validate_success(api_client.approve_design(
        design["id"], approve_design_payload(batch["id"]), CO), 200)
    assert approved["status"] == "APPROVED"
    assert approved["revision"] == 2
    batch_after = validate_success(api_client.get_wood_batch(batch["id"], CO), 200)
    # PRD §3.2 geometry for a DELICATE 50x50x50 / 50 kg item: clearance 10,
    # thickness 1.8, external 73.6 cm per axis -> 3.250176 m2 -> ceil(35.751936) = 36.
    assert approved["board_feet_required"] == 36
    assert batch_after["reserved_board_feet"] == 36, \
        "the reservation lands only after the reject-revise-approve cycle completes"


# ---------------------------------------------------------------------------
# Crate reopen / reseal stamp cycle (difficulty: non_linear_state_machine)
# ---------------------------------------------------------------------------

def _setup_sealed_reopen_crate():
    return setup_sealed_crate(
        item_overrides={"description": "Motor", "weight_kg": 40,
                        "declared_value_cents": 60000},
        batch_overrides={"ht_certificate_no": "HT-2026-0021",
                         "received_board_feet": 5000, "stamps_acquired": 2})


def test_reopen_voids_stamp_and_reverts_crate(api):
    """PRD §3.4: "A `ShopForeman` may reopen a `SEALED` crate, moving it to `REOPENED`. The stamp is destroyed as an instrument but kept as evidence: `stamp_status` becomes `VOIDED` while the `stamp_serial` string is retained for audit, the batch's `stamps_applied` decreases by one and its `stamps_voided` increases by one, and two board feet of padding are sacrificed — `consumed_board_feet` decreases by two while `scrapped_board_feet` increases by two."

    Design: Difficulty/non_linear_state_machine/crate_reopen_reseal_stamp_cycle
    """
    ctx = _setup_sealed_reopen_crate()
    serial_1 = ctx["crate"]["stamp_serial"]
    assert serial_1 == "ISPM15-HT-2026-0021-0001"

    reopened = validate_success(api_client.reopen_crate(ctx["crate"]["id"], SF), 200)
    assert reopened["status"] == "REOPENED"
    assert reopened["stamp_status"] == "VOIDED"
    assert reopened["stamp_serial"] == serial_1, "the serial string is retained for audit"

    get_success_data(api_client.pack_crate(ctx["crate"]["id"], pack_crate_payload(), SF))
    resealed = validate_success(api_client.seal_crate(ctx["crate"]["id"], CO), 200)
    assert resealed["status"] == "SEALED"
    assert resealed["stamp_serial"] == "ISPM15-HT-2026-0021-0002"
    assert resealed["stamp_serial"] != serial_1, "a voided serial is never reused"


def test_reopen_reseal_keeps_batch_stamp_ledger_balanced(api):
    """PRD §3.3: "On the stamp side, `stamps_applied` counts serials currently active on sealed crates, `stamps_voided` counts serials voided by reopens — a voided serial is never reusable — and `stamps_available` is the acquired count minus applied minus voided."
    PRD §3.4: "`consumed_board_feet` decreases by two while `scrapped_board_feet` increases by two."

    Design: Difficulty/non_linear_state_machine/crate_reopen_reseal_stamp_cycle
    """
    ctx = _setup_sealed_reopen_crate()
    get_success_data(api_client.reopen_crate(ctx["crate"]["id"], SF))
    get_success_data(api_client.pack_crate(ctx["crate"]["id"], pack_crate_payload(), SF))
    get_success_data(api_client.seal_crate(ctx["crate"]["id"], CO))

    batch = validate_success(api_client.get_wood_batch(ctx["batch"]["id"], CO), 200)
    assert batch["stamps_applied"] == 1
    assert batch["stamps_voided"] == 1
    assert batch["scrapped_board_feet"] == 2
    assert batch["stamps_available"] == 0
    assert_wood_ledger_invariants(batch)


# ---------------------------------------------------------------------------
# Seal consumes the last available stamp (difficulty: boundary_precision_check)
# ---------------------------------------------------------------------------

def test_seal_with_last_available_stamp_succeeds(api):
    """PRD §3.4: "The stamp guard: the batch's `stamps_available` must be greater than zero (otherwise `ERR_STAMPS_EXHAUSTED`)."
    PRD §3.4: "A successful seal mints the crate's `stamp_serial` — the literal prefix `ISPM15-`, then the batch's `ht_certificate_no`, then a hyphen, then a four-digit zero-padded sequence equal to the batch's `stamps_applied` plus `stamps_voided` plus one".

    Design: Difficulty/boundary_precision_check/seal_consumes_last_available_stamp
    """
    ctx = setup_two_packed_crates_one_stamp()
    sealed = validate_success(api_client.seal_crate(ctx["crate1"]["id"], CO), 200)
    assert sealed["status"] == "SEALED"
    assert sealed["stamp_serial"].endswith("-0001")
    batch = validate_success(api_client.get_wood_batch(ctx["batch"]["id"], CO), 200)
    assert batch["stamps_available"] == 0


def test_seal_with_zero_available_stamps_rejected(api):
    """PRD §3.4: "The stamp guard: the batch's `stamps_available` must be greater than zero (otherwise `ERR_STAMPS_EXHAUSTED`)."

    Design: Difficulty/boundary_precision_check/seal_consumes_last_available_stamp
    """
    ctx = setup_two_packed_crates_one_stamp()
    get_success_data(api_client.seal_crate(ctx["crate1"]["id"], CO))
    res = api_client.seal_crate(ctx["crate2"]["id"], CO)
    validate_error(res, "ERR_STAMPS_EXHAUSTED", expected_status=422)
    crate2 = validate_success(api_client.get_crate(ctx["crate2"]["id"], SF), 200)
    assert crate2["status"] == "PACKED"


# ---------------------------------------------------------------------------
# Hazmat declaration gate at seal (difficulty: cross_entity_state_dependency)
# ---------------------------------------------------------------------------

def _setup_hazmat_packed_crate(batch_overrides=None):
    ctx = setup_job_with_approved_design(
        item_overrides={"description": "Paint line robot", "length_cm": 100,
                        "width_cm": 80, "height_cm": 60, "weight_kg": 40,
                        "hazmat": True, "declared_value_cents": 120000},
        batch_overrides=batch_overrides or {"received_board_feet": 5000,
                                            "stamps_acquired": 2})
    decl = get_success_data(api_client.create_hazmat_declaration(
        ctx["item"]["id"], {"un_number": "UN1263", "dg_class": "3", "packing_group": "II"},
        {"X-User-ID": "u-foreman-1", "X-User-Role": "ShopForeman",
         "Content-Type": "application/json"}))
    get_success_data(api_client.submit_hazmat_declaration(
        decl["id"], {"X-User-ID": "u-foreman-1", "X-User-Role": "ShopForeman",
                     "Content-Type": "application/json"}))
    accept_quote(ctx["customer"], ctx["job"]["id"])
    get_success_data(api_client.start_packing(ctx["job"]["id"], SF))
    crate = get_success_data(api_client.create_crate(
        ctx["item"]["id"], {"design_id": ctx["design"]["id"]}, SF))
    get_success_data(api_client.build_crate(crate["id"], SF))
    crate = get_success_data(api_client.pack_crate(crate["id"], pack_crate_payload(), SF))
    ctx["crate"] = crate
    ctx["decl"] = decl
    return ctx


def test_seal_blocked_while_declaration_not_approved(api):
    """PRD §3.4: "The dangerous-goods guard: if the item's `hazmat` is true or its `battery_in_equipment` is anything other than `NONE`, an `APPROVED` hazardous-goods declaration must exist for the item (otherwise `ERR_HAZMAT_DECLARATION_REQUIRED`)."

    Design: Difficulty/cross_entity_state_dependency/seal_requires_approved_hazmat_declaration
    """
    ctx = _setup_hazmat_packed_crate()
    res = api_client.seal_crate(ctx["crate"]["id"], CO)
    validate_error(res, "ERR_HAZMAT_DECLARATION_REQUIRED", expected_status=422)
    crate = validate_success(api_client.get_crate(ctx["crate"]["id"], SF), 200)
    assert crate["status"] == "PACKED"


def test_seal_succeeds_after_declaration_approved(api):
    """PRD §3.4: "an `APPROVED` hazardous-goods declaration must exist for the item (otherwise `ERR_HAZMAT_DECLARATION_REQUIRED`)".
    PRD §3.5: "Judgment belongs to a `ComplianceOfficer` alone, under segregation of duties: whether approving or rejecting, the officer's `X-User-ID` must differ from the declaration's `prepared_by_user_id`".

    Design: Difficulty/cross_entity_state_dependency/seal_requires_approved_hazmat_declaration
    """
    ctx = _setup_hazmat_packed_crate()
    approved = get_success_data(api_client.approve_hazmat_declaration(
        ctx["decl"]["id"], {"X-User-ID": "u-officer-9", "X-User-Role": "ComplianceOfficer",
                            "Content-Type": "application/json"}))
    assert approved["status"] == "APPROVED"
    assert approved["approved_by_user_id"] == "u-officer-9"
    sealed = validate_success(api_client.seal_crate(ctx["crate"]["id"], CO), 200)
    assert sealed["status"] == "SEALED"


# ---------------------------------------------------------------------------
# Safety-vs-fiscal priority at seal (difficulty: priority_pair_validation_conflict)
# ---------------------------------------------------------------------------

def test_seal_reports_hazmat_gate_before_stamp_quota(api):
    """PRD §2.8: "Beyond resolution, every request walks a single validation ladder, and when a request would fail several checks the failure earliest in this ladder is the one reported."
    PRD §2.8: "7. **Business safety** — declaration presence at seal (`ERR_HAZMAT_DECLARATION_REQUIRED`) ... 11. **Fiscal ceilings** — credit exposure (`ERR_CREDIT_LIMIT_EXCEEDED`), lumber sufficiency (`ERR_INSUFFICIENT_WOOD`), stamp availability (`ERR_STAMPS_EXHAUSTED`), and container payload (`ERR_CONTAINER_OVERWEIGHT`)."

    Design: Difficulty/priority_pair_validation_conflict/seal_safety_beats_fiscal_stamps
    """
    ctx = _setup_hazmat_packed_crate(batch_overrides={"received_board_feet": 5000,
                                                      "stamps_acquired": 0})
    res = api_client.seal_crate(ctx["crate"]["id"], CO)
    # Both the declaration gate (SUBMITTED, not APPROVED) and the stamp quota
    # (stamps_available == 0) fail; the earlier ladder tier is reported.
    validate_error(res, "ERR_HAZMAT_DECLARATION_REQUIRED", expected_status=422)


def test_seal_hazmat_priority_leaves_crate_and_stamps_untouched(api):
    """PRD §2.8: "7. **Business safety** — declaration presence at seal (`ERR_HAZMAT_DECLARATION_REQUIRED`), batch activity (`ERR_BATCH_NOT_ACTIVE`), dangerous-goods segregation in a container (`ERR_DG_SEGREGATION_VIOLATION`), protection-device fidelity at packing, crew qualification (`ERR_CREW_UNQUALIFIED`), and segregation of duties on declarations (`ERR_SOD_VIOLATION`)."
    PRD §3.4: "A successful seal mints the crate's `stamp_serial` — the literal prefix `ISPM15-`, then the batch's `ht_certificate_no`, then a hyphen, then a four-digit zero-padded sequence equal to the batch's `stamps_applied` plus `stamps_voided` plus one — sets `stamp_status` to `ACTIVE`, increments the batch's `stamps_applied` by one, bubbles the item to `SEALED`, and triggers the job's readiness auto-check described below."

    Design: Difficulty/priority_pair_validation_conflict/seal_safety_beats_fiscal_stamps
    """
    ctx = _setup_hazmat_packed_crate(batch_overrides={"received_board_feet": 5000,
                                                      "stamps_acquired": 0})
    api_client.seal_crate(ctx["crate"]["id"], CO)
    crate = validate_success(api_client.get_crate(ctx["crate"]["id"], SF), 200)
    assert crate["status"] == "PACKED"
    assert crate["stamp_serial"] is None, "no stamp may be minted by a rejected seal"
    batch = validate_success(api_client.get_wood_batch(ctx["batch"]["id"], CO), 200)
    assert batch["stamps_applied"] == 0


# ---------------------------------------------------------------------------
# Segregation of duties and declaration RBAC (corner: validations, rbac)
# ---------------------------------------------------------------------------

def test_declaration_approve_by_preparer_rejected(api):
    """PRD §2.10: "the approving or rejecting `ComplianceOfficer` must carry an `X-User-ID` different from the declaration's `prepared_by_user_id`, and a same-operator attempt is rejected with `ERR_SOD_VIOLATION` (HTTP 403)."

    Design: Corner/validations/sod_approver_is_preparer_rejected
    """
    _, _, item = setup_quoted_job_with_item(item_overrides={
        "description": "Battery pack", "weight_kg": 40, "hazmat": True,
        "battery_in_equipment": "LITHIUM_ION", "declared_value_cents": 80000,
    })
    co1 = {"X-User-ID": "u-co-1", "X-User-Role": "ComplianceOfficer",
           "Content-Type": "application/json"}
    decl = get_success_data(api_client.create_hazmat_declaration(
        item["id"], {"un_number": "UN3481", "dg_class": "9", "packing_group": "II",
                     "battery_type": "LITHIUM_ION"}, co1))
    get_success_data(api_client.submit_hazmat_declaration(decl["id"], co1))
    res = api_client.approve_hazmat_declaration(decl["id"], co1)
    validate_error(res, "ERR_SOD_VIOLATION", expected_status=403)
    decl_after = validate_success(api_client.get_hazmat_declaration(decl["id"], co1), 200)
    assert decl_after["status"] == "SUBMITTED"
    assert decl_after["approved_by_user_id"] is None


def test_foreman_cannot_approve_declaration(api):
    """PRD §3.5: "Judgment belongs to a `ComplianceOfficer` alone, under segregation of duties: whether approving or rejecting, the officer's `X-User-ID` must differ from the declaration's `prepared_by_user_id`, and a same-operator judgment is rejected with `ERR_SOD_VIOLATION`."
    PRD §2.1: "Access to each operation is restricted by role; a caller whose role is not admitted by the endpoint is rejected with `ERR_FORBIDDEN`."

    Design: Corner/rbac/foreman_cannot_approve_hazmat
    """
    _, _, item = setup_quoted_job_with_item(item_overrides={
        "description": "Battery pack", "weight_kg": 40, "hazmat": True,
        "battery_in_equipment": "LITHIUM_ION", "declared_value_cents": 80000,
    })
    foreman1 = {"X-User-ID": "u-foreman-1", "X-User-Role": "ShopForeman",
                "Content-Type": "application/json"}
    decl = get_success_data(api_client.create_hazmat_declaration(
        item["id"], {"un_number": "UN3481", "dg_class": "9", "packing_group": "II",
                     "battery_type": "LITHIUM_ION"}, foreman1))
    get_success_data(api_client.submit_hazmat_declaration(decl["id"], foreman1))
    res = api_client.approve_hazmat_declaration(decl["id"], foreman1)
    validate_error(res, "ERR_FORBIDDEN", expected_status=403)


# ---------------------------------------------------------------------------
# Design approval RBAC (corner: rbac)
# ---------------------------------------------------------------------------

def test_customer_cannot_approve_design(api):
    """PRD §2.1: "Access to each operation is restricted by role; a caller whose role is not admitted by the endpoint is rejected with `ERR_FORBIDDEN`."
    PRD §4: "Approve a design, pinning a wood batch and reserving board feet (`IN_REVIEW` → `APPROVED`) | ComplianceOfficer".

    Design: Corner/rbac/customer_cannot_approve_design
    """
    from test_helpers import make_customer_headers
    _, _, item = setup_quoted_job_with_item(customer_overrides={"site_code": "RBC-01"})
    batch = create_wood_batch(received_board_feet=500, stamps_acquired=2)
    design = get_success_data(api_client.create_design(
        item["id"], create_design_payload(item["version"]), CD))
    get_success_data(api_client.submit_design(design["id"], CD))
    owner = get_success_data(api_client.get_packing_job(item["packing_job_id"], SR))
    res = api_client.approve_design(
        design["id"], approve_design_payload(batch["id"]),
        make_customer_headers(owner["customer_id"]))
    validate_error(res, "ERR_FORBIDDEN", expected_status=403)
    design_after = validate_success(api_client.get_design(design["id"], CD), 200)
    assert design_after["status"] == "IN_REVIEW"
    batch_after = validate_success(api_client.get_wood_batch(batch["id"], CO), 200)
    assert batch_after["reserved_board_feet"] == 0, "no wood may be reserved by a rejected approval"


# ---------------------------------------------------------------------------
# Design supersede OCC and happy path (corner: cross_cutting_layers)
# ---------------------------------------------------------------------------

def test_design_create_with_stale_item_version_rejected(api):
    """PRD §2.7: "Creating a crate design for an item supersedes that item's existing non-terminal designs and is legitimate even when a prior design exists, but the request must carry `expected_item_version` equal to the item's current `version`. If the item's version has advanced since the caller last read it, the caller's view of the item's design set is stale and the create is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_layers/occ_stale_design_supersede
    """
    _, _, item = setup_quoted_job_with_item(item_overrides={
        "description": "Block", "weight_kg": 50, "declared_value_cents": 1000,
    })
    design1 = get_success_data(api_client.create_design(
        item["id"], create_design_payload(item["version"]), CD))
    res = api_client.create_design(
        item["id"], create_design_payload(item["version"]), CD)
    validate_error(res, "ERR_STALE_VERSION", expected_status=412)
    design1_after = validate_success(api_client.get_design(design1["id"], CD), 200)
    assert design1_after["status"] == "DRAFT", "the rejected create must not supersede design1"


def test_design_create_supersedes_prior_draft_with_fresh_version(api):
    """PRD §3.2: "it is the supersede mechanism: any of the item's existing designs in `DRAFT`, `IN_REVIEW`, or `REJECTED` are moved to `SUPERSEDED` by the act of creation, and the new design's `revision` is the count of the item's prior designs plus one".

    Design: Corner/cross_cutting_layers/design_supersede_success
    """
    _, _, item = setup_quoted_job_with_item(item_overrides={
        "description": "Block", "weight_kg": 50, "declared_value_cents": 1000,
    })
    design1 = get_success_data(api_client.create_design(
        item["id"], create_design_payload(item["version"]), CD))
    fresh_item = validate_success(api_client.get_item(item["id"], CD), 200)
    design2 = validate_success(api_client.create_design(
        item["id"], create_design_payload(fresh_item["version"]), CD), 201)
    assert design2["revision"] == 2
    assert design2["status"] == "DRAFT"
    design1_after = validate_success(api_client.get_design(design1["id"], CD), 200)
    assert design1_after["status"] == "SUPERSEDED"


# ---------------------------------------------------------------------------
# Wood batch job-cancel cascade (difficulty: transitive_cascade)
# ---------------------------------------------------------------------------

def _setup_depleted_batch_job():
    ctx = setup_job_with_approved_design(
        item_overrides={"description": "Pump", "weight_kg": 50,
                        "declared_value_cents": 30000},
        batch_overrides={"ht_certificate_no": "HT-2026-0030",
                         "received_board_feet": 27, "stamps_acquired": 0})
    return ctx


def test_batch_auto_depletes_when_availability_hits_zero(api):
    """PRD §3.3: "When `available_board_feet` reaches zero while the sum of reserved and consumed footage is positive, the batch moves itself from `ACTIVE` to `DEPLETED`".
    PRD §3.3: "`available_board_feet` is always the received footage minus the reserved, consumed, and scrapped amounts."

    Design: Difficulty/transitive_cascade/job_cancel_wood_release_cascade
    """
    ctx = _setup_depleted_batch_job()
    batch = validate_success(api_client.get_wood_batch(ctx["batch"]["id"], CO), 200)
    assert batch["available_board_feet"] == 0
    assert batch["reserved_board_feet"] == 27
    assert batch["status"] == "DEPLETED"


def test_job_cancel_releases_reservation_and_revives_batch(api):
    """PRD §3.9: "Every design in `DRAFT`, `IN_REVIEW`, `REJECTED`, `APPROVED`, or `LOCKED` moves to `SUPERSEDED`, and the `APPROVED` and `LOCKED` ones return their lumber: each batch's `reserved_board_feet` decreases by the corresponding `board_feet_required`."
    PRD §3.3: "when a later reservation release pushes availability above zero again, it recovers from `DEPLETED` back to `ACTIVE` on its own."

    Design: Difficulty/transitive_cascade/job_cancel_wood_release_cascade
    """
    ctx = _setup_depleted_batch_job()
    cancelled = validate_success(api_client.cancel_job(ctx["job"]["id"], SR), 200)
    assert cancelled["status"] == "CANCELLED"
    design = validate_success(api_client.get_design(ctx["design"]["id"], CD), 200)
    assert design["status"] == "SUPERSEDED"
    batch = validate_success(api_client.get_wood_batch(ctx["batch"]["id"], CO), 200)
    assert batch["reserved_board_feet"] == 0
    assert batch["available_board_feet"] == 27
    assert batch["status"] == "ACTIVE"
    assert_wood_ledger_invariants(batch)


# ---------------------------------------------------------------------------
# Batch suspend compliance-hold cascade (difficulty: transitive_cascade)
# ---------------------------------------------------------------------------

def test_suspend_batch_sets_compliance_hold_on_sealed_crate(api):
    """PRD §3.3: "Suspension cascades immediately: every crate whose pinned design draws on this batch and which currently sits in `PLANNED`, `BUILT`, `PACKED`, or `SEALED` has its `compliance_hold` set true, and each affected job's `readiness_posture` is recomputed — a job reading `READY` drops to `BLOCKED`."

    Design: Difficulty/transitive_cascade/batch_suspend_compliance_hold_cascade
    """
    ctx = setup_sealed_crate(
        item_overrides={"description": "Compressor", "weight_kg": 50,
                        "declared_value_cents": 90000},
        batch_overrides={"received_board_feet": 500, "stamps_acquired": 2})
    job = validate_success(api_client.get_packing_job(ctx["job"]["id"], SF), 200)
    assert job["status"] == "READY_TO_LOAD"
    assert job["readiness_posture"] == "READY"

    get_success_data(api_client.suspend_wood_batch(ctx["batch"]["id"], CO))
    crate = validate_success(api_client.get_crate(ctx["crate"]["id"], CO), 200)
    assert crate["compliance_hold"] is True


def test_suspend_batch_flips_job_readiness_to_blocked(api):
    """PRD §3.3: "each affected job's `readiness_posture` is recomputed — a job reading `READY` drops to `BLOCKED`."
    PRD §3.4: "A job's `readiness_posture` reads `READY` exactly when at least one crate exists, every crate sits in `SEALED`, `LOADED`, `SHIPPED`, or `DELIVERED`, and no crate carries a compliance hold; in every other situation it reads `BLOCKED`."

    Design: Difficulty/transitive_cascade/batch_suspend_compliance_hold_cascade
    """
    ctx = setup_sealed_crate(
        item_overrides={"description": "Compressor", "weight_kg": 50,
                        "declared_value_cents": 90000},
        batch_overrides={"received_board_feet": 500, "stamps_acquired": 2})
    get_success_data(api_client.suspend_wood_batch(ctx["batch"]["id"], CO))
    job = validate_success(api_client.get_packing_job(ctx["job"]["id"], CO), 200)
    assert job["readiness_posture"] == "BLOCKED"


# ---------------------------------------------------------------------------
# Wood ledger conservation (difficulty: compensating_invariant)
# ---------------------------------------------------------------------------

def test_wood_ledger_after_approval_reserves_exact_board_feet(api):
    """PRD §3.2: "On approval the design pins that `wood_batch_id`, the batch's `reserved_board_feet` increases by the required footage, `available_board_feet` is recomputed".
    PRD §3.3: "`available_board_feet` is always the received footage minus the reserved, consumed, and scrapped amounts."

    Design: Difficulty/compensating_invariant/wood_ledger_reserve_release_conservation
    """
    ctx = setup_job_with_approved_design(
        item_overrides={"description": "Pump", "weight_kg": 50,
                        "declared_value_cents": 30000},
        batch_overrides={"ht_certificate_no": "HT-2026-0070",
                         "received_board_feet": 500, "stamps_acquired": 0})
    batch = validate_success(api_client.get_wood_batch(ctx["batch"]["id"], CO), 200)
    assert batch["reserved_board_feet"] == 27
    assert batch["available_board_feet"] == 473
    assert_wood_ledger_invariants(batch)


def test_wood_ledger_returns_to_pre_action_state_after_cancel(api):
    """PRD §3.9: "Every design in `DRAFT`, `IN_REVIEW`, `REJECTED`, `APPROVED`, or `LOCKED` moves to `SUPERSEDED`, and the `APPROVED` and `LOCKED` ones return their lumber: each batch's `reserved_board_feet` decreases by the corresponding `board_feet_required`."
    PRD §3.3: "`available_board_feet` is always the received footage minus the reserved, consumed, and scrapped amounts."

    Design: Difficulty/compensating_invariant/wood_ledger_reserve_release_conservation
    """
    ctx = setup_job_with_approved_design(
        item_overrides={"description": "Pump", "weight_kg": 50,
                        "declared_value_cents": 30000},
        batch_overrides={"ht_certificate_no": "HT-2026-0070",
                         "received_board_feet": 500, "stamps_acquired": 0})
    get_success_data(api_client.cancel_job(ctx["job"]["id"], SR))
    batch = validate_success(api_client.get_wood_batch(ctx["batch"]["id"], CO), 200)
    assert batch["reserved_board_feet"] == 0
    assert batch["consumed_board_feet"] == 0
    assert batch["scrapped_board_feet"] == 0
    assert batch["available_board_feet"] == 500
    assert_wood_ledger_invariants(batch)


# ---------------------------------------------------------------------------
# Seal response immediate consistency (corner: consistency_model)
# ---------------------------------------------------------------------------

def test_seal_response_carries_minted_serial(api):
    """PRD §3.4: "A successful seal mints the crate's `stamp_serial` — the literal prefix `ISPM15-`, then the batch's `ht_certificate_no`, then a hyphen, then a four-digit zero-padded sequence equal to the batch's `stamps_applied` plus `stamps_voided` plus one — sets `stamp_status` to `ACTIVE`, increments the batch's `stamps_applied` by one, bubbles the item to `SEALED`".

    Design: Corner/consistency_model/seal_response_immediate_consistency
    """
    ctx = setup_packing_job_with_crate(
        batch_overrides={"ht_certificate_no": "HT-2026-0160",
                         "received_board_feet": 500, "stamps_acquired": 2},
        pack=True)
    sealed = validate_success(api_client.seal_crate(ctx["crate"]["id"], CO), 200)
    assert sealed["status"] == "SEALED"
    assert sealed["stamp_serial"] == "ISPM15-HT-2026-0160-0001"
    assert sealed["stamp_status"] == "ACTIVE"


def test_seal_response_agrees_with_subsequent_read(api):
    """PRD §2.11: "Several statuses in this system are derived rather than directly set, and the server transitions resources automatically when their criteria are met or broken".
    PRD §3.4: "A successful seal mints the crate's `stamp_serial` — the literal prefix `ISPM15-`, then the batch's `ht_certificate_no`, then a hyphen, then a four-digit zero-padded sequence equal to the batch's `stamps_applied` plus `stamps_voided` plus one — sets `stamp_status` to `ACTIVE`, increments the batch's `stamps_applied` by one, bubbles the item to `SEALED`, and triggers the job's readiness auto-check described below."

    Design: Corner/consistency_model/seal_response_immediate_consistency
    """
    ctx = setup_packing_job_with_crate(
        batch_overrides={"ht_certificate_no": "HT-2026-0160",
                         "received_board_feet": 500, "stamps_acquired": 2},
        pack=True)
    sealed = validate_success(api_client.seal_crate(ctx["crate"]["id"], CO), 200)
    reread = validate_success(api_client.get_crate(ctx["crate"]["id"], CO), 200)
    assert reread["status"] == sealed["status"] == "SEALED"
    assert reread["stamp_serial"] == sealed["stamp_serial"]
