"""Composed derivations: legacy wellbore risk scoring, the per-tract pore-space
settlement and its project total, and the pinned evaluation order behind the
required financial assurance.

Each concern here assembles one regulated number out of several inputs whose
combination order, clamping and rounding order are themselves part of the
contract.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import constants, factories, fixtures, make_landowner_headers

WELLBORE_SCREENING_SPECS = [
    constants.WELLBORE_SEAL_OPEN_HOLE_NEAR,
    constants.WELLBORE_PARTIALLY_PLUGGED_MID,
    constants.WELLBORE_CEMENTED_DOCUMENTED_FAR,
    constants.WELLBORE_BEYOND_AOR,
]


def _register_four_wellbores_against_a_delineated_area_of_review(api, headers):
    """Delineate the area of review, then register four legacy wellbores.

    The four differ in seal penetration, plug condition, plugging record and
    distance from the injector, so each one exercises a different combination of
    the four multiplicative factors against the same 3.0 km area of review.
    """
    ctx = fixtures.setup_project_with_finalized_aor(api)
    wellbores = []
    for index, spec in enumerate(WELLBORE_SCREENING_SPECS, start=1):
        wellbores.append(
            validate_success(
                api.create_legacy_wellbore(
                    factories.create_legacy_wellbore_payload(
                        ctx["project"]["id"], f"15-001-{index:05d}", **spec
                    ),
                    headers,
                ),
                201,
            )
        )
    return ctx, wellbores


def test_wellbore_risk_score_inside_area_of_review_obligates_by_seal_or_threshold(
    api, project_developer_headers
):
    """The proximity factor is 0.20 flat whenever the project's `aor_radius_km` is zero or below, because an undelineated area of review carries no meaningful proximity signal; otherwise it is one minus the ratio of `distance_from_injector_km` to the project's `aor_radius_km`, clamped so that it is never above 1.00 and never below 0.20.
    The `risk_score` is 100.0 multiplied by the seal factor, multiplied by the plug factor, multiplied by the record factor, multiplied by the quantity 0.40 plus 0.60 times the proximity factor, rounded half up to 2 decimal places — so 40 percent of the score is fixed by the wellbore's own condition and 60 percent is modulated by how close it sits to the injector.
    The `ca_cost_estimate_usd` is a base mobilisation cost of 150,000.00 dollars, plus 120.00 dollars for every metre of `total_depth_m`, plus 2,000.00 dollars for every point of `risk_score`, with the total rounded half up to 2 decimal places.
    Immediately afterwards, each wellbore that has just reached `IDENTIFIED` and either has `penetrates_seal` true or carries a `risk_score` of at least 40.00 auto-advances `IDENTIFIED → CA_REQUIRED` in the same request — a wellbore that penetrates the confining zone is always obligated regardless of its score, and a wellbore that does not penetrate the seal is obligated only once its score reaches the 40.00 threshold.

    Design: Difficulty/combinatorial_formula/wellbore_risk_score_nested_min_max_and_state_branches
    """
    _, wellbores = _register_four_wellbores_against_a_delineated_area_of_review(
        api, project_developer_headers
    )

    near_open_hole = fixtures.refresh_wellbore(api, wellbores[0]["id"])
    assert near_open_hole["risk_score"] == 90.00
    assert near_open_hole["ca_cost_estimate_usd"] == 570000.00
    assert near_open_hole["corrective_action_status"] == "CA_REQUIRED"

    partially_plugged = fixtures.refresh_wellbore(api, wellbores[1]["id"])
    assert partially_plugged["risk_score"] == 47.60
    assert partially_plugged["ca_cost_estimate_usd"] == 389200.00
    assert partially_plugged["corrective_action_status"] == "CA_REQUIRED"

    cemented_documented = fixtures.refresh_wellbore(api, wellbores[2]["id"])
    assert cemented_documented["risk_score"] == 7.65
    assert cemented_documented["ca_cost_estimate_usd"] == 261300.00
    assert cemented_documented["corrective_action_status"] == "IDENTIFIED"


def test_wellbore_beyond_area_of_review_is_scored_but_starts_out_of_aor(
    api, project_developer_headers
):
    """When the project's `aor_radius_km` is 0, or when the wellbore's `distance_from_injector_km` exceeds the project's `aor_radius_km`, the wellbore begins at `OUT_OF_AOR` and waits for a future delineation to pull it in.
    The `risk_score` is 100.0 multiplied by the seal factor, multiplied by the plug factor, multiplied by the record factor, multiplied by the quantity 0.40 plus 0.60 times the proximity factor, rounded half up to 2 decimal places — so 40 percent of the score is fixed by the wellbore's own condition and 60 percent is modulated by how close it sits to the injector.
    The `ca_cost_estimate_usd` is a base mobilisation cost of 150,000.00 dollars, plus 120.00 dollars for every metre of `total_depth_m`, plus 2,000.00 dollars for every point of `risk_score`, with the total rounded half up to 2 decimal places.
    Wellbores whose `corrective_action_status` is `OUT_OF_AOR` are excluded entirely, from both numerator and denominator — they are outside the regulator's concern.
    Otherwise it is 100.0 multiplied by the count of closed wellbores divided by the count of obligated wellbores, rounded half up to 2 decimal places.

    Design: Difficulty/combinatorial_formula/wellbore_risk_score_nested_min_max_and_state_branches
    """
    ctx, wellbores = _register_four_wellbores_against_a_delineated_area_of_review(
        api, project_developer_headers
    )

    beyond_area_of_review = fixtures.refresh_wellbore(api, wellbores[3]["id"])
    assert beyond_area_of_review["corrective_action_status"] == "OUT_OF_AOR"
    assert beyond_area_of_review["risk_score"] == 44.20
    assert beyond_area_of_review["ca_cost_estimate_usd"] == 358400.00

    project = fixtures.refresh_project(api, ctx["project"]["id"])
    assert project["corrective_action_completion_pct"] == 0.00


def _three_tracts_with_outstanding_offers(api):
    """Register the three canonical tracts and put the same offer on each."""
    fixtures.set_logical_clock(api, constants.STARTUP_CLOCK_UTC)
    project = fixtures.open_project(api)
    tracts = []
    for spec in constants.CANONICAL_TRACT_SPECS:
        spec = dict(spec)
        label = spec.pop("tract_label")
        tract = fixtures.register_tract(api, project["id"], label, **spec)
        tracts.append(
            fixtures.send_offer(
                api,
                tract,
                bonus_per_acre_usd=constants.DEFAULT_BONUS_PER_ACRE_USD,
                royalty_rate_pct=constants.DEFAULT_ROYALTY_RATE_PCT,
            )
        )
    return project, tracts


def _accept_every_outstanding_offer(api, tracts):
    """Let each landowner accept the offer standing on its own tract."""
    return [
        validate_success(
            api.respond_to_lease_offer(
                tract["id"],
                factories.accept_offer_payload(),
                make_landowner_headers(tract["landowner_user_id"]),
            )
        )
        for tract in tracts
    ]


def test_pore_space_bonus_total_sums_already_rounded_per_tract_settlements(api):
    """Per tract, `net_acreage` is `acreage` multiplied by `ownership_pct` divided by 100.0, rounded half up to 4 decimal places, and `bonus_settlement_usd` is that `net_acreage` multiplied by `executed_bonus_per_acre_usd`, rounded half up to 2 decimal places.
    The project's pore-space bonus total is the sum of the already-rounded per-tract settlements, not the rounding of an unrounded aggregate — the two orders differ in cents, and the former is correct.
    That last figure must be assembled from the rounded per-tract settlements and not from an unrounded aggregate.

    Design: Difficulty/combinatorial_formula/pore_space_bonus_round_per_tract_then_sum
    """
    project, tracts = _three_tracts_with_outstanding_offers(api)

    executed = _accept_every_outstanding_offer(api, tracts)

    assert executed[0]["net_acreage"] == 333.3330
    assert executed[0]["bonus_settlement_usd"] == 5000.00
    assert executed[1]["net_acreage"] == 666.6670
    assert executed[1]["bonus_settlement_usd"] == 10000.01
    assert executed[2]["net_acreage"] == 1400.0000
    assert executed[2]["bonus_settlement_usd"] == 21000.00

    project = fixtures.refresh_project(api, project["id"])
    assert project["pore_space_bonus_total_usd"] == 36000.01
    assert project["pore_space_bonus_total_usd"] != 36000.00


def test_pore_space_acreage_and_consent_recomputed_over_the_holder_set(api):
    """At project level the holders are the tracts whose `lease_status` is `EXECUTED` or `UNITIZED`, summed in `created_at` ascending order: `secured_acreage` is the sum of their `net_acreage` values rounded half up to 4 decimal places, `outstanding_acreage` is `total_project_acreage` less `secured_acreage` rounded half up to 4 decimal places, `pore_space_consent_pct` is 100.0 multiplied by `secured_acreage` divided by `total_project_acreage` rounded half up to 2 decimal places, and `pore_space_bonus_total_usd` is the sum of the holders' already-rounded `bonus_settlement_usd` values rounded half up to 2 decimal places.
    Every one of these four project figures is recomputed on acceptance, and both the tract's `version` and the project's `version` increment.

    Design: Difficulty/combinatorial_formula/pore_space_bonus_round_per_tract_then_sum
    """
    project, tracts = _three_tracts_with_outstanding_offers(api)

    _accept_every_outstanding_offer(api, tracts)

    project = fixtures.refresh_project(api, project["id"])
    assert project["secured_acreage"] == 2400.0000
    assert project["outstanding_acreage"] == 1600.0000
    assert project["pore_space_consent_pct"] == 60.00


def _accepted_model_and_three_wellbores_outside_the_area_of_review(api):
    """Accept a model but leave the area of review unpublished.

    Every wellbore therefore registers against a project whose `aor_radius_km` is
    still 0, so none of them is inside the area of review yet.
    """
    ctx = fixtures.setup_project_with_accepted_model(api)
    specs = [
        constants.WELLBORE_SEAL_OPEN_HOLE_NEAR,
        constants.WELLBORE_PARTIALLY_PLUGGED_MID,
        constants.WELLBORE_CEMENTED_DOCUMENTED_FAR,
    ]
    for index, spec in enumerate(specs, start=1):
        ctx["wellbores"].append(
            fixtures.register_wellbore(
                api, ctx["project"]["id"], f"15-001-{index:05d}", **spec
            )
        )
    ctx["project"] = fixtures.refresh_project(api, ctx["project"]["id"])
    return ctx


def test_required_assurance_rises_when_delineation_publishes_the_area_of_review(
    api, project_developer_headers
):
    """The first link copies the model's computed `aor_radius_km` onto the project's `aor_radius_km`, publishing the delineation.
    The third link recomputes the project's `corrective_action_completion_pct` and `required_financial_assurance_usd`, because the population of obligated wellbores has changed.
    Finally the model's `plume_status` moves `SIMULATED → AOR_FINALIZED`, and both the model's `version` and the project's `version` increment by one.
    The emergency reserve bucket is the larger of a two-million-dollar floor and the area-based figure obtained by multiplying 500,000.00 dollars per square kilometre by pi and by the square of the project's `aor_radius_km`, that area-based figure being rounded half up to 2 decimal places before the comparison.
    The project's `required_financial_assurance_usd` is the sum of those five already-rounded buckets, itself rounded half up to 2 decimal places.
    `assurance_coverage_status` is then derived by comparing `allocated_assurance_usd` against `required_financial_assurance_usd`, and the tests are applied in this order: the status is `UNFUNDED` when `allocated_assurance_usd` is zero or below; otherwise it is `FUNDED` when `allocated_assurance_usd` is at least `required_financial_assurance_usd`; otherwise it is `UNDERFUNDED`.

    Design: Difficulty/combinatorial_formula/required_assurance_pinned_evaluation_order
    """
    ctx = _accepted_model_and_three_wellbores_outside_the_area_of_review(api)
    assert ctx["project"]["required_financial_assurance_usd"] == 12500000.00
    assert ctx["project"]["aor_radius_km"] == 0

    model = validate_success(
        api.finalize_aor(ctx["model"]["id"], {}, project_developer_headers)
    )
    assert model["plume_status"] == "AOR_FINALIZED"

    project = fixtures.refresh_project(api, ctx["project"]["id"])
    assert project["aor_radius_km"] == 3.0
    assert project["required_financial_assurance_usd"] == 25857666.94
    assert project["assurance_coverage_status"] == "UNFUNDED"


def test_required_assurance_rescreens_wellbore_costs_before_summing_the_buckets(
    api, project_developer_headers
):
    """The second link re-screens legacy wellbores: because the project's area of review has changed, every legacy wellbore of the project whose `corrective_action_status` is `OUT_OF_AOR` and whose `distance_from_injector_km` is less than or equal to the project's new `aor_radius_km` moves `OUT_OF_AOR → IDENTIFIED`, and every wellbore now inside the area of review has its `risk_score` and `ca_cost_estimate_usd` recomputed against the new radius.
    The corrective-action bucket totals the `ca_cost_estimate_usd` of the project's wellbores whose `corrective_action_status` is `IDENTIFIED`, `CA_REQUIRED` or `CA_SCHEDULED` — work that is still outstanding — with the sum of those already-rounded per-wellbore figures rounded half up to 2 decimal places.
    The rate the project will actually be able to use, `effective_injection_rate_tpy`, is the smaller of the parent project's `requested_annual_injection_rate_tpy` and that `max_injection_rate_tpy` — a developer who asks for more than the rock allows receives the rock's answer, and a developer who asks for less receives what they asked for.
    The administrative fee is tiered on the governing model's `effective_annual_injection_rate_tpy`: it is 250,000.00 dollars when that rate is at most 500,000 tonnes per year, 500,000.00 dollars when the rate exceeds 500,000 but is at most 1,500,000 tonnes per year, and 900,000.00 dollars when the rate exceeds 1,500,000 tonnes per year.

    Design: Difficulty/combinatorial_formula/required_assurance_pinned_evaluation_order
    """
    ctx = _accepted_model_and_three_wellbores_outside_the_area_of_review(api)

    validate_success(api.finalize_aor(ctx["model"]["id"], {}, project_developer_headers))

    model = fixtures.refresh_model(api, ctx["model"]["id"])
    assert model["effective_injection_rate_tpy"] == 1000000

    rescreened = [
        fixtures.refresh_wellbore(api, wellbore["id"])["ca_cost_estimate_usd"]
        for wellbore in ctx["wellbores"]
    ]
    assert rescreened == [570000.00, 389200.00, 261300.00]
