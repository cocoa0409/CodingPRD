"""Carrier selection: the declared basis flips the winner, the score is non-linear in
premium, and the safest-available gate reads the opinion verdict rather than the status.
"""

from prd_bench_local_runner.testing import validate_error

from test_helpers import api_errors, fiduciary_headers
from test_helpers.constants import (
    RATING_POINTS,
    W_CAPITAL,
    W_PRICE,
    W_RATING,
    capital_component,
    composite_score_bp,
    floor_div,
    price_component,
)
from test_helpers.fixtures import (
    InsurerSpec,
    ParticipantSpec,
    QuoteSpec,
    build_authorized_plan,
    build_quoting_tranche,
    collect_quotes,
    create_expert,
    create_insurer_panel,
    issue_opinion,
    read_expert,
    read_quote,
    read_tranche,
    review_expert,
    select_insurer,
)

AURORA_PREMIUM = 12500000
BEACON_PREMIUM = 11800000
CARDINAL_PREMIUM = 13400000

PANEL = (
    InsurerSpec("Aurora Life Assurance", "AA_PLUS", 4200),
    InsurerSpec("Beacon Mutual Annuity", "AA_MINUS", 3800),
    InsurerSpec("Cardinal Guaranty Life", "AAA", 5100),
)

#: (rating grade, capital ratio, premium) for the three carriers, in panel order.
CARRIERS = (
    ("AA_PLUS", 4200, AURORA_PREMIUM),
    ("AA_MINUS", 3800, BEACON_PREMIUM),
    ("AAA", 5100, CARDINAL_PREMIUM),
)

LOWEST_PREMIUM = min(premium for _grade, _capital, premium in CARRIERS)


def _expected_scores(selection_basis):
    return [
        composite_score_bp(selection_basis, grade, capital, LOWEST_PREMIUM, premium)
        for grade, capital, premium in CARRIERS
    ]


def _panel_quotes(insurers):
    return [
        QuoteSpec(insurer["id"], premium, 90, 60)
        for insurer, (_grade, _capital, premium) in zip(insurers, CARRIERS)
    ]


# ---------------------------------------------------------------------------
# Design: Difficulty/dual_variant_calc/insurer_selection_basis_flips_winner
# ---------------------------------------------------------------------------


def test_the_two_selection_bases_name_different_winners_on_identical_quote_data(api):
    """Identical quote sets, two bases, two winners.

    PRD: "The fiduciary declares a `selection_basis` of either `SAFETY_WEIGHTED` or
    `PRICE_WEIGHTED`, and the two bases can name different winners on identical
    data."

    PRD: "Under `SAFETY_WEIGHTED` the weights are 55 for rating, 25 for capital, and
    20 for price — claims-paying strength dominates."

    Design: Difficulty/dual_variant_calc/insurer_selection_basis_flips_winner
    """
    authorized = build_authorized_plan(
        api,
        participants=[ParticipantSpec(250000), ParticipantSpec(250000)],
    )
    insurers = create_insurer_panel(api, PANEL)
    aurora, _beacon, cardinal = insurers

    first = build_quoting_tranche(
        api,
        authorized.plan_id,
        [authorized.participants[0]],
        tranche_name="Safety Weighted Tranche",
    )
    second = build_quoting_tranche(
        api,
        authorized.plan_id,
        [authorized.participants[1]],
        tranche_name="Price Weighted Tranche",
    )
    first_quotes = collect_quotes(api, first.tranche_id, _panel_quotes(insurers))
    second_quotes = collect_quotes(api, second.tranche_id, _panel_quotes(insurers))

    safety = select_insurer(api, first.tranche_id, "SAFETY_WEIGHTED")
    price = select_insurer(api, second.tranche_id, "PRICE_WEIGHTED")

    safety_scores = _expected_scores("SAFETY_WEIGHTED")
    price_scores = _expected_scores("PRICE_WEIGHTED")

    assert safety["selection_basis"] == "SAFETY_WEIGHTED"
    assert safety["selected_insurer_id"] == cardinal["id"]
    assert safety["selected_quote_id"] == first_quotes[2]["id"]
    assert safety["selection_score_bp"] == max(safety_scores)

    assert price["selection_basis"] == "PRICE_WEIGHTED"
    assert price["selected_insurer_id"] == aurora["id"]
    assert price["selected_quote_id"] == second_quotes[0]["id"]
    assert price["selection_score_bp"] == max(price_scores)

    assert safety["selected_insurer_id"] != price["selected_insurer_id"]

    for quote, expected in zip(first_quotes, safety_scores):
        assert read_quote(api, quote["id"])["composite_score_bp"] == expected
    for quote, expected in zip(second_quotes, price_scores):
        assert read_quote(api, quote["id"])["composite_score_bp"] == expected


