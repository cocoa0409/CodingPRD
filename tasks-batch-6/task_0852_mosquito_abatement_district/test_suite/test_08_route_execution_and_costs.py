"""Route execution, the wind-drift volume variant, voiding, and what a treatment
costs when the plan completes."""

import test_helpers as fx
from test_helpers import MANAGER, ApiErrorId, validate_error, validate_success

LARVICIDE_TECH = {"license_category": "LARVICIDE_ONLY"}


def test_wind_below_eight_miles_per_hour_applies_no_drift_factor(api):
    """PRD §3.9: "Below 8.0 miles per hour the factor is 1.00."
    PRD §3.9: "Multiply `actual_acres` by the product's `label_rate_ml_per_acre`
    and by the drift factor, round half up to two decimal places, and write the
    result to `actual_volume_ml`."

    Design: Corner/calculations/corner_wind_drift_factor_not_applied_below_eight_mph
    """
    bundle = fx.setup_in_progress_plan(
        applicator_overrides=LARVICIDE_TECH,
        product_overrides={"reentry_interval_hours": 0},
        routes=[{"planned_acres": 10.0, "window_start": "2026-06-05T09:00:00.000Z",
                 "window_end": "2026-06-05T10:00:00.000Z"}],
    )

    executed = validate_success(
        api.transition_treatment_route(
            bundle["route"]["id"],
            {"action": "EXECUTE", "actual_acres": 10.0, "wind_speed_mph": 7.9},
            fx.make_field_tech_headers(bundle["applicator"]["id"]),
        )
    )

    fx.assert_index(executed["estimated_volume_ml"], 1000.00, "estimated_volume_ml")
    fx.assert_index(executed["actual_volume_ml"], 1000.00, "actual_volume_ml")
    product = fx.read_product(bundle["product"]["id"])
    fx.assert_index(product["on_hand_ml"], 99000.00, "on_hand_ml")
    fx.assert_index(product["committed_ml"], 0.00, "committed_ml")
    fx.assert_index(product["applied_ml"], 1000.00, "applied_ml")
    fx.assert_inventory_partition(product)


def test_subtotal_of_exactly_one_hundred_thousand_cents_selects_the_middle_tier(api):
    """PRD §3.9: "Fourth, the administrative fee tier is selected **from the
    subtotal**, before any fee has been added: `admin_fee_rate` is 0.08 when
    `subtotal_cents` is below 100000 cents, 0.06 when it is below 500000 cents, and
    0.045 otherwise. The tier boundaries are half-open on the low side, so a
    subtotal of exactly 100000 cents selects 0.06 and a subtotal of exactly 500000
    cents selects 0.045."

    Design: Corner/calculations/corner_admin_fee_tier_two_selected_at_subtotal_exactly_one_hundred_thousand
    """
    bundle = fx.setup_verified_route(
        applicator_overrides=LARVICIDE_TECH,
        product_overrides={"reentry_interval_hours": 0},
        actual_acres=0.10, wind_speed_mph=3.0,
        routes=[{"planned_acres": 0.10, "window_start": "2026-06-05T09:00:00.000Z",
                 "window_end": "2026-06-05T22:53:00.000Z"}],
    )

    completed = validate_success(
        api.transition_treatment_plan(bundle["plan"]["id"], {"action": "COMPLETE"}, MANAGER)
    )

    assert fx.read_route(bundle["route"]["id"])["duration_minutes"] == 833
    fx.assert_index(
        fx.read_route(bundle["route"]["id"])["actual_volume_ml"], 10.00, "actual_volume_ml"
    )
    assert completed["material_cost_cents"] == 40
    assert completed["labor_cost_cents"] == 99960
    assert completed["subtotal_cents"] == 100000
    assert completed["admin_fee_rate"] == 0.06
    assert completed["admin_fee_cents"] == 6000
    assert completed["total_cost_cents"] == 106000


