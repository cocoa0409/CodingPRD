"""Quote and job-charge pricing: dual estimate/final variants, non-linear composition,
per-line add-on tax rounding, and the billable-hours floor boundary."""
import pytest

from test_helpers import (
    validate_success,
    create_config, create_approved_helper, create_draft_job, add_addon,
    request_quote, create_quoted_job, create_booked_job, assign_helper,
    check_in, check_out, ADMIN, DISPATCHER,
    complete_payload, make_customer_headers,
    api_client,
)


WEEKDAY_START = "2026-03-11T09:00:00Z"
WEEKDAY_END = "2026-03-11T12:00:00Z"
WEEKEND_START = "2026-03-14T09:00:00Z"   # Saturday UTC
WEEKEND_END = "2026-03-14T13:00:00Z"


class TestDualVariantJobCharge:
    """Design: Difficulty/dual_variant_calc/job_charge_estimate_vs_final_diverge"""

    def test_booking_copies_estimate_variant_total_to_job(self, api):
        """PRD §3.3: "The raw base labor is the rate card's `base_hourly_rate_cents`
        multiplied by the job's `crew_size` and by the billable hours, rounded half up to
        cents." PRD §3.4: "the job's `estimated_total_cents` is set to that quote's
        `total_cents`".

        Estimate variant on a crew-2, 2.5h, truck-required weekday job with one 4500-cent
        HEAVY_ITEM add-on totals 49315.

        Design: Difficulty/dual_variant_calc/job_charge_estimate_vs_final_diverge
        """
        rate_card, policy, customer = create_config(api)
        booked, quote = create_booked_job(
            api, rate_card["id"], policy["id"], customer["id"],
            crew_size=2, estimated_hours=2.5, truck_required=True,
            window_start=WEEKDAY_START, window_end=WEEKDAY_END,
            addons=[{"addon_type": "HEAVY_ITEM", "quantity": 1, "unit_fee_cents": 4500}],
        )
        assert quote["total_cents"] == 49315
        assert booked["estimated_total_cents"] == 49315

    def test_completion_final_variant_uses_actual_hours_and_diverges(self, api):
        """PRD §3.6: "the job's `actual_hours` is stored and its `final_total_cents` is
        computed by the same pricing procedure used for the quote, but with `actual_hours`
        substituted for the estimated hours as the hours input".

        The identical job priced at actual_hours 3.0 yields final 56215, distinct from the
        estimate 49315.

        Design: Difficulty/dual_variant_calc/job_charge_estimate_vs_final_diverge
        """
        rate_card, policy, customer = create_config(api)
        helper = create_approved_helper(api)
        booked, quote = create_booked_job(
            api, rate_card["id"], policy["id"], customer["id"],
            crew_size=2, estimated_hours=2.5, truck_required=True,
            window_start=WEEKDAY_START, window_end=WEEKDAY_END,
            addons=[{"addon_type": "HEAVY_ITEM", "quantity": 1, "unit_fee_cents": 4500}],
        )
        job_id = booked["id"]
        assignment = assign_helper(api, job_id, helper["id"], role="LEAD")
        check_in(api, assignment["id"], helper["id"])
        validate_success(api.start_job(job_id, DISPATCHER))
        check_out(api, assignment["id"], helper["id"])
        completed = validate_success(api.complete_job(job_id, complete_payload(3.0), DISPATCHER))
        assert completed["final_total_cents"] == 56215
        assert completed["final_total_cents"] != completed["estimated_total_cents"]


class TestCombinatorialQuoteComposition:
    """Design: Difficulty/combinatorial_formula/quote_total_nonlinear_weekend_crew_surcharge"""

    def _weekend_crew3_quote(self, api):
        rate_card, policy, customer = create_config(api)
        _job, quote = create_quoted_job(
            api, rate_card["id"], policy["id"], customer["id"],
            crew_size=3, estimated_hours=4.0, truck_required=False,
            window_start=WEEKEND_START, window_end=WEEKEND_END,
        )
        return quote

    def test_crew_surcharge_and_weekend_surge_compose_into_total(self, api):
        """PRD §3.3: "If `crew_size` is at least 3, the crew surcharge applies: the base
        labor becomes the raw base labor multiplied by one plus the rate card's
        `crew_surcharge_pct`, rounded half up to cents". PRD §3.3: "The `surge_multiplier`
        is the rate card's `peak_surge_multiplier` when the job's `window_start` falls on a
        Saturday or Sunday in UTC, and is 1.0 on weekdays."

        crew_size 3 lifts raw labor 72000 to 79200; the Saturday window applies the 1.25
        surge; composed total is 113850.

        Design: Difficulty/combinatorial_formula/quote_total_nonlinear_weekend_crew_surcharge
        """
        quote = self._weekend_crew3_quote(api)
        assert quote["base_labor_cents"] == 79200
        assert quote["surge_multiplier"] == 1.25
        assert quote["total_cents"] == 113850

    def test_subtotal_and_service_fee_components(self, api):
        """PRD §3.3: "The pre-surge `subtotal_cents` is the sum of `base_labor_cents`,
        `truck_fee_cents`, and `addons_total_cents`." PRD §3.3: "The `service_fee_cents` is
        that surged amount multiplied by the platform service-fee rate of 15%, rounded half
        up to cents."

        Design: Difficulty/combinatorial_formula/quote_total_nonlinear_weekend_crew_surcharge
        """
        quote = self._weekend_crew3_quote(api)
        assert quote["subtotal_cents"] == 79200
        assert quote["service_fee_cents"] == 14850


