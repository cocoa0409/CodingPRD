"""Authentication, role authorization, identity binding and the family-specific 404s."""

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    make_board_president_headers,
    policy_payload,
    post_notice,
    read_agenda_item,
    read_meeting,
    schedule_meeting,
    seat_board,
    set_clock,
    setup_open_meeting_with_first_reading,
    setup_policy_with_draft,
    validate_error,
    validate_paginated,
    vote_payload,
)

CLERK = TEST_USERS["board_clerk_headers"]
PUBLIC = TEST_USERS["public_headers"]
LUS = TEST_USERS["legal_update_service_headers"]
PRINCIPAL = TEST_USERS["school_principal_headers"]

UNKNOWN_UUID = "00000000-0000-4000-8000-000000000000"


def test_a_request_without_the_role_header_is_unauthenticated():
    """PRD 2.1: "Every request to the API must carry two headers: `X-User-ID`, identifying
    the caller, and `X-User-Role`, naming the caller's governance role. If either header is
    missing or empty, or if `X-User-Role` names a role that is not one of the eight declared
    below, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/request_with_missing_x_user_role_header_returns_unauthenticated
    """
    response = api_client.create_policy(
        policy_payload(
            code="BP-4119",
            title="Employee Conflict of Interest",
            category="PERSONNEL",
            legal_requirement_level="REQUIRED_BY_LAW",
            manual_section="4000.19",
        ),
        {"Content-Type": "application/json"},
    )
    validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED.value)
    assert response.status_code == 401

    _rows, meta = validate_paginated(api_client.list_policies(PUBLIC))
    assert meta["total_count"] == 0


def test_the_clerk_who_builds_the_agenda_may_not_record_the_vote():
    """PRD 2.1: "A clerk may never record a vote and may never draft policy text."
    PRD 2.1: "When both headers are well formed but the named role does not appear in the
    authorized-role list for the endpoint being called, the request is rejected with
    `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/rbac/board_clerk_cannot_record_a_vote_returns_forbidden_role
    """
    members = seat_board(3)
    ids = [m["id"] for m in members]
    policy, version = setup_policy_with_draft()
    meeting, item = setup_open_meeting_with_first_reading(
        members, version["id"], item_title="First reading BP-4119"
    )

    response = api_client.record_vote(
        item["id"], vote_payload(yes_member_ids=ids[:2], no_member_ids=ids[2:3]), CLERK
    )
    validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE.value)
    assert response.status_code == 403

    row = read_agenda_item(item["id"])
    assert row["status"] == "POSTED"
    assert row["vote_outcome"] is None


def test_a_member_of_the_public_may_not_register_a_policy():
    """PRD 2.1: "Finally, **`Public`** is any member of the community exercising open-meeting
    rights: reading the public record and filing speaker cards."
    PRD 2.1: "When both headers are well formed but the named role does not appear in the
    authorized-role list for the endpoint being called, the request is rejected with
    `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/rbac/public_cannot_create_a_policy_returns_forbidden_role
    """
    response = api_client.create_policy(
        policy_payload(
            code="BP-4119",
            title="Employee Conflict of Interest",
            category="PERSONNEL",
            legal_requirement_level="REQUIRED_BY_LAW",
            manual_section="4000.19",
        ),
        PUBLIC,
    )
    validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE.value)
    assert response.status_code == 403

    _rows, meta = validate_paginated(api_client.list_policies(PUBLIC))
    assert meta["total_count"] == 0


