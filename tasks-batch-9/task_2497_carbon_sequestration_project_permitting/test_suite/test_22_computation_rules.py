"""Derived-number computation rules of the carbon storage permitting file.

Every figure exercised here is computed by the server from a pinned evaluation
order: the confining-zone rate cap and the plume and area-of-review radii of a
simulated geologic model, the five cost buckets that size the required financial
assurance, a legacy wellbore's leakage risk score and corrective-action cost, the
project-level pore-space aggregates, and the assurance waterfall that fills an
instrument's four buckets and reconciles back onto the project.
"""

import pytest

from prd_bench_local_runner.testing import validate_success
from test_helpers import fixtures
from test_helpers.constants import (
    CHARLIE_PROJECT,
    STARTUP_CLOCK_UTC,
    WELLBORE_UNKNOWN_PLUG_MID,
)
from test_helpers.factories import accept_offer_payload, allocate_payload
from test_helpers.test_users import make_landowner_headers


def test_plume_simulation_derives_radii_and_rate_cap_for_twenty_year_injection(
    api, project_developer_headers
):
    """It records `injection_years` on the model and then performs a chain of computations whose evaluation order is pinned, each step consuming the stored output of the step before it rather than re-deriving it.

    The largest annual rate the confining zone tolerates, `max_injection_rate_tpy`, is that allowable buildup multiplied by `permeability_md`, multiplied by `porosity_fraction`, multiplied by 1000, divided by the injection buildup coefficient of 45.0, and then floored to a whole number of tonnes.

    The rate the project will actually be able to use, `effective_injection_rate_tpy`, is the smaller of the parent project's `requested_annual_injection_rate_tpy` and that `max_injection_rate_tpy` — a developer who asks for more than the rock allows receives the rock's answer, and a developer who asks for less receives what they asked for.

    `plume_radius_km` is the square root of that swept area, divided by 1000.0 to convert metres to kilometres, rounded half up to 3 decimal places.

    `pressure_front_radius_km` is `plume_radius_km` multiplied by the pressure-front multiplier of 1.8, rounded half up to 3 decimal places.

    The model's own `aor_radius_km` takes the larger of those two radii, multiplies it by 10.0, rounds that product *up* to the next whole number, and divides by 10.0 — in other words, the area-of-review radius is the greater of the free-phase plume and pressure-front radii, rounded up to the next tenth of a kilometre.

    Completing the simulation moves `plume_status` from `NOT_RUN` to `SIMULATED` and bumps the model's `version`.

    Until this delineation has happened for some accepted model, the project's `aor_radius_km` remains 0, and every operation that depends on a delineated area of review is refused with `ERR_AOR_NOT_DELINEATED` (HTTP 422).

    Design: Corner/calculations/plume_and_aor_radii_correct_result_for_twenty_year_injection
    """
    fixtures.set_logical_clock(api, STARTUP_CLOCK_UTC)
    project = fixtures.open_project(api)
    model = fixtures.register_geologic_model(api, project["id"], project["version"])

    response = api.run_plume_simulation(
        model["id"], {"injection_years": 20}, project_developer_headers
    )
    simulated = validate_success(response, 200)

    assert simulated["max_injection_rate_tpy"] == 1200000
    assert simulated["effective_injection_rate_tpy"] == 1000000
    assert simulated["plume_radius_km"] == 1.612
    assert simulated["pressure_front_radius_km"] == 2.902
    assert simulated["aor_radius_km"] == 3.0

    stored = fixtures.refresh_model(api, model["id"])
    assert stored["max_injection_rate_tpy"] == 1200000
    assert stored["effective_injection_rate_tpy"] == 1000000
    assert stored["injection_years"] == 20
    assert stored["plume_status"] == "SIMULATED"

    refreshed_project = fixtures.refresh_project(api, project["id"])
    assert refreshed_project["aor_radius_km"] == 0


