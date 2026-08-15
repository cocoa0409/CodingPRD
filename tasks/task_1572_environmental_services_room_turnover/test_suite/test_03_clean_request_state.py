"""CleanRequest state machine claims (transitions, terminal lockdown, cancel paths)."""
from test_helpers import (
    ApiErrorId,
    CLOCK_T0800,
    api_client,
    create_bed_payload,
    create_clean_request_payload,
    create_unit_payload,
    get_success_data,
    set_clock,
    setup_basic_scenario,
    setup_needs_reclean,
    validate_error,
    validate_paginated,
    validate_success,
    TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]
ANY = TEST_USERS["any_headers"]


def test_clean_request_terminal_states_reject_all_transitions(api):
    """PRD §2.10: "State validity comes first, and within it a terminal-state
    rejection always precedes a wrong-state rejection: a clean request that has
    reached `VERIFIED` or `CANCELLED` answers `ERR_REQUEST_ALREADY_TERMINAL` to
    any further transition attempt, never a wrong-state error."

    Design: Corner/state_machines/clean_request_terminal_states_reject_all_transitions
    """
    ctx = setup_basic_scenario()
    # R1 driven to VERIFIED.
    r1 = get_success_data(
        api.create_clean_request(
            create_clean_request_payload(bed_id=ctx["bed"]["id"]), DISPATCHER
        )
    )
    get_success_data(
        api.assign_clean_request(r1["id"], {"staff_id": ctx["tech"]["id"]}, DISPATCHER)
    )
    get_success_data(
        api.start_clean_request(
            r1["id"], __import__("test_helpers").make_technician_headers(ctx["tech"]["id"])
        )
    )
    set_clock("2026-08-01T08:45:00Z")
    get_success_data(
        api.complete_clean_request(
            r1["id"], __import__("test_helpers").make_technician_headers(ctx["tech"]["id"])
        )
    )
    get_success_data(
        api.create_quality_audit(
            {"clean_request_id": r1["id"], "audit_method": "ATP_SWAB", "rlu_reading": 100},
            __import__("test_helpers").make_auditor_headers(ctx["auditor"]["id"]),
        )
    )
    verified = validate_success(api.get_clean_request(r1["id"], ANY))
    assert verified["status"] == "VERIFIED"

    # R2 cancelled from QUEUED.
    bed2 = get_success_data(
        api.create_bed(
            create_bed_payload(unit_id=ctx["unit"]["id"], bed_code="B2"), ADMIN
        )
    )
    r2 = get_success_data(
        api.create_clean_request(
            create_clean_request_payload(bed_id=bed2["id"]), DISPATCHER
        )
    )
    get_success_data(api.cancel_clean_request(r2["id"], DISPATCHER))
    cancelled = validate_success(api.get_clean_request(r2["id"], ANY))
    assert cancelled["status"] == "CANCELLED"

    for req_id in (r1["id"], r2["id"]):
        r_assign = api.assign_clean_request(
            req_id, {"staff_id": ctx["tech"]["id"]}, DISPATCHER
        )
        validate_error(r_assign, ApiErrorId.ERR_REQUEST_ALREADY_TERMINAL)
        r_cancel = api.cancel_clean_request(req_id, DISPATCHER)
        validate_error(r_cancel, ApiErrorId.ERR_REQUEST_ALREADY_TERMINAL)

    v_after = validate_success(api.get_clean_request(r1["id"], ANY))
    assert v_after["status"] == "VERIFIED"
    c_after = validate_success(api.get_clean_request(r2["id"], ANY))
    assert c_after["status"] == "CANCELLED"


def test_clean_request_cancel_from_queued_leaves_clean_slate(api):
    """PRD §3.4: "**Cancelling** from `QUEUED` or `ASSIGNED` moves the request
    to `CANCELLED`, clearing any assignment and its active-count contribution."

    Design: Corner/state_machines/clean_request_cancel_from_queued_leaves_clean_slate
    """
    set_clock(CLOCK_T0800)
    unit = get_success_data(api.create_unit(create_unit_payload(), ADMIN))
    get_success_data(
        api.create_clean_standard(
            {
                "clean_type": "ROUTINE",
                "base_minutes": 45,
                "outbreak_multiplier_bps": 15000,
                "atp_rlu_threshold": 250,
            },
            ADMIN,
        )
    )
    bed = get_success_data(
        api.create_bed(create_bed_payload(unit_id=unit["id"]), ADMIN)
    )
    req = get_success_data(
        api.create_clean_request(create_clean_request_payload(bed_id=bed["id"]), DISPATCHER)
    )

    cancelled = validate_success(api.cancel_clean_request(req["id"], DISPATCHER))
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["assigned_staff_id"] is None
    assert cancelled["supply_reserved"] is False

    bed_after = validate_success(api.get_bed(bed["id"], ANY))
    assert bed_after["bed_status"] == "VACANT_DIRTY"

    follow = validate_success(
        api.create_clean_request(create_clean_request_payload(bed_id=bed["id"]), DISPATCHER),
        201,
    )
    assert follow["status"] == "QUEUED"
    assert follow["bed_id"] == bed["id"]


