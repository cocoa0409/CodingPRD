"""Turnover scheduling (vendor type, buffered overlap), inspection (SoD, state), and the
cross-entity check-in gate on turnover inspection."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    TEST_USERS, ApiErrorId,
    create_turnover_task_payload, create_inspection_payload,
    make_vendor_headers, fixtures,
)

PM = TEST_USERS["property_manager_headers"]


# --------------------------------------------------------------------------- #
# Difficulty: cross-entity check-in gate
# --------------------------------------------------------------------------- #
def _confirmed_booking_with_cleaned_turnover(api):
    fixtures.set_clock(api, "2026-06-01T00:00:00Z")
    listed = fixtures.create_listed_property(api)
    pid = listed["property"]["id"]
    guest = fixtures.create_guest(api)
    booking = fixtures.create_confirmed_booking(api, pid, guest["id"], "2026-06-10T00:00:00Z", "2026-06-13T00:00:00Z")
    cleaner = fixtures.create_vendor(api, "CLEANER")
    turnover = get_success_data(api.create_turnover_task(create_turnover_task_payload(
        booking["id"], pid, cleaner["id"], "2026-06-05T10:00:00Z", "2026-06-05T13:00:00Z"), PM))
    get_success_data(api.start_turnover(turnover["id"], make_vendor_headers(cleaner["id"])))
    get_success_data(api.complete_turnover(turnover["id"], make_vendor_headers(cleaner["id"])))
    fixtures.set_clock(api, "2026-06-12T00:00:00Z")  # clock >= check_in so only the turnover gate can fail
    return booking


def test_checkin_blocked_while_turnover_not_inspected(api):
    """PRD §3.5: "the property's most recent turnover task, if any exists, must be in
    `INSPECTED` status — a check-in against an un-inspected turnover fails with
    `ERR_TURNOVER_NOT_READY`."

    Design: Difficulty/cross_entity_state_dependency/checkin_blocked_until_latest_turnover_inspected
    """
    booking = _confirmed_booking_with_cleaned_turnover(api)
    resp = api.check_in_booking(booking["id"], PM)
    validate_error(resp, ApiErrorId.ERR_TURNOVER_NOT_READY.value)


def test_checkin_blocked_leaves_booking_confirmed(api):
    """PRD §3.5: "Checking in advances `CONFIRMED → CHECKED_IN` and requires two conditions:
    the logical clock must be at or after the booking's `check_in`, and the property's most
    recent turnover task, if any exists, must be in `INSPECTED` status".

    Design: Difficulty/cross_entity_state_dependency/checkin_blocked_until_latest_turnover_inspected
    """
    booking = _confirmed_booking_with_cleaned_turnover(api)
    api.check_in_booking(booking["id"], PM)
    assert get_success_data(api.get_booking(booking["id"], PM))["stay_status"] == "CONFIRMED"


# --------------------------------------------------------------------------- #
# Difficulty: vendor buffered turnover overlap
# --------------------------------------------------------------------------- #
def _vendor_with_scheduled_turnover(api):
    fixtures.set_clock(api, "2026-06-01T00:00:00Z")
    listed = fixtures.create_listed_property(api)
    pid = listed["property"]["id"]
    guest = fixtures.create_guest(api)
    booking = fixtures.create_booking(api, pid, guest["id"], "2026-07-01T00:00:00Z", "2026-07-04T00:00:00Z")
    cleaner = fixtures.create_vendor(api, "CLEANER")
    get_success_data(api.create_turnover_task(create_turnover_task_payload(
        booking["id"], pid, cleaner["id"], "2026-07-04T10:00:00Z", "2026-07-04T13:00:00Z"), PM))
    return pid, booking["id"], cleaner["id"]


def test_turnover_within_vendor_buffer_rejected(api):
    """PRD §3.6: "expands each such task's window by two hours (120 minutes) on both sides,
    and treats the requested window as conflicting if it intersects any buffered window under
    closed-interval comparison — that is, the requested start is at or before the buffered end
    and the buffered start is at or before the requested end. Any conflict is rejected with
    `ERR_VENDOR_UNAVAILABLE`."

    Design: Difficulty/resource_temporal_overlap/vendor_turnover_buffer_overlap_rejected
    """
    pid, booking_id, cleaner_id = _vendor_with_scheduled_turnover(api)
    # existing [10:00,13:00] buffered to [08:00,15:00]; requested 14:00 <= 15:00 => conflict
    resp = api.create_turnover_task(create_turnover_task_payload(
        booking_id, pid, cleaner_id, "2026-07-04T14:00:00Z", "2026-07-04T16:00:00Z"), PM)
    validate_error(resp, ApiErrorId.ERR_VENDOR_UNAVAILABLE.value)


def test_turnover_outside_vendor_buffer_allowed(api):
    """PRD §3.6: "for the same assigned vendor, it examines every other turnover in a
    non-terminal-ish status ... expands each such task's window by two hours (120 minutes) on
    both sides, and treats the requested window as conflicting if it intersects any buffered
    window under closed-interval comparison".

    Design: Difficulty/resource_temporal_overlap/vendor_turnover_buffer_overlap_rejected
    """
    pid, booking_id, cleaner_id = _vendor_with_scheduled_turnover(api)
    # existing buffered end is 15:00; requested 20:00 > 15:00 => no conflict, schedules fine
    resp = api.create_turnover_task(create_turnover_task_payload(
        booking_id, pid, cleaner_id, "2026-07-04T20:00:00Z", "2026-07-04T22:00:00Z"), PM)
    data = validate_success(resp, 201)
    assert data["status"] == "SCHEDULED"


# --------------------------------------------------------------------------- #
# Corner: inspection state machine and validations
# --------------------------------------------------------------------------- #
def test_inspection_pass_sets_turnover_inspected(api):
    """PRD §3.6: "A `PASS` result drives the turnover `CLEANED → INSPECTED` (unblocking the
    next check-in)".
    PRD §3.6: "An inspection is created in `COMPLETED`".

    Design: Corner/state_machines/inspection_pass_sets_turnover_inspected
    """
    ctx = fixtures.setup_cleaned_turnover(api)
    resp = api.create_inspection(create_inspection_payload(
        ctx["turnover"]["id"], ctx["inspector"]["id"], "PASS"), PM)
    inspection = validate_success(resp, 201)
    assert inspection["status"] == "COMPLETED"
    assert get_success_data(api.get_turnover_task(ctx["turnover"]["id"], PM))["status"] == "INSPECTED"


def test_inspection_sod_inspector_equals_cleaner_rejected(api):
    """PRD §3.6: "enforces segregation of duties: the `inspector_vendor_id` must differ from
    the turnover's `assigned_vendor_id`, since a crew may not inspect its own cleaning — a
    self-inspection is rejected with `ERR_SOD_INSPECTOR_IS_CLEANER`."

    Design: Corner/validations/inspection_sod_inspector_equals_cleaner_rejected
    """
    ctx = fixtures.setup_cleaned_turnover(api)
    resp = api.create_inspection(create_inspection_payload(
        ctx["turnover"]["id"], ctx["cleaner"]["id"], "PASS"), PM)
    validate_error(resp, ApiErrorId.ERR_SOD_INSPECTOR_IS_CLEANER.value)


def test_inspection_on_uncleaned_turnover_rejected(api):
    """PRD §3.6: "The inspection requires the turnover to be in `CLEANED` (else
    `ERR_TURNOVER_NOT_CLEANED`)".

    Design: Corner/validations/inspection_on_uncleaned_turnover_rejected
    """
    fixtures.set_clock(api, "2026-06-01T00:00:00Z")
    listed = fixtures.create_listed_property(api)
    pid = listed["property"]["id"]
    guest = fixtures.create_guest(api)
    booking = fixtures.create_booking(api, pid, guest["id"], "2026-07-01T00:00:00Z", "2026-07-04T00:00:00Z")
    cleaner = fixtures.create_vendor(api, "CLEANER")
    inspector = fixtures.create_vendor(api, "INSPECTOR")
    turnover = get_success_data(api.create_turnover_task(create_turnover_task_payload(
        booking["id"], pid, cleaner["id"], "2026-07-04T10:00:00Z", "2026-07-04T13:00:00Z"), PM))
    # turnover is SCHEDULED (never started/cleaned); inspector differs from cleaner
    resp = api.create_inspection(create_inspection_payload(turnover["id"], inspector["id"], "PASS"), PM)
    validate_error(resp, ApiErrorId.ERR_TURNOVER_NOT_CLEANED.value)


def test_turnover_assigned_non_cleaner_vendor_rejected(api):
    """PRD §3.6: "The assigned vendor must be of `vendor_type` `CLEANER`, else
    `ERR_VENDOR_NOT_CLEANER`."

    Design: Corner/validations/turnover_assigned_non_cleaner_vendor_rejected
    """
    fixtures.set_clock(api, "2026-06-01T00:00:00Z")
    listed = fixtures.create_listed_property(api)
    pid = listed["property"]["id"]
    guest = fixtures.create_guest(api)
    booking = fixtures.create_booking(api, pid, guest["id"], "2026-07-01T00:00:00Z", "2026-07-04T00:00:00Z")
    vendor = fixtures.create_vendor(api, "MAINTENANCE")
    resp = api.create_turnover_task(create_turnover_task_payload(
        booking["id"], pid, vendor["id"], "2026-07-04T10:00:00Z", "2026-07-04T13:00:00Z"), PM)
    validate_error(resp, ApiErrorId.ERR_VENDOR_NOT_CLEANER.value)
