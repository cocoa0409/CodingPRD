"""Inclusive thresholds tested at the exact value and one increment away."""

from typing import Tuple

from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers import ConsultingApiClient
from test_helpers import api_errors as E
from test_helpers import constants as C
from test_helpers import fixtures as fx
from test_helpers.assertions import assert_fields, assert_money, assert_two_dp

# 40 percent of the 100000000 estimate scores exactly 60.00; 39.9 percent of it
# scores 59.96, the nearest reachable value below the inclusive threshold.
BUDGET_ON_THE_LINE_CENTS = 40000000
BUDGET_BELOW_THE_LINE_CENTS = 39900000

# 167.76 added ANALYST hours price to a cumulative 40.00 percent, 167.80 to 40.01
HOURS_ON_THE_LINE = 167.76
HOURS_OVER_THE_LINE = 167.80


def _two_identical_screening_pursuits(
    api: ConsultingApiClient,
) -> Tuple[fx.Scenario, fx.Scenario]:
    """The same client, the same estimate, the same sponsor: only budgets differ."""
    sc = fx.build_screening_pursuit(api)
    fx.screen_conflicts(sc)
    return sc, fx.build_sibling_screening_pursuit(sc)


def test_a_verified_score_of_exactly_sixty_qualifies(
    api: ConsultingApiClient,
) -> None:
    """The threshold is inclusive, so the pursuit standing on it goes forward.

    PRD 3.2: "A pursuit qualifies when that score is 60.00 or higher — the
    threshold is inclusive, so a score of exactly 60.00 qualifies."

    Design: Difficulty/boundary_precision_check/qualification_threshold_exact_sixty_boundary
    """
    sc, _ = _two_identical_screening_pursuits(api)

    fx.verify_budget(sc, BUDGET_ON_THE_LINE_CENTS)
    decided = get_success_data(api.qualify(sc.opportunity_id, {}, sc.partner))

    # 30 * 0.80 + 40 * 0.40 + 20 + 0
    assert_two_dp(decided, "qualification_score_verified", 60.00)
    assert_fields(decided, status="QUALIFIED")
    # The intake variant is untouched by the decision
    assert_two_dp(decided, "qualification_score_intake", 68.00)


def test_a_verified_score_four_hundredths_below_sixty_is_disqualified(
    api: ConsultingApiClient,
) -> None:
    """One hundred thousand cents of budget less, and the pursuit dies.

    PRD 3.2: "The decision itself re-runs the verified-budget variant of the
    score, writes the result to `qualification_score_verified`, and branches
    purely on that freshly recomputed number: a score of 60.00 or above moves
    the pursuit `SCREENING → QUALIFIED`, and a score below 60.00 moves it
    `SCREENING → DISQUALIFIED`."

    Design: Difficulty/boundary_precision_check/qualification_threshold_exact_sixty_boundary
    """
    _, sib = _two_identical_screening_pursuits(api)

    fx.verify_budget(sib, BUDGET_BELOW_THE_LINE_CENTS)
    decided = get_success_data(api.qualify(sib.opportunity_id, {}, sib.partner))

    # 30 * 0.80 + 40 * 0.399 + 20 + 0
    assert_two_dp(decided, "qualification_score_verified", 59.96)
    assert_fields(decided, status="DISQUALIFIED")
    assert_two_dp(decided, "qualification_score_intake", 68.00)


def test_a_cumulative_change_of_exactly_forty_percent_is_assessed(
    api: ConsultingApiClient,
) -> None:
    """The ceiling admits the request that lands precisely on it.

    PRD 3.8: "Two thresholds then read that one number. If it is strictly
    greater than 40.00, the assessment is refused outright with
    `ERR_CHANGE_EXCEEDS_MATERIALITY` — a cumulative figure of exactly 40.00 is
    accepted, and 40.01 is not."

    Design: Difficulty/boundary_precision_check/change_materiality_ceiling_exact_forty_boundary
    """
    sc = fx.build_burned_engagement(api)
    request = fx.raise_change_request(sc, added_hours=HOURS_ON_THE_LINE)

    assessed = fx.assess_change_request(sc, request["id"])

    # 167.76 * 21500 * 0.95 loaded by the pinned 0.20 premium
    assert_money(assessed, "gross_delta_cents", 3426498)
    assert_money(assessed, "fee_delta_cents", 4111798)
    assert_two_dp(assessed, "cumulative_change_pct_at_assessment", 40.00)
    assert_fields(
        assessed,
        routing=C.ROUTING_LEADERSHIP_THEN_CLIENT,
        status=C.CR_PENDING_LEADERSHIP_APPROVAL,
    )


def test_a_cumulative_change_of_forty_point_zero_one_is_refused(
    api: ConsultingApiClient,
) -> None:
    """Four hundredths of an hour more, and the assessment never happens.

    PRD 3.8: "Materiality is measured cumulatively and against the **signed**
    price, never against the current contracted figure."

    Design: Difficulty/boundary_precision_check/change_materiality_ceiling_exact_forty_boundary
    """
    sc = fx.build_burned_engagement(api)
    request = fx.raise_change_request(sc, added_hours=HOURS_OVER_THE_LINE)

    response = api.assess_impact(request["id"], {}, sc.manager)

    validate_error(response, E.ERR_CHANGE_EXCEEDS_MATERIALITY)
    refused = fx.read_change_request(sc, request["id"])
    assert_fields(
        refused,
        status=C.CR_DRAFT,
        routing=None,
        gross_delta_cents=None,
        fee_delta_cents=None,
        cumulative_change_pct_at_assessment=None,
    )
    # The signed price is unchanged, so it stays the denominator for the next try
    assert_money(
        fx.read_engagement(sc), "contracted_fee_cents", C.CANON_FIXED_FEE_QUOTED_CENTS
    )
