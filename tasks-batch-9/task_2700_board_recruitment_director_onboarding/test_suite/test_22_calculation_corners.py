"""Corner cases of the computed reads: policy selection, gap population, ballot
tallies, the compensation waterfall and the ordered compliance legs."""
from prd_bench_local_runner.testing import validate_success

from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers.assertions import (
    assert_fields_equal,
    assert_gap_row,
    assert_slate_tallies,
)
from test_helpers.test_users import (
    SECRETARY,
    STAFF,
    make_committee_chair_headers,
    make_committee_member_headers,
)

# ---------------------------------------------------------------------------
# Two policies adopted in sequence: the first is flipped to SUPERSEDED by the
# second, and only the surviving row may be consulted for a threshold.
# ---------------------------------------------------------------------------
POLICY_A_EFFECTIVE_FROM = "2026-01-01T00:00:00Z"
POLICY_B_EFFECTIVE_FROM = "2026-06-01T00:00:00Z"
QUORUM_SIZE_SUPERSEDED = 3  # would refuse a single-ballot decision
QUORUM_SIZE_SURVIVING = 1  # admits a single-ballot decision
SINGLE_BALLOT_APPROVAL_PCT = 100.00

# ---------------------------------------------------------------------------
# Skills matrix: CYBER carries strategic_weight 0.80, requires two covered
# directors and is risk-oversight flagged, so one missing director weighs
# 1 * 0.80 * 1.5 == 1.20.
# ---------------------------------------------------------------------------
CYBER_WEIGHT = 0.80
CYBER_REQUIRED_MIN_DIRECTORS = 2
CYBER_COVERED_WEIGHTED_GAP = 0.00
CYBER_MINOR_WEIGHTED_GAP = 1.20
SELF_RATING_COVERING = 4  # at or above 3, so it covers the category

# FINANCE carries strategic_weight 1.00, requires one covered director and is
# not risk-oversight flagged, so a single self-rating of 4 leaves no gap.
FINANCE_COVERED_WEIGHTED_GAP = 0.00
FINANCE_BOARD_GAP_INDEX = 0.00

# ---------------------------------------------------------------------------
# Ballot tally: FOR, FOR, AGAINST and RECUSED.  Four CAST ballots clear the
# default quorum_size of 3, while the approval denominator is the three
# non-recused ballots, giving 66.67 rather than the 50.00 that dividing by all
# four would produce.
# ---------------------------------------------------------------------------
TALLY_APPROVAL_PCT = 66.67
TALLY_APPROVAL_PCT_IF_RECUSAL_COUNTED = 50.00

# ---------------------------------------------------------------------------
# Compensation offset tier ceiling at 30000000 cents, which is inclusive.
# A full calendar year is 365 service days, so the retainer prorates whole.
# ---------------------------------------------------------------------------
FULL_YEAR_SERVICE_DAYS = 365
EQUITY_GRANT_CENTS = 20000000
RETAINER_AT_CEILING_CENTS = 10000000
PRE_OFFSET_AT_CEILING_CENTS = 30000000  # 10000000 + 0 + 20000000
TOTAL_AT_CEILING_CENTS = 30000000  # a 0.0 percent offset takes nothing
OWNERSHIP_REQUIREMENT_AT_CEILING_CENTS = 50000000  # 5.0 x cash of 10000000
RETAINER_OVER_CEILING_CENTS = 10000100  # one hundred cents more
PRE_OFFSET_OVER_CEILING_CENTS = 30000100
OFFSET_OVER_CEILING_CENTS = 750003  # round_half_up(750002.5)
TOTAL_OVER_CEILING_CENTS = 29250097
OWNERSHIP_REQUIREMENT_OVER_CEILING_CENTS = 50000500
SHARE_PRICE_CENTS = 90000
SHARES_HELD_COMPLIANT = 600
OWNERSHIP_ACTUAL_COMPLIANT_CENTS = 54000000  # 600 x 90000

