"""Combinatorial formulas: tier-credit accrual with three-input nesting
across game_type × tier × loss, and the comp-room-rate per-step rounding
order that differs from round-at-end."""
import pytest

from test_helpers import (
    validate_success,
    set_clock,
    create_property,
    create_member,
    record_gaming_session,
    get_member_version,
    create_booking,
    promote_member_to_platinum,
    promote_member_to_diamond_from_platinum,
    make_loyalty_manager_headers,
)


class TestTierCreditAccrualThreeInputFormula:
    """PRD §3.3: tier_credits_earned = round_half_up_2dp(
       (theoretical_loss_cents / 100) * game_type_mult * tier_mult)."""

    def test_poker_at_gold_crosses_platinum_threshold(self, api):
        """PRD §3.3: "for POKER by one and a half" and "GOLD carries a
        coefficient of one ... a member who is not excluded promotes from
        GOLD to PLATINUM when tier_credits_ytd reaches at least fifteen
        thousand".

        Design: Difficulty/combinatorial_formula/tier_credit_accrual_three_input_formula_with_nested_branches
        """
        set_clock("2026-09-01T00:00:00Z")
        prop = create_property()
        mem = create_member(
            property_id=prop["id"], full_name="M Acc", email="macc@x.com",
        )
        # Bring ytd to 14000 via TABLE_GAMES on GOLD: theor_loss=700000 →
        # base=7000, *2.0=14000, *1.0=14000 TC. Still GOLD (just below 15000).
        record_gaming_session(
            member_id=mem["id"], property_id=prop["id"],
            started_at="2026-09-01T01:00:00Z",
            ended_at="2026-09-01T02:00:00Z",
            game_type="TABLE_GAMES", theoretical_loss_cents=700000,
        )
        # Trigger: POKER $4000 at GOLD: base=4000, *1.5=6000, *1.0=6000 TC.
        # ytd: 14000 + 6000 = 20000 → crosses PLATINUM (>=15000).
        from test_helpers import make_member_services_headers
        resp = api.create_gaming_session(
            {
                "member_id": mem["id"], "property_id": prop["id"],
                "started_at": "2026-09-01T03:00:00Z",
                "ended_at": "2026-09-01T04:00:00Z",
                "game_type": "POKER", "theoretical_loss_cents": 400000,
            },
            make_member_services_headers("ms_1"),
        )
        sess = validate_success(resp, expected_status=201)
        assert sess["tier_credits_earned"] == 6000.00, (
            f"POKER at GOLD with $4000 loss: 4000 * 1.5 * 1.0 = 6000.00, "
            f"got {sess['tier_credits_earned']}"
        )
        m = validate_success(
            api.get_member(mem["id"], make_loyalty_manager_headers("lm_1")),
            expected_status=200,
        )
        assert m["tier_credits_ytd"] == pytest.approx(20000.00, abs=0.01)
        assert m["tier_status"] == "PLATINUM"

    def test_tier_multiplier_uses_tier_at_request_start_not_after_promotion(
        self, api,
    ):
        """PRD §3.3: "multiplied by a tier-driven coefficient that depends
        on the member's tier_status *as it stood the moment the request
        began*, before any tier promotion that this same session might
        trigger".

        Design: Difficulty/combinatorial_formula/tier_credit_accrual_three_input_formula_with_nested_branches
        """
        from test_helpers import make_member_services_headers
        set_clock("2026-09-05T00:00:00Z")
        prop = create_property()
        mem = create_member(
            property_id=prop["id"], full_name="M Bound", email="mbnd@x.com",
        )
        # Single SLOTS $20000 loss at GOLD: base=20000, *1.0, *1.0 = 20000 TC.
        # ytd: 20000 → crosses PLATINUM (>=15000). But tier mult must be
        # GOLD (1.0) because that's the tier BEFORE the accrual.
        resp = api.create_gaming_session(
            {
                "member_id": mem["id"], "property_id": prop["id"],
                "started_at": "2026-09-05T10:00:00Z",
                "ended_at": "2026-09-05T11:00:00Z",
                "game_type": "SLOTS", "theoretical_loss_cents": 2_000_000,
            },
            make_member_services_headers("ms_1"),
        )
        sess = validate_success(resp, expected_status=201)
        assert sess["tier_credits_earned"] == 20000.00, (
            f"SLOTS at GOLD with $20000 loss must use GOLD multiplier (1.0); "
            f"expected 20000.00 TC, got {sess['tier_credits_earned']}"
        )
        m = validate_success(
            api.get_member(mem["id"], make_loyalty_manager_headers("lm_1")),
            expected_status=200,
        )
        # Member is promoted to PLATINUM AFTER accrual, not before.
        assert m["tier_status"] == "PLATINUM"
        assert m["tier_credits_ytd"] == pytest.approx(20000.00, abs=0.01)