def test_estimated_volume_is_reserved_without_the_drift_factor(api):
    """PRD §3.9: "The **estimated volume** that condition 9 tests is computed from
    the plan on paper: multiply the route's `planned_acres` by the product's
    `label_rate_ml_per_acre` and round half up to two decimal places."
    PRD §3.9: "The trigger is inclusive, so exactly 8.0 miles per hour already
    incurs the surcharge."

    Design: Difficulty/dual_variant_calc/route_volume_estimated_vs_actual_diverge_on_wind_drift
    """
    bundle = fx.setup_in_progress_plan(
        treatment_type="ADULTICIDE", posture="EMERGENCY",
        routes=[{"planned_acres": 10.0, "window_start": "2026-06-05T09:00:00.000Z",
                 "window_end": "2026-06-05T12:00:00.000Z",
                 "center_x_m": 0, "center_y_m": 0}],
    )
    fx.assert_index(
        fx.read_route(bundle["route"]["id"])["estimated_volume_ml"], 1000.00,
        "estimated_volume_ml",
    )

    executed = validate_success(
        api.transition_treatment_route(
            bundle["route"]["id"],
            {"action": "EXECUTE", "actual_acres": 10.0, "wind_speed_mph": 8.0},
            fx.make_field_tech_headers(bundle["applicator"]["id"]),
        )
    )

    assert executed["status"] == "EXECUTED"
    fx.assert_index(executed["estimated_volume_ml"], 1000.00, "estimated_volume_ml")
    fx.assert_index(executed["actual_volume_ml"], 1100.00, "actual_volume_ml")
    assert executed["executed_at"] == "2026-06-05T09:00:00.000Z"


def test_drift_surcharge_withdraws_the_overshoot_from_on_hand_stock(api):
    """PRD §3.9: "On success `executed_at` is stamped from the logical clock,
    `committed_ml` decreases by the estimated volume, `applied_ml` increases by the
    actual volume, `on_hand_ml` absorbs the estimated volume minus the actual
    volume — a *withdrawal* whenever the crew overshot its estimate — the product's
    `version` advances, and the area's `seasonal_application_count` increases by 1."
    PRD §2.9: "Executing a route moves the estimated volume out of `committed_ml`,
    adds the *actual* volume to `applied_ml`, and returns the difference between
    estimated and actual to `on_hand_ml` — a difference that is negative, and
    therefore a further withdrawal from on-hand stock, whenever the actual
    application exceeded the estimate."

    Design: Difficulty/dual_variant_calc/route_volume_estimated_vs_actual_diverge_on_wind_drift
    """
    bundle = fx.setup_in_progress_plan(
        treatment_type="ADULTICIDE", posture="EMERGENCY",
        routes=[{"planned_acres": 10.0, "window_start": "2026-06-05T09:00:00.000Z",
                 "window_end": "2026-06-05T12:00:00.000Z",
                 "center_x_m": 0, "center_y_m": 0}],
    )

    fx.route_action(
        bundle["route"]["id"], "EXECUTE",
        fx.make_field_tech_headers(bundle["applicator"]["id"]),
        actual_acres=10.0, wind_speed_mph=8.0,
    )

    product = fx.read_product(bundle["product"]["id"])
    fx.assert_index(product["on_hand_ml"], 98900.00, "on_hand_ml")
    fx.assert_index(product["committed_ml"], 0.00, "committed_ml")
    fx.assert_index(product["applied_ml"], 1100.00, "applied_ml")
    fx.assert_index(product["received_total_ml"], 100000.00, "received_total_ml")
    fx.assert_inventory_partition(product)
    assert fx.read_area(bundle["area"]["id"])["seasonal_application_count"] == 1


def test_material_and_labour_costs_are_summed_from_the_verified_route(api):
    """PRD §3.9: "First, material cost: for each verified route, divide its
    `actual_volume_ml` by 1000 to convert millilitres to litres, multiply by that
    route's product's `cost_cents_per_liter`, and round half up to a whole number
    of cents — *per route* — then sum those per-route whole-cent figures into
    `material_cost_cents`."
    PRD §3.9: "Third, `subtotal_cents` is `material_cost_cents` plus
    `labor_cost_cents`."

    Design: Difficulty/combinatorial_formula/admin_fee_tier_selected_from_subtotal_not_from_total
    """
    bundle = fx.setup_verified_route(
        product_overrides={"reentry_interval_hours": 4},
        actual_acres=0.15, wind_speed_mph=5.0,
        routes=[{"planned_acres": 0.15, "window_start": "2026-06-05T09:00:00.000Z",
                 "window_end": "2026-06-05T22:52:00.000Z"}],
    )

    completed = validate_success(
        api.transition_treatment_plan(bundle["plan"]["id"], {"action": "COMPLETE"}, MANAGER)
    )

    route = fx.read_route(bundle["route"]["id"])
    assert route["duration_minutes"] == 832
    fx.assert_index(route["actual_volume_ml"], 15.00, "actual_volume_ml")
    assert completed["material_cost_cents"] == 60
    assert completed["labor_cost_cents"] == 99840
    assert completed["subtotal_cents"] == 99900


