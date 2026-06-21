"""Pricing, engineering, and overtime calculations (Difficulty rules 1, 2, 6).

Covers the dual-variant engineering estimate-vs-final, the combinatorial overtime
surcharge, the nested quarter-hour-then-cents rounding order, and the exact-boundary
behavior of the overtime grace allowance.
"""
import pytest

from test_helpers import (
    validate_success,
    api_client,
    TEST_USERS,
    setup_studio_room_client,
    setup_engineer,
    create_booking,
    pay_deposit,
    confirm,
    set_clock,
    check_in,
    check_out,
    assign_engineer,
    list_overtime_records,
)

SM = TEST_USERS["studio_manager_headers"]


# =====================================================================
# Difficulty rule 1 — dual_variant_calc:
#   engineering_estimate_vs_final_diverge_on_overtime
# =====================================================================
class TestEngineeringEstimateVsFinal:
    """The forward-looking estimate (scheduled_hours only) and the chronological
    final (scheduled + overtime hours) yield different charge_cents for the SAME
    assignment."""

    def _setup(self):
        # studio: deposit 0.60, grace 10, multiplier 1.5; room hourly 6000; engineer rate 8000
        studio, room, client = setup_studio_room_client(
            studio_overrides={
                "deposit_pct": 0.60,
                "overtime_multiplier": 1.5,
                "overtime_grace_minutes": 10,
                "cancellation_tier_hours": 48,
                "late_cancel_fee_pct": 0.25,
            },
            room_overrides={"hourly_rate_cents": 6000, "block_rate_cents": 40000,
                            "block_hours": 8, "turnaround_minutes": 30},
        )
        engineer = setup_engineer(studio["id"], full_name="Sam Senior", tier="SENIOR",
                                  hourly_rate_cents=8000)
        # HOURLY booking 09:00 -> 12:30 (3.5h)
        booking = create_booking(studio, room, client,
                                 start_at="2026-07-10T09:00:00Z", end_at="2026-07-10T12:30:00Z")
        return studio, room, client, engineer, booking

    def test_estimate_uses_scheduled_hours_only(self):
        """PRD §3.5: "The assignment's `scheduled_hours` is the booking's scheduled duration in
        hours rounded **up to the next quarter hour**: take the difference between `end_at` and
        `start_at` in hours, multiply by four, round up to a whole number, and divide by four."
        PRD §3.5: "The estimate `charge_cents` is `scheduled_hours` multiplied by the engineer's
        `hourly_rate_cents`, rounded half up to a whole cent. This estimate deliberately ignores
        overtime — it is the figure quoted before the session runs."

        Design: Difficulty/dual_variant_calc/engineering_estimate_vs_final_diverge_on_overtime
        """
        studio, room, client, engineer, booking = self._setup()
        assign = assign_engineer(booking, engineer)
        # 3.5h is already a quarter-hour multiple -> scheduled_hours == 3.5
        assert assign["scheduled_hours"] == 3.5, assign["scheduled_hours"]
        # estimate charge = round_half_up(3.5 * 8000) == 28000
        assert assign["charge_cents"] == 28000, assign["charge_cents"]

    def test_final_charge_folds_in_overtime_after_checkout(self):
        """PRD §3.5: "The `billed_hours` becomes `scheduled_hours` plus the overtime portion,
        where the overtime portion is the billable overage minutes expressed in hours and rounded
        **up to the next quarter hour** (the overtime hours multiplied by four, rounded up,
        divided by four)."
        PRD §3.5: "The final `charge_cents` is `billed_hours` multiplied by the engineer's
        `hourly_rate_cents`, rounded half up to a whole cent."

        Design: Difficulty/dual_variant_calc/engineering_estimate_vs_final_diverge_on_overtime
        """
        studio, room, client, engineer, booking = self._setup()
        assign = assign_engineer(booking, engineer)
        pay_deposit(booking, client, 14400)
        confirm(booking)
        set_clock("2026-07-10T09:05:00Z")
        check_in(booking)
        # check out at 12:55 -> 25 raw over min - 10 grace = 15 billable -> 0.25h after quarter-ceil
        check_out(booking, "2026-07-10T12:55:00Z")
        final = validate_success(api_client.get_engineer_assignment(assign["id"], SM), 200)
        # billed_hours = 3.5 + 0.25 == 3.75 ; charge = round_half_up(3.75 * 8000) == 30000
        assert final["billed_hours"] == 3.75, final["billed_hours"]
        assert final["charge_cents"] == 30000, final["charge_cents"]


