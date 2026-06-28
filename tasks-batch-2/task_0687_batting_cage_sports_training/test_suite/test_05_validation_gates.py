"""Confirm-time validation gates and their priority ordering: waiver, posture, strikes,
resource availability, lane time conflict (buffer + half-open), outside hours, booking
shape, funds; plus the two priority-pair conflicts.

Covers Difficulty rules priority_pair_validation_conflict, cross_entity_state_dependency
(inactive instructor), resource_temporal_overlap, and the validations corner instances.
"""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    make_member_headers,
    ApiErrorId,
    setup_member_ready,
    create_facility,
    create_lane,
    create_instructor,
    create_member,
    sign_waiver,
    top_up,
    request_booking,
    confirm_booking,
    create_confirmed_booking,
    open_maintenance,
    set_clock,
    lane_version,
)

MANAGER = {"X-User-ID": "test-manager-1", "X-User-Role": "FacilityManager", "Content-Type": "application/json"}


# ─── priority_pair_validation_conflict / waiver_required_beats_insufficient_funds ─

def test_waiver_required_outranks_insufficient_funds(api):
    """PRD §2.11: "From there the business rules apply in this order: waiver currency
    (sixth) ... funds and minutes (thirteenth)". PRD §3.5: "The member's waiver_ok must
    be true, or the confirm is rejected with ERR_WAIVER_REQUIRED."

    Design: Difficulty/priority_pair_validation_conflict/waiver_required_beats_insufficient_funds
    """
    facility = create_facility(hourly_rate_cents=4000, token_price_cents=500)
    lane = create_lane(facility["id"], kind="CAGE", buffer_minutes=0)
    member = create_member(facility["id"], tier="NONE")  # no waiver, 0 tokens
    booking = request_booking(
        facility, lane["id"], member, "OPEN_SLOT", "TOKEN",
        "2026-04-02T09:00:00Z", "2026-04-02T10:00:00Z",
    )
    ver = lane_version(lane["id"])
    res = api.confirm_booking(
        booking["id"], {"expected_lane_version": ver}, make_member_headers(member["id"])
    )
    validate_error(res, ApiErrorId.ERR_WAIVER_REQUIRED.value)


def test_waiver_required_returned_for_lesson_with_no_waiver_no_funds(api):
    """PRD §2.11: "From there the business rules apply in this order: waiver currency
    (sixth) ... funds and minutes (thirteenth)". PRD §3.5: "The member's waiver_ok must
    be true, or the confirm is rejected with ERR_WAIVER_REQUIRED."

    Design: Difficulty/priority_pair_validation_conflict/waiver_required_beats_insufficient_funds
    """
    facility = create_facility(hourly_rate_cents=4000, token_price_cents=500)
    lane = create_lane(facility["id"], kind="CAGE", buffer_minutes=0)
    instructor = create_instructor(facility["id"], rate_cents_per_hour=6000)
    member = create_member(facility["id"], tier="NONE")  # no waiver, 0 tokens
    booking = request_booking(
        facility, lane["id"], member, "LESSON", "TOKEN",
        "2026-04-02T09:00:00Z", "2026-04-02T10:00:00Z",
        instructor_id=instructor["id"],
    )
    ver = lane_version(lane["id"])
    res = api.confirm_booking(
        booking["id"], {"expected_lane_version": ver}, make_member_headers(member["id"])
    )
    # Waiver(6) outranks funds(13) even though the lesson would cost far more than 0 tokens.
    validate_error(res, ApiErrorId.ERR_WAIVER_REQUIRED.value)


# ─── priority_pair_validation_conflict / invalid_state_beats_lane_time_conflict ─

def test_invalid_state_outranks_lane_time_conflict(api):
    """PRD §2.11: "State validity is fifth". PRD §2.11: "lane time conflict (tenth)".
    PRD §2.11: "the priority numbering here is what determines which single error a
    multiply-invalid request receives."

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_lane_time_conflict
    """
    facility, lane, member = setup_member_ready(
        lane_overrides={"buffer_minutes": 0}, tier="NONE", waiver=True, tokens=100
    )
    booking = create_confirmed_booking(
        facility, lane, member,
        start_utc="2026-04-02T09:00:00Z", end_utc="2026-04-02T10:00:00Z",
    )
    # Re-confirm the already-CONFIRMED booking: state(5) must win over any temporal(10).
    ver = lane_version(lane["id"])
    res = api.confirm_booking(
        booking["id"], {"expected_lane_version": ver}, make_member_headers(member["id"])
    )
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)


