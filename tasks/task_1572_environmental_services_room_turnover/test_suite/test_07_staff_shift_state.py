"""StaffMember shift machine claims."""
from test_helpers import (
    ApiErrorId,
    CLOCK_T0800,
    api_client,
    create_bed_payload,
    create_clean_request_payload,
    create_unit_payload,
    get_success_data,
    make_technician_headers,
    set_clock,
    setup_basic_scenario,
    validate_error,
    validate_success,
    TEST_USERS,
)
from test_helpers.fixtures import (
    create_standard,
    create_technician,
    seed_supplies,
)

ADMIN = TEST_USERS["admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]
ANY = TEST_USERS["any_headers"]


def test_staff_shift_invalid_transitions_rejected(api):
    """PRD §3.4: "Clocking in requires `OFF_SHIFT` (a second clock-in is
    `ERR_STAFF_ALREADY_ON_SHIFT`) and stamps `last_clock_in_at`. Starting a
    break requires `ON_SHIFT` (`ERR_STAFF_NOT_ON_SHIFT`) ... Ending a break
    requires `ON_BREAK` (`ERR_STAFF_NOT_ON_BREAK`)."

    Design: Corner/state_machines/staff_shift_invalid_transitions_rejected
    """
    set_clock(CLOCK_T0800)
    tech = create_technician("T1")
    tid = tech["id"]
    th = make_technician_headers(tid)

    # break-start from OFF_SHIFT
    r = api.break_start_staff(tid, th)
    validate_error(r, ApiErrorId.ERR_STAFF_NOT_ON_SHIFT)

    # clock-in OK, then double clock-in
    get_success_data(api.clock_in_staff(tid, th))
    r = api.clock_in_staff(tid, th)
    validate_error(r, ApiErrorId.ERR_STAFF_ALREADY_ON_SHIFT)

    # break-end from ON_SHIFT
    r = api.break_end_staff(tid, th)
    validate_error(r, ApiErrorId.ERR_STAFF_NOT_ON_BREAK)

    # break-start OK, then break-start again from ON_BREAK
    get_success_data(api.break_start_staff(tid, th))
    r = api.break_start_staff(tid, th)
    validate_error(r, ApiErrorId.ERR_STAFF_NOT_ON_SHIFT)

    # clock-in from ON_BREAK
    r = api.clock_in_staff(tid, th)
    validate_error(r, ApiErrorId.ERR_STAFF_ALREADY_ON_SHIFT)

    # Valid path: break-end then clock-out.
    get_success_data(api.break_end_staff(tid, th))
    out = get_success_data(api.clock_out_staff(tid, th))
    assert out["shift_status"] == "OFF_SHIFT"


def test_staff_clock_out_and_break_start_blocked_by_active_cleans(api):
    """PRD §3.4: "Starting a break requires `ON_SHIFT` (`ERR_STAFF_NOT_ON_SHIFT`)
    and is refused while the staff member holds an `IN_PROGRESS` clean
    (`ERR_STAFF_HAS_ACTIVE_CLEANS`)."
    PRD §3.4: "Clocking out from `ON_SHIFT` or `ON_BREAK` is refused while the
    staff member holds any `ASSIGNED` or `IN_PROGRESS` clean
    (`ERR_STAFF_HAS_ACTIVE_CLEANS`)."

    Design: Corner/state_machines/staff_clock_out_and_break_start_blocked_by_active_cleans
    """
    ctx = setup_basic_scenario()
    tech = ctx["tech"]
    th = make_technician_headers(tech["id"])

    req = get_success_data(
        api.create_clean_request(
            create_clean_request_payload(bed_id=ctx["bed"]["id"]), DISPATCHER
        )
    )
    get_success_data(
        api.assign_clean_request(req["id"], {"staff_id": tech["id"]}, DISPATCHER)
    )

    # ASSIGNED does not block break-start, but blocks clock-out.
    on_break = get_success_data(api.break_start_staff(tech["id"], th))
    assert on_break["shift_status"] == "ON_BREAK"

    r = api.clock_out_staff(tech["id"], th)
    validate_error(r, ApiErrorId.ERR_STAFF_HAS_ACTIVE_CLEANS)

    get_success_data(api.break_end_staff(tech["id"], th))
    get_success_data(api.start_clean_request(req["id"], th))

    r = api.break_start_staff(tech["id"], th)
    validate_error(r, ApiErrorId.ERR_STAFF_HAS_ACTIVE_CLEANS)
    r = api.clock_out_staff(tech["id"], th)
    validate_error(r, ApiErrorId.ERR_STAFF_HAS_ACTIVE_CLEANS)

    set_clock("2026-08-01T08:45:00Z")
    get_success_data(api.complete_clean_request(req["id"], th))
    out = get_success_data(api.clock_out_staff(tech["id"], th))
    assert out["shift_status"] == "OFF_SHIFT"


def test_staff_shift_seconds_accrue_at_boundaries_excluding_breaks(api):
    """PRD §3.4: "Open spans are not counted until they close, so
    `shift_seconds_today` moves only at break-start, break-end, and clock-out
    boundaries."
    PRD §3.4: "clocking out from `ON_SHIFT` adds the closing span's seconds to
    `shift_seconds_today`, while break spans never accrue."

    Design: Corner/state_machines/staff_shift_seconds_accrue_at_boundaries_excluding_breaks
    """
    set_clock(CLOCK_T0800)
    tech = create_technician("T1")
    tid = tech["id"]
    th = make_technician_headers(tid)

    get_success_data(api.clock_in_staff(tid, th))

    # One hour into an OPEN span: nothing accrued yet.
    set_clock("2026-08-01T09:00:00Z")
    open_read = get_success_data(api.get_staff(tid, ANY))
    assert open_read["shift_seconds_today"] == 0

    set_clock("2026-08-01T10:00:00Z")
    at_break = get_success_data(api.break_start_staff(tid, th))
    assert at_break["shift_seconds_today"] == 7200

    set_clock("2026-08-01T10:30:00Z")
    at_bend = get_success_data(api.break_end_staff(tid, th))
    assert at_bend["shift_seconds_today"] == 7200

    set_clock("2026-08-01T12:00:00Z")
    at_out = get_success_data(api.clock_out_staff(tid, th))
    assert at_out["shift_seconds_today"] == 12600
