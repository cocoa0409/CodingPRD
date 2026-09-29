"""Labor calls: the overnight determination on the call's own start, the frozen
estimate off the scheduled span, and the settled figure off reported hours."""
import pytest

from test_helpers import (
    create_labor_call,
    draft_booking,
    place_hold,
    read_labor_call,
    setup_arena,
    validate_success,
    TEST_USERS,
)

COORDINATOR = TEST_USERS["labor_coordinator_headers"]


def _held_concert_show():
    """One promoter concert holding a date, ready to carry load-in labor."""
    arena = setup_arena(profiles=("CONCERT",))
    booking = draft_booking(
        arena["venue_id"], arena["profiles"]["CONCERT"]["id"], "Concert Sep 10",
        "2026-09-10T16:00:00Z", "2026-09-10T19:00:00Z",
        expected_attendance=8_000, rigging_load_kg=5_000,
        promoter_name="Northline Live",
    )
    arena["booking"] = place_hold(booking["id"])
    return arena


def _close_call(api, call_id, actual_hours):
    return validate_success(
        api.close_labor_call(call_id, {"actual_hours": actual_hours}, COORDINATOR),
        200,
    )


class TestRiggerCallEstimatedAgainstSettled:
    def test_the_estimate_is_frozen_from_the_scheduled_span_at_the_overnight_rate(
        self, api
    ):
        """PRD §3.9: "The **estimated** variant, frozen into `estimated_cost_cents` at creation
        before anyone has worked an hour, takes billable hours as the greater of
        `guaranteed_hours` and the scheduled span — the exact, possibly fractional, number of
        hours from `call_start_utc` to `call_end_utc`."
        PRD §3.9: "From whichever billable-hours figure applies, straight hours are the lesser
        of that figure and eight hours, and overtime hours are the amount by which it exceeds
        eight hours, floored at zero. Overtime hours are weighted at one and a half times
        straight time."
        PRD §3.9: "Its `overnight` flag is computed at creation by the same arena-local rule
        §3.7 applies to turnaround windows, evaluated here on `call_start_utc`."
        PRD §3.9: "A call is created `CALLED` with `actual_hours` and `settled_cost_cents`
        unset and `cancellation_fee_cents` at 0, and finishes as either `WORKED` or
        `CANCELLED`, both terminal."

        Design: Difficulty/dual_variant_calc/labor_call_estimated_variant_from_scheduled_window_diverges_from_settled_variant_on_reported_hours
        """
        arena = _held_concert_show()
        call = create_labor_call(
            "RIGGER", 6, "2026-09-10T04:00:00Z", "2026-09-10T13:00:00Z",
            guaranteed_hours=4, booking_id=arena["booking"]["id"],
        )

        assert call["status"] == "CALLED"
        assert call["overnight"] is True, (
            "04:00 UTC is midnight arena-local, strictly less than six"
        )
        assert call["estimated_cost_cents"] == 554_040, (
            "nine scheduled hours give eight straight plus one at time and a half"
        )
        assert call["settled_cost_cents"] is None
        assert call["actual_hours"] is None
        assert call["cancellation_fee_cents"] == 0

    def test_the_settled_figure_absorbs_unscheduled_overtime_the_estimate_never_saw(
        self, api
    ):
        """PRD §3.9: "The **settled** variant, written into `settled_cost_cents` when the call
        is closed, takes billable hours as the greater of `guaranteed_hours` and the reported
        `actual_hours`; overtime that was never scheduled therefore surfaces only in the settled
        figure."
        PRD §3.9: "On acceptance the call moves `CALLED → WORKED`, `actual_hours` is stored, and
        `settled_cost_cents` is written from the settled variant."
        PRD §3.9: "The per-worker amount is the base rate multiplied by the sum of straight
        hours and weighted overtime hours, multiplied by the overnight multiplier, and **then**
        rounded half up to whole cents."
        PRD §3.9: "Neither variant aggregates across sibling calls; each call is costed
        entirely from its own row."

        Design: Difficulty/dual_variant_calc/labor_call_estimated_variant_from_scheduled_window_diverges_from_settled_variant_on_reported_hours
        """
        arena = _held_concert_show()
        call = create_labor_call(
            "RIGGER", 6, "2026-09-10T04:00:00Z", "2026-09-10T13:00:00Z",
            guaranteed_hours=4, booking_id=arena["booking"]["id"],
        )
        closed = _close_call(api, call["id"], 11.5)

        assert closed["status"] == "WORKED"
        assert float(closed["actual_hours"]) == pytest.approx(11.5, abs=0.005)
        assert closed["settled_cost_cents"] == 772_740, (
            "eleven and a half hours give eight straight plus three and a half at "
            "time and a half"
        )
        assert closed["estimated_cost_cents"] == 554_040, (
            "the estimate is frozen at creation and is not revisited at close"
        )
        assert closed["settled_cost_cents"] - closed["estimated_cost_cents"] == 218_700
        assert closed["cancellation_fee_cents"] == 0

        stored = read_labor_call(call["id"])
        assert stored["settled_cost_cents"] == 772_740


