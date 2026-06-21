"""Pricing engine: estimate generation, dual-variant divergence, combinatorial
composition, and the round-per-component-then-sum discipline.

Every test translates exactly one design-index instance (queue A difficulty or
queue B corner) and cites the verbatim PRD sentence that pins its outcome.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    assert_estimate, assert_packing_order,
    create_estimate_payload, create_packing_order_payload,
    register_customer, create_job, create_survey_with_items, add_packing_order,
    generate_estimate, setup_job_with_survey,
    make_estimator_headers, TEST_USERS,
    ITEMS_370CF, ITEMS_120CF, PACKING_LINES_38300,
)

ESTIMATOR = TEST_USERS["estimator_headers"]


def test_estimate_total_diverges_long_haul_vs_local(api):
    """PRD §3.4: "For a `LONG_HAUL` job, pricing is weight-tariff driven and the
    labor field is 0."
    PRD §3.4: "For a `LOCAL` job, pricing is hourly and the linehaul field is 0;
    `distance_miles` is ignored."

    Two jobs with an identical 370cf survey diverge on estimate_total_cents because
    the variant is selected by service_type. Long-haul (BINDING/FULL_VALUE,
    packing, accessorials) totals 666864 with linehaul 543900 and labor 0; local
    (NON_BINDING/RELEASED) totals 70200 with labor 57000 and linehaul 0.

    Design: Difficulty/dual_variant_calc/estimate_total_long_haul_vs_local_diverge
    """
    cust_id = register_customer()["id"]

    # LONG_HAUL job: 900mi, 2 stairs, 1 long-carry, packing, FULL_VALUE.
    lh_job = create_job(cust_id, "LONG_HAUL", origin_zip="90001", destination_zip="10001",
                        distance_miles=900, requested_move_date="2026-07-01T09:00:00Z",
                        stair_flights=2, long_carry_units=1)
    lh_survey = create_survey_with_items(lh_job["id"], ITEMS_370CF)
    add_packing_order(lh_job["id"], PACKING_LINES_38300, crate_count=3)
    lh_job = get_success_data(api.get_move_job(lh_job["id"], ESTIMATOR))
    lh_est = validate_success(api.create_estimate(
        create_estimate_payload(lh_job["id"], lh_survey["id"], lh_job["version"],
                                binding_type="BINDING", valuation_coverage="FULL_VALUE",
                                declared_value_cents=1600000, deductible_cents=50000),
        ESTIMATOR), 201)
    assert_estimate(lh_est)

    # LOCAL job: distance ignored, RELEASED, single dish_pack line.
    loc_job = create_job(cust_id, "LOCAL", origin_zip="90001", destination_zip="90002",
                         distance_miles=0, requested_move_date="2026-07-02T09:00:00Z")
    loc_survey = create_survey_with_items(loc_job["id"], ITEMS_370CF)
    add_packing_order(loc_job["id"],
                      [{"material_code": "dish_pack", "quantity": 2, "unit_price_cents": 1850}],
                      crate_count=0)
    loc_job = get_success_data(api.get_move_job(loc_job["id"], ESTIMATOR))
    loc_est = validate_success(api.create_estimate(
        create_estimate_payload(loc_job["id"], loc_survey["id"], loc_job["version"],
                                binding_type="NON_BINDING", valuation_coverage="RELEASED"),
        ESTIMATOR), 201)

    assert lh_est["estimate_total_cents"] == 666864
    assert lh_est["linehaul_cents"] == 543900
    assert lh_est["labor_cents"] == 0
    assert loc_est["estimate_total_cents"] == 70200
    assert loc_est["labor_cents"] == 57000
    assert loc_est["linehaul_cents"] == 0


def test_long_haul_estimate_composes_tiered_cwt_fuel_and_addons(api):
    """PRD §3.4: "A per-hundredweight rate is selected by a single whole-shipment
    mileage band keyed on the job's `distance_miles`, with both ends of each band
    inclusive: a distance of 0 through 250 miles bills 9,000 cents per
    hundredweight, 251 through 750 miles bills 14,000 cents, 751 through 1,500
    miles bills 21,000 cents, and 1,501 miles or more bills 29,000 cents."
    PRD §3.4: "The `fuel_surcharge_cents` is the `linehaul_cents` multiplied by a
    fuel factor of 8.5 percent, rounded half up."

    A 900mi (751-1500 band, 21000/cwt) 2590lb shipment with packing 38300,
    FULL_VALUE premium 14432, and accessorials 24000 composes to 666864.

    Design: Difficulty/combinatorial_formula/long_haul_tiered_cwt_with_fuel_and_addons
    """
    cust_id = register_customer()["id"]
    job = create_job(cust_id, "LONG_HAUL", origin_zip="90001", destination_zip="10001",
                     distance_miles=900, requested_move_date="2026-07-01T09:00:00Z",
                     stair_flights=2, long_carry_units=1)
    survey = create_survey_with_items(job["id"], ITEMS_370CF)
    add_packing_order(job["id"], PACKING_LINES_38300, crate_count=3)
    job = get_success_data(api.get_move_job(job["id"], ESTIMATOR))
    est = validate_success(api.create_estimate(
        create_estimate_payload(job["id"], survey["id"], job["version"],
                                binding_type="BINDING", valuation_coverage="FULL_VALUE",
                                declared_value_cents=1600000, deductible_cents=50000),
        ESTIMATOR), 201)

    assert est["linehaul_cents"] == 543900
    assert est["fuel_surcharge_cents"] == 46232
    assert est["valuation_premium_cents"] == 14432
    assert est["accessorial_cents"] == 24000
    assert est["packing_cents"] == 38300
    assert est["estimate_total_cents"] == 666864


def test_full_value_declared_value_at_exact_minimum_passes(api):
    """PRD §3.4: "the `declared_value_cents` must be at least the linked survey's
    `estimated_weight_lbs` multiplied by 600 cents (a six-dollar-per-pound minimum
    declared value); a declared value below that floor, or a `deductible_cents`
    that is not one of the allowed amounts, is rejected with
    ERR_DECLARED_VALUE_TOO_LOW."

    A 2590lb shipment has a floor of 2590*600=1554000; declaring exactly 1554000
    is accepted (premium 17094 at deductible 0).

    Design: Difficulty/boundary_precision_check/full_value_declared_value_at_exact_minimum_passes
    """
    cust_id = register_customer()["id"]
    job = create_job(cust_id, "LONG_HAUL", origin_zip="90001", destination_zip="10001",
                     distance_miles=900, requested_move_date="2026-07-01T09:00:00Z")
    survey = create_survey_with_items(job["id"], ITEMS_370CF)
    job = get_success_data(api.get_move_job(job["id"], ESTIMATOR))
    res = api.create_estimate(
        create_estimate_payload(job["id"], survey["id"], job["version"],
                                binding_type="BINDING", valuation_coverage="FULL_VALUE",
                                declared_value_cents=1554000, deductible_cents=0),
        ESTIMATOR)
    est = validate_success(res, 201)
    assert est["valuation_premium_cents"] == 17094


def test_local_estimate_labor_and_travel_components(api):
    """PRD §3.4: "The `labor_cents` is that hourly rate multiplied by the billable
    hours, rounded half up."
    PRD §3.4: "A flat travel fee equal to the hourly rate multiplied by a half-hour
    of travel time is rounded half up and stored in `fuel_surcharge_cents` (a local
    job reuses the fuel field slot for its travel charge); for a local job
    `linehaul_cents` is 0."

    The same 370cf LOCAL job that totals 70200: labor 57000, fuel/travel slot, and
    linehaul pinned to 0 — the local variant's component breakdown, complementing
    the divergence assertion.

    Design: Difficulty/dual_variant_calc/estimate_total_long_haul_vs_local_diverge
    """
    cust_id = register_customer()["id"]
    job = create_job(cust_id, "LOCAL", origin_zip="90001", destination_zip="90002",
                     distance_miles=0, requested_move_date="2026-07-02T09:00:00Z")
    survey = create_survey_with_items(job["id"], ITEMS_370CF)
    add_packing_order(job["id"],
                      [{"material_code": "dish_pack", "quantity": 2, "unit_price_cents": 1850}],
                      crate_count=0)
    job = get_success_data(api.get_move_job(job["id"], ESTIMATOR))
    est = validate_success(api.create_estimate(
        create_estimate_payload(job["id"], survey["id"], job["version"],
                                binding_type="NON_BINDING", valuation_coverage="RELEASED"),
        ESTIMATOR), 201)
    assert est["labor_cents"] == 57000
    assert est["linehaul_cents"] == 0
    assert est["estimate_total_cents"] == 70200


def test_long_haul_full_value_premium_with_deductible_credit(api):
    """PRD §3.4: "First a base premium is computed as the declared value divided by
    10,000 and multiplied by a rate of 110 cents per hundred dollars of declared
    value (that is, $1.10 per $100), rounded half up to integer cents, and then
    floored to a minimum premium of 7,500 cents ($75) — the base is the larger of
    that $75 floor and the rounded rate figure."
    PRD §3.4: "The final `valuation_premium_cents` is the base premium multiplied by
    one minus that credit fraction, again rounded half up to integer cents."

    declared 1600000 -> base round(160*110)=17600; deductible 50000 -> 18% credit ->
    round(17600*0.82)=14432. A second assertion on the combinatorial instance,
    isolating the valuation premium sub-formula that feeds the 666864 total.

    Design: Difficulty/combinatorial_formula/long_haul_tiered_cwt_with_fuel_and_addons
    """
    cust_id = register_customer()["id"]
    job = create_job(cust_id, "LONG_HAUL", origin_zip="90001", destination_zip="10001",
                     distance_miles=900, requested_move_date="2026-07-01T09:00:00Z",
                     stair_flights=2, long_carry_units=1)
    survey = create_survey_with_items(job["id"], ITEMS_370CF)
    add_packing_order(job["id"], PACKING_LINES_38300, crate_count=3)
    job = get_success_data(api.get_move_job(job["id"], ESTIMATOR))
    est = validate_success(api.create_estimate(
        create_estimate_payload(job["id"], survey["id"], job["version"],
                                binding_type="BINDING", valuation_coverage="FULL_VALUE",
                                declared_value_cents=1600000, deductible_cents=50000),
        ESTIMATOR), 201)
    assert est["valuation_premium_cents"] == 14432
    assert est["estimate_total_cents"] == 666864


def test_full_value_declared_value_one_below_minimum_rejected(api):
    """PRD §3.4: "the `declared_value_cents` must be at least the linked survey's
    `estimated_weight_lbs` multiplied by 600 cents (a six-dollar-per-pound minimum
    declared value); a declared value below that floor, or a `deductible_cents`
    that is not one of the allowed amounts, is rejected with
    ERR_DECLARED_VALUE_TOO_LOW."

    The X-1 side of the boundary: 1553999 (one cent under the 1554000 floor) is
    rejected, the negative twin of the accepted-at-exact-minimum case.

    Design: Difficulty/boundary_precision_check/full_value_declared_value_at_exact_minimum_passes
    """
    cust_id = register_customer()["id"]
    job = create_job(cust_id, "LONG_HAUL", origin_zip="90001", destination_zip="10001",
                     distance_miles=900, requested_move_date="2026-07-01T09:00:00Z")
    survey = create_survey_with_items(job["id"], ITEMS_370CF)
    job = get_success_data(api.get_move_job(job["id"], ESTIMATOR))
    res = api.create_estimate(
        create_estimate_payload(job["id"], survey["id"], job["version"],
                                binding_type="BINDING", valuation_coverage="FULL_VALUE",
                                declared_value_cents=1553999, deductible_cents=0),
        ESTIMATOR)
    validate_error(res, "ERR_DECLARED_VALUE_TOO_LOW", 422)


def test_full_value_declared_value_below_minimum_rejected(api):
    """PRD §3.4: "the `declared_value_cents` must be at least the linked survey's
    `estimated_weight_lbs` multiplied by 600 cents (a six-dollar-per-pound minimum
    declared value); a declared value below that floor, or a `deductible_cents`
    that is not one of the allowed amounts, is rejected with
    ERR_DECLARED_VALUE_TOO_LOW."

    1553999 is one cent below the 2590*600=1554000 floor and is rejected.

    Design: Corner/validations/declared_value_too_low_returns_422
    """
    cust_id = register_customer()["id"]
    job = create_job(cust_id, "LONG_HAUL", origin_zip="90001", destination_zip="10001",
                     distance_miles=900, requested_move_date="2026-07-01T09:00:00Z")
    survey = create_survey_with_items(job["id"], ITEMS_370CF)
    job = get_success_data(api.get_move_job(job["id"], ESTIMATOR))
    res = api.create_estimate(
        create_estimate_payload(job["id"], survey["id"], job["version"],
                                binding_type="BINDING", valuation_coverage="FULL_VALUE",
                                declared_value_cents=1553999, deductible_cents=0),
        ESTIMATOR)
    validate_error(res, "ERR_DECLARED_VALUE_TOO_LOW", 422)


def test_packing_total_with_crates_and_lines(api):
    """PRD §3.3: "It is the subtotal of the material lines — the sum over each line
    of that line's `quantity` times its `unit_price_cents` — plus a flat
    custom-crate fee of 9,500 cents (ninety-five dollars) for each crate counted
    in `crate_count`; that combined figure is rounded half up to integer cents."

    4*1850 + 2*1200 + 3*9500 = 7400 + 2400 + 28500 = 38300 cents.

    Design: Corner/calculations/packing_total_with_crates_correct
    """
    cust_id = register_customer()["id"]
    job = create_job(cust_id, "LOCAL")
    res = api.create_packing_order(
        create_packing_order_payload(job["id"], PACKING_LINES_38300, crate_count=3),
        ESTIMATOR)
    po = validate_success(res, 201)
    assert_packing_order(po)
    assert po["packing_total_cents"] == 38300


def test_new_estimate_starts_in_draft(api):
    """PRD §3.4: "A fresh estimate's `status` is `DRAFT`."
    PRD §2.4: "`version` (integer): a system-managed integer that starts at its
    initial value and increments by one on every mutation of the resource."

    Design: Corner/state_machines/initial_state_of_new_estimate_is_draft
    """
    cust_id, job, survey = setup_job_with_survey(service_type="LOCAL", items=ITEMS_120CF)
    res = api.create_estimate(
        create_estimate_payload(job["id"], survey["id"], job["version"],
                                binding_type="BINDING", valuation_coverage="RELEASED"),
        ESTIMATOR)
    est = validate_success(res, 201)
    assert est["status"] == "DRAFT"
    assert est["version"] == 1