def test_required_assurance_plugging_bucket_excludes_draft_permits(
    api, second_reviewer_headers
):
    """The plugging bucket is 850,000.00 dollars for each injection well permit of the project whose `permit_status` is `SUBMITTED`, `TECHNICAL_REVIEW`, `REVISION_REQUESTED`, `APPROVED`, `ACTIVE` or `SUSPENDED`; permits still at `DRAFT` and permits that reached `DENIED` are not counted.

    The project's `required_financial_assurance_usd` is the sum of those five already-rounded buckets, itself rounded half up to 2 decimal places.

    `APPROVE` is admissible from `TECHNICAL_REVIEW` and additionally requires the project's `corrective_action_completion_pct` to equal 100; approval moves `permit_status` `TECHNICAL_REVIEW → APPROVED`, recomputes the project's `required_financial_assurance_usd` and `assurance_coverage_status` because an approved permit now counts toward the plugging bucket, and increments both the permit's `version` and the project's `version`.

    A project with nothing allocated therefore reads `UNFUNDED` even when its requirement happens to be zero.

    Design: Corner/calculations/required_assurance_excludes_draft_permits_from_plugging_bucket
    """
    ctx = fixtures.setup_project_with_finalized_aor(api)
    project_id = ctx["project"]["id"]
    first_permit = fixtures.create_permit(
        api, project_id, ctx["model"]["id"], well_name="ALPHA-1"
    )
    second_permit = fixtures.create_permit(
        api, project_id, ctx["model"]["id"], well_name="ALPHA-2"
    )

    with_two_drafts = fixtures.refresh_project(api, project_id)
    assert with_two_drafts["required_financial_assurance_usd"] == pytest.approx(
        24637166.94, abs=0.01
    )

    fixtures.submit_permit(api, first_permit["id"])
    fixtures.rule_on_permit(api, first_permit["id"], "BEGIN_TECHNICAL_REVIEW")

    response = api.review_injection_well_permit(
        first_permit["id"],
        {"decision": "APPROVE", "review_note": "construction standards met"},
        second_reviewer_headers,
    )
    approved = validate_success(response, 200)
    assert approved["permit_status"] == "APPROVED"

    assert (
        fixtures.refresh_permit(api, second_permit["id"])["permit_status"] == "DRAFT"
    )

    after_approval = fixtures.refresh_project(api, project_id)
    assert after_approval["required_financial_assurance_usd"] == pytest.approx(
        25487166.94, abs=0.01
    )
    assert after_approval["assurance_coverage_status"] == "UNFUNDED"


def test_required_assurance_applies_tier_one_admin_fee_and_emergency_floor(
    api, regulatory_reviewer_headers
):
    """The post-injection site care bucket is the project's `pisc_duration_years` multiplied by its `effective_annual_monitoring_cost_usd`, rounded half up to 2 decimal places — fifty years of monitoring at the uplifted rate is by far the largest line item on most projects.

    The emergency reserve bucket is the larger of a two-million-dollar floor and the area-based figure obtained by multiplying 500,000.00 dollars per square kilometre by pi and by the square of the project's `aor_radius_km`, that area-based figure being rounded half up to 2 decimal places before the comparison.

    The administrative fee is tiered on the governing model's `effective_annual_injection_rate_tpy`: it is 250,000.00 dollars when that rate is at most 500,000 tonnes per year, 500,000.00 dollars when the rate exceeds 500,000 but is at most 1,500,000 tonnes per year, and 900,000.00 dollars when the rate exceeds 1,500,000 tonnes per year.

    The project's `required_financial_assurance_usd` is the sum of those five already-rounded buckets, itself rounded half up to 2 decimal places.

    And because the governing model has changed, the project's `required_financial_assurance_usd` and `assurance_coverage_status` are recomputed.

    Design: Corner/calculations/required_assurance_applies_tier_one_admin_fee_and_emergency_floor
    """
    fixtures.set_logical_clock(api, STARTUP_CLOCK_UTC)
    project = fixtures.open_project(api, **CHARLIE_PROJECT)
    model = fixtures.register_geologic_model(
        api, project["id"], project["version"], model_label="C1-DET"
    )
    simulated = fixtures.simulate_plume(api, model["id"], 20)
    assert simulated["max_injection_rate_tpy"] == 1200000
    assert simulated["effective_injection_rate_tpy"] == 400000
    fixtures.submit_model(api, model["id"])

    response = api.review_geologic_model(
        model["id"],
        {"decision": "ACCEPT", "review_note": "seal integrity acceptable"},
        regulatory_reviewer_headers,
    )
    validate_success(response, 200)

    accepted_project = fixtures.refresh_project(api, project["id"])
    assert accepted_project["required_financial_assurance_usd"] == pytest.approx(
        7250000.00, abs=0.01
    )
    assert accepted_project["effective_annual_monitoring_cost_usd"] == 100000.00
    assert accepted_project["pisc_duration_years"] == 50
    assert accepted_project["aor_radius_km"] == 0


