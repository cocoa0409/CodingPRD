"""Seating the board, chartering committees, and the committee-seat ledger."""

import pytest

from test_helpers import (
    ApiErrorId,
    CLOCK_START,
    TEST_USERS,
    api_client,
    assert_committee_seat_conservation,
    assert_instant_equals,
    board_member_payload,
    change_assignment_status,
    charter_committee,
    committee_assignment_payload,
    get_success_data,
    read_board_member,
    read_committee,
    read_disclosure,
    register_policy,
    file_disclosure,
    seat_board,
    seat_on_committee,
    resign_trustee,
    validate_error,
    validate_success,
)

CLERK = TEST_USERS["board_clerk_headers"]


def test_trustee_term_must_be_a_real_interval():
    """PRD 3.1: "The term must be a real interval: `term_end_date` has to be strictly
    after `term_start_date`, and a request where it is not is malformed."

    Design: Corner/entities/create_board_member_with_term_end_before_start_returns_invalid_request
    """
    response = api_client.create_board_member(
        board_member_payload(
            full_name="Ada Reyes",
            seat_number=1,
            term_start_date="2030-01-01T00:00:00Z",
            term_end_date="2026-01-01T00:00:00Z",
            employer_name="Reyes Dental",
        ),
        CLERK,
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value)
    assert response.status_code == 400


def test_two_seated_trustees_may_not_share_a_seat_number():
    """PRD 3.1: "Two uniqueness rules guard the roster, and both surface as
    `ERR_DUPLICATE_SEAT_NUMBER`: no two trustees whose `status` is `SEATED` may share a
    `seat_number`, and at most one `SEATED` trustee may hold the `PRESIDENT` office."

    Design: Corner/validations/duplicate_seat_number_among_seated_trustees_returns_conflict
    """
    members = seat_board(1)
    response = api_client.create_board_member(
        board_member_payload(full_name="Ben Cole", seat_number=1, employer_name="Cole Freight"),
        CLERK,
    )
    validate_error(response, ApiErrorId.ERR_DUPLICATE_SEAT_NUMBER.value)
    assert response.status_code == 409
    assert read_board_member(members[0]["id"])["seat_number"] == 1


def test_resignation_cascades_to_committee_seats_and_open_disclosures():
    """PRD 3.1: "Resignation is the trustee's exit door, and it is a four-hop cascade. The
    trustee's `status` moves `SEATED → RESIGNED`. Because the trustee has left the board,
    every committee seat they hold in `ACTIVE` or `RECUSED` status moves to `REMOVED` with
    `removed_on` stamped from the logical clock. Because those seats emptied, each
    affected committee recomputes `filled_seat_count`, `voting_seat_count` and
    `vacant_seat_count`, and flips from `ACTIVE` to `INQUORATE` when `voting_seat_count`
    has fallen below its `quorum_size`. And because the trustee can no longer vote, every
    one of their disclosures in `RECUSAL_REQUIRED` moves to `CLEARED` with `cleared_on`
    stamped, dropping `open_recusal_count` to 0."

    Design: Corner/state_machines/board_member_resignation_cascades_to_seats_and_disclosures
    """
    members = seat_board(3)
    committee = charter_committee()
    chair_seat = seat_on_committee(committee["id"], members[1]["id"], "CHAIR")
    member_seat = seat_on_committee(committee["id"], members[2]["id"], "MEMBER")
    policy = register_policy("BP-3312", "Purchasing", "BUSINESS", "RECOMMENDED", "3000.12")
    disclosure = file_disclosure(
        members[1]["id"], policy["id"], "FINANCIAL", "Family firm bids on district contracts."
    )

    resigned = validate_success(api_client.resign_board_member(members[1]["id"], CLERK), 200)
    assert resigned["status"] == "RESIGNED"

    from test_helpers import api_client as client

    chair_row = get_success_data(client.get_committee_assignment(chair_seat["id"], CLERK))
    member_row = get_success_data(client.get_committee_assignment(member_seat["id"], CLERK))
    assert chair_row["status"] == "REMOVED"
    assert_instant_equals(chair_row["removed_on"], CLOCK_START, "CommitteeAssignment.removed_on")
    assert member_row["status"] == "ACTIVE"

    after = read_committee(committee["id"])
    assert after["voting_seat_count"] == 1
    assert after["filled_seat_count"] == 1
    assert after["vacant_seat_count"] == 2
    assert after["status"] == "INQUORATE"

    cleared = read_disclosure(disclosure["id"])
    assert cleared["status"] == "CLEARED"
    assert_instant_equals(cleared["cleared_on"], CLOCK_START, "ConflictDisclosure.cleared_on")
    assert read_board_member(members[1]["id"])["open_recusal_count"] == 0