def test_confirm_rejected_booking_overlapping_neighbour_yields_invalid_state(api):
    """PRD §2.11: "State validity is fifth: a target resource that is not in a legal state
    for the requested transition yields ERR_INVALID_STATE." PRD §2.11: "lane time conflict
    (tenth)". The state check (5) precedes the temporal check (10).

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_lane_time_conflict
    """
    facility, lane, member = setup_member_ready(
        lane_overrides={"buffer_minutes": 0}, tier="NONE", waiver=True, tokens=100
    )
    # Booking X requested on 09:00-10:00, then REJECTED (terminal).
    bk_x = request_booking(
        facility, lane["id"], member, "OPEN_SLOT", "TOKEN",
        "2026-04-02T09:00:00Z", "2026-04-02T10:00:00Z",
    )
    validate_success(api.reject_booking(bk_x["id"], MANAGER), 200)
    # A neighbour confirmed over the same interval would make X temporally conflict too.
    create_confirmed_booking(
        facility, lane, member,
        start_utc="2026-04-02T09:00:00Z", end_utc="2026-04-02T10:00:00Z",
    )
    ver = lane_version(lane["id"])
    res = api.confirm_booking(
        bk_x["id"], {"expected_lane_version": ver}, make_member_headers(member["id"])
    )
    # X is REJECTED (invalid state, priority 5) — that outranks the lane-time conflict (10).
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)


# ─── cross_entity_state_dependency / lesson_confirm_blocked_by_inactive_instructor ─

def test_lesson_confirm_blocked_by_inactive_instructor(api):
    """PRD §3.4: "A LESSON without an active instructor, a MEMBERSHIP pay mode on a
    member whose tier is NONE, or a PARTY with a party_guests count below 1 is rejected
    with ERR_BOOKING_SHAPE_INVALID."

    Design: Difficulty/cross_entity_state_dependency/lesson_confirm_blocked_by_inactive_instructor
    """
    facility = create_facility(hourly_rate_cents=4000, token_price_cents=500)
    lane = create_lane(facility["id"], kind="CAGE", buffer_minutes=0)
    instructor = create_instructor(facility["id"], rate_cents_per_hour=6000, active=False)
    member = create_member(facility["id"], tier="GOLD")
    sign_waiver(facility["id"], member["id"])
    top_up(member["id"], 200)

    # PRD §3.4: the booking shape is checked at request time, so naming an inactive
    # instructor on a LESSON is rejected with ERR_BOOKING_SHAPE_INVALID before the
    # booking ever reaches REQUESTED status.
    payload = {
        "facility_id": facility["id"], "lane_id": lane["id"], "member_id": member["id"],
        "kind": "LESSON", "pay_mode": "TOKEN",
        "start_utc": "2026-04-02T09:00:00Z", "end_utc": "2026-04-02T10:00:00Z",
        "instructor_id": instructor["id"],
    }
    res = api.create_booking(payload, make_member_headers(member["id"]))
    validate_error(res, ApiErrorId.ERR_BOOKING_SHAPE_INVALID.value)


def test_membership_paymode_none_tier_blocked_at_confirm(api):
    """PRD §3.4: "a MEMBERSHIP pay mode on a member whose tier is NONE ... is rejected
    with ERR_BOOKING_SHAPE_INVALID."

    Design: Difficulty/cross_entity_state_dependency/lesson_confirm_blocked_by_inactive_instructor
    """
    facility = create_facility(hourly_rate_cents=4000, token_price_cents=500)
    lane = create_lane(facility["id"], kind="CAGE", buffer_minutes=0)
    member = create_member(facility["id"], tier="NONE")
    sign_waiver(facility["id"], member["id"])
    # PRD §3.4: a MEMBERSHIP pay mode on a NONE-tier member is an invalid booking shape,
    # rejected at request time with ERR_BOOKING_SHAPE_INVALID.
    payload = {
        "facility_id": facility["id"], "lane_id": lane["id"], "member_id": member["id"],
        "kind": "OPEN_SLOT", "pay_mode": "MEMBERSHIP",
        "start_utc": "2026-04-02T09:00:00Z", "end_utc": "2026-04-02T10:00:00Z",
    }
    res = api.create_booking(payload, make_member_headers(member["id"]))
    validate_error(res, ApiErrorId.ERR_BOOKING_SHAPE_INVALID.value)


