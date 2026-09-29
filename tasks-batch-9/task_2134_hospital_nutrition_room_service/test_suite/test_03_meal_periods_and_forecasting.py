"""Meal period scheduling, production forecasting and the period cost rollup."""
import pytest
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    approx2,
    assert_meal_period,
    assert_period_cost_rollup,
    create_active_diet_order,
    create_meal_period_payload,
    create_dinner_period_payload,
    line,
    lock_forecast,
    new_diet_rule,
    new_dinner_period,
    new_meal_period,
    new_menu_item,
    new_patient,
    new_ward,
    open_service,
    place_tray,
    read_meal_order,
    read_meal_period,
    set_clock,
    setup_tray_scenario,
    validate_error,
    validate_paginated,
    validate_success,
    validate_tray,
)

MANAGER = TEST_USERS["nutrition_manager_headers"]
CLERK = TEST_USERS["diet_clerk_headers"]


def _two_period_ward_with_three_patients():
    ward = new_ward()
    for index, (mrn, name, age) in enumerate(
        [("MRN-2001", "Ada Kern", 71), ("MRN-2002", "Ben Oduya", 64),
         ("MRN-2003", "Cara Lind", 58)]
    ):
        new_patient(ward["id"], mrn=mrn, full_name=name, age_years=age)
    lunch = new_meal_period(ward["id"])
    dinner = new_dinner_period(ward["id"])
    return {"ward": ward, "lunch": lunch, "dinner": dinner}


class TestProductionForecastVariants:
    def test_rolling_average_falls_back_to_ward_tray_line_capacity(self, api):
        """PRD §3.5: "Under **`ROLLING_AVERAGE`**, the system looks backwards. It
        gathers the meal periods on the same ward with the same `period_code` whose
        `status` is `CLOSED` and whose `service_date` is earlier than this period's
        `service_date`, ranks them by `service_date` descending with `created_at`
        descending as the tie-break, and keeps at most the **three** most recent. If
        that history is empty, `forecast_tray_count` falls back to the ward's
        `tray_line_capacity_per_window` — a fallback that typically overshoots a small
        census."
        PRD §3.5: "Whichever variant produced it, `forecast_cost_cents` is
        `forecast_tray_count` multiplied by the departmental average tray cost of
        1,150 cents — eleven dollars and fifty cents per tray — as exact integer
        arithmetic."

        Design: Difficulty/dual_variant_calc/production_forecast_diverges_by_variant_on_same_ward
        """
        scenario = _two_period_ward_with_three_patients()

        locked = validate_success(
            api.lock_forecast(scenario["lunch"]["id"], "ROLLING_AVERAGE", MANAGER), 200
        )
        assert_meal_period(locked)

        assert locked["status"] == "FORECAST_LOCKED"
        assert locked["forecast_variant"] == "ROLLING_AVERAGE"
        assert locked["forecast_tray_count"] == 20, (
            "with no CLOSED history the ward tray-line capacity is the fallback"
        )
        assert locked["forecast_cost_cents"] == 23000
        assert locked["forecast_variance_pct"] == approx2(-100.00)

    def test_census_based_diverges_from_rolling_average_on_the_same_ward(self, api):
        """PRD §3.5: "Under **`CENSUS_BASED`**, the system looks forwards. It counts
        the patients on this period's ward whose `status` is `ADMITTED` and whose
        `npo_status` is `NONE` at the moment of the lock, multiplies that live census
        by a participation rate of 0.85, and **rounds the product up to the next whole
        tray**. Delivered history is ignored entirely."
        PRD §3.5: "The two variants answer the same question from opposite directions
        and will generally disagree on the same period."
        PRD §2.7: "A ward's `active_patient_census` counts the patients on that ward
        who are `ADMITTED` and whose `npo_status` is `NONE`, and is recomputed
        whenever a patient is admitted, discharged, placed under a hold, or released
        from one."

        Design: Difficulty/dual_variant_calc/production_forecast_diverges_by_variant_on_same_ward
        """
        scenario = _two_period_ward_with_three_patients()

        rolling = lock_forecast(scenario["lunch"]["id"], "ROLLING_AVERAGE")
        census = validate_success(
            api.lock_forecast(scenario["dinner"]["id"], "CENSUS_BASED", MANAGER), 200
        )

        assert census["forecast_variant"] == "CENSUS_BASED"
        # CEIL(3 admitted, non-NPO patients * 0.85) == 3 trays.
        assert census["forecast_tray_count"] == 3
        assert census["forecast_cost_cents"] == 3450
        assert census["forecast_variance_pct"] == approx2(-100.00)

        assert rolling["forecast_tray_count"] != census["forecast_tray_count"], (
            "the two variants must disagree on the same ward and service date"
        )
        ward = validate_success(api.get_ward(scenario["ward"]["id"], MANAGER), 200)
        assert ward["active_patient_census"] == 3

    def test_forecast_variance_rounds_half_up_to_two_decimals(self, api):
        """PRD §3.5: "Otherwise `forecast_variance_pct` is the committed tray count
        minus the forecast tray count, divided by the forecast tray count, multiplied
        by 100, and rounded half up to 2 decimal places. The result is signed:
        committing fewer trays than forecast yields a negative percentage."
        PRD §2.9: "Rounded arithmetic is performed with decimal arithmetic rather than
        binary floating point, so that a weighted sum of, for example, 4.325 rounds up
        to 4.33 rather than down."

        Design: Corner/calculations/forecast_variance_rounds_half_up_to_two_decimals
        """
        ward = new_ward()
        rule = new_diet_rule("REGULAR_STD")
        broth = new_menu_item("SOU-BRO")
        patient = new_patient(ward["id"], mrn="MRN-AC01", full_name="Cy Novak",
                              age_years=61)
        new_patient(ward["id"], mrn="MRN-AC02", full_name="Dee Farr", age_years=55)
        new_patient(ward["id"], mrn="MRN-AC03", full_name="Eli Ward", age_years=47)
        diet_order = create_active_diet_order(patient["id"], rule["id"])
        period = new_meal_period(ward["id"])
        locked = lock_forecast(period["id"], "CENSUS_BASED")
        assert locked["forecast_tray_count"] == 3
        assert locked["forecast_cost_cents"] == 3450
        set_clock("2026-08-02T09:00:00Z")
        tray = place_tray(patient["id"], period["id"], diet_order["id"],
                          [line(broth["id"], 1)], diet_order["version"])

        validate_tray(tray["id"])

        after = read_meal_period(period["id"])
        assert after["committed_tray_count"] == 1
        assert after["forecast_variance_pct"] == approx2(-66.67), (
            "(1 - 3) / 3 * 100 rounds half up to -66.67, never -66.66 or -66.7"
        )
        assert after["committed_food_cost_cents"] == 146
        assert after["period_overhead_cents"] == 26
        assert after["period_total_cost_cents"] == 172


