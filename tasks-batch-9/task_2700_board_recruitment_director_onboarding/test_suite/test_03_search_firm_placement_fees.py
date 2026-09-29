"""Search-firm placement fees: per-nominee rounding, the two tiers and the ledger."""
from test_helpers import fixtures as X
from test_helpers.assertions import assert_fields_equal, assert_firm_ledger
from test_helpers.test_users import make_committee_chair_headers

# Each of these targets puts its percentage product on an exact half cent.
TARGET_A = 35000020
TARGET_B = 42000020
TARGET_C = 28000020

FEE_A = 9625006
FEE_B = 11550006
FEE_C = 6300005
COMMITTED = FEE_A + FEE_B + FEE_C  # 27475017
COMMITTED_IF_SUMMED_RAW = 27475016
RETAINER = 5000000


def _three_fee_bearing_nominees(client):
    """Aurora sources three cleared candidates, all three added to one draft slate."""
    X.adopt_policy(client, min_completed_interviews=1)
    firm = X.new_search_firm(
        client,
        name="Aurora Board Search",
        contact_email="partners@aurora.example",
        fee_model="RETAINER",
        retainer_fee_cents=RETAINER,
        placement_fee_pct=27.5,
        placement_fee_tier2_pct=22.5,
    )
    chair = X.new_seated_director(
        client, full_name="Dana Chair", email="dana.chair@issuer.example",
        birth_date="1962-03-15", appointed_on="2019-05-01",
    )
    chair_headers = make_committee_chair_headers(chair["id"])
    interviewer = X.new_seated_director(
        client, full_name="Ivan Interviewer", email="ivan@issuer.example",
        birth_date="1966-07-07", appointed_on="2020-05-01",
    )

    candidates = []
    for slot, (name, email, birth_date, target) in enumerate(
        [
            ("Cand A", "cand.a@x.example", "1972-04-02", TARGET_A),
            ("Cand B", "cand.b@x.example", "1974-05-03", TARGET_B),
            ("Cand C", "cand.c@x.example", "1976-06-04", TARGET_C),
        ]
    ):
        candidate = X.new_search_firm_candidate(
            client,
            firm["id"],
            full_name=name,
            email=email,
            birth_date=birth_date,
            target_annual_comp_cents=target,
        )
        X.advance_to_slate_eligible(
            client,
            candidate["id"],
            chair_headers,
            [interviewer["id"]],
            scores=(4,),
            first_slot=slot,
        )
        candidates.append(candidate)

    slate = X.new_slate(client, cycle_year=2026, seat_count=9)
    nominees = [
        X.add_candidate_nominee(client, slate["id"], candidate["id"], order)
        for order, candidate in enumerate(candidates, start=1)
    ]
    return {"firm": firm, "slate": slate, "candidates": candidates, "nominees": nominees}


def test_each_placement_fee_is_rounded_before_the_ledger_sums_them(client):
    """Three half-cent products round up individually to 9625006, 11550006 and 6300005, so
    the committed total is 27475017 and not the 27475016 a single final rounding gives.

    PRD: "each nominee's fee is rounded to whole cents first, and the already-rounded integers are then summed."

    Design: Difficulty/combinatorial_formula/search_fee_rounds_per_nominee_before_summing_across_two_tiers
    """
    built = _three_fee_bearing_nominees(client)
    nominee_a, nominee_b, nominee_c = built["nominees"]

    assert nominee_a["placement_fee_cents"] == FEE_A
    assert nominee_b["placement_fee_cents"] == FEE_B
    assert nominee_c["placement_fee_cents"] == FEE_C

    firm = X.get_firm(client, built["firm"]["id"])
    assert firm["committed_fee_cents"] == COMMITTED
    assert firm["committed_fee_cents"] != COMMITTED_IF_SUMMED_RAW