# ─── resource_temporal_overlap / lane_buffer_adjacency_rejects_back_to_back ────

def test_buffer_blocks_back_to_back_booking(api):
    """PRD §3.5: "The booked interval plus the lane's buffer_minutes must not overlap any
    CONFIRMED or CHECKED_IN booking, nor any OPEN maintenance window, on each occupied
    lane — the buffer is an idle gap required after each booking before the next may start,
    applied as closed-interval adjacency — or the confirm is rejected with
    ERR_LANE_TIME_CONFLICT."

    Design: Difficulty/resource_temporal_overlap/lane_buffer_adjacency_rejects_back_to_back
    """
    facility, lane, member = setup_member_ready(
        lane_overrides={"buffer_minutes": 15}, tier="NONE", waiver=True, tokens=100
    )
    create_confirmed_booking(
        facility, lane, member,
        start_utc="2026-04-02T09:00:00Z", end_utc="2026-04-02T10:00:00Z",
    )
    bk_b = request_booking(
        facility, lane["id"], member, "OPEN_SLOT", "TOKEN",
        "2026-04-02T10:00:00Z", "2026-04-02T11:00:00Z",
    )
    ver = lane_version(lane["id"])
    res = api.confirm_booking(
        bk_b["id"], {"expected_lane_version": ver}, make_member_headers(member["id"])
    )
    validate_error(res, ApiErrorId.ERR_LANE_TIME_CONFLICT.value)


def test_booking_after_buffer_gap_is_allowed(api):
    """PRD §3.5: "the buffer is an idle gap required after each booking before the next
    may start, applied as closed-interval adjacency". PRD §3.5: "The booked interval plus
    the lane's buffer_minutes must not overlap any CONFIRMED or CHECKED_IN booking ... or
    the confirm is rejected with ERR_LANE_TIME_CONFLICT."

    Design: Difficulty/resource_temporal_overlap/lane_buffer_adjacency_rejects_back_to_back
    """
    facility, lane, member = setup_member_ready(
        lane_overrides={"buffer_minutes": 15}, tier="NONE", waiver=True, tokens=100
    )
    create_confirmed_booking(
        facility, lane, member,
        start_utc="2026-04-02T09:00:00Z", end_utc="2026-04-02T10:00:00Z",
    )
    # Next booking starts at 10:15 = first end (10:00) + 15-min buffer -> no longer occupied.
    bk_b = request_booking(
        facility, lane["id"], member, "OPEN_SLOT", "TOKEN",
        "2026-04-02T10:15:00Z", "2026-04-02T11:15:00Z",
    )
    ver = lane_version(lane["id"])
    confirmed = validate_success(
        api.confirm_booking(bk_b["id"], {"expected_lane_version": ver},
                            make_member_headers(member["id"])),
        200,
    )
    assert confirmed["status"] == "CONFIRMED"


# ─── resource_temporal_overlap / pure_half_open_booking_overlap_rejects_confirm ─

def test_half_open_overlap_rejects_confirm(api):
    """PRD §2.5: "Reservations and maintenance windows model time as half-open intervals
    [start, end) ... Two such intervals overlap when each begins strictly before the
    other ends." PRD §3.5: "The booked interval plus the lane's buffer_minutes must not
    overlap any CONFIRMED or CHECKED_IN booking ... or the confirm is rejected with
    ERR_LANE_TIME_CONFLICT."

    Design: Difficulty/resource_temporal_overlap/pure_half_open_booking_overlap_rejects_confirm
    """
    facility, lane, member = setup_member_ready(
        lane_overrides={"buffer_minutes": 0}, tier="NONE", waiver=True, tokens=100
    )
    create_confirmed_booking(
        facility, lane, member,
        start_utc="2026-04-02T09:00:00Z", end_utc="2026-04-02T10:00:00Z",
    )
    bk_b = request_booking(
        facility, lane["id"], member, "OPEN_SLOT", "TOKEN",
        "2026-04-02T09:30:00Z", "2026-04-02T10:30:00Z",
    )
    ver = lane_version(lane["id"])
    res = api.confirm_booking(
        bk_b["id"], {"expected_lane_version": ver}, make_member_headers(member["id"])
    )
    validate_error(res, ApiErrorId.ERR_LANE_TIME_CONFLICT.value)