class TestPeriodCostRollup:
    def test_validated_tray_commits_its_cents_to_the_period_subtotal(self, api):
        """PRD §3.5: "The **line subtotal** is `committed_food_cost_cents`: the sum of
        `food_cost_cents` across every tray in this period whose fulfillment dimension
        reads `VALIDATED`, `IN_PRODUCTION`, `PLATED` or `DELIVERED`. Trays that are
        `PENDING_VALIDATION`, `CANCELLED` or `MISSED` contribute nothing."
        PRD §3.6: "The period's `committed_tray_count` increments by 1 and this tray's
        `food_cost_cents` is added to `committed_food_cost_cents`; the period then
        re-runs its cost rollup across `period_overhead_cents`,
        `period_bulk_discount_cents` and `period_total_cost_cents`, and recomputes
        `forecast_variance_pct` whenever `forecast_tray_count` is neither null nor
        zero."

        Design: Difficulty/combinatorial_formula/period_cost_rollup_tier_keyed_on_subtotal_not_on_gross
        """
        scenario = setup_tray_scenario(
            menu_keys=("SUP-ORS",),
            patient_overrides={"mrn": "MRN-5001", "texture_level": "PUREED"},
            tray_lines=(("SUP-ORS", 5),),
        )

        validated = validate_success(
            api.validate_meal_order(scenario["meal_order"]["id"], CLERK), 200
        )
        # 5 units at 260 cents plus the 60 cent pureed surcharge, waste factor 1.08.
        assert validated["food_cost_cents"] == 1728

        period = read_meal_period(scenario["period"]["id"])
        assert period["committed_tray_count"] == 1
        assert period["committed_food_cost_cents"] == 1728

    def test_volume_tier_is_keyed_on_the_subtotal_not_on_the_gross(self, api):
        """PRD §3.5: "The **volume tier** is keyed on that step-one subtotal and on
        nothing else — never on the gross and never on the final total. Tier A applies
        when the subtotal is **below** 2,000 cents (twenty dollars). Tier B applies
        when the subtotal is **at least** 2,000 cents and **below** 6,000 cents (sixty
        dollars). Tier C applies when the subtotal is **at or above** 6,000 cents."
        PRD §3.5: "`period_overhead_cents` is the subtotal multiplied by the tier's
        overhead rate — 18.0 percent in tier A, 15.0 percent in tier B, 12.0 percent
        in tier C — rounded half up to whole cents."
        PRD §3.5: "`period_bulk_discount_cents` is the **gross** multiplied by the
        tier's bulk-discount rate — 0.0 percent in tier A, 2.0 percent in tier B, 4.5
        percent in tier C — rounded half up to whole cents."
        PRD §3.5: "The circular-sounding reading in which the tier is whichever band
        the *period total* falls into is explicitly rejected: the tier is fixed at step
        two, before any overhead exists, which is precisely what makes step three well
        defined."

        Design: Difficulty/combinatorial_formula/period_cost_rollup_tier_keyed_on_subtotal_not_on_gross
        """
        scenario = setup_tray_scenario(
            menu_keys=("SUP-ORS",),
            patient_overrides={"mrn": "MRN-5001", "texture_level": "PUREED"},
            tray_lines=(("SUP-ORS", 5),),
        )
        validate_tray(scenario["meal_order"]["id"])

        period = read_meal_period(scenario["period"]["id"])
        assert period["committed_food_cost_cents"] == 1728
        # 1728 is below 2000 so tier A holds: overhead 18.0%, discount 0.0%.
        assert period["period_overhead_cents"] == 311
        assert period["period_bulk_discount_cents"] == 0
        assert period["period_total_cost_cents"] == 2039
        assert period["period_total_cost_cents"] != 1947, (
            "keying the tier on the 2039 gross would have produced 1947"
        )
        assert_period_cost_rollup(period)