def test_selection_shortlists_the_winner_and_declines_the_rest_with_their_scores(api):
    """The losing quotes are declined but keep the score that lost them the tranche.

    PRD: "The winning quote transitions `SUBMITTED → SHORTLISTED`; every other quote
    of the tranche still in `SUBMITTED` transitions to `DECLINED`, carrying its
    `composite_score_bp` when it was in the candidate pool."

    Design: Difficulty/dual_variant_calc/insurer_selection_basis_flips_winner
    """
    authorized = build_authorized_plan(api, participants=[ParticipantSpec(250000)])
    insurers = create_insurer_panel(api, PANEL)
    _aurora, beacon, cardinal = insurers

    quoting = build_quoting_tranche(api, authorized.plan_id, authorized.participants)
    quotes = collect_quotes(api, quoting.tranche_id, _panel_quotes(insurers))

    selected = select_insurer(api, quoting.tranche_id, "SAFETY_WEIGHTED")

    safety_scores = _expected_scores("SAFETY_WEIGHTED")
    statuses = [read_quote(api, quote["id"])["quote_status"] for quote in quotes]

    assert selected["selected_insurer_id"] == cardinal["id"]
    assert statuses == ["DECLINED", "DECLINED", "SHORTLISTED"]
    for quote, expected in zip(quotes, safety_scores):
        assert read_quote(api, quote["id"])["composite_score_bp"] == expected

    # The cheapest carrier is selected by neither basis.
    beacon_index = 1
    assert BEACON_PREMIUM == LOWEST_PREMIUM
    assert safety_scores[beacon_index] < max(safety_scores)
    assert _expected_scores("PRICE_WEIGHTED")[beacon_index] < max(
        _expected_scores("PRICE_WEIGHTED")
    )
    assert read_quote(api, quotes[beacon_index]["id"])["insurer_id"] == beacon["id"]


# ---------------------------------------------------------------------------
# Design: Difficulty/combinatorial_formula/insurer_composite_score_nonlinear_in_premium
# ---------------------------------------------------------------------------


def test_price_points_are_floor_divided_so_a_large_premium_gap_moves_few_points(api):
    """A 900,000-cent premium gap is worth only six price points after truncation.

    PRD: "For each candidate quote, three component scores on a 0-to-100 scale are
    computed: its rating points, taken from the points value of its
    `rating_at_submission`; its capital points, being the carrier's
    `capital_ratio_bp` divided by 100 with the remainder discarded, then capped at
    100; and its price points, being the lowest premium in the pool multiplied by 100
    and divided by this quote's own `premium_cents` with the remainder discarded,
    which gives 100 to the cheapest quote and proportionally less to dearer ones."

    Design: Difficulty/combinatorial_formula/insurer_composite_score_nonlinear_in_premium
    """
    authorized = build_authorized_plan(api, participants=[ParticipantSpec(250000)])
    insurers = create_insurer_panel(api, PANEL)

    quoting = build_quoting_tranche(api, authorized.plan_id, authorized.participants)
    quotes = collect_quotes(api, quoting.tranche_id, _panel_quotes(insurers))

    select_insurer(api, quoting.tranche_id, "SAFETY_WEIGHTED")

    aurora_price_points = price_component(LOWEST_PREMIUM, AURORA_PREMIUM)
    cardinal_price_points = price_component(LOWEST_PREMIUM, CARDINAL_PREMIUM)
    assert CARDINAL_PREMIUM - AURORA_PREMIUM == 900000
    assert aurora_price_points - cardinal_price_points == 6

    # Truncation, not proportionality: the raw ratios are not integers.
    assert LOWEST_PREMIUM * 100 % AURORA_PREMIUM != 0
    assert aurora_price_points == floor_div(LOWEST_PREMIUM * 100, AURORA_PREMIUM)

    for quote, (grade, capital, premium) in zip(quotes, CARRIERS):
        stored = read_quote(api, quote["id"])
        assert stored["composite_score_bp"] == (
            RATING_POINTS[grade] * W_RATING["SAFETY_WEIGHTED"]
            + capital_component(capital) * W_CAPITAL["SAFETY_WEIGHTED"]
            + price_component(LOWEST_PREMIUM, premium) * W_PRICE["SAFETY_WEIGHTED"]
        )


