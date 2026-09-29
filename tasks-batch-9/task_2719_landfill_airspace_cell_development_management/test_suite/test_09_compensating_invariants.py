"""Reversals that must land on the exact pre-event figures, asymmetries included."""
from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers import fixtures
from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_amount, assert_cell_fill, assert_density
from test_helpers.test_users import TEST_USERS

AGENCY = TEST_USERS["regulatory_agency_headers"]
ENV_MANAGER = TEST_USERS["environmental_manager_headers"]
FINANCE = TEST_USERS["finance_filer_headers"]
SURVEYOR = TEST_USERS["surveyor_headers"]

FEE_SCHEDULE = {
    "posted_tipping_fee_per_ton": 42.5,
    "host_fee_per_ton": 3.75,
    "tier1_monthly_tons": 100,
    "royalty_tier1_pct": 0.04,
    "royalty_tier2_pct": 0.07,
    "minimum_annual_payment": 250000,
    "effective_from": "2026-01-01T00:00:00Z",
    "expires_on": "2036-01-01T00:00:00Z",
}
DAY_SHAPE = {
    "operating_date": "2026-08-05T00:00:00Z",
    "working_face_area_sf": 5000,
    "cover_material_type": "ALTERNATIVE_TARP",
}
# C-1 is left at QA_CERTIFIED so it contributes airspace but never a working face.
RESERVE_CELL = {"cell_code": "C-1", "design_airspace_cy": 1000000, "design_area_sf": 120001}
# 196.00 consumed cubic yards is exactly 98 percent of C-2.
WORKING_CELL = {
    "cell_code": "C-2",
    "design_airspace_cy": 200,
    "design_area_sf": 45001,
    "construction_end_date": "2026-07-20T00:00:00Z",
}
AMEND_REASON = "Scale ticket reconciliation with the hauler."


def _closed_day_that_filled_the_only_active_cell():
    """A closed day whose 166.60 tons took the site's only working face to FULL."""
    landfill = fixtures.create_landfill()
    reserve = fixtures.setup_qa_certified_cell(
        landfill["id"], cell_overrides=RESERVE_CELL
    )["cell"]
    working = fixtures.setup_qa_certified_cell(
        landfill["id"], cell_overrides=WORKING_CELL
    )["cell"]
    fixtures.setup_funded_assurance(landfill["id"])
    fixtures.authorize_waste_placement(working["id"], "AGY-2026-C2")
    fixtures.activate_cell(landfill["id"], working["id"])
    fixtures.setup_executed_host_agreement(landfill["id"], **FEE_SCHEDULE)
    approval = fixtures.setup_approved_special_waste(
        landfill["id"],
        waste_code="IS-4410",
        approved_tons_cap=500,
        effective_from="2026-01-01T00:00:00Z",
    )
    day = fixtures.open_operating_day(landfill["id"], working["id"], **DAY_SHAPE)
    load = fixtures.place_certified_load(
        landfill["id"], day["id"], 166.60, manifest_tons=166.60, hauler_ref="H-1"
    )
    assert_amount(load["gate_charge_amount"], 7705.25, "gate charge at the scale")

    closed = fixtures.close_operating_day(landfill["id"], day["id"])

    assert closed["status"] == "CLOSED"
    assert_amount(closed["tons_placed"], 166.60, "tons placed")
    assert_density(closed["effective_density_tons_per_cy"], 0.8500, "effective density")
    assert_amount(closed["airspace_consumed_cy"], 196.00, "airspace consumed")
    filled = get_success_data(api_client.get_cell(working["id"], AGENCY))
    assert filled["status"] == "FULL"
    assert_amount(filled["fill_pct"], 98.00, "fill percentage")
    site = fixtures.read_landfill(landfill["id"])
    assert site["active_cell_count"] == 0
    assert site["operating_status"] == "SUSPENDED_NO_AIRSPACE"
    assert_amount(site["certified_airspace_cy"], 1000200.00, "certified airspace")
    suspended = get_success_data(
        api_client.get_special_waste_approval(approval["id"], ENV_MANAGER)
    )
    assert suspended["status"] == "SUSPENDED"
    billed = get_success_data(api_client.get_waste_load(load["id"], FINANCE))
    assert billed["billing_status"] == "FINALIZED"
    assert_amount(billed["host_royalty_amount"], 368.14, "host royalty")
    assert_amount(billed["final_charge_amount"], 8073.39, "final charge")
    return {
        "landfill": landfill,
        "reserve": reserve,
        "cell": working,
        "day": closed,
        "load": load,
        "approval": approval,
    }