def test_admin_fee_tier_is_keyed_on_the_subtotal_not_on_the_total(api):
    """PRD §3.9: "Fifth, `admin_fee_cents` is `subtotal_cents` multiplied by
    `admin_fee_rate`, rounded half up to a whole number of cents, and
    `total_cost_cents` is `subtotal_cents` plus `admin_fee_cents`. The evaluation
    order is fixed — subtotal, then rate, then fee, then total. The fee is never
    re-derived from the total and no fixed-point iteration is performed, even
    though the tier boundaries happen to be expressed in the same units as the
    total."
    PRD §3.9: "**Completion** closes the plan and is the only moment its cost
    record is written."

    Design: Difficulty/combinatorial_formula/admin_fee_tier_selected_from_subtotal_not_from_total
    """
    bundle = fx.setup_verified_route(
        product_overrides={"reentry_interval_hours": 4},
        actual_acres=0.15, wind_speed_mph=5.0,
        routes=[{"planned_acres": 0.15, "window_start": "2026-06-05T09:00:00.000Z",
                 "window_end": "2026-06-05T22:52:00.000Z"}],
    )

    completed = validate_success(
        api.transition_treatment_plan(bundle["plan"]["id"], {"action": "COMPLETE"}, MANAGER)
    )

    assert completed["subtotal_cents"] == 99900
    assert completed["admin_fee_rate"] == 0.08
    assert completed["admin_fee_cents"] == 7992
    assert completed["total_cost_cents"] == 107892
    assert completed["status"] == "COMPLETED"
    assert completed["completed_at"] == "2026-06-05T09:00:00.000Z"


def test_voiding_the_last_verified_route_reverts_the_completed_plan(api):
    """PRD §3.9: "And because the plan may now have no route in `EXECUTED` or
    `VERIFIED` at all, a parent plan that had already reached `COMPLETED` reverts
    `COMPLETED → IN_PROGRESS`, clears `completed_at` back to null, and zeroes its
    cost record — `material_cost_cents`, `labor_cost_cents`, `subtotal_cents`,
    `admin_fee_cents`, and `total_cost_cents` all return to 0 and `admin_fee_rate`
    returns to `0.0`."

    Design: Difficulty/transitive_cascade/route_void_cascades_three_hops_and_reverts_completed_plan
    """
    bundle = fx.setup_completed_plan(
        treatment_type="ADULTICIDE", posture="EMERGENCY",
        actual_acres=10.0, wind_speed_mph=8.0,
        routes=[{"planned_acres": 10.0, "window_start": "2026-06-05T09:00:00.000Z",
                 "window_end": "2026-06-05T12:00:00.000Z",
                 "center_x_m": 0, "center_y_m": 0}],
    )
    assert bundle["plan"]["total_cost_cents"] == 28080

    voided = validate_success(
        api.transition_treatment_route(
            bundle["route"]["id"],
            {"action": "VOID", "void_reason": "Applicator logged the wrong block"},
            MANAGER,
        )
    )

    assert voided["status"] == "VOIDED"
    plan = fx.read_plan(bundle["plan"]["id"])
    assert plan["status"] == "IN_PROGRESS"
    assert plan["completed_at"] is None
    assert plan["material_cost_cents"] == 0
    assert plan["labor_cost_cents"] == 0
    assert plan["subtotal_cents"] == 0
    assert plan["admin_fee_cents"] == 0
    assert plan["total_cost_cents"] == 0
    assert plan["admin_fee_rate"] == 0.0
    fx.assert_index(plan["estimated_total_ml"], 0.00, "estimated_total_ml")