# ---------------------------------------------------------------------------
# Proration rounds half up in both directions against the 12000000 retainer.
# 300 days give 9863013.6986 and 200 days give 6575342.4657.
# ---------------------------------------------------------------------------
SERVICE_DAYS_ROUNDING_UP = 300
PRORATED_ROUNDED_UP_CENTS = 9863014
PRORATED_IF_TRUNCATED_CENTS = 9863013
PRE_OFFSET_ROUNDING_UP_CENTS = 29863014
OWNERSHIP_REQUIREMENT_ROUNDING_UP_CENTS = 49315070
SHARES_HELD_ROUNDING_UP = 550
OWNERSHIP_ACTUAL_ROUNDING_UP_CENTS = 49500000

SERVICE_DAYS_ROUNDING_DOWN = 200
PRORATED_ROUNDED_DOWN_CENTS = 6575342
PRORATED_IF_ROUNDED_AWAY_CENTS = 6575343
PRE_OFFSET_ROUNDING_DOWN_CENTS = 26575342
OWNERSHIP_REQUIREMENT_ROUNDING_DOWN_CENTS = 32876710
SHARES_HELD_ROUNDING_DOWN = 400
OWNERSHIP_ACTUAL_ROUNDING_DOWN_CENTS = 36000000

# ---------------------------------------------------------------------------
# Compliance legs: a director on four outside public boards holding only 100
# shares.  The award nets 31200000 from a pre-offset total of 32000000 less the
# 2.5 percent tier, and its ownership requirement of 60000000 is unmet.
# ---------------------------------------------------------------------------
SHARES_HELD_SHORTFALL = 100
PRE_OFFSET_SHORTFALL_CENTS = 32000000  # 12000000 + 0 + 20000000
OFFSET_SHORTFALL_CENTS = 800000  # 2.5 percent of 32000000
TOTAL_SHORTFALL_CENTS = 31200000
OWNERSHIP_REQUIREMENT_SHORTFALL_CENTS = 60000000  # 5.0 x cash of 12000000
OWNERSHIP_ACTUAL_SHORTFALL_CENTS = 9000000  # 100 x 90000
BOARDS_AT_OVERBOARDED = 4
BOARDS_AFTER_ENDING_ONE = 3

FULL_YEAR_START = "2026-01-01"
FULL_YEAR_END = "2026-12-31"


def _cast_ballot(client, slate_id, voting_director_id, ballot, headers):
    """Cast one ballot and assert the 201 a ballot creation returns."""
    return validate_success(
        client.cast_vote(slate_id, F.vote_payload(voting_director_id, ballot), headers), 201
    )


def _chair_and_incumbent(client):
    """One seated independent chair plus one seated independent incumbent."""
    chair = X.new_seated_director(
        client,
        full_name="Dana Chair",
        email="dana.chair@issuer.example",
        birth_date="1962-03-15",
        appointed_on="2019-05-01",
        is_independent=True,
    )
    incumbent = X.new_seated_director(
        client,
        full_name="Ida Incumbent",
        email="ida@issuer.example",
        birth_date="1968-01-01",
        appointed_on="2021-01-01",
        is_independent=True,
    )
    return chair, incumbent


def _full_year_award(client, director_id, shares_held):
    return X.new_comp_award(
        client,
        director_id,
        cycle_year=2026,
        service_start_on=FULL_YEAR_START,
        service_end_on=FULL_YEAR_END,
        share_price_cents=SHARE_PRICE_CENTS,
        shares_held=shares_held,
    )