def test_the_amend_zeroes_the_days_own_three_figures():
    """The day keeps its loads but stops accounting for any of them.

    PRD: "The day's `airspace_consumed_cy`, `effective_density_tons_per_cy` and
    `tons_placed` are all reset to 0, the `amend_reason` is recorded, the `status` becomes
    `AMENDED` and the `version` is incremented by 1."

    Design: Difficulty/compensating_invariant/day_amend_reverses_airspace_billing_and_posture_with_no_drift
    """
    world = _closed_day_that_filled_the_only_active_cell()

    amended = fixtures.amend_operating_day(
        world["landfill"]["id"], world["day"]["id"], AMEND_REASON
    )

    assert amended["status"] == "AMENDED"
    assert amended["amend_reason"] == AMEND_REASON
    assert_amount(amended["tons_placed"], 0, "tons placed after the amend")
    assert_amount(amended["airspace_consumed_cy"], 0, "airspace consumed after the amend")
    assert_density(amended["effective_density_tons_per_cy"], 0, "density after the amend")
    assert amended["version"] > world["day"]["version"]


def test_the_amend_returns_the_cell_fill_to_its_exact_pre_close_value():
    """The cell ledger lands back on 0.00, not merely somewhere under the threshold.

    PRD: "The working-face cell's `consumed_airspace_cy` and `fill_pct` are recomputed with
    the amended day no longer contributing, so the cell's fill returns to its exact
    pre-close value."

    Design: Difficulty/compensating_invariant/day_amend_reverses_airspace_billing_and_posture_with_no_drift
    """
    world = _closed_day_that_filled_the_only_active_cell()

    fixtures.amend_operating_day(world["landfill"]["id"], world["day"]["id"], AMEND_REASON)

    cell = get_success_data(api_client.get_cell(world["cell"]["id"], AGENCY))
    assert_amount(cell["consumed_airspace_cy"], 0.00, "cell consumed airspace")
    assert_amount(cell["fill_pct"], 0.00, "cell fill percentage")
    assert_cell_fill(cell)


def test_the_amend_lifts_the_suspension_and_unwinds_the_approval_cascade():
    """One reversal walks three links back up: cell, site posture, and every profile.

    PRD: "If the cell was sitting in `FULL` and the recomputed consumption has dropped back
    below 98 percent of its `design_airspace_cy`, the cell moves `FULL → ACTIVE`, which
    recomputes the site's `active_cell_count` upward, lifts a `SUSPENDED_NO_AIRSPACE` posture
    back to `OPEN`, and restores every `SUSPENDED` special-waste approval of the site to
    `APPROVED`."

    Design: Difficulty/compensating_invariant/day_amend_reverses_airspace_billing_and_posture_with_no_drift
    """
    world = _closed_day_that_filled_the_only_active_cell()

    fixtures.amend_operating_day(world["landfill"]["id"], world["day"]["id"], AMEND_REASON)

    assert get_success_data(api_client.get_cell(world["cell"]["id"], AGENCY))["status"] == (
        "ACTIVE"
    )
    site = fixtures.read_landfill(world["landfill"]["id"])
    assert site["active_cell_count"] == 1
    assert site["operating_status"] == "OPEN"
    restored = get_success_data(
        api_client.get_special_waste_approval(world["approval"]["id"], ENV_MANAGER)
    )
    assert restored["status"] == "APPROVED", (
        "the link-4 suspension is undone even though no load referenced the profile"
    )


def test_the_amend_recomputes_the_site_airspace_ledger():
    """The site reads its full certified basis again, and three years of life with it.

    PRD: "The site's `consumed_airspace_cy`, `remaining_airspace_cy` and
    `remaining_life_years` are recomputed, and every affected special-waste approval's
    `consumed_tons` is recomputed back onto the manifest basis; any approval sitting in
    `EXHAUSTED` whose recomputed `consumed_tons` has fallen back below its
    `approved_tons_cap` is restored to `APPROVED` with its `version` incremented by 1."

    Design: Difficulty/compensating_invariant/day_amend_reverses_airspace_billing_and_posture_with_no_drift
    """
    world = _closed_day_that_filled_the_only_active_cell()

    fixtures.amend_operating_day(world["landfill"]["id"], world["day"]["id"], AMEND_REASON)

    site = fixtures.read_landfill(world["landfill"]["id"])
    assert_amount(site["consumed_airspace_cy"], 0.00, "site consumed airspace")
    assert_amount(site["remaining_airspace_cy"], 1000200.00, "site remaining airspace")
    assert_amount(site["remaining_life_years"], 3.00, "site remaining life")