def test_voiding_returns_applied_millilitres_and_frees_seasonal_capacity(api):
    """PRD §3.9: "Because the application record is being withdrawn, the route's
    `actual_volume_ml` leaves `applied_ml` and returns to `on_hand_ml` and the
    product's `version` advances — which is precisely why the four-field partition
    of §2.9 still balances afterwards. Because that usage no longer counts against
    the area, the area's `seasonal_application_count` decreases by 1, freeing
    capacity under the seasonal cap."
    PRD §3.9: "Voiding also decreases the applicator's `assigned_route_count` by 1
    and triggers a recomputation of the plan's `estimated_total_ml`."

    Design: Difficulty/transitive_cascade/route_void_cascades_three_hops_and_reverts_completed_plan
    """
    bundle = fx.setup_completed_plan(
        treatment_type="ADULTICIDE", posture="EMERGENCY",
        actual_acres=10.0, wind_speed_mph=8.0,
        routes=[{"planned_acres": 10.0, "window_start": "2026-06-05T09:00:00.000Z",
                 "window_end": "2026-06-05T12:00:00.000Z",
                 "center_x_m": 0, "center_y_m": 0}],
    )

    fx.route_action(
        bundle["route"]["id"], "VOID", void_reason="Applicator logged the wrong block"
    )

    product = fx.read_product(bundle["product"]["id"])
    fx.assert_index(product["applied_ml"], 0.00, "applied_ml")
    fx.assert_index(product["committed_ml"], 0.00, "committed_ml")
    fx.assert_index(product["on_hand_ml"], 100000.00, "on_hand_ml")
    fx.assert_index(product["received_total_ml"], 100000.00, "received_total_ml")
    fx.assert_inventory_partition(product)
    assert fx.read_area(bundle["area"]["id"])["seasonal_application_count"] == 0
    assert fx.read_applicator(bundle["applicator"]["id"])["assigned_route_count"] == 0


def test_execution_refused_while_the_plan_is_only_scheduled(api):
    """PRD §3.9: "The parent plan must be `IN_PROGRESS`; a plan that is merely
    `SCHEDULED`, or one currently `SUSPENDED` for weather, is refused with
    `ERR_PLAN_NOT_IN_PROGRESS` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/route_execute_requires_parent_plan_in_progress
    """
    bundle = fx.setup_committed_route(
        applicator_overrides=LARVICIDE_TECH,
        product_overrides={"reentry_interval_hours": 4},
        routes=[{"window_start": "2026-06-05T09:00:00.000Z",
                 "window_end": "2026-06-05T12:00:00.000Z"}],
    )
    fx.plan_action(
        bundle["plan"]["id"], "SCHEDULE", scheduled_start_at="2026-06-05T09:00:00.000Z"
    )
    fx.set_clock("2026-06-05T09:00:00.000Z")

    response = api.transition_treatment_route(
        bundle["route"]["id"],
        {"action": "EXECUTE", "actual_acres": 1.0, "wind_speed_mph": 3.0},
        fx.make_field_tech_headers(bundle["applicator"]["id"]),
    )
    validate_error(response, ApiErrorId.ERR_PLAN_NOT_IN_PROGRESS.value, 409)

    assert fx.read_route(bundle["route"]["id"])["status"] == "COMMITTED"


def test_execution_succeeds_immediately_after_the_plan_starts(api):
    """PRD §3.8: "Starting the operation advances `SCHEDULED → IN_PROGRESS` and is
    permitted only when the logical clock has reached `scheduled_start_at`,
    inclusive; starting earlier is refused with `ERR_PLAN_START_TOO_EARLY` (HTTP
    409). Only from `IN_PROGRESS` may routes be executed."
    PRD §3.9: "**Execution** is the one route action that belongs to the field
    rather than to the office."

    Design: Difficulty/cross_entity_state_dependency/route_execute_requires_parent_plan_in_progress
    """
    bundle = fx.setup_committed_route(
        applicator_overrides=LARVICIDE_TECH,
        product_overrides={"reentry_interval_hours": 4},
        routes=[{"window_start": "2026-06-05T09:00:00.000Z",
                 "window_end": "2026-06-05T12:00:00.000Z"}],
    )
    fx.plan_action(
        bundle["plan"]["id"], "SCHEDULE", scheduled_start_at="2026-06-05T09:00:00.000Z"
    )
    fx.set_clock("2026-06-05T09:00:00.000Z")
    fx.plan_action(bundle["plan"]["id"], "START")

    executed = validate_success(
        api.transition_treatment_route(
            bundle["route"]["id"],
            {"action": "EXECUTE", "actual_acres": 1.0, "wind_speed_mph": 3.0},
            fx.make_field_tech_headers(bundle["applicator"]["id"]),
        )
    )

    assert executed["status"] == "EXECUTED"
    fx.assert_index(executed["actual_volume_ml"], 100.00, "actual_volume_ml")
    fx.assert_index(executed["estimated_volume_ml"], 100.00, "estimated_volume_ml")
    product = fx.read_product(bundle["product"]["id"])
    fx.assert_index(product["applied_ml"], 100.00, "applied_ml")
    fx.assert_index(product["committed_ml"], 0.00, "committed_ml")
    fx.assert_index(product["on_hand_ml"], 99900.00, "on_hand_ml")