def test_clean_request_complete_requires_in_progress_state(api):
    """PRD §3.5: "**Completing** a clean requires `IN_PROGRESS`
    (`ERR_REQUEST_NOT_IN_PROGRESS` otherwise, terminal requests again answering
    `ERR_REQUEST_ALREADY_TERMINAL`)."

    Design: Corner/state_machines/clean_request_complete_requires_in_progress_state
    """
    from test_helpers import make_technician_headers

    ctx = setup_basic_scenario()
    req = get_success_data(
        api.create_clean_request(
            create_clean_request_payload(bed_id=ctx["bed"]["id"]), DISPATCHER
        )
    )
    get_success_data(
        api.assign_clean_request(req["id"], {"staff_id": ctx["tech"]["id"]}, DISPATCHER)
    )

    r = api.complete_clean_request(
        req["id"], make_technician_headers(ctx["tech"]["id"])
    )
    validate_error(r, ApiErrorId.ERR_REQUEST_NOT_IN_PROGRESS)

    after = validate_success(api.get_clean_request(req["id"], ANY))
    assert after["status"] == "ASSIGNED"
    assert after["completed_at"] is None

    disinfectant = ctx["supplies"]["DISINFECTANT"]
    item = validate_success(api.get_supply_item(disinfectant["id"], ANY))
    assert item["reserved_quantity"] == 0


def test_clean_request_unassign_requires_assigned_state(api):
    """PRD §3.4: "**Unassigning** returns an `ASSIGNED` request to `QUEUED`,
    clearing `assigned_staff_id` and the planned window, dropping the staff
    member's active count by one in compensation, and incrementing the
    request's `version`; anything not `ASSIGNED` is rejected
    (`ERR_REQUEST_NOT_ASSIGNED`, or `ERR_REQUEST_ALREADY_TERMINAL` when
    terminal)."

    Design: Corner/state_machines/clean_request_unassign_requires_assigned_state
    """
    set_clock(CLOCK_T0800)
    unit = get_success_data(api.create_unit(create_unit_payload(), ADMIN))
    get_success_data(
        api.create_clean_standard(
            {
                "clean_type": "ROUTINE",
                "base_minutes": 45,
                "outbreak_multiplier_bps": 15000,
                "atp_rlu_threshold": 250,
            },
            ADMIN,
        )
    )
    bed = get_success_data(
        api.create_bed(create_bed_payload(unit_id=unit["id"]), ADMIN)
    )
    req = get_success_data(
        api.create_clean_request(create_clean_request_payload(bed_id=bed["id"]), DISPATCHER)
    )
    created_version = req["version"]

    r = api.unassign_clean_request(req["id"], DISPATCHER)
    validate_error(r, ApiErrorId.ERR_REQUEST_NOT_ASSIGNED)

    after = validate_success(api.get_clean_request(req["id"], ANY))
    assert after["status"] == "QUEUED"
    assert after["assigned_staff_id"] is None
    assert after["version"] == created_version


def test_clean_request_reassign_requires_assigned_state(api):
    """PRD §3.4: "**Reassigning** swaps one `ASSIGNED` request to a different
    staff member; it is the OCC-guarded write of §2.7 requiring
    `expected_clean_request_version`, re-runs the certification,
    STAT-eligibility, and buffer checks for the new staff member."
    PRD §2.10: "Sixth, optimistic-concurrency fields must match current
    versions (the 412 family of §2.7). Only then do state and business rules
    run."

    Design: Corner/state_machines/clean_request_reassign_requires_assigned_state
    """
    set_clock(CLOCK_T0800)
    unit = get_success_data(api.create_unit(create_unit_payload(), ADMIN))
    get_success_data(
        api.create_clean_standard(
            {
                "clean_type": "ROUTINE",
                "base_minutes": 45,
                "outbreak_multiplier_bps": 15000,
                "atp_rlu_threshold": 250,
            },
            ADMIN,
        )
    )
    tech = get_success_data(
        api.create_staff(
            {
                "employee_code": "T1",
                "display_name": "Tech One",
                "capabilities": ["CLEAN"],
                "certifications": [],
            },
            ADMIN,
        )
    )
    bed = get_success_data(
        api.create_bed(create_bed_payload(unit_id=unit["id"]), ADMIN)
    )
    req = get_success_data(
        api.create_clean_request(create_clean_request_payload(bed_id=bed["id"]), DISPATCHER)
    )
    created_version = req["version"]

    r = api.reassign_clean_request(
        req["id"],
        {"staff_id": tech["id"], "expected_clean_request_version": created_version},
        DISPATCHER,
    )
    validate_error(r, ApiErrorId.ERR_REQUEST_NOT_ASSIGNED)

    after = validate_success(api.get_clean_request(req["id"], ANY))
    assert after["status"] == "QUEUED"
    assert after["assigned_staff_id"] is None