# =====================================================================
# Difficulty rule 2 — combinatorial_formula:
#   overtime_surcharge_multi_input_nonlinear_mode_a
# =====================================================================
class TestOvertimeSurchargeCombinatorial:
    """overtime_cents combines (actual_end - end), the grace subtraction, the room rate,
    the studio multiplier, and a per-assignment quarter-hour-ceil sum."""

    def _setup_checked_in(self):
        studio, room, client = setup_studio_room_client(
            studio_overrides={"deposit_pct": 0.60, "overtime_multiplier": 1.5,
                              "overtime_grace_minutes": 10},
            room_overrides={"hourly_rate_cents": 6000, "block_rate_cents": 40000},
        )
        engineer = setup_engineer(studio["id"], full_name="Sam", tier="STAFF",
                                  hourly_rate_cents=8000)
        booking = create_booking(studio, room, client,
                                 start_at="2026-07-10T09:00:00Z", end_at="2026-07-10T12:30:00Z")
        assign_engineer(booking, engineer)
        pay_deposit(booking, client, 14400)
        confirm(booking)
        set_clock("2026-07-10T09:05:00Z")
        check_in(booking)
        return booking

    def test_overtime_cents_sums_room_and_engineer_surcharges(self):
        """PRD §3.4: "The room_surcharge_cents is the billable minutes expressed as a fraction
        of an hour (overage_minutes divided by 60), multiplied by the room's hourly_rate_cents,
        multiplied by the studio's overtime_multiplier, with the product rounded half up to a
        whole cent."
        PRD §3.4: "The booking's `overtime_cents` is the room surcharge plus the summed engineer
        surcharge."

        Design: Difficulty/combinatorial_formula/overtime_surcharge_multi_input_nonlinear_mode_a
        """
        booking = self._setup_checked_in()
        # actual_end 12:55 -> raw 25 min - 10 grace = 15 billable minutes
        checked_out = check_out(booking, "2026-07-10T12:55:00Z")
        # room surcharge = round_half_up(15/60 * 6000 * 1.5) = 2250
        # engineer surcharge = round_half_up(ceil(0.25*4)/4 * 8000) = round_half_up(0.25*8000) = 2000
        assert checked_out["overtime_cents"] == 4250, checked_out["overtime_cents"]

    def test_overtime_record_components_break_down(self):
        """PRD §3.4: "From that raw overage subtract the studio's `overtime_grace_minutes`, and
        floor the result at zero — this yields the billable `overage_minutes`."
        PRD §3.4: "The `engineer_surcharge_cents` is summed across the booking's non-released
        engineer assignments: for each `ASSIGNED` assignment, take the billable minutes as a
        fraction of an hour, round that hour figure **up to the next quarter hour**, multiply by
        that engineer's `hourly_rate_cents`, round half up to a whole cent, and add it to the
        running total."

        Design: Difficulty/combinatorial_formula/overtime_surcharge_multi_input_nonlinear_mode_a
        """
        booking = self._setup_checked_in()
        check_out(booking, "2026-07-10T12:55:00Z")
        records = list_overtime_records(booking["id"])
        assert len(records) == 1, records
        rec = records[0]
        assert rec["overage_minutes"] == 15, rec["overage_minutes"]
        assert rec["room_surcharge_cents"] == 2250, rec["room_surcharge_cents"]
        assert rec["engineer_surcharge_cents"] == 2000, rec["engineer_surcharge_cents"]


