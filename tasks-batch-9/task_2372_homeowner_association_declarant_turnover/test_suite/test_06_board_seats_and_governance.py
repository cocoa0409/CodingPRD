"""The board seat ledger: resignation, seating to capacity, and rescission."""

from typing import Any, Dict, List

import pytest
from test_helpers import (
    DEFAULT_CLOCK_UTC,
    ERR_SEAT_CAPACITY_EXCEEDED,
    INSPECTOR_HEADERS,
    SEAT_TYPE_OWNER_ELECTED,
    TRIGGER_BASIS_FIXED_DATE,
    ApiClient,
    assert_instant,
    assert_seat_ledger,
    director_payload,
    do_certify_trigger,
    do_rescind_director,
    make_transition_committee_headers,
    read_turnover_case,
    seed_association,
    seed_declarant_appointed_director,
    seed_owner_elected_director,
    seed_turnover_case,
    validate_error,
    validate_paginated,
)

OWNER_CANDIDATES = [
    "Fay Oduya",
    "Gil Marchetti",
    "Hana Iwu",
    "Ivo Salcedo",
    "Jo Renwick",
]


@pytest.fixture
def windrow_estates(api: ApiClient) -> Dict[str, Any]:
    """Two appointed directors, then certification — so all five seats stand vacant."""
    association = seed_association(
        api,
        name="Windrow Estates",
        total_planned_lots=15,
        turnover_threshold_pct=66.67,
        fixed_turnover_date="2026-07-01T00:00:00Z",
        statute_of_repose_years=8,
        reserve_pool_cents=90000,
        reserve_claim_pool_cents=200000,
        declarant_monthly_subsidy_cents=33000,
    )
    case = seed_turnover_case(api, association["id"], total_seats=5)
    appointed = [
        seed_declarant_appointed_director(api, case["id"], full_name="Dana Vogel"),
        seed_declarant_appointed_director(api, case["id"], full_name="Eli Prasad"),
    ]
    certified = do_certify_trigger(
        api, case["id"], association["id"], TRIGGER_BASIS_FIXED_DATE
    )
    return {
        "association": association,
        "case": certified,
        "appointed": appointed,
        "committee_headers": make_transition_committee_headers(association["id"]),
    }


def _seat_owners(api: ApiClient, case_id: str, count: int) -> List[Dict[str, Any]]:
    return [
        seed_owner_elected_director(api, case_id, full_name=OWNER_CANDIDATES[index])
        for index in range(count)
    ]


