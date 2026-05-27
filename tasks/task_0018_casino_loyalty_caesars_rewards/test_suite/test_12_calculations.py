"""Calculation corners: DIAMOND SLOTS tier accrual, GOLD REGIONAL
provisional comp rate, per-session round-half-up precision."""
import pytest

from test_helpers import (
    validate_success,
    set_clock,
    create_property,
    create_member,
    record_gaming_session,
    get_member_version,
    create_booking,
    make_loyalty_manager_headers,
    make_member_services_headers,
)


class TestTierCreditAccrualDiamondSlots:
    """PRD §3.3: SLOTS at DIAMOND uses tier multiplier 1.50."""

    def test_diamond_slots_5000_loss_yields_7500_tc(self, api):
        """PRD §3.3: "DIAMOND of one and one-half ... The final value is
        rounded half-up to two decimal places — this rounding is done per
        session, before the value is added to any running total — and
        stored on the session as tier_credits_earned."

        Calculation: base = 500000/100 = 5000; * 1.0 (SLOTS) = 5000;
        * 1.50 (DIAMOND) = 7500.00.

        Design: Corner/calculations/tier_credit_accrual_diamond_slots_correct
        """
        set_clock("2026-02-01T00:00:00Z")
        prop = create_property()
        mem = create_member(
            property_id=prop["id"], full_name="D", email="d@x.com",
        )
        # Promote GOLD → DIAMOND in one SLOTS session: $75000 loss = 7_500_000
        # cents → base=75000, *1.0, *1.0 = 75000 TC → ytd=75000 → DIAMOND.
        record_gaming_session(
            member_id=mem["id"], property_id=prop["id"],
            started_at="2026-02-01T01:00:00Z",
            ended_at="2026-02-01T02:00:00Z",
            game_type="SLOTS", theoretical_loss_cents=7_500_000,
        )
        # Subsequent SLOTS $5000 loss at DIAMOND.
        resp = api.create_gaming_session(
            {
                "member_id": mem["id"], "property_id": prop["id"],
                "started_at": "2026-02-01T03:00:00Z",
                "ended_at": "2026-02-01T04:00:00Z",
                "game_type": "SLOTS",
                "theoretical_loss_cents": 500000,
            },
            make_member_services_headers("ms_1"),
        )
        data = validate_success(resp, expected_status=201)
        assert data["tier_credits_earned"] == pytest.approx(7500.00, abs=0.01), (
            f"DIAMOND SLOTS $5000 loss: expected 7500.00 TC, "
            f"got {data['tier_credits_earned']}"
        )


class TestCompRoomRateGoldRegional:
    """PRD §3.6: GOLD at REGIONAL: discount=0.10, market=1.00."""

    def test_gold_regional_base_20000_provisional_rate_18000(self, api):
        """PRD §3.6: "The provisional rate begins from the property's
        base_room_rate_cents and applies, in order, two multipliers. The
        first is the tier-driven comp discount, which represents the
        fraction of the base rate that the casino is waiving: ten
        one-hundredths for GOLD ... The second multiplier is the
        market-segment band — ... one for REGIONAL".

        step_a = round_half_up(20000 * (1 - 0.10)) = 18000
        step_b = round_half_up(18000 * 1.00)        = 18000.

        Design: Corner/calculations/comp_room_rate_gold_member_regional_property_provisional
        """
        set_clock("2026-02-10T00:00:00Z")
        prop = create_property(
            name="CP-Reg", market_segment="REGIONAL",
            base_room_rate_cents=20000,
        )
        mem = create_member(
            property_id=prop["id"], full_name="G", email="gg@x.com",
        )
        v = get_member_version(mem["id"])
        booking = create_booking(
            member_id=mem["id"], property_id=prop["id"],
            expected_member_version=v,
            check_in="2026-03-10T15:00:00Z",
            check_out="2026-03-11T11:00:00Z",
        )
        assert booking["provisional_rate_cents"] == 18000, (
            f"GOLD REGIONAL base=20000 should give provisional 18000, "
            f"got {booking['provisional_rate_cents']}"
        )
        assert booking["nights"] == 1
        assert booking["total_charge_cents"] == 18000


class TestTierCreditAccrualPerSessionRounding:
    """PRD §2.7: per-session round_half_up to 2 decimal places."""

    def test_platinum_slots_333_cents_rounds_to_4_16(self, api):
        """PRD §2.7: "Tier-Credit accrual produces a per-session credit
        value rounded half-up to two decimal places before being added to
        the member's year-to-date and lifetime running totals; the
        rounding happens once per session, never on the running total."

        Calculation: base = 333/100 = 3.33; * 1.0 (SLOTS) = 3.33;
        * 1.25 (PLATINUM) = 4.1625; round_half_up(2dp) = 4.16.

        Design: Corner/calculations/tier_credit_accrual_per_session_rounding_precision
        """
        set_clock("2026-02-12T00:00:00Z")
        prop = create_property()
        mem = create_member(
            property_id=prop["id"], full_name="PR", email="pr@x.com",
        )
        # Promote to PLATINUM: SLOTS $15000 → 15000 TC.
        record_gaming_session(
            member_id=mem["id"], property_id=prop["id"],
            started_at="2026-02-12T01:00:00Z",
            ended_at="2026-02-12T02:00:00Z",
            game_type="SLOTS", theoretical_loss_cents=1_500_000,
        )
        resp = api.create_gaming_session(
            {
                "member_id": mem["id"], "property_id": prop["id"],
                "started_at": "2026-02-12T03:00:00Z",
                "ended_at": "2026-02-12T04:00:00Z",
                "game_type": "SLOTS",
                "theoretical_loss_cents": 333,
            },
            make_member_services_headers("ms_1"),
        )
        data = validate_success(resp, expected_status=201)
        assert data["tier_credits_earned"] == pytest.approx(4.16, abs=0.001), (
            f"PLATINUM SLOTS 333 cents: 3.33 * 1.0 * 1.25 = 4.1625, "
            f"round_half_up(2dp) = 4.16; got {data['tier_credits_earned']}"
        )
