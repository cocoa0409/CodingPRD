"""Fair-use weighting variants and the nested rounding of the E&O premium.

The first pair of scenarios turns one factor vector into two opposite business
outcomes purely on the parent asset's `usage_purpose`; the second pins the order
in which the per-asset loadings of a premium are rounded.
"""
from test_helpers import (
    assert_asset_dimensions,
    assert_clearance_chart,
    assert_eo_application,
    assert_fair_use_analysis,
    assert_license_money_ledger,
    assert_production_counters,
    CLEARANCE_SUPERVISOR,
    create_and_execute_license,
    create_archive_with_rate_card,
    create_asset,
    create_asset_with_selected_source,
    create_fair_use_analysis,
    create_production_in_clearance,
    drive_fair_use_analysis,
    get_asset,
    get_chart,
    get_production,
    issue_opinion_letter,
    LEGAL_COUNSEL,
    open_eo_application,
    pin_chart,
    state_payload,
    validate_error,
    validate_success,
)

# The PRD §3.5 factor vector: 90 transformative, 60 nature, 40 amount used,
# 50 market harm — the identical inputs both variants are fed.
_FACTORS = {
    "transformative_score": 90,
    "nature_score": 60,
    "amount_used_score": 40,
    "market_harm_score": 50,
}


def _setup_identical_factor_analyses(api):
    """Two footage assets differing only in `usage_purpose`, each with a live letter.

    Each asset carries one SUBMITTED analysis on the identical factor vector and
    one ISSUED opinion letter, so the opinion-letter requirement of PRD §3.5 is
    already satisfied and only the score gate can fire on acceptance.
    """
    production = create_production_in_clearance(
        api, title="Grain and Memory", delivery_deadline_date="2027-09-30")
    asset_c = create_asset(
        api, production["id"], asset_type="ARCHIVAL_FOOTAGE",
        title="Newsreel excerpt under critique", timecode_in_seconds=0,
        timecode_out_seconds=20, usage_purpose="CRITICAL_COMMENTARY")
    asset_d = create_asset(
        api, production["id"], asset_type="ARCHIVAL_FOOTAGE",
        title="Newsreel excerpt as wallpaper", timecode_in_seconds=0,
        timecode_out_seconds=20, usage_purpose="ILLUSTRATIVE_BACKGROUND")

    analysis_c = create_fair_use_analysis(api, asset_c["id"], **_FACTORS)
    analysis_d = create_fair_use_analysis(api, asset_d["id"], **_FACTORS)
    drive_fair_use_analysis(api, analysis_c["id"], "SUBMITTED")
    drive_fair_use_analysis(api, analysis_d["id"], "SUBMITTED")
    issue_opinion_letter(api, analysis_c["id"], counsel_firm="Donaldson & Callif",
                         letter_reference="OL-C-1", risk_rating="LOW")
    issue_opinion_letter(api, analysis_d["id"], counsel_firm="Donaldson & Callif",
                         letter_reference="OL-D-1", risk_rating="MODERATE")
    return production, asset_c, asset_d, analysis_c, analysis_d


def _setup_two_licensed_rows_with_draft_eo(api):
    """Two CLEARED / LICENSED footage rows under one PINNED chart and a DRAFT E&O.

    The application asks for a coverage limit of 1000040 cents against a retention
    of 20000, the figures that make the per-asset rounding order observable.
    """
    production = create_production_in_clearance(
        api, title="Two Reels", delivery_deadline_date="2027-12-31")
    archive, _card = create_archive_with_rate_card(api)

    licenses = []
    for title in ("Reel one", "Reel two"):
        asset, _candidate = create_asset_with_selected_source(
            api, production["id"], archive["id"], title=title,
            timecode_in_seconds=0, timecode_out_seconds=45)
        licenses.append(create_and_execute_license(
            api, production["id"], asset["id"], archive["id"]))

    chart = pin_chart(api, production["id"], chart_label="v1 pre-E&O")
    application = open_eo_application(api, production["id"], chart["id"],
                                      coverage_limit_cents=1000040,
                                      retention_cents=20000)
    return {
        "production": get_production(api, production["id"]),
        "archive": archive,
        "licenses": licenses,
        "chart": chart,
        "eo_application": application,
    }


