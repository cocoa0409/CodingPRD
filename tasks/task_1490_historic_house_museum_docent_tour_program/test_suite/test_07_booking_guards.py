"""Booking creation and confirmation guards: slot-state gate, safety caps,
chaperone ratios, curriculum alignment, member standing, payment equality,
capacity boundaries, and validation precedence."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    assign_and_confirm_lead,
    confirm_booking,
    create_certified_docent,
    create_general_booking,
    create_member,
    create_slot,
    get_booking,
    get_slot,
    make_member_headers,
    open_slot,
    run_epoch,
    set_clock,
    setup_active_route_with_script,
    setup_open_slot,
    setup_staffed_scheduled_slot,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["museum_admin_headers"]
FRONT_DESK = TEST_USERS["front_desk_staff_headers"]


class TestBookingRequiresOpenSlot:

    def test_booking_on_in_progress_slot_rejected(self):
        """PRD section 2.9, tier 5: "except booking creation, which has its
        own code: the slot must be `OPEN`, and any other slot state
        (including `FULL`) yields `ERR_SLOT_NOT_OPEN`."
        PRD section 3.4: "Requesting `to_status` IN_PROGRESS moves an `OPEN`
        or `FULL` slot to `IN_PROGRESS`, but only once the logical clock has
        reached `start_at`; starting early is rejected with
        `ERR_INVALID_STATE`."

        Design: Difficulty/cross_entity_state_dependency/booking_requires_slot_open_state
        """
        ctx = setup_open_slot()
        set_clock("2026-09-01T10:00:00Z")
        resp = api_client.advance_tour_slot(
            ctx["slot_id"], {"to_status": "IN_PROGRESS"}, ADMIN)
        validate_success(resp)
        resp = api_client.create_booking(
            {"slot_id": ctx["slot_id"], "booking_kind": "GENERAL",
             "visitor_name": "Gus", "party_size": 1},
            FRONT_DESK)
        validate_error(resp, ApiErrorId.ERR_SLOT_NOT_OPEN)

    def test_booking_on_scheduled_slot_rejected(self):
        """PRD section 2.9, tier 5: "except booking creation, which has its
        own code: the slot must be `OPEN`, and any other slot state
        (including `FULL`) yields `ERR_SLOT_NOT_OPEN`."
        PRD section 3.6: "The slot must be `OPEN` — a `FULL` slot is already
        a failed state for new bookings, and any non-open slot yields
        `ERR_SLOT_NOT_OPEN` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/booking_requires_slot_open_state
        """
        ctx = setup_staffed_scheduled_slot()
        assert ctx["slot"]["status"] == "SCHEDULED"
        resp = api_client.create_booking(
            {"slot_id": ctx["slot_id"], "booking_kind": "GENERAL",
             "visitor_name": "Gus", "party_size": 1},
            FRONT_DESK)
        validate_error(resp, ApiErrorId.ERR_SLOT_NOT_OPEN)


class TestSlotStateBeatsSafetyCap:
    """A cancelled slot with an oversized HIGH_VALUE party: tier 5 wins."""

    def _high_value_open_slot(self):
        return setup_open_slot(
            room_specs=[{"name": "Silver Closet", "floor": 1,
                         "capacity_max": 20, "safety_max_party": 4,
                         "collection_tier": "HIGH_VALUE"}],
            route_name="Silver Tour")

    def test_cancelled_slot_oversized_party_returns_slot_not_open(self):
        """PRD section 2.9: "Every request passes through an ordered gauntlet
        of checks, and a failure at any tier short-circuits all later tiers —
        the error surfaced is always the earliest applicable one, never a
        later mask."
        PRD section 2.9, tier 5: "except booking creation, which has its own
        code: the slot must be `OPEN`, and any other slot state (including
        `FULL`) yields `ERR_SLOT_NOT_OPEN`."

        Design: Difficulty/priority_pair_validation_conflict/cancelled_slot_oversized_party_returns_slot_not_open
        """
        ctx = self._high_value_open_slot()
        resp = api_client.cancel_tour_slot(ctx["slot_id"], ADMIN)
        validate_success(resp)
        # party 10 also breaches the HIGH_VALUE safety cap of 4 (tier 7),
        # but the lifecycle gate (tier 5) fires first.
        resp = api_client.create_booking(
            {"slot_id": ctx["slot_id"], "booking_kind": "GENERAL",
             "visitor_name": "Zed", "party_size": 10},
            FRONT_DESK)
        validate_error(resp, ApiErrorId.ERR_SLOT_NOT_OPEN)

    def test_oversized_party_on_open_slot_returns_safety_error(self):
        """PRD section 2.7: "First, the party-cap rule: if any room on a tour
        route is `HIGH_VALUE`, no single tour party booked onto a slot of
        that route may exceed the smallest `safety_max_party` among the
        route's `HIGH_VALUE` rooms; violations are rejected with
        `ERR_SAFETY_PARTY_TOO_LARGE` (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/cancelled_slot_oversized_party_returns_slot_not_open
        """
        ctx = self._high_value_open_slot()
        # The slot is OPEN, so the state gate passes and the safety cap
        # (safety_max_party 4) fires in isolation.
        resp = api_client.create_booking(
            {"slot_id": ctx["slot_id"], "booking_kind": "GENERAL",
             "visitor_name": "Zed", "party_size": 10},
            FRONT_DESK)
        validate_error(resp, ApiErrorId.ERR_SAFETY_PARTY_TOO_LARGE)


class TestSeatCapacityBoundary:

    def _two_open_slots_with_three_seats_taken(self):
        """Capacity 8 each (room 10 minus buffer 2); a CONFIRMED party of 3
        on each leaves seats_available == 5 on both."""
        ctx = setup_active_route_with_script(
            room_specs=[{"name": "Parlor", "floor": 1, "capacity_max": 10,
                         "safety_max_party": 12,
                         "collection_tier": "STANDARD"}])
        docent = create_certified_docent([ctx["route_id"]])
        slot1 = create_slot(ctx["route_id"], start_at="2026-09-01T10:00:00Z")
        slot2 = create_slot(ctx["route_id"], start_at="2026-09-01T13:00:00Z")
        assign_and_confirm_lead(docent["id"], slot1["id"])
        assign_and_confirm_lead(docent["id"], slot2["id"])
        open_slot(slot1["id"])
        open_slot(slot2["id"])
        b1 = create_general_booking(slot1["id"], 3, visitor_name="Ann")
        confirm_booking(b1["id"], 3000)
        b2 = create_general_booking(slot2["id"], 3, visitor_name="Bob")
        confirm_booking(b2["id"], 3000)
        return ctx, slot1, slot2

    def test_exact_fit_accepted_and_fills_slot(self):
        """PRD section 3.6: "Capacity comes last: the `party_size` must not
        exceed the slot's `seats_available`, though a party exactly equal to
        the remaining seats is allowed; overcapacity is rejected with
        `ERR_CAPACITY_EXCEEDED` (HTTP 409)."
        PRD section 3.4: "when a booking creation or confirmation drives
        `seats_available` to exactly zero the slot flips from `OPEN` to
        `FULL`".

        Design: Difficulty/boundary_precision_check/seat_boundary_exact_fit_then_one_over
        """
        _ctx, slot1, _slot2 = \
            self._two_open_slots_with_three_seats_taken()
        resp = api_client.create_booking(
            {"slot_id": slot1["id"], "booking_kind": "GENERAL",
             "visitor_name": "Eve", "party_size": 5},
            FRONT_DESK)
        data = validate_success(resp, expected_status=201)
        assert data["status"] == "RESERVED", (
            "party_size equal to seats_available must be accepted "
            f"(inclusive boundary), got {data['status']}"
        )
        slot = get_slot(slot1["id"])
        assert slot["seats_available"] == 0
        assert slot["status"] == "FULL"

    def test_one_over_capacity_rejected(self):
        """PRD section 3.6: "Capacity comes last: the `party_size` must not
        exceed the slot's `seats_available`, though a party exactly equal to
        the remaining seats is allowed; overcapacity is rejected with
        `ERR_CAPACITY_EXCEEDED` (HTTP 409)."

        Design: Difficulty/boundary_precision_check/seat_boundary_exact_fit_then_one_over
        """
        _ctx, _slot1, slot2 = \
            self._two_open_slots_with_three_seats_taken()
        resp = api_client.create_booking(
            {"slot_id": slot2["id"], "booking_kind": "GENERAL",
             "visitor_name": "Fox", "party_size": 6},
            FRONT_DESK)
        validate_error(resp, ApiErrorId.ERR_CAPACITY_EXCEEDED)
        slot = get_slot(slot2["id"])
        assert slot["seats_available"] == 5, (
            f"a rejected booking must not consume seats, "
            f"got {slot['seats_available']}"
        )


class TestSafetyPartyCap:

    def test_safety_party_cap_high_value_room(self):
        """PRD section 2.7: "First, the party-cap rule: if any room on a tour
        route is `HIGH_VALUE`, no single tour party booked onto a slot of
        that route may exceed the smallest `safety_max_party` among the
        route's `HIGH_VALUE` rooms; violations are rejected with
        `ERR_SAFETY_PARTY_TOO_LARGE` (HTTP 422)."

        Design: Corner/validations/safety_party_cap_high_value_room
        """
        ctx = setup_open_slot(
            room_specs=[{"name": "Silver Closet", "floor": 1,
                         "capacity_max": 30, "safety_max_party": 4,
                         "collection_tier": "HIGH_VALUE"}],
            route_name="Silver Tour")
        resp = api_client.create_booking(
            {"slot_id": ctx["slot_id"], "booking_kind": "GENERAL",
             "visitor_name": "Big Party", "party_size": 5},
            FRONT_DESK)
        validate_error(resp, ApiErrorId.ERR_SAFETY_PARTY_TOO_LARGE)
        # The cap is inclusive: party 4 == safety_max_party books fine.
        data = create_general_booking(ctx["slot_id"], 4,
                                      visitor_name="Small Party")
        assert data["total_price_cents"] == 4000


class TestChaperoneRatioHighValue:

    def test_school_booking_high_value_ratio_8(self):
        """PRD section 2.7: "Third, the chaperone rule: the free-chaperone
        quota and the minimum-chaperone requirement for school groups divide
        by eight instead of ten whenever any room on the route is
        `HIGH_VALUE` (§3.6)."
        PRD section 3.6: "a school group must meet its chaperone quota — the
        required number of chaperones is the `student_count` divided by ten
        and rounded up to a whole chaperone, tightening to a divisor of eight
        when any room on the route is `HIGH_VALUE`, and the booking passes
        when `chaperone_count` is at least the requirement, with an exact
        match counting as a pass — else `ERR_CHAPERONE_RATIO_VIOLATION`
        (HTTP 422)."

        Design: Corner/validations/school_booking_high_value_ratio_8
        """
        ctx = setup_open_slot(
            room_specs=[{"name": "Silver Vault", "floor": 1,
                         "capacity_max": 40, "safety_max_party": 35,
                         "collection_tier": "HIGH_VALUE"}],
            route_kind="SCHOOL", base_price_cents=0,
            curriculum_standards=["HIST-5"], route_name="School Silver Tour")
        # ceil(17/8) = 3 > 2 chaperones -> violation.
        resp = api_client.create_booking(
            {"slot_id": ctx["slot_id"], "booking_kind": "SCHOOL",
             "visitor_name": "Roosevelt Middle", "student_count": 17,
             "chaperone_count": 2, "grade_level": "7",
             "curriculum_standard": "HIST-5"},
            FRONT_DESK)
        validate_error(resp, ApiErrorId.ERR_CHAPERONE_RATIO_VIOLATION)
        # ceil(16/8) = 2 == 2 chaperones -> exact match passes;
        # 15*800 + 1*700 = 12700, both chaperones free.
        data = validate_success(api_client.create_booking(
            {"slot_id": ctx["slot_id"], "booking_kind": "SCHOOL",
             "visitor_name": "Roosevelt Middle", "student_count": 16,
             "chaperone_count": 2, "grade_level": "7",
             "curriculum_standard": "HIST-5"},
            FRONT_DESK), expected_status=201)
        assert data["total_price_cents"] == 12700, (
            f"school total must be 12700, got {data['total_price_cents']}"
        )


class TestCurriculumAlignment:

    def test_curriculum_not_aligned_rejected(self):
        """PRD section 3.6: "The requested `curriculum_standard` must appear
        among the `curriculum_standards` of the route's currently `PUBLISHED`
        script, else `ERR_CURRICULUM_NOT_ALIGNED` (HTTP 422)."

        Design: Corner/validations/curriculum_not_aligned_rejected
        """
        ctx = setup_open_slot(
            room_specs=[{"name": "Schoolroom", "floor": 1, "capacity_max": 40,
                         "safety_max_party": 35,
                         "collection_tier": "STANDARD"}],
            route_kind="SCHOOL", base_price_cents=0,
            curriculum_standards=["HIST-5"], route_name="School Tour")
        resp = api_client.create_booking(
            {"slot_id": ctx["slot_id"], "booking_kind": "SCHOOL",
             "visitor_name": "Roosevelt Middle", "student_count": 10,
             "chaperone_count": 1, "grade_level": "7",
             "curriculum_standard": "ART-2"},
            FRONT_DESK)
        validate_error(resp, ApiErrorId.ERR_CURRICULUM_NOT_ALIGNED)


class TestMemberStanding:

    def test_member_lapsed_booking_rejected(self):
        """PRD section 3.6: "A `MEMBER` booking also requires the member to
        be `ACTIVE`; booking with a `LAPSED` or `EXPIRED` member is rejected
        with `ERR_MEMBER_NOT_ACTIVE` (HTTP 422)."
        PRD section 3.5: "On each run, an `ACTIVE` member whose `renews_on`
        has passed — the renewal date is earlier than the current date —
        slips to `LAPSED`".

        Design: Corner/validations/member_lapsed_booking_rejected
        """
        ctx = setup_open_slot()
        member = create_member(renews_on="2026-08-10")
        set_clock("2026-08-11T00:00:00Z")
        run_epoch()
        resp = api_client.create_booking(
            {"slot_id": ctx["slot_id"], "booking_kind": "MEMBER",
             "visitor_name": "Mel", "party_size": 1,
             "member_id": member["id"]},
            FRONT_DESK)
        validate_error(resp, ApiErrorId.ERR_MEMBER_NOT_ACTIVE)


class TestPaymentEquality:

    def test_payment_mismatch_rejected(self):
        """PRD section 3.6: "The request carries `paid_cents`, which must
        equal the booking's `total_price_cents` exactly; any discrepancy is
        rejected with `ERR_PAYMENT_MISMATCH` (HTTP 422)."

        Design: Corner/validations/payment_mismatch_rejected
        """
        ctx = setup_open_slot()
        booking = create_general_booking(ctx["slot_id"], 2)
        assert booking["total_price_cents"] == 2000
        resp = api_client.confirm_booking(
            booking["id"], {"paid_cents": 1999}, FRONT_DESK)
        validate_error(resp, ApiErrorId.ERR_PAYMENT_MISMATCH)
        after = get_booking(booking["id"])
        assert after["status"] == "RESERVED", (
            f"a rejected confirm must leave the booking RESERVED, "
            f"got {after['status']}"
        )


class TestMemberBookingOwnership:

    def test_member_cannot_book_for_other_member_forbidden(self):
        """PRD section 2.1: "Additionally, a caller in the `Member` role may
        only create bookings whose `booking_kind` is `MEMBER` and whose
        `member_id` equals their own `X-User-ID` — any other creation by a
        member is rejected with `ERR_FORBIDDEN`."

        Design: Corner/rbac/member_cannot_book_for_other_member_forbidden
        """
        ctx = setup_open_slot()
        m1 = create_member(full_name="Mel Member", email="mel@x.org",
                           member_number="M-100")
        m2 = create_member(full_name="Ned Member", email="ned@x.org",
                           member_number="M-200")
        resp = api_client.create_booking(
            {"slot_id": ctx["slot_id"], "booking_kind": "MEMBER",
             "visitor_name": "Ned", "party_size": 2, "member_id": m2["id"]},
            make_member_headers(m1["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
