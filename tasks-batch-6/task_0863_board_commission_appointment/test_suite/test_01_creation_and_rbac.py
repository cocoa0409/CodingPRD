"""Board / seat / vacancy creation, input validation, RBAC, and listing.

Queue B (Corner) — entities, validations, roles, endpoints sections.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    assert_board, assert_seat,
    create_board_payload, create_seat_payload,
    TEST_USERS, ANON_HEADERS, make_applicant_headers, make_auditor_headers,
    NON_EXISTENT_UUID,
)

CLERK = TEST_USERS["clerk_headers"]


def test_board_create_returns_all_fields(api):
    """PRD §3.1: "A board's `status` is system-managed and is always `ACTIVE`."
    PRD §3.1: "`max_holdover_days` ... defaults to 90".
    PRD §2.4: "`version`: an integer that begins at 1 and increments on every mutation".

    Design: Corner/entities/board_create_returns_all_fields
    """
    board = validate_success(api.create_board(create_board_payload(name="Parks Commission"), CLERK), 201)
    assert_board(board)
    assert board["status"] == "ACTIVE"
    assert board["version"] == 1
    assert board["max_holdover_days"] == 90


def test_get_board_nonexistent_not_found(api):
    """PRD §2.7: "then existence of every referenced resource (`ERR_NOT_FOUND`)".

    Design: Corner/entities/get_board_nonexistent_not_found
    """
    validate_error(api.get_board(NON_EXISTENT_UUID, CLERK), "ERR_NOT_FOUND")


def test_board_create_missing_quorum_invalid_request(api):
    """PRD §2.7: "then field-level input validation (`ERR_INVALID_REQUEST` — required
    fields present, enum values in range, and numeric constraints ...)".

    Design: Corner/entities/board_create_missing_quorum_invalid_request
    """
    payload = create_board_payload(name="Parks Commission")
    del payload["quorum_count"]
    validate_error(api.create_board(payload, CLERK), "ERR_INVALID_REQUEST")


def test_seat_create_invalid_category_enum(api):
    """PRD §2.7: "field-level input validation (`ERR_INVALID_REQUEST` — required
    fields present, enum values in range ...)".
    PRD §3.1: "a `seat_category` of `AT_LARGE`, `DISTRICT`, or `EX_OFFICIO`".

    Design: Corner/entities/seat_create_invalid_category_enum
    """
    board = validate_success(api.create_board(create_board_payload(), CLERK), 201)
    res = api.create_seat(
        create_seat_payload(board["id"], seat_category="MAYORAL"), CLERK)
    validate_error(res, "ERR_INVALID_REQUEST")


def test_seat_district_specific_without_required_district(api):
    """PRD §3.1: "When and only when the residency requirement is `DISTRICT_SPECIFIC`,
    the `required_district` field must be supplied as a non-null value; a
    district-specific seat created without it is rejected with `ERR_DISTRICT_REQUIRED`."

    Design: Corner/entities/seat_district_specific_without_required_district
    """
    board = validate_success(api.create_board(create_board_payload(), CLERK), 201)
    res = api.create_seat(
        create_seat_payload(board["id"], seat_category="DISTRICT",
                            residency_requirement="DISTRICT_SPECIFIC"), CLERK)
    validate_error(res, "ERR_DISTRICT_REQUIRED")


def test_seat_defaults_vacant(api):
    """PRD §3.1: "A seat's `occupancy_status` starts at `VACANT`."

    Design: Corner/entities/seat_defaults_vacant
    """
    board = validate_success(api.create_board(create_board_payload(), CLERK), 201)
    seat = validate_success(api.create_seat(create_seat_payload(board["id"]), CLERK), 201)
    assert_seat(seat)
    assert seat["occupancy_status"] == "VACANT"


def test_seat_limit_reached_exceeds_authorized(api):
    """PRD §3.1: "Creating a seat may not push the board's total seat count above its
    `authorized_seat_count`; a seat that would exceed the authorization is rejected
    with `ERR_SEAT_LIMIT_REACHED`."

    Design: Corner/validations/seat_limit_reached_exceeds_authorized
    """
    board = validate_success(api.create_board(
        create_board_payload(name="Tiny Board", board_type="BOARD",
                             authorized_seat_count=1, quorum_count=1), CLERK), 201)
    validate_success(api.create_seat(create_seat_payload(board["id"], seat_number=1), CLERK), 201)
    res = api.create_seat(create_seat_payload(board["id"], seat_number=2), CLERK)
    validate_error(res, "ERR_SEAT_LIMIT_REACHED")


def test_board_create_unauthenticated(api):
    """PRD §2.1: "If either header is missing, or if `X-User-Role` is not one of the
    recognized roles, the request is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/validations/board_create_unauthenticated
    """
    validate_error(api.create_board(create_board_payload(), ANON_HEADERS),
                   "ERR_UNAUTHENTICATED")


def test_applicant_cannot_create_board_unauthorized(api):
    """PRD §2.1: "When the headers are well-formed but the role is not permitted to
    perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED`."

    Design: Corner/validations/applicant_cannot_create_board_unauthorized
    """
    res = api.create_board(create_board_payload(), make_applicant_headers("someone"))
    validate_error(res, "ERR_UNAUTHORIZED")


def test_public_auditor_cannot_post_seat_unauthorized(api):
    """PRD §2.1: "When the headers are well-formed but the role is not permitted to
    perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED`."
    PRD §4: POST /civic/seats is authorized for BoardClerk only.

    Design: Corner/roles/public_auditor_cannot_post_seat_unauthorized
    """
    board = validate_success(api.create_board(create_board_payload(), CLERK), 201)
    res = api.create_seat(create_seat_payload(board["id"]), make_auditor_headers("audit-1"))
    validate_error(res, "ERR_UNAUTHORIZED")


def test_boards_list_pagination(api):
    """PRD §2.3: "The `limit` parameter caps the number of items returned ... Every list
    response includes `limit`, `offset`, `total_count`, and `has_more` in the `meta`
    object, where `total_count` is the number of matching records before pagination and
    `has_more` indicates whether records remain beyond the current page."

    Design: Corner/endpoints/boards_list_pagination
    """
    validate_success(api.create_board(create_board_payload(name="Board A", board_type="BOARD"), CLERK), 201)
    validate_success(api.create_board(create_board_payload(name="Board B"), CLERK), 201)
    data, meta = validate_paginated(
        api.list_boards(make_auditor_headers("audit-1"), params={"limit": 1, "offset": 0}))
    assert len(data) == 1
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