# ─── The fair-use weighting variant ──────────────────────────────────────────


def test_critical_commentary_asset_scores_0_6750_and_its_analysis_is_accepted(api):
    """The transformative weighting turns 90/60/40/50 into 0.6750 and clears the gate.

    PRD §3.5: "An asset used for `CRITICAL_COMMENTARY` yields
    `TRANSFORMATIVE_WEIGHTED`, weighting the transformative factor at 0.45, nature
    at 0.10, amount used at 0.15 and market harm at 0.30." PRD §3.5 also fixes the
    consequence: "Acceptance is what clears the asset. The asset's `rights_basis`
    becomes `FAIR_USE` and its `licensing_status` recomputes to `CLEARED`, whether
    the asset had been sitting in `UNCLEARED` with no licences at all or in
    `IN_NEGOTIATION` with a licence still on the table — both `UNCLEARED →
    CLEARED` and `IN_NEGOTIATION → CLEARED` are legitimate dimension-A moves out
    of an acceptance."

    Design: Difficulty/dual_variant_calc/fair_use_weighting_variant_divergence_on_identical_factors
    """
    _production, asset_c, _asset_d, analysis_c, _analysis_d = \
        _setup_identical_factor_analyses(api)

    assert_fair_use_analysis(analysis_c)
    assert analysis_c["weighting_variant"] == "TRANSFORMATIVE_WEIGHTED"
    # 0.90*0.45 + 0.60*0.10 + 0.40*0.15 + 0.50*0.30 = 0.6750
    assert round(float(analysis_c["strength_score"]), 4) == 0.6750

    accepted = validate_success(
        api.set_fair_use_analysis_state(
            analysis_c["id"],
            state_payload("ACCEPTED", decision_rationale="Transformative critique"),
            LEGAL_COUNSEL),
        200)
    assert accepted["status"] == "ACCEPTED"
    assert accepted["decision_rationale"] == "Transformative critique"
    assert round(float(accepted["strength_score"]), 4) == 0.6750

    assert_asset_dimensions(get_asset(api, asset_c["id"]), "CLEARED",
                            depiction_status="NOT_REQUIRED", rights_basis="FAIR_USE",
                            lapse_count=0)


def test_illustrative_background_asset_scores_0_5700_and_is_refused(api):
    """The market-harm weighting turns the same vector into 0.5700 and is refused.

    PRD §3.5: "An asset used for `ILLUSTRATIVE_BACKGROUND` yields
    `MARKET_HARM_WEIGHTED`, weighting the transformative factor at 0.20, nature at
    0.10, amount used at 0.20 and market harm at 0.50." PRD §3.5 fixes the refusal:
    "only once at least one opinion letter on the analysis is in `ISSUED` does the
    score gate apply, refusing a `strength_score` below 0.6000 with
    `ERR_FAIR_USE_SCORE_INSUFFICIENT` (HTTP 422)."

    Design: Difficulty/dual_variant_calc/fair_use_weighting_variant_divergence_on_identical_factors
    """
    _production, _asset_c, asset_d, _analysis_c, analysis_d = \
        _setup_identical_factor_analyses(api)

    assert_fair_use_analysis(analysis_d)
    assert analysis_d["weighting_variant"] == "MARKET_HARM_WEIGHTED"
    # 0.90*0.20 + 0.60*0.10 + 0.40*0.20 + 0.50*0.50 = 0.5700
    assert round(float(analysis_d["strength_score"]), 4) == 0.5700

    validate_error(
        api.set_fair_use_analysis_state(
            analysis_d["id"],
            state_payload("ACCEPTED",
                          decision_rationale="Attempted on identical factors"),
            LEGAL_COUNSEL),
        "ERR_FAIR_USE_SCORE_INSUFFICIENT")

    settled = validate_success(api.get_fair_use_analysis(analysis_d["id"],
                                                         CLEARANCE_SUPERVISOR), 200)
    assert settled["status"] == "SUBMITTED"
    assert round(float(settled["strength_score"]), 4) == 0.5700

    # No accepted analysis, no licences and no attestation, so the rollup of
    # PRD §3.1 leaves the asset exactly where it was.
    assert_asset_dimensions(get_asset(api, asset_d["id"]), "UNCLEARED",
                            depiction_status="NOT_REQUIRED",
                            rights_basis="UNDETERMINED", lapse_count=0)


