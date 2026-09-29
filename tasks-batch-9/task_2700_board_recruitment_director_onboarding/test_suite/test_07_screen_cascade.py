"""A supplemental re-screen that goes adverse, and the five entity hops it moves.

One determine call on a re-screen opened against a sitting nominee travels from
the screen to the candidate, to that candidate's nominee row, to the owning
slate and the sourcing firm's fee ledger, and finally to every ballot already
cast on the slate.  Each hop is asserted on its own.
"""
from prd_bench_local_runner.testing import is_iso8601_timestamp, validate_success

from test_helpers import fixtures as X
from test_helpers.assertions import (
    assert_fields_equal,
    assert_firm_ledger,
    assert_slate_tallies,
)
from test_helpers.test_users import (
    STAFF,
    make_committee_chair_headers,
    make_committee_member_headers,
)

# The firm's tier-1 percentage and the candidate's target pay, stated as the
# literals the fee arithmetic is built from.
PLACEMENT_FEE_PCT = 27.5
PLACEMENT_FEE_TIER2_PCT = 22.5
RETAINER_FEE_CENTS = 5000000
TARGET_ANNUAL_COMP_CENTS = 35000020

# 27.5 percent of 35000020 cents is 9625005.5, which rounds half up to this
# whole-cent figure; the retainer credit is the lesser of the retainer and it.
PLACEMENT_FEE_CENTS = 9625006
RETAINER_CREDIT_CENTS = 5000000
NET_PAYABLE_CENTS = 4625006

# Three ballots stand on the slate before the trigger: two FOR and one AGAINST,
# so 100 * 2 / 3 rounds half up to this approval percentage.
APPROVAL_PCT_BEFORE = 66.67

# The slate keeps nine seats standing for election, well above the two nominees.
SLATE_SEAT_COUNT = 9

# Only one completed interview is demanded, so the pipeline stays short.
MIN_COMPLETED_INTERVIEWS = 1


def _cascade_world(client):
    """Build the world up to the moment before the supplemental determination.

    Returns every identifier the hops are asserted against.  On return the
    supplemental screen is `SUBMITTED` and nothing else has moved yet.
    """
    X.adopt_policy(client, min_completed_interviews=MIN_COMPLETED_INTERVIEWS)

    firm = X.new_search_firm(
        client,
        name="Aurora Board Search",
        contact_email="partners@aurora.example",
        fee_model="RETAINER",
        retainer_fee_cents=RETAINER_FEE_CENTS,
        placement_fee_pct=PLACEMENT_FEE_PCT,
        placement_fee_tier2_pct=PLACEMENT_FEE_TIER2_PCT,
    )

    chair = X.new_seated_director(
        client,
        full_name="Dana Chair",
        email="dana.chair@issuer.example",
        birth_date="1962-03-15",
        appointed_on="2019-05-01",
    )
    interviewer = X.new_seated_director(
        client,
        full_name="Ivan Interviewer",
        email="ivan@issuer.example",
        birth_date="1966-07-07",
        appointed_on="2020-05-01",
    )
    voter_one = X.new_seated_director(
        client,
        full_name="Vera Voter",
        email="vera@issuer.example",
        birth_date="1967-02-02",
        appointed_on="2021-05-01",
    )
    voter_two = X.new_seated_director(
        client,
        full_name="Victor Voter",
        email="victor@issuer.example",
        birth_date="1969-03-03",
        appointed_on="2022-05-01",
    )
    incumbent = X.new_seated_director(
        client,
        full_name="Iris Incumbent",
        email="iris@issuer.example",
        birth_date="1965-08-08",
        appointed_on="2020-01-01",
        is_independent=True,
    )
    chair_headers = make_committee_chair_headers(chair["id"])

    candidate = X.new_search_firm_candidate(
        client,
        firm["id"],
        full_name="Cara Cascade",
        email="cara@cand.example",
        birth_date="1972-04-02",
        target_annual_comp_cents=TARGET_ANNUAL_COMP_CENTS,
    )

    # First-pass screen: clean, so the candidate comes out INDEPENDENT.
    first_screen = X.screen_candidate(client, candidate["id"], chair_headers)
    X.run_interviews(client, candidate["id"], [interviewer["id"]], [4])
    X.record_reference_check(client, candidate["id"])
    X.run_conflict_clearance(client, candidate["id"], chair_headers)

    slate = X.new_slate(client, cycle_year=2026, seat_count=SLATE_SEAT_COUNT)
    candidate_nominee = X.add_candidate_nominee(client, slate["id"], candidate["id"], 1)
    incumbent_nominee = X.add_incumbent_nominee(client, slate["id"], incumbent["id"], 2)
    X.submit_slate(client, slate["id"])

    chair_ballot = X.cast_ballot(client, slate["id"], chair["id"], "FOR", chair_headers)
    ballot_one = X.cast_ballot(
        client,
        slate["id"],
        voter_one["id"],
        "FOR",
        make_committee_member_headers(voter_one["id"]),
    )
    ballot_two = X.cast_ballot(
        client,
        slate["id"],
        voter_two["id"],
        "AGAINST",
        make_committee_member_headers(voter_two["id"]),
    )

    # The supplemental re-screen: new information about a family employment
    # relationship, opened while the candidate is already NOMINATED.
    supplemental = X.open_screen(client, candidate["id"], family_member_employed=True)
    X.submit_screen(client, supplemental["id"])

    return {
        "chair_headers": chair_headers,
        "firm_id": firm["id"],
        "candidate_id": candidate["id"],
        "first_screen_id": first_screen["id"],
        "supplemental_id": supplemental["id"],
        "slate_id": slate["id"],
        "candidate_nominee_id": candidate_nominee["id"],
        "incumbent_nominee_id": incumbent_nominee["id"],
        "ballot_ids": [chair_ballot["id"], ballot_one["id"], ballot_two["id"]],
    }


