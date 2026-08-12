"""Access control, the response envelope, existence checking, and read
consistency (PRD §2.1, §2.2, §2.3, §2.8)."""
import re

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    assert_machine_resource,
    create_cleanliness_certificate_payload,
    create_machine_resource_payload,
    create_material_lot_payload,
    create_quality_inspection_payload,
    create_spec_decide_payload,
    create_tool_payload,
    get_success_data,
    is_iso8601_timestamp,
    validate_error,
    validate_paginated,
    validate_success,
)

_PLANNER = TEST_USERS["materials_planner_headers"]
_ENGINEER = TEST_USERS["tooling_engineer_headers"]
_MANAGER = TEST_USERS["plant_manager_headers"]
_SCHEDULER = TEST_USERS["production_scheduler_headers"]
_INSPECTOR = TEST_USERS["quality_inspector_headers"]
_ANY = TEST_USERS["any_headers"]


def test_create_lot_missing_auth_header_rejected(api):
    """PRD §2.1: "Every request must carry two HTTP headers: `X-User-ID`,
    identifying the acting operator, and `X-User-Role`, naming their
    operational capacity. A request missing either header, or carrying an
    empty value for either, is rejected with
    `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

    Design: Corner/errors/create_lot_missing_auth_header_rejected
    """
    res = api.create_material_lot(
        create_material_lot_payload(
            lot_code="L-AUTH", quantity_kg=5.000, unit_cost_per_kg=8.00
        ),
        headers={},
    )
    validate_error(res, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


def test_materials_planner_cannot_create_tool(api):
    """PRD §2.1: "A request whose role is not permitted on the targeted
    endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §2.1: "`ToolingEngineer` owns tool build, the prototype-to-production
    step, and drawing revision"

    Tool creation is outside the MaterialsPlanner remit.

    Design: Corner/rbac/materials_planner_cannot_create_tool
    """
    res = api.create_tool(
        create_tool_payload(tool_code="T-R1", part_number="P-R1"),
        _PLANNER,
    )
    validate_error(res, ApiErrorId.ERR_FORBIDDEN_ROLE)


def test_scheduler_cannot_record_inspection(api):
    """PRD §2.1: "`QualityInspector` records and dispositions quality
    inspections and issues cleanliness certificates"
    PRD §2.1: "A request whose role is not permitted on the targeted endpoint
    is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §2.9: "When several rules could reject the same request, checks are
    evaluated in a fixed priority order, and the earliest failing check
    determines the error returned."

    The role gate fires before existence checks, so the deliberately unknown
    referenced ids are never consulted.

    Design: Corner/rbac/scheduler_cannot_record_inspection
    """
    payload = create_quality_inspection_payload(
        NON_EXISTENT_UUID, NON_EXISTENT_UUID,
        inspection_type="FINAL",
        scheduled_start="2026-05-02T12:00:00Z",
        scheduled_end="2026-05-02T12:30:00Z",
        wall_measurements_mm=[1.240],
    )
    res = api.create_quality_inspection(payload, _SCHEDULER)
    validate_error(res, ApiErrorId.ERR_FORBIDDEN_ROLE)


def test_shared_get_endpoints_allow_any_role(api):
    """PRD §2.1: "`Any` is a shorthand meaning that any authenticated role may
    use the read endpoints and advance the logical clock."

    All six authenticated roles can list tools and see the same content.

    Design: Corner/rbac/shared_get_endpoints_allow_any_role
    """
    get_success_data(
        api.create_tool(create_tool_payload(tool_code="T-R4", part_number="P-R4"), _ENGINEER)
    )
    role_keys = [
        "materials_planner_headers",
        "tooling_engineer_headers",
        "packaging_engineer_headers",
        "plant_manager_headers",
        "production_scheduler_headers",
        "quality_inspector_headers",
    ]
    expected = None
    for key in role_keys:
        data, meta = validate_paginated(api.list_tools(TEST_USERS[key]))
        if expected is None:
            expected = data
            assert len(data) == 1 and data[0]["tool_code"] == "T-R4"
        else:
            assert data == expected, (
                f"every authenticated role must read the same content via {key}"
            )


def test_nonexistent_resources_return_not_found_battery(api):
    """PRD §2.8: "When a request references resources — path identifiers
    first, in left-to-right order, then identifiers referenced inside the
    request body — each must exist, or the request is rejected with the 404
    error specific to the missing resource: `ERR_MATERIAL_LOT_NOT_FOUND`,
    `ERR_REGRIND_BATCH_NOT_FOUND`, `ERR_TOOL_NOT_FOUND`,
    `ERR_PACKAGING_SPEC_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`,
    `ERR_ALLOCATION_NOT_FOUND`, `ERR_MACHINE_RESOURCE_NOT_FOUND`,
    `ERR_FORMING_RUN_NOT_FOUND`, `ERR_SCRAP_RECORD_NOT_FOUND`,
    `ERR_QUALITY_INSPECTION_NOT_FOUND`, `ERR_ASSEMBLY_TASK_NOT_FOUND`, or
    `ERR_CERTIFICATE_NOT_FOUND`."
    PRD §2.8: "For a certificate issuance, the polymorphic subject must exist
    as an entity of the declared `subject_type`; a `subject_id` naming no such
    entity yields the not-found error of that subject kind."

    Design: Corner/errors/nonexistent_resources_return_not_found_battery
    """
    validate_error(api.get_tool(NON_EXISTENT_UUID, _ANY), ApiErrorId.ERR_TOOL_NOT_FOUND)
    validate_error(
        api.get_material_lot(NON_EXISTENT_UUID, _ANY), ApiErrorId.ERR_MATERIAL_LOT_NOT_FOUND
    )
    validate_error(
        api.get_production_order(NON_EXISTENT_UUID, _ANY), ApiErrorId.ERR_ORDER_NOT_FOUND
    )
    validate_error(
        api.get_machine_resource(NON_EXISTENT_UUID, _ANY),
        ApiErrorId.ERR_MACHINE_RESOURCE_NOT_FOUND,
    )
    validate_error(
        api.get_quality_inspection(NON_EXISTENT_UUID, _ANY),
        ApiErrorId.ERR_QUALITY_INSPECTION_NOT_FOUND,
    )
    validate_error(
        api.get_assembly_task(NON_EXISTENT_UUID, _ANY), ApiErrorId.ERR_ASSEMBLY_TASK_NOT_FOUND
    )
    validate_error(
        api.get_material_allocation(NON_EXISTENT_UUID, _ANY),
        ApiErrorId.ERR_ALLOCATION_NOT_FOUND,
    )
    validate_error(
        api.get_forming_run(NON_EXISTENT_UUID, _ANY), ApiErrorId.ERR_FORMING_RUN_NOT_FOUND
    )
    validate_error(
        api.get_scrap_record(NON_EXISTENT_UUID, _ANY), ApiErrorId.ERR_SCRAP_RECORD_NOT_FOUND
    )
    validate_error(
        api.get_regrind_batch(NON_EXISTENT_UUID, _ANY), ApiErrorId.ERR_REGRIND_BATCH_NOT_FOUND
    )
    validate_error(
        api.get_cleanliness_certificate(NON_EXISTENT_UUID, _ANY),
        ApiErrorId.ERR_CERTIFICATE_NOT_FOUND,
    )
    validate_error(
        api.decide_packaging_spec(
            NON_EXISTENT_UUID, create_spec_decide_payload("APPROVED"), _MANAGER
        ),
        ApiErrorId.ERR_PACKAGING_SPEC_NOT_FOUND,
    )
    # Polymorphic subject lookup: an unknown TOOL subject id yields the tool's
    # not-found error, not the certificate's.
    validate_error(
        api.create_cleanliness_certificate(
            create_cleanliness_certificate_payload(
                "TOOL", NON_EXISTENT_UUID, grade="INDUSTRIAL"
            ),
            _INSPECTOR,
        ),
        ApiErrorId.ERR_TOOL_NOT_FOUND,
    )


def test_get_response_envelope_shape(api):
    """PRD §2.2: "The `response_type` is either "object" for a single resource
    or "array" for a list of resources."
    PRD §2.2: "The `api_request_id` is a server-generated unique identifier
    for the request that starts with `req_`."
    PRD §2.2: "The `api_request_timestamp` is a server-generated ISO 8601 UTC
    timestamp with three fractional digits."

    Design: Corner/endpoints/get_response_envelope_shape
    """
    lot = get_success_data(
        api.create_material_lot(
            create_material_lot_payload(
                lot_code="L-E3", resin_type="PP", gauge_mm=1.000,
                quantity_kg=4.000, unit_cost_per_kg=6.00,
            ),
            _PLANNER,
        )
    )
    res = api.get_material_lot(lot["id"], _ANY)
    data = validate_success(res, 200)
    body = res.json()
    assert body["response_type"] == "object", (
        f"a single-resource GET must carry response_type 'object', got {body['response_type']}"
    )
    assert data["id"] == lot["id"]
    request_id = body["meta"]["api_request_id"]
    assert isinstance(request_id, str) and request_id.startswith("req_"), (
        f"api_request_id must start with 'req_', got {request_id!r}"
    )
    timestamp = body["meta"]["api_request_timestamp"]
    assert is_iso8601_timestamp(timestamp)
    assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$", timestamp), (
        f"api_request_timestamp must carry three fractional digits, got {timestamp!r}"
    )


