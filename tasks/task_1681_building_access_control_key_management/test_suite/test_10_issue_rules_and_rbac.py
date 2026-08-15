"""Credential issuance rules (vendor expiry, master-key staffing, limits),
issuance cross-entity dependencies, validation-priority pairs, and self-service
RBAC."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    create_building,
    create_credential,
    create_key_node,
    create_person,
    get_credential,
    issue_credential,
    list_work_orders,
    make_resident_headers,
    set_clock,
    setup_building_with_chain,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["security_admin_headers"]
DESK = TEST_USERS["front_desk_headers"]


# ---------------------------------------------------------------------------
# Corner: issuance guard violations
# ---------------------------------------------------------------------------

def test_vendor_issue_without_expiry_rejected(api):
    """PRD §3.2: "and `expires_at` is required (`ERR_EXPIRY_REQUIRED_FOR_VENDOR`
    if absent) and must lie strictly in the future (`ERR_VALIDITY_WINDOW_INVALID`
    if not)."

    Design: Corner/validations/vendor_issue_without_expiry_rejected
    """
    ctx = setup_building_with_chain("ExpiryReq House")
    building, change = ctx["building"], ctx["change"]
    set_clock("2026-08-01T09:00:00Z")
    v1 = create_person(building["id"], "Vendor One", "VENDOR", employer_name="ACME")
    badge = create_credential(building["id"], change["id"], "VB-1", "FOB")

    resp = api.issue_credential(badge["id"], {"person_id": v1["id"]}, DESK)
    validate_error(resp, ApiErrorId.ERR_EXPIRY_REQUIRED_FOR_VENDOR)
    assert get_credential(badge["id"])["status"] == "IN_STOCK"


def test_non_vendor_issue_with_expiry_returns_invalid_request(api):
    """PRD §3.2: "For any non-vendor holder, supplying `expires_at` at all is
    `ERR_INVALID_REQUEST`."

    Design: Corner/validations/non_vendor_issue_with_expiry_returns_invalid_request
    """
    ctx = setup_building_with_chain("NoExpiry House")
    building, change = ctx["building"], ctx["change"]
    set_clock("2026-08-01T09:00:00Z")
    r1 = create_person(building["id"], "Res One", "RESIDENT", unit_label="U-1")
    cred = create_credential(building["id"], change["id"], "F-1", "FOB")

    resp = api.issue_credential(
        cred["id"], {"person_id": r1["id"], "expires_at": "2026-08-02T00:00:00Z"}, DESK
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_master_level_credential_to_resident_rejected(api):
    """PRD §3.2: "If the credential's key node sits above `CHANGE` level, the
    holder must be `STAFF`, else `ERR_MASTER_KEY_STAFF_ONLY`."

    Design: Corner/validations/master_level_credential_to_resident_rejected
    """
    building = create_building("MasterKey House")
    set_clock("2026-08-01T09:00:00Z")
    master = create_key_node(building["id"], "MASTER", "M")
    r1 = create_person(building["id"], "Res One", "RESIDENT", unit_label="U-1")
    mk = create_credential(building["id"], master["id"], "MK-1", "METAL_KEY")

    resp = api.issue_credential(mk["id"], {"person_id": r1["id"]}, DESK)
    validate_error(resp, ApiErrorId.ERR_MASTER_KEY_STAFF_ONLY)
    assert get_credential(mk["id"])["status"] == "IN_STOCK"


def test_vendor_single_live_badge_overlap_rejected(api):
    """PRD §3.2: "the vendor must not already hold another live credential — one
    `ISSUED` whose `expires_at` is still in the future — else
    `ERR_VENDOR_CREDENTIAL_WINDOW_OVERLAP`;"

    Design: Corner/validations/vendor_single_live_badge_overlap_rejected
    """
    ctx = setup_building_with_chain("Overlap House", vendor_badge_pool_max=10)
    building, change = ctx["building"], ctx["change"]
    set_clock("2026-08-01T09:00:00Z")
    v1 = create_person(building["id"], "Vendor One", "VENDOR", employer_name="ACME")
    vb1 = create_credential(building["id"], change["id"], "VB-1", "FOB")
    issue_credential(vb1["id"], v1["id"], expires_at="2026-08-01T12:00:00Z")
    vb2 = create_credential(building["id"], change["id"], "VB-2", "FOB")

    set_clock("2026-08-01T10:00:00Z")
    resp = api.issue_credential(
        vb2["id"], {"person_id": v1["id"], "expires_at": "2026-08-01T13:00:00Z"}, DESK
    )
    validate_error(resp, ApiErrorId.ERR_VENDOR_CREDENTIAL_WINDOW_OVERLAP)
    assert get_credential(vb2["id"])["status"] == "IN_STOCK"


# ---------------------------------------------------------------------------
# Corner: RBAC denials and self-service filters
# ---------------------------------------------------------------------------

def test_resident_cannot_create_door(api):
    """PRD §2.1: "`SecurityAdmin` is the superset role: it alone creates
    buildings, key nodes, and doors; patches doors; creates, patches, and
    deletes access groups; terminates staff and vendors; creates, approves, and
    cancels rekey campaigns; voids charges; and sets the logical clock."
    PRD §2.1: "A request whose role is not permitted for the endpoint, or whose
    ownership check fails, is rejected with `ERR_FORBIDDEN` (HTTP 403)."

    Design: Corner/roles/resident_cannot_create_door
    """
    ctx = setup_building_with_chain("RBAC House")
    building, change = ctx["building"], ctx["change"]
    r1 = create_person(building["id"], "Res One", "RESIDENT", unit_label="U-1")

    resp = api.create_door(
        {"building_id": building["id"], "door_code": "D-9", "key_node_id": change["id"]},
        make_resident_headers(r1["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
    doors = validate_paginated(api.list_doors(ADMIN, params={"building_id": building["id"]}))[0]
    assert doors == []


def test_resident_credential_list_requires_self_filter(api):
    """PRD §2.1: "Concretely, a `Resident` or `Vendor` may read only their own
    `Person` record (path id must equal `X-User-ID`, else `ERR_FORBIDDEN`), may
    list credentials only with a `holder_person_id` filter equal to their own
    id, may list charges only with a `person_id` filter equal to their own id,
    may pay only charges whose `person_id` equals their own id, and may report
    lost only credentials whose `holder_person_id` equals their own id."

    Design: Corner/roles/resident_credential_list_requires_self_filter
    """
    ctx = setup_building_with_chain("SelfList House")
    building, change = ctx["building"], ctx["change"]
    set_clock("2026-08-01T09:00:00Z")
    r1 = create_person(building["id"], "Res One", "RESIDENT", unit_label="U-1")
    r2 = create_person(building["id"], "Res Two", "RESIDENT", unit_label="U-2")
    f1 = create_credential(building["id"], change["id"], "F-1", "FOB")
    issue_credential(f1["id"], r1["id"])

    resp = api.list_credentials(make_resident_headers(r1["id"]),
                                params={"holder_person_id": r2["id"]})
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    mine, meta = validate_paginated(
        api.list_credentials(make_resident_headers(r1["id"]),
                             params={"holder_person_id": r1["id"]})
    )
    assert len(mine) == 1
    assert mine[0]["id"] == f1["id"]


# ---------------------------------------------------------------------------
# Difficulty: issue requires an ACTIVE person (Credential <- Person)
# ---------------------------------------------------------------------------

def _setup_moved_out_holder():
    ctx = setup_building_with_chain("CrossDep House")
    building, change = ctx["building"], ctx["change"]
    set_clock("2026-08-01T09:00:00Z")
    r1 = create_person(building["id"], "Res One", "RESIDENT", unit_label="U-1")
    validate_success(api_client.move_out_person(r1["id"], DESK))
    f1 = create_credential(building["id"], change["id"], "F-1", "FOB")
    ctx.update({"person": r1, "credential": f1})
    return ctx


def test_issue_requires_active_person_rejected(api):
    """PRD §3.2: "The target person must exist and be `ACTIVE`, else
    `ERR_PERSON_INACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/issue_requires_active_person
    """
    ctx = _setup_moved_out_holder()
    resp = api.issue_credential(ctx["credential"]["id"],
                                {"person_id": ctx["person"]["id"]}, DESK)
    validate_error(resp, ApiErrorId.ERR_PERSON_INACTIVE)


def test_issue_requires_active_person_no_partial_mutation(api):
    """PRD §3.2: "The target person must exist and be `ACTIVE`, else
    `ERR_PERSON_INACTIVE`."
    PRD §3.2: "A new credential has `status` `IN_STOCK`, null
    `holder_person_id`, null `issued_at`, null `expires_at`, null `lost_at`, and
    null `deactivated_reason`."

    Design: Difficulty/cross_entity_state_dependency/issue_requires_active_person
    """
    ctx = _setup_moved_out_holder()
    resp = api.issue_credential(ctx["credential"]["id"],
                                {"person_id": ctx["person"]["id"]}, DESK)
    validate_error(resp, ApiErrorId.ERR_PERSON_INACTIVE)
    cred = get_credential(ctx["credential"]["id"])
    assert cred["status"] == "IN_STOCK"
    assert cred["holder_person_id"] is None


# ---------------------------------------------------------------------------
# Difficulty: priority pair — state guard beats person-inactive safety rule
# ---------------------------------------------------------------------------

def _setup_deactivated_credential_and_moved_out_target():
    ctx = setup_building_with_chain("Priority House")
    building, change = ctx["building"], ctx["change"]
    set_clock("2026-08-01T09:00:00Z")
    r1 = create_person(building["id"], "Res One", "RESIDENT", unit_label="U-1")
    r2 = create_person(building["id"], "Res Two", "RESIDENT", unit_label="U-2")
    f1 = create_credential(building["id"], change["id"], "F-1", "FOB")
    issue_credential(f1["id"], r1["id"])
    validate_success(api_client.move_out_person(r1["id"], DESK))
    validate_success(api_client.move_out_person(r2["id"], DESK))
    ctx.update({"r1": r1, "r2": r2, "f1": f1})
    return ctx


def test_issue_state_error_beats_person_inactive_error(api):
    """PRD §2.9: "State-transition guards come after that — credential
    issuable/issued, person `ACTIVE`, and the
    incident/campaign/work-order/charge/alert guards (the various HTTP 409
    codes). Then security-critical
    business rules (`ERR_PERSON_INACTIVE`, `ERR_MASTER_KEY_STAFF_ONLY`)"
    PRD §3.2: "The credential must currently be `IN_STOCK`, else
    `ERR_CREDENTIAL_NOT_ISSUABLE`."

    Design: Difficulty/priority_pair_validation_conflict/issue_state_error_beats_person_inactive_safety
    """
    ctx = _setup_deactivated_credential_and_moved_out_target()
    # F-1 is DEACTIVATED (state violation) AND R2 is MOVED_OUT (safety
    # violation); the state guard is checked first.
    resp = api.issue_credential(ctx["f1"]["id"], {"person_id": ctx["r2"]["id"]}, DESK)
    validate_error(resp, ApiErrorId.ERR_CREDENTIAL_NOT_ISSUABLE)


def test_issue_state_error_beats_person_inactive_no_mutation(api):
    """PRD §2.9: "State-transition guards come after that — credential
    issuable/issued, person `ACTIVE`, and the
    incident/campaign/work-order/charge/alert guards (the various HTTP 409
    codes). Then security-critical
    business rules (`ERR_PERSON_INACTIVE`, `ERR_MASTER_KEY_STAFF_ONLY`)"

    Design: Difficulty/priority_pair_validation_conflict/issue_state_error_beats_person_inactive_safety
    """
    ctx = _setup_deactivated_credential_and_moved_out_target()
    resp = api.issue_credential(ctx["f1"]["id"], {"person_id": ctx["r2"]["id"]}, DESK)
    validate_error(resp, ApiErrorId.ERR_CREDENTIAL_NOT_ISSUABLE)
    assert get_credential(ctx["f1"]["id"])["status"] == "DEACTIVATED"
    assert validate_success(api.get_person(ctx["r2"]["id"], DESK))["status"] == "MOVED_OUT"


# ---------------------------------------------------------------------------
# Difficulty: priority pair — credential limit (constraint) beats expiry window
# (temporal)
# ---------------------------------------------------------------------------

def _setup_vendor_at_limit_with_stale_badges():
    """V1 holds 5 ISSUED badges whose expiries have all passed (unswept — no
    run-ops has run), so the 5-count limit is hit while no badge is live."""
    ctx = setup_building_with_chain("Constraint House", vendor_badge_pool_max=10)
    building, change = ctx["building"], ctx["change"]
    set_clock("2026-08-01T08:00:00Z")
    v1 = create_person(building["id"], "Vendor One", "VENDOR",
                       employer_name="ACME Elevators")
    windows = [
        ("VT-1", "2026-08-01T08:00:00Z", "2026-08-01T09:00:00Z", "2026-08-01T09:30:00Z"),
        ("VT-2", "2026-08-01T09:30:00Z", "2026-08-01T10:30:00Z", "2026-08-01T11:00:00Z"),
        ("VT-3", "2026-08-01T11:00:00Z", "2026-08-01T12:00:00Z", "2026-08-01T12:30:00Z"),
        ("VT-4", "2026-08-01T12:30:00Z", "2026-08-01T13:30:00Z", "2026-08-01T14:00:00Z"),
        ("VT-5", "2026-08-01T14:00:00Z", "2026-08-01T15:00:00Z", "2026-08-01T15:30:00Z"),
    ]
    for serial, issue_at, expires_at, next_clock in windows:
        set_clock(issue_at)
        cred = create_credential(building["id"], change["id"], serial, "FOB")
        issue_credential(cred["id"], v1["id"], expires_at=expires_at)
        set_clock(next_clock)
    vt6 = create_credential(building["id"], change["id"], "VT-6", "FOB")
    ctx.update({"v1": v1, "vt6": vt6})
    return ctx


def test_vendor_issue_limit_beats_expiry_temporal_error(api):
    """PRD §2.9: "then uniqueness, hierarchy, capacity, and scope constraints
    (`ERR_DOOR_CODE_EXISTS`, `ERR_SERIAL_EXISTS`, `ERR_KEY_HIERARCHY_INVALID`,
    `ERR_CREDENTIAL_LIMIT_EXCEEDED`, `ERR_VENDOR_CREDENTIAL_WINDOW_OVERLAP`,
    `ERR_VENDOR_BADGE_POOL_EXHAUSTED`, `ERR_WORK_ORDER_OVERLAP`,
    `ERR_REKEY_SCOPE_EMPTY`), then temporal sanity
    (`ERR_EXPIRY_REQUIRED_FOR_VENDOR`, `ERR_VALIDITY_WINDOW_INVALID`,
    `ERR_SCHEDULE_INVALID`)"
    PRD §3.2: "The person must currently hold fewer than 5 credentials in
    `ISSUED`, else `ERR_CREDENTIAL_LIMIT_EXCEEDED`."

    Design: Difficulty/priority_pair_validation_conflict/vendor_issue_limit_beats_expiry_temporal
    """
    ctx = _setup_vendor_at_limit_with_stale_badges()
    # Now == 15:30; the offered expires_at 15:00 is also in the past, so both
    # the capacity rule and the temporal rule fail — the capacity rule wins.
    resp = api.issue_credential(
        ctx["vt6"]["id"],
        {"person_id": ctx["v1"]["id"], "expires_at": "2026-08-01T15:00:00Z"},
        DESK,
    )
    validate_error(resp, ApiErrorId.ERR_CREDENTIAL_LIMIT_EXCEEDED)


def test_vendor_issue_limit_beats_expiry_temporal_no_mutation(api):
    """PRD §2.9: "then uniqueness, hierarchy, capacity, and scope constraints
    (`ERR_DOOR_CODE_EXISTS`, `ERR_SERIAL_EXISTS`, `ERR_KEY_HIERARCHY_INVALID`,
    `ERR_CREDENTIAL_LIMIT_EXCEEDED`, `ERR_VENDOR_CREDENTIAL_WINDOW_OVERLAP`,
    `ERR_VENDOR_BADGE_POOL_EXHAUSTED`, `ERR_WORK_ORDER_OVERLAP`,
    `ERR_REKEY_SCOPE_EMPTY`), then temporal sanity
    (`ERR_EXPIRY_REQUIRED_FOR_VENDOR`, `ERR_VALIDITY_WINDOW_INVALID`,
    `ERR_SCHEDULE_INVALID`)"

    Design: Difficulty/priority_pair_validation_conflict/vendor_issue_limit_beats_expiry_temporal
    """
    ctx = _setup_vendor_at_limit_with_stale_badges()
    resp = api.issue_credential(
        ctx["vt6"]["id"],
        {"person_id": ctx["v1"]["id"], "expires_at": "2026-08-01T15:00:00Z"},
        DESK,
    )
    validate_error(resp, ApiErrorId.ERR_CREDENTIAL_LIMIT_EXCEEDED)
    assert get_credential(ctx["vt6"]["id"])["status"] == "IN_STOCK"