def test_the_gate_price_survives_the_amend_while_the_final_price_is_cleared():
    """The reversal is deliberately asymmetric across the load's three money fields.

    PRD: "Every load of the day whose `billing_status` is `FINALIZED` moves back to
    `PROVISIONAL`, with `final_charge_amount` and `host_royalty_amount` reset to null.
    `gate_charge_amount` is deliberately left untouched — the provisional gate price stands,
    because the truck really did cross the scale at the manifest weight."

    Design: Difficulty/compensating_invariant/day_amend_reverses_airspace_billing_and_posture_with_no_drift
    """
    world = _closed_day_that_filled_the_only_active_cell()

    fixtures.amend_operating_day(world["landfill"]["id"], world["day"]["id"], AMEND_REASON)

    load = get_success_data(api_client.get_waste_load(world["load"]["id"], FINANCE))
    assert load["billing_status"] == "PROVISIONAL"
    assert load["host_royalty_amount"] is None
    assert load["final_charge_amount"] is None
    assert_amount(load["gate_charge_amount"], 7705.25, "retained gate charge")
    assert_amount(load["certified_net_tons"], 166.60, "retained certified weight")
    assert load["screening_status"] == "CLEARED", (
        "the amend touches the billing dimension only, never the screening dimension"
    )


def test_re_closing_reproduces_every_figure_with_no_drift():
    """Close, amend, close: the second close lands on the first close's numbers exactly.

    PRD: "Re-closing an amended day re-applies every step and every cascade link of the
    original close against whatever load set now exists, under the same five preconditions."

    Design: Difficulty/compensating_invariant/day_amend_reverses_airspace_billing_and_posture_with_no_drift
    """
    world = _closed_day_that_filled_the_only_active_cell()
    fixtures.amend_operating_day(world["landfill"]["id"], world["day"]["id"], AMEND_REASON)

    reclosed = fixtures.close_operating_day(world["landfill"]["id"], world["day"]["id"])

    assert reclosed["status"] == "CLOSED"
    assert_amount(reclosed["tons_placed"], 166.60, "tons placed on the re-close")
    assert_amount(reclosed["airspace_consumed_cy"], 196.00, "airspace on the re-close")
    cell = get_success_data(api_client.get_cell(world["cell"]["id"], AGENCY))
    assert_amount(cell["consumed_airspace_cy"], 196.00, "cell consumed airspace")
    assert_amount(cell["fill_pct"], 98.00, "cell fill percentage")
    assert cell["status"] == "FULL"
    site = fixtures.read_landfill(world["landfill"]["id"])
    assert_amount(site["consumed_airspace_cy"], 196.00, "site consumed airspace")
    assert site["operating_status"] == "SUSPENDED_NO_AIRSPACE"
    load = get_success_data(api_client.get_waste_load(world["load"]["id"], FINANCE))
    assert load["billing_status"] == "FINALIZED"
    assert_amount(load["gate_charge_amount"], 7705.25, "gate charge across three writes")
    assert_amount(load["host_royalty_amount"], 368.14, "re-derived host royalty")
    assert_amount(load["final_charge_amount"], 8073.39, "re-derived final charge")