# =====================================================================
# Difficulty rule 2 — combinatorial_formula:
#   engineering_charge_quarter_hour_then_cents_rounding_order_mode_b
# =====================================================================
class TestEngineeringQuarterHourRoundingOrder:
    """Hours are ceil-rounded to the next quarter-hour FIRST, THEN multiplied by the rate,
    THEN rounded to cents."""

    def _setup(self):
        studio, room, client = setup_studio_room_client(
            room_overrides={"hourly_rate_cents": 6000, "block_rate_cents": 40000},
        )
        engineer = setup_engineer(studio["id"], full_name="Sam", tier="STAFF",
                                  hourly_rate_cents=8000)
        # 09:00 -> 12:10 == 3h10m
        booking = create_booking(studio, room, client,
                                 start_at="2026-07-10T09:00:00Z", end_at="2026-07-10T12:10:00Z")
        return booking, engineer

    def test_scheduled_hours_ceils_to_quarter_hour(self):
        """PRD §3.5: "The assignment's `scheduled_hours` is the booking's scheduled duration in
        hours rounded **up to the next quarter hour**: take the difference between `end_at` and
        `start_at` in hours, multiply by four, round up to a whole number, and divide by four."

        Design: Difficulty/combinatorial_formula/engineering_charge_quarter_hour_then_cents_rounding_order_mode_b
        """
        booking, engineer = self._setup()
        assign = assign_engineer(booking, engineer)
        # 3.1667h * 4 = 12.667 -> ceil 13 -> /4 = 3.25
        assert assign["scheduled_hours"] == 3.25, assign["scheduled_hours"]

    def test_charge_rounds_hours_first_then_cents(self):
        """PRD §3.5: "The estimate `charge_cents` is `scheduled_hours` multiplied by the
        engineer's `hourly_rate_cents`, rounded half up to a whole cent."
        PRD §2.6: "where a formula calls for rounding hours or blocks or rental-days up to a whole
        unit, that ceiling is applied to the time quantity *first*, and only the rounded quantity
        is multiplied by the per-unit rate."

        Design: Difficulty/combinatorial_formula/engineering_charge_quarter_hour_then_cents_rounding_order_mode_b
        """
        booking, engineer = self._setup()
        assign = assign_engineer(booking, engineer)
        # round_half_up(3.25 * 8000) == 26000
        assert assign["charge_cents"] == 26000, assign["charge_cents"]


# =====================================================================
# Difficulty rule 6 — boundary_precision_check:
#   overtime_grace_exact_boundary_no_charge_on_checkout
# =====================================================================
class TestOvertimeGraceBoundary:
    """An actual_end exactly grace minutes past end_at yields overage_minutes == 0 and
    overtime_cents == 0; the threshold is strict-greater-than grace."""

    def _setup_checked_in(self, grace=10):
        studio, room, client = setup_studio_room_client(
            studio_overrides={"deposit_pct": 0.60, "overtime_grace_minutes": grace,
                              "overtime_multiplier": 1.5},
            room_overrides={"hourly_rate_cents": 6000, "block_rate_cents": 40000},
        )
        booking = create_booking(studio, room, client,
                                 start_at="2026-07-10T09:00:00Z", end_at="2026-07-10T12:30:00Z")
        pay_deposit(booking, client, 14400)
        confirm(booking)
        set_clock("2026-07-10T09:05:00Z")
        check_in(booking)
        return booking

    def test_exactly_grace_minutes_over_incurs_no_overtime(self):
        """PRD §3.4: "billing is triggered only when overage_minutes ends up strictly greater
        than zero (equivalently, only when the raw overage strictly exceeds the grace
        allowance); a session that runs over by no more than the grace incurs no overtime."

        Design: Difficulty/boundary_precision_check/overtime_grace_exact_boundary_no_charge_on_checkout
        """
        booking = self._setup_checked_in()
        # 12:40 is exactly 10 min (== grace) past end 12:30 -> overage_minutes == 0
        checked_out = check_out(booking, "2026-07-10T12:40:00Z")
        assert checked_out["overtime_cents"] == 0, checked_out["overtime_cents"]
        records = list_overtime_records(booking["id"])
        assert len(records) == 1, records
        assert records[0]["overage_minutes"] == 0, records[0]["overage_minutes"]

    def test_one_minute_past_grace_bills_one_minute(self):
        """PRD §3.4: "From that raw overage subtract the studio's overtime_grace_minutes, and
        floor the result at zero — this yields the billable overage_minutes."

        Design: Difficulty/boundary_precision_check/overtime_grace_exact_boundary_no_charge_on_checkout
        """
        booking = self._setup_checked_in()
        # 12:41 is 11 min past end -> 11 - 10 grace = 1 billable minute
        check_out(booking, "2026-07-10T12:41:00Z")
        records = list_overtime_records(booking["id"])
        assert len(records) == 1, records
        assert records[0]["overage_minutes"] == 1, records[0]["overage_minutes"]