def test_the_superseded_policy_row_is_never_read_for_the_quorum_threshold(client):
    """A second adoption supersedes the first, so a slate decided on one ballot is
    approved under the surviving quorum_size of 1 instead of the superseded 3.

    PRD: "The eligible set is the `GovernancePolicy` rows whose `status` is `ACTIVE`; rows whose `status` is `SUPERSEDED` are never consulted for any purpose."

    Design: Corner/calculations/active_policy_selector_never_consults_a_superseded_row
    """
    policy_a = X.adopt_policy(
        client,
        effective_from=POLICY_A_EFFECTIVE_FROM,
        quorum_size=QUORUM_SIZE_SUPERSEDED,
    )
    policy_b = X.adopt_policy(
        client,
        effective_from=POLICY_B_EFFECTIVE_FROM,
        quorum_size=QUORUM_SIZE_SURVIVING,
    )
    chair, incumbent = _chair_and_incumbent(client)
    chair_headers = make_committee_chair_headers(chair["id"])
    slate = X.new_slate(client, cycle_year=2026, seat_count=9)
    X.add_incumbent_nominee(client, slate["id"], incumbent["id"], 1)
    X.submit_slate(client, slate["id"])
    _cast_ballot(client, slate["id"], chair["id"], "FOR", chair_headers)

    decided = X.decide_slate(client, slate["id"], chair_headers, decision="APPROVE")

    assert validate_success(client.get_policy(policy_a["id"], SECRETARY))["status"] == "SUPERSEDED"
    assert validate_success(client.get_policy(policy_b["id"], SECRETARY))["status"] == "ACTIVE"
    assert decided["status"] == "APPROVED"
    assert_fields_equal(
        X.get_slate(client, slate["id"]),
        {
            "status": "APPROVED",
            "quorum_met": True,
            "approval_pct": SINGLE_BALLOT_APPROVAL_PCT,
        },
    )


def test_a_resigned_director_drops_out_of_the_gap_analysis_coverage_count(client):
    """A resignation removes the director from the gap-analysis population, so CYBER
    falls from COVERED to MINOR_GAP while the resigned director's rating row survives.

    PRD: "The population is the directors whose `service_status` is `SEATED` or `ONBOARDING`; directors who are `RETIREMENT_NOTICED`, `RETIRED`, `RESIGNED` or `NOT_RENOMINATED` are excluded entirely."

    Design: Corner/calculations/skills_gap_analysis_drops_a_resigned_director_from_the_coverage_count
    """
    X.adopt_policy(client)
    category = X.new_skill_category(
        client,
        code="CYBER",
        name="Cybersecurity Oversight",
        strategic_weight=CYBER_WEIGHT,
        required_min_directors=CYBER_REQUIRED_MIN_DIRECTORS,
        risk_oversight=True,
        criticality="CORE",
    )
    stays = X.new_seated_director(
        client, full_name="Stay Put", email="stay@issuer.example", birth_date="1970-01-01",
        appointed_on="2021-01-01",
    )
    leaves = X.new_seated_director(
        client, full_name="Leaves Soon", email="leaves@issuer.example", birth_date="1971-01-01",
        appointed_on="2021-01-01",
    )
    X.record_rating(client, stays["id"], category["id"], SELF_RATING_COVERING)
    leaving_rating = X.record_rating(
        client, leaves["id"], category["id"], SELF_RATING_COVERING
    )

    before = X.get_gap_analysis(client)
    X.record_departure(client, leaves["id"], notice_type="RESIGNATION")
    after = X.get_gap_analysis(client)

    assert_fields_equal(
        before,
        {
            "seated_director_count": 2,
            "category_count": 1,
            "board_gap_index": CYBER_COVERED_WEIGHTED_GAP,
            "priority_category_code": "CYBER",
        },
    )
    assert_gap_row(before, "CYBER", 2, 0, CYBER_COVERED_WEIGHTED_GAP, "COVERED")
    assert X.get_director(client, leaves["id"])["service_status"] == "RESIGNED"
    assert_fields_equal(
        after,
        {"seated_director_count": 1, "board_gap_index": CYBER_MINOR_WEIGHTED_GAP},
    )
    assert_gap_row(after, "CYBER", 1, 1, CYBER_MINOR_WEIGHTED_GAP, "MINOR_GAP")
    assert X.get_rating(client, leaving_rating["id"])["self_rating"] == SELF_RATING_COVERING