def test_the_cheapest_quote_loses_the_safety_weighted_sum_despite_full_price_points(api):
    """Full price points cannot rescue the weakest rating and capital under safety weights.

    PRD: "The `composite_score_bp` is then the rating points multiplied by the rating
    weight, plus the capital points multiplied by the capital weight, plus the price
    points multiplied by the price weight."

    PRD: "The winner is the candidate with the highest `composite_score_bp`; ties are
    broken by the lower `premium_cents`, then by the higher rating points, then by the
    earlier `submitted_at`, then by the earlier `created_at`."

    Design: Difficulty/combinatorial_formula/insurer_composite_score_nonlinear_in_premium
    """
    authorized = build_authorized_plan(api, participants=[ParticipantSpec(250000)])
    insurers = create_insurer_panel(api, PANEL)
    _aurora, _beacon, cardinal = insurers

    quoting = build_quoting_tranche(api, authorized.plan_id, authorized.participants)
    quotes = collect_quotes(api, quoting.tranche_id, _panel_quotes(insurers))

    selected = select_insurer(api, quoting.tranche_id, "SAFETY_WEIGHTED")

    beacon_quote = read_quote(api, quotes[1]["id"])
    cardinal_quote = read_quote(api, quotes[2]["id"])

    assert price_component(LOWEST_PREMIUM, BEACON_PREMIUM) == 100
    assert beacon_quote["composite_score_bp"] == (
        RATING_POINTS["AA_MINUS"] * W_RATING["SAFETY_WEIGHTED"]
        + capital_component(3800) * W_CAPITAL["SAFETY_WEIGHTED"]
        + 100 * W_PRICE["SAFETY_WEIGHTED"]
    )
    assert beacon_quote["composite_score_bp"] < cardinal_quote["composite_score_bp"]
    assert selected["selected_quote_id"] == cardinal_quote["id"]
    assert selected["selected_insurer_id"] == cardinal["id"]
    assert selected["selection_score_bp"] == cardinal_quote["composite_score_bp"]


# ---------------------------------------------------------------------------
# Design: Difficulty/cross_entity_state_dependency/insurer_selection_gated_on_opinion_verdict_not_opinion_existence
# ---------------------------------------------------------------------------


def _quoting_tranche_with_engaged_expert_only(api):
    authorized = build_authorized_plan(
        api,
        participants=[ParticipantSpec(250000)],
        expert_opinion=None,
        expert_firm_name="Thornbury Actuarial Consulting",
    )
    insurer = create_insurer_panel(api, (PANEL[1],))[0]
    quoting = build_quoting_tranche(api, authorized.plan_id, authorized.participants)
    quotes = collect_quotes(
        api, quoting.tranche_id, [QuoteSpec(insurer["id"], BEACON_PREMIUM, 90, 60)]
    )
    return authorized, insurer, quoting, quotes[0]