def test_the_reversal_moves_field_values_but_never_version_counters():
    """Three rows are compensated and all three version counters still only climb.

    PRD: "Both the cell and the landfill have their `version` incremented by 1 on an amend,
    alongside the day's own increment."

    Design: Difficulty/compensating_invariant/day_amend_reverses_airspace_billing_and_posture_with_no_drift
    """
    world = _closed_day_that_filled_the_only_active_cell()
    before_cell = get_success_data(api_client.get_cell(world["cell"]["id"], AGENCY))["version"]
    before_site = fixtures.read_landfill(world["landfill"]["id"])["version"]

    amended = fixtures.amend_operating_day(
        world["landfill"]["id"], world["day"]["id"], AMEND_REASON
    )
    after_cell = get_success_data(api_client.get_cell(world["cell"]["id"], AGENCY))["version"]
    after_site = fixtures.read_landfill(world["landfill"]["id"])["version"]
    reclosed = fixtures.close_operating_day(world["landfill"]["id"], world["day"]["id"])

    assert after_cell > before_cell
    assert after_site > before_site
    assert reclosed["version"] > amended["version"] > world["day"]["version"]
    assert (
        get_success_data(api_client.get_cell(world["cell"]["id"], AGENCY))["version"]
        > after_cell
    )
    assert fixtures.read_landfill(world["landfill"]["id"])["version"] > after_site


CAPPED_PROFILE = {
    "generator_name": "Ridgeview Plating Co",
    "waste_code": "IS-4410",
    "profile_stream": "INDUSTRIAL_SPECIAL",
    "approved_tons_cap": 137.0,
    "effective_from": "2026-01-01T00:00:00Z",
    "expires_on": "2026-12-31T00:00:00Z",
}


def _place_special(site, approval_id, hauler_ref, manifest_tons):
    """Weigh in one profiled truck and clear it, which charges the manifest basis."""
    load = fixtures.receive_load(
        site["landfill"]["id"],
        site["day"]["id"],
        hauler_ref=hauler_ref,
        waste_stream="INDUSTRIAL_SPECIAL",
        manifest_tons=manifest_tons,
        special_waste_approval_id=approval_id,
    )
    return fixtures.clear_screening(site["landfill"]["id"], load["id"])


def _read_approval(approval_id):
    return get_success_data(api_client.get_special_waste_approval(approval_id, ENV_MANAGER))


def _day_with_two_cleared_special_loads():
    """Two profiled trucks cleared at 40.00 and 90.00 manifest tons against a 137.00 cap."""
    site = fixtures.setup_open_day(
        agreement_overrides=dict(FEE_SCHEDULE), day_overrides=dict(DAY_SHAPE)
    )
    approval = fixtures.setup_approved_special_waste(site["landfill"]["id"], **CAPPED_PROFILE)
    assert_amount(approval["consumed_tons"], 0, "consumed tons on a fresh approval")
    first = _place_special(site, approval["id"], "H-1", 40.0)
    second = _place_special(site, approval["id"], "H-2", 90.0)
    assert_amount(first["gate_charge_amount"], 1850.00, "first gate charge")
    assert_amount(second["gate_charge_amount"], 4162.50, "second gate charge")
    site["approval"] = approval
    site["first"] = first
    site["second"] = second
    return site


def _certify_both(site):
    fixtures.certify_weight(site["landfill"]["id"], site["first"]["id"], 45.25)
    fixtures.certify_weight(site["landfill"]["id"], site["second"]["id"], 92.0)


def test_clearing_charges_the_profile_ledger_on_the_manifest_basis():
    """40.00 plus 90.00 is 130.00, and the cap check legitimately passed on that basis.

    PRD: "`consumed_tons` is at all times the sum, over the cleared loads referencing the
    approval, of `certified_net_tons` for those loads whose `billing_status` is `FINALIZED`
    and of `manifest_tons` for every other cleared load — which is exactly why it reads on
    the manifest basis between clearance and day close, on the certified basis after the
    close, and back on the manifest basis after an amendment."

    Design: Difficulty/compensating_invariant/amend_rebases_special_waste_tonnage_and_reverses_exhaustion
    """
    site = _day_with_two_cleared_special_loads()

    approval = _read_approval(site["approval"]["id"])

    assert_amount(approval["consumed_tons"], 130.00, "consumed tons on the manifest basis")
    assert approval["status"] == "APPROVED"


def test_recording_certified_weights_moves_the_profile_ledger_not_at_all():
    """The scale ticket is stored while both loads are still PROVISIONAL.

    PRD: "That call stores the weight and increments the load's `version` by 1 and does
    nothing else: in particular a special-waste approval's `consumed_tons` is deliberately
    **not** touched here, because the re-basing from manifest tonnage to certified tonnage
    happens at day close."

    Design: Difficulty/compensating_invariant/amend_rebases_special_waste_tonnage_and_reverses_exhaustion
    """
    site = _day_with_two_cleared_special_loads()

    _certify_both(site)

    approval = _read_approval(site["approval"]["id"])
    assert_amount(approval["consumed_tons"], 130.00, "consumed tons after certification")
    assert approval["status"] == "APPROVED"