def test_a_recused_ballot_counts_for_quorum_but_leaves_the_approval_denominator(client):
    """Four CAST ballots meet quorum while the recused one is struck from the approval
    denominator, so two FOR out of three counted ballots reads 66.67 and approves.

    PRD: "The approval denominator, by contrast, excludes recusals: it is `votes_for` plus `votes_against` plus `votes_abstain`."

    Design: Corner/calculations/committee_vote_tally_keeps_a_recused_ballot_in_quorum_and_out_of_approval
    """
    X.adopt_policy(client)
    chair = X.new_seated_director(
        client, full_name="Cora Chair", email="cora@issuer.example", birth_date="1962-01-01",
        appointed_on="2019-01-01", is_independent=True,
    )
    member_for = X.new_seated_director(
        client, full_name="Mo Member", email="mo@issuer.example", birth_date="1965-01-01",
        appointed_on="2020-01-01", is_independent=True,
    )
    member_against = X.new_seated_director(
        client, full_name="Nia Member", email="nia@issuer.example", birth_date="1966-01-01",
        appointed_on="2020-01-01", is_independent=True,
    )
    nominee_director = X.new_seated_director(
        client, full_name="Rex Recused", email="rex@issuer.example", birth_date="1968-01-01",
        appointed_on="2021-01-01", is_independent=True,
    )
    other_nominee_director = X.new_seated_director(
        client, full_name="Ned Nominee", email="ned@issuer.example", birth_date="1969-01-01",
        appointed_on="2021-01-01", is_independent=True,
    )
    chair_headers = make_committee_chair_headers(chair["id"])
    slate = X.new_slate(client, cycle_year=2026, seat_count=9)
    nominee_row = X.add_incumbent_nominee(client, slate["id"], nominee_director["id"], 1)
    X.add_incumbent_nominee(client, slate["id"], other_nominee_director["id"], 2)
    X.submit_slate(client, slate["id"])

    ballot_chair = _cast_ballot(client, slate["id"], chair["id"], "FOR", chair_headers)
    _cast_ballot(
        client, slate["id"], member_for["id"], "FOR",
        make_committee_member_headers(member_for["id"]),
    )
    ballot_recused = _cast_ballot(
        client, slate["id"], nominee_director["id"], "RECUSED",
        make_committee_member_headers(nominee_director["id"]),
    )
    ballot_against = _cast_ballot(
        client, slate["id"], member_against["id"], "AGAINST",
        make_committee_member_headers(member_against["id"]),
    )
    decided = X.decide_slate(client, slate["id"], chair_headers, decision="APPROVE")

    assert_slate_tallies(
        X.get_slate(client, slate["id"]),
        votes_for=2,
        votes_against=1,
        votes_abstain=0,
        votes_recused=1,
        approval_pct=TALLY_APPROVAL_PCT,
        quorum_met=True,
    )
    assert X.get_slate(client, slate["id"])["approval_pct"] != TALLY_APPROVAL_PCT_IF_RECUSAL_COUNTED
    assert_fields_equal(
        ballot_recused, {"ballot": "RECUSED", "recusal_required": True}
    )
    assert nominee_row["incumbent_director_id"] == nominee_director["id"]
    assert ballot_chair["recusal_required"] is False
    assert ballot_against["recusal_required"] is False
    assert decided["status"] == "APPROVED"


