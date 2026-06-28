"""Lactation production figures, feed cost, and income-over-feed-cost.

Difficulty instances:
  dual_variant_calc / lactation_actual_vs_projected305_diverge
  combinatorial_formula / ration_feed_cost_round_per_line_then_sum
Corner instances:
  calculations / iofc_computed_read_correct_value
  cross_cutting_complexity_layers / derived_field_lactation_recompute_after_single_test
"""
from test_helpers import (
    validate_success, get_success_data,
    setup_open_lactation, add_test_day, create_ration,
    api_client, TEST_USERS,
)

HM = TEST_USERS["herd_manager_headers"]


def test_cumulative_milk_uses_test_interval_method():
    """PRD §3.4: "Seed the accumulator with the first test's milk weight
    multiplied by its day-in-milk — this credits production from calving (day 0)
    up to the first test. Then for each subsequent test, add the average of the
    current and previous tests' milk weights, multiplied by the gap in days
    between the current and previous tests' day-in-milk values."
    PRD §3.4: "After processing every test, round the accumulated total to 1
    decimal place."

    Design: Difficulty/dual_variant_calc/lactation_actual_vs_projected305_diverge
    """
    _h, _a, lact, _c = setup_open_lactation(
        herd_name="Lactation Dairy", ear_tag="LA-001",
        service_date="2026-01-10", calving_date="2026-02-01",
        calving_clock="2026-02-01T00:00:00Z",
    )
    add_test_day(lact["id"], "2026-03-13", milk_weight_lbs=85.0, fat_pct=3.8,
                 protein_pct=3.1, scc_thousands=150, clock="2026-05-12T00:00:00Z")
    add_test_day(lact["id"], "2026-04-12", milk_weight_lbs=92.0, fat_pct=3.9,
                 protein_pct=3.0, scc_thousands=160)
    add_test_day(lact["id"], "2026-05-12", milk_weight_lbs=78.0, fat_pct=4.1,
                 protein_pct=3.2, scc_thousands=170)

    data = validate_success(api_client.get_lactation(lact["id"], HM))
    assert data["cumulative_milk_lbs"] == 8605.0, data["cumulative_milk_lbs"]


def test_projected_305d_extrapolates_last_test_to_day_305():
    """PRD §3.4: "If the latest day-in-milk is short of 305 days, the projection
    adds, on top of the cumulative figure, the latest test's milk weight
    multiplied by the number of days remaining to reach 305 (that is, 305 minus
    the latest day-in-milk); the result is rounded to 1 decimal place."

    Design: Difficulty/dual_variant_calc/lactation_actual_vs_projected305_diverge
    """
    _h, _a, lact, _c = setup_open_lactation(
        herd_name="Lactation Dairy 2", ear_tag="LA-002",
        service_date="2026-01-10", calving_date="2026-02-01",
        calving_clock="2026-02-01T00:00:00Z",
    )
    add_test_day(lact["id"], "2026-03-13", milk_weight_lbs=85.0, fat_pct=3.8,
                 protein_pct=3.1, scc_thousands=150, clock="2026-05-12T00:00:00Z")
    add_test_day(lact["id"], "2026-04-12", milk_weight_lbs=92.0, fat_pct=3.9,
                 protein_pct=3.0, scc_thousands=160)
    add_test_day(lact["id"], "2026-05-12", milk_weight_lbs=78.0, fat_pct=4.1,
                 protein_pct=3.2, scc_thousands=170)

    data = validate_success(api_client.get_lactation(lact["id"], HM))
    assert data["projected_305d_milk_lbs"] == 24595.0, data["projected_305d_milk_lbs"]
    assert data["projected_305d_milk_lbs"] != data["cumulative_milk_lbs"], (
        "projection must diverge from realized cumulative"
    )


def test_feed_cost_rounds_each_line_then_sums():
    """PRD §3.1: "On creation the system computes `daily_feed_cost_per_cow`: for each ingredient line, multiply its `lbs_as_fed` by its `price_per_lb` and round that line to the cent; then sum the rounded line costs."
    PRD §3.1: "The rounding is per line and then summed — the system must not
    multiply-and-sum first and round once."

    Design: Difficulty/combinatorial_formula/ration_feed_cost_round_per_line_then_sum
    """
    herd = get_success_data(api_client.create_herd(
        {"name": "Feed Cost Dairy", "federal_order_number": "30"}, HM))
    ration = create_ration(
        herd["id"], name="High Group TMR",
        ingredients=[
            {"ingredient_name": "corn silage", "lbs_as_fed": 55, "price_per_lb": 0.045},
            {"ingredient_name": "alfalfa", "lbs_as_fed": 18, "price_per_lb": 0.125},
            {"ingredient_name": "corn grain", "lbs_as_fed": 21, "price_per_lb": 0.075},
            {"ingredient_name": "protein mix", "lbs_as_fed": 9, "price_per_lb": 0.405},
        ],
    )
    data = validate_success(api_client.get_ration(ration["id"], HM))
    assert data["daily_feed_cost_per_cow"] == 9.96, data["daily_feed_cost_per_cow"]