def test_the_close_re_bases_onto_certified_tons_and_crosses_the_cap():
    """137.25 certified tons breach a cap that the 130.00 manifest basis never touched.

    PRD: "The **tonnage sync** recomputes `consumed_tons` for every special-waste approval
    referenced by this day's cleared loads, re-basing each one from manifest tonnage onto
    certified tonnage; any such approval sitting in `APPROVED` whose recomputed
    `consumed_tons` has reached its `approved_tons_cap` is moved to `EXHAUSTED` with its
    `version` incremented by 1."

    Design: Difficulty/compensating_invariant/amend_rebases_special_waste_tonnage_and_reverses_exhaustion
    """
    site = _day_with_two_cleared_special_loads()
    _certify_both(site)

    closed = fixtures.close_operating_day(site["landfill"]["id"], site["day"]["id"])

    assert_amount(closed["tons_placed"], 137.25, "tons placed")
    assert_amount(closed["airspace_consumed_cy"], 161.47, "airspace consumed")
    approval = _read_approval(site["approval"]["id"])
    assert_amount(approval["consumed_tons"], 137.25, "consumed tons on the certified basis")
    assert approval["status"] == "EXHAUSTED"


def test_the_amend_re_bases_the_profile_ledger_back_and_un_exhausts_it():
    """The ledger returns to 130.00 and the exhaustion is undone with it.

    PRD: "The site's `consumed_airspace_cy`, `remaining_airspace_cy` and
    `remaining_life_years` are recomputed, and every affected special-waste approval's
    `consumed_tons` is recomputed back onto the manifest basis; any approval sitting in
    `EXHAUSTED` whose recomputed `consumed_tons` has fallen back below its
    `approved_tons_cap` is restored to `APPROVED` with its `version` incremented by 1."

    Design: Difficulty/compensating_invariant/amend_rebases_special_waste_tonnage_and_reverses_exhaustion
    """
    site = _day_with_two_cleared_special_loads()
    _certify_both(site)
    fixtures.close_operating_day(site["landfill"]["id"], site["day"]["id"])

    fixtures.amend_operating_day(
        site["landfill"]["id"], site["day"]["id"], "Generator disputed the certified weights."
    )

    approval = _read_approval(site["approval"]["id"])
    assert_amount(approval["consumed_tons"], 130.00, "consumed tons back on the manifest basis")
    assert approval["status"] == "APPROVED"


def _second_day_over_the_re_based_ledger(site):
    """Close, amend, then open a fresh day so the cap probes can actually be cleared.

    A load may only be cleared while its operating day is `OPEN`, and the amended day is
    not; the working face is still `ACTIVE` and the site is still `OPEN`, so a second
    calendar day is the PRD-reachable way to probe the re-based 130.00 ledger.
    """
    _certify_both(site)
    fixtures.close_operating_day(site["landfill"]["id"], site["day"]["id"])
    fixtures.amend_operating_day(
        site["landfill"]["id"], site["day"]["id"], "Generator disputed the certified weights."
    )
    site["day"] = fixtures.open_operating_day(
        site["landfill"]["id"],
        site["cell"]["id"],
        operating_date="2026-08-06T00:00:00Z",
        working_face_area_sf=5000,
        cover_material_type="ALTERNATIVE_TARP",
    )
    return site


def test_a_profiled_load_landing_exactly_on_the_cap_is_cleared():
    """130.00 plus 7.00 is exactly 137.00, which is allowed and stays APPROVED.

    PRD: "The two remaining states, `SUSPENDED` and `EXHAUSTED`, are never reached by a
    client call at all: they are written only by the day-close cascade and unwound only by
    cell activation or day amendment, as described in §3.6."

    Design: Difficulty/compensating_invariant/amend_rebases_special_waste_tonnage_and_reverses_exhaustion
    """
    site = _second_day_over_the_re_based_ledger(_day_with_two_cleared_special_loads())

    probe = _place_special(site, site["approval"]["id"], "H-3", 7.0)

    assert probe["screening_status"] == "CLEARED"
    approval = _read_approval(site["approval"]["id"])
    assert_amount(approval["consumed_tons"], 137.00, "consumed tons at the cap")
    assert approval["status"] == "APPROVED", (
        "only the day-close cascade may write EXHAUSTED, never a clearance"
    )