class TestMealPeriodWindows:
    def test_touching_windows_on_the_same_ward_are_rejected(self, api):
        """PRD §3.5: "Two meal periods on the same ward may not occupy overlapping
        delivery windows, and the comparison here is **closed on both ends**: the
        interval running from `window_start_at` through `window_end_at` includes both
        endpoints, so a new period whose window starts at exactly the instant an
        existing period's window ends does collide, and is rejected with
        `ERR_MEAL_PERIOD_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/meal_period_windows_closed_interval_rejects_touching_windows_on_same_ward
        """
        ward = new_ward()
        new_meal_period(ward["id"])

        response = api.create_meal_period(
            create_meal_period_payload(
                ward["id"],
                period_code="DINNER",
                order_cutoff_at="2026-08-02T12:30:00Z",
                window_start_at="2026-08-02T13:00:00Z",
                window_end_at="2026-08-02T14:30:00Z",
            ),
            MANAGER,
        )
        validate_error(response, ApiErrorId.ERR_MEAL_PERIOD_WINDOW_OVERLAP, 409)

        _, meta = validate_paginated(
            api.list_meal_periods(MANAGER, params={"ward_id": ward["id"]})
        )
        assert meta["total_count"] == 1

    def test_the_same_clash_on_a_different_ward_is_accepted(self, api):
        """PRD §3.5: "Two meal periods on the same ward may not occupy overlapping
        delivery windows, and the comparison here is **closed on both ends**: the
        interval running from `window_start_at` through `window_end_at` includes both
        endpoints, so a new period whose window starts at exactly the instant an
        existing period's window ends does collide, and is rejected with
        `ERR_MEAL_PERIOD_WINDOW_OVERLAP`."
        PRD §3.5: "A **meal period** is one ward's service slot for one meal on one
        day, and it is the unit against which production capacity and food cost are
        budgeted."

        Design: Difficulty/resource_temporal_overlap/meal_period_windows_closed_interval_rejects_touching_windows_on_same_ward
        """
        ward_one = new_ward()
        ward_two = new_ward(name="Ward 6 North", code="W6N",
                            tray_line_capacity_per_window=16, delivery_lead_minutes=25)
        new_meal_period(ward_one["id"])

        response = api.create_meal_period(
            create_meal_period_payload(
                ward_two["id"],
                order_cutoff_at="2026-08-02T11:00:00Z",
                window_start_at="2026-08-02T12:00:00Z",
                window_end_at="2026-08-02T13:30:00Z",
                production_capacity_trays=16,
            ),
            MANAGER,
        )
        created = validate_success(response, 201)
        assert created["status"] == "PLANNED", (
            "the contended resource is the ward's tray line, so another ward may clash"
        )

        _, meta_one = validate_paginated(
            api.list_meal_periods(MANAGER, params={"ward_id": ward_one["id"]})
        )
        _, meta_two = validate_paginated(
            api.list_meal_periods(MANAGER, params={"ward_id": ward_two["id"]})
        )
        assert meta_one["total_count"] == 1
        assert meta_two["total_count"] == 1


