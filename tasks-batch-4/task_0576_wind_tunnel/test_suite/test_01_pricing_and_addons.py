"""Booking price and add-on statement calculations (PRD §3.3, §3.8, §2.5)."""
from test_helpers import (
    TEST_USERS,
    add_coaching,
    make_member,
    make_membership,
    make_package,
    setup_member_with_scheduled_flight_and_membership,
    validate_success,
)

FRONTDESK = TEST_USERS["frontdesk_headers"]
MANAGER = TEST_USERS["manager_headers"]


class TestWalkInVsReservationPricing:
    """Same base and party size, two pricing variants diverge."""

    def _pkg_and_member(self, api):
        pkg = make_package(api, name="First Flight", included_minutes=2, base_price_cents=6000)
        member = make_member(api, name="Ada", weight_kg=80)
        return pkg, member

    def test_walk_in_surcharge_price(self, api):
        """PRD §3.3: "For a `WALK_IN`, multiply the subtotal by 1.20 — a
        twenty-percent walk-in surcharge — and disregard `lead_days` completely."
        PRD §3.3: "Choose a party multiplier by size: exactly 1.00 for a party of
        one or two, 0.95 for a party of three or four, and 0.90 for a party of five
        or more."

        Design: Difficulty/dual_variant_calc/booking_price_walk_in_vs_reservation
        """
        pkg, member = self._pkg_and_member(api)
        resp = api.create_booking(
            {"member_id": member["id"], "package_id": pkg["id"],
             "booking_type": "WALK_IN", "party_size": 2},
            FRONTDESK,
        )
        booking = validate_success(resp, 201)
        assert booking["total_price_cents"] == 14400, booking["total_price_cents"]

    def test_reservation_lead_discount_price(self, api):
        """PRD §3.3: "For a `RESERVATION`, apply a lead-time discount instead: no
        discount when `lead_days` is fewer than 3, a five-percent discount (multiply
        by 0.95) when `lead_days` is at least 3 but fewer than 7, and a ten-percent
        discount (multiply by 0.90) when `lead_days` is 7 or more. A reservation
        carries no surcharge."

        Design: Difficulty/dual_variant_calc/booking_price_walk_in_vs_reservation
        """
        pkg, member = self._pkg_and_member(api)
        resp = api.create_booking(
            {"member_id": member["id"], "package_id": pkg["id"],
             "booking_type": "RESERVATION", "party_size": 2, "lead_days": 7},
            FRONTDESK,
        )
        booking = validate_success(resp, 201)
        assert booking["total_price_cents"] == 10800, booking["total_price_cents"]


class TestCombinatorialPricing:
    """Three tiered inputs interact under a single final rounding."""

    def _setup(self, api):
        pkg = make_package(api, name="Group", included_minutes=2, base_price_cents=6000)
        member = make_member(api, name="Bo", weight_kg=70, experience_status="RETURNING")
        make_membership(api, member["id"], "PRO")
        return pkg, member

    def test_party_lead_membership_combined_price(self, api):
        """PRD §3.3: "Apply the member discount by multiplying by one minus the
        member's rate: 0.00 for `NONE`, 0.10 for `STANDARD`, 0.15 for `PRO`."
        PRD §3.3: "Round the single final product to a whole number of cents using
        round-half-up. Only this one rounding occurs; the intermediate products are
        not rounded."

        Design: Difficulty/combinatorial_formula/booking_price_tiered_party_lead_membership_mode_a
        """
        pkg, member = self._setup(api)
        resp = api.create_booking(
            {"member_id": member["id"], "package_id": pkg["id"],
             "booking_type": "RESERVATION", "party_size": 3, "lead_days": 7},
            FRONTDESK,
        )
        booking = validate_success(resp, 201)
        assert booking["total_price_cents"] == 13082, booking["total_price_cents"]

    def test_party_lead_membership_price_persisted(self, api):
        """PRD §3.3: "Round the single final product to a whole number of cents using
        round-half-up. Only this one rounding occurs; the intermediate products are
        not rounded."

        Design: Difficulty/combinatorial_formula/booking_price_tiered_party_lead_membership_mode_a
        """
        pkg, member = self._setup(api)
        created = validate_success(
            api.create_booking(
                {"member_id": member["id"], "package_id": pkg["id"],
                 "booking_type": "RESERVATION", "party_size": 3, "lead_days": 7},
                FRONTDESK,
            ),
            201,
        )
        reread = validate_success(api.get_booking(created["id"], FRONTDESK), 200)
        assert reread["total_price_cents"] == 13082, reread["total_price_cents"]