def test_adverse_supplemental_determination_lands_on_the_screen_itself(client):
    """Hop one: the re-screen itself goes adverse, records its determination instant
    and the family-employment factor, while the candidate's earlier clean screen is
    left exactly as it was recorded.

    PRD: "The screen itself becomes `DETERMINED_NOT_INDEPENDENT` with `determination` `NOT_INDEPENDENT` and `determined_at` set."

    Design: Difficulty/transitive_cascade/supplemental_rescreen_not_independent_cascades_screen_to_candidate_to_nominee_to_slate_to_ballots
    """
    world = _cascade_world(client)

    determined = X.determine_screen(
        client, world["supplemental_id"], world["chair_headers"]
    )

    assert_fields_equal(
        determined,
        {
            "status": "DETERMINED_NOT_INDEPENDENT",
            "determination": "NOT_INDEPENDENT",
            "bright_line_fail_count": 1,
            "disqualifying_factor_code": "FAMILY_EMPLOYMENT",
        },
    )
    assert is_iso8601_timestamp(determined["determined_at"]), determined["determined_at"]
    assert_fields_equal(
        X.get_screen(client, world["first_screen_id"]),
        {"status": "DETERMINED_INDEPENDENT", "determination": "INDEPENDENT"},
    )


def test_adverse_supplemental_determination_rejects_the_nominated_candidate(client):
    """Hop two: the candidate was `NOMINATED` and `INDEPENDENT` right up to the
    determination, and the adverse screen rejects them with the independence reason.

    PRD: "the candidate's `independence_result` becomes `NOT_INDEPENDENT`, its `rejection_reason_code` becomes `INDEPENDENCE_FAILED`"

    Design: Difficulty/transitive_cascade/supplemental_rescreen_not_independent_cascades_screen_to_candidate_to_nominee_to_slate_to_ballots
    """
    world = _cascade_world(client)

    assert_fields_equal(
        X.get_candidate(client, world["candidate_id"]),
        {
            "status": "NOMINATED",
            "independence_result": "INDEPENDENT",
            "rejection_reason_code": None,
        },
    )

    X.determine_screen(client, world["supplemental_id"], world["chair_headers"])

    assert_fields_equal(
        X.get_candidate(client, world["candidate_id"]),
        {
            "status": "REJECTED",
            "independence_result": "NOT_INDEPENDENT",
            "rejection_reason_code": "INDEPENDENCE_FAILED",
        },
    )


def test_rejection_voids_only_the_rejected_candidates_nominee_row(client):
    """Hop three: the rejected candidate's live nominee row is voided with its instant
    recorded, while the incumbent renomination sharing the same slate stays `PROPOSED`.

    PRD: "every slate nominee row naming that candidate whose `status` is `PROPOSED` or `CONFIRMED` becomes `VOIDED` with `voided_at` set to the logical clock instant."

    Design: Difficulty/transitive_cascade/supplemental_rescreen_not_independent_cascades_screen_to_candidate_to_nominee_to_slate_to_ballots
    """
    world = _cascade_world(client)

    X.determine_screen(client, world["supplemental_id"], world["chair_headers"])

    voided = X.get_nominee(client, world["candidate_nominee_id"])
    assert_fields_equal(voided, {"status": "VOIDED"})
    assert is_iso8601_timestamp(voided["voided_at"]), voided["voided_at"]

    untouched = X.get_nominee(client, world["incumbent_nominee_id"])
    assert_fields_equal(untouched, {"status": "PROPOSED", "voided_at": None})