class TestSlotAndCentsConservation:
    def test_validate_reserves_exactly_one_slot_and_its_cents(self, api):
        """PRD §2.7: "**Ledger symmetry** is the second discipline. A tray that
        reaches the validated state reserves exactly one production slot and exactly
        its own food cost in cents against its meal period."
        PRD §3.6: "The period's `committed_tray_count` increments by 1 and this tray's
        `food_cost_cents` is added to `committed_food_cost_cents`; the period then
        re-runs its cost rollup across `period_overhead_cents`,
        `period_bulk_discount_cents` and `period_total_cost_cents`, and recomputes
        `forecast_variance_pct` whenever `forecast_tray_count` is neither null nor
        zero."

        Design: Difficulty/compensating_invariant/tray_slot_count_conserved_across_validate_then_cancel
        """
        scenario = setup_tray_scenario(
            menu_keys=("SOU-BRO",),
            patient_overrides={"mrn": "MRN-J001", "texture_level": "PUREED"},
            period_overrides={"production_capacity_trays": 5},
        )
        before = read_meal_period(scenario["period"]["id"])
        assert before["committed_tray_count"] == 0
        assert before["committed_food_cost_cents"] == 0

        validate_tray(scenario["meal_order"]["id"])

        after = read_meal_period(scenario["period"]["id"])
        assert after["committed_tray_count"] == 1
        assert after["committed_food_cost_cents"] == 211
        assert after["period_overhead_cents"] == 38
        assert after["period_total_cost_cents"] == 249
        assert_period_cost_rollup(after)

    def test_cancel_returns_the_slot_and_the_cents_exactly(self, api):
        """PRD §3.6: "Cancelling from `VALIDATED`, from `IN_PRODUCTION` or from
        `PLATED` moves the tray to `CANCELLED` and, in each of those three cases
        identically, decrements the period's `committed_tray_count` by 1, subtracts
        the tray's `food_cost_cents` from `committed_food_cost_cents`, re-runs the
        period cost rollup and the forecast variance, and increments both the tray's
        `version` and the period's `version` by 1. This is the exact compensating
        action for the slot-and-cents reservation that validation took: both the tray
        count and the cents ledger return to their pre-validation values."

        Design: Difficulty/compensating_invariant/tray_slot_count_conserved_across_validate_then_cancel
        """
        scenario = setup_tray_scenario(
            menu_keys=("SOU-BRO",),
            patient_overrides={"mrn": "MRN-J001", "texture_level": "PUREED"},
            period_overrides={"production_capacity_trays": 5},
        )
        validate_tray(scenario["meal_order"]["id"])

        cancelled = validate_success(
            api.cancel_meal_order(scenario["meal_order"]["id"], CLERK), 200
        )
        assert cancelled["fulfillment_status"] == "CANCELLED"
        assert cancelled["food_cost_cents"] == 211, "the cancel does not re-price the tray"

        period = read_meal_period(scenario["period"]["id"])
        assert period["committed_tray_count"] == 0
        assert period["committed_food_cost_cents"] == 0
        assert period["period_overhead_cents"] == 0
        assert period["period_bulk_discount_cents"] == 0
        assert period["period_total_cost_cents"] == 0

        _, meta = validate_paginated(
            api.list_meal_orders(
                CLERK,
                params={
                    "meal_period_id": scenario["period"]["id"],
                    "fulfillment_status": "VALIDATED",
                },
            )
        )
        assert meta["total_count"] == 0


