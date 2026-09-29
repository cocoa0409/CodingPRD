"""Multi-input formulas whose pinned composition and rounding order are observable."""
from prd_bench_local_runner.testing import get_success_data

from test_helpers import fixtures
from test_helpers.api_client import api_client
from test_helpers.assertions import (
    assert_amount,
    assert_closure_cost_estimate,
    assert_density,
    assert_estimate_totals_consistent,
)
from test_helpers.test_users import TEST_USERS

ENV_MANAGER = TEST_USERS["environmental_manager_headers"]


def _closed_day(site, operating_date, working_face_area_sf, cover_material_type, tons=100.0):
    """Open a day with one certified 100 t load on it and close it."""
    day = fixtures.open_operating_day(
        site["landfill"]["id"],
        site["cell"]["id"],
        operating_date=operating_date,
        working_face_area_sf=working_face_area_sf,
        cover_material_type=cover_material_type,
    )
    fixtures.place_certified_load(
        site["landfill"]["id"], day["id"], tons, manifest_tons=tons
    )
    return fixtures.close_operating_day(site["landfill"]["id"], day["id"])


def test_effective_density_multiplies_the_cover_factor_by_the_face_penalty():
    """0.90 planned, 0.92 soil cover and the 0.96 medium-face penalty give 0.7949.

    PRD: "The raw density is the site's `planned_density_tons_per_cy` multiplied by the
    day's cover factor and then by the day's face penalty factor."

    Design: Difficulty/combinatorial_formula/daily_airspace_density_composes_three_inputs_with_clamp
    """
    site = fixtures.setup_active_site(landfill_overrides={"planned_density_tons_per_cy": 0.9})

    closed = _closed_day(site, "2026-08-05T00:00:00Z", 9000, "SOIL_6IN")

    assert closed["status"] == "CLOSED"
    assert_amount(closed["tons_placed"], 100.00, "tons placed")
    assert_density(closed["effective_density_tons_per_cy"], 0.7949, "effective density")
    assert_amount(closed["airspace_consumed_cy"], 125.80, "airspace consumed")


def test_the_harshest_cover_and_the_largest_face_compound_into_the_lowest_density():
    """Shredder fines at 0.88 over a 20,000 sf face at 0.90 give 0.7128, burning 140.29 cy.

    PRD: "`working_face_area_sf` drives a separate face penalty, because a sprawling face
    compacts worse: a face larger than 15,000 square feet carries a penalty factor of
    0.90, a face larger than 8,000 but not larger than 15,000 square feet carries 0.96,
    and a face of 8,000 square feet or smaller carries no penalty at all, a factor of
    1.00."

    Design: Difficulty/combinatorial_formula/daily_airspace_density_composes_three_inputs_with_clamp
    """
    site = fixtures.setup_active_site(landfill_overrides={"planned_density_tons_per_cy": 0.9})

    closed = _closed_day(site, "2026-08-06T00:00:00Z", 20000, "AUTO_SHRED_FINES")

    assert_density(closed["effective_density_tons_per_cy"], 0.7128, "effective density")
    assert_amount(closed["airspace_consumed_cy"], 140.29, "airspace consumed")


def test_a_product_above_the_target_density_is_capped_before_the_division():
    """0.90 x 0.97 x 1.00 is 0.8730, but the stored density is the 0.8500 cap.

    PRD: "That raw figure is then raised to at least the density floor of 0.55 tons per
    cubic yard and capped at the target density of 0.85 tons per cubic yard, and the
    clamped value is rounded to 4 decimal places and stored as
    `effective_density_tons_per_cy`."

    Design: Difficulty/combinatorial_formula/daily_airspace_density_composes_three_inputs_with_clamp
    """
    site = fixtures.setup_active_site(landfill_overrides={"planned_density_tons_per_cy": 0.9})

    closed = _closed_day(site, "2026-08-07T00:00:00Z", 5000, "ADC_FOAM")

    assert_density(closed["effective_density_tons_per_cy"], 0.8500, "effective density")
    assert_amount(closed["airspace_consumed_cy"], 117.65, "airspace consumed")


