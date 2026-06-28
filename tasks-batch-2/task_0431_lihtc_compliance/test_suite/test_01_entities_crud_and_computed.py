"""Entity creation, computed fields, validation, pagination, RBAC, and authentication.

Translates queue B (Corner) instances from the entities, rbac, and consistency_model
sections of the coverage index.
"""
import pytest
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    NON_EXISTENT_UUID,
    TEST_USERS,
    create_project_payload,
    create_household_payload,
    assert_project,
    assert_unit,
    setup_project_building,
    create_project,
    create_building,
    create_household,
)

OWNER = TEST_USERS["owner_agent_headers"]
HFA = TEST_USERS["state_hfa_headers"]


def test_create_project_returns_201_with_server_defaults(api, owner_headers):
    """PRD §3.1: "On creation the project's `status` is `DRAFT`, its `posture` is
    `COMPLIANT`, and its `open_finding_count` is 0."

    Design: Corner/entities/create_project_returns_201_with_defaults
    """
    res = api.create_project(create_project_payload(), owner_headers)
    project = validate_success(res, 201)
    assert_project(project)
    assert project["status"] == "DRAFT"
    assert project["posture"] == "COMPLIANT"
    assert project["open_finding_count"] == 0
    assert project["version"] == 1


def test_create_project_missing_required_field_returns_validation(api, owner_headers):
    """PRD §3.1: "The create payload supplies a `name`, the area median income baseline
    `area_median_income_cents` (the annual AMI for a four-person household, in cents, which
    must be at least 100000 cents and serves as the baseline for every unit income limit in
    the project), the elected minimum set-aside test `minimum_set_aside`, and the
    `placed_in_service_date` that marks the start of the compliance period."
    PRD §2.4: "A malformed body, a missing required field, or an invalid enum or type value
    is rejected with `ERR_VALIDATION`."

    Design: Corner/entities/create_project_missing_required_field_returns_validation
    """
    payload = create_project_payload()
    del payload["area_median_income_cents"]
    res = api.create_project(payload, owner_headers)
    validate_error(res, "ERR_VALIDATION", expected_status=400)


def test_get_nonexistent_project_returns_not_found(api, hfa_headers):
    """PRD §2.4: "If any referenced identifier fails to resolve to an existing resource, the
    request is rejected immediately with `ERR_NOT_FOUND`, and later identifiers are not
    examined."

    Design: Corner/entities/get_nonexistent_project_returns_not_found
    """
    res = api.get_project(NON_EXISTENT_UUID, hfa_headers)
    validate_error(res, "ERR_NOT_FOUND", expected_status=404)


def test_unit_income_rent_limits_computed_on_create(api):
    """PRD §3.1: "The `income_limit_cents` is then the AMI baseline multiplied by the AMI
    percentage divided by 100, multiplied by the household-size factor divided by 10000, with
    the result floored. The `gross_rent_ceiling_cents` is the `income_limit_cents` multiplied
    by 30, divided by 100, divided by 12, floored — that is, thirty percent of the annual
    income limit expressed as a monthly figure, floored. Finally, the `net_max_rent_cents` is
    the `gross_rent_ceiling_cents` minus the unit's `utility_allowance_cents`."
    PRD §3.1: "At creation, a unit's `li_status` is `VACANT_NEVER_OCCUPIED` and its computed
    `is_low_income_counted` flag is false."

    Design: Corner/entities/unit_income_rent_limits_computed_on_create_inputs_ignored
    """
    project, building = setup_project_building()
    res = api.create_unit(
        {
            "building_id": building["id"],
            "unit_number": "U1",
            "bedroom_count": 1,
            "sqft": 1_000,
            "utility_allowance_cents": 9_000,
            "ami_designation": "AMI_50",
        },
        OWNER,
    )
    unit = validate_success(res, 201)
    assert_unit(unit)
    assert unit["income_limit_cents"] == 3_840_000
    assert unit["gross_rent_ceiling_cents"] == 96_000
    assert unit["net_max_rent_cents"] == 87_000
    assert unit["li_status"] == "VACANT_NEVER_OCCUPIED"
    assert unit["is_low_income_counted"] is False