def test_the_slate_re_derives_its_rollups_and_returns_to_draft(client):
    """Hop four on the slate: the void takes the fee-bearing nominee out of the counted
    set, so the rollups fall back to the single incumbent, the committed search fee
    releases in full, and the slate under review returns to draft one revision on.

    PRD: "each affected slate re-derives `nominee_count`, `independent_nominee_count`, `independent_nominee_pct`, `independence_shortfall`, `committed_search_fee_cents`, `contested` and `universal_proxy_applicable`"

    Design: Difficulty/transitive_cascade/supplemental_rescreen_not_independent_cascades_screen_to_candidate_to_nominee_to_slate_to_ballots
    """
    world = _cascade_world(client)

    assert_fields_equal(
        X.get_slate(client, world["slate_id"]),
        {
            "status": "COMMITTEE_REVIEW",
            "nominee_count": 2,
            "committed_search_fee_cents": PLACEMENT_FEE_CENTS,
            "revision_count": 0,
        },
    )

    X.determine_screen(client, world["supplemental_id"], world["chair_headers"])

    assert_fields_equal(
        X.get_slate(client, world["slate_id"]),
        {
            "status": "DRAFT",
            "revision_count": 1,
            "nominee_count": 1,
            "independent_nominee_count": 1,
            "independent_nominee_pct": 100.00,
            "independence_shortfall": False,
            "committed_search_fee_cents": 0,
        },
    )


def test_the_sourcing_firms_fee_ledger_returns_to_zero(client):
    """Hop four on the firm: the ledger carried the whole placement fee, its retainer
    credit and the net payable while the nominee stood, and every figure returns to
    zero once the cascade voids that nominee.

    PRD: "each sourcing search firm re-derives `placed_nominee_count`, `committed_fee_cents`, `retainer_credit_applied_cents` and `net_payable_cents`"

    Design: Difficulty/transitive_cascade/supplemental_rescreen_not_independent_cascades_screen_to_candidate_to_nominee_to_slate_to_ballots
    """
    world = _cascade_world(client)

    assert_firm_ledger(
        X.get_firm(client, world["firm_id"]),
        placed_nominee_count=1,
        committed_fee_cents=PLACEMENT_FEE_CENTS,
        retainer_credit_applied_cents=RETAINER_CREDIT_CENTS,
        net_payable_cents=NET_PAYABLE_CENTS,
    )

    X.determine_screen(client, world["supplemental_id"], world["chair_headers"])

    assert_firm_ledger(
        X.get_firm(client, world["firm_id"]),
        placed_nominee_count=0,
        committed_fee_cents=0,
        retainer_credit_applied_cents=0,
        net_payable_cents=0,
    )


def test_every_cast_ballot_is_voided_and_the_tallies_reset(client):
    """Hop five: because the slate went back to draft underneath the review, all three
    ballots are voided by the revision and the slate's tally, approval percentage and
    quorum flag are re-derived over an empty set of cast ballots.

    PRD: "every ballot on it whose `status` is `CAST` becomes `VOIDED_BY_REVISION`, and that slate's `votes_for`, `votes_against`, `votes_abstain`, `votes_recused`, `approval_pct` and `quorum_met` are re-derived from the ballots that remain `CAST`"

    Design: Difficulty/transitive_cascade/supplemental_rescreen_not_independent_cascades_screen_to_candidate_to_nominee_to_slate_to_ballots
    """
    world = _cascade_world(client)

    assert_slate_tallies(
        X.get_slate(client, world["slate_id"]),
        votes_for=2,
        votes_against=1,
        votes_abstain=0,
        votes_recused=0,
        approval_pct=APPROVAL_PCT_BEFORE,
        quorum_met=True,
    )

    X.determine_screen(client, world["supplemental_id"], world["chair_headers"])

    for ballot_id in world["ballot_ids"]:
        ballot = validate_success(client.get_vote(ballot_id, STAFF), 200)
        assert_fields_equal(ballot, {"status": "VOIDED_BY_REVISION"})

    assert_slate_tallies(
        X.get_slate(client, world["slate_id"]),
        votes_for=0,
        votes_against=0,
        votes_abstain=0,
        votes_recused=0,
        approval_pct=0.00,
        quorum_met=False,
    )