def test_three_days_of_identical_tonnage_accumulate_their_differing_consumption():
    """125.80 plus 140.29 plus 117.65 roll up to 383.74 on the cell and the site.

    PRD: "Consumed airspace is a derivation, not a counter: it is the sum of the airspace
    consumed by every operating day whose working face was this cell and which currently
    sits in `CLOSED`."

    Design: Difficulty/combinatorial_formula/daily_airspace_density_composes_three_inputs_with_clamp
    """
    site = fixtures.setup_active_site(landfill_overrides={"planned_density_tons_per_cy": 0.9})

    _closed_day(site, "2026-08-05T00:00:00Z", 9000, "SOIL_6IN")
    _closed_day(site, "2026-08-06T00:00:00Z", 20000, "AUTO_SHRED_FINES")
    _closed_day(site, "2026-08-07T00:00:00Z", 5000, "ADC_FOAM")

    cell = get_success_data(api_client.get_cell(site["cell"]["id"], site["site_headers"]))
    landfill = fixtures.read_landfill(site["landfill"]["id"])

    assert cell["status"] == "ACTIVE"
    assert_amount(cell["consumed_airspace_cy"], 383.74, "cell consumed airspace")
    assert_amount(landfill["consumed_airspace_cy"], 383.74, "site consumed airspace")


def _site_with_two_certified_cells():
    """Two certified cells, 120001 sf and 45001 sf, so both price final cover."""
    landfill = fixtures.create_landfill()
    fixtures.setup_qa_certified_cell(
        landfill["id"],
        cell_overrides={"cell_code": "C-1", "design_airspace_cy": 1000000, "design_area_sf": 120001},
    )
    fixtures.setup_qa_certified_cell(
        landfill["id"],
        cell_overrides={
            "cell_code": "C-2",
            "design_airspace_cy": 200,
            "design_area_sf": 45001,
            "construction_end_date": "2026-07-20T00:00:00Z",
        },
    )
    return landfill


def _first_estimate(landfill_id):
    return fixtures.file_closure_estimate(
        landfill_id,
        estimate_year=2026,
        closure_unit_cost_per_sf=1.855,
        post_closure_annual_cost=95000.0,
        inflation_pct=0.03,
        post_closure_years=30,
    )


def test_final_cover_cost_rounds_each_cell_term_before_summing():
    """222601.86 plus 83476.86 is 306078.72, one cent above the single-multiply answer.

    PRD: "For each contributing cell, its `design_area_sf` is multiplied by
    `closure_unit_cost_per_sf` and that per-cell term is rounded to 2 decimal places; the
    rounded per-cell terms are then summed and the sum is rounded to 2 decimal places to
    give `closure_cost_total`."

    Design: Difficulty/combinatorial_formula/closure_cost_rounds_per_cell_before_summing
    """
    landfill = _site_with_two_certified_cells()
    assert_amount(
        fixtures.read_landfill(landfill["id"])["certified_airspace_cy"],
        1000200,
        "certified airspace",
    )

    estimate = _first_estimate(landfill["id"])

    assert_closure_cost_estimate(estimate)
    assert_amount(estimate["closure_cost_total"], 306078.72, "closure cost total")
    assert float(estimate["closure_cost_total"]) != 306078.71, (
        "multiplying the summed 165002 square feet by the unit cost is a forbidden result"
    )


def test_post_closure_care_rounds_each_year_before_summing():
    """Thirty inflated annual terms, each rounded to cents first, sum to 4519664.50.

    PRD: "The rounded per-year terms are summed and the sum is rounded to 2 decimal places
    to give `post_closure_cost_total`."

    Design: Difficulty/combinatorial_formula/closure_cost_rounds_per_cell_before_summing
    """
    landfill = _site_with_two_certified_cells()

    estimate = _first_estimate(landfill["id"])

    assert_amount(estimate["post_closure_cost_total"], 4519664.50, "post-closure total")
    assert float(estimate["post_closure_cost_total"]) != 4519664.49, (
        "summing the unrounded inflated terms and rounding once is a forbidden result"
    )


def test_the_required_amount_and_shortfall_follow_from_both_rounding_orders():
    """4825743.22 is only reachable when both pinned summation orders are honoured.

    PRD: "*Step three* sets `required_assurance_amount` to the sum of the two totals,
    rounded to 2 decimal places."

    Design: Difficulty/combinatorial_formula/closure_cost_rounds_per_cell_before_summing
    """
    landfill = _site_with_two_certified_cells()

    estimate = _first_estimate(landfill["id"])

    assert_amount(estimate["required_assurance_amount"], 4825743.22, "required assurance")
    assert_amount(estimate["funding_shortfall"], 4825743.22, "funding shortfall")
    assert_estimate_totals_consistent(estimate)
    assert estimate["status"] == "DRAFT"
    assert fixtures.read_landfill(landfill["id"])["financial_assurance_status"] == "UNFUNDED"