class TestAddOnPerLineRounding:
    """Design: Difficulty/combinatorial_formula/addons_per_line_round_then_sum"""

    def _quote_with_two_addons(self, api):
        rate_card, policy, customer = create_config(api)
        job = create_draft_job(
            api, rate_card["id"], policy["id"], customer["id"],
            crew_size=2, estimated_hours=2.0,
            window_start=WEEKDAY_START, window_end=WEEKDAY_END, truck_required=False,
        )
        a1 = add_addon(api, job["id"], customer["id"], "HEAVY_ITEM", 1, 4500)
        a2 = add_addon(api, job["id"], customer["id"], "PACKING_MATERIALS", 3, 999)
        quote = request_quote(api, job["id"], customer["id"])
        return a1, a2, quote

    def test_each_line_total_rounded_before_summing(self, api):
        """PRD §3.3: "Each line's `line_total_cents` is computed at creation by multiplying
        `unit_fee_cents` by `quantity`, multiplying the product by one plus the add-on tax
        rate of 8.5%, and rounding that result half up to whole cents."

        4500x1 taxed rounds to 4883; 999x3 taxed rounds to 3252.

        Design: Difficulty/combinatorial_formula/addons_per_line_round_then_sum
        """
        a1, a2, _quote = self._quote_with_two_addons(api)
        assert a1["line_total_cents"] == 4883
        assert a2["line_total_cents"] == 3252

    def test_quote_addons_total_sums_per_line_totals(self, api):
        """PRD §3.3: "This per-line rounding is deliberate: the taxed lines are each rounded
        first and then summed, never summed and rounded once, because the two orders can
        differ by a cent."

        Per-line-then-sum yields 4883 + 3252 = 8135 (sum-then-round would give 8134).

        Design: Difficulty/combinatorial_formula/addons_per_line_round_then_sum
        """
        _a1, _a2, quote = self._quote_with_two_addons(api)
        assert quote["addons_total_cents"] == 8135


class TestBillableHoursFloorBoundary:
    """Design: Difficulty/boundary_precision_check/quote_billable_hours_floor_boundary"""

    def _quote_for_hours(self, api, estimated_hours):
        rate_card, policy, customer = create_config(api)
        _job, quote = create_quoted_job(
            api, rate_card["id"], policy["id"], customer["id"],
            crew_size=2, estimated_hours=estimated_hours,
            window_start=WEEKDAY_START, window_end=WEEKDAY_END, truck_required=False,
        )
        return quote

    def test_hours_at_and_below_floor_pin_to_min_billable(self, api):
        """PRD §3.3: "First, the billable hours are the greater of that hours input and the
        rate card's `min_billable_hours`."

        With min_billable_hours 2.0, both estimated_hours 2.0 (at the floor) and 1.5 (below)
        bill at 2.0 -> base_labor 24000.

        Design: Difficulty/boundary_precision_check/quote_billable_hours_floor_boundary
        """
        assert self._quote_for_hours(api, 2.0)["base_labor_cents"] == 24000
        assert self._quote_for_hours(api, 1.5)["base_labor_cents"] == 24000

    def test_hours_above_floor_use_actual_estimated_hours(self, api):
        """PRD §3.3: "First, the billable hours are the greater of that hours input and the
        rate card's `min_billable_hours`."

        estimated_hours 2.5 exceeds the 2.0 floor and bills at 2.5 -> base_labor 30000.

        Design: Difficulty/boundary_precision_check/quote_billable_hours_floor_boundary
        """
        assert self._quote_for_hours(api, 2.5)["base_labor_cents"] == 30000


def test_book_with_correct_version_copies_quote_total(api):
    """PRD §3.4: "Booking succeeds only if the job is `QUOTED`, the referenced `quote_id` is
    the job's current `ACTIVE` quote, the booking window is still open, and
    `expected_job_version` matches the job's `version`." PRD §3.4: "the job's
    `estimated_total_cents` is set to that quote's `total_cents`".

    A crew-1, 3.0h weekday job quotes at 20700; booking with the freshly read version moves
    it to BOOKED and copies 20700 into estimated_total_cents.

    Design: Corner/cross_cutting/book_succeeds_with_correct_version
    """
    rate_card, policy, customer = create_config(api)
    booked, quote = create_booked_job(
        api, rate_card["id"], policy["id"], customer["id"],
        crew_size=1, estimated_hours=3.0,
        window_start=WEEKDAY_START, window_end=WEEKDAY_END,
    )
    assert booked["status"] == "BOOKED"
    assert booked["estimated_total_cents"] == 20700