def test_household_student_eligible_false_when_all_students_no_exception(api):
    """PRD §3.2: "A household is student-ineligible — `student_eligible` is false — in exactly
    one situation: when `all_full_time_students` is true and `student_exception` is `NONE`."

    Design: Corner/entities/household_student_eligible_false_when_all_students_no_exception
    """
    project = create_project()
    res = api.create_household(
        create_household_payload(
            project["id"], all_full_time_students=True, student_exception="NONE"
        ),
        OWNER,
    )
    household = validate_success(res, 201)
    assert household["student_eligible"] is False


def test_household_student_exception_rescues_eligibility(api):
    """PRD §3.2: "an all-student household that carries any exception other than `NONE` is
    rescued and therefore eligible."

    Design: Corner/entities/household_student_exception_rescues_eligibility
    """
    project = create_project()
    res = api.create_household(
        create_household_payload(
            project["id"], all_full_time_students=True, student_exception="SINGLE_PARENT"
        ),
        OWNER,
    )
    household = validate_success(res, 201)
    assert household["student_eligible"] is True


def test_list_projects_pagination_envelope_fields(api):
    """PRD §2.3: "List responses carry the pagination fields `limit`, `offset`,
    `total_count`, and `has_more` inside the `meta` object of the envelope."

    Design: Corner/entities/list_projects_pagination_envelope_fields
    """
    create_project(name="P1")
    create_project(name="P2")
    data, meta = validate_paginated(
        api.list_projects(HFA, params={"limit": 1, "offset": 0})
    )
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert len(data) == 1


# ─── RBAC + authentication (Corner/rbac) ──────────────

def test_owner_agent_cannot_approve_certification(api):
    """PRD §2.1: "When a request is well-authenticated but the acting role is not permitted to
    perform the requested operation, the system rejects it with `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/owner_agent_cannot_approve_certification
    """
    project, building = setup_project_building()
    unit = get_success_data(
        api.create_unit(
            {
                "building_id": building["id"],
                "unit_number": "U1",
                "bedroom_count": 1,
                "sqft": 1_000,
                "utility_allowance_cents": 9_000,
                "ami_designation": "AMI_50",
            },
            OWNER,
        )
    )
    household = create_household(project["id"])
    cert = get_success_data(
        api.create_certification(
            {
                "household_id": household["id"],
                "unit_id": unit["id"],
                "cert_type": "INITIAL",
                "annual_income_cents": 3_000_000,
                "effective_date": "2026-01-15T00:00:00Z",
            },
            OWNER,
        )
    )
    get_success_data(api.submit_certification(cert["id"], OWNER))
    res = api.approve_certification(cert["id"], {"decision": "APPROVE"}, OWNER)
    validate_error(res, "ERR_UNAUTHORIZED", expected_status=403)
    after = get_success_data(api.get_certification(cert["id"], OWNER))
    assert after["status"] == "SUBMITTED"


def test_state_hfa_cannot_create_project(api, hfa_headers):
    """PRD §2.1: "The `OwnerAgent` is the property owner or management agent. It creates and
    operates the LIHTC project and its buildings, units, and households; it certifies tenant
    income; it leases units; and it corrects findings."
    PRD §2.1: "When a request is well-authenticated but the acting role is not permitted to
    perform the requested operation, the system rejects it with `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/state_hfa_cannot_create_project
    """
    res = api.create_project(create_project_payload(), hfa_headers)
    validate_error(res, "ERR_UNAUTHORIZED", expected_status=403)


def test_missing_auth_headers_returns_unauthenticated(api):
    """PRD §2.1: "If either header is missing or malformed, the request is rejected with
    `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/missing_auth_headers_returns_unauthenticated
    """
    res = api.create_project(create_project_payload(), {})
    validate_error(res, "ERR_UNAUTHENTICATED", expected_status=401)