def _agreement_for_surcharge():
    landfill = fixtures.create_landfill()
    agreement = fixtures.register_treatment_agreement(
        landfill["id"],
        facility_name="Valley POTW",
        daily_gallon_cap=20000,
        concurrent_slot_capacity=2,
        base_haul_fee=350.0,
        treatment_rate_per_kgal=62.5,
    )
    return landfill, agreement


def test_the_surcharge_tier_is_read_off_the_pre_surcharge_subtotal():
    """830.00 of treatment plus 350.00 of haul is 1180.00, which sits in the 0.06 band.

    PRD: "*Step three* adds those two and rounds to 2 decimal places to give the
    pre-surcharge subtotal — an intermediate that is deliberately **not** stored on the row
    — and reads `surcharge_pct` off that subtotal: a subtotal below 500.00 dollars attracts
    no surcharge and `surcharge_pct` is 0.00; a subtotal of 500.00 dollars or more but
    below 1200.00 dollars gives a `surcharge_pct` of 0.06; a subtotal of 1200.00 dollars or
    more gives 0.10."

    Design: Difficulty/combinatorial_formula/leachate_surcharge_tier_keyed_on_pre_surcharge_subtotal
    """
    landfill, agreement = _agreement_for_surcharge()

    shipment = fixtures.book_shipment(
        landfill["id"],
        agreement["id"],
        gallons=13280,
        window_start="2026-08-01T02:00:00Z",
        window_end="2026-08-01T04:00:00Z",
    )

    assert shipment["status"] == "SCHEDULED"
    assert_amount(shipment["treatment_fee"], 830.00, "treatment fee")
    assert_amount(shipment["surcharge_pct"], 0.06, "surcharge pct")
    assert shipment["invoice_total"] is None, (
        "the invoice total stays null until the load is accepted"
    )


def test_acceptance_totals_the_subtotal_and_its_surcharge_not_the_higher_tier():
    """1180.00 plus 70.80 is 1250.80; re-keying the tier off the total would give 1298.00.

    PRD: "The tier is always read off the step-three subtotal and never off
    `invoice_total`; feeding the total back into the tier lookup is a different and
    forbidden result."

    Design: Difficulty/combinatorial_formula/leachate_surcharge_tier_keyed_on_pre_surcharge_subtotal
    """
    landfill, agreement = _agreement_for_surcharge()
    shipment = fixtures.book_shipment(
        landfill["id"],
        agreement["id"],
        gallons=13280,
        window_start="2026-08-01T02:00:00Z",
        window_end="2026-08-01T04:00:00Z",
    )
    fixtures.dispatch_shipment(landfill["id"], shipment["id"], hauler_ref="TNK-77")

    accepted = fixtures.accept_shipment(landfill["id"], shipment["id"])

    assert accepted["status"] == "ACCEPTED"
    assert_amount(accepted["invoice_total"], 1250.80, "invoice total")
    assert float(accepted["invoice_total"]) != 1298.00, (
        "keying the tier off the invoice total is a forbidden result"
    )


def test_an_accepted_shipment_still_occupies_its_gallons_for_the_day():
    """13280 booked gallons remain counted after dispatch and acceptance.

    PRD: "`scheduled_gallons_today` is a derivation, not a counter: at any moment it is the
    sum of `gallons` over the shipments of that agreement which are in `SCHEDULED`,
    `DISPATCHED` or `ACCEPTED` and whose `window_start` falls on the current logical
    clock's UTC calendar date."

    Design: Difficulty/combinatorial_formula/leachate_surcharge_tier_keyed_on_pre_surcharge_subtotal
    """
    landfill, agreement = _agreement_for_surcharge()
    shipment = fixtures.book_shipment(
        landfill["id"],
        agreement["id"],
        gallons=13280,
        window_start="2026-08-01T02:00:00Z",
        window_end="2026-08-01T04:00:00Z",
    )
    fixtures.dispatch_shipment(landfill["id"], shipment["id"], hauler_ref="TNK-77")
    fixtures.accept_shipment(landfill["id"], shipment["id"])

    refreshed = get_success_data(
        api_client.get_treatment_agreement(agreement["id"], ENV_MANAGER)
    )
    assert_amount(refreshed["scheduled_gallons_today"], 13280, "scheduled gallons today")
