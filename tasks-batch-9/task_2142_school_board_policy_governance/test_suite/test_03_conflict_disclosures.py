"""Conflict-of-interest disclosure, its classification matrix, and clearing."""

import pytest

from test_helpers import (
    ApiErrorId,
    CLOCK_START,
    TEST_USERS,
    api_client,
    assert_conflict_disclosure,
    assert_instant_equals,
    clear_disclosure,
    conflict_disclosure_payload,
    file_disclosure,
    make_board_member_headers,
    make_board_president_headers,
    read_board_member,
    read_disclosure,
    register_policy,
    seat_board,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

PUBLIC = TEST_USERS["public_headers"]
CLERK = TEST_USERS["board_clerk_headers"]


def test_employment_interest_on_an_instruction_policy_is_advisory_only():
    """PRD 3.2: "A `FINANCIAL` or `VENDOR` interest is categorically disqualifying and
    lands as `RECUSAL_REQUIRED` regardless of which policy it touches. An `EMPLOYMENT`
    interest lands as `RECUSAL_REQUIRED` only when the linked policy's `category` is
    `PERSONNEL`. A `FAMILIAL` interest lands as `RECUSAL_REQUIRED` only when the linked
    policy's `category` is `STUDENTS`. In every other combination the disclosure lands as
    `ADVISORY_ONLY` and the trustee may still vote on that policy. After classification,
    the trustee's `open_recusal_count` is recomputed as the number of their disclosures
    whose `status` is `RECUSAL_REQUIRED`."

    Design: Corner/calculations/employment_disclosure_on_instruction_policy_is_advisory_only
    """
    members = seat_board(2)
    policy = register_policy("BP-6155", "Homework and Grading", "INSTRUCTION", "RECOMMENDED", "6000.55")

    response = api_client.create_conflict_disclosure(
        conflict_disclosure_payload(
            members[1]["id"],
            policy["id"],
            nature="EMPLOYMENT",
            narrative="Spouse teaches in the district.",
        ),
        make_board_member_headers(members[1]["id"]),
    )
    data = validate_success(response, 201)
    assert_conflict_disclosure(data)
    assert data["status"] == "ADVISORY_ONLY"
    assert read_board_member(members[1]["id"])["open_recusal_count"] == 0


def test_familial_interest_on_a_students_policy_requires_recusal():
    """PRD 3.2: "A `FAMILIAL` interest lands as `RECUSAL_REQUIRED` only when the linked
    policy's `category` is `STUDENTS`."
    PRD 3.2: "The instant of filing is stamped as `disclosed_on` from the logical clock,
    and `cleared_on` stays null."

    Design: Corner/calculations/familial_disclosure_on_students_policy_requires_recusal
    """
    members = seat_board(2)
    policy = register_policy("BP-5030", "Student Wellness", "STUDENTS", "RECOMMENDED", "5000.30")

    response = api_client.create_conflict_disclosure(
        conflict_disclosure_payload(
            members[1]["id"],
            policy["id"],
            nature="FAMILIAL",
            narrative="Child is enrolled at the affected site.",
        ),
        make_board_member_headers(members[1]["id"]),
    )
    data = validate_success(response, 201)
    assert data["status"] == "RECUSAL_REQUIRED"
    assert_instant_equals(data["disclosed_on"], CLOCK_START, "ConflictDisclosure.disclosed_on")
    assert data["cleared_on"] is None
    assert read_board_member(members[1]["id"])["open_recusal_count"] == 1


def test_disclosure_listing_is_reachable_from_either_parent():
    """PRD 3.2: "Disclosures are part of the public record and can be listed by anyone,
    filtered by `board_member_id`, by `policy_id`, or by `status`."
    PRD 3.2: "A `FINANCIAL` or `VENDOR` interest is categorically disqualifying and lands
    as `RECUSAL_REQUIRED` regardless of which policy it touches."

    Design: Corner/entities/conflict_disclosure_list_filtered_by_policy_finds_children_of_that_policy
    """
    members = seat_board(2)
    policy_a = register_policy("BP-3312", "Purchasing", "BUSINESS", "RECOMMENDED", "3000.12")
    policy_b = register_policy("BP-6155", "Homework and Grading", "INSTRUCTION", "RECOMMENDED", "6000.55")
    disclosure = file_disclosure(
        members[1]["id"], policy_a["id"], "VENDOR", "Owns a stake in a district vendor."
    )

    rows_a, meta_a = validate_paginated(
        api_client.list_conflict_disclosures(PUBLIC, {"policy_id": policy_a["id"]})
    )
    assert meta_a["total_count"] == 1
    assert rows_a[0]["id"] == disclosure["id"]

    _rows_b, meta_b = validate_paginated(
        api_client.list_conflict_disclosures(PUBLIC, {"policy_id": policy_b["id"]})
    )
    assert meta_b["total_count"] == 0

    _rows_c, meta_c = validate_paginated(
        api_client.list_conflict_disclosures(PUBLIC, {"board_member_id": members[0]["id"]})
    )
    assert meta_c["total_count"] == 0

    assert read_disclosure(disclosure["id"])["status"] == "RECUSAL_REQUIRED"


def test_clearing_an_already_cleared_disclosure_is_refused():
    """PRD 3.2: "Clearing a disclosure is a presidential act, permitted while the
    disclosure is `RECUSAL_REQUIRED` or `ADVISORY_ONLY`, and it stamps `cleared_on` from
    the logical clock and recomputes the trustee's `open_recusal_count`."
    PRD 3.2: "Clearing a disclosure that is already `CLEARED` is refused with
    `ERR_DISCLOSURE_ALREADY_CLEARED`."

    Design: Corner/state_machines/clear_an_already_cleared_disclosure_returns_disclosure_already_cleared
    """
    members = seat_board(2)
    policy = register_policy("BP-3312", "Purchasing", "BUSINESS", "RECOMMENDED", "3000.12")
    disclosure = file_disclosure(
        members[1]["id"], policy["id"], "VENDOR", "Owns a stake in a district vendor."
    )
    clear_disclosure(disclosure["id"], members[0]["id"])
    set_clock("2026-08-09T00:00:00Z")

    response = api_client.clear_conflict_disclosure(
        disclosure["id"], make_board_president_headers(members[0]["id"])
    )
    validate_error(response, ApiErrorId.ERR_DISCLOSURE_ALREADY_CLEARED.value)
    assert response.status_code == 409

    row = read_disclosure(disclosure["id"])
    assert row["status"] == "CLEARED"
    assert_instant_equals(row["cleared_on"], CLOCK_START, "ConflictDisclosure.cleared_on")
    assert read_board_member(members[1]["id"])["open_recusal_count"] == 0


def test_moving_the_logical_clock_is_echoed_and_stamps_the_next_write():
    """PRD 2.4: "The clock starts at exactly `2026-08-01T00:00:00.000Z` when the server
    starts and never falls back to real wall-clock time."
    PRD 2.4: "An administrative capability lets a caller move the clock: it accepts a
    single field, `to_iso8601`, carrying the ISO 8601 UTC instant the clock should read,
    and answers with the new position in a `current_utc` field. Moving the clock mutates
    no entity."

    Design: Corner/endpoints/clock_endpoint_echoes_the_new_logical_time
    """
    members = seat_board(2)
    policy = register_policy("BP-3312", "Purchasing", "BUSINESS", "RECOMMENDED", "3000.12")
    policy_before = validate_success(api_client.get_policy(policy["id"], PUBLIC), 200)

    moved = validate_success(
        api_client.set_clock({"to_iso8601": "2026-12-25T09:30:00Z"}, CLERK), 200
    )
    assert_instant_equals(moved["current_utc"], "2026-12-25T09:30:00Z", "clock current_utc")

    policy_after = validate_success(api_client.get_policy(policy["id"], PUBLIC), 200)
    assert policy_after["version"] == policy_before["version"], "moving the clock mutates no entity"
    assert policy_after["updated_at"] == policy_before["updated_at"]

    disclosure = file_disclosure(
        members[1]["id"], policy["id"], "VENDOR", "Holiday disclosure."
    )
    assert_instant_equals(
        disclosure["disclosed_on"], "2026-12-25T09:30:00Z", "ConflictDisclosure.disclosed_on"
    )