def test_a_pre_offset_total_of_exactly_thirty_million_draws_no_offset(client):
    """A pre-offset total sitting exactly on 30000000 keeps the 0.0 percent tier, while one
    hundred cents above the same figure draws 2.5 percent and an offset of 750003.

    PRD: "it is 0.0 when the `pre_offset_total_cents` is at or below 30000000 cents, 2.5 when it is above that and at or below 40000000 cents, and 5.0 when it is above 40000000 cents."

    Design: Corner/calculations/comp_award_offset_tier_ceiling_is_inclusive_at_thirty_million_cents
    """
    X.adopt_policy(
        client,
        effective_from=POLICY_A_EFFECTIVE_FROM,
        annual_cash_retainer_cents=RETAINER_AT_CEILING_CENTS,
        equity_grant_value_cents=EQUITY_GRANT_CENTS,
    )
    at_ceiling = X.new_seated_director(
        client, full_name="Cap Exact", email="capexact@issuer.example",
        birth_date="1968-01-01", appointed_on="2019-01-01",
        shares_held=SHARES_HELD_COMPLIANT,
    )
    over_ceiling = X.new_seated_director(
        client, full_name="Cap Over", email="capover@issuer.example",
        birth_date="1969-01-01", appointed_on="2019-01-01",
        shares_held=SHARES_HELD_COMPLIANT,
    )

    award_at = _full_year_award(client, at_ceiling["id"], SHARES_HELD_COMPLIANT)
    X.adopt_policy(
        client,
        effective_from="2026-02-01T00:00:00Z",
        annual_cash_retainer_cents=RETAINER_OVER_CEILING_CENTS,
        equity_grant_value_cents=EQUITY_GRANT_CENTS,
    )
    award_over = _full_year_award(client, over_ceiling["id"], SHARES_HELD_COMPLIANT)

    assert_fields_equal(
        award_at,
        {
            "service_days": FULL_YEAR_SERVICE_DAYS,
            "prorated_cash_retainer_cents": RETAINER_AT_CEILING_CENTS,
            "committee_fees_cents": 0,
            "equity_value_cents": EQUITY_GRANT_CENTS,
            "pre_offset_total_cents": PRE_OFFSET_AT_CEILING_CENTS,
            "excess_offset_pct": 0.0,
            "excess_offset_cents": 0,
            "total_cents": TOTAL_AT_CEILING_CENTS,
            "ownership_requirement_cents": OWNERSHIP_REQUIREMENT_AT_CEILING_CENTS,
            "ownership_actual_cents": OWNERSHIP_ACTUAL_COMPLIANT_CENTS,
            "ownership_compliant": True,
        },
    )
    assert_fields_equal(
        award_over,
        {
            "prorated_cash_retainer_cents": RETAINER_OVER_CEILING_CENTS,
            "pre_offset_total_cents": PRE_OFFSET_OVER_CEILING_CENTS,
            "excess_offset_pct": 2.5,
            "excess_offset_cents": OFFSET_OVER_CEILING_CENTS,
            "total_cents": TOTAL_OVER_CEILING_CENTS,
            "ownership_requirement_cents": OWNERSHIP_REQUIREMENT_OVER_CEILING_CENTS,
            "ownership_compliant": True,
        },
    )


def test_a_three_hundred_day_window_prorates_the_retainer_upwards(client):
    """Three hundred service days give an exact quotient of 9863013.6986, which must land on
    9863014 rather than the 9863013 a truncation would keep.

    PRD: "The `prorated_cash_retainer_cents` is the policy's `annual_cash_retainer_cents` multiplied by the `service_days` and divided by 365, rounded half up to whole cents."

    Design: Corner/calculations/comp_award_proration_rounds_half_up_in_both_directions
    """
    X.adopt_policy(client, effective_from=POLICY_A_EFFECTIVE_FROM)
    director = X.new_seated_director(
        client, full_name="Round Up", email="roundup@issuer.example",
        birth_date="1968-01-01", appointed_on="2019-01-01",
        shares_held=SHARES_HELD_ROUNDING_UP,
    )

    award = X.new_comp_award(
        client,
        director["id"],
        cycle_year=2026,
        service_start_on=FULL_YEAR_START,
        service_end_on="2026-10-27",
        share_price_cents=SHARE_PRICE_CENTS,
        shares_held=SHARES_HELD_ROUNDING_UP,
    )

    assert_fields_equal(
        award,
        {
            "service_days": SERVICE_DAYS_ROUNDING_UP,
            "prorated_cash_retainer_cents": PRORATED_ROUNDED_UP_CENTS,
            "pre_offset_total_cents": PRE_OFFSET_ROUNDING_UP_CENTS,
            "excess_offset_pct": 0.0,
            "total_cents": PRE_OFFSET_ROUNDING_UP_CENTS,
            "ownership_requirement_cents": OWNERSHIP_REQUIREMENT_ROUNDING_UP_CENTS,
            "ownership_actual_cents": OWNERSHIP_ACTUAL_ROUNDING_UP_CENTS,
            "ownership_compliant": True,
        },
    )
    assert award["prorated_cash_retainer_cents"] != PRORATED_IF_TRUNCATED_CENTS


