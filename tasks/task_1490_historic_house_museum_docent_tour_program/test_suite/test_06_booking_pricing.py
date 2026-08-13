"""Booking pricing: server-computed totals, the candlelight rounding order,
member free admission, and the school tier schedule."""
from test_helpers import (
    TEST_USERS,
    api_client,
    assert_booking,
    confirm_booking,
    create_member,
    create_member_booking,
    create_school_booking,
    make_member_headers,
    setup_open_slot,
    validate_success,
)

FRONT_DESK = TEST_USERS["front_desk_staff_headers"]


class TestServerComputedPricing:

    def test_booking_computed_price_client_input_ignored(self):
        """PRD section 3.6: "Pricing is computed and frozen on the booking at
        the instant of creation, in integer cents under the rounding rules of
        §2.6."
        PRD section 2.10: "A booking's `unit_price_cents` and
        `total_price_cents` are likewise frozen at booking creation."

        Design: Corner/entities/booking_computed_price_client_input_ignored
        """
        ctx = setup_open_slot()
        resp = api_client.create_booking(
            {"slot_id": ctx["slot_id"], "booking_kind": "GENERAL",
             "visitor_name": "Ann", "party_size": 2, "total_price_cents": 1},
            FRONT_DESK)
        data = validate_success(resp, expected_status=201)
        assert_booking(data)
        # 2 x 1000 base = 2000; the smuggled total_price_cents: 1 is ignored.
        assert data["total_price_cents"] == 2000, (
            f"server-computed total must be authoritative, "
            f"got {data['total_price_cents']}"
        )


class TestCandlelightRoundingOrder:
    """base 1055: round per person first (1583), then multiply by headcount."""

    def test_candlelight_unit_price_rounded_per_person_first(self):
        """PRD section 2.6: "One rounding-order rule is pinned and
        load-bearing: when a per-person price is scaled (the candlelight
        multiplier), the per-person amount is rounded half-up to a whole cent
        first, and only then multiplied by the headcount — never multiply
        first and round the product."
        PRD section 3.6: "the booking's `unit_price_cents` records that
        per-person figure".

        Design: Difficulty/combinatorial_formula/candlelight_price_round_per_person_then_multiply
        """
        ctx = setup_open_slot(route_kind="CANDLELIGHT", base_price_cents=1055)
        resp = api_client.create_booking(
            {"slot_id": ctx["slot_id"], "booking_kind": "GENERAL",
             "visitor_name": "Kai", "party_size": 3},
            FRONT_DESK)
        data = validate_success(resp, expected_status=201)
        # round_half_up(1055 * 1.5) = round_half_up(1582.5) = 1583
        assert data["unit_price_cents"] == 1583, (
            f"per-person unit must be rounded first: 1583, "
            f"got {data['unit_price_cents']}"
        )

    def test_candlelight_total_is_unit_times_headcount(self):
        """PRD section 3.6: "For `GENERAL`, the per-person unit is the
        route's `base_price_cents`, except on a `CANDLELIGHT` route, where
        the unit is one and a half times the base, rounded half-up to a whole
        cent per person before anything is multiplied; the booking's
        `unit_price_cents` records that per-person figure, and
        `total_price_cents` is the unit multiplied by `party_size` — round
        per person first, then multiply by headcount, never the reverse."

        Design: Difficulty/combinatorial_formula/candlelight_price_round_per_person_then_multiply
        """
        ctx = setup_open_slot(route_kind="CANDLELIGHT", base_price_cents=1055)
        resp = api_client.create_booking(
            {"slot_id": ctx["slot_id"], "booking_kind": "GENERAL",
             "visitor_name": "Kai", "party_size": 3},
            FRONT_DESK)
        data = validate_success(resp, expected_status=201)
        # 1583 * 3 = 4749; multiply-then-round would yield
        # round_half_up(3165 * 1.5) = 4748.
        assert data["total_price_cents"] == 4749, (
            f"total must be 1583 * 3 = 4749, got {data['total_price_cents']}"
        )
        assert data["total_price_cents"] != 4748


