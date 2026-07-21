"""Booking guard checks: validation precedence, boundaries, overlaps, and corner rejects."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    make_approved_trip, make_credit_from_cancelled_nonref,
    make_policy, make_traveler, make_vendor, make_rate, make_trip, submit_trip,
    book, cancel_booking, trip_version, set_clock, run_sweep,
    make_group_booking, confirm_group_booking,
    make_traveler_headers,
    create_booking_payload, create_group_booking_payload, exchange_booking_payload,
    TEST_USERS,
)
from test_helpers.constants import CLOCK_DEFAULT

MGR = TEST_USERS["travel_manager_headers"]


# ─── Priority pair: advance-purchase (9) beats rate-unavailable (11) ──
def _expired_rate_and_too_soon_booking(api):
    """Auto-approved trip; rate swept to EXPIRED; booking both references it and departs
    inside the advance-purchase window."""
    set_clock(CLOCK_DEFAULT)
    policy = make_policy()
    trav = make_traveler(policy["id"])
    ven = make_vendor()
    rate = make_rate(ven["id"], valid_to="2026-07-10T00:00:00Z")
    trip = make_trip(trav["id"], depart_date="2026-07-20T09:00:00Z",
                     return_date="2026-07-25T09:00:00Z", market_estimate_cents=50000)
    trip = submit_trip(trip["id"], trav["id"])  # NONE -> APPROVED
    v = trip["version"]
    set_clock("2026-07-15T00:00:00Z")
    run_sweep()  # rate -> EXPIRED
    return api.create_booking(
        create_booking_payload(trip["id"], ven["id"], v,
                               negotiated_rate_id=rate["id"], segment_type="AIR",
                               fare_basis="NONREFUNDABLE", fare_cents=250000,
                               depart_datetime="2026-07-20T09:00:00Z",
                               return_datetime="2026-07-20T20:00:00Z"),
        make_traveler_headers(trav["id"]))


def test_advance_purchase_beats_rate_unavailable(api):
    """PRD §2.7: "wherever two of these do coexist the lower-numbered one is evaluated
    first."
    PRD §2.7: "(9) the advance-purchase window (`ERR_ADVANCE_PURCHASE_VIOLATION`); ... (11)
    negotiated-rate and vendor availability (`ERR_RATE_UNAVAILABLE`)."

    Design: Difficulty/priority_pair_validation_conflict/advance_purchase_beats_rate_unavailable
    """
    res = _expired_rate_and_too_soon_booking(api)
    validate_error(res, ApiErrorId.ERR_ADVANCE_PURCHASE_VIOLATION)


def test_dual_failure_does_not_report_the_lower_priority_rate_error(api):
    """PRD §2.7: "When several checks guard the same endpoint, they are evaluated in a
    fixed priority order, and the first failing check determines the error returned."

    Design: Difficulty/priority_pair_validation_conflict/advance_purchase_beats_rate_unavailable
    """
    res = _expired_rate_and_too_soon_booking(api)
    body = res.json()
    assert body["data"]["error_id"] == "ERR_ADVANCE_PURCHASE_VIOLATION", (
        f"lower-priority-number temporal check must pre-empt, got {body['data']['error_id']}"
    )
    assert body["data"]["error_id"] != "ERR_RATE_UNAVAILABLE"


# ─── Priority pair: invalid-state (5) beats self-approval (7) ──
def _self_approve_draft_trip(api):
    policy = make_policy()
    trav = make_traveler(policy["id"], grade="MANAGER")
    trip = make_trip(trav["id"], market_estimate_cents=200000)  # left DRAFT
    from test_helpers import make_approver_headers
    return api.approve_trip_request(trip["id"], make_approver_headers(trav["id"]))


def test_invalid_state_beats_self_approval(api):
    """PRD §2.7: "(5) the target resource being in a state that permits the requested
    transition (`ERR_INVALID_STATE`); ... (7) segregation of duties on approvals and
    rejections (`ERR_SELF_APPROVAL`)."

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_self_approval
    """
    res = _self_approve_draft_trip(api)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)


def test_draft_self_approval_reports_state_not_sod(api):
    """PRD §2.7: "the first failing check determines the error returned."

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_self_approval
    """
    res = _self_approve_draft_trip(api)
    body = res.json()
    assert body["data"]["error_id"] == "ERR_INVALID_STATE", (
        f"state check (priority 5) must pre-empt SoD (priority 7), got {body['data']['error_id']}"
    )
    assert body["data"]["error_id"] != "ERR_SELF_APPROVAL"


# ─── Boundary: advance-purchase exact threshold ───────
def test_advance_purchase_exact_boundary_accepted(api):
    """PRD §3.3: "The segment's `depart_datetime` must be at least `advance_purchase_days`
    whole days after the current clock; a departure sooner than that window is refused with
    `ERR_ADVANCE_PURCHASE_VIOLATION`."

    Design: Difficulty/boundary_precision_check/advance_purchase_exact_boundary_accepted
    """
    ctx = make_approved_trip(market_estimate=50000)  # clock 2026-07-01, advance 14 days
    trip, trav, ven = ctx["trip"], ctx["traveler"], ctx["vendor"]
    res = api.create_booking(
        create_booking_payload(trip["id"], ven["id"], trip["version"], segment_type="AIR",
                               fare_basis="REFUNDABLE", fare_cents=250000,
                               depart_datetime="2026-07-15T00:00:00Z",
                               return_datetime="2026-07-15T20:00:00Z"),
        make_traveler_headers(trav["id"]))
    booking = validate_success(res, 201)
    assert booking["status"] == "TICKETED", f"exactly-14-days departure should be accepted, got {booking['status']}"


def test_advance_purchase_one_day_short_rejected(api):
    """PRD §3.3: "a departure sooner than that window is refused with
    `ERR_ADVANCE_PURCHASE_VIOLATION`."

    Design: Difficulty/boundary_precision_check/advance_purchase_exact_boundary_accepted
    """
    ctx = make_approved_trip(market_estimate=50000)
    trip, trav, ven = ctx["trip"], ctx["traveler"], ctx["vendor"]
    res = api.create_booking(
        create_booking_payload(trip["id"], ven["id"], trip["version"], segment_type="AIR",
                               fare_basis="REFUNDABLE", fare_cents=250000,
                               depart_datetime="2026-07-14T00:00:00Z",
                               return_datetime="2026-07-14T20:00:00Z"),
        make_traveler_headers(trav["id"]))
    validate_error(res, ApiErrorId.ERR_ADVANCE_PURCHASE_VIOLATION)


# ─── Boundary: group block_size minimum ───────────────
def _hotel_vendor_with_organizer():
    policy = make_policy()
    organizer = make_traveler(policy["id"], grade="MANAGER")
    vendor = make_vendor(vendor_type="HOTEL", capacity=10)
    return organizer, vendor


def test_group_block_size_zero_rejected(api):
    """PRD §3.6: "A group booking is created with the `vendor_id`, the
    `organizer_traveler_id`, the `block_size` (at least 1), and the block's `start_date`
    and `end_date`."

    Design: Difficulty/boundary_precision_check/group_block_size_zero_rejected
    """
    organizer, vendor = _hotel_vendor_with_organizer()
    res = api.create_group_booking(
        create_group_booking_payload(vendor["id"], organizer["id"], block_size=0), MGR)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)


def test_group_block_size_one_accepted(api):
    """PRD §3.6: "the `block_size` (at least 1)".
    PRD §3.6: "Its `confirmed_count` starts at 0 and its `status` starts at `HELD`."

    Design: Difficulty/boundary_precision_check/group_block_size_zero_rejected
    """
    organizer, vendor = _hotel_vendor_with_organizer()
    res = api.create_group_booking(
        create_group_booking_payload(vendor["id"], organizer["id"], block_size=1), MGR)
    gb = validate_success(res, 201)
    assert gb["status"] == "HELD" and gb["block_size"] == 1


# ─── Resource overlap: traveler double-booking (half-open) ──
def test_traveler_overlapping_segment_rejected(api):
    """PRD §3.3: "intervals are treated as half-open from `depart_datetime` up to but not
    including `return_datetime`, so two segments that merely touch end-to-start (one ending
    exactly when the next begins) are permitted, but any true overlap is refused with
    `ERR_TRAVELER_DOUBLE_BOOKED`."

    Design: Difficulty/resource_temporal_overlap/traveler_double_booked_half_open_overlap
    """
    ctx = make_approved_trip(market_estimate=50000,
                             trip_overrides={"return_date": "2026-08-20T09:00:00Z"})
    trip, trav, ven = ctx["trip"], ctx["traveler"], ctx["vendor"]
    book(trip["id"], trav["id"], trip["version"], vendor_id=ven["id"], segment_type="AIR",
         fare_basis="REFUNDABLE", fare_cents=250000,
         depart_datetime="2026-08-01T09:00:00Z", return_datetime="2026-08-01T18:00:00Z")
    v2 = trip_version(trip["id"], trav["id"])
    res = api.create_booking(
        create_booking_payload(trip["id"], ven["id"], v2, segment_type="AIR",
                               fare_basis="REFUNDABLE", fare_cents=250000,
                               depart_datetime="2026-08-01T15:00:00Z",
                               return_datetime="2026-08-01T20:00:00Z"),
        make_traveler_headers(trav["id"]))
    validate_error(res, ApiErrorId.ERR_TRAVELER_DOUBLE_BOOKED)


def test_traveler_back_to_back_segments_allowed(api):
    """PRD §3.3: "two segments that merely touch end-to-start (one ending exactly when the
    next begins) are permitted."

    Design: Difficulty/resource_temporal_overlap/traveler_double_booked_half_open_overlap
    """
    ctx = make_approved_trip(market_estimate=50000,
                             trip_overrides={"return_date": "2026-08-20T09:00:00Z"})
    trip, trav, ven = ctx["trip"], ctx["traveler"], ctx["vendor"]
    book(trip["id"], trav["id"], trip["version"], vendor_id=ven["id"], segment_type="AIR",
         fare_basis="REFUNDABLE", fare_cents=250000,
         depart_datetime="2026-08-01T09:00:00Z", return_datetime="2026-08-01T18:00:00Z")
    v2 = trip_version(trip["id"], trav["id"])
    res = api.create_booking(
        create_booking_payload(trip["id"], ven["id"], v2, segment_type="AIR",
                               fare_basis="REFUNDABLE", fare_cents=250000,
                               depart_datetime="2026-08-01T18:00:00Z",
                               return_datetime="2026-08-01T22:00:00Z"),
        make_traveler_headers(trav["id"]))
    booking = validate_success(res, 201)
    assert booking["status"] == "TICKETED", f"touching segment should be allowed, got {booking['status']}"


# ─── Resource overlap: group aggregate capacity ───────
def _confirmed_block_six():
    organizer, vendor = _hotel_vendor_with_organizer()
    gb1 = make_group_booking(vendor["id"], organizer["id"], block_size=6,
                             start_date="2026-08-01T00:00:00Z", end_date="2026-08-05T00:00:00Z")
    confirm_group_booking(gb1["id"], 6)
    return organizer, vendor


def test_group_overlapping_block_exceeds_capacity(api):
    """PRD §3.6: "The occupied capacity is the sum of `block_size` across all blocks on the
    vendor that are in `HELD` or `CONFIRMED` and overlap the new block. If that occupied
    total plus the new block's `block_size` exceeds the vendor's `capacity`, the hold is
    refused with `ERR_VENDOR_CAPACITY_EXCEEDED`."

    Design: Difficulty/resource_temporal_overlap/group_block_aggregate_capacity_overlap
    """
    organizer, vendor = _confirmed_block_six()
    res = api.create_group_booking(
        create_group_booking_payload(vendor["id"], organizer["id"], block_size=5,
                                     start_date="2026-08-03T00:00:00Z",
                                     end_date="2026-08-07T00:00:00Z"), MGR)
    validate_error(res, ApiErrorId.ERR_VENDOR_CAPACITY_EXCEEDED)


def test_group_nonoverlapping_block_allowed(api):
    """PRD §3.6: "Two blocks on the same vendor overlap when they share any point on their
    closed intervals — that is, when the first's `start_date` is at or before the second's
    `end_date` and the second's `start_date` is at or before the first's `end_date`."

    Design: Difficulty/resource_temporal_overlap/group_block_aggregate_capacity_overlap
    """
    organizer, vendor = _confirmed_block_six()
    res = api.create_group_booking(
        create_group_booking_payload(vendor["id"], organizer["id"], block_size=5,
                                     start_date="2026-08-10T00:00:00Z",
                                     end_date="2026-08-15T00:00:00Z"), MGR)
    gb = validate_success(res, 201)
    assert gb["status"] == "HELD", f"a non-overlapping block should be held, got {gb['status']}"


# ─── Corner: hotel nightly cap ────────────────────────
def test_hotel_over_nightly_cap_rejected(api):
    """PRD §3.3: "For a `HOTEL` segment, `fare_cents` (serving as the nightly-rate proxy)
    must not exceed the policy's `max_hotel_nightly_cents`, else `ERR_POLICY_VIOLATION`;
    `AIR` and `CAR` segments carry no amount cap."

    Design: Corner/validations/hotel_over_nightly_cap_returns_policy_violation
    """
    ctx = make_approved_trip(market_estimate=50000, vendor_type="HOTEL")
    trip, trav, ven = ctx["trip"], ctx["traveler"], ctx["vendor"]
    res = api.create_booking(
        create_booking_payload(trip["id"], ven["id"], trip["version"], segment_type="HOTEL",
                               fare_basis="REFUNDABLE", fare_cents=50000,
                               depart_datetime="2026-08-01T09:00:00Z",
                               return_datetime="2026-08-04T09:00:00Z"),
        make_traveler_headers(trav["id"]))
    validate_error(res, ApiErrorId.ERR_POLICY_VIOLATION)


# ─── Corner: OCC stale trip version ───────────────────
def test_second_segment_with_stale_trip_version_rejected(api):
    """PRD §2.8: "If `expected_trip_request_version` does not match the trip's current
    `version`, the create is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_trip_version_on_second_segment
    """
    ctx = make_approved_trip(market_estimate=50000,
                             trip_overrides={"return_date": "2026-08-20T09:00:00Z"})
    trip, trav, ven = ctx["trip"], ctx["traveler"], ctx["vendor"]
    stale_version = trip["version"]
    book(trip["id"], trav["id"], stale_version, vendor_id=ven["id"], segment_type="AIR",
         fare_basis="REFUNDABLE", fare_cents=250000,
         depart_datetime="2026-08-01T09:00:00Z", return_datetime="2026-08-01T20:00:00Z")
    res = api.create_booking(
        create_booking_payload(trip["id"], ven["id"], stale_version, segment_type="AIR",
                               fare_basis="REFUNDABLE", fare_cents=260000,
                               depart_datetime="2026-08-10T09:00:00Z",
                               return_datetime="2026-08-10T20:00:00Z"),
        make_traveler_headers(trav["id"]))
    validate_error(res, ApiErrorId.ERR_STALE_VERSION)


# ─── Corner: exchange after departure ─────────────────
def test_exchange_after_departure_rejected(api):
    """PRD §3.4: "A `TICKETED` booking may be **exchanged** by the owning `Traveler` for a
    new fare, provided the trip is `BOOKED` and the current clock is at or before the
    segment's `depart_datetime` — a segment cannot be exchanged after departure."

    Design: Corner/state_machines/exchange_after_departure_returns_invalid_state
    """
    ctx = make_approved_trip(market_estimate=50000)
    trip, trav, ven = ctx["trip"], ctx["traveler"], ctx["vendor"]
    old = book(trip["id"], trav["id"], trip["version"], vendor_id=ven["id"], segment_type="AIR",
               fare_basis="NONREFUNDABLE", fare_cents=250000,
               depart_datetime="2026-08-01T09:00:00Z", return_datetime="2026-08-01T20:00:00Z")
    set_clock("2026-08-02T00:00:00Z")
    res = api.exchange_booking(old["id"], exchange_booking_payload(200000),
                               make_traveler_headers(trav["id"]))
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)


# ─── Corner: cancel a REFUNDED (terminal) booking ─────
def test_cancel_refunded_booking_rejected(api):
    """PRD §3.4: "A `REFUNDABLE` booking moves to `REFUNDED` and issues no credit."
    PRD §3.4: "`CANCELLED` and `REFUNDED` are both terminal for a booking."

    Design: Corner/state_machines/cancel_booking_from_terminal_refunded_returns_invalid_state
    """
    ctx = make_approved_trip(market_estimate=50000)
    trip, trav, ven = ctx["trip"], ctx["traveler"], ctx["vendor"]
    booking = book(trip["id"], trav["id"], trip["version"], vendor_id=ven["id"], segment_type="AIR",
                   fare_basis="REFUNDABLE", fare_cents=250000)
    cancel_booking(booking["id"], trav["id"])  # -> REFUNDED
    res = api.cancel_booking(booking["id"], make_traveler_headers(trav["id"]))
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)


# ─── Corner: redeem an expired credit ─────────────────
def test_redeem_expired_credit_rejected(api):
    """PRD §3.3: "The credit must be `AVAILABLE` or `PARTIALLY_USED`, must not have expired,
    must be owned by this traveler, and must be for the same vendor as the booking; any of
    these failing yields `ERR_CREDIT_UNAVAILABLE`."

    Design: Corner/validations/redeem_expired_credit_returns_credit_unavailable
    """
    ctx = make_credit_from_cancelled_nonref(fare_cents=250000)
    trip, trav, ven, credit = ctx["trip"], ctx["traveler"], ctx["vendor"], ctx["credit"]
    set_clock("2028-01-01T00:00:00Z")
    run_sweep()  # credit past expiry -> EXPIRED
    v = trip_version(trip["id"], trav["id"])
    res = api.create_booking(
        create_booking_payload(trip["id"], ven["id"], v, segment_type="AIR",
                               fare_basis="REFUNDABLE", fare_cents=180000,
                               redeem_credit_id=credit["id"],
                               depart_datetime="2028-03-01T09:00:00Z",
                               return_datetime="2028-03-01T20:00:00Z"),
        make_traveler_headers(trav["id"]))
    validate_error(res, ApiErrorId.ERR_CREDIT_UNAVAILABLE)