def test_a_two_hundred_day_window_prorates_the_retainer_downwards(client):
    """Two hundred service days give an exact quotient of 6575342.4657, which must land on
    6575342 rather than the 6575343 that rounding away from zero would give.

    PRD: "The `prorated_cash_retainer_cents` is the policy's `annual_cash_retainer_cents` multiplied by the `service_days` and divided by 365, rounded half up to whole cents."

    Design: Corner/calculations/comp_award_proration_rounds_half_up_in_both_directions
    """
    X.adopt_policy(client, effective_from=POLICY_A_EFFECTIVE_FROM)
    director = X.new_seated_director(
        client, full_name="Round Down", email="rounddown@issuer.example",
        birth_date="1969-01-01", appointed_on="2019-01-01",
        shares_held=SHARES_HELD_ROUNDING_DOWN,
    )

    award = X.new_comp_award(
        client,
        director["id"],
        cycle_year=2026,
        service_start_on=FULL_YEAR_START,
        service_end_on="2026-07-19",
        share_price_cents=SHARE_PRICE_CENTS,
        shares_held=SHARES_HELD_ROUNDING_DOWN,
    )

    assert_fields_equal(
        award,
        {
            "service_days": SERVICE_DAYS_ROUNDING_DOWN,
            "prorated_cash_retainer_cents": PRORATED_ROUNDED_DOWN_CENTS,
            "pre_offset_total_cents": PRE_OFFSET_ROUNDING_DOWN_CENTS,
            "total_cents": PRE_OFFSET_ROUNDING_DOWN_CENTS,
            "ownership_requirement_cents": OWNERSHIP_REQUIREMENT_ROUNDING_DOWN_CENTS,
            "ownership_actual_cents": OWNERSHIP_ACTUAL_ROUNDING_DOWN_CENTS,
            "ownership_compliant": True,
        },
    )
    assert award["prorated_cash_retainer_cents"] != PRORATED_IF_ROUNDED_AWAY_CENTS


def test_a_gap_analysis_read_without_a_variant_scores_the_self_reported_rating(client):
    """Omitting the variant echoes SELF_REPORTED and counts an UNVALIDATED self-rating of 4 as
    covering FINANCE, matching the explicitly requested SELF_REPORTED read figure for figure.

    PRD: "it runs in one of two variants selected by the `variant` query parameter: `SELF_REPORTED`, which is the default, or `VALIDATED_ONLY`."

    Design: Corner/calculations/gap_analysis_omitted_variant_parameter_defaults_to_self_reported
    """
    X.adopt_policy(client, effective_from=POLICY_A_EFFECTIVE_FROM)
    category = X.new_skill_category(
        client,
        code="FINANCE",
        name="Financial Expertise",
        strategic_weight=1.00,
        required_min_directors=1,
        risk_oversight=False,
        criticality="CORE",
    )
    director = X.new_seated_director(
        client, full_name="Self Rater", email="selfrater@issuer.example",
        birth_date="1970-01-01", appointed_on="2021-01-01",
    )
    rating = X.record_rating(client, director["id"], category["id"], SELF_RATING_COVERING)

    defaulted = X.get_gap_analysis(client)
    explicit = X.get_gap_analysis(client, variant="SELF_REPORTED")

    assert defaulted["variant"] == "SELF_REPORTED"
    for analysis in (defaulted, explicit):
        assert_fields_equal(
            analysis,
            {
                "seated_director_count": 1,
                "category_count": 1,
                "board_gap_index": FINANCE_BOARD_GAP_INDEX,
                "priority_category_code": "FINANCE",
            },
        )
        assert_gap_row(analysis, "FINANCE", 1, 0, FINANCE_COVERED_WEIGHTED_GAP, "COVERED")
    assert_fields_equal(
        X.get_rating(client, rating["id"]),
        {
            "validation_status": "UNVALIDATED",
            "validated_rating": None,
            "effective_rating": SELF_RATING_COVERING,
        },
    )