class TestSeatCountIsConserved:
    """total_seats equals the seated directors plus the vacant seats, always."""

    def test_the_resignation_cascade_frees_both_appointed_seats(
        self, api: ApiClient, windrow_estates: Dict[str, Any]
    ) -> None:
        """Two appointed directors resign, and their seats reappear as vacant.

        "The quantity that must hold after every seat mutation, including the
        resignation cascade of certification and every rescission, is that
        `total_seats` always equals the number of `SEATED` directors plus
        `vacant_seats`."

        Design: Difficulty/compensating_invariant/board_seat_count_conserved_across_resignation_seating_and_rescission
        """
        case = windrow_estates["case"]
        assert case["governance_status"] == "ELECTION_CALLED"
        assert_seat_ledger(
            case, declarant_appointed=0, owner_elected=0, vacant=5, total_seats=5
        )

        directors, meta = validate_paginated(
            api.list_directors(case["id"], windrow_estates["committee_headers"])
        )
        assert meta["total_count"] == 2
        for row in directors:
            assert row["status"] == "RESIGNED"
            assert_instant(row["vacated_at"], DEFAULT_CLOCK_UTC, "vacated_at")

    def test_seating_fills_the_board_and_the_sixth_seat_is_refused(
        self, api: ApiClient, windrow_estates: Dict[str, Any]
    ) -> None:
        """The fourth seat holds the election and the fifth fills the board.

        "Seating is refused outright when `vacant_seats` is already 0 — the board
        cannot exceed the size the bylaws fix — with
        `ERR_SEAT_CAPACITY_EXCEEDED`."

        Design: Difficulty/compensating_invariant/board_seat_count_conserved_across_resignation_seating_and_rescission
        """
        case_id = windrow_estates["case"]["id"]
        committee = windrow_estates["committee_headers"]

        _seat_owners(api, case_id, 3)
        after_three = read_turnover_case(api, case_id)
        assert after_three["governance_status"] == "ELECTION_CALLED"
        assert_seat_ledger(
            after_three, declarant_appointed=0, owner_elected=3, vacant=2, total_seats=5
        )

        seed_owner_elected_director(api, case_id, full_name=OWNER_CANDIDATES[3])
        after_four = read_turnover_case(api, case_id)
        assert after_four["governance_status"] == "ELECTION_HELD"
        assert_seat_ledger(
            after_four, declarant_appointed=0, owner_elected=4, vacant=1, total_seats=5
        )

        seed_owner_elected_director(api, case_id, full_name=OWNER_CANDIDATES[4])
        after_five = read_turnover_case(api, case_id)
        assert after_five["governance_status"] == "ELECTION_HELD", (
            "A fifth owner director does not disturb an already-held election"
        )
        assert_seat_ledger(
            after_five, declarant_appointed=0, owner_elected=5, vacant=0, total_seats=5
        )

        validate_error(
            api.seat_director(
                director_payload(
                    case_id, SEAT_TYPE_OWNER_ELECTED, full_name="Kip Halloran"
                ),
                INSPECTOR_HEADERS,
            ),
            ERR_SEAT_CAPACITY_EXCEEDED,
        )

        _rows, meta = validate_paginated(api.list_directors(case_id, committee))
        assert meta["total_count"] == 7, (
            "The refused seating creates no Director row: two resigned plus five seated"
        )
        assert_seat_ledger(
            read_turnover_case(api, case_id),
            declarant_appointed=0,
            owner_elected=5,
            vacant=0,
            total_seats=5,
        )

    def test_rescission_returns_the_seat_and_can_un_hold_the_election(
        self, api: ApiClient, windrow_estates: Dict[str, Any]
    ) -> None:
        """The first rescission leaves the majority intact; the second breaks it.

        "Rescission sets `status` to `RESCINDED`, stamps `vacated_at`, decrements
        `owner_elected_seats` by one and increments `vacant_seats` by one so the
        seat ledger still balances; and if that drops `owner_elected_seats` below
        `owner_elected_seats_required` while the case sits in `ELECTION_HELD`, the
        governance dimension reverts `ELECTION_HELD → ELECTION_CALLED` and the
        posture is re-derived."

        Design: Difficulty/compensating_invariant/board_seat_count_conserved_across_resignation_seating_and_rescission
        """
        case_id = windrow_estates["case"]["id"]
        owners = _seat_owners(api, case_id, 5)
        assert read_turnover_case(api, case_id)["governance_status"] == "ELECTION_HELD"

        fifth = do_rescind_director(api, owners[4]["id"])
        assert fifth["status"] == "RESCINDED"
        assert_instant(fifth["vacated_at"], DEFAULT_CLOCK_UTC, "vacated_at")
        after_first = read_turnover_case(api, case_id)
        assert after_first["governance_status"] == "ELECTION_HELD", (
            "Four of four required seats still holds the election"
        )
        assert_seat_ledger(
            after_first, declarant_appointed=0, owner_elected=4, vacant=1, total_seats=5
        )

        do_rescind_director(api, owners[3]["id"])
        after_second = read_turnover_case(api, case_id)
        assert after_second["governance_status"] == "ELECTION_CALLED", (
            "Dropping below owner_elected_seats_required un-holds the election"
        )
        assert_seat_ledger(
            after_second, declarant_appointed=0, owner_elected=3, vacant=2, total_seats=5
        )
