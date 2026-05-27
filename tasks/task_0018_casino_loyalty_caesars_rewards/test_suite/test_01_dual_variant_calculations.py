"""Dual-variant calculations: PROVISIONAL vs FINAL comp-room rate across a
tier crossing, and the same gaming-session input driving two distinct
calculation domains (tier accrual + velocity monitor)."""
import pytest

from test_helpers import (
    validate_success,
    set_clock,
    create_property,
    create_member,
    record_gaming_session,
    get_member_version,
    create_booking,
    confirm_booking,
    check_in_booking,
    promote_member_to_platinum,
    promote_member_to_diamond_from_platinum,
    make_loyalty_manager_headers,
    make_member_services_headers,
)


class TestCompRoomRateProvisionalVsFinalAcrossTierCrossing:
    """PRD §3.6: PROVISIONAL is frozen at booking creation; FINAL is
    recomputed at check-in using the member's tier_status at that instant.
    When the member's tier changes between creation and check-in, the two
    variants diverge."""

    def test_provisional_uses_tier_at_booking_creation(self, api):
        """PRD §3.6: "The provisional rate is computed using the member's
        tier_status at the instant of booking creation."

        Design: Difficulty/dual_variant_calc/comp_room_rate_provisional_vs_final_tier_crossing
        """
        # PLATINUM member at VEGAS_STRIP base=30000:
        # step_a = round_half_up(30000 * (1 - 0.40)) = 18000
        # step_b = round_half_up(18000 * 1.20)      = 21600
        set_clock("2026-06-15T00:00:00Z")
        prop = create_property(
            name="CP-LV", market_segment="VEGAS_STRIP",
            base_room_rate_cents=30000,
        )
        mem = create_member(
            property_id=prop["id"], full_name="M One", email="m1@x.com",
        )
        # Promote to PLATINUM via a multi-session ladder that respects the
        # PRD §3.4 velocity SUSPEND threshold (1_500_000 cents per rolling
        # 60-minute window).
        promote_member_to_platinum(
            member_id=mem["id"], property_id=prop["id"],
            started_at="2026-06-15T01:00:00Z",
            ended_at="2026-06-15T02:00:00Z",
        )
        v = get_member_version(mem["id"])
        booking = create_booking(
            member_id=mem["id"], property_id=prop["id"],
            expected_member_version=v,
            check_in="2026-07-01T15:00:00Z",
            check_out="2026-07-03T11:00:00Z",
        )
        assert booking["provisional_rate_cents"] == 21600, (
            f"Expected provisional 21600 at PLATINUM VEGAS_STRIP base=30000, "
            f"got {booking['provisional_rate_cents']}"
        )
        # nights = ceil((2026-07-03T11:00 - 2026-07-01T15:00) / 86400s) = ceil(44h/24h) = 2.
        assert booking["nights"] == 2
        assert booking["total_charge_cents"] == 2 * 21600
        assert booking["status"] == "PENDING"
        assert booking["final_rate_cents"] is None

    def test_final_uses_tier_at_check_in_diverging_from_provisional(self, api):
        """PRD §3.6: "At check-in the server recomputes the same rate formula
        in its final variant: same base rate (re-read from the property),
        same discount-then-market sequence of multiplications, same per-step
        round-half-up, but using the member's tier_status at the moment of
        check-in. The result is stored as final_rate_cents, and
        total_charge_cents is overwritten as nights multiplied by
        final_rate_cents."

        Design: Difficulty/dual_variant_calc/comp_room_rate_provisional_vs_final_tier_crossing
        """
        set_clock("2026-06-15T00:00:00Z")
        prop = create_property(
            name="CP-LV", market_segment="VEGAS_STRIP",
            base_room_rate_cents=30000,
        )
        mem = create_member(
            property_id=prop["id"], full_name="M One", email="m1@x.com",
        )
        # Promote to PLATINUM via a multi-session ladder that respects the
        # PRD §3.4 velocity SUSPEND threshold (1_500_000 cents per rolling
        # 60-minute window).
        promote_member_to_platinum(
            member_id=mem["id"], property_id=prop["id"],
            started_at="2026-06-15T01:00:00Z",
            ended_at="2026-06-15T02:00:00Z",
        )
        v = get_member_version(mem["id"])
        booking = create_booking(
            member_id=mem["id"], property_id=prop["id"],
            expected_member_version=v,
            check_in="2026-07-01T15:00:00Z",
            check_out="2026-07-03T11:00:00Z",
        )
        confirm_booking(booking["id"])
        # Promote PLATINUM → DIAMOND BEFORE check-in. Multi-session ladder
        # respects velocity SUSPEND threshold per PRD §3.4.
        promote_member_to_diamond_from_platinum(
            member_id=mem["id"], property_id=prop["id"],
            started_at="2026-06-20T01:00:00Z",
            ended_at="2026-06-20T02:00:00Z",
        )
        set_clock("2026-07-01T16:00:00Z")
        resp = api.check_in_comp_room_booking(
            booking["id"], make_loyalty_manager_headers("lm_1"),
        )
        data = validate_success(resp, expected_status=200)
        # DIAMOND at VEGAS_STRIP base=30000:
        # step_a = round_half_up(30000 * (1 - 0.70)) = 9000
        # step_b = round_half_up(9000 * 1.20)        = 10800
        assert data["final_rate_cents"] == 10800, (
            f"Expected final 10800 at DIAMOND VEGAS_STRIP base=30000, "
            f"got {data['final_rate_cents']}"
        )
        assert data["provisional_rate_cents"] == 21600
        # total_charge overwritten = nights * final = 2 * 10800.
        assert data["total_charge_cents"] == 2 * 10800
        assert data["status"] == "CHECKED_IN"