def test_one_ton_past_the_cap_is_refused_and_charges_nothing():
    """The rejected truck leaves the ledger, its own screening and its price untouched.

    PRD: "And finally, if the load references an approval, that approval's `consumed_tons`
    plus this load's `manifest_tons` may not exceed its `approved_tons_cap`; exact equality
    with the cap is allowed, and anything beyond it is refused with
    `ERR_APPROVAL_TONNAGE_CAP_EXCEEDED`."

    Design: Difficulty/compensating_invariant/amend_rebases_special_waste_tonnage_and_reverses_exhaustion
    """
    site = _second_day_over_the_re_based_ledger(_day_with_two_cleared_special_loads())
    _place_special(site, site["approval"]["id"], "H-3", 7.0)
    overflow = fixtures.receive_load(
        site["landfill"]["id"],
        site["day"]["id"],
        hauler_ref="H-4",
        waste_stream="INDUSTRIAL_SPECIAL",
        manifest_tons=1.0,
        special_waste_approval_id=site["approval"]["id"],
    )

    response = api_client.clear_screening(overflow["id"], None, site["scale_headers"])

    validate_error(response, ApiErrorId.ERR_APPROVAL_TONNAGE_CAP_EXCEEDED.value, 422)
    unchanged = get_success_data(api_client.get_waste_load(overflow["id"], FINANCE))
    assert unchanged["screening_status"] == "PENDING"
    assert unchanged["gate_charge_amount"] is None
    assert_amount(
        _read_approval(site["approval"]["id"])["consumed_tons"],
        137.00,
        "consumed tons after the refusal",
    )
    assert_amount(
        get_success_data(api_client.get_waste_load(site["first"]["id"], FINANCE))[
            "gate_charge_amount"
        ],
        1850.00,
        "the first gate charge across close, amend and two later trucks",
    )


EARLIER_FLIGHT = {
    "flown_on": "2026-08-01T00:00:00Z",
    "coverage_period_start": "2026-05-01T00:00:00Z",
    "coverage_period_end": "2026-07-31T00:00:00Z",
    "measured_remaining_airspace_cy": 700000,
    "tons_placed_in_period": 250000,
}
LATER_FLIGHT = {
    "flown_on": "2026-10-30T00:00:00Z",
    "coverage_period_start": "2026-08-01T00:00:00Z",
    "coverage_period_end": "2026-10-29T00:00:00Z",
    "measured_remaining_airspace_cy": 640000,
    "tons_placed_in_period": 50000,
}
VOID_REASON = "Ground control point mis-identified in the flight log."


def _projection(landfill_id):
    return get_success_data(api_client.get_remaining_life_projection(landfill_id, SURVEYOR))


def _two_flights_one_superseding_the_other():
    """A ledger basis of 1,000,000 cy and two surveys, the later one RECORDED."""
    landfill = fixtures.create_landfill(
        planned_density_tons_per_cy=0.9, annual_tonnage_forecast=300000
    )
    fixtures.setup_qa_certified_cell(
        landfill["id"], cell_overrides={"design_airspace_cy": 1000000}
    )
    before = _projection(landfill["id"])
    assert before["variant"] == "ledger_based"
    assert_amount(before["remaining_life_years"], 3.00, "life before any survey")

    first = fixtures.record_aerial_survey(landfill["id"], **EARLIER_FLIGHT)
    second = fixtures.record_aerial_survey(landfill["id"], **LATER_FLIGHT)

    site = fixtures.read_landfill(landfill["id"])
    assert_amount(site["remaining_life_years"], 1.78, "life under the later survey")
    assert site["operating_status"] == "RESTRICTED_AIRSPACE"
    return landfill, first, second