def test_wellbore_risk_score_rounds_half_up_on_area_of_review_delineation(
    api, project_developer_headers
):
    """Unless a specific rule says otherwise, every monetary amount is carried to 2 decimal places and every rounding operation in this system rounds half up.

    The proximity factor is 0.20 flat whenever the project's `aor_radius_km` is zero or below, because an undelineated area of review carries no meaningful proximity signal; otherwise it is one minus the ratio of `distance_from_injector_km` to the project's `aor_radius_km`, clamped so that it is never above 1.00 and never below 0.20.

    The `risk_score` is 100.0 multiplied by the seal factor, multiplied by the plug factor, multiplied by the record factor, multiplied by the quantity 0.40 plus 0.60 times the proximity factor, rounded half up to 2 decimal places — so 40 percent of the score is fixed by the wellbore's own condition and 60 percent is modulated by how close it sits to the injector.

    The `ca_cost_estimate_usd` is a base mobilisation cost of 150,000.00 dollars, plus 120.00 dollars for every metre of `total_depth_m`, plus 2,000.00 dollars for every point of `risk_score`, with the total rounded half up to 2 decimal places.

    The second link re-screens legacy wellbores: because the project's area of review has changed, every legacy wellbore of the project whose `corrective_action_status` is `OUT_OF_AOR` and whose `distance_from_injector_km` is less than or equal to the project's new `aor_radius_km` moves `OUT_OF_AOR → IDENTIFIED`, and every wellbore now inside the area of review has its `risk_score` and `ca_cost_estimate_usd` recomputed against the new radius.

    Immediately afterwards, each wellbore that has just reached `IDENTIFIED` and either has `penetrates_seal` true or carries a `risk_score` of at least 40.00 auto-advances `IDENTIFIED → CA_REQUIRED` in the same request — a wellbore that penetrates the confining zone is always obligated regardless of its score, and a wellbore that does not penetrate the seal is obligated only once its score reaches the 40.00 threshold.

    When the obligated set is empty, `corrective_action_completion_pct` is exactly 100.00.

    The corrective-action bucket totals the `ca_cost_estimate_usd` of the project's wellbores whose `corrective_action_status` is `IDENTIFIED`, `CA_REQUIRED` or `CA_SCHEDULED` — work that is still outstanding — with the sum of those already-rounded per-wellbore figures rounded half up to 2 decimal places.

    Design: Corner/calculations/wellbore_risk_score_round_half_up_at_third_decimal
    """
    ctx = fixtures.setup_project_with_accepted_model(api)
    project_id = ctx["project"]["id"]
    wellbore = fixtures.register_wellbore(
        api, project_id, "15-001-00007", **WELLBORE_UNKNOWN_PLUG_MID
    )
    assert wellbore["risk_score"] == 22.54
    assert wellbore["ca_cost_estimate_usd"] == 315080.00

    response = api.finalize_aor(ctx["model"]["id"], {}, project_developer_headers)
    validate_success(response, 200)

    delineated_project = fixtures.refresh_project(api, project_id)
    assert delineated_project["aor_radius_km"] == 3.0

    rescreened = fixtures.refresh_wellbore(api, wellbore["id"])
    assert rescreened["risk_score"] == 30.35
    assert rescreened["ca_cost_estimate_usd"] == 330700.00
    assert rescreened["corrective_action_status"] == "IDENTIFIED"

    assert delineated_project["corrective_action_completion_pct"] == 100.00
    assert delineated_project["required_financial_assurance_usd"] == pytest.approx(
        24967866.94, abs=0.01
    )