def test_exactly_adjacent_zero_buffer_booking_allowed(api):
    """PRD §2.5: "Reservations and maintenance windows model time as half-open intervals
    [start, end) — the start instant is included and the end instant is excluded. Two such
    intervals overlap when each begins strictly before the other ends." PRD §3.1: "an
    optional buffer_minutes (defaulting to 0 ...) that specifies the idle gap that must be
    left after each booking before the next booking may start on that lane."

    Design: Difficulty/resource_temporal_overlap/pure_half_open_booking_overlap_rejects_confirm
    """
    facility, lane, member = setup_member_ready(
        lane_overrides={"buffer_minutes": 0}, tier="NONE", waiver=True, tokens=100
    )
    create_confirmed_booking(
        facility, lane, member,
        start_utc="2026-04-02T09:00:00Z", end_utc="2026-04-02T10:00:00Z",
    )
    # Adjacent booking starts exactly at the first's end on a zero-buffer lane: half-open
    # [10:00,11:00) does not overlap [09:00,10:00), so confirm is allowed.
    bk_b = request_booking(
        facility, lane["id"], member, "OPEN_SLOT", "TOKEN",
        "2026-04-02T10:00:00Z", "2026-04-02T11:00:00Z",
    )
    ver = lane_version(lane["id"])
    confirmed = validate_success(
        api.confirm_booking(bk_b["id"], {"expected_lane_version": ver},
                            make_member_headers(member["id"])),
        200,
    )
    assert confirmed["status"] == "CONFIRMED"


# ─── validations corner: outside_hours_rejected_on_confirm ─────────────────────

def test_outside_open_hours_rejected_on_confirm(api):
    """PRD §3.4: "A request whose interval falls outside the facility's open hours window
    [open_minute, close_minute) on its day is rejected with ERR_OUTSIDE_HOURS." PRD §3.1:
    "an open_minute (defaulting to 480, i.e. 08:00 UTC)".

    Design: Corner/validations/outside_hours_rejected_on_confirm
    """
    facility, lane, member = setup_member_ready(tier="NONE", waiver=True, tokens=100)
    # PRD §3.4: an interval before the facility's open_minute is rejected at request time
    # with ERR_OUTSIDE_HOURS.
    payload = {
        "facility_id": facility["id"], "lane_id": lane["id"], "member_id": member["id"],
        "kind": "OPEN_SLOT", "pay_mode": "TOKEN",
        "start_utc": "2026-04-02T06:00:00Z", "end_utc": "2026-04-02T07:00:00Z",  # before 08:00 open
    }
    res = api.create_booking(payload, make_member_headers(member["id"]))
    validate_error(res, ApiErrorId.ERR_OUTSIDE_HOURS.value)


# ─── validations corner: membership_pay_mode_requires_non_none_tier ────────────

def test_membership_paymode_requires_non_none_tier(api):
    """PRD §3.4: "a MEMBERSHIP pay mode on a member whose tier is NONE ... is rejected
    with ERR_BOOKING_SHAPE_INVALID." PRD §3.5: "non-NONE tier for membership ... or it is
    rejected with ERR_BOOKING_SHAPE_INVALID."

    Design: Corner/validations/membership_pay_mode_requires_non_none_tier
    """
    facility, lane, member = setup_member_ready(tier="NONE", waiver=True, tokens=0)
    # PRD §3.4: a MEMBERSHIP pay mode on a NONE-tier member is an invalid booking shape,
    # rejected at request time with ERR_BOOKING_SHAPE_INVALID.
    payload = {
        "facility_id": facility["id"], "lane_id": lane["id"], "member_id": member["id"],
        "kind": "OPEN_SLOT", "pay_mode": "MEMBERSHIP",
        "start_utc": "2026-04-02T09:00:00Z", "end_utc": "2026-04-02T10:00:00Z",
    }
    res = api.create_booking(payload, make_member_headers(member["id"]))
    validate_error(res, ApiErrorId.ERR_BOOKING_SHAPE_INVALID.value)


# ─── validations corner: end_before_start_invalid_request ──────────────────────