def test_the_void_re_selects_the_superseded_survey_for_the_projection():
    """The restore chain walks back one link instead of dropping to the ledger.

    PRD: "The void then **restores the previous picture**: among the site's surveys in
    `SUPERSEDED`, the one ranked first by `flown_on` descending and, as a tie-break,
    `created_at` descending, is put back to `RECORDED` with its `version` incremented by 1."

    Design: Difficulty/compensating_invariant/survey_void_restores_prior_survey_or_falls_back_to_the_ledger
    """
    landfill, first, second = _two_flights_one_superseding_the_other()

    voided = fixtures.void_aerial_survey(second["id"], VOID_REASON)

    assert voided["status"] == "VOID"
    projection = _projection(landfill["id"])
    assert projection["variant"] == "survey_based"
    assert projection["source_survey_id"] == first["id"]
    assert_density(projection["density_tons_per_cy"], 0.8333, "restored survey density")
    assert_amount(projection["remaining_life_years"], 1.94, "restored remaining life")


def test_an_empty_superseded_set_flips_the_projection_back_to_the_ledger():
    """With both flights void the site has no recorded survey and reports design intent.

    PRD: "Under `ledger_based`, the remaining airspace is the site's `certified_airspace_cy`
    minus its `consumed_airspace_cy`, rounded to 2 decimal places; the density is the site's
    `planned_density_tons_per_cy`; and `source_survey_id` is null."

    Design: Difficulty/compensating_invariant/survey_void_restores_prior_survey_or_falls_back_to_the_ledger
    """
    landfill, first, second = _two_flights_one_superseding_the_other()
    fixtures.void_aerial_survey(second["id"], VOID_REASON)

    fixtures.void_aerial_survey(first["id"], "Same flight log; the whole campaign failed.")

    projection = _projection(landfill["id"])
    assert projection["variant"] == "ledger_based"
    assert projection["source_survey_id"] is None
    assert_density(projection["density_tons_per_cy"], 0.90, "ledger density")
    assert_amount(projection["remaining_airspace_cy"], 1000000.00, "ledger remaining airspace")
    assert_amount(projection["remaining_life_years"], 3.00, "ledger remaining life")


def test_the_void_compensates_the_projection_but_not_the_posture():
    """Three years of life are back and the site is still restricted until an admin says so.

    PRD: "The first lifts a restriction back to normal operation, taking a site from
    `RESTRICTED_AIRSPACE` to `OPEN`; it is also the way out of `SUSPENDED_NO_AIRSPACE` and
    `SUSPENDED_FINANCIAL`, so the request is accepted when the site currently sits in any of
    `OPEN`, `RESTRICTED_AIRSPACE`, `SUSPENDED_NO_AIRSPACE` or `SUSPENDED_FINANCIAL`."

    Design: Difficulty/compensating_invariant/survey_void_restores_prior_survey_or_falls_back_to_the_ledger
    """
    landfill, first, second = _two_flights_one_superseding_the_other()
    fixtures.void_aerial_survey(second["id"], VOID_REASON)
    fixtures.void_aerial_survey(first["id"], "Same flight log; the whole campaign failed.")

    site = fixtures.read_landfill(landfill["id"])
    assert_amount(site["remaining_life_years"], 3.00, "recomputed remaining life")
    assert site["operating_status"] == "RESTRICTED_AIRSPACE", (
        "the void compensates the projection only; the posture is not auto-lifted"
    )

    lifted = fixtures.set_operating_status(landfill["id"], "OPEN")

    assert lifted["operating_status"] == "OPEN"


def test_a_second_void_of_a_terminal_survey_restores_nothing():
    """The duplicate void is refused, and it must not resurrect either flight.

    PRD: "The survey must be in `RECORDED`; it moves to the terminal `VOID`, its reason is
    stored and its `version` is incremented by 1."

    Design: Difficulty/compensating_invariant/survey_void_restores_prior_survey_or_falls_back_to_the_ledger
    """
    landfill, first, second = _two_flights_one_superseding_the_other()
    fixtures.void_aerial_survey(second["id"], VOID_REASON)
    fixtures.void_aerial_survey(first["id"], "Same flight log; the whole campaign failed.")

    response = api_client.void_aerial_survey(
        second["id"], {"void_reason": "Duplicate void attempt."}, SURVEYOR
    )

    validate_error(response, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value, 409)
    for survey in (first, second):
        assert get_success_data(api_client.get_aerial_survey(survey["id"], SURVEYOR))[
            "status"
        ] == "VOID"
    assert_amount(
        fixtures.read_landfill(landfill["id"])["remaining_life_years"],
        3.00,
        "remaining life after the refused void",
    )