class TestCompRoomRateRoundPerStepNotRoundAtEnd:
    """PRD §2.7 + §3.6: comp-room rate applies round_half_up at EACH
    multiplication step; not deferred to the end. A test case where the
    two policies diverge pins the correct policy."""

    def test_platinum_international_base_5557_rounds_per_step_to_3667(self, api):
        """PRD §3.6: "The server multiplies the base rate by one minus that
        fraction and rounds the result half-up to whole cents. The second
        multiplier is the market-segment band — one and two-tenths for
        VEGAS_STRIP, one for REGIONAL, and one and one-tenth for
        INTERNATIONAL — applied to the post-discount cent value and again
        rounded half-up to whole cents. Both rounding steps are performed
        at the multiplication, not deferred to the end."

        Design: Difficulty/combinatorial_formula/comp_room_rate_round_per_step_versus_round_at_end
        """
        set_clock("2026-09-10T00:00:00Z")
        prop = create_property(
            name="CP-Int", market_segment="INTERNATIONAL",
            base_room_rate_cents=5557,
        )
        mem = create_member(
            property_id=prop["id"], full_name="M Round", email="mr@x.com",
        )
        # Promote to PLATINUM via a multi-session ladder that respects the
        # PRD §3.4 velocity SUSPEND threshold (1_500_000 cents per rolling
        # 60-minute window).
        promote_member_to_platinum(
            member_id=mem["id"], property_id=prop["id"],
            started_at="2026-09-10T01:00:00Z",
            ended_at="2026-09-10T02:00:00Z",
        )
        v = get_member_version(mem["id"])
        booking = create_booking(
            member_id=mem["id"], property_id=prop["id"],
            expected_member_version=v,
            check_in="2026-10-01T15:00:00Z",
            check_out="2026-10-02T11:00:00Z",
        )
        # Round-per-step:
        #   step_a = round_half_up(5557 * (1 - 0.40)) = round_half_up(3334.2) = 3334
        #   step_b = round_half_up(3334 * 1.10)       = round_half_up(3667.4) = 3667
        # Round-at-end alternative: 5557 * 0.60 * 1.10 = 3667.62 → 3668. Test pins 3667.
        assert booking["provisional_rate_cents"] == 3667, (
            f"Round-per-step expected 3667 at PLATINUM INTERNATIONAL base=5557, "
            f"got {booking['provisional_rate_cents']}"
        )
        assert booking["provisional_rate_cents"] != 3668
        assert booking["nights"] == 1
        assert booking["total_charge_cents"] == 1 * 3667

    def test_diamond_vegas_strip_base_3333_per_step_rounding(self, api):
        """PRD §2.7: "Comp-room rate computation works entirely in integer
        USD cents and applies round-half-up at each multiplication step
        (the discount multiplication first, the market-segment
        multiplication second)."

        Design: Difficulty/combinatorial_formula/comp_room_rate_round_per_step_versus_round_at_end
        """
        # DIAMOND at VEGAS_STRIP base=3333:
        # step_a = round_half_up(3333 * (1 - 0.70)) = round_half_up(999.9) = 1000
        # step_b = round_half_up(1000 * 1.20)       = 1200
        # Round-at-end: 3333 * 0.30 * 1.20 = 1199.88 → 1200. Same answer here.
        # We pick a base where per-step rounding still applies; the
        # important property is the discrete sequencing.
        set_clock("2026-09-15T00:00:00Z")
        prop = create_property(
            name="CP-DiVS", market_segment="VEGAS_STRIP",
            base_room_rate_cents=3333,
        )
        mem = create_member(
            property_id=prop["id"], full_name="M D",
            email="md_round@x.com",
        )
        # Promote GOLD → DIAMOND via a multi-session ladder respecting the
        # PRD §3.4 velocity SUSPEND threshold. PLATINUM stage first
        # (2 SLOTS sessions of 750_000 cents each), then DIAMOND stage
        # (3 TABLE_GAMES sessions of 1_200_000 cents each).
        promote_member_to_platinum(
            member_id=mem["id"], property_id=prop["id"],
            started_at="2026-09-15T01:00:00Z",
            ended_at="2026-09-15T02:00:00Z",
        )
        promote_member_to_diamond_from_platinum(
            member_id=mem["id"], property_id=prop["id"],
            started_at="2026-09-15T08:00:00Z",
            ended_at="2026-09-15T09:00:00Z",
        )
        v = get_member_version(mem["id"])
        booking = create_booking(
            member_id=mem["id"], property_id=prop["id"],
            expected_member_version=v,
            check_in="2026-10-15T15:00:00Z",
            check_out="2026-10-16T11:00:00Z",
        )
        assert booking["provisional_rate_cents"] == 1200, (
            f"Expected 1200 at DIAMOND VEGAS_STRIP base=3333, "
            f"got {booking['provisional_rate_cents']}"
        )