def test_the_third_nominee_crosses_from_the_first_fee_tier_into_the_second(client):
    """Ordinals 1 and 2 take placement_fee_pct as TIER1 while ordinal 3 takes
    placement_fee_tier2_pct as TIER2.

    PRD: "The first two positions take the firm's `placement_fee_pct` and record `fee_tier_applied` `TIER1`; the third position and every later one take the firm's `placement_fee_tier2_pct` and record `TIER2`."

    Design: Difficulty/combinatorial_formula/search_fee_rounds_per_nominee_before_summing_across_two_tiers
    """
    built = _three_fee_bearing_nominees(client)
    nominee_a, nominee_b, nominee_c = built["nominees"]

    assert_fields_equal(
        X.get_nominee(client, nominee_a["id"]),
        {"nominee_ordinal": 1, "fee_tier_applied": "TIER1", "placement_fee_cents": FEE_A},
    )
    assert_fields_equal(
        X.get_nominee(client, nominee_b["id"]),
        {"nominee_ordinal": 2, "fee_tier_applied": "TIER1", "placement_fee_cents": FEE_B},
    )
    assert_fields_equal(
        X.get_nominee(client, nominee_c["id"]),
        {"nominee_ordinal": 3, "fee_tier_applied": "TIER2", "placement_fee_cents": FEE_C},
    )


def test_the_retainer_credit_is_capped_by_the_committed_fee_and_nets_the_payable(client):
    """A RETAINER firm credits its whole retainer against a larger committed fee, leaving
    22475017 net payable across three placements.

    PRD: "`retainer_credit_applied_cents` is the lesser of the firm's `retainer_fee_cents` and its `committed_fee_cents` when the `fee_model` is `RETAINER` and is 0 when the `fee_model` is `CONTINGENT`, and `net_payable_cents` is the `committed_fee_cents` less the `retainer_credit_applied_cents`."

    Design: Difficulty/combinatorial_formula/search_fee_rounds_per_nominee_before_summing_across_two_tiers
    """
    built = _three_fee_bearing_nominees(client)

    assert_firm_ledger(
        X.get_firm(client, built["firm"]["id"]),
        placed_nominee_count=3,
        committed_fee_cents=COMMITTED,
        retainer_credit_applied_cents=RETAINER,
        net_payable_cents=COMMITTED - RETAINER,
    )


def test_the_slate_carries_the_same_committed_search_fee_as_its_own_nominees(client):
    """The slate's committed_search_fee_cents is the sum over its own counted nominees, and
    all three cleared candidates land as fully independent nominees.

    PRD: "The slate's `committed_search_fee_cents` is the sum of `placement_fee_cents` over that slate's own counted nominees."

    Design: Difficulty/combinatorial_formula/search_fee_rounds_per_nominee_before_summing_across_two_tiers
    """
    built = _three_fee_bearing_nominees(client)

    slate = X.get_slate(client, built["slate"]["id"])
    assert_fields_equal(
        slate,
        {
            "committed_search_fee_cents": COMMITTED,
            "nominee_count": 3,
            "independent_nominee_count": 3,
            "independent_nominee_pct": 100.00,
            "independence_shortfall": False,
        },
    )
    for candidate in built["candidates"]:
        assert X.get_candidate(client, candidate["id"])["status"] == "NOMINATED"


def test_a_search_firm_candidate_with_one_strong_interview_reaches_readiness_92(client):
    """One completed interview scored 4 gives 32.00, plus 30.00 independence, 20.00 for the
    search-firm channel and the full 10.00 board-capacity allowance.

    PRD: "is 8.0 points per point of `interview_score_avg`, that product rounded half up to two decimal places, and then capped at 40.00."

    Design: Difficulty/combinatorial_formula/search_fee_rounds_per_nominee_before_summing_across_two_tiers
    """
    built = _three_fee_bearing_nominees(client)

    first_candidate = X.get_candidate(client, built["candidates"][0]["id"])
    assert first_candidate["readiness_score"] == 92.00
    assert first_candidate["interview_score_avg"] == 4.00
    assert first_candidate["completed_interview_count"] == 1
