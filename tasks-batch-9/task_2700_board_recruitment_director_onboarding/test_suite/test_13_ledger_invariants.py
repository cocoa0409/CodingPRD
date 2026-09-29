"""Compensating operations and the ledgers they must restore exactly: the
committee seat count under revocation, and the search-fee ledger under nominee
voids that also re-tier the survivors.
"""
from prd_bench_local_runner.testing import validate_success

from test_helpers import fixtures as X
from test_helpers.assertions import (
    assert_committee_ledger,
    assert_fields_equal,
    assert_firm_ledger,
    assert_page,
)
from test_helpers.test_users import STAFF, make_committee_chair_headers

# Three chartered seats with a strength floor of two, so the posture depends on
# both the count and the presence of an ACTIVE chair.
COMMITTEE_AUTHORIZED_SEATS = 3
COMMITTEE_MIN_SEATS = 2

# Each target comp puts its tier percentage on an exact half cent, so the
# per-nominee rounding is observable in every one of these literals.
TARGET_A = 35000020
TARGET_B = 42000020
TARGET_C = 28000020

FEE_A_TIER1 = 9625006
FEE_B_TIER1 = 11550006
FEE_C_TIER2 = 6300005
# C is promoted out of the second tier once the ordinal-1 nominee leaves the book.
FEE_C_TIER1 = 7700006

COMMITTED_WITH_THREE = 27475017
COMMITTED_WITH_B_AND_C = 19250012
COMMITTED_WITH_C_ONLY = 7700006

RETAINER = 5000000
NET_WITH_THREE = 22475017
NET_WITH_B_AND_C = 14250012
NET_WITH_C_ONLY = 2700006


def _committee_with_a_chair_and_a_member_seated(client):
    """A COMPENSATION committee holding two ACTIVE assignments, one of them the chair."""
    X.adopt_policy(client)
    chair_director = X.new_seated_director(
        client,
        full_name="Cora Chairseat",
        email="cora@issuer.example",
        birth_date="1968-01-01",
        appointed_on="2021-01-01",
        is_independent=True,
    )
    member_director = X.new_seated_director(
        client,
        full_name="Milo Memberseat",
        email="milo@issuer.example",
        birth_date="1969-02-02",
        appointed_on="2021-02-01",
        is_independent=True,
    )
    committee = X.new_committee(
        client,
        code="COMPENSATION",
        name="Compensation Committee",
        authorized_seats=COMMITTEE_AUTHORIZED_SEATS,
        min_seats=COMMITTEE_MIN_SEATS,
    )
    chair_seat = X.seat_assignment(
        client, committee["id"], chair_director["id"], seat_role="CHAIR"
    )
    member_seat = X.seat_assignment(
        client, committee["id"], member_director["id"], seat_role="MEMBER"
    )
    return {"committee": committee, "chair_seat": chair_seat, "member_seat": member_seat}