def test_identical_factors_diverge_only_on_the_parent_assets_usage_purpose(api):
    """One factor vector, two variants, opposite outcomes on the same production.

    PRD §3.5: "The variant choice is decisive rather than cosmetic: factor scores
    of 90, 60, 40 and 50 score 0.6750 under the transformative weighting and clear
    the acceptance threshold, while the very same four numbers score 0.5700 under
    the market-harm weighting and are refused — identical inputs, opposite
    outcomes, decided entirely by the parent asset's `usage_purpose`."

    Design: Difficulty/dual_variant_calc/fair_use_weighting_variant_divergence_on_identical_factors
    """
    production, asset_c, asset_d, analysis_c, analysis_d = \
        _setup_identical_factor_analyses(api)

    # The four submitted factor scores are byte-identical on both analyses.
    for factor, value in _FACTORS.items():
        assert analysis_c[factor] == value
        assert analysis_d[factor] == value

    assert analysis_c["weighting_variant"] == "TRANSFORMATIVE_WEIGHTED"
    assert analysis_d["weighting_variant"] == "MARKET_HARM_WEIGHTED"
    assert round(float(analysis_c["strength_score"]), 4) == 0.6750
    assert round(float(analysis_d["strength_score"]), 4) == 0.5700

    accepted = validate_success(
        api.set_fair_use_analysis_state(
            analysis_c["id"],
            state_payload("ACCEPTED", decision_rationale="Transformative critique"),
            LEGAL_COUNSEL),
        200)
    assert accepted["status"] == "ACCEPTED"

    validate_error(
        api.set_fair_use_analysis_state(
            analysis_d["id"],
            state_payload("ACCEPTED",
                          decision_rationale="Attempted on identical factors"),
            LEGAL_COUNSEL),
        "ERR_FAIR_USE_SCORE_INSUFFICIENT")

    assert get_asset(api, asset_c["id"])["licensing_status"] == "CLEARED"
    assert get_asset(api, asset_d["id"])["licensing_status"] == "UNCLEARED"

    # PRD §3.5: "The production's `cleared_asset_count` rises by one, its
    # `open_asset_count` falls by one" — for the accepted analysis only.
    assert_production_counters(get_production(api, production["id"]),
                               asset_count=2, cleared_asset_count=1,
                               open_asset_count=1)


# ─── The E&O premium's per-asset rounding ────────────────────────────────────


def test_eo_premium_rounds_each_asset_loading_before_summing_them(api):
    """Two loadings of 10000.4 round to 10000 each, giving 20000 and a premium of 26501.

    PRD §3.7: "The row's loading is then the `coverage_limit_cents` multiplied by
    that row's final weight, rounded half up to an integer number of cents **at
    this point, per asset**, and the loading total is the sum of those
    already-rounded per-asset loadings."

    Design: Difficulty/combinatorial_formula/eo_premium_rounds_per_asset_then_sums
    """
    scenario = _setup_two_licensed_rows_with_draft_eo(api)
    application = scenario["eo_application"]

    assert_eo_application(application)
    assert application["status"] == "DRAFT"
    assert application["premium_cents"] is None
    assert application["coverage_limit_cents"] == 1000040
    assert application["retention_cents"] == 20000

    submitted = validate_success(
        api.set_eo_application_state(application["id"], state_payload("SUBMITTED"),
                                     CLEARANCE_SUPERVISOR),
        200)

    # base 12501 (round_half_up of 12500.5) + loading 20000 (10000 + 10000)
    # - retention credit 6000 = 26501.
    assert submitted["premium_cents"] == 26501
    # 26502 is what summing the un-rounded loadings and rounding once produces.
    assert submitted["premium_cents"] != 26502

    persisted = validate_success(
        api.get_eo_application(application["id"], CLEARANCE_SUPERVISOR), 200)
    assert persisted["premium_cents"] == 26501