def test_reinstating_an_active_seat_is_refused():
    """PRD 3.1: "Recusing a seat that is not `ACTIVE`, reinstating one that is not
    `RECUSED`, or removing one that is already `REMOVED` are all refused with
    `ERR_ASSIGNMENT_STATE_INVALID`."

    Design: Corner/state_machines/reinstate_an_active_assignment_returns_assignment_state_invalid
    """
    members = seat_board(2)
    committee = charter_committee(name="Finance Committee", charter_type="FINANCE")
    seat = seat_on_committee(committee["id"], members[1]["id"], "MEMBER")

    response = api_client.set_committee_assignment_status(
        seat["id"], {"action": "REINSTATE"}, CLERK
    )
    validate_error(response, ApiErrorId.ERR_ASSIGNMENT_STATE_INVALID.value)
    assert response.status_code == 409

    row = get_success_data(api_client.get_committee_assignment(seat["id"], CLERK))
    assert row["status"] == "ACTIVE"
    committee_after = read_committee(committee["id"])
    assert committee_after["voting_seat_count"] == 1
    assert committee_after["status"] == "INQUORATE"


def test_recusing_then_reinstating_a_seat_restores_committee_quorum():
    """PRD 3.1: "`RECUSE` takes an `ACTIVE` seat to `RECUSED`: `voting_seat_count` falls
    by one while `filled_seat_count` is untouched, and the committee may flip `ACTIVE →
    INQUORATE`. `REINSTATE` takes a `RECUSED` seat back to `ACTIVE` — permitted only while
    the underlying trustee is still `SEATED`, and otherwise refused with
    `ERR_MEMBER_NOT_SEATED` — raising `voting_seat_count` by one and possibly flipping the
    committee `INQUORATE → ACTIVE`."

    Design: Corner/state_machines/recuse_then_reinstate_restores_committee_quorum
    """
    members = seat_board(3)
    committee = charter_committee(name="Audit Committee", charter_type="AUDIT")
    seat_on_committee(committee["id"], members[1]["id"], "CHAIR")
    second_seat = seat_on_committee(committee["id"], members[2]["id"], "MEMBER")

    change_assignment_status(second_seat["id"], "RECUSE")
    midway = read_committee(committee["id"])
    assert midway["voting_seat_count"] == 1
    assert midway["filled_seat_count"] == 2
    assert midway["status"] == "INQUORATE"

    change_assignment_status(second_seat["id"], "REINSTATE")
    row = get_success_data(api_client.get_committee_assignment(second_seat["id"], CLERK))
    assert row["status"] == "ACTIVE"
    after = read_committee(committee["id"])
    assert after["voting_seat_count"] == 2
    assert after["filled_seat_count"] == 2
    assert after["vacant_seat_count"] == 1
    assert after["status"] == "ACTIVE"


def test_a_full_committee_refuses_another_seat_holder():
    """PRD 3.1: "A committee with `vacant_seat_count` at zero cannot take another seat
    holder and refuses with `ERR_COMMITTEE_SEATS_FULL`."

    Design: Corner/validations/assigning_a_trustee_to_a_full_committee_returns_committee_seats_full
    """
    members = seat_board(4)
    committee = charter_committee()
    seat_on_committee(committee["id"], members[0]["id"], "CHAIR")
    seat_on_committee(committee["id"], members[1]["id"], "MEMBER")
    seat_on_committee(committee["id"], members[2]["id"], "MEMBER")

    response = api_client.create_committee_assignment(
        committee_assignment_payload(committee["id"], members[3]["id"], role_on_committee="MEMBER"),
        CLERK,
    )
    validate_error(response, ApiErrorId.ERR_COMMITTEE_SEATS_FULL.value)
    assert response.status_code == 409

    after = read_committee(committee["id"])
    assert after["filled_seat_count"] == 3
    assert after["vacant_seat_count"] == 0
    assert after["status"] == "ACTIVE"


