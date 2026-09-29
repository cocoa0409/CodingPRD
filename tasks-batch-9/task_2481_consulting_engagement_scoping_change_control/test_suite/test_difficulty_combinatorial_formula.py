"""Formulas whose result is selected from several independently computed terms."""

from prd_bench_local_runner.testing import get_success_data

from test_helpers import ConsultingApiClient
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as fx
from test_helpers.assertions import assert_fields, assert_money, assert_two_dp

TARGET_BONUS_SLACK_CENTS = 30000000
TARGET_BONUS_BINDING_CENTS = 10000000


def test_outcome_based_at_risk_share_is_capped_by_the_risk_loaded_share(
    api: ConsultingApiClient,
) -> None:
    """With a slack bonus the 0.35 risk-loaded cap is the smallest candidate.

    PRD 3.5: "`at_risk_component_cents` is the smallest of those three
    candidates — the uncapped remainder, the risk-loaded cap and the
    benefit-share cap — so which cap binds varies with the client's bonus
    appetite."

    Design: Difficulty/combinatorial_formula/outcome_based_fee_cap_selection_matrix
    """
    sc = fx.build_baselined_pursuit(api)
    sow = fx.draft_sow(
        sc,
        pricing_model=C.PRICING_OUTCOME_BASED,
        target_bonus_cents=TARGET_BONUS_SLACK_CENTS,
    )

    # 40 OUTCOME_BASED + 15 COMMITTEE + 8 specification + 10 dependency + 3 obligation
    assert_fields(sow, risk_score=76)
    assert_two_dp(sow, "risk_premium_pct", C.RISK_PREMIUM_HIGH)
    # 8566982 * 0.70, with no premium on the fixed share
    assert_money(sow, "fixed_component_cents", 5996887)
    # min(remainder 4283491, risk-loaded cap 3598132, benefit cap 6000000)
    assert_money(sow, "at_risk_component_cents", 3598132)
    assert_money(sow, "quoted_fee_cents", 9595019)
    assert_money(sow, "not_to_exceed_cents", None)
    # Below the fixed-fee quote on identical scope
    assert sow["quoted_fee_cents"] < C.CANON_FIXED_FEE_QUOTED_CENTS


def test_lowering_the_target_bonus_makes_the_benefit_share_cap_bind(
    api: ConsultingApiClient,
) -> None:
    """Only the bonus moves, and a different one of the three candidates wins.

    PRD 3.5: "The second cap is `target_bonus_cents` multiplied by 0.20,
    rounded half up to whole cents."

    Design: Difficulty/combinatorial_formula/outcome_based_fee_cap_selection_matrix
    """
    sc = fx.build_baselined_pursuit(api)
    fx.draft_sow(
        sc,
        pricing_model=C.PRICING_OUTCOME_BASED,
        target_bonus_cents=TARGET_BONUS_SLACK_CENTS,
    )
    current_version = fx.read_opportunity(sc)["version"]

    leaner = get_success_data(
        api.create_sow(
            F.sow_payload(
                sc.opportunity_id,
                current_version,
                pricing_model=C.PRICING_OUTCOME_BASED,
                target_bonus_cents=TARGET_BONUS_BINDING_CENTS,
            ),
            sc.partner,
        )
    )

    # The fixed share is untouched by the bonus
    assert_money(leaner, "fixed_component_cents", 5996887)
    # 10000000 * 0.20 now beats the remainder 4283491 and the cap 3598132
    assert_money(leaner, "at_risk_component_cents", 2000000)
    assert_money(leaner, "quoted_fee_cents", 7996887)
    assert_money(leaner, "not_to_exceed_cents", None)


def test_baseline_rounds_each_line_before_summing_the_effort_cost(
    api: ConsultingApiClient,
) -> None:
    """Per-line rounding lands one cent above the sum-then-round answer.

    PRD 3.4: "Only after every line has been individually rounded are the
    rounded lines added together, and that integer sum is stored as the
    pursuit's `baseline_effort_cost_cents`."

    Design: Difficulty/combinatorial_formula/scope_baseline_per_line_rounding_and_discount_tier
    """
    sc = fx.build_scoped_pursuit(api)

    baselined = fx.baseline_scope(sc)

    # 120.25 * 36500 * 0.95 = 4169668.75 and 80.50 * 57500 * 0.95 = 4397312.50
    assert_money(
        fx.read_deliverable(sc, sc.d1_id), "line_cost_cents", C.CANON_D1_LINE_COST_CENTS
    )
    assert_money(
        fx.read_deliverable(sc, sc.d2_id), "line_cost_cents", C.CANON_D2_LINE_COST_CENTS
    )
    assert_money(
        baselined,
        "baseline_effort_cost_cents",
        C.CANON_BASELINE_EFFORT_COST_CENTS,
    )
    # Summing the raw lines first would round 8566981.25 down to 8566981
    assert baselined["baseline_effort_cost_cents"] != 8566981


def test_total_estimated_hours_selects_the_five_percent_volume_tier(
    api: ConsultingApiClient,
) -> None:
    """200.75 hours sit just above the inclusive 200-hour lower bound.

    PRD 3.4: "The boundaries bite exactly where stated — a scope totalling
    199.99 hours takes no discount, and one totalling exactly 200.00 hours
    takes the five-percent tier."

    Design: Difficulty/combinatorial_formula/scope_baseline_per_line_rounding_and_discount_tier
    """
    sc = fx.build_scoped_pursuit(api)

    baselined = fx.baseline_scope(sc)

    assert_two_dp(baselined, "total_estimated_hours", C.CANON_TOTAL_ESTIMATED_HOURS)
    assert_two_dp(baselined, "scope_discount_pct", C.SCOPE_DISCOUNT_TIER_MID)
    # Nodes rather than edges: d1 -> d2 counts as a chain of 2
    assert_fields(
        baselined,
        longest_dependency_chain=C.CANON_LONGEST_DEPENDENCY_CHAIN,
        status="SCOPE_BASELINED",
    )
    assert baselined["baselined_at"].startswith("2026-08-03T09:00:00")