def test_pore_space_project_totals_count_only_executed_tracts(api):
    """A new tract rests at `lease_status` `UNLEASED` with `negotiation_round_count`, `bonus_settlement_usd` and `net_acreage` all at 0.

    Acceptance locks the terms: `executed_bonus_per_acre_usd` takes the value of `current_offer_bonus_per_acre_usd`, `executed_royalty_rate_pct` takes the value of `current_offer_royalty_rate_pct`, and the supplied term dates are stored.

    Per tract, `net_acreage` is `acreage` multiplied by `ownership_pct` divided by 100.0, rounded half up to 4 decimal places, and `bonus_settlement_usd` is that `net_acreage` multiplied by `executed_bonus_per_acre_usd`, rounded half up to 2 decimal places.

    At project level the holders are the tracts whose `lease_status` is `EXECUTED` or `UNITIZED`, summed in `created_at` ascending order: `secured_acreage` is the sum of their `net_acreage` values rounded half up to 4 decimal places, `outstanding_acreage` is `total_project_acreage` less `secured_acreage` rounded half up to 4 decimal places, `pore_space_consent_pct` is 100.0 multiplied by `secured_acreage` divided by `total_project_acreage` rounded half up to 2 decimal places, and `pore_space_bonus_total_usd` is the sum of the holders' already-rounded `bonus_settlement_usd` values rounded half up to 2 decimal places.

    Design: Corner/calculations/pore_space_aggregates_only_executed_tracts
    """
    fixtures.set_logical_clock(api, STARTUP_CLOCK_UTC)
    project = fixtures.open_project(api)
    first_tract = fixtures.register_tract(
        api,
        project["id"],
        "T1",
        acreage=1000,
        ownership_pct=100,
        landowner_user_id="landowner-1",
    )
    second_tract = fixtures.register_tract(
        api,
        project["id"],
        "T2",
        acreage=500,
        ownership_pct=100,
        landowner_user_id="landowner-2",
    )
    offered = fixtures.send_offer(
        api, first_tract, bonus_per_acre_usd=15.00, royalty_rate_pct=12.5
    )

    response = api.respond_to_lease_offer(
        offered["id"],
        accept_offer_payload(),
        make_landowner_headers("landowner-1"),
    )
    executed = validate_success(response, 200)

    assert executed["lease_status"] == "EXECUTED"
    assert executed["net_acreage"] == 1000.0000
    assert executed["bonus_settlement_usd"] == 15000.00

    untouched = fixtures.refresh_tract(api, second_tract["id"])
    assert untouched["lease_status"] == "UNLEASED"
    assert untouched["net_acreage"] == 0

    settled_project = fixtures.refresh_project(api, project["id"])
    assert settled_project["secured_acreage"] == 1000.0000
    assert settled_project["outstanding_acreage"] == 3000.0000
    assert settled_project["pore_space_consent_pct"] == 25.00
    assert settled_project["pore_space_bonus_total_usd"] == 15000.00


def test_assurance_waterfall_partially_fills_emergency_bucket(
    api, project_developer_headers
):
    """Four requirement figures are taken from the current computation: the corrective-action requirement is the corrective-action bucket, the plugging requirement is the plugging bucket, the post-injection requirement is the post-injection site care bucket, and the emergency requirement is the emergency reserve bucket plus the administrative fee combined into one figure.

    Starting with the whole `face_amount_usd` as the remaining balance, the buckets are filled in the order corrective action, plugging, post-injection site care, emergency: each bucket receives the smaller of the remaining balance and its own requirement, rounded half up to 2 decimal places, and the remaining balance is then reduced by the amount just assigned, again rounded half up to 2 decimal places.

    Those four amounts land in `allocated_ca_usd`, `allocated_plugging_usd`, `allocated_pisc_usd` and `allocated_emergency_usd` respectively, and whatever remains becomes `unallocated_usd`, rounded half up to 2 decimal places.

    The waterfall never assigns more than the face amount in aggregate, so an instrument too small to cover the whole requirement fills the earlier buckets completely and leaves the later ones short.

    Allocation sets the instrument's `status` to `ALLOCATED`, recomputes the project's `allocated_assurance_usd` as the sum, over the project's instruments whose `status` is `ALLOCATED`, of their four allocated buckets (rounded half up to 2 decimal places), resets `assurance_coverage_status`, and bumps both the instrument's `version` and the project's `version`.

    `assurance_coverage_status` is then derived by comparing `allocated_assurance_usd` against `required_financial_assurance_usd`, and the tests are applied in this order: the status is `UNFUNDED` when `allocated_assurance_usd` is zero or below; otherwise it is `FUNDED` when `allocated_assurance_usd` is at least `required_financial_assurance_usd`; otherwise it is `UNDERFUNDED`.

    Design: Corner/calculations/assurance_waterfall_partially_fills_final_emergency_bucket
    """
    ctx = fixtures.setup_project_with_accepted_model(api)
    project_id = ctx["project"]["id"]
    instrument = fixtures.post_instrument(
        api, project_id, instrument_type="SURETY_BOND", face_amount_usd=11000000
    )

    response = api.allocate_financial_instrument(
        instrument["id"],
        allocate_payload(instrument["version"]),
        project_developer_headers,
    )
    allocated = validate_success(response, 200)

    assert allocated["allocated_ca_usd"] == 0.00
    assert allocated["allocated_plugging_usd"] == 0.00
    assert allocated["allocated_pisc_usd"] == 10000000.00
    assert allocated["allocated_emergency_usd"] == 1000000.00
    assert allocated["unallocated_usd"] == 0.00

    stored = fixtures.refresh_instrument(api, instrument["id"])
    assert stored["status"] == "ALLOCATED"
    assert stored["drawn_usd"] == 0.00

    funded_project = fixtures.refresh_project(api, project_id)
    assert funded_project["allocated_assurance_usd"] == 11000000.00
    assert funded_project["required_financial_assurance_usd"] == pytest.approx(
        12500000.00, abs=0.01
    )
    assert funded_project["assurance_coverage_status"] == "UNDERFUNDED"


