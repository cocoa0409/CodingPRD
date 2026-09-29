"""One formula, two stored results: the qualification score and the fee quote."""

from prd_bench_local_runner.testing import get_success_data, validate_success

from test_helpers import ConsultingApiClient
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as fx
from test_helpers.assertions import assert_fields, assert_money, assert_two_dp


def test_intake_variant_scores_the_stated_budget_and_survives_verification(
    api: ConsultingApiClient,
) -> None:
    """Verification writes the second variant without touching the first.

    PRD 3.2: "At intake, the budget figure fed into the budget ratio is
    `stated_budget_cents`, the client's self-reported number, and the result is
    written to `qualification_score_intake` while `verified_budget_cents`
    remains null."

    Design: Difficulty/dual_variant_calc/qualification_intake_vs_verified_budget_divergence
    """
    sc = fx.build_screening_pursuit(api)
    fresh = fx.read_opportunity(sc)
    # 30 * 0.80 + 40 * 0.60 + 20 * 1 + 10 * 0
    assert_two_dp(fresh, "qualification_score_intake", 68.00)
    assert fresh["qualification_score_verified"] is None
    assert fresh["verified_budget_cents"] is None

    fx.screen_conflicts(sc)
    verified = fx.verify_budget(sc, 30000000)

    # 30 * 0.80 + 40 * 0.30 + 20 * 1 + 10 * 0
    assert_two_dp(verified, "qualification_score_verified", 56.00)
    assert_two_dp(verified, "qualification_score_intake", 68.00)
    assert_money(verified, "verified_budget_cents", 30000000)
    assert (
        verified["qualification_score_intake"]
        - verified["qualification_score_verified"]
        == 12.00
    )


def test_qualify_gate_follows_the_verified_variant_into_disqualified(
    api: ConsultingApiClient,
) -> None:
    """The passing intake score plays no part in the gate.

    PRD 3.2: "The decision itself re-runs the verified-budget variant of the
    score, writes the result to `qualification_score_verified`, and branches
    purely on that freshly recomputed number: a score of 60.00 or above moves
    the pursuit `SCREENING → QUALIFIED`, and a score below 60.00 moves it
    `SCREENING → DISQUALIFIED`."

    Design: Difficulty/dual_variant_calc/qualification_intake_vs_verified_budget_divergence
    """
    sc = fx.build_screening_pursuit(api)
    fx.screen_conflicts(sc)
    fx.verify_budget(sc, 30000000)

    decided = get_success_data(api.qualify(sc.opportunity_id, {}, sc.partner))

    assert_fields(decided, status="DISQUALIFIED")
    assert_two_dp(decided, "qualification_score_verified", 56.00)
    assert_two_dp(decided, "qualification_score_intake", 68.00)


def test_fixed_fee_loads_the_whole_premium_into_one_guaranteed_number(
    api: ConsultingApiClient,
) -> None:
    """A high-tier fixed-fee quote is the risk-loaded baseline exactly.

    PRD 3.5: "`fixed_component_cents` becomes the risk-loaded total,
    `at_risk_component_cents` is 0, `not_to_exceed_cents` is null, and
    `quoted_fee_cents` equals `fixed_component_cents`."

    Design: Difficulty/dual_variant_calc/sow_fixed_fee_vs_time_and_materials_variant_divergence
    """
    sc = fx.build_baselined_pursuit(api)
    sow = fx.draft_sow(sc)

    # 25 FIXED_FEE + 15 COMMITTEE + 8 specification + 10 dependency + 3 obligation
    assert_fields(sow, risk_score=61, pricing_model=C.PRICING_FIXED_FEE)
    assert_two_dp(sow, "risk_premium_pct", C.RISK_PREMIUM_HIGH)
    assert_money(sow, "baseline_effort_cost_cents", C.CANON_BASELINE_EFFORT_COST_CENTS)
    assert_money(sow, "quoted_fee_cents", C.CANON_FIXED_FEE_QUOTED_CENTS)
    assert_money(sow, "fixed_component_cents", C.CANON_FIXED_FEE_QUOTED_CENTS)
    assert_money(sow, "at_risk_component_cents", 0)
    assert_money(sow, "not_to_exceed_cents", None)


def test_time_and_materials_discards_the_premium_and_widens_the_ceiling(
    api: ConsultingApiClient,
) -> None:
    """The same frozen baseline lands in a different tier and a ceiling quote.

    PRD 3.5: "Under `TIME_AND_MATERIALS`, the risk premium is discarded from
    the fee entirely — risk is passed through to the client hour by hour rather
    than pre-loaded — and the risk tier instead widens a billing ceiling."

    Design: Difficulty/dual_variant_calc/sow_fixed_fee_vs_time_and_materials_variant_divergence
    """
    sc = fx.build_sow_draft(api)
    fixed_fee_id = sc.sow_id
    current_version = fx.read_opportunity(sc)["version"]

    tnm = get_success_data(
        api.create_sow(
            F.sow_payload(
                sc.opportunity_id,
                current_version,
                pricing_model=C.PRICING_TIME_AND_MATERIALS,
            ),
            sc.partner,
        )
    )

    # 10 TIME_AND_MATERIALS + 15 + 8 + 10 + 3 lands in the medium tier
    assert_fields(tnm, risk_score=C.CANON_TNM_RISK_SCORE)
    assert_two_dp(tnm, "risk_premium_pct", C.RISK_PREMIUM_MEDIUM)
    assert_money(tnm, "not_to_exceed_cents", C.CANON_TNM_QUOTED_CENTS)
    assert_money(tnm, "quoted_fee_cents", C.CANON_TNM_QUOTED_CENTS)
    assert_money(tnm, "fixed_component_cents", 0)
    assert_money(tnm, "at_risk_component_cents", 0)
    # Identical pinned baseline on both rows, so the quote gap is variant-driven
    assert_money(tnm, "baseline_effort_cost_cents", C.CANON_BASELINE_EFFORT_COST_CENTS)
    assert_fields(tnm, supersedes_sow_id=fixed_fee_id)

    superseded = validate_success(api.get_sow(fixed_fee_id, sc.partner))
    assert_fields(superseded, status="SUPERSEDED")
    assert_money(
        superseded, "quoted_fee_cents", C.CANON_FIXED_FEE_QUOTED_CENTS
    )

    pursuit = fx.read_opportunity(sc)
    assert_fields(pursuit, status="SOW_ISSUED")
    assert pursuit["version"] > current_version
