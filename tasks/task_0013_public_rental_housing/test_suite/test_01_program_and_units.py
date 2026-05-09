"""Program creation, housing-unit registration, basic CRUD, headers, and pagination.

Covers PRD §2.1 (headers + RBAC), §2.2 (envelope), §2.3 (pagination), §2.4 (id and
timestamps), §2.5 (clock advance), §3.1 (program setup, housing stock).
"""

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    advance_clock_by,
    api_client as api,
    assert_housing_unit,
    assert_program,
    create_housing_unit_payload,
    create_program,
    create_program_payload,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_create_program_with_required_fields_returns_201_and_initial_clock():
    """PRD §3.1: "The program is created with current_period_index initialized to 0".
    PRD §4: "New resource creation returns HTTP 201 and a body containing the created resource".
    """
    payload = create_program_payload(
        name="Spring 2026 Program",
        notice_period_length=5,
        grace_period_length=4,
        per_capita_income_threshold_cents=300_000,
        per_capita_asset_threshold_cents=500_000,
    )
    res = api.create_program(payload, TEST_USERS["housing_director_headers"])
    program = validate_success(res, expected_status=201)
    assert_program(program)
    assert program["name"] == "Spring 2026 Program"
    assert program["current_period_index"] == 0
    assert program["notice_period_length"] == 5
    assert program["grace_period_length"] == 4


def test_get_nonexistent_program_returns_program_not_found():
    """PRD §2.8: "the program is resolved first, and if it does not exist the request is
    rejected with ERR_PROGRAM_NOT_FOUND".
    """
    res = api.get_program(NON_EXISTENT_UUID, TEST_USERS["housing_director_headers"])
    validate_error(res, "ERR_PROGRAM_NOT_FOUND")


def test_create_program_without_headers_rejected():
    """PRD §2.1: "A request that is missing either header, or that provides a value the
    server cannot interpret, is rejected with ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER
    at HTTP 400".
    """
    payload = create_program_payload()
    res = api.create_program(payload, headers={})
    validate_error(res, "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER")


@pytest.mark.parametrize(
    "role_role_id",
    [
        ("HousingOfficer", "test-officer-rbac"),
        ("Applicant", "test-applicant-rbac"),
        ("Citizen", "test-citizen-rbac"),
        ("IntegrationGateway", "test-int-rbac"),
    ],
)
def test_only_housing_director_may_create_program(role_role_id):
    """PRD §3.1: "A HousingDirector opens a program by supplying its name..." and
    PRD §4 endpoint table: "POST /housing-programs" is restricted to HousingDirector.
    PRD §2.1: "A request whose role is recognized but is not authorized for the requested
    operation is rejected with ERR_INSUFFICIENT_PERMISSIONS at HTTP 403".
    """
    role, user_id = role_role_id
    headers = {"X-User-ID": user_id, "X-User-Role": role}
    res = api.create_program(create_program_payload(), headers)
    validate_error(res, "ERR_INSUFFICIENT_PERMISSIONS")


def test_advance_clock_by_periods_increments_index():
    """PRD §2.5: "the program's current_period_index increases by exactly that amount"."""
    program = create_program()
    initial = program["current_period_index"]
    updated = advance_clock_by(program["id"], 7)
    assert updated["current_period_index"] == initial + 7


def test_advance_clock_only_housing_director():
    """PRD §4: POST /housing-programs/{programId}/clock/advance is HousingDirector-only.
    PRD §2.1: "A request whose role is recognized but is not authorized for the requested
    operation is rejected with ERR_INSUFFICIENT_PERMISSIONS at HTTP 403".
    """
    program = create_program()
    res = api.advance_clock(
        program["id"], {"by_periods": 1}, TEST_USERS["housing_officer_headers"]
    )
    validate_error(res, "ERR_INSUFFICIENT_PERMISSIONS")


# ──────────────────────────────────────────────────────────
# Housing units
# ──────────────────────────────────────────────────────────


def test_create_housing_unit_in_available_status():
    """PRD §3.1: "A new unit enters the world in AVAILABLE status"."""
    program = create_program()
    payload = create_housing_unit_payload(
        unit_code="A-101",
        apartment_type="ONE_BEDROOM",
        bedroom_count=1,
        monthly_base_rent_cents=80_000,
    )
    res = api.create_housing_unit(program["id"], payload, TEST_USERS["housing_director_headers"])
    unit = validate_success(res, expected_status=201)
    assert_housing_unit(unit)
    assert unit["status"] == "AVAILABLE"
    assert unit["unit_code"] == "A-101"


@pytest.mark.parametrize(
    "apartment_type,bad_bedroom_count",
    [
        ("STUDIO", 1),
        ("ONE_BEDROOM", 0),
        ("ONE_BEDROOM", 2),
        ("TWO_BEDROOM", 1),
        ("THREE_BEDROOM", 2),
    ],
)
def test_bedroom_count_must_match_apartment_type(apartment_type, bad_bedroom_count):
    """PRD §3.1: "a bedroom_count that must match the apartment type (STUDIO is 0
    bedrooms, ONE_BEDROOM is 1, TWO_BEDROOM is 2, THREE_BEDROOM is 3 — any mismatch is
    rejected with ERR_BEDROOM_COUNT_TYPE_MISMATCH)".
    """
    program = create_program()
    payload = create_housing_unit_payload(
        apartment_type=apartment_type,
        bedroom_count=bad_bedroom_count,
    )
    res = api.create_housing_unit(program["id"], payload, TEST_USERS["housing_director_headers"])
    validate_error(res, "ERR_BEDROOM_COUNT_TYPE_MISMATCH")


def test_get_housing_unit_under_wrong_program_returns_not_found():
    """PRD §2.8: "A child resource whose parent identifiers do not match the parents on
    its actual record is treated as not found at the segment that did not match".
    """
    program_a = create_program()
    program_b = create_program()
    unit = validate_success(
        api.create_housing_unit(
            program_a["id"],
            create_housing_unit_payload(),
            TEST_USERS["housing_director_headers"],
        ),
        expected_status=201,
    )
    res = api.get_housing_unit(program_b["id"], unit["id"], TEST_USERS["housing_director_headers"])
    # Either the program path resolves but the unit does not under it, or generic NOT_FOUND.
    assert res.status_code == 404


# ──────────────────────────────────────────────────────────
# Pagination
# ──────────────────────────────────────────────────────────


def test_list_units_pagination_envelope():
    """PRD §2.3: "The pagination meta block on every list response carries limit,
    offset, total_count (the total size of the unfiltered-by-pagination result set), and
    has_more (true when offset + limit < total_count)".
    """
    program = create_program()
    for i in range(3):
        api.create_housing_unit(
            program["id"],
            create_housing_unit_payload(unit_code=f"P-{i:03d}"),
            TEST_USERS["housing_director_headers"],
        )
    data, meta = validate_paginated(
        api.list_housing_units(program["id"], TEST_USERS["housing_director_headers"])
    )
    assert "limit" in meta and "offset" in meta and "total_count" in meta and "has_more" in meta
    assert meta["total_count"] >= 3

    data, meta = validate_paginated(
        api.list_housing_units(
            program["id"],
            TEST_USERS["housing_director_headers"],
            params={"limit": 1, "offset": 0},
        )
    )
    assert len(data) == 1
    assert meta["has_more"] is True


def test_unit_only_returned_to_authenticated_caller():
    """PRD §2.1: missing headers -> ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER."""
    program = create_program()
    res = api.list_housing_units(program["id"], headers={})
    validate_error(res, "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER")
