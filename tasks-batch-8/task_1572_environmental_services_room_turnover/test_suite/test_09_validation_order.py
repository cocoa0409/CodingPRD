"""Validation cascade claims (PRD §2.10): header, shape-beats-role, and the
existence / OCC / state ordering pairs."""
from test_helpers import (
    ApiErrorId,
    BOGUS_UUID,
    CLOCK_T0800,
    api_client,
    create_bed_payload,
    create_clean_request_payload,
    create_maintenance_window_payload,
    create_unit_payload,
    get_success_data,
    make_auditor_headers,
    make_technician_headers,
    set_clock,
    setup_basic_scenario,
    validate_error,
    validate_paginated,
    validate_success,
    TEST_USERS,
)
from test_helpers.fixtures import (
    assign_request,
    create_bed,
    create_request,
    create_standard,
    create_staff,
    create_technician,
    create_unit,
    seed_supplies,
    start_request,
)

ADMIN = TEST_USERS["admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]
ANY = TEST_USERS["any_headers"]


def test_request_missing_header_rejected_before_everything(api):
    """PRD §2.10: "First, the presence of the `X-User-ID` and `X-User-Role`
    headers is enforced (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`)."

    Design: Corner/validations/request_missing_header_rejected_before_everything
    """
    set_clock(CLOCK_T0800)
    # No X-User-ID / X-User-Role headers at all.
    resp = api.list_units(headers={"Content-Type": "application/json"})
    validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


def test_malformed_body_beats_role_check(api):
    """PRD §2.10: "Shape errors beat authorization — a malformed body is
    rejected before role checks run."
    PRD §3.6: "an `ATP_SWAB` audit must carry an integer `rlu_reading` and must
    not carry `marker_fraction_removed`, while a `FLUORESCENT_MARKER` audit
    must carry `marker_fraction_removed` — a fraction between 0 and 1 inclusive
    — and must not carry `rlu_reading`. Any mismatch between method and fields
    is rejected with `ERR_AUDIT_METHOD_FIELD_MISMATCH`."

    Design: Corner/validations/malformed_body_beats_role_check
    """
    set_clock(CLOCK_T0800)
    auditor = create_staff("A1", capabilities=("AUDIT",), display_name="Auditor One")

    # Malformed (missing rlu_reading) AND unauthorized role (dispatcher may not audit).
    r1 = api.create_quality_audit(
        {"clean_request_id": BOGUS_UUID, "audit_method": "ATP_SWAB"},
        DISPATCHER,
    )
    validate_error(r1, ApiErrorId.ERR_AUDIT_METHOD_FIELD_MISMATCH)

    # Mirrored: FLUORESCENT_MARKER carrying the forbidden rlu_reading, from a
    # properly-roled auditor.
    r2 = api.create_quality_audit(
        {
            "clean_request_id": BOGUS_UUID,
            "audit_method": "FLUORESCENT_MARKER",
            "marker_fraction_removed": 0.9,
            "rlu_reading": 100,
        },
        make_auditor_headers(auditor["id"]),
    )
    validate_error(r2, ApiErrorId.ERR_AUDIT_METHOD_FIELD_MISMATCH)


def test_unknown_staff_beats_state_check_on_assign(api):
    """PRD §2.10: "Fourth, path identifiers must resolve left to right,
    followed by body foreign keys (the 404 family of §2.5). ... Only then do
    state and business rules run."

    Design: Corner/validations/unknown_staff_beats_state_check_on_assign
    """
    ctx = setup_basic_scenario()
    req = create_request(ctx["bed"]["id"], "ROUTINE")
    assign_request(req["id"], ctx["tech"]["id"])
    start_request(req["id"], ctx["tech"]["id"])

    r = api.assign_clean_request(
        req["id"], {"staff_id": BOGUS_UUID}, DISPATCHER
    )
    validate_error(r, ApiErrorId.ERR_STAFF_NOT_FOUND)

    after = get_success_data(api.get_clean_request(req["id"], ANY))
    assert after["status"] == "IN_PROGRESS"
    assert after["assigned_staff_id"] == ctx["tech"]["id"]


def test_stale_version_beats_state_check_on_reassign(api):
    """PRD §2.10: "Sixth, optimistic-concurrency fields must match current
    versions (the 412 family of §2.7). Only then do state and business rules
    run."
    PRD §2.7: "Reassigning a clean request requires
    `expected_clean_request_version` matching the request's current `version`."

    Design: Corner/validations/stale_version_beats_state_check_on_reassign
    """
    set_clock(CLOCK_T0800)
    unit = create_unit()
    create_standard("ROUTINE")
    tech = create_technician("T1")
    bed = create_bed(unit["id"])
    req = create_request(bed["id"], "ROUTINE")
    created_version = req["version"]

    r = api.reassign_clean_request(
        req["id"],
        {
            "staff_id": tech["id"],
            "expected_clean_request_version": created_version + 1,
        },
        DISPATCHER,
    )
    validate_error(r, ApiErrorId.ERR_STALE_REQUEST_VERSION)

    after = get_success_data(api.get_clean_request(req["id"], ANY))
    assert after["status"] == "QUEUED"
    assert after["version"] == created_version


def test_open_request_blocks_manual_create_and_window_activation(api):
    """PRD §3.3: "Manual creation requires the bed to be `VACANT_DIRTY`
    (`ERR_BED_NOT_DIRTY` otherwise) and requires that the bed carry no other
    open request — a request in `QUEUED`, `ASSIGNED`, `IN_PROGRESS`,
    `PENDING_QA`, or `NEEDS_RECLEAN` status on the same bed rejects both manual
    creation and the discharge auto-create with `ERR_OPEN_REQUEST_EXISTS`."
    PRD §3.9: "and requires no open clean request on the bed — any request in
    `QUEUED`, `ASSIGNED`, `IN_PROGRESS`, `PENDING_QA`, or `NEEDS_RECLEAN`
    rejects the activation with `ERR_OPEN_REQUEST_EXISTS`."

    Design: Corner/validations/open_request_blocks_manual_create_and_window_activation
    """
    set_clock(CLOCK_T0800)
    unit = create_unit()
    create_standard("ROUTINE")
    b1 = create_bed(unit["id"], "B1", "STANDARD")
    b2 = create_bed(unit["id"], "B2", "STANDARD")
    create_request(b1["id"], "ROUTINE")
    create_request(b2["id"], "ROUTINE")
    window = get_success_data(
        api.create_maintenance_window(
            create_maintenance_window_payload(bed_id=b2["id"]), ADMIN
        )
    )

    r_create = api.create_clean_request(
        create_clean_request_payload(bed_id=b1["id"]), DISPATCHER
    )
    validate_error(r_create, ApiErrorId.ERR_OPEN_REQUEST_EXISTS)

    r_activate = api.activate_maintenance_window(window["id"], ADMIN)
    validate_error(r_activate, ApiErrorId.ERR_OPEN_REQUEST_EXISTS)

    reqs, meta = validate_paginated(
        api.list_clean_requests(ANY, params={"bed_id": b1["id"]})
    )
    assert len(reqs) == 1
    w_after = get_success_data(api.get_maintenance_window(window["id"], ANY))
    assert w_after["status"] == "SCHEDULED"
    b2_after = get_success_data(api.get_bed(b2["id"], ANY))
    assert b2_after["bed_status"] == "VACANT_DIRTY"


def test_manual_create_requires_vacant_dirty_bed(api):
    """PRD §3.3: "Manual creation requires the bed to be `VACANT_DIRTY`
    (`ERR_BED_NOT_DIRTY` otherwise)."

    Design: Corner/validations/manual_create_requires_vacant_dirty_bed
    """
    from test_helpers.fixtures import setup_verified_clean

    ctx = setup_verified_clean()
    bed = get_success_data(api.get_bed(ctx["bed"]["id"], ANY))
    assert bed["bed_status"] == "READY"

    r = api.create_clean_request(
        create_clean_request_payload(bed_id=ctx["bed"]["id"]), DISPATCHER
    )
    validate_error(r, ApiErrorId.ERR_BED_NOT_DIRTY)

    reqs, _ = validate_paginated(
        api.list_clean_requests(ANY, params={"bed_id": ctx["bed"]["id"]})
    )
    assert len(reqs) == 1