def test_immediate_read_after_write_consistency(api):
    """PRD §2.2: "Unless otherwise noted, operations that create or modify a
    resource will return the created or updated resource object in the data
    field."
    PRD §3.6: "Floor capacity is modeled as machine resources, registered by a
    `ProductionScheduler` with a `resource_code`, a `resource_type` of
    `FORMING_STATION` or `INSPECTION_BOOTH` (immutable after creation), the
    highest product grade the resource may touch as `cleanliness_grade`, and a
    positive `machine_rate_per_hour`."

    A GET issued immediately after the create returns every input field
    verbatim — there is no eventual-convergence window.

    Design: Corner/consistency_model/immediate_read_after_write_consistency
    """
    created = validate_success(
        api.create_machine_resource(
            create_machine_resource_payload(
                resource_code="ST-CM1", resource_type="FORMING_STATION",
                cleanliness_grade="FOOD", machine_rate_per_hour=62.50,
            ),
            _SCHEDULER,
        ),
        201,
    )
    got = validate_success(api.get_machine_resource(created["id"], _ANY), 200)
    assert_machine_resource(got)
    assert got["id"] == created["id"]
    assert got["resource_code"] == "ST-CM1"
    assert got["resource_type"] == "FORMING_STATION"
    assert got["cleanliness_grade"] == "FOOD"
    assert got["machine_rate_per_hour"] == 62.50
