"""Session billing calculation: free period, hourly tally, daily cap,
exemption, monthly cover (PRD §3.5, §2.9, §2.10)."""
from __future__ import annotations

import pytest

from test_helpers import (
    add_hours,
    add_minutes,
    add_seconds,
    advance_clock,
    bind_vehicle_to_card,
    create_card,
    create_vehicle,
    exit_session,
    get_session,
    open_session,
    setup_basic_session_scenario,
    setup_lot_zone_spaces,
    validate_success,
)


# ===========================================================================
# §3.5 — free_minutes boundary
# ===========================================================================
class TestFreeMinutesBoundary:
    def test_exit_at_free_minutes_exact_yields_zero_fee(self, api):
        """PRD §3.5: 'If the duration is at most the lot's free_minutes
        multiplied by 60 seconds, the fee is zero.'"""
        scen = setup_basic_session_scenario(
            base_iso="2026-08-01T10:00:00.000Z",
            free_minutes=15,
            hourly_rate_cents=400,
        )
        # exit at exactly entry_at + 15min
        advance_clock("2026-08-01T10:15:00.000Z")
        exit_session(scen["session"]["id"])
        sess = get_session(scen["session"]["id"])
        assert sess["final_fee_cents"] == 0, (
            f"Expected fee 0 at <= free_minutes*60s, got {sess['final_fee_cents']}"
        )

    def test_exit_one_second_past_free_minutes_charges_one_hour(self, api):
        """PRD §3.5: 'Otherwise, the duration is split into per-calendar-day
        segments ... the day's started-hour count is the billable seconds
        divided by 3600 rounded up to the next whole number — any partial
        hour rounds up.'"""
        scen = setup_basic_session_scenario(
            base_iso="2026-08-01T10:00:00.000Z",
            free_minutes=15,
            hourly_rate_cents=400,
            daily_cap_cents=2000,
        )
        # exit at entry_at + 15min + 1sec → 1 billable second → 1 hour
        advance_clock("2026-08-01T10:15:01.000Z")
        exit_session(scen["session"]["id"])
        sess = get_session(scen["session"]["id"])
        assert sess["final_fee_cents"] == 400, (
            f"Expected fee 400 at free_minutes+1s, got {sess['final_fee_cents']}"
        )


# ===========================================================================
# §3.5 — Started-hour ceiling
# ===========================================================================
class TestStartedHourCeiling:
    def test_one_hour_one_minute_charges_two_hours(self, api):
        """PRD §3.5: 'any partial hour rounds up.' (PRD §2.9: 'any partial
        hour is rounded up to the next whole hour'.)"""
        scen = setup_basic_session_scenario(
            base_iso="2026-08-02T10:00:00.000Z",
            free_minutes=0,
            hourly_rate_cents=400,
            daily_cap_cents=10_000,
        )
        # 1h + 1min duration → 2 started hours
        advance_clock("2026-08-02T11:01:00.000Z")
        exit_session(scen["session"]["id"])
        sess = get_session(scen["session"]["id"])
        assert sess["final_fee_cents"] == 800, (
            f"Expected fee 800 (2 started hours), got {sess['final_fee_cents']}"
        )


# ===========================================================================
# §3.5 — Daily cap
# ===========================================================================
class TestDailyCap:
    def test_long_session_capped_at_daily_cap(self, api):
        """PRD §3.5: 'The day's capped cost is the smaller of the raw cost
        and the lot's daily_cap_cents.'"""
        # 10 hours @ 400/hr = 4000 raw, capped at 1500
        scen = setup_basic_session_scenario(
            base_iso="2026-08-03T08:00:00.000Z",
            free_minutes=0,
            hourly_rate_cents=400,
            daily_cap_cents=1500,
        )
        advance_clock("2026-08-03T18:00:00.000Z")
        exit_session(scen["session"]["id"])
        sess = get_session(scen["session"]["id"])
        assert sess["final_fee_cents"] == 1500, (
            f"Expected daily-cap 1500, got {sess['final_fee_cents']}"
        )


