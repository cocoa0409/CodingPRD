"""Employee hiring defaults, uniqueness, lookup, and roster listing (PRD §3.1)."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    api_client,
    assert_employee,
    create_employee,
    create_employee_payload,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

MANAGER = TEST_USERS["crew_manager_headers"]


def test_employee_creation_applies_system_defaults(api):
    """PRD §3.1: "A freshly hired employee starts with `availability_status`
    set to `AVAILABLE`, `cumulative_duty_minutes_month` at 0, and `fatigue_score`
    at 0."

    Design: Corner/entities/employee_creation_applies_system_defaults
    """
    resp = api_client.create_employee(
        create_employee_payload(
            employee_number="E0001", full_name="Default Dan", craft="BRAKEMAN",
            seniority_date="2020-01-01T00:00:00Z", home_terminal="CHI",
        ),
        MANAGER,
    )
    data = validate_success(resp, expected_status=201)
    assert_employee(data)
    assert data["availability_status"] == "AVAILABLE"
    assert data["cumulative_duty_minutes_month"] == 0
    assert data["fatigue_score"] == 0


def test_employee_duplicate_employee_number_rejected(api):
    """PRD §3.1: "A `CrewManager` hires an employee by supplying the craft-unique
    payroll number `employee_number` (unique across the railroad — a duplicate
    is rejected with `ERR_DUPLICATE`, HTTP 409)".

    Design: Corner/entities/employee_duplicate_employee_number_rejected
    """
    set_clock()
    create_employee(employee_number="E0002", full_name="First")
    resp = api_client.create_employee(
        create_employee_payload(employee_number="E0002", full_name="Second",
                                craft="ENGINEER"),
        MANAGER,
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE)


def test_employee_get_not_found(api):
    """PRD §2.9: "Fifth, path resolution: every `id` in the URL must resolve,
    validated left to right — the job before the call, the employee before the
    slot, and so on — with the first unresolvable segment rejected with
    `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/employee_get_not_found
    """
    resp = api_client.get_employee(NON_EXISTENT_UUID, MANAGER)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_employee_invalid_craft_enum_rejected(api):
    """PRD §2.9: "first, request well-formedness — required fields present, types
    correct, enum values within their declared sets, numeric fields within sign
    and range constraints such as `crew_required` being at least 1 and
    `claimed_minutes` never negative — rejected with `ERR_INVALID_REQUEST`
    (HTTP 400)."

    Design: Corner/entities/employee_invalid_craft_enum_rejected
    """
    resp = api_client.create_employee(
        create_employee_payload(employee_number="E0003", craft="DISPATCHER"),
        MANAGER,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_employee_missing_required_field_rejected(api):
    """PRD §2.9: "first, request well-formedness — required fields present, types
    correct, enum values within their declared sets, numeric fields within sign
    and range constraints such as `crew_required` being at least 1 and
    `claimed_minutes` never negative — rejected with `ERR_INVALID_REQUEST`
    (HTTP 400)."

    Design: Corner/entities/employee_missing_required_field_rejected
    """
    payload = create_employee_payload(employee_number="E0004")
    del payload["seniority_date"]
    resp = api_client.create_employee(payload, MANAGER)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_pagination_defaults_on_employee_list(api):
    """PRD §2.3: "List endpoints accept the query parameters `limit` and
    `offset`. `limit` defaults to 10, with a minimum of 1 and a maximum of 100;
    `offset` defaults to 0."
    PRD §2.3: "List responses carry the pagination fields `limit`, `offset`,
    `total_count`, and `has_more` inside the `meta` envelope."

    Design: Corner/entities/pagination_defaults_on_employee_list
    """
    set_clock()
    for i in range(12):
        create_employee(employee_number=f"P{i + 1:04d}",
                        seniority_date=f"2010-01-{i + 1:02d}T00:00:00Z")

    resp = api_client.list_employees(MANAGER)
    page1, meta1 = validate_paginated(resp)
    assert len(page1) == 10, f"default limit must return 10 rows, got {len(page1)}"
    assert meta1["total_count"] == 12
    assert meta1["has_more"] is True

    resp2 = api_client.list_employees(MANAGER, params={"offset": 10})
    page2, meta2 = validate_paginated(resp2)
    assert len(page2) == 2, f"offset=10 must return the remaining 2 rows, got {len(page2)}"
    assert meta2["total_count"] == 12
    assert meta2["has_more"] is False
