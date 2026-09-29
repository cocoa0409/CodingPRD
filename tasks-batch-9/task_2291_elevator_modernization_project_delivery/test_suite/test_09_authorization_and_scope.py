"""Authentication, endpoint role lists, ownership scoping and the terminal project."""
from test_helpers import (
    ApiErrorId,
    api_client,
    build_user_headers,
    create_jurisdiction,
    create_project,
    make_ahj_inspector_headers,
    make_building_representative_headers,
    project_version,
    read_group,
    read_inspection_appointment,
    read_project,
    read_scope_option,
    request_inspection,
    setup_car_in_testing,
    setup_completed_project,
    setup_scoped_car,
    setup_surveyed_car,
    submit_scope_option,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import PM, TECH

NO_ROLE_HEADERS = {"Content-Type": "application/json"}
UNDECLARED_ROLE_HEADERS = build_user_headers("concierge-001", "Concierge")


def test_a_project_read_without_role_headers_is_unauthenticated():
    """Every request to every endpoint must carry two headers: `X-User-ID`, identifying the
    acting principal, and `X-User-Role`, naming the authority under which they act. If either
    header is absent or empty, or if the value of `X-User-Role` is not one of the six role
    names declared below, the request is refused with `ERR_MISSING_AUTH` and HTTP 401.

    The `error_id` is a unique, machine-readable string that identifies the specific error.

    Design: Corner/errors/project_read_with_no_role_header_is_unauthenticated
    """
    ctx = setup_scoped_car()
    project_id = ctx["project"]["id"]

    anonymous = api_client.get_project(project_id, NO_ROLE_HEADERS)
    validate_error(anonymous, ApiErrorId.ERR_MISSING_AUTH, expected_status=401)
    envelope = anonymous.json()
    assert envelope["response_type"] == "error"
    assert envelope["data"]["error_id"] == "ERR_MISSING_AUTH"
    assert envelope["data"]["message"]

    unknown_role = api_client.get_project(project_id, UNDECLARED_ROLE_HEADERS)
    validate_error(unknown_role, ApiErrorId.ERR_MISSING_AUTH, expected_status=401)
    assert unknown_role.json()["data"]["error_id"] != "ERR_ROLE_NOT_PERMITTED"

    resolved = validate_success(api_client.get_project(project_id, TECH))
    assert resolved["id"] == project_id


def test_a_survey_technician_may_not_price_a_scope_option():
    """When both headers are well formed but the named role does not appear in the target
    endpoint's authorized-role list, the request is refused with `ERR_ROLE_NOT_PERMITTED` and
    HTTP 403. This second check runs before any identifier in the request path is resolved,
    so a caller without permission on an endpoint cannot use 404-versus-403 differences to
    discover which rows exist.

    Design: Corner/rbac/survey_technician_cannot_create_a_scope_option
    """
    ctx = setup_surveyed_car()
    project_id = ctx["project"]["id"]
    car_id = ctx["car"]["id"]
    version_before = project_version(project_id)

    payload = {
        "car_id": car_id,
        "tier": "CONTROLLER_ONLY",
        "base_price_cents": 5_000_000,
        "expected_project_version": version_before,
    }

    refused = api_client.create_scope_option(payload, TECH)
    validate_error(refused, ApiErrorId.ERR_ROLE_NOT_PERMITTED, expected_status=403)

    _, meta = validate_paginated(
        api_client.list_scope_options(PM, params={"car_id": car_id})
    )
    assert meta["total_count"] == 0
    assert project_version(project_id) == version_before

    allowed = validate_success(
        api_client.create_scope_option(payload, PM), expected_status=201
    )
    assert allowed["car_id"] == car_id
    assert allowed["status"] == "DRAFT"


def test_a_representative_may_not_approve_another_buildings_option():
    """When `X-User-Role` is `BuildingRepresentative`, `X-User-ID` is the `id` of the acting
    `ModernizationProject`; ownership checks on any resource that references a
    `ModernizationProject` compare the resource's owning project — resolved through car to
    project, group to project, scope option to car to project, and so on — to `X-User-ID`, and
    a mismatch is refused with `ERR_PROJECT_SCOPE_MISMATCH` and HTTP 403. A representative of
    one building can therefore never act on another building's rows, even on endpoints their
    role permits, and their list reads are scoped to their own project.

    Design: Corner/rbac/building_representative_cannot_approve_another_projects_scope_option
    """
    ctx = setup_scoped_car()
    option_id = ctx["scope_option"]["id"]
    owning_project_id = ctx["project"]["id"]
    submit_scope_option(option_id)

    other_project = create_project(
        ctx["jurisdiction"]["id"], building_name="Brentwood Annex"
    )

    refused = api_client.approve_scope_option(
        option_id, make_building_representative_headers(other_project["id"])
    )
    validate_error(refused, ApiErrorId.ERR_PROJECT_SCOPE_MISMATCH, expected_status=403)

    stored = read_scope_option(option_id)
    assert stored["status"] == "SUBMITTED"

    owner = read_project(owning_project_id)
    assert owner["approved_scope_value_cents"] == 0
    assert owner["status"] == "SCOPING"

    approved = validate_success(
        api_client.approve_scope_option(
            option_id, make_building_representative_headers(owning_project_id)
        )
    )
    assert approved["status"] == "APPROVED"


def test_an_inspector_may_not_schedule_outside_its_own_jurisdiction():
    """When `X-User-Role` is `AHJInspector`, `X-User-ID` is the `id` of the acting
    `Jurisdiction`; ownership checks compare the `jurisdiction_id` of the project owning the
    target resource to `X-User-ID`, and a mismatch is refused with
    `ERR_JURISDICTION_SCOPE_MISMATCH` and HTTP 403. An inspector cannot schedule, reschedule,
    waive or rule on work outside their own jurisdiction.

    Design: Corner/rbac/ahj_inspector_cannot_schedule_outside_its_own_jurisdiction
    """
    ctx = setup_car_in_testing(staging_area_sqft=1200)
    governing_jurisdiction_id = ctx["jurisdiction"]["id"]
    appointment = request_inspection(ctx["car"]["id"], "2026-08-25")
    assert appointment["recorded_by_jurisdiction_id"] == governing_jurisdiction_id

    foreign = create_jurisdiction(name="County of Marlow", code_edition_year=2022)

    refused = api_client.schedule_inspection_appointment(
        appointment["id"],
        {"scheduled_at": "2026-08-25T13:00:00Z"},
        make_ahj_inspector_headers(foreign["id"]),
    )
    validate_error(
        refused, ApiErrorId.ERR_JURISDICTION_SCOPE_MISMATCH, expected_status=403
    )

    stored = read_inspection_appointment(appointment["id"])
    assert stored["status"] == "REQUESTED"
    assert stored["scheduled_at"] is None
    assert stored["recorded_by_jurisdiction_id"] == governing_jurisdiction_id

    scheduled = validate_success(
        api_client.schedule_inspection_appointment(
            appointment["id"],
            {"scheduled_at": "2026-08-25T13:00:00Z"},
            make_ahj_inspector_headers(governing_jurisdiction_id),
        )
    )
    assert scheduled["status"] == "SCHEDULED"
    assert scheduled["scheduled_at"] == "2026-08-25T13:00:00.000Z"


def test_registering_a_car_into_a_completed_project_is_refused():
    """Registering a car into a project that has already reached `COMPLETED` is refused with
    `ERR_PROJECT_STATE_INVALID`.

    The project row counts as an ancestor for this purpose: a project that has reached
    `COMPLETED` is closed to new work, so registering a car, creating a scope option or
    planning an outage window against it is refused with `ERR_PROJECT_STATE_INVALID`.

    Design: Corner/errors/adding_a_car_to_a_completed_project_is_rejected
    """
    ctx = setup_completed_project(warranty_months=12, staging_area_sqft=1200)
    project_id = ctx["project"]["id"]
    group_id = ctx["group"]["id"]

    finished = read_project(project_id)
    assert finished["status"] == "COMPLETED"
    assert finished["car_count"] == 1
    assert ctx["maintenance_contract"]["status"] == "ACTIVE"
    assert ctx["maintenance_contract"]["cars_covered"] == 1

    refused = api_client.create_elevator_car(
        {
            "project_id": project_id,
            "group_id": group_id,
            "car_designation": "CAR-2",
            "rated_load_lbs": 3500,
            "controller_type_legacy": "RELAY",
            "machine_type": "GEARLESS",
            "duty_rank": 2,
        },
        PM,
    )
    validate_error(refused, ApiErrorId.ERR_PROJECT_STATE_INVALID, expected_status=409)

    _, meta = validate_paginated(
        api_client.list_elevator_cars(PM, params={"project_id": project_id})
    )
    assert meta["total_count"] == 1
    assert read_project(project_id)["car_count"] == 1

    group = read_group(group_id)
    assert group["car_count"] == 1
    assert group["cars_in_service"] == 1