def test_only_the_seated_president_may_call_a_meeting_to_order():
    """PRD 2.1: "When `X-User-Role` is `BoardPresident`, `X-User-ID` is the `id` of the
    acting `BoardMember`; ownership checks compare a resource's trustee foreign key to
    `X-User-ID`, and the acting trustee must additionally be a `BoardMember` whose `status`
    is `SEATED` and whose `office` is `PRESIDENT`."
    PRD 2.1: "Any of these mismatches — including a `BoardPresident` caller who is not the
    seated president — is rejected with `ERR_IDENTITY_MISMATCH` (HTTP 403)."

    Design: Corner/rbac/non_president_trustee_cannot_open_a_meeting_returns_identity_mismatch
    """
    members = seat_board(3)
    ids = [m["id"] for m in members]
    meeting = schedule_meeting()
    post_notice(meeting["id"])
    set_clock("2026-09-10T18:00:00Z")

    response = api_client.open_meeting(
        meeting["id"],
        {"attending_member_ids": ids},
        make_board_president_headers(ids[1]),
    )
    validate_error(response, ApiErrorId.ERR_IDENTITY_MISMATCH.value)
    assert response.status_code == 403

    row = read_meeting(meeting["id"])
    assert row["status"] == "NOTICED"
    assert row["opened_at"] is None


def test_each_family_answers_an_unknown_id_with_its_own_not_found_code():
    """PRD 2.7: "Each family has its own not-found code: `ERR_BOARD_MEMBER_NOT_FOUND`,
    `ERR_COMMITTEE_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`, `ERR_DISCLOSURE_NOT_FOUND`,
    `ERR_POLICY_NOT_FOUND`, `ERR_POLICY_VERSION_NOT_FOUND`, `ERR_MANDATE_NOT_FOUND`,
    `ERR_MEETING_NOT_FOUND`, `ERR_AGENDA_ITEM_NOT_FOUND`, `ERR_WAIVER_NOT_FOUND`,
    `ERR_EVALUATION_NOT_FOUND` and `ERR_PUBLICATION_NOT_FOUND`, all returned with HTTP 404."

    Design: Corner/errors/unknown_path_ids_return_domain_specific_not_found_errors
    """
    probes = [
        (api_client.get_meeting(UNKNOWN_UUID, PUBLIC), ApiErrorId.ERR_MEETING_NOT_FOUND.value),
        (api_client.get_agenda_item(UNKNOWN_UUID, PUBLIC), ApiErrorId.ERR_AGENDA_ITEM_NOT_FOUND.value),
        (
            api_client.get_committee_assignment(UNKNOWN_UUID, CLERK),
            ApiErrorId.ERR_ASSIGNMENT_NOT_FOUND.value,
        ),
        (
            api_client.get_conflict_disclosure(UNKNOWN_UUID, PUBLIC),
            ApiErrorId.ERR_DISCLOSURE_NOT_FOUND.value,
        ),
        (api_client.get_legal_mandate(UNKNOWN_UUID, LUS), ApiErrorId.ERR_MANDATE_NOT_FOUND.value),
        (
            api_client.get_waiver_request(UNKNOWN_UUID, PRINCIPAL),
            ApiErrorId.ERR_WAIVER_NOT_FOUND.value,
        ),
        (
            api_client.get_superintendent_evaluation(UNKNOWN_UUID, CLERK),
            ApiErrorId.ERR_EVALUATION_NOT_FOUND.value,
        ),
        (
            api_client.get_manual_publication(UNKNOWN_UUID, PUBLIC),
            ApiErrorId.ERR_PUBLICATION_NOT_FOUND.value,
        ),
        (api_client.get_board_member(UNKNOWN_UUID, CLERK), ApiErrorId.ERR_BOARD_MEMBER_NOT_FOUND.value),
        (api_client.get_committee(UNKNOWN_UUID, CLERK), ApiErrorId.ERR_COMMITTEE_NOT_FOUND.value),
        (
            api_client.get_policy_version(UNKNOWN_UUID, PUBLIC),
            ApiErrorId.ERR_POLICY_VERSION_NOT_FOUND.value,
        ),
    ]
    for response, expected_error_id in probes:
        validate_error(response, expected_error_id)
        assert response.status_code == 404, (
            f"expected HTTP 404 for {expected_error_id}, got {response.status_code}"
        )
        assert response.json()["response_type"] == "error"
