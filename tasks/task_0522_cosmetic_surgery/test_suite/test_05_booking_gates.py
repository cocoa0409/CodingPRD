"""Surgery-booking gates: clearance safety, OR half-open overlap, surgeon turnaround
buffer, future-start, time-range, and the optimistic-concurrency version check."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS, PROC_A,
    create_procedure, create_accepted_quote,
    create_surgery_booking_payload,
)

FRONT = TEST_USERS["front_desk_headers"]


def _book(api, quote, **overrides):
    return api.create_surgery_booking(
        create_surgery_booking_payload(quote["id"], quote["version"], **overrides), FRONT)


def test_surgery_in_past_rejected(api):
    """PRD §3.6: "The scheduled_start must be strictly in the future relative to the
    current logical clock, otherwise ERR_SURGERY_IN_PAST."

    Design: Corner/validations/error_surgery_in_past_on_book
    """
    procA = create_procedure(**PROC_A)
    quote, _c, _p, _l = create_accepted_quote([procA["id"]], deposit_cents=170000)
    # clock at default 2026-05-01; start 2026-04-01 is in the past
    resp = _book(api, quote, scheduled_start="2026-04-01T00:00:00Z",
                 scheduled_end="2026-04-01T03:00:00Z")
    validate_error(resp, ApiErrorId.ERR_SURGERY_IN_PAST, 409)


def test_invalid_time_range_rejected(api):
    """PRD §3.6: "The scheduled_end must be strictly after scheduled_start, otherwise
    ERR_INVALID_TIME_RANGE."

    Design: Corner/validations/error_invalid_time_range_on_book
    """
    procA = create_procedure(**PROC_A)
    quote, _c, _p, _l = create_accepted_quote([procA["id"]], deposit_cents=170000)
    resp = _book(api, quote, scheduled_start="2026-08-01T03:00:00Z",
                 scheduled_end="2026-08-01T03:00:00Z")
    validate_error(resp, ApiErrorId.ERR_INVALID_TIME_RANGE, 400)


def test_booking_missing_clearance_rejected(api):
    """PRD §3.6: "the patient must have an ISSUED clearance whose cleared is true,
    otherwise ERR_CLEARANCE_MISSING."

    Design: Difficulty/priority_pair_validation_conflict/priority_clearance_missing_before_or_double_booked
    """
    procA = create_procedure(**PROC_A)
    # uncleared patient (clearance=False), quote still accepted
    quote, _c, _p, _l = create_accepted_quote(
        [procA["id"]], deposit_cents=170000, clearance=False, surgeon_user_id="surgeon-2")
    resp = _book(api, quote, surgeon_user_id="surgeon-2", or_room="OR1",
                 scheduled_start="2026-08-01T01:00:00Z",
                 scheduled_end="2026-08-01T02:00:00Z")
    validate_error(resp, ApiErrorId.ERR_CLEARANCE_MISSING, 409)


def test_clearance_missing_precedes_or_double_booked(api):
    """PRD §3.6: "then for booking the clearance-present safety check, then the
    operating-room overlap check ... A single request that trips more than one of these
    surfaces the earliest one in this ordering."
    PRD §3.6: "the patient must have an ISSUED clearance whose cleared is true,
    otherwise ERR_CLEARANCE_MISSING."

    Design: Difficulty/priority_pair_validation_conflict/priority_clearance_missing_before_or_double_booked
    """
    procA = create_procedure(**PROC_A)
    # First, a cleared booking occupies OR1 00:00-03:00.
    q_cleared, _c, _p, _l = create_accepted_quote(
        [procA["id"]], deposit_cents=170000, clearance=True, surgeon_user_id="surgeon-1")
    get_success_data(_book(api, q_cleared, surgeon_user_id="surgeon-1", or_room="OR1",
                           scheduled_start="2026-08-01T00:00:00Z",
                           scheduled_end="2026-08-01T03:00:00Z"))
    # Second patient: NO clearance, and booking overlaps OR1 in the same window.
    q_uncleared, _c2, _p2, _l2 = create_accepted_quote(
        [procA["id"]], deposit_cents=170000, clearance=False, surgeon_user_id="surgeon-2")
    resp = _book(api, q_uncleared, surgeon_user_id="surgeon-2", or_room="OR1",
                 scheduled_start="2026-08-01T01:00:00Z",
                 scheduled_end="2026-08-01T02:00:00Z")
    # Both clearance-missing and OR-double-booked apply; clearance precedes overlap.
    validate_error(resp, ApiErrorId.ERR_CLEARANCE_MISSING, 409)


def test_or_touching_endpoints_allowed(api):
    """PRD §3.6: "the interval is treated as half-open ... so two bookings that merely
    touch at an endpoint (one ending exactly when the next begins) do not conflict."

    Design: Difficulty/resource_temporal_overlap/overlap_or_room_half_open_touching_allowed
    """
    procA = create_procedure(**PROC_A)
    q1, _c, _p, _l = create_accepted_quote(
        [procA["id"]], deposit_cents=170000, surgeon_user_id="surgeon-1")
    get_success_data(_book(api, q1, surgeon_user_id="surgeon-1", or_room="OR1",
                           scheduled_start="2026-08-01T00:00:00Z",
                           scheduled_end="2026-08-01T03:00:00Z"))
    # Distinct surgeon so the surgeon-buffer rule does not interfere; touching OR1 at 03:00.
    q2, _c2, _p2, _l2 = create_accepted_quote(
        [procA["id"]], deposit_cents=170000, surgeon_user_id="surgeon-2")
    resp = _book(api, q2, surgeon_user_id="surgeon-2", or_room="OR1",
                 scheduled_start="2026-08-01T03:00:00Z",
                 scheduled_end="2026-08-01T05:00:00Z")
    data = validate_success(resp, 201)
    assert data["status"] == "SCHEDULED"


def test_or_overlapping_interval_rejected(api):
    """PRD §3.6: "The requested operating-room interval must not overlap an existing
    SCHEDULED booking in the same or_room; the interval is treated as half-open, meaning
    two intervals conflict when one starts strictly before the other ends and the second
    starts strictly before the first ends ... A conflict here is ERR_OR_DOUBLE_BOOKED."

    Design: Difficulty/resource_temporal_overlap/overlap_or_room_half_open_touching_allowed
    """
    procA = create_procedure(**PROC_A)
    q1, _c, _p, _l = create_accepted_quote(
        [procA["id"]], deposit_cents=170000, surgeon_user_id="surgeon-1")
    get_success_data(_book(api, q1, surgeon_user_id="surgeon-1", or_room="OR1",
                           scheduled_start="2026-08-01T00:00:00Z",
                           scheduled_end="2026-08-01T03:00:00Z"))
    q2, _c2, _p2, _l2 = create_accepted_quote(
        [procA["id"]], deposit_cents=170000, surgeon_user_id="surgeon-2")
    resp = _book(api, q2, surgeon_user_id="surgeon-2", or_room="OR1",
                 scheduled_start="2026-08-01T01:00:00Z",
                 scheduled_end="2026-08-01T02:00:00Z")
    validate_error(resp, ApiErrorId.ERR_OR_DOUBLE_BOOKED, 409)


def test_surgeon_buffer_touching_conflicts(api):
    """PRD §3.6: "a new booking must leave a 60-minute turnaround buffer around any
    existing SCHEDULED booking with the same surgeon_user_id ... so unlike the
    operating-room rule, exactly touching endpoints do conflict here, because the buffer
    is greater than zero. A surgeon conflict is ERR_SURGEON_BUFFER_CONFLICT."

    Design: Difficulty/resource_temporal_overlap/overlap_surgeon_buffer_touching_conflicts
    """
    procA = create_procedure(**PROC_A)
    q1, _c, _p, _l = create_accepted_quote(
        [procA["id"]], deposit_cents=170000, surgeon_user_id="surgeon-1")
    get_success_data(_book(api, q1, surgeon_user_id="surgeon-1", or_room="OR1",
                           scheduled_start="2026-08-01T00:00:00Z",
                           scheduled_end="2026-08-01T03:00:00Z"))
    # Same surgeon, different OR, starting exactly at 03:00 -> within 60-min buffer.
    q2, _c2, _p2, _l2 = create_accepted_quote(
        [procA["id"]], deposit_cents=170000, surgeon_user_id="surgeon-1")
    resp = _book(api, q2, surgeon_user_id="surgeon-1", or_room="OR2",
                 scheduled_start="2026-08-01T03:00:00Z",
                 scheduled_end="2026-08-01T05:00:00Z")
    validate_error(resp, ApiErrorId.ERR_SURGEON_BUFFER_CONFLICT, 409)


def test_surgeon_buffer_beyond_60_minutes_allowed(api):
    """PRD §3.6: "a new booking must leave a 60-minute turnaround buffer around any
    existing SCHEDULED booking with the same surgeon_user_id. Two bookings conflict on
    this rule when one starts strictly before the other's end extended forward by 60
    minutes and the other starts strictly before the first's end extended forward by 60
    minutes."

    Design: Difficulty/resource_temporal_overlap/overlap_surgeon_buffer_touching_conflicts
    """
    procA = create_procedure(**PROC_A)
    q1, _c, _p, _l = create_accepted_quote(
        [procA["id"]], deposit_cents=170000, surgeon_user_id="surgeon-1")
    get_success_data(_book(api, q1, surgeon_user_id="surgeon-1", or_room="OR1",
                           scheduled_start="2026-08-01T00:00:00Z",
                           scheduled_end="2026-08-01T03:00:00Z"))
    # Same surgeon, start at 04:01 -> strictly beyond the 03:00 end + 60 min buffer.
    q2, _c2, _p2, _l2 = create_accepted_quote(
        [procA["id"]], deposit_cents=170000, surgeon_user_id="surgeon-1")
    resp = _book(api, q2, surgeon_user_id="surgeon-1", or_room="OR2",
                 scheduled_start="2026-08-01T04:01:00Z",
                 scheduled_end="2026-08-01T06:00:00Z")
    data = validate_success(resp, 201)
    assert data["status"] == "SCHEDULED"


def test_stale_quote_version_rejected(api):
    """PRD §2.7: "If that value does not equal the quote's current version — for instance
    because another writer has since recorded a deposit or bound a financing application,
    each of which increments the quote's version — the booking is rejected with
    ERR_STALE_VERSION (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_quote_version_on_booking
    """
    procA = create_procedure(**PROC_A)
    quote, _c, _p, _l = create_accepted_quote([procA["id"]], deposit_cents=170000)
    stale_version = quote["version"]
    # A further deposit bumps the quote version, making stale_version out of date.
    get_success_data(api.record_deposit(quote["id"], {"amount_cents": 1000},
                                        TEST_USERS["billing_headers"]))
    resp = api.create_surgery_booking(
        create_surgery_booking_payload(quote["id"], stale_version), FRONT)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)


def test_booking_current_version_succeeds_and_bumps_quote_version(api):
    """PRD §2.7: "The create-booking request therefore requires a non-optional
    expected_quote_package_version field carrying the client's last observed version of
    the referenced QuotePackage."
    PRD §3.3: "increments the quote's version" [on each mutation of the quote].

    Design: Corner/cross_cutting_complexity_layers/occ_correct_version_succeeds_and_bumps
    """
    procA = create_procedure(**PROC_A)
    quote, _c, _p, _l = create_accepted_quote([procA["id"]], deposit_cents=170000)
    live_version = quote["version"]
    booking = get_success_data(api.create_surgery_booking(
        create_surgery_booking_payload(quote["id"], live_version), FRONT))
    assert booking["status"] == "SCHEDULED"
    quote_after = get_success_data(api.get_quote_package(quote["id"], FRONT))
    assert quote_after["version"] == live_version + 1


def test_surgery_complete_before_start_rejected(api):
    """PRD §3.7: "Completion requires the booking to be SCHEDULED (otherwise
    ERR_INVALID_STATE) and requires the current logical clock to have reached or passed
    scheduled_start — that is, the clock must be at or after the scheduled start —
    otherwise ERR_SURGERY_NOT_STARTED."

    Design: Corner/state_machines/surgery_complete_before_start_returns_not_started
    """
    procA = create_procedure(**PROC_A)
    quote, _c, _p, _l = create_accepted_quote([procA["id"]], deposit_cents=170000)
    booking = get_success_data(api.create_surgery_booking(
        create_surgery_booking_payload(quote["id"], quote["version"]), FRONT))
    # clock at default 2026-05-01, before scheduled_start 2026-08-01
    resp = api.complete_surgery_booking(
        booking["id"], TEST_USERS["surgeon_headers"])
    validate_error(resp, ApiErrorId.ERR_SURGERY_NOT_STARTED, 409)
