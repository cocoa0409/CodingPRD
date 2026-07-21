"""Guided trips: cancellation cascade, capacity boundary, membership gating,
guide scheduling, and validation-precedence pairs."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, NON_EXISTENT_UUID,
    fixtures, factories,
)

ADMIN = fixtures.ADMIN
STAFF = fixtures.STAFF


# ---------------------------------------------------------------------------
# Queue A — transitive_cascade / trip_cancel_cascade_depth3
# ---------------------------------------------------------------------------

def _member_with_points_and_booking(api):
    """Member with 1000 points, an OPEN trip, and a booking redeeming all 1000 points."""
    fixtures.set_clock(api, "2026-07-01T00:00:00Z")
    member, member_headers = fixtures.create_active_member(api)
    product = fixtures.create_product(api, retail_price_cents=100000, tax_rate=0.05)
    fixtures.create_purchase(
        api, member["id"],
        [{"product_id": product["id"], "quantity": 1, "unit_price_cents": 100000}])
    trip, guide = fixtures.setup_open_trip(api, capacity=2, price_cents=5000)
    booking = validate_success(api.create_booking(
        trip["id"], {"member_id": member["id"], "points_redeemed": 1000}, member_headers), 201)
    return member, member_headers, trip, booking


def test_trip_cancel_cascades_booking_cancellation(api):
    """PRD §3.4: "a booking may also be cancelled by the cascade from a trip
    cancellation, which can cancel bookings that are `CONFIRMED` or `CHECKED_IN`."

    Design: Difficulty/transitive_cascade/trip_cancel_cascade_depth3
    """
    member, member_headers, trip, booking = _member_with_points_and_booking(api)
    trip = validate_success(api.cancel_trip(trip["id"], ADMIN))
    assert trip["status"] == "CANCELLED"
    booking = validate_success(api.get_booking(booking["id"], member_headers))
    assert booking["status"] == "CANCELLED"


def test_trip_cancel_refunds_points_and_credits_wallet(api):
    """PRD §3.4: "In every cancellation the booking moves to the terminal
    `CANCELLED` state, a loyalty refund entry is appended returning the member's
    `points_redeemed`, the member's `wallet_credit_cents` is credited by the
    `price_paid_cents` minus the `points_redeemed`, and the trip's
    `seats_confirmed` is recomputed downward by 1."

    Design: Difficulty/transitive_cascade/trip_cancel_cascade_depth3
    """
    member, member_headers, trip, booking = _member_with_points_and_booking(api)
    validate_success(api.cancel_trip(trip["id"], ADMIN))
    member = validate_success(api.get_member(member["id"], member_headers))
    assert member["loyalty_points_balance"] == 1000
    assert member["wallet_credit_cents"] == 4000


# ---------------------------------------------------------------------------
# Queue A — boundary_precision_check / trip_capacity_full_eq_boundary
# ---------------------------------------------------------------------------

def test_booking_below_capacity_succeeds_and_counts_seat(api):
    """PRD §3.4: "`seats_confirmed` is the number of that trip's bookings in
    `CONFIRMED` or `CHECKED_IN` status ... Each new confirmed booking raises the
    trip's `seats_confirmed` by 1."

    Design: Difficulty/boundary_precision_check/trip_capacity_full_eq_boundary
    """
    member, member_headers = fixtures.create_active_member(api)
    trip, guide = fixtures.setup_open_trip(api, capacity=1, price_cents=3000)
    validate_success(api.create_booking(
        trip["id"], {"member_id": member["id"]}, member_headers), 201)
    trip = validate_success(api.get_trip(trip["id"], STAFF))
    assert trip["seats_confirmed"] == 1


def test_booking_at_capacity_rejected_trip_full(api):
    """PRD §3.4: "a booking is rejected with `ERR_TRIP_FULL` when `seats_confirmed`
    already equals `capacity` — the trip itself stays `OPEN`, and there is no full
    status."

    Design: Difficulty/boundary_precision_check/trip_capacity_full_eq_boundary
    """
    m1, m1_headers = fixtures.create_active_member(api)
    m2, m2_headers = fixtures.create_active_member(api)
    trip, guide = fixtures.setup_open_trip(api, capacity=1, price_cents=3000)
    validate_success(api.create_booking(
        trip["id"], {"member_id": m1["id"]}, m1_headers), 201)
    validate_error(api.create_booking(
        trip["id"], {"member_id": m2["id"]}, m2_headers), ApiErrorId.ERR_TRIP_FULL.value)


# ---------------------------------------------------------------------------
# Queue A — cross_entity_state_dependency / booking_requires_member_active
# ---------------------------------------------------------------------------

def test_lapsed_member_cannot_book(api):
    """PRD §3.4: "The booking member's `membership_status` must be `ACTIVE`,
    otherwise `ERR_MEMBERSHIP_NOT_ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/booking_requires_member_active
    """
    member, member_headers = fixtures.create_active_member(api)
    validate_success(api.lapse_member(member["id"], ADMIN))
    trip, guide = fixtures.setup_open_trip(api, capacity=3, price_cents=4000)
    validate_error(api.create_booking(
        trip["id"], {"member_id": member["id"]}, member_headers),
        ApiErrorId.ERR_MEMBERSHIP_NOT_ACTIVE.value)


def test_pending_member_cannot_book(api):
    """PRD §3.4: "The booking member's `membership_status` must be `ACTIVE`,
    otherwise `ERR_MEMBERSHIP_NOT_ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/booking_requires_member_active
    """
    member, member_headers = fixtures.create_pending_member(api)
    trip, guide = fixtures.setup_open_trip(api, capacity=3, price_cents=4000)
    validate_error(api.create_booking(
        trip["id"], {"member_id": member["id"]}, member_headers),
        ApiErrorId.ERR_MEMBERSHIP_NOT_ACTIVE.value)


# ---------------------------------------------------------------------------
# Queue A — resource_temporal_overlap / guide_schedule_closed_interval_touch
# ---------------------------------------------------------------------------

def test_guide_assignment_touching_prior_trip_rejected(api):
    """PRD §3.4: "because the intervals are closed and inclusive, exact adjacency
    — this trip starting at the very instant another ends — counts as a conflict,
    rejected with `ERR_GUIDE_SCHEDULE_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/guide_schedule_closed_interval_touch
    """
    guide = fixtures.create_guide(api, certifications=[])
    trip_b = fixtures.create_trip(api, start_time="2026-08-01T09:00:00Z",
                                  end_time="2026-08-01T17:00:00Z", required_certification="NONE")
    validate_success(api.assign_guide(trip_b["id"], {"guide_id": guide["id"]}, ADMIN))
    trip_a = fixtures.create_trip(api, start_time="2026-08-01T17:00:00Z",
                                  end_time="2026-08-01T19:00:00Z", required_certification="NONE")
    validate_error(api.assign_guide(trip_a["id"], {"guide_id": guide["id"]}, ADMIN),
                   ApiErrorId.ERR_GUIDE_SCHEDULE_CONFLICT.value)


def test_guide_assignment_with_clear_gap_allowed(api):
    """PRD §3.4: "This trip's window `[start_time, end_time]` conflicts with an
    assigned trip's window `[assigned_start, assigned_end]` when this start is at
    or before the assigned end and the assigned start is at or before this end".

    Design: Difficulty/resource_temporal_overlap/guide_schedule_closed_interval_touch
    """
    guide = fixtures.create_guide(api, certifications=[])
    trip_b = fixtures.create_trip(api, start_time="2026-08-01T09:00:00Z",
                                  end_time="2026-08-01T17:00:00Z", required_certification="NONE")
    validate_success(api.assign_guide(trip_b["id"], {"guide_id": guide["id"]}, ADMIN))
    trip_a = fixtures.create_trip(api, start_time="2026-08-01T18:00:00Z",
                                  end_time="2026-08-01T19:00:00Z", required_certification="NONE")
    assigned = validate_success(api.assign_guide(trip_a["id"], {"guide_id": guide["id"]}, ADMIN))
    assert assigned["guide_id"] == guide["id"]


# ---------------------------------------------------------------------------
# Queue A — priority_pair_validation_conflict / state_vs_fiscal_booking_returns_trip_not_open
# ---------------------------------------------------------------------------

def test_draft_trip_booking_reports_state_error_over_fiscal(api):
    """PRD §2.9: "(4) state and cross-entity state preconditions, yielding
    `ERR_INVALID_STATE`, `ERR_TRIP_NOT_OPEN`, `ERR_MEMBERSHIP_NOT_ACTIVE`, or
    `ERR_RENTAL_UNIT_UNAVAILABLE`; ... and (8) fiscal-capacity checks, yielding
    `ERR_INSUFFICIENT_POINTS` or `ERR_INSUFFICIENT_WALLET`."
    PRD §3.4: "A booking is only accepted on an `OPEN` trip; a trip in any other
    status yields `ERR_TRIP_NOT_OPEN`."

    Design: Difficulty/priority_pair_validation_conflict/state_vs_fiscal_booking_returns_trip_not_open
    """
    member, member_headers = fixtures.create_active_member(api)
    trip, guide = fixtures.setup_draft_trip_with_guide(api, capacity=5, price_cents=5000)
    validate_error(api.create_booking(
        trip["id"], {"member_id": member["id"], "points_redeemed": 5000}, member_headers),
        ApiErrorId.ERR_TRIP_NOT_OPEN.value)


def test_open_trip_booking_reports_fiscal_error_when_state_ok(api):
    """PRD §3.4: "When points are redeemed on a booking they are deducted through
    a loyalty redemption entry, and the member must hold enough points, otherwise
    `ERR_INSUFFICIENT_POINTS`."

    Design: Difficulty/priority_pair_validation_conflict/state_vs_fiscal_booking_returns_trip_not_open
    """
    member, member_headers = fixtures.create_active_member(api)
    trip, guide = fixtures.setup_open_trip(api, capacity=5, price_cents=5000)
    validate_error(api.create_booking(
        trip["id"], {"member_id": member["id"], "points_redeemed": 5000}, member_headers),
        ApiErrorId.ERR_INSUFFICIENT_POINTS.value)


# ---------------------------------------------------------------------------
# Queue A — priority_pair_validation_conflict / safety_vs_temporal_assign_guide_returns_not_certified
# ---------------------------------------------------------------------------

def test_assign_guide_reports_certification_error_over_schedule(api):
    """PRD §2.9: "(5) business-safety checks such as guide certification, yielding
    `ERR_GUIDE_NOT_CERTIFIED`; (6) temporal checks — rental window conflicts,
    guide schedule conflicts, and interval validity — yielding
    `ERR_RENTAL_WINDOW_CONFLICT`, `ERR_GUIDE_SCHEDULE_CONFLICT`, or
    `ERR_INVALID_INTERVAL`".
    PRD §3.4: "Assigning a guide requires that the guide hold the trip's
    `required_certification` — the guide's `certifications` must contain it —
    otherwise the assignment is rejected with `ERR_GUIDE_NOT_CERTIFIED`."

    Design: Difficulty/priority_pair_validation_conflict/safety_vs_temporal_assign_guide_returns_not_certified
    """
    guide = fixtures.create_guide(api, certifications=[])
    trip_b = fixtures.create_trip(api, start_time="2026-08-01T09:00:00Z",
                                  end_time="2026-08-01T17:00:00Z", required_certification="NONE")
    validate_success(api.assign_guide(trip_b["id"], {"guide_id": guide["id"]}, ADMIN))
    trip_a = fixtures.create_trip(api, start_time="2026-08-01T12:00:00Z",
                                  end_time="2026-08-01T14:00:00Z", required_certification="ALPINE")
    validate_error(api.assign_guide(trip_a["id"], {"guide_id": guide["id"]}, ADMIN),
                   ApiErrorId.ERR_GUIDE_NOT_CERTIFIED.value)


def test_assign_certified_guide_reports_schedule_conflict_when_safety_ok(api):
    """PRD §3.4: "This trip's window `[start_time, end_time]` conflicts with an
    assigned trip's window `[assigned_start, assigned_end]` when this start is at
    or before the assigned end and the assigned start is at or before this end ...
    rejected with `ERR_GUIDE_SCHEDULE_CONFLICT`."

    Design: Difficulty/priority_pair_validation_conflict/safety_vs_temporal_assign_guide_returns_not_certified
    """
    guide = fixtures.create_guide(api, certifications=["ALPINE"])
    trip_b = fixtures.create_trip(api, start_time="2026-08-01T09:00:00Z",
                                  end_time="2026-08-01T17:00:00Z", required_certification="NONE")
    validate_success(api.assign_guide(trip_b["id"], {"guide_id": guide["id"]}, ADMIN))
    trip_a = fixtures.create_trip(api, start_time="2026-08-01T12:00:00Z",
                                  end_time="2026-08-01T14:00:00Z", required_certification="ALPINE")
    validate_error(api.assign_guide(trip_a["id"], {"guide_id": guide["id"]}, ADMIN),
                   ApiErrorId.ERR_GUIDE_SCHEDULE_CONFLICT.value)


# ---------------------------------------------------------------------------
# Queue B — errors / assign_guide_guide_not_found_returns_404
# ---------------------------------------------------------------------------

def test_assign_missing_guide_returns_not_found(api):
    """PRD §2.9: "a missing guide `ERR_GUIDE_NOT_FOUND`".

    Design: Corner/errors/assign_guide_guide_not_found_returns_404
    """
    trip = fixtures.create_trip(api, required_certification="NONE")
    validate_error(api.assign_guide(trip["id"], {"guide_id": NON_EXISTENT_UUID}, ADMIN),
                   ApiErrorId.ERR_GUIDE_NOT_FOUND.value)