class TestMemberFreeAdmission:

    def test_member_free_admission_party_price(self):
        """PRD section 3.6: "For `MEMBER`, the unit is computed exactly as
        for `GENERAL`, candlelight multiplier included, but the member's own
        seat is free, so `total_price_cents` is the unit multiplied by
        `party_size` minus one; a solo active member therefore pays zero."

        Design: Corner/calculations/member_free_admission_party_price
        """
        ctx = setup_open_slot()
        member = create_member()
        data = create_member_booking(ctx["slot_id"], member["id"], 3)
        assert_booking(data)
        assert data["unit_price_cents"] == 1000
        # (3 - 1) x 1000: the member's own seat is free.
        assert data["total_price_cents"] == 2000, (
            f"member party of 3 must pay for 2 guests only, "
            f"got {data['total_price_cents']}"
        )

    def test_member_solo_booking_zero_total_confirms_free(self):
        """PRD section 3.6: "For `MEMBER`, the unit is computed exactly as
        for `GENERAL`, candlelight multiplier included, but the member's own
        seat is free, so `total_price_cents` is the unit multiplied by
        `party_size` minus one; a solo active member therefore pays zero."
        PRD section 3.6: "The request carries `paid_cents`, which must equal
        the booking's `total_price_cents` exactly; any discrepancy is
        rejected with `ERR_PAYMENT_MISMATCH` (HTTP 422)."
        PRD section 3.6: "Members confirm their own bookings; the desk and
        admin confirm anyone's."

        Design: Corner/calculations/member_solo_booking_zero_total_confirms_free
        """
        ctx = setup_open_slot()
        member = create_member()
        booking = create_member_booking(ctx["slot_id"], member["id"], 1)
        assert booking["total_price_cents"] == 0, (
            f"a solo active member must pay zero, "
            f"got {booking['total_price_cents']}"
        )
        confirmed = confirm_booking(
            booking["id"], 0, headers=make_member_headers(member["id"]))
        assert confirmed["status"] == "CONFIRMED"


class TestSchoolPricing:

    def _school_slot(self):
        return setup_open_slot(
            room_specs=[{"name": "Schoolroom", "floor": 1, "capacity_max": 40,
                         "safety_max_party": 35,
                         "collection_tier": "STANDARD"}],
            route_kind="SCHOOL", base_price_cents=0,
            curriculum_standards=["HIST-5"], route_name="School Tour")

    def test_school_tiered_price_marginal_rates(self):
        """PRD section 3.6: "For `SCHOOL`, students are charged in tiers —
        the first fifteen students at 800 cents each, the next fifteen
        (students sixteen through thirty) at 700 cents each, and every
        student beyond the thirtieth at 600 cents each — and chaperones are
        free up to the same rounded-up quota used by the chaperone
        requirement (divisor ten, or eight with a `HIGH_VALUE` room on the
        route), with each chaperone beyond the free quota costing 1000 cents".
        PRD section 3.6: "`SCHOOL` bookings are the mirror image, forbidden
        from passing `party_size` (their party size is computed as
        `student_count` plus `chaperone_count`)".

        Design: Corner/calculations/school_tiered_price_marginal_rates
        """
        ctx = self._school_slot()
        data = create_school_booking(ctx["slot_id"], student_count=20,
                                     chaperone_count=2)
        assert_booking(data)
        assert data["party_size"] == 22, (
            f"school party_size must be 20 + 2 = 22, got {data['party_size']}"
        )
        # 15*800 + 5*700 = 15500; ceil(20/10) = 2 chaperones are free.
        assert data["total_price_cents"] == 15500, (
            f"school total must be 15500, got {data['total_price_cents']}"
        )

    def test_school_extra_chaperone_flat_fee(self):
        """PRD section 3.6: "For `SCHOOL`, students are charged in tiers —
        the first fifteen students at 800 cents each, the next fifteen
        (students sixteen through thirty) at 700 cents each, and every
        student beyond the thirtieth at 600 cents each — and chaperones are
        free up to the same rounded-up quota used by the chaperone
        requirement (divisor ten, or eight with a `HIGH_VALUE` room on the
        route), with each chaperone beyond the free quota costing 1000 cents;
        `total_price_cents` is the student charge plus the extra-chaperone
        charge".

        Design: Corner/calculations/school_extra_chaperone_flat_fee
        """
        ctx = self._school_slot()
        data = create_school_booking(ctx["slot_id"], student_count=10,
                                     chaperone_count=3)
        # 10*800 + (3 - ceil(10/10)) * 1000 = 8000 + 2000 = 10000
        assert data["total_price_cents"] == 10000, (
            f"school total must be 10000, got {data['total_price_cents']}"
        )