def test_end_not_after_start_rejected(api):
    """PRD §3.4: "an end instant not strictly after the start ... is rejected with
    ERR_INVALID_REQUEST." PRD §2.11: "an end instant that is not strictly after the start
    instant ... yields ERR_INVALID_REQUEST."

    Design: Corner/validations/end_before_start_invalid_request
    """
    facility = create_facility(hourly_rate_cents=4000, token_price_cents=500)
    lane = create_lane(facility["id"], kind="CAGE", buffer_minutes=0)
    member = create_member(facility["id"], tier="NONE")
    payload = {
        "facility_id": facility["id"], "lane_id": lane["id"], "member_id": member["id"],
        "kind": "OPEN_SLOT", "pay_mode": "HOURLY",
        "start_utc": "2026-04-02T10:00:00Z", "end_utc": "2026-04-02T09:00:00Z",
    }
    res = api.create_booking(payload, make_member_headers(member["id"]))
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST.value)


# ─── validations corner: booking_create_on_lane_under_maintenance_rejected ─────

def test_request_on_under_maintenance_lane_rejected(api):
    """PRD §3.4: "each occupied lane's maint_status must be AVAILABLE for the interval,
    failing which the request is rejected with ERR_RESOURCE_UNAVAILABLE." PRD §3.3:
    "Opening a ROUTINE window on a lane that has no CRITICAL open window moves the lane
    from AVAILABLE to UNDER_MAINTENANCE".

    Design: Corner/validations/booking_create_on_lane_under_maintenance_rejected
    """
    facility = create_facility(hourly_rate_cents=4000, token_price_cents=500)
    lane = create_lane(facility["id"], kind="CAGE", buffer_minutes=0)
    member = create_member(facility["id"], tier="NONE")
    open_maintenance(
        facility, lane["id"], "2026-04-02T09:00:00Z", "2026-04-02T10:00:00Z", "ROUTINE"
    )
    lane_after = get_success_data(api.get_lane(lane["id"], MANAGER))
    assert lane_after["maint_status"] == "UNDER_MAINTENANCE"

    payload = {
        "facility_id": facility["id"], "lane_id": lane["id"], "member_id": member["id"],
        "kind": "OPEN_SLOT", "pay_mode": "HOURLY",
        "start_utc": "2026-04-02T09:00:00Z", "end_utc": "2026-04-02T10:00:00Z",
    }
    res = api.create_booking(payload, make_member_headers(member["id"]))
    validate_error(res, ApiErrorId.ERR_RESOURCE_UNAVAILABLE.value)


# ─── validations corner: insufficient_tokens_rejected ──────────────────────────

def test_insufficient_tokens_rejected_at_confirm(api):
    """PRD §3.5: "for a TOKEN booking the member's token_balance must be at least the
    computed token cost ... or the confirm is rejected with ERR_INSUFFICIENT_FUNDS."

    Design: Corner/validations/insufficient_tokens_rejected
    """
    facility, lane, member = setup_member_ready(tier="NONE", waiver=True, tokens=3)
    booking = request_booking(
        facility, lane["id"], member, "OPEN_SLOT", "TOKEN",
        "2026-04-02T09:00:00Z", "2026-04-02T10:00:00Z",
    )
    ver = lane_version(lane["id"])
    res = api.confirm_booking(
        booking["id"], {"expected_lane_version": ver}, make_member_headers(member["id"])
    )
    validate_error(res, ApiErrorId.ERR_INSUFFICIENT_FUNDS.value)


# ─── validations corner: waiver_expired_rejected_at_confirm ────────────────────

def test_expired_waiver_rejected_at_confirm(api):
    """PRD §3.2: "computes expires_at as exactly 365 days after signed_at". PRD §3.2:
    "The member's waiver_ok is true exactly when such a SIGNED waiver exists and the
    current clock is strictly earlier than that waiver's expires_at." PRD §3.5: "The
    member's waiver_ok must be true, or the confirm is rejected with ERR_WAIVER_REQUIRED."

    Design: Corner/validations/waiver_expired_rejected_at_confirm
    """
    facility, lane, member = setup_member_ready(tier="NONE", waiver=True, tokens=100)
    # Waiver signed at default clock 2026-04-01; advance past expiry (signed + 365 days).
    set_clock("2027-04-02T08:00:00Z")
    booking = request_booking(
        facility, lane["id"], member, "OPEN_SLOT", "TOKEN",
        "2027-04-02T09:00:00Z", "2027-04-02T10:00:00Z",
    )
    ver = lane_version(lane["id"])
    res = api.confirm_booking(
        booking["id"], {"expected_lane_version": ver}, make_member_headers(member["id"])
    )
    validate_error(res, ApiErrorId.ERR_WAIVER_REQUIRED.value)