# The four outside seats are recorded while the governing limit is 5, so the seats
# themselves are admissible; the limit then tightens to 4 and the overboarding leg
# bites on a count of 4, because 4 plus this board is strictly greater than 4.
MAX_BOARDS_PERMISSIVE = 5


def test_an_overboarded_director_reports_overboarding_before_the_ownership_shortfall(client):
    """A director on four outside public boards whose finalized award is short of its ownership
    requirement reports OVERBOARDED, and only ending one seat exposes OWNERSHIP_SHORTFALL.

    PRD: "Because the legs are ordered, an overboarded director who also has an ownership shortfall reports `OVERBOARDED`, and the shortfall becomes visible only once the outside seat is ended."

    Design: Corner/calculations/compliance_leg_order_puts_overboarded_ahead_of_ownership_shortfall
    """
    X.adopt_policy(
        client,
        effective_from=POLICY_A_EFFECTIVE_FROM,
        max_public_boards_default=MAX_BOARDS_PERMISSIVE,
    )
    director = X.new_seated_director(
        client, full_name="Ollie Overboard", email="ollie@issuer.example",
        birth_date="1968-01-01", appointed_on="2019-01-01",
        shares_held=SHARES_HELD_SHORTFALL,
    )
    companies = X.new_public_companies(client, BOARDS_AT_OVERBOARDED)
    seats = X.give_director_boards(client, director["id"], [c["id"] for c in companies])
    X.adopt_policy(client, effective_from="2026-02-01T00:00:00Z")
    award = _full_year_award(client, director["id"], SHARES_HELD_SHORTFALL)

    finalized = X.finalize_award(client, award["id"])
    overboarded = X.get_director(client, director["id"])
    validate_success(
        client.end_external_directorship(
            seats[-1]["id"], F.end_directorship_payload(end_on="2026-07-31"), STAFF
        )
    )
    after_ending_a_seat = X.get_director(client, director["id"])

    assert_fields_equal(
        finalized,
        {
            "status": "FINALIZED",
            "pre_offset_total_cents": PRE_OFFSET_SHORTFALL_CENTS,
            "excess_offset_cents": OFFSET_SHORTFALL_CENTS,
            "total_cents": TOTAL_SHORTFALL_CENTS,
            "ownership_requirement_cents": OWNERSHIP_REQUIREMENT_SHORTFALL_CENTS,
            "ownership_actual_cents": OWNERSHIP_ACTUAL_SHORTFALL_CENTS,
            "ownership_compliant": False,
        },
    )
    assert_fields_equal(
        overboarded,
        {
            "external_public_board_count": BOARDS_AT_OVERBOARDED,
            "compliance_status": "OVERBOARDED",
        },
    )
    assert_fields_equal(
        after_ending_a_seat,
        {
            "external_public_board_count": BOARDS_AFTER_ENDING_ONE,
            "compliance_status": "OWNERSHIP_SHORTFALL",
        },
    )