def test_submission_rates_the_premium_but_leaves_both_review_branches_pending(api):
    """Rating stamps the premium and forks two PENDING branches without entering review.

    PRD §3.7: "Submission also **forks** the application into two independent
    review dimensions, both left at `PENDING`, and the application's `version`
    increments."

    Design: Difficulty/combinatorial_formula/eo_premium_rounds_per_asset_then_sums
    """
    scenario = _setup_two_licensed_rows_with_draft_eo(api)
    application = scenario["eo_application"]
    version_before = application["version"]

    submitted = validate_success(
        api.set_eo_application_state(application["id"], state_payload("SUBMITTED"),
                                     CLEARANCE_SUPERVISOR),
        200)

    assert submitted["status"] == "SUBMITTED"
    assert submitted["legal_review_status"] == "PENDING"
    assert submitted["underwriting_review_status"] == "PENDING"
    assert submitted["premium_cents"] == 26501
    assert submitted["policy_number"] is None
    assert submitted["version"] == version_before + 1

    persisted = validate_success(
        api.get_eo_application(application["id"], CLEARANCE_SUPERVISOR), 200)
    assert persisted["status"] == "SUBMITTED"
    assert persisted["legal_review_status"] == "PENDING"
    assert persisted["underwriting_review_status"] == "PENDING"
    assert persisted["premium_cents"] == 26501


def test_rated_premium_reads_two_licensed_chart_rows_over_a_724500_cent_ledger(api):
    """The two rows the premium rated are the chart's, and the ledger holds both fees.

    PRD §3.7: "Next, the rated rows are walked in ascending asset `created_at`
    order, and only the rows whose `licensing_status` is `CLEARED` are rated at
    all; every other row is skipped."

    Design: Difficulty/combinatorial_formula/eo_premium_rounds_per_asset_then_sums
    """
    scenario = _setup_two_licensed_rows_with_draft_eo(api)

    chart = get_chart(api, scenario["chart"]["id"])
    assert_clearance_chart(chart)
    assert chart["status"] == "PINNED"
    assert chart["pinned_row_count"] == 2
    assert chart["music_leg_gap_count"] == 0
    for row in chart["pinned_rows"]:
        assert row["licensing_status"] == "CLEARED"
        assert row["rights_basis"] == "LICENSED"
        assert row["depiction_status"] == "NOT_REQUIRED"

    submitted = validate_success(
        api.set_eo_application_state(scenario["eo_application"]["id"],
                                     state_payload("SUBMITTED"), CLEARANCE_SUPERVISOR),
        200)
    assert submitted["premium_cents"] == 26501

    # PRD §2.9: committed_fee_cents equals the sum of executed_fee_cents over every
    # licence of the production whose status is EXECUTED, ACTIVE or EXPIRING.
    for license_row in scenario["licenses"]:
        assert license_row["executed_fee_cents"] == 362250
    production = get_production(api, scenario["production"]["id"])
    assert production["committed_fee_cents"] == 724500
    assert_license_money_ledger(api, production["id"], CLEARANCE_SUPERVISOR)
    assert_production_counters(production, asset_count=2, cleared_asset_count=2,
                               open_asset_count=0)
