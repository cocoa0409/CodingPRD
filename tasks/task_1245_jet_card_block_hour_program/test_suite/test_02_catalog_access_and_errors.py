"""Role-based access to the program catalog and generic error envelope behavior."""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    create_aircraft_payload,
    create_member,
    create_program,
    create_program_payload,
    make_member_headers,
    purchase_card,
    set_clock,
    validate_error,
    validate_paginated,
)

OPS = TEST_USERS["ops_headers"]
ANON = TEST_USERS["anonymous_headers"]


def test_anonymous_can_read_programs(api):
    """PRD §3.1: "Programs are publicly readable — `Anonymous` callers browse the catalog".
    PRD §2.1: "Anonymous callers may list and read card programs and their peak and
    blackout windows, and nothing else."

    Design: Corner/rbac/anonymous_can_read_programs
    """
    set_clock()
    create_program(program_code="RBAC1")
    resp = api.list_programs(ANON)
    data, meta = validate_paginated(resp)
    codes = [p["program_code"] for p in data]
    assert "RBAC1" in codes, f"Anonymous list of /programs must include RBAC1, got {codes}"


def test_member_cannot_create_aircraft(api):
    """PRD §3.2: "Aircraft registration, also `Ops`-only".
    PRD §2.1: "A request whose role is recognized but not permitted on the target endpoint
    is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/member_cannot_create_aircraft
    """
    set_clock()
    member = create_member()
    resp = api.create_aircraft(
        create_aircraft_payload(tail_number="N999LT"), make_member_headers(member["id"])
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, expected_status=403)


def test_member_cannot_activate_card(api):
    """PRD §4 endpoint table: "POST /cards/{cardId}/activate | Activate card (payment
    cleared) | Ops".
    PRD §2.1: "A request whose role is recognized but not permitted on the target endpoint
    is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/errors/err_unauthorized_member_cannot_activate
    """
    set_clock()
    program = create_program(program_code="ERR1")
    member = create_member()
    card = purchase_card(member["id"], program["id"])
    resp = api.activate_card(card["id"], make_member_headers(member["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, expected_status=403)


def test_missing_required_field_invalid_request(api):
    """PRD §2.11: "A malformed payload that fails schema validation surfaces as
    `ERR_INVALID_REQUEST` (HTTP 400) before any of the above."

    Design: Corner/errors/err_invalid_request_missing_required_field
    """
    set_clock()
    resp = api.create_program(
        {"program_code": "INCOMPLETE", "aircraft_category": "LIGHT"}, OPS
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)


def test_card_not_found_returns_404(api):
    """PRD §2.5: "A failure to resolve any path-referenced resource — program, member,
    card, trip, invoice, refund, or aircraft — is rejected with `ERR_NOT_FOUND`
    (HTTP 404)."

    Design: Corner/entities/card_not_found_returns_404
    """
    set_clock()
    resp = api.get_card(NON_EXISTENT_UUID, OPS)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND, expected_status=404)