# ===========================================================================
# §2.10 — Vehicle exemption
# ===========================================================================
class TestExemptVehicleBilling:
    @pytest.mark.parametrize("kind", ["EMERGENCY", "DISABLED"])
    def test_exempt_vehicle_billing_kind_pinned_to_exempt(self, api, kind):
        """PRD §2.10: 'A Vehicle whose kind is EMERGENCY or DISABLED is
        exempt from billing on every session it parks (its
        Session.billing_kind is pinned as EXEMPT_VEHICLE and
        Session.final_fee_cents is zero).'"""
        scen = setup_basic_session_scenario(
            base_iso="2026-08-04T10:00:00.000Z",
            vehicle_kind=kind,
            free_minutes=0,
            hourly_rate_cents=400,
            daily_cap_cents=2000,
        )
        # advance 2h then exit
        advance_clock("2026-08-04T12:00:00.000Z")
        exit_session(scen["session"]["id"])
        sess = get_session(scen["session"]["id"])
        assert sess["billing_kind"] == "EXEMPT_VEHICLE"
        assert sess["final_fee_cents"] == 0


# ===========================================================================
# §3.5 — Monthly card coverage
# ===========================================================================
class TestMonthlyCardCoverage:
    def test_monthly_card_pins_billing_kind_and_zero_fee(self, api):
        """PRD §3.5: 'Otherwise, if the session has a non-null card_id and
        that card has card_type MONTHLY and status ACTIVE and the session's
        vehicle is in the card's bound_vehicle_ids and the session's
        entry_at lies inside the card's [valid_from, valid_until] window,
        then billing_kind is pinned to MONTHLY_COVERED and the fee is zero.'"""
        advance_clock("2026-08-05T08:00:00.000Z")
        lot, zone, spaces = setup_lot_zone_spaces(
            hourly_rate_cents=400,
            daily_cap_cents=2000,
            free_minutes=0,
            space_count=1,
        )
        vehicle = create_vehicle()
        card = create_card(
            card_type="MONTHLY",
            monthly_fee_cents=5000,
            valid_from="2026-08-01T00:00:00.000Z",
            valid_until="2026-09-01T00:00:00.000Z",
        )
        bind_vehicle_to_card(card["id"], vehicle["id"])
        session = open_session(
            lot["id"], vehicle_id=vehicle["id"],
            space_id=spaces[0]["id"], card_id=card["id"],
        )
        # Exit at +2h to confirm fee stays 0 due to MONTHLY_COVERED.
        advance_clock("2026-08-05T10:00:00.000Z")
        exit_session(session["id"])
        sess = get_session(session["id"])
        assert sess["billing_kind"] == "MONTHLY_COVERED"
        assert sess["final_fee_cents"] == 0


# ===========================================================================
# §3.5 — Provisional vs Final variant divergence
# ===========================================================================
class TestProvisionalVsFinal:
    def test_provisional_recomputed_live_on_get(self, api, operator_headers):
        """PRD §3.5: 'Reading a session re-runs the session-billing
        calculation in its provisional-estimate variant on every request
        and returns the result as estimated_fee_cents (recomputed live and
        never persisted).'"""
        scen = setup_basic_session_scenario(
            base_iso="2026-08-06T10:00:00.000Z",
            free_minutes=15,
            hourly_rate_cents=400,
            daily_cap_cents=2000,
        )
        # First read at +30min: 30min - 15 free = 15 billable → ceil(900/3600)=1h
        advance_clock("2026-08-06T10:30:00.000Z")
        sess1 = get_session(scen["session"]["id"])
        assert sess1["estimated_fee_cents"] == 400
        # Second read at +1h30min: 90 - 15 = 75 min → ceil(75/60)=2h
        advance_clock("2026-08-06T11:30:00.000Z")
        sess2 = get_session(scen["session"]["id"])
        assert sess2["estimated_fee_cents"] == 800
