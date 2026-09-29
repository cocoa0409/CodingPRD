"""The two dual-variant calculations: remaining-life projection and load pricing."""
from prd_bench_local_runner.testing import get_success_data, validate_success

from test_helpers import fixtures
from test_helpers.api_client import api_client
from test_helpers.assertions import (
    assert_amount,
    assert_density,
    assert_projection_arithmetic,
    assert_remaining_life_projection,
)
from test_helpers.test_users import TEST_USERS

AGENCY = TEST_USERS["regulatory_agency_headers"]


def _site_with_one_certified_cell():
    """A site owning 1,000,000 certified cubic yards and nothing consumed."""
    landfill = fixtures.create_landfill(
        planned_density_tons_per_cy=0.9, annual_tonnage_forecast=300000
    )
    fixtures.setup_qa_certified_cell(landfill["id"], cell_overrides={"design_airspace_cy": 1000000})
    return landfill


def test_projection_falls_back_to_the_ledger_when_no_survey_is_recorded():
    """With no recorded survey the projection reports design intent, not field reality.

    PRD: "Variant selection is mechanical: if the site has a survey in `RECORDED` whose
    `measured_density_tons_per_cy` is greater than zero, the `variant` is `survey_based`;
    otherwise — no recorded survey at all, or a recorded survey that measured a density
    of zero — the `variant` is `ledger_based`."

    Design: Difficulty/dual_variant_calc/remaining_life_survey_based_vs_ledger_based_divergence
    """
    landfill = _site_with_one_certified_cell()

    projection = get_success_data(
        api_client.get_remaining_life_projection(landfill["id"], AGENCY)
    )

    assert_remaining_life_projection(projection)
    assert projection["variant"] == "ledger_based"
    assert projection["source_survey_id"] is None
    assert_density(projection["density_tons_per_cy"], 0.90, "ledger density")
    assert_amount(projection["remaining_airspace_cy"], 1000000, "ledger remaining airspace")
    assert_amount(projection["remaining_life_years"], 3.00, "ledger remaining life")
    assert_projection_arithmetic(projection)


def test_recording_a_survey_flips_the_projection_onto_the_measured_density():
    """The same site, unchanged, reports a shorter life once a flight is reduced.

    PRD: "Under `survey_based`, the remaining airspace is the recorded survey's
    `measured_remaining_airspace_cy`, the density is that survey's
    `measured_density_tons_per_cy`, and `source_survey_id` is that survey's `id`."

    Design: Difficulty/dual_variant_calc/remaining_life_survey_based_vs_ledger_based_divergence
    """
    landfill = _site_with_one_certified_cell()
    ledger = get_success_data(api_client.get_remaining_life_projection(landfill["id"], AGENCY))

    survey = fixtures.record_aerial_survey(
        landfill["id"],
        flown_on="2026-08-01T00:00:00Z",
        coverage_period_start="2026-05-01T00:00:00Z",
        coverage_period_end="2026-07-31T00:00:00Z",
        measured_remaining_airspace_cy=700000,
        tons_placed_in_period=250000,
    )

    assert survey["status"] == "RECORDED"
    assert_amount(survey["airspace_consumed_in_period_cy"], 300000.00, "consumed in period")
    assert_density(survey["measured_density_tons_per_cy"], 0.8333, "measured density")

    projection = get_success_data(
        api_client.get_remaining_life_projection(landfill["id"], AGENCY)
    )

    assert projection["variant"] == "survey_based"
    assert projection["source_survey_id"] == survey["id"]
    assert_density(projection["density_tons_per_cy"], 0.8333, "survey density")
    assert_amount(projection["remaining_airspace_cy"], 700000, "survey remaining airspace")
    assert_amount(projection["remaining_life_years"], 1.94, "survey remaining life")
    assert_projection_arithmetic(projection)
    assert float(ledger["remaining_life_years"]) != float(projection["remaining_life_years"]), (
        "the two variants must disagree on identical field data"
    )


def test_the_survey_variant_alone_crosses_the_two_year_restriction_threshold():
    """3.00 ledger years leave the site OPEN; 1.94 surveyed years restrict it.

    PRD: "The site's `remaining_life_years` is then recomputed, and if the recomputed
    value falls below 2.0 years while the site is `OPEN`, its `operating_status` moves to
    `RESTRICTED_AIRSPACE`."

    Design: Difficulty/dual_variant_calc/remaining_life_survey_based_vs_ledger_based_divergence
    """
    landfill = _site_with_one_certified_cell()
    before = fixtures.read_landfill(landfill["id"])
    assert before["operating_status"] == "OPEN"
    assert_amount(before["remaining_life_years"], 3.00, "stored remaining life")

    fixtures.record_aerial_survey(
        landfill["id"],
        flown_on="2026-08-01T00:00:00Z",
        coverage_period_start="2026-05-01T00:00:00Z",
        coverage_period_end="2026-07-31T00:00:00Z",
        measured_remaining_airspace_cy=700000,
        tons_placed_in_period=250000,
    )

    after = fixtures.read_landfill(landfill["id"])
    assert_amount(after["remaining_life_years"], 1.94, "stored remaining life")
    assert after["operating_status"] == "RESTRICTED_AIRSPACE"