class TestPerHeadRoundingBeforeTheHeadcountMultiply:
    def test_a_scheduled_span_of_exactly_eight_hours_carries_no_overtime(self, api):
        """PRD §3.9: "The hourly base rate is read from the `craft`: 4,800 cents for
        `STAGEHAND`, 7,200 cents for `RIGGER`, 5,600 cents for `ICE_TECH`, 6,900 cents for
        `ELECTRICIAN` and 4,200 cents for `CONVERSION_CREW`."
        PRD §3.9: "From whichever billable-hours figure applies, straight hours are the lesser
        of that figure and eight hours, and overtime hours are the amount by which it exceeds
        eight hours, floored at zero. Overtime hours are weighted at one and a half times
        straight time."
        PRD §3.9: "The overnight multiplier is 1.35 when the call's `overnight` flag is true and
        1.0 otherwise."
        PRD §3.9: "Only after that per-worker rounding is the amount multiplied by `headcount`
        to give the stored figure."

        Design: Difficulty/boundary_precision_check/labor_settlement_rounds_per_head_half_cent_up_before_the_headcount_multiply
        """
        arena = _held_concert_show()
        call = create_labor_call(
            "ELECTRICIAN", 4, "2026-09-10T04:00:00Z", "2026-09-10T12:00:00Z",
            guaranteed_hours=4, booking_id=arena["booking"]["id"],
        )

        assert call["overnight"] is True
        assert call["headcount"] == 4
        assert call["estimated_cost_cents"] == 298_080, (
            "eight straight hours at the electrician rate, uplifted for overnight, "
            "rounds to 74520 a head"
        )
        assert call["settled_cost_cents"] is None

    def test_a_half_cent_per_head_rounds_up_before_the_headcount_multiply(self, api):
        """PRD §3.9: "The per-worker amount is the base rate multiplied by the sum of straight
        hours and weighted overtime hours, multiplied by the overnight multiplier, and **then**
        rounded half up to whole cents."
        PRD §3.9: "Rounding the aggregate instead of the per-worker amount is explicitly not
        the rule and produces a different total whenever the per-worker amount lands on a half
        cent."
        PRD §2.8: "Wherever a value is rounded, the method is **round half up** — a value
        sitting exactly on a half increment rounds away from zero to the larger magnitude."
        PRD §2.8: "Labor cost figures are rounded to whole cents once per worker, before the
        per-worker figure is multiplied by the call's `headcount`; the alternative order,
        multiplying first and rounding the aggregate, yields a different total whenever the
        per-worker amount lands on a half cent and is not used."

        Design: Difficulty/boundary_precision_check/labor_settlement_rounds_per_head_half_cent_up_before_the_headcount_multiply
        """
        arena = _held_concert_show()
        call = create_labor_call(
            "ELECTRICIAN", 4, "2026-09-10T04:00:00Z", "2026-09-10T12:00:00Z",
            guaranteed_hours=4, booking_id=arena["booking"]["id"],
        )
        closed = _close_call(api, call["id"], 8.2)

        assert closed["status"] == "WORKED"
        assert float(closed["actual_hours"]) == pytest.approx(8.2, abs=0.005)
        assert closed["settled_cost_cents"] == 309_260, (
            "77314.5 cents a head rounds up to 77315 before the multiply by four"
        )
        assert closed["settled_cost_cents"] != 309_258, (
            "309258 rounds the aggregate instead of the per-worker amount"
        )
        assert closed["estimated_cost_cents"] == 298_080