def test_allocated_assurance_reconciles_with_allocated_instrument_buckets(
    api, project_developer_headers
):
    """Allocation sets the instrument's `status` to `ALLOCATED`, recomputes the project's `allocated_assurance_usd` as the sum, over the project's instruments whose `status` is `ALLOCATED`, of their four allocated buckets (rounded half up to 2 decimal places), resets `assurance_coverage_status`, and bumps both the instrument's `version` and the project's `version`.

    A posted instrument rests at `status` `POSTED` with all four allocated buckets — `allocated_ca_usd`, `allocated_plugging_usd`, `allocated_pisc_usd` and `allocated_emergency_usd` — at 0, `unallocated_usd` equal to the full `face_amount_usd`, `drawn_usd` at 0 and `released_at` null.

    Starting with the whole `face_amount_usd` as the remaining balance, the buckets are filled in the order corrective action, plugging, post-injection site care, emergency: each bucket receives the smaller of the remaining balance and its own requirement, rounded half up to 2 decimal places, and the remaining balance is then reduced by the amount just assigned, again rounded half up to 2 decimal places.

    `assurance_coverage_status` is then derived by comparing `allocated_assurance_usd` against `required_financial_assurance_usd`, and the tests are applied in this order: the status is `UNFUNDED` when `allocated_assurance_usd` is zero or below; otherwise it is `FUNDED` when `allocated_assurance_usd` is at least `required_financial_assurance_usd`; otherwise it is `UNDERFUNDED`.

    Design: Corner/calculations/allocated_assurance_reconciles_with_allocated_instrument_buckets
    """
    ctx = fixtures.setup_project_with_accepted_model(api)
    project_id = ctx["project"]["id"]
    instrument_a = fixtures.post_and_allocate_instrument(
        api, project_id, instrument_type="SURETY_BOND", face_amount_usd=11000000
    )
    instrument_b = fixtures.post_instrument(
        api, project_id, instrument_type="LETTER_OF_CREDIT", face_amount_usd=5000000
    )

    before = fixtures.refresh_project(api, project_id)
    assert before["allocated_assurance_usd"] == 11000000.00
    assert before["assurance_coverage_status"] == "UNDERFUNDED"

    response = api.allocate_financial_instrument(
        instrument_b["id"],
        allocate_payload(instrument_b["version"]),
        project_developer_headers,
    )
    allocated_b = validate_success(response, 200)

    assert allocated_b["allocated_pisc_usd"] == 5000000.00
    assert allocated_b["allocated_emergency_usd"] == 0.00
    assert allocated_b["unallocated_usd"] == 0.00

    stored_b = fixtures.refresh_instrument(api, instrument_b["id"])
    assert stored_b["status"] == "ALLOCATED"

    stored_a = fixtures.refresh_instrument(api, instrument_a["id"])
    assert stored_a["allocated_pisc_usd"] == 10000000.00
    assert stored_a["allocated_emergency_usd"] == 1000000.00

    after = fixtures.refresh_project(api, project_id)
    assert after["allocated_assurance_usd"] == 16000000.00
    assert after["assurance_coverage_status"] == "FUNDED"