class TestMealPeriodLifecycle:
    def test_meal_period_starts_in_planned_with_null_forecast_fields(self, api):
        """PRD §3.5: "A new period is stored `PLANNED`, with `forecast_variant`,
        `forecast_tray_count`, `forecast_cost_cents`, `forecast_variance_pct` and
        `locked_at` all null and with `committed_tray_count`,
        `committed_food_cost_cents`, `delivered_tray_count`, `period_overhead_cents`,
        `period_bulk_discount_cents` and `period_total_cost_cents` all zero."
        PRD §3.5: "`cost_ceiling_cents` is optional; when supplied it must be zero or
        greater and caps the period's committed food cost, and when null the period
        has no cost ceiling at all."

        Design: Corner/state_machines/meal_period_starts_in_planned_with_null_forecast_fields
        """
        ward = new_ward()

        response = api.create_meal_period(create_meal_period_payload(ward["id"]), MANAGER)
        period = validate_success(response, 201)
        assert_meal_period(period)

        assert period["status"] == "PLANNED"
        assert period["forecast_variant"] is None
        assert period["forecast_tray_count"] is None
        assert period["forecast_cost_cents"] is None
        assert period["forecast_variance_pct"] is None
        assert period["locked_at"] is None
        assert period["committed_tray_count"] == 0
        assert period["committed_food_cost_cents"] == 0
        assert period["delivered_tray_count"] == 0
        assert period["period_overhead_cents"] == 0
        assert period["period_bulk_discount_cents"] == 0
        assert period["period_total_cost_cents"] == 0
        assert period["cost_ceiling_cents"] is None

    def test_open_service_from_planned_returns_invalid_state(self, api):
        """PRD §3.5: "**Opening service** moves the period `FORECAST_LOCKED →
        IN_SERVICE`, requires the ward to be `ACTIVE`, and bumps the period's
        `version` by 1; it is the gate that lets validated trays enter production."
        PRD §2.5: "10. **Transition legality** — the target row currently sits in one
        of the from-states the requested transition declares, else
        `ERR_INVALID_STATE`."

        Design: Corner/state_machines/meal_period_open_service_from_planned_returns_invalid_state
        """
        ward = new_ward()
        period = new_meal_period(ward["id"])
        assert period["status"] == "PLANNED"

        response = api.open_service(period["id"], MANAGER)
        validate_error(response, ApiErrorId.ERR_INVALID_STATE, 409)

        assert read_meal_period(period["id"])["status"] == "PLANNED"

    def test_close_twice_returns_invalid_state_from_the_terminal_state(self, api):
        """PRD §3.5: "**Closing** moves `IN_SERVICE → CLOSED`, is terminal, and
        unwinds whatever the service did not finish."
        PRD §2.5: "10. **Transition legality** — the target row currently sits in one
        of the from-states the requested transition declares, else
        `ERR_INVALID_STATE`."
        PRD §2.4: "`version` is an integer that starts at 1 when the row is created
        and increments by exactly 1 on every mutation of that row, including mutations
        that a cascade performs on the operator's behalf rather than mutations the
        operator requested directly."

        Design: Corner/state_machines/meal_period_close_twice_returns_invalid_state_from_terminal
        """
        ward = new_ward()
        period = new_meal_period(ward["id"])
        lock_forecast(period["id"], "CENSUS_BASED")
        open_service(period["id"])
        closed = validate_success(api.close_meal_period(period["id"], MANAGER), 200)
        assert closed["status"] == "CLOSED"
        version_after_close = closed["version"]

        response = api.close_meal_period(period["id"], MANAGER)
        validate_error(response, ApiErrorId.ERR_INVALID_STATE, 409)

        after = read_meal_period(period["id"])
        assert after["status"] == "CLOSED"
        assert after["version"] == version_after_close, (
            "a rejected transition is not a mutation and must not bump version"
        )

    def test_validate_response_carries_the_refreshed_totals_in_the_same_request(self, api):
        """PRD §2.7: "Many operations in this system mutate more than the row the
        caller named. When they do, the effects are **immediate and complete within
        the request** — there is no deferred or eventual settlement."
        PRD §3.6: "A tray that survives all of that moves `PENDING_VALIDATION →
        VALIDATED`. Its `effective_texture_level` and `effective_liquid_level` are
        refreshed from the pinned order's envelope, its four nutrient totals are
        recomputed, every `line_cost_cents` and the tray's `food_cost_cents` are
        recomputed, and `revalidation_required` is cleared to false."

        Design: Corner/consistency_model/validate_response_carries_the_refreshed_totals_in_the_same_request
        """
        scenario = setup_tray_scenario(
            menu_keys=("SOU-BRO",),
            patient_overrides={"mrn": "MRN-BE01", "full_name": "Gus Pinto",
                               "age_years": 52},
            forecast_variant="CENSUS_BASED",
            open_for_service=True,
        )

        response = api.validate_meal_order(scenario["meal_order"]["id"], CLERK)
        validated = validate_success(response, 200)
        assert validated["fulfillment_status"] == "VALIDATED"
        assert validated["food_cost_cents"] == 146
        assert validated["revalidation_required"] is False

        period = validate_success(
            api.get_meal_period(scenario["period"]["id"], MANAGER), 200
        )
        assert period["committed_tray_count"] == 1
        assert period["committed_food_cost_cents"] == 146
        assert period["period_overhead_cents"] == 26
        assert period["period_total_cost_cents"] == 172
        assert period["forecast_variance_pct"] == approx2(0.00)