def test_feed_cost_per_line_rounding_returned_on_create():
    """PRD §3.1: "for each ingredient line, multiply its `lbs_as_fed` by its `price_per_lb` and round that line to the cent; then sum the rounded line costs. The rounding is per line and then summed — the system must not multiply-and-sum first and round once."

    Design: Difficulty/combinatorial_formula/ration_feed_cost_round_per_line_then_sum
    """
    herd = get_success_data(api_client.create_herd(
        {"name": "Feed Cost Dairy 2", "federal_order_number": "30"}, HM))
    ration = create_ration(
        herd["id"], name="High Group TMR",
        ingredients=[
            {"ingredient_name": "corn silage", "lbs_as_fed": 55, "price_per_lb": 0.045},
            {"ingredient_name": "alfalfa", "lbs_as_fed": 18, "price_per_lb": 0.125},
            {"ingredient_name": "corn grain", "lbs_as_fed": 21, "price_per_lb": 0.075},
            {"ingredient_name": "protein mix", "lbs_as_fed": 9, "price_per_lb": 0.405},
        ],
    )
    # The create response itself carries the computed value (round-each-line-then-sum = 9.96,
    # never the sum-raw-then-round-once 9.95).
    assert ration["daily_feed_cost_per_cow"] == 9.96, ration["daily_feed_cost_per_cow"]


def test_iofc_computed_read_returns_revenue_feed_and_iofc():
    """PRD §3.11: "The milk revenue is that test's `milk_weight_lbs` in hundredweight (its pounds divided by 100) times the supplied `blend_price_per_cwt`, rounded to 2 decimal places. The income over feed cost per cow per day is then that milk revenue minus the named ration's `daily_feed_cost_per_cow` — an exact subtraction."

    Design: Corner/calculations/iofc_computed_read_correct_value
    """
    herd = get_success_data(api_client.create_herd(
        {"name": "IOFC Dairy", "federal_order_number": "30"}, HM))
    ration = create_ration(herd["id"], name="High Group TMR")  # default ingredients => 9.96
    # Build the cow + OPEN lactation + one test in the same herd.
    a = get_success_data(api_client.create_animal(
        {"herd_id": herd["id"], "ear_tag": "IO-001", "birth_date": "2023-01-01"}, HM))
    from test_helpers import TEST_USERS as _TU
    vet = _TU["veterinarian_headers"]
    api_client.set_clock("2026-02-01T00:00:00Z", HM)
    be = get_success_data(api_client.create_breeding_event(
        {"animal_id": a["id"], "service_date": "2026-01-10", "sire_code": "S-1"}, vet))
    get_success_data(api_client.confirm_breeding_event(be["id"], vet))
    ce = get_success_data(api_client.create_calving_event(
        {"animal_id": a["id"], "breeding_event_id": be["id"], "calving_date": "2026-02-01"}, HM))
    lact_id = ce["opened_lactation_id"]
    add_test_day(lact_id, "2026-03-13", milk_weight_lbs=85.0, fat_pct=3.8,
                 protein_pct=3.1, scc_thousands=150, clock="2026-03-13T00:00:00Z")

    data = validate_success(api_client.get_iofc(
        a["id"], HM, params={"ration_id": ration["id"], "blend_price_per_cwt": 22.000}))
    assert data["milk_revenue"] == 18.70, data["milk_revenue"]
    assert data["daily_feed_cost_per_cow"] == 9.96, data["daily_feed_cost_per_cow"]
    assert data["iofc_per_cow_per_day"] == 8.74, data["iofc_per_cow_per_day"]


def test_lactation_recomputed_after_single_test_day():
    """PRD §3.4: "Each accepted test day recomputes the owning lactation's two production figures from all of that lactation's test-day records, ordered by `day_in_milk` ascending (ties are impossible because day-in-milk strictly increases)."
    PRD §3.4: "Seed the accumulator with the first test's milk weight multiplied
    by its day-in-milk — this credits production from calving (day 0) up to the
    first test."

    Design: Corner/cross_cutting_complexity_layers/derived_field_lactation_recompute_after_single_test
    """
    _h, _a, lact, _c = setup_open_lactation(
        herd_name="Derived Dairy", ear_tag="DR-001",
        service_date="2026-01-10", calving_date="2026-02-01",
        calving_clock="2026-02-01T00:00:00Z",
    )
    add_test_day(lact["id"], "2026-03-13", milk_weight_lbs=85.0, fat_pct=3.8,
                 protein_pct=3.1, scc_thousands=150, clock="2026-03-13T00:00:00Z")
    data = validate_success(api_client.get_lactation(lact["id"], HM))
    assert data["cumulative_milk_lbs"] == 3400.0, data["cumulative_milk_lbs"]
    assert data["projected_305d_milk_lbs"] == 25925.0, data["projected_305d_milk_lbs"]
