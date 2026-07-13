"""Calculation tests: overtime pay dual-variant, tiered material recommendation,
per-line cost rounding, and numeric-threshold boundaries.

Difficulty queue: dual_variant_calc, combinatorial_formula, boundary_precision_check.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, ApiErrorId, TEST_USERS,
    new_operator, new_storm, new_callout, complete_callout,
    setup_started_assignment, setup_recorded_application,
    new_application, make_operator_headers,
)

DISPATCH = TEST_USERS["dispatch_headers"]
YARD = TEST_USERS["yard_headers"]


# --- dual_variant_calc / overtime_standard_vs_storm -----------------------

def test_overtime_standard_variant_pay(api):
    """PRD §3.7: "A `LIGHT` or `MODERATE` storm uses the standard variant, recorded
    as `pay_mode` `STANDARD`". PRD §3.7: "Under `STANDARD`, the overtime threshold is
    8 hours, the overtime multiplier is 1.5, and the guaranteed callout minimum is 2
    hours." PRD §3.7: "Finally, `pay_cents` is the regular hours times the operator's
    `hourly_rate_cents`, plus the overtime hours times the operator's
    `hourly_rate_cents` times the variant's multiplier, with the final cents value
    rounded half up."

    Design: Difficulty/dual_variant_calc/overtime_standard_vs_storm
    """
    op = new_operator(hourly_rate_cents=4000)
    storm = new_storm(name="Moderate", severity="MODERATE")
    co = new_callout(storm["id"], op["id"],
                     window_start_at="2026-02-10T00:00:00Z", window_end_at="2026-02-10T08:00:00Z")
    resp = api.complete_callout(co["id"], {"hours_worked": 10}, make_operator_headers(op["id"]))
    data = validate_success(resp, 200)
    assert data["pay_mode"] == "STANDARD", f"expected STANDARD, got {data['pay_mode']}"
    assert data["pay_cents"] == 44000, f"expected 44000, got {data['pay_cents']}"


def test_overtime_storm_variant_pay(api):
    """PRD §3.7: "a `SEVERE` or `EMERGENCY` storm uses the storm variant, recorded as
    `pay_mode` `STORM_MODE`". PRD §3.7: "Under `STORM_MODE`, the overtime threshold is
    6 hours, the overtime multiplier is 2.0, and the guaranteed callout minimum is 3
    hours — so for identical `hours_worked` a storm-mode completion always yields
    strictly higher pay."

    Design: Difficulty/dual_variant_calc/overtime_standard_vs_storm
    """
    op = new_operator(hourly_rate_cents=4000)
    storm = new_storm(name="Severe", severity="SEVERE")
    co = new_callout(storm["id"], op["id"],
                     window_start_at="2026-02-11T00:00:00Z", window_end_at="2026-02-11T08:00:00Z")
    resp = api.complete_callout(co["id"], {"hours_worked": 10}, make_operator_headers(op["id"]))
    data = validate_success(resp, 200)
    assert data["pay_mode"] == "STORM_MODE", f"expected STORM_MODE, got {data['pay_mode']}"
    assert data["pay_cents"] == 56000, f"expected 56000, got {data['pay_cents']}"


# --- dual_variant_calc / cost_estimate_vs_actual --------------------------

def _cost_scene():
    """SEVERE storm, ARTERIAL route (2.0 lane-miles), COMBO vehicle, operator 4000
    with a COMPLETED callout (8h window -> pay 56000), one IN_PROGRESS assignment
    planned 2.0 with one RECORDED SALT application of 1.0 ton."""
    scene = setup_recorded_application(salt_tons=1.0, planned_material_tons=2.0, severity="SEVERE")
    complete_callout(scene["callout"]["id"], scene["operator"]["id"], 10)
    return scene


def test_cost_report_estimate_totals(api):
    """PRD §3.9: "Its material lines are this storm's route assignments whose `status`
    is `PLANNED`, `IN_PROGRESS`, or `COMPLETED`; each contributes its
    `planned_material_tons` times 8,500 cents, rounded half up, and these are summed
    into `total_material_cost_cents`." PRD §3.9: "Its labor lines are this storm's
    callouts whose `status` is `ISSUED` or `COMPLETED`; each contributes a straight-time
    projection equal to the number of hours between its `window_start_at` and
    `window_end_at` times the operator's `hourly_rate_cents`, rounded half up, with no
    overtime multiplier applied, and these are summed into `total_labor_cost_cents`."

    Design: Difficulty/dual_variant_calc/cost_estimate_vs_actual
    """
    scene = _cost_scene()
    resp = api.create_cost_report(scene["storm"]["id"], {"variant": "ESTIMATE"},
                                  DISPATCH)
    data = validate_success(resp, 201)
    assert data["total_material_cost_cents"] == 17000, data
    assert data["total_labor_cost_cents"] == 32000, data
    assert data["total_cost_cents"] == 49000, data


def test_cost_report_actual_totals(api):
    """PRD §3.9: "Its material lines are this storm's material applications whose
    `status` is `RECORDED` (voided applications are excluded); each salt line contributes
    its `salt_tons` times 8,500 cents and each brine line its `brine_gallons` times 25
    cents, each rounded half up, then summed into `total_material_cost_cents`." PRD §3.9:
    "Its labor lines are this storm's callouts whose `status` is `COMPLETED`; their
    already-integer `pay_cents` values — which include any overtime — are summed directly
    into `total_labor_cost_cents`."

    Design: Difficulty/dual_variant_calc/cost_estimate_vs_actual
    """
    scene = _cost_scene()
    resp = api.create_cost_report(scene["storm"]["id"], {"variant": "ACTUAL"},
                                  DISPATCH)
    data = validate_success(resp, 201)
    assert data["total_material_cost_cents"] == 8500, data
    assert data["total_labor_cost_cents"] == 56000, data
    assert data["total_cost_cents"] == 64500, data


# --- combinatorial_formula / material_rate_tiered_nonlinear ---------------

def test_material_recommendation_arterial_cold(api):
    """PRD §3.6: "The recommendation is the product of four factors: the
    `lane_miles_treated`, a base spread rate of 0.15 tons per lane-mile, a temperature
    factor selected from the measured `pavement_temp_f`, and a tier multiplier selected
    from the route's `tier`." PRD §3.6: "The temperature factor is 0.8 when the pavement
    temperature is at least 30 degrees Fahrenheit; 1.0 when it is at least 20 but below
    30; 1.3 when it is at least 10 but below 20; and 1.6 when it is below 10. The tier
    multiplier is 1.0 for an `ARTERIAL` route and 0.6 for a `RESIDENTIAL` route. The four
    factors are multiplied together and the result is rounded half up to two decimal
    places to yield `recommended_salt_tons`."

    Design: Difficulty/combinatorial_formula/material_rate_tiered_nonlinear
    """
    scene = setup_started_assignment(planned_material_tons=2.0, tier="ARTERIAL")
    app = new_application(scene["assignment"]["id"], scene["operator"]["id"], scene["depot"]["id"],
                          material_type="SALT", salt_tons=0.5, lane_miles_treated=2.0, pavement_temp_f=15)
    # 2.0 * 0.15 * 1.3 (10<=t<20) * 1.0 (ARTERIAL) = 0.39
    assert app["recommended_salt_tons"] == 0.39, f"expected 0.39, got {app['recommended_salt_tons']}"


def test_material_recommendation_residential_mild(api):
    """PRD §3.6: "The temperature factor is 0.8 when the pavement temperature is at least
    30 degrees Fahrenheit; 1.0 when it is at least 20 but below 30; 1.3 when it is at
    least 10 but below 20; and 1.6 when it is below 10. The tier multiplier is 1.0 for an
    `ARTERIAL` route and 0.6 for a `RESIDENTIAL` route. The four factors are multiplied
    together and the result is rounded half up to two decimal places to yield
    `recommended_salt_tons`."

    Design: Difficulty/combinatorial_formula/material_rate_tiered_nonlinear
    """
    scene = setup_started_assignment(planned_material_tons=2.0, tier="RESIDENTIAL", lane_miles=1.0)
    app = new_application(scene["assignment"]["id"], scene["operator"]["id"], scene["depot"]["id"],
                          material_type="SALT", salt_tons=0.5, lane_miles_treated=2.0, pavement_temp_f=35)
    # 2.0 * 0.15 * 0.8 (t>=30) * 0.6 (RESIDENTIAL) = 0.144 -> round half up 2dp = 0.14
    assert app["recommended_salt_tons"] == 0.14, f"expected 0.14, got {app['recommended_salt_tons']}"


# --- combinatorial_formula / cost_material_round_per_line -----------------

def test_actual_material_cost_rounds_per_line_two_apps(api):
    """PRD §3.9: "In every material total, each contributing line is rounded half up to
    integer cents on its own before the lines are summed — the per-line rounding happens
    first, and summing already-rounded lines is required." PRD §3.9: "each salt line
    contributes its `salt_tons` times 8,500 cents and each brine line its `brine_gallons`
    times 25 cents, each rounded half up, then summed into `total_material_cost_cents`."

    Design: Difficulty/combinatorial_formula/cost_material_round_per_line
    """
    scene = setup_started_assignment(planned_material_tons=0)
    for _ in range(2):
        new_application(scene["assignment"]["id"], scene["operator"]["id"], scene["depot"]["id"],
                        material_type="SALT", salt_tons=1.2345, lane_miles_treated=2.0, pavement_temp_f=15)
    resp = api.create_cost_report(scene["storm"]["id"], {"variant": "ACTUAL"},
                                  DISPATCH)
    data = validate_success(resp, 201)
    # per line: round_half_up(1.2345*8500 = 10493.25) = 10493; sum = 20986 (not 20987)
    assert data["total_material_cost_cents"] == 20986, data
    assert data["total_labor_cost_cents"] == 0, data
    assert data["total_cost_cents"] == 20986, data


def test_actual_material_cost_single_line_rounding(api):
    """PRD §3.9: "In every material total, each contributing line is rounded half up to
    integer cents on its own before the lines are summed — the per-line rounding happens
    first, and summing already-rounded lines is required."

    Design: Difficulty/combinatorial_formula/cost_material_round_per_line
    """
    scene = setup_started_assignment(planned_material_tons=0)
    new_application(scene["assignment"]["id"], scene["operator"]["id"], scene["depot"]["id"],
                    material_type="SALT", salt_tons=1.2345, lane_miles_treated=2.0, pavement_temp_f=15)
    resp = api.create_cost_report(scene["storm"]["id"], {"variant": "ACTUAL"},
                                  DISPATCH)
    data = validate_success(resp, 201)
    # round_half_up(1.2345*8500 = 10493.25) = 10493
    assert data["total_material_cost_cents"] == 10493, data


# --- boundary_precision_check / overtime_threshold_eight_hours ------------

def test_overtime_exactly_eight_hours_no_overtime(api):
    """PRD §3.7: "The `overtime_hours` are the paid hours in excess of the threshold, and
    zero when the paid hours do not exceed it — overtime accrues strictly above the
    threshold, not at it." PRD §3.7: "Under `STANDARD`, the overtime threshold is 8 hours,
    the overtime multiplier is 1.5, and the guaranteed callout minimum is 2 hours."

    Design: Difficulty/boundary_precision_check/overtime_threshold_eight_hours
    """
    op = new_operator(hourly_rate_cents=4000)
    storm = new_storm(name="Moderate", severity="MODERATE")
    co = new_callout(storm["id"], op["id"],
                     window_start_at="2026-02-10T00:00:00Z", window_end_at="2026-02-10T08:00:00Z")
    resp = api.complete_callout(co["id"], {"hours_worked": 8.0}, make_operator_headers(op["id"]))
    data = validate_success(resp, 200)
    assert data["overtime_hours"] == 0, data
    assert data["pay_cents"] == 32000, data


def test_overtime_just_above_eight_hours(api):
    """PRD §3.7: "The `overtime_hours` are the paid hours in excess of the threshold, and
    zero when the paid hours do not exceed it — overtime accrues strictly above the
    threshold, not at it." PRD §3.7: "Finally, `pay_cents` is the regular hours times the
    operator's `hourly_rate_cents`, plus the overtime hours times the operator's
    `hourly_rate_cents` times the variant's multiplier, with the final cents value rounded
    half up."

    Design: Difficulty/boundary_precision_check/overtime_threshold_eight_hours
    """
    op = new_operator(hourly_rate_cents=4000)
    storm = new_storm(name="Moderate", severity="MODERATE")
    co = new_callout(storm["id"], op["id"],
                     window_start_at="2026-02-11T00:00:00Z", window_end_at="2026-02-11T08:00:00Z")
    resp = api.complete_callout(co["id"], {"hours_worked": 8.01}, make_operator_headers(op["id"]))
    data = validate_success(resp, 200)
    # regular 8 * 4000 = 32000; overtime 0.01 * 4000 * 1.5 = 60 -> 32060
    assert data["pay_cents"] == 32060, data


# --- boundary_precision_check / depot_exact_remaining_material ------------

def test_application_consumes_exact_remaining_salt(api):
    """PRD §2.8: "an application that would draw more than the depot holds is refused
    before any debit occurs." PRD §3.6: "The depot must hold enough first —
    `salt_tons_on_hand` at least `salt_tons` for salt, or `brine_gallons_on_hand` at least
    `brine_gallons` for brine — or the request is rejected with `ERR_INSUFFICIENT_MATERIAL`
    and no debit occurs."

    Design: Difficulty/boundary_precision_check/depot_exact_remaining_material
    """
    scene = setup_started_assignment(planned_material_tons=10.0, salt_tons_on_hand=10.0)
    new_application(scene["assignment"]["id"], scene["operator"]["id"], scene["depot"]["id"],
                    material_type="SALT", salt_tons=10.0, lane_miles_treated=2.0, pavement_temp_f=15)
    depot = validate_success(
        api.get_depot(scene["depot"]["id"], YARD), 200)
    assert depot["salt_tons_on_hand"] == pytest.approx(0.0, abs=1e-9), depot


def test_application_one_hundredth_over_remaining_rejected(api):
    """PRD §3.6: "The depot must hold enough first — `salt_tons_on_hand` at least
    `salt_tons` for salt, or `brine_gallons_on_hand` at least `brine_gallons` for brine —
    or the request is rejected with `ERR_INSUFFICIENT_MATERIAL` and no debit occurs."

    Design: Difficulty/boundary_precision_check/depot_exact_remaining_material
    """
    scene = setup_started_assignment(planned_material_tons=10.0, salt_tons_on_hand=10.0)
    op_headers = make_operator_headers(scene["operator"]["id"])
    api.create_application(scene["assignment"]["id"],
                           {"depot_id": scene["depot"]["id"], "material_type": "SALT",
                            "salt_tons": 10.0, "lane_miles_treated": 2.0, "pavement_temp_f": 15},
                           op_headers)
    resp = api.create_application(scene["assignment"]["id"],
                                  {"depot_id": scene["depot"]["id"], "material_type": "SALT",
                                   "salt_tons": 0.01, "lane_miles_treated": 2.0, "pavement_temp_f": 15},
                                  op_headers)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_MATERIAL.value, 409)