class TestTierAccrualAndVelocityMonitorOnSameSession:
    """PRD §3.3 + §3.4: a single POST /gaming-sessions drives both the
    tier-credit accrual calc (per-session, updates Member.tier_credits_ytd)
    AND the velocity monitor (sliding-window aggregate, may flip
    Member.velocity_status). Same input, two distinct calculation domains."""

    def test_tier_credits_earned_on_each_session(self, api):
        """PRD §3.3: "the base figure is multiplied by ... slots take a
        game-type multiplier of one. The result is then multiplied by a
        tier-driven coefficient that depends on the member's tier_status as
        it stood the moment the request began ... GOLD carries a coefficient
        of one ... The final value is rounded half-up to two decimal
        places — this rounding is done per session, before the value is
        added to any running total — and stored on the session as
        tier_credits_earned."

        Design: Difficulty/dual_variant_calc/tier_credit_accrual_versus_velocity_monitor_same_session
        """
        set_clock("2026-08-01T00:00:00Z")
        prop = create_property(name="CP-LV", market_segment="VEGAS_STRIP")
        mem = create_member(
            property_id=prop["id"], full_name="M Velocity", email="mv@x.com",
        )
        # First $3000 SLOTS at GOLD: base=3000, *1.0, *1.0 = 3000 TC.
        record_gaming_session(
            member_id=mem["id"], property_id=prop["id"],
            started_at="2026-08-01T10:00:00Z",
            ended_at="2026-08-01T10:30:00Z",
            game_type="SLOTS", theoretical_loss_cents=300000,
        )
        # Second $2000 SLOTS at GOLD: still GOLD because 3000 < 15000.
        resp = api.create_gaming_session(
            {
                "member_id": mem["id"], "property_id": prop["id"],
                "started_at": "2026-08-01T10:45:00Z",
                "ended_at": "2026-08-01T10:55:00Z",
                "game_type": "SLOTS", "theoretical_loss_cents": 200000,
            },
            make_member_services_headers("ms_1"),
        )
        data = validate_success(resp, expected_status=201)
        assert data["tier_credits_earned"] == 2000.00, (
            f"Expected 2000.00 TC from $2000 SLOTS at GOLD, "
            f"got {data['tier_credits_earned']}"
        )

    def test_velocity_monitor_aggregates_over_60min_window_on_same_session(self, api):
        """PRD §3.4: "It looks back one hour — exactly three thousand six
        hundred seconds — from the just-recorded session's ended_at and
        computes the sum of theoretical_loss_cents across every
        GamingSession for this member whose status is RECORDED and whose
        ended_at falls in the window that is open on the left (strictly
        greater than window_start) and closed on the right (less than or
        equal to window_end)."
        PRD §3.4: "A total of exactly five hundred thousand cents trips
        FLAGGED, not NORMAL."

        Design: Difficulty/dual_variant_calc/tier_credit_accrual_versus_velocity_monitor_same_session
        """
        set_clock("2026-08-01T00:00:00Z")
        prop = create_property(name="CP-LV", market_segment="VEGAS_STRIP")
        mem = create_member(
            property_id=prop["id"], full_name="M Velocity", email="mv@x.com",
        )
        # First session $3000 SLOTS, ends 10:30.
        record_gaming_session(
            member_id=mem["id"], property_id=prop["id"],
            started_at="2026-08-01T10:00:00Z",
            ended_at="2026-08-01T10:30:00Z",
            game_type="SLOTS", theoretical_loss_cents=300000,
        )
        # Second session $2000 SLOTS, ends 10:55. Window (9:55, 10:55]
        # contains both ended_at values (10:30 and 10:55). Sum =
        # 300000 + 200000 = 500000 → exactly FLAG threshold.
        record_gaming_session(
            member_id=mem["id"], property_id=prop["id"],
            started_at="2026-08-01T10:45:00Z",
            ended_at="2026-08-01T10:55:00Z",
            game_type="SLOTS", theoretical_loss_cents=200000,
        )
        m = validate_success(
            api.get_member(mem["id"], make_loyalty_manager_headers("lm_1")),
            expected_status=200,
        )
        assert m["velocity_status"] == "FLAGGED", (
            f"Sum exactly at flag threshold (500000) must trip FLAGGED, "
            f"got velocity_status={m['velocity_status']!r}"
        )
        assert m["tier_credits_ytd"] == pytest.approx(5000.00, abs=0.01)
        assert m["tier_status"] == "GOLD"