def _three_nominees_on_one_firms_book(client):
    """Vega sources three cleared candidates, all three placed on one draft slate."""
    X.adopt_policy(client, min_completed_interviews=1)
    firm = X.new_search_firm(
        client,
        name="Vega Board Partners",
        contact_email="partners@vega.example",
        fee_model="RETAINER",
        retainer_fee_cents=RETAINER,
        placement_fee_pct=27.5,
        placement_fee_tier2_pct=22.5,
    )
    chair = X.new_seated_director(
        client,
        full_name="Dana Chair",
        email="dana.chair@issuer.example",
        birth_date="1962-03-15",
        appointed_on="2019-05-01",
    )
    chair_headers = make_committee_chair_headers(chair["id"])
    interviewer = X.new_seated_director(
        client,
        full_name="Ivan Interviewer",
        email="ivan@issuer.example",
        birth_date="1966-07-07",
        appointed_on="2020-05-01",
    )

    candidates = []
    for slot, (full_name, email, birth_date, target) in enumerate(
        [
            ("Ada Aone", "ada@cand.example", "1972-04-02", TARGET_A),
            ("Ben Btwo", "ben@cand.example", "1973-05-03", TARGET_B),
            ("Cleo Cthree", "cleo@cand.example", "1974-06-04", TARGET_C),
        ]
    ):
        candidate = X.new_search_firm_candidate(
            client,
            firm["id"],
            full_name=full_name,
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
    return {
        "firm": firm,
        "slate": slate,
        "candidates": candidates,
        "nominees": nominees,
    }


def _void(client, nominee_id):
    return validate_success(client.void_slate_nominee(nominee_id, STAFF), 200)


def test_each_revocation_records_its_reason_without_erasing_the_activation(client):
    """Both seats are released one after the other; each revoked row carries the revocation
    reason and an end instant while keeping the activation instant it was seated on.

    PRD: "available from `PROPOSED` or `ACTIVE`, it sets `status` to `REVOKED`, `ended_reason_code` to `REVOCATION` and `ended_at` to the logical clock instant"

    Design: Difficulty/compensating_invariant/committee_seat_ledger_returns_to_its_pre_activation_value_after_revocations
    """
    built = _committee_with_a_chair_and_a_member_seated(client)

    member = X.revoke_assignment(client, built["member_seat"]["id"])
    chair = X.revoke_assignment(client, built["chair_seat"]["id"])

    for revoked in (member, chair):
        assert_fields_equal(
            revoked, {"status": "REVOKED", "ended_reason_code": "REVOCATION"}
        )
        assert revoked["ended_at"] is not None
        assert revoked["activated_at"] is not None


def test_the_seat_count_walks_back_to_its_pre_activation_value(client):
    """filled_seats is recounted from the ACTIVE rows at every step, so the two revocations
    take it 2, 1, 0 and the emptied committee agrees with an empty ACTIVE listing.

    PRD: "The `filled_seats` is the count of that committee's assignments whose `status` is exactly `ACTIVE`; `PROPOSED`, `ENDED` and `REVOKED` rows never occupy a seat."

    Design: Difficulty/compensating_invariant/committee_seat_ledger_returns_to_its_pre_activation_value_after_revocations
    """
    built = _committee_with_a_chair_and_a_member_seated(client)
    committee_id = built["committee"]["id"]

    assert X.get_committee(client, committee_id)["filled_seats"] == 2

    X.revoke_assignment(client, built["member_seat"]["id"])
    assert X.get_committee(client, committee_id)["filled_seats"] == 1

    X.revoke_assignment(client, built["chair_seat"]["id"])
    assert X.get_committee(client, committee_id)["filled_seats"] == 0

    rows, _ = assert_page(
        client.list_assignments(
            STAFF, params={"committee_id": committee_id, "status": "ACTIVE"}
        ),
        expected_total=0,
    )
    assert X.get_committee(client, committee_id)["filled_seats"] == len(rows)


def test_the_posture_is_re_derived_from_the_count_after_each_revocation(client):
    """Releasing the member seat drops the count below the strength floor and releasing the
    chair seat empties the committee, so the posture is derived afresh both times.

    PRD: "An activation followed by a revocation therefore returns `filled_seats` to exactly its prior value and re-derives the same posture from that count."

    Design: Difficulty/compensating_invariant/committee_seat_ledger_returns_to_its_pre_activation_value_after_revocations
    """
    built = _committee_with_a_chair_and_a_member_seated(client)
    committee_id = built["committee"]["id"]

    assert_committee_ledger(
        X.get_committee(client, committee_id), filled_seats=2, status="AT_STRENGTH"
    )

    X.revoke_assignment(client, built["member_seat"]["id"])
    assert_committee_ledger(
        X.get_committee(client, committee_id), filled_seats=1, status="UNDER_STRENGTH"
    )

    X.revoke_assignment(client, built["chair_seat"]["id"])
    assert_committee_ledger(
        X.get_committee(client, committee_id), filled_seats=0, status="UNDER_STRENGTH"
    )


def test_voiding_the_first_nominee_re_tiers_the_survivors_upward(client):
    """Losing the ordinal-1 nominee shifts B and C up one place each, so C leaves the second
    tier and its own fee rises from 6300005 to 7700006.

    PRD: "the sourcing firm's ledger is recomputed with every surviving nominee's `nominee_ordinal`, `fee_tier_applied` and `placement_fee_cents` re-derived from the new ordering, so a void can promote a later `TIER2` nominee into `TIER1`"

    Design: Difficulty/compensating_invariant/search_fee_ledger_releases_exactly_what_each_nominee_committed_and_re_tiers_survivors
    """
    built = _three_nominees_on_one_firms_book(client)
    nominee_a, nominee_b, nominee_c = built["nominees"]

    assert nominee_c["placement_fee_cents"] == FEE_C_TIER2
    assert nominee_c["fee_tier_applied"] == "TIER2"

    _void(client, nominee_a["id"])

    assert_fields_equal(
        X.get_nominee(client, nominee_b["id"]),
        {
            "nominee_ordinal": 1,
            "fee_tier_applied": "TIER1",
            "placement_fee_cents": FEE_B_TIER1,
        },
    )
    assert_fields_equal(
        X.get_nominee(client, nominee_c["id"]),
        {
            "nominee_ordinal": 2,
            "fee_tier_applied": "TIER1",
            "placement_fee_cents": FEE_C_TIER1,
        },
    )


def test_each_void_releases_exactly_the_cents_that_nominee_committed(client):
    """The committed total is the sum of the surviving rounded fees at every step, walking
    27475017 to 19250012 to 7700006 to 0 with the slate's own figure in step.

    PRD: "Because every stored fee is an exact integer, voiding a nominee releases precisely the cents it committed and the ledger returns to its prior value with no drift."

    Design: Difficulty/compensating_invariant/search_fee_ledger_releases_exactly_what_each_nominee_committed_and_re_tiers_survivors
    """
    built = _three_nominees_on_one_firms_book(client)
    firm_id = built["firm"]["id"]
    slate_id = built["slate"]["id"]
    nominee_a, nominee_b, nominee_c = built["nominees"]

    assert X.get_firm(client, firm_id)["committed_fee_cents"] == COMMITTED_WITH_THREE
    assert X.get_slate(client, slate_id)["committed_search_fee_cents"] == (
        COMMITTED_WITH_THREE
    )

    _void(client, nominee_a["id"])
    assert X.get_firm(client, firm_id)["committed_fee_cents"] == COMMITTED_WITH_B_AND_C
    assert X.get_slate(client, slate_id)["committed_search_fee_cents"] == (
        COMMITTED_WITH_B_AND_C
    )

    _void(client, nominee_b["id"])
    assert X.get_firm(client, firm_id)["committed_fee_cents"] == COMMITTED_WITH_C_ONLY
    assert X.get_slate(client, slate_id)["committed_search_fee_cents"] == (
        COMMITTED_WITH_C_ONLY
    )

    _void(client, nominee_c["id"])
    assert X.get_firm(client, firm_id)["committed_fee_cents"] == 0
    assert X.get_slate(client, slate_id)["committed_search_fee_cents"] == 0


def test_the_retainer_credit_is_released_with_the_last_committed_fee(client):
    """The retainer stays fully credited while any fee survives, and the whole ledger,
    credit included, returns to zero once the last nominee leaves the book.

    PRD: "`retainer_credit_applied_cents` is the lesser of the firm's `retainer_fee_cents` and its `committed_fee_cents` when the `fee_model` is `RETAINER` and is 0 when the `fee_model` is `CONTINGENT`"

    Design: Difficulty/compensating_invariant/search_fee_ledger_releases_exactly_what_each_nominee_committed_and_re_tiers_survivors
    """
    built = _three_nominees_on_one_firms_book(client)
    firm_id = built["firm"]["id"]
    nominee_a, nominee_b, nominee_c = built["nominees"]

    assert_firm_ledger(
        X.get_firm(client, firm_id),
        placed_nominee_count=3,
        committed_fee_cents=COMMITTED_WITH_THREE,
        retainer_credit_applied_cents=RETAINER,
        net_payable_cents=NET_WITH_THREE,
    )

    _void(client, nominee_a["id"])
    assert_firm_ledger(
        X.get_firm(client, firm_id),
        placed_nominee_count=2,
        committed_fee_cents=COMMITTED_WITH_B_AND_C,
        retainer_credit_applied_cents=RETAINER,
        net_payable_cents=NET_WITH_B_AND_C,
    )

    _void(client, nominee_b["id"])
    assert_firm_ledger(
        X.get_firm(client, firm_id),
        placed_nominee_count=1,
        committed_fee_cents=COMMITTED_WITH_C_ONLY,
        retainer_credit_applied_cents=RETAINER,
        net_payable_cents=NET_WITH_C_ONLY,
    )

    _void(client, nominee_c["id"])
    assert_firm_ledger(
        X.get_firm(client, firm_id),
        placed_nominee_count=0,
        committed_fee_cents=0,
        retainer_credit_applied_cents=0,
        net_payable_cents=0,
    )


def test_the_emptied_slate_keeps_the_fee_each_voided_row_carried(client):
    """With the counted set empty the slate reports no nominees and no percentage, while the
    three voided rows keep the fees they held when they left and defer their candidates.

    PRD: "The `independent_nominee_pct` is 0.00 when the `nominee_count` is 0, and otherwise 100 multiplied by the `independent_nominee_count` divided by the `nominee_count`, rounded half up to two decimal places."

    Design: Difficulty/compensating_invariant/search_fee_ledger_releases_exactly_what_each_nominee_committed_and_re_tiers_survivors
    """
    built = _three_nominees_on_one_firms_book(client)
    nominee_a, nominee_b, nominee_c = built["nominees"]

    for nominee in (nominee_a, nominee_b, nominee_c):
        _void(client, nominee["id"])

    assert_fields_equal(
        X.get_slate(client, built["slate"]["id"]),
        {
            "nominee_count": 0,
            "independent_nominee_count": 0,
            "independent_nominee_pct": 0.00,
            "independence_shortfall": False,
        },
    )
    for nominee, retained_fee in (
        (nominee_a, FEE_A_TIER1),
        (nominee_b, FEE_B_TIER1),
        (nominee_c, FEE_C_TIER1),
    ):
        row = X.get_nominee(client, nominee["id"])
        assert_fields_equal(row, {"status": "VOIDED", "placement_fee_cents": retained_fee})
        assert row["voided_at"] is not None
    for candidate in built["candidates"]:
        assert_fields_equal(
            X.get_candidate(client, candidate["id"]),
            {"status": "DEFERRED", "deferred_cycle_year": 2026},
        )