def test_seating_the_same_trustee_on_one_committee_twice_is_refused():
    """PRD 3.1: "Two duplicate conditions both answer `ERR_DUPLICATE_ASSIGNMENT`: the same
    trustee already holding a seat on that committee in `ACTIVE` or `RECUSED` status, and
    the committee already having an `ACTIVE` `CHAIR` when a second chair is proposed."

    Design: Corner/validations/seating_the_same_trustee_on_one_committee_twice_returns_duplicate_assignment
    """
    members = seat_board(2)
    committee = charter_committee()
    seat_on_committee(committee["id"], members[1]["id"], "CHAIR")

    response = api_client.create_committee_assignment(
        committee_assignment_payload(committee["id"], members[1]["id"], role_on_committee="MEMBER"),
        CLERK,
    )
    validate_error(response, ApiErrorId.ERR_DUPLICATE_ASSIGNMENT.value)
    assert response.status_code == 409

    after = read_committee(committee["id"])
    assert after["filled_seat_count"] == 1
    assert after["vacant_seat_count"] == 2


def test_seat_capacity_equals_filled_plus_vacant_at_every_observation_point():
    """PRD 2.10: "A committee's `seat_capacity` always equals `filled_seat_count` plus
    `vacant_seat_count`, and `filled_seat_count` always equals the number of that
    committee's seats whose `status` is `ACTIVE` or `RECUSED`."
    PRD 3.1: "A committee's `status` is derived, not set: it flips to `ACTIVE` the moment
    `voting_seat_count` reaches `quorum_size` and back to `INQUORATE` when it falls below."

    Design: Difficulty/compensating_invariant/committee_seat_capacity_conserved_across_assignment_and_removal
    """
    members = seat_board(3)
    committee = charter_committee(name="Audit Committee", charter_type="AUDIT")
    seat_on_committee(committee["id"], members[1]["id"], "CHAIR")

    before = read_committee(committee["id"])
    assert before["filled_seat_count"] == 1
    assert before["vacant_seat_count"] == 2
    assert before["status"] == "INQUORATE"
    assert_committee_seat_conservation(before)

    second_seat = seat_on_committee(committee["id"], members[2]["id"], "MEMBER")
    midway = read_committee(committee["id"])
    assert midway["filled_seat_count"] == 2
    assert midway["vacant_seat_count"] == 1
    assert midway["status"] == "ACTIVE"
    assert_committee_seat_conservation(midway)

    change_assignment_status(second_seat["id"], "REMOVE")
    after = read_committee(committee["id"])
    assert after["filled_seat_count"] == 1
    assert after["vacant_seat_count"] == 2
    assert after["status"] == "INQUORATE"
    assert_committee_seat_conservation(after)
    assert after["seat_capacity"] == 3


def test_removing_a_seat_stamps_removed_on_and_leaves_the_chair_seat_standing():
    """PRD 3.1: "`REMOVE` takes a seat in either `ACTIVE` or `RECUSED` to `REMOVED`,
    stamping `removed_on`, lowering `filled_seat_count` and `voting_seat_count` and
    raising `vacant_seat_count` so that capacity still equals filled plus vacant."
    PRD 2.4: "The clock starts at exactly `2026-08-01T00:00:00.000Z` when the server
    starts and never falls back to real wall-clock time."

    Design: Difficulty/compensating_invariant/committee_seat_capacity_conserved_across_assignment_and_removal
    """
    members = seat_board(3)
    committee = charter_committee(name="Audit Committee", charter_type="AUDIT")
    chair_seat = seat_on_committee(committee["id"], members[1]["id"], "CHAIR")
    second_seat = seat_on_committee(committee["id"], members[2]["id"], "MEMBER")

    removed = change_assignment_status(second_seat["id"], "REMOVE")
    assert removed["status"] == "REMOVED"
    assert_instant_equals(removed["removed_on"], CLOCK_START, "CommitteeAssignment.removed_on")

    chair_row = get_success_data(api_client.get_committee_assignment(chair_seat["id"], CLERK))
    assert chair_row["status"] == "ACTIVE"
    assert read_committee(committee["id"])["voting_seat_count"] == 1
