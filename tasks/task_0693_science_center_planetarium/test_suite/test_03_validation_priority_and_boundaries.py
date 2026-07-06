"""Validation precedence, numeric/empty-set boundaries, and buffer-aware vs
bare-window temporal overlap.

Queue A (Difficulty): priority_pair_validation_conflict, boundary_precision_check,
resource_temporal_overlap.
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    create_dome,
    create_open_show,
    create_classroom_program,
    create_registration,
    create_hold,
    create_group_booking,
    create_sponsor,
    record_contribution,
    create_rental_hall,
    create_held_rental,
)

ADMIN = TEST_USERS["facility_admin_headers"]
BOX_OFFICE = TEST_USERS["box_office_headers"]
GROUP_SALES = TEST_USERS["group_sales_headers"]
PROGRAM = TEST_USERS["program_coordinator_headers"]
DEV = TEST_USERS["development_officer_headers"]
EVENTS = TEST_USERS["events_manager_headers"]


# --- priority_pair_validation_conflict ---

def test_state_check_wins_over_capacity_on_group_deposit(api):
    """PRD §3.10: "Only then come state and business checks: that the target is in a
    state from which the transition is defined (`ERR_INVALID_STATE`) ... then show
    seat capacity (`ERR_SHOW_CAPACITY_EXCEEDED`)".
    PRD §3.10: "A higher-priority failure is always reported in preference to a
    lower-priority one."

    A SCHEDULED (never-opened) show with a deposit that also exceeds capacity reports
    the higher-priority ERR_INVALID_STATE, not ERR_SHOW_CAPACITY_EXCEEDED.

    Design: Difficulty/priority_pair_validation_conflict/state_vs_fiscal_on_group_pay_deposit
    """
    dome = create_dome(seated_capacity=2, name="Dome E")
    show = validate_success(api.create_show(
        {"venue_id": dome["id"], "title": "Closed", "starts_at": "2026-04-12T10:00:00Z",
         "ends_at": "2026-04-12T11:00:00Z", "base_price_cents": 1000}, BOX_OFFICE),
        expected_status=201)
    gb = validate_success(api.create_group_booking(
        {"show_event_id": show["id"], "organization_name": "Big Group",
         "student_count": 4, "chaperone_count": 1}, GROUP_SALES), expected_status=201)

    resp = api.pay_group_deposit(gb["id"], GROUP_SALES)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)


def test_age_and_overfulfillment_are_distinct_category_errors(api):
    """PRD §3.6: "Enrollment is gated on age: the participant's age must fall within
    the session's band, that is, at least `min_age` and at most `max_age`; an age
    outside the band is rejected with `ERR_AGE_INELIGIBLE`."
    PRD §3.8: "A contribution that would push the sponsor's `received_cents` above its
    `pledged_cents` is rejected with `ERR_OVERFULFILLMENT` — over-fulfillment is not
    allowed."

    Two independent single-failure scenarios: an under-age registration and an
    over-pledge contribution each fire their own category error.

    Design: Difficulty/priority_pair_validation_conflict/safety_age_vs_fiscal_overfulfillment_categories
    """
    program = create_classroom_program(capacity=10, tuition_cents=8000, min_age=6, max_age=12,
                                        program_kind="CLASS", title="Kids Lab")
    age_resp = api.create_registration(
        {"program_session_id": program["id"], "participant_name": "Tot",
         "participant_age": 4, "expected_session_version": program["version"]}, PROGRAM)
    validate_error(age_resp, ApiErrorId.ERR_AGE_INELIGIBLE.value)

    sponsor = create_sponsor(pledged_cents=5000, sponsor_kind="SPONSOR", org_name="Acme")
    record_contribution(sponsor["id"], amount_cents=3000)  # -> PARTIALLY_FULFILLED (still accepting)
    sponsor_live = validate_success(api.get_sponsor(sponsor["id"], DEV))
    over_resp = api.create_contribution(
        sponsor["id"], {"amount_cents": 3000, "expected_sponsor_version": sponsor_live["version"]}, DEV)
    validate_error(over_resp, ApiErrorId.ERR_OVERFULFILLMENT.value)


# --- boundary_precision_check ---

def test_last_seat_hold_succeeds_and_flips_sold_out(api):
    """PRD §3.4: "The hold is rejected with `ERR_SHOW_CAPACITY_EXCEEDED` if the show's
    current `seats_sold` plus the requested `party_size` would exceed the venue's
    `seated_capacity`."
    PRD §3.3: "When `seats_sold` reaches the venue's `seated_capacity`, the system
    automatically bubbles the show `OPEN → SOLD_OUT`".

    Capacity 3, 2 seats held: a party_size=1 hold (sum==3==capacity) is accepted and
    flips the show to SOLD_OUT.

    Design: Difficulty/boundary_precision_check/show_capacity_exact_boundary
    """
    show = create_open_show(seated_capacity=3, base_price_cents=1000, title="Edge")
    create_hold(show["id"], party_size=2)
    b2 = create_hold(show["id"], party_size=1)

    assert b2["status"] == "HELD"
    show_after = validate_success(api.get_show(show["id"], BOX_OFFICE))
    assert show_after["seats_sold"] == 3, f"expected seats_sold 3, got {show_after['seats_sold']}"
    assert show_after["status"] == "SOLD_OUT", \
        f"expected SOLD_OUT at exact capacity, got {show_after['status']}"


def test_over_capacity_hold_rejected_at_boundary(api):
    """PRD §3.4: "The hold is rejected with `ERR_SHOW_CAPACITY_EXCEEDED` if the show's
    current `seats_sold` plus the requested `party_size` would exceed the venue's
    `seated_capacity`."

    Capacity 3, 2 seats held: a party_size=2 hold (sum==4 > 3) is rejected.

    Design: Difficulty/boundary_precision_check/show_capacity_exact_boundary
    """
    show = create_open_show(seated_capacity=3, base_price_cents=1000, title="EdgeOver")
    create_hold(show["id"], party_size=2)
    version = validate_success(api.get_show(show["id"], BOX_OFFICE))["version"]

    resp = api.create_show_booking(
        {"show_event_id": show["id"], "party_size": 2, "expected_show_version": version}, BOX_OFFICE)
    validate_error(resp, ApiErrorId.ERR_SHOW_CAPACITY_EXCEEDED.value)


def test_enroll_into_full_session_waitlists_at_position_one(api):
    """PRD §3.6: "when no seat remains, the registration is accepted but placed on the
    waitlist. An enrolled registration is `ENROLLED`; a waitlisted one is `WAITLISTED`,
    and its `waitlist_position` is its 1-based rank among the session's `WAITLISTED`
    registrations ordered by `created_at` ascending (the position is null while
    enrolled)."

    Capacity 1, already 1 ENROLLED: the next registration is WAITLISTED at position 1.

    Design: Difficulty/boundary_precision_check/program_waitlist_zero_seat_empty_set
    """
    program = create_classroom_program(capacity=1, tuition_cents=5000, min_age=5, max_age=99,
                                        program_kind="CLASS", title="Solo Class")
    reg1 = create_registration(program["id"], participant_name="First", participant_age=10)
    assert reg1["status"] == "ENROLLED"

    reg2 = create_registration(program["id"], participant_name="Second", participant_age=11)
    assert reg2["status"] == "WAITLISTED", f"expected WAITLISTED, got {reg2['status']}"
    assert reg2["waitlist_position"] == 1, \
        f"expected waitlist_position 1, got {reg2['waitlist_position']}"


# --- resource_temporal_overlap ---

def test_show_overlap_within_turnover_buffer_rejected(api):
    """PRD §2.10: "When a new show is scheduled, its window extended forward by the
    venue's turnover buffer must not overlap any other non-cancelled show in that same
    venue; an overlap is rejected with `ERR_SHOW_TIME_CONFLICT`."

    Buffer 15 min, first show 10:00-11:00; a second show 11:10-12:00 starts within the
    11:00 + 15-min buffer window, so it conflicts.

    Design: Difficulty/resource_temporal_overlap/show_overlap_with_turnover_buffer
    """
    dome = create_dome(seated_capacity=50, turnover_buffer_minutes=15, name="Dome I")
    validate_success(api.create_show(
        {"venue_id": dome["id"], "title": "First", "starts_at": "2026-04-20T10:00:00Z",
         "ends_at": "2026-04-20T11:00:00Z", "base_price_cents": 1000}, BOX_OFFICE),
        expected_status=201)

    resp = api.create_show(
        {"venue_id": dome["id"], "title": "Second", "starts_at": "2026-04-20T11:10:00Z",
         "ends_at": "2026-04-20T12:00:00Z", "base_price_cents": 1000}, BOX_OFFICE)
    validate_error(resp, ApiErrorId.ERR_SHOW_TIME_CONFLICT.value, expected_status=409)


def test_rental_back_to_back_adjacency_allowed(api):
    """PRD §2.10: "Rental windows are likewise half-open from `starts_at` inclusive to
    `ends_at` exclusive, but they carry **no** buffer: a rental may be held only if its
    bare window overlaps no other held or confirmed rental in the same hall, and an
    overlap is rejected with `ERR_RENTAL_TIME_CONFLICT`."

    A HELD rental 14:00-16:00 and a second rental 16:00-18:00 share only the exclusive
    boundary (gap=0); with no buffer the adjacent hold is allowed.

    Design: Difficulty/resource_temporal_overlap/rental_overlap_no_buffer_adjacency_ok
    """
    hall = create_rental_hall(seated_capacity=80, name="Hall J")
    create_held_rental(hall["id"], guest_count=10, base_rental_cents=30000, host_name="A",
                       starts_at="2026-05-10T14:00:00Z", ends_at="2026-05-10T16:00:00Z")
    r2 = validate_success(api.create_rental(
        {"venue_id": hall["id"], "host_name": "B", "starts_at": "2026-05-10T16:00:00Z",
         "ends_at": "2026-05-10T18:00:00Z", "guest_count": 10, "base_rental_cents": 30000}, EVENTS),
        expected_status=201)

    held = validate_success(api.hold_rental(r2["id"], EVENTS))
    assert held["status"] == "HELD", f"adjacent rental should hold, got {held['status']}"