def _open_day_with_one_manifest_load():
    """An ACTIVE cell, a live host agreement, an OPEN day and one 45.25 t truck."""
    site = fixtures.setup_open_day(
        agreement_overrides={
            "posted_tipping_fee_per_ton": 42.5,
            "host_fee_per_ton": 3.75,
            "tier1_monthly_tons": 100,
            "royalty_tier1_pct": 0.04,
            "royalty_tier2_pct": 0.07,
        },
        day_overrides={
            "operating_date": "2026-08-05T00:00:00Z",
            "working_face_area_sf": 5000,
            "cover_material_type": "ALTERNATIVE_TARP",
        },
    )
    site["load"] = fixtures.receive_load(
        site["landfill"]["id"], site["day"]["id"], manifest_tons=45.25, hauler_ref="H-0001"
    )
    return site


def test_gate_pricing_bills_the_manifest_tonnage_with_no_royalty_component():
    """Clearance prices 45.25 manifest tons at the gate rate and stops there.

    PRD: "It bills the *manifest* tonnage: the gross is `manifest_tons` multiplied by
    `posted_tipping_fee_per_ton`, rounded to 2 decimal places; the host fee is
    `manifest_tons` multiplied by `host_fee_per_ton`, also rounded to 2 decimal places;
    and `gate_charge_amount` is the sum of those two already-rounded components, rounded
    again to 2 decimal places."

    Design: Difficulty/dual_variant_calc/tipping_charge_gate_rate_vs_certified_scale_divergence
    """
    site = _open_day_with_one_manifest_load()

    response = api_client.clear_screening(
        site["load"]["id"], None, site["scale_headers"]
    )
    cleared = validate_success(response, 200)

    assert cleared["screening_status"] == "CLEARED"
    assert cleared["billing_status"] == "PROVISIONAL"
    assert_amount(cleared["gate_charge_amount"], 2092.82, "gate charge")
    assert cleared["host_royalty_amount"] is None, (
        "the gate variant applies no royalty component whatsoever"
    )
    assert cleared["final_charge_amount"] is None
    assert cleared["certified_net_tons"] is None


def test_day_close_reprices_on_certified_tonnage_and_leaves_the_gate_price_standing():
    """Both variant outputs stay readable on one row: 2092.82 gate, 1918.00 final.

    PRD: "For any load whose certified weight differs from its manifest weight, or whose
    tonnage crosses the monthly tier-1 ceiling, `final_charge_amount` will differ from
    `gate_charge_amount` — and both stay on the row, so the divergence is observable and
    auditable."

    Design: Difficulty/dual_variant_calc/tipping_charge_gate_rate_vs_certified_scale_divergence
    """
    site = _open_day_with_one_manifest_load()
    fixtures.clear_screening(site["landfill"]["id"], site["load"]["id"])
    fixtures.certify_weight(site["landfill"]["id"], site["load"]["id"], 40.0)

    fixtures.close_operating_day(site["landfill"]["id"], site["day"]["id"])

    load = get_success_data(
        api_client.get_waste_load(site["load"]["id"], site["scale_headers"])
    )
    assert load["screening_status"] == "CLEARED"
    assert load["billing_status"] == "FINALIZED"
    assert_amount(load["gate_charge_amount"], 2092.82, "gate charge after finalisation")
    assert_amount(load["host_royalty_amount"], 68.00, "host royalty")
    assert_amount(load["final_charge_amount"], 1918.00, "final charge")


def test_the_closed_day_consumes_airspace_at_the_capped_density():
    """40.00 certified tons at the 0.8500 cap burn 47.06 cubic yards.

    PRD: "`airspace_consumed_cy` is then the day's `tons_placed` divided by that
    **already-rounded** four-decimal density, rounded to 2 decimal places — except that
    when `tons_placed` is zero the consumption is exactly 0.00 and no division is
    attempted."

    Design: Difficulty/dual_variant_calc/tipping_charge_gate_rate_vs_certified_scale_divergence
    """
    site = _open_day_with_one_manifest_load()
    fixtures.clear_screening(site["landfill"]["id"], site["load"]["id"])
    fixtures.certify_weight(site["landfill"]["id"], site["load"]["id"], 40.0)

    closed = fixtures.close_operating_day(site["landfill"]["id"], site["day"]["id"])

    assert closed["status"] == "CLOSED"
    assert_amount(closed["tons_placed"], 40.00, "tons placed")
    assert_density(closed["effective_density_tons_per_cy"], 0.8500, "effective density")
    assert_amount(closed["airspace_consumed_cy"], 47.06, "airspace consumed")
