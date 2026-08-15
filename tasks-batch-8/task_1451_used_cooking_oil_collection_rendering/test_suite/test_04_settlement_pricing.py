"""Settlement pricing: dual variants, combinatorial formula, rounding order,
and publish-recompute cascade."""
import pytest

from test_helpers import (
    ApiErrorId,
    complete_visit,
    create_container,
    create_customer,
    create_manifest,
    create_truck,
    dispatch_manifest,
    draw_and_grade_sample,
    generate_settlement,
    get_success_data,
    make_driver_headers,
    manifest_visits,
    container_visits,
    publish_quote,
    set_clock,
    setup_completed_visit,
    setup_provisional_settlement,
    start_visit,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import BILL, DISP, FOPS, PLANT, create_active_customer


# ---------------------------------------------------------------------------
# Difficulty: settlement provisional vs final divergence
# ---------------------------------------------------------------------------

def _divergence_setup(api):
    """Matches the design recipe: REBATE floor 50 cap 150; pickup 2026-08-05
    pump 200.00 field 8.0; sample graded lab 16.0/1.0 (grade C); quotes
    w07-27 @140 (decoy), w08-03 @100, w08-10 @110; period [08-01, 08-15)."""
    ctx = setup_provisional_settlement(
        name="Diner One",
        container_capacity=1200,
        container_fill_rate=200,
        truck_plate="T-1",
        tank_capacity=2000,
        pump_gallons=200.00,
        field_moisture_pct=8.0,
        quote_weeks=(
            ("2026-07-27", 140),
            ("2026-08-03", 100),
            ("2026-08-10", 110),
        ),
        grade=(16.0, 1.0),
    )
    return ctx


def test_provisional_variant_prices_field_grade_and_latest_week(api, billing_headers):
    """PRD §3.7: "The provisional variant bills `net_gallons_provisional` and
    maps `field_moisture_pct` through the moisture thresholds of §3.6 to a field
    grade."
    PRD §3.7: "The rate source is the `PUBLISHED` quote of the contract's
    `index_code` with the greatest `week_start` that is on or before the
    pickup's `scheduled_date`"
    PRD §3.7: "`B` retains 90 percent (factor 0.90)"

    Net 184.00 gal x rate 90 (= clamp(100 x 0.90) into [50, 150]) == 16560.

    Design: Difficulty/dual_variant_calc/settlement_provisional_vs_final_divergence
    """
    ctx = _divergence_setup(api)
    settlement = ctx["settlement"]
    assert settlement["provisional_total_cents"] == 16560
    lines = get_success_data(api.list_settlement_lines(settlement["id"], billing_headers))
    assert len(lines) == 1
    assert lines[0]["variant"] == "PROVISIONAL"
    assert lines[0]["rate_cents_per_gal"] == pytest.approx(90, abs=0.001)


def test_final_variant_prices_lab_grade_and_period_average(api, billing_headers):
    """PRD §3.7: "The final variant bills lab-netted gallons — the pump gallons
    multiplied by one minus the lab moisture fraction, rounded half-up to two
    decimal places, using the `lab_moisture_pct` of the visit's `GRADED` sample
    — and uses the laboratory `grade` itself. Identical pump gallons can
    therefore net differently between the variants, and the line amounts diverge
    accordingly."
    PRD §3.7: "a final index price equal to the arithmetic mean of
    `price_cents_per_gal` across all `PUBLISHED` quotes of the contract's
    `index_code` whose `week_start` falls inside the half-open billing period"
    PRD §3.7: "`C` retains 75 percent (factor 0.75)"

    Final: net 168.00 gal x rate 78.75 (= mean(100, 110) x 0.75) == 13230.

    Design: Difficulty/dual_variant_calc/settlement_provisional_vs_final_divergence
    """
    ctx = _divergence_setup(api)
    settlement = ctx["settlement"]
    finalized = get_success_data(api.finalize_settlement(settlement["id"], billing_headers))
    assert finalized["provisional_total_cents"] == 16560
    assert finalized["final_total_cents"] == 13230
    assert finalized["provisional_total_cents"] != finalized["final_total_cents"], (
        "the two variants price the same physical pickup differently"
    )
    lines = get_success_data(api.list_settlement_lines(settlement["id"], billing_headers))
    assert len(lines) == 1
    assert lines[0]["variant"] == "FINAL"
    assert lines[0]["rate_cents_per_gal"] == pytest.approx(78.75, abs=0.001)


# ---------------------------------------------------------------------------
# Corner: provisional price uses latest prior week (not highest price)
# ---------------------------------------------------------------------------

def test_provisional_price_uses_latest_prior_week(api, billing_headers):
    """PRD §3.7: "Provisional pricing keys on the pickup date. The rate source
    is the `PUBLISHED` quote of the contract's `index_code` with the greatest
    `week_start` that is on or before the pickup's `scheduled_date`"

    With w07-27 @140 and w08-03 @100, the 2026-08-05 pickup prices at 100
    (rate 90 after the 0.90 field-grade-B factor), not at the higher 140.

    Design: Corner/calculations/c_provisional_price_uses_latest_prior_week
    """
    ctx = setup_provisional_settlement(
        name="Price House",
        container_capacity=1200,
        container_fill_rate=200,
        truck_plate="T-C5",
        tank_capacity=2000,
        pump_gallons=200.00,
        field_moisture_pct=8.0,
        quote_weeks=(("2026-07-27", 140), ("2026-08-03", 100)),
    )
    settlement = ctx["settlement"]
    assert settlement["provisional_total_cents"] == 16560
    lines = get_success_data(api.list_settlement_lines(settlement["id"], billing_headers))
    assert lines[0]["rate_cents_per_gal"] == pytest.approx(90, abs=0.001), (
        "rate must come from w08-03 @100 x 0.90, not w07-27 @140"
    )


# ---------------------------------------------------------------------------
# Corner: settlement lines reverse-reachable from the visit
# ---------------------------------------------------------------------------

def test_settlement_lines_reverse_reachable(api, billing_headers):
    """PRD §3.7: "Each line belongs to its settlement via `settlement_id`,
    references the billed visit via `pickup_visit_id`, records which
    calculation variant produced it in `variant` (`PROVISIONAL` or `FINAL`)"

    Line: net 95.00 (100.00 x (1 - 5.0/100)) x rate 90 (100 x 0.90) == 8550.

    Design: Corner/endpoints/c_settlement_lines_reverse_reachable
    """
    ctx = setup_provisional_settlement(
        name="Line House", truck_plate="T-C17",
        pump_gallons=100.00, field_moisture_pct=5.0,
        quote_weeks=(("2026-08-03", 100),),
    )
    resp = api.list_visit_settlement_lines(ctx["visit"]["id"], billing_headers)
    data = validate_success(resp, expected_status=200)
    assert len(data) == 1
    line = data[0]
    assert line["settlement_id"] == ctx["settlement"]["id"]
    assert line["pickup_visit_id"] == ctx["visit"]["id"]
    assert line["variant"] == "PROVISIONAL"
    assert line["rate_cents_per_gal"] == pytest.approx(90, abs=0.001)
    assert line["line_amount_cents"] == 8550


# ---------------------------------------------------------------------------
# Difficulty: combinatorial formula — SERVICE_FEE overage + REBATE cap clamp
# ---------------------------------------------------------------------------

def _combinatorial_setup(api):
    """Two customers on one manifest: A SERVICE_FEE (fee 2500, threshold 150,
    rate 40), B REBATE (floor 50, cap 120). Both pickups graded lab 16.0/1.0.
    Quotes YG_A w08-03 @100, YG_B w08-03 @200. Both settlements finalized."""
    set_clock("2026-08-02T00:00:00Z")
    cust_a = create_customer(name="Fee House", address="3 Fry Way")
    con_a = get_success_data(
        api.create_contract(
            cust_a["id"],
            {
                "pricing_mode": "SERVICE_FEE",
                "index_code": "YG_A",
                "term_start": "2026-07-01",
                "term_end": "2027-07-01",
                "service_fee_cents": 2500,
                "overage_threshold_gal": 150,
                "overage_rate_cents_per_gal": 40,
            },
            FOPS,
        )
    )
    get_success_data(api.activate_contract(con_a["id"], FOPS))
    ctn_a = create_container(cust_a["id"], capacity=500, fill_rate=200,
                             lock_code="LKA")
    cust_b = create_customer(name="Rebate House", address="4 Fry Way")
    con_b = get_success_data(
        api.create_contract(
            cust_b["id"],
            {
                "pricing_mode": "REBATE",
                "index_code": "YG_B",
                "term_start": "2026-07-01",
                "term_end": "2027-07-01",
                "floor_cents_per_gal": 50,
                "cap_cents_per_gal": 120,
            },
            FOPS,
        )
    )
    get_success_data(api.activate_contract(con_b["id"], FOPS))
    ctn_b = create_container(cust_b["id"], capacity=500, fill_rate=200,
                             lock_code="LKB")
    truck = create_truck(plate="T-3", tank_capacity=2000)
    manifest = create_manifest(truck["id"], [ctn_a["id"], ctn_b["id"]],
                               service_date="2026-08-05")
    dispatch_manifest(manifest["id"], start_level=0)
    v_a = container_visits(ctn_a["id"])[0]
    v_b = container_visits(ctn_b["id"])[0]
    set_clock("2026-08-05T08:00:00Z")
    start_visit(v_a["id"])
    complete_visit(v_a["id"], pump_gallons=200.00, field_moisture_pct=8.0)
    start_visit(v_b["id"])
    complete_visit(v_b["id"], pump_gallons=100.00, field_moisture_pct=8.0)
    draw_and_grade_sample(v_a["id"], lab_moisture_pct=16.0, lab_impurity_pct=1.0)
    draw_and_grade_sample(v_b["id"], lab_moisture_pct=16.0, lab_impurity_pct=1.0)
    publish_quote(index_code="YG_A", week_start="2026-08-03", price=100)
    publish_quote(index_code="YG_B", week_start="2026-08-03", price=200)
    set_clock("2026-08-15T00:00:00Z")
    stl_a = generate_settlement(cust_a["id"])
    get_success_data(api.finalize_settlement(stl_a["id"], BILL))
    stl_b = generate_settlement(cust_b["id"])
    get_success_data(api.finalize_settlement(stl_b["id"], BILL))
    return stl_a, stl_b


def test_service_fee_line_is_negative_fee_plus_overage(api, billing_headers):
    """PRD §3.7: "Under `SERVICE_FEE` pricing, the line's `rate_cents_per_gal`
    is null; the overage gallons are the billed gallons exceeding
    `overage_threshold_gal`, never below zero; and the line amount is the
    negative of `service_fee_cents` plus the overage gallons multiplied by
    `overage_rate_cents_per_gal` rounded half-up to whole cents — the customer
    owes the company."

    Lab-netted 168.00 gal; -(2500 + round(18.00 x 40)) == -3220.

    Design: Difficulty/combinatorial_formula/service_fee_overage_and_rebate_cap_clamp
    """
    stl_a, _ = _combinatorial_setup(api)
    lines = get_success_data(api.list_settlement_lines(stl_a["id"], billing_headers))
    assert len(lines) == 1
    assert lines[0]["line_amount_cents"] == -3220
    assert lines[0]["rate_cents_per_gal"] is None


def test_rebate_line_rate_clamped_at_cap(api, billing_headers):
    """PRD §3.7: "Under `REBATE` pricing, the raw rate is the resolved index
    price multiplied by the grade factor; the applied rate clamps the raw rate,
    raised to `floor_cents_per_gal` if the raw rate is below the floor and
    lowered to `cap_cents_per_gal` if above the cap; the line amount is the
    billed gallons multiplied by the applied rate, rounded half-up to whole
    cents"

    Raw rate 200 x 0.75 == 150 -> clamped to cap 120; 84.00 x 120 == 10080.

    Design: Difficulty/combinatorial_formula/service_fee_overage_and_rebate_cap_clamp
    """
    _, stl_b = _combinatorial_setup(api)
    lines = get_success_data(api.list_settlement_lines(stl_b["id"], billing_headers))
    assert len(lines) == 1
    assert lines[0]["rate_cents_per_gal"] == pytest.approx(120, abs=0.001)
    assert lines[0]["line_amount_cents"] == 10080
    settlement = get_success_data(api.get_settlement(stl_b["id"], billing_headers))
    assert settlement["final_total_cents"] == 10080


# ---------------------------------------------------------------------------
# Difficulty: per-line rounding before summation
# ---------------------------------------------------------------------------

def _rounding_setup(api):
    """floor == cap == 10 forces rate 10 regardless of index; two containers
    completed pump 7.15 and 14.35 at field moisture 0.0 (field grade A)."""
    set_clock("2026-08-02T00:00:00Z")
    customer, _ = create_active_customer(
        name="Rounding House",
        contract_overrides={"floor_cents_per_gal": 10, "cap_cents_per_gal": 10},
    )
    ctn1 = create_container(customer["id"], capacity=50, fill_rate=10,
                            lock_code="LKR1")
    ctn2 = create_container(customer["id"], capacity=50, fill_rate=10,
                            lock_code="LKR2")
    truck = create_truck(plate="T-4", tank_capacity=100)
    manifest = create_manifest(truck["id"], [ctn1["id"], ctn2["id"]],
                               service_date="2026-08-05")
    dispatch_manifest(manifest["id"], start_level=0)
    v1 = container_visits(ctn1["id"])[0]
    v2 = container_visits(ctn2["id"])[0]
    set_clock("2026-08-05T08:00:00Z")
    start_visit(v1["id"])
    complete_visit(v1["id"], pump_gallons=7.15, field_moisture_pct=0.0)
    start_visit(v2["id"])
    complete_visit(v2["id"], pump_gallons=14.35, field_moisture_pct=0.0)
    publish_quote(index_code="YG_CBI", week_start="2026-08-03", price=5)
    set_clock("2026-08-15T00:00:00Z")
    return customer


def test_settlement_total_rounds_each_line_then_sums(api, billing_headers):
    """PRD §3.7: "Rounding order is pinned: each line amount is rounded half-up
    to integer cents first, and the settlement total is the sum of those
    rounded integers. Summing unrounded amounts and rounding once at the end
    produces a different result and is not the contract."

    Lines 71.5 -> 72 and 143.5 -> 144 give total 216; sum-then-round of 215.0
    would be one cent less.

    Design: Difficulty/combinatorial_formula/per_line_rounding_before_sum
    """
    customer = _rounding_setup(api)
    settlement = generate_settlement(customer["id"])
    assert settlement["provisional_total_cents"] == 216
    assert settlement["provisional_total_cents"] != 215


def test_settlement_lines_carry_individually_rounded_amounts(api, billing_headers):
    """PRD §2.6: "**Money** — rates, line amounts, settlement totals, and the
    rebate ledger — is expressed in integer cents (or integer cents per gallon
    for resolved index prices), with each line amount rounded half-up to whole
    cents before any summation."

    Design: Difficulty/combinatorial_formula/per_line_rounding_before_sum
    """
    customer = _rounding_setup(api)
    settlement = generate_settlement(customer["id"])
    lines = get_success_data(api.list_settlement_lines(settlement["id"], billing_headers))
    assert len(lines) == 2
    amounts = sorted(line["line_amount_cents"] for line in lines)
    assert amounts == [72, 144], "7.15 x 10 == 71.5 -> 72; 14.35 x 10 == 143.5 -> 144"


# ---------------------------------------------------------------------------
# Difficulty: publish cascade recomputes PROVISIONAL settlements
# ---------------------------------------------------------------------------

def _publish_cascade_setup(api):
    """Pickup 2026-08-05 pump 200.00 field 8.0; only w08-03 @100 published
    before generate; PROVISIONAL settlement over [08-01, 08-15)."""
    set_clock("2026-08-02T00:00:00Z")
    customer, _ = create_active_customer(name="Index House")
    container = create_container(customer["id"], capacity=1200, fill_rate=200,
                                 lock_code="LKI")
    truck = create_truck(plate="T-6", tank_capacity=2000)
    manifest = create_manifest(truck["id"], [container["id"]],
                               service_date="2026-08-05")
    dispatch_manifest(manifest["id"], start_level=0)
    visit = manifest_visits(manifest["id"])[0]
    set_clock("2026-08-05T08:00:00Z")
    start_visit(visit["id"])
    complete_visit(visit["id"], pump_gallons=200.00, field_moisture_pct=8.0)
    publish_quote(index_code="YG_CBI", week_start="2026-08-03", price=100)
    set_clock("2026-08-15T00:00:00Z")
    settlement = generate_settlement(customer["id"])
    return customer, settlement


def test_publish_recomputes_provisional_settlement_total(api, billing_headers):
    """PRD §3.7: "Publication cascades into open billing. Every settlement
    still in `PROVISIONAL` whose included pickups are priced — under the
    provisional variant — against the published `index_code` has its lines
    recomputed, mutating each affected line's `rate_cents_per_gal` and
    `line_amount_cents` and the settlement's `provisional_total_cents`."

    Newer quote w08-04 @200: rate becomes clamp(200 x 0.90 = 180) == 150, line
    184.00 x 150 == 27600.

    Design: Difficulty/transitive_cascade/index_publish_provisional_recompute_cascade
    """
    _, settlement = _publish_cascade_setup(api)
    assert settlement["provisional_total_cents"] == 16560
    publish_quote(index_code="YG_CBI", week_start="2026-08-04", price=200)
    after = get_success_data(api.get_settlement(settlement["id"], billing_headers))
    assert after["provisional_total_cents"] == 27600


def test_publish_recompute_mutates_lines_and_settlement_version(api, billing_headers):
    """PRD §3.7: "Publication cascades into open billing. Every settlement
    still in `PROVISIONAL` whose included pickups are priced — under the
    provisional variant — against the published `index_code` has its lines
    recomputed, mutating each affected line's `rate_cents_per_gal` and
    `line_amount_cents` and the settlement's `provisional_total_cents`."
    PRD §2.5: "Any mutation of a resource — whether from a client request or
    from a cascade such as a theft confirmation or a quote publication —
    refreshes `updated_at` and increments `version` on each mutated resource
    independently."

    Design: Difficulty/transitive_cascade/index_publish_provisional_recompute_cascade
    """
    _, settlement = _publish_cascade_setup(api)
    v0 = settlement["version"]
    publish_quote(index_code="YG_CBI", week_start="2026-08-04", price=200)
    after = get_success_data(api.get_settlement(settlement["id"], billing_headers))
    assert after["version"] > v0, (
        "settlement version must advance though no settlement endpoint was called"
    )
    lines = get_success_data(api.list_settlement_lines(settlement["id"], billing_headers))
    assert lines[0]["rate_cents_per_gal"] == pytest.approx(150, abs=0.001)
    assert lines[0]["line_amount_cents"] == 27600