def test_an_engaged_expert_opens_quoting_but_cannot_carry_the_selection(api):
    """Quoting accepts an engaged expert; selection demands an affirmative opinion.

    PRD: "And at least one independent expert of the plan must be in `ENGAGED` or
    `OPINION_ISSUED`, else `ERR_EXPERT_STATE_INVALID`."

    PRD: "At least one independent expert of the plan must be in `OPINION_ISSUED`
    with a `safest_available_opinion` of `AFFIRMATIVE`; a qualified or adverse
    opinion, or no opinion at all, is rejected with `ERR_EXPERT_OPINION_REQUIRED`."

    Design: Difficulty/cross_entity_state_dependency/insurer_selection_gated_on_opinion_verdict_not_opinion_existence
    """
    authorized, _insurer, quoting, quote = _quoting_tranche_with_engaged_expert_only(api)

    assert read_expert(api, authorized.expert["id"])["expert_status"] == "ENGAGED"
    assert quoting.tranche["tranche_status"] == "QUOTING"

    response = api.post_insurer_selection(
        quoting.tranche_id, {"selection_basis": "SAFETY_WEIGHTED"}, fiduciary_headers()
    )
    validate_error(response, api_errors.ERR_EXPERT_OPINION_REQUIRED)

    unchanged = read_tranche(api, quoting.tranche_id)
    assert unchanged["tranche_status"] == "QUOTING"
    assert unchanged["selected_quote_id"] is None
    assert unchanged["selected_insurer_id"] is None
    assert unchanged["selection_score_bp"] is None
    assert read_quote(api, quote["id"])["quote_status"] == "SUBMITTED"


def test_an_adverse_opinion_satisfies_the_status_yet_still_blocks_the_selection(api):
    """The operative predicate is the verdict field, not the expert's status.

    PRD: "At least one independent expert of the plan must be in `OPINION_ISSUED`
    with a `safest_available_opinion` of `AFFIRMATIVE`; a qualified or adverse
    opinion, or no opinion at all, is rejected with `ERR_EXPERT_OPINION_REQUIRED`."

    Design: Difficulty/cross_entity_state_dependency/insurer_selection_gated_on_opinion_verdict_not_opinion_existence
    """
    authorized, _insurer, quoting, quote = _quoting_tranche_with_engaged_expert_only(api)

    adverse = issue_opinion(api, authorized.expert["id"], "ADVERSE")
    assert adverse["expert_status"] == "OPINION_ISSUED"
    assert adverse["safest_available_opinion"] == "ADVERSE"

    response = api.post_insurer_selection(
        quoting.tranche_id, {"selection_basis": "SAFETY_WEIGHTED"}, fiduciary_headers()
    )
    validate_error(response, api_errors.ERR_EXPERT_OPINION_REQUIRED)

    unchanged = read_tranche(api, quoting.tranche_id)
    assert unchanged["tranche_status"] == "QUOTING"
    assert unchanged["selected_insurer_id"] is None
    assert read_quote(api, quote["id"])["quote_status"] == "SUBMITTED"


def test_one_affirmative_opinion_unblocks_selection_while_a_dissent_remains_attached(api):
    """The gate is existential over the plan's experts, so one dissent does not veto.

    PRD: "At least one independent expert of the plan must be in `OPINION_ISSUED`
    with a `safest_available_opinion` of `AFFIRMATIVE`; a qualified or adverse
    opinion, or no opinion at all, is rejected with `ERR_EXPERT_OPINION_REQUIRED`."

    Design: Difficulty/cross_entity_state_dependency/insurer_selection_gated_on_opinion_verdict_not_opinion_existence
    """
    authorized, insurer, quoting, quote = _quoting_tranche_with_engaged_expert_only(api)
    issue_opinion(api, authorized.expert["id"], "ADVERSE")

    second = create_expert(api, authorized.plan_id, "Kestrel Independent Advisors")
    review_expert(api, second["id"], "ENGAGE")
    affirmative = issue_opinion(api, second["id"], "AFFIRMATIVE")
    assert affirmative["safest_available_opinion"] == "AFFIRMATIVE"

    selected = select_insurer(api, quoting.tranche_id, "SAFETY_WEIGHTED")

    expected = composite_score_bp(
        "SAFETY_WEIGHTED", "AA_MINUS", 3800, BEACON_PREMIUM, BEACON_PREMIUM
    )
    assert selected["tranche_status"] == "INSURER_SELECTED"
    assert selected["selected_insurer_id"] == insurer["id"]
    assert selected["selected_quote_id"] == quote["id"]
    assert selected["selection_score_bp"] == expected

    dissenting = read_expert(api, authorized.expert["id"])
    assert dissenting["expert_status"] == "OPINION_ISSUED"
    assert dissenting["safest_available_opinion"] == "ADVERSE"