class TestAddonStatementRounding:
    """Per-line rounding before summation is authoritative."""

    def _setup(self, api):
        ctx = setup_member_with_scheduled_flight_and_membership(api, tier="STANDARD")
        return ctx

    def test_per_line_video_and_coaching_charges(self, api):
        """PRD §3.8: "The flight's `video_charge_cents` is computed as 3335 cents
        multiplied by one minus the member's discount rate, rounded half-up to a
        whole cent."
        PRD §3.8: "Its `charge_cents` is computed as 1245 cents per minute multiplied
        by the purchased `minutes`, then by one minus the member's discount rate,
        rounded half-up to a whole cent."

        Design: Difficulty/combinatorial_formula/addon_statement_round_per_line_mode_b
        """
        ctx = self._setup(api)
        flight = validate_success(api.purchase_video(ctx["flight"]["id"], FRONTDESK), 200)
        assert flight["video_charge_cents"] == 3002, flight["video_charge_cents"]
        coaching = add_coaching(api, ctx["flight"]["id"], ctx["instructor"]["id"], 3)
        assert coaching["charge_cents"] == 3362, coaching["charge_cents"]

    def test_outstanding_addon_round_per_line_sum(self, api):
        """PRD §3.8: "The member's `outstanding_addon_cents` is the sum of these
        per-line charges: the sum of each video flight's rounded line plus the sum of
        each non-cancelled coaching booking's rounded line."
        PRD §3.8: "Because each line is rounded before summation, this total can
        differ from rounding a raw sum, and the per-line rounding is authoritative."

        Design: Difficulty/combinatorial_formula/addon_statement_round_per_line_mode_b
        """
        ctx = self._setup(api)
        api.purchase_video(ctx["flight"]["id"], FRONTDESK)
        add_coaching(api, ctx["flight"]["id"], ctx["instructor"]["id"], 3)
        member = validate_success(api.get_member(ctx["member"]["id"], FRONTDESK), 200)
        assert member["outstanding_addon_cents"] == 6364, member["outstanding_addon_cents"]


def test_booking_price_visible_in_create_response(api):
    """PRD §3.3: "For a `WALK_IN`, multiply the subtotal by 1.20 — a twenty-percent
    walk-in surcharge — and disregard `lead_days` completely."
    PRD §2.5: "the system applies every downstream effect atomically as part of the
    triggering request."

    Design: Corner/consistency_model/booking_price_visible_in_create_response
    """
    pkg = make_package(api, name="P", included_minutes=2, base_price_cents=6000)
    member = make_member(api, name="Ada", weight_kg=80)
    resp = api.create_booking(
        {"member_id": member["id"], "package_id": pkg["id"],
         "booking_type": "WALK_IN", "party_size": 1},
        FRONTDESK,
    )
    booking = validate_success(resp, 201)
    assert booking["total_price_cents"] == 7200, booking["total_price_cents"]


def test_booking_minutes_included_computed(api):
    """PRD §3.3: "On creation the booking's minute pool is fixed: `minutes_included`
    is the `party_size` multiplied by the package's `included_minutes`, and
    `minutes_remaining` starts equal to `minutes_included`."

    Design: Corner/entities/booking_minutes_included_computed
    """
    pkg = make_package(api, name="P", included_minutes=2, base_price_cents=6000)
    member = make_member(api, name="Ada", weight_kg=80)
    booking = validate_success(
        api.create_booking(
            {"member_id": member["id"], "package_id": pkg["id"],
             "booking_type": "WALK_IN", "party_size": 3},
            FRONTDESK,
        ),
        201,
    )
    assert booking["minutes_included"] == 6, booking["minutes_included"]
    assert booking["minutes_remaining"] == 6, booking["minutes_remaining"]


def test_membership_discount_pct_computed(api):
    """PRD §3.2: "The membership's `discount_pct` is a computed rate — 0.10 (ten
    percent) for `STANDARD` and 0.15 (fifteen percent) for `PRO` — and its `status`
    begins `ACTIVE`. While a membership is `ACTIVE`, the owning member's computed
    `membership_tier` mirrors the membership's tier".

    Design: Corner/entities/membership_discount_pct_computed
    """
    member = make_member(api, name="Bo", weight_kg=70, experience_status="RETURNING")
    membership = validate_success(
        api.create_membership({"member_id": member["id"], "tier": "PRO"}, FRONTDESK), 201
    )
    assert membership["discount_pct"] == 0.15, membership["discount_pct"]
    reread = validate_success(api.get_member(member["id"], FRONTDESK), 200)
    assert reread["membership_tier"] == "PRO", reread["membership_tier"]
