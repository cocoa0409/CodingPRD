"""Campus registration, catalogue models and inventory risk classification."""

from test_helpers import (
    MONITOR_UNIT,
    ApiErrorId,
    assert_department,
    assert_device,
    assert_facility,
    bootstrap_campus,
    bootstrap_pump_campus,
    create_department,
    create_device,
    create_facility,
    create_monitor_model,
    is_valid_uuid,
    read_device,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.factories import create_facility_payload


def test_facility_registration_returns_declared_system_defaults(api, ce_manager_headers):
    """PRD §3.1: "A newly registered campus opens with `ce_posture` set to `NORMAL`,
    `pm_audit_index` at 0, `open_class_i_recall_count` at 0, `departments_on_hold_count`
    at 0, `pm_compliance_pct_strict` at 0.00 and `pm_compliance_pct_operational` at 100.00."
    PRD §2.4: "The `version` is an integer that starts at 1 when the row is created and
    increments by exactly 1 on every mutation of that row, whether the mutation was
    requested directly or caused by a cascade from another resource."

    Design: Corner/entities/facility_creation_returns_system_defaults
    """
    response = api.create_facility(create_facility_payload(), ce_manager_headers)
    data = validate_success(response, 201)
    assert_facility(data)

    assert data["ce_posture"] == "NORMAL"
    assert float(data["pm_compliance_pct_strict"]) == 0.00
    assert float(data["pm_compliance_pct_operational"]) == 100.00
    assert data["pm_audit_index"] == 0
    assert data["open_class_i_recall_count"] == 0
    assert data["departments_on_hold_count"] == 0
    assert data["version"] == 1


def test_facility_creation_response_uses_the_standard_object_envelope(api, ce_manager_headers):
    """PRD §2.2: "The `response_type` is either "object" for a single resource or "array"
    for a list of resources."
    PRD §2.2: "The `api_request_id` is a server-generated unique identifier for the request
    that starts with `req_`."

    Design: Corner/entities/facility_creation_returns_system_defaults
    """
    response = api.create_facility(create_facility_payload(facility_code="RMC-02"),
                                   ce_manager_headers)
    assert response.status_code == 201, response.text
    body = response.json()

    assert body["response_type"] == "object"
    assert isinstance(body["meta"]["api_request_id"], str)
    assert body["meta"]["api_request_id"].startswith("req_")
    assert isinstance(body["meta"]["api_request_timestamp"], str)


def test_facility_read_returns_the_stored_campus(api, biomed_tech_headers):
    """PRD §3.1: "Registration takes a display `name`, a short campus code supplied as
    `facility_code`, and the regulatory PM completion-rate target expressed in percent as
    `pm_compliance_target_pct` — a value carried to two decimals and constrained to the
    range from 0.00 through 100.00 inclusive."

    Design: Corner/entities/facility_get_returns_stored_entity
    """
    facility = create_facility()

    data = validate_success(api.get_facility(facility["id"], biomed_tech_headers), 200)
    assert_facility(data)
    assert data["id"] == facility["id"]
    assert data["facility_code"] == "RMC-01"
    assert float(data["pm_compliance_target_pct"]) == 90.00
    assert data["name"] == "Riverbend Medical Center"


def test_duplicate_facility_code_is_rejected(api, ce_manager_headers):
    """PRD §3.1: "The `facility_code` must be unique across every campus already registered
    and must be between 1 and 16 characters long; a collision is rejected with
    `ERR_DUPLICATE_FACILITY_CODE`."

    Design: Corner/entities/facility_duplicate_code_returns_conflict
    """
    create_facility()

    response = api.create_facility(
        create_facility_payload(name="Riverbend Annex", facility_code="RMC-01",
                                pm_compliance_target_pct=95.00),
        ce_manager_headers,
    )
    validate_error(response, ApiErrorId.ERR_DUPLICATE_FACILITY_CODE.value, 409)


def test_department_opens_with_zero_spend_and_open_budget_state(api, ce_manager_headers):
    """PRD §3.1: "The department opens with `downtime_spend_cents` at 0 and `budget_state`
    at `OPEN`."

    Design: Corner/entities/department_creation_defaults_open_budget_state
    """
    facility = create_facility()

    response = api.create_department(
        {"facility_id": facility["id"], "name": "Neonatal ICU",
         "cost_center_code": "CC-8100", "downtime_budget_cents": 250_000},
        ce_manager_headers,
    )
    data = validate_success(response, 201)
    assert_department(data)
    assert data["downtime_spend_cents"] == 0
    assert data["budget_state"] == "OPEN"
    assert data["version"] == 1

    listed, meta = validate_paginated(
        api.list_departments(ce_manager_headers, params={"facility_id": facility["id"]})
    )
    assert len(listed) == 1, f"Expected exactly 1 department, got {len(listed)}"
    assert meta["total_count"] == 1


def test_device_list_reports_pagination_metadata(api, ce_manager_headers):
    """PRD §2.3: "The `meta` block of a list response carries `limit` and `offset` echoing
    the effective values used, `total_count` giving the number of records matching the
    filter before pagination was applied, and `has_more` indicating whether any records
    remain beyond the current page."

    Design: Corner/entities/devices_list_returns_pagination_envelope
    """
    scene = bootstrap_campus()
    create_device(scene["facility"]["id"], scene["department"]["id"], scene["model"]["id"],
                  MONITOR_UNIT, serial_number="SN-2002", acquisition_date="2023-01-10",
                  acquisition_cost_cents=1_450_000, condition_score=2)

    response = api.list_devices(ce_manager_headers,
                                params={"facility_id": scene["facility"]["id"],
                                        "limit": 1, "offset": 0})
    data, meta = validate_paginated(response)

    assert response.json()["response_type"] == "array"
    assert len(data) == 1, f"Expected exactly 1 element with limit=1, got {len(data)}"
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert meta["limit"] == 1
    assert meta["offset"] == 0


def test_device_list_limit_above_one_hundred_is_rejected(api, ce_manager_headers):
    """PRD §2.3: "`limit` controls page size: it defaults to 10 when omitted, must be at
    least 1, and must be at most 100."
    PRD §2.3: "A `limit` outside the range 1 through 100, or a negative `offset`, is
    rejected with `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/endpoints/devices_list_limit_above_maximum_returns_invalid_request
    """
    facility = create_facility()

    response = api.list_devices(ce_manager_headers,
                                params={"facility_id": facility["id"], "limit": 101})
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)


def test_device_read_with_unknown_id_returns_device_not_found(api, ce_manager_headers):
    """PRD §2.11: "Existence of every resource named in the URL path, validated left to
    right — the not-found code matching the missing resource type: `ERR_FACILITY_NOT_FOUND`,
    `ERR_DEPARTMENT_NOT_FOUND`, `ERR_VENDOR_NOT_FOUND`, `ERR_DEVICE_MODEL_NOT_FOUND`,
    `ERR_DEVICE_NOT_FOUND`, `ERR_PM_TASK_NOT_FOUND`, `ERR_WORK_ORDER_NOT_FOUND`,
    `ERR_LOANER_ASSIGNMENT_NOT_FOUND`, `ERR_RECALL_NOTICE_NOT_FOUND`,
    `ERR_RECALL_MATCH_NOT_FOUND`, `ERR_SERVICE_CONTRACT_NOT_FOUND` or
    `ERR_SECURITY_FINDING_NOT_FOUND`, each HTTP 404."

    Design: Corner/entities/device_get_unknown_id_returns_not_found
    """
    response = api.get_device("00000000-0000-4000-8000-000000000000", ce_manager_headers)
    validate_error(response, ApiErrorId.ERR_DEVICE_NOT_FOUND.value, 404)


def test_device_creation_without_maintenance_requirement_code_is_rejected(api, ce_manager_headers):
    """PRD §2.4: "Required fields that are absent, enum values outside their declared set,
    and integers outside their declared range all produce the same rejection."
    PRD §3.2: "Three integer weights describe the unit's clinical profile: `function_code`,
    the clinical-function weight, an integer from 1 through 10; `physical_risk_code`, the
    physical risk of a failure, an integer from 1 through 5; and
    `maintenance_requirement_code`, the maintenance burden, likewise an integer from 1
    through 5."

    Design: Corner/entities/device_create_missing_required_field_returns_invalid_request
    """
    facility = create_facility()
    department = create_department(facility["id"])
    model = create_monitor_model()

    response = api.create_device(
        {"facility_id": facility["id"], "department_id": department["id"],
         "device_model_id": model["id"], "serial_number": "SN-BAD",
         "acquisition_date": "2023-01-10", "acquisition_cost_cents": 1_000_000,
         "function_code": 5, "physical_risk_code": 3},
        ce_manager_headers,
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)

    listed, _ = validate_paginated(
        api.list_devices(ce_manager_headers, params={"facility_id": facility["id"]})
    )
    assert listed == [], "A rejected device create must not persist a row"


def test_device_creation_with_function_code_above_ten_is_rejected(api, ce_manager_headers):
    """PRD §3.2: "Three integer weights describe the unit's clinical profile: `function_code`,
    the clinical-function weight, an integer from 1 through 10; `physical_risk_code`, the
    physical risk of a failure, an integer from 1 through 5; and
    `maintenance_requirement_code`, the maintenance burden, likewise an integer from 1
    through 5."
    PRD §2.4: "Required fields that are absent, enum values outside their declared set,
    and integers outside their declared range all produce the same rejection."

    Design: Corner/entities/device_create_function_code_out_of_range_returns_invalid_request
    """
    facility = create_facility()
    department = create_department(facility["id"])
    model = create_monitor_model()

    response = api.create_device(
        {"facility_id": facility["id"], "department_id": department["id"],
         "device_model_id": model["id"], "serial_number": "SN-RANGE",
         "acquisition_date": "2023-01-10", "acquisition_cost_cents": 1_000_000,
         "function_code": 11, "physical_risk_code": 3, "maintenance_requirement_code": 2},
        ce_manager_headers,
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)


def test_device_creation_rejects_a_client_supplied_risk_score(api, ce_manager_headers):
    """PRD §2.4: "Fields whose values the system derives are never accepted from a client.
    Any request body that carries an unknown key, or that attempts to set a computed or
    system-maintained field, is rejected with `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/device_create_computed_risk_score_input_ignored
    """
    facility = create_facility()
    department = create_department(facility["id"])
    model = create_monitor_model()

    response = api.create_device(
        {"facility_id": facility["id"], "department_id": department["id"],
         "device_model_id": model["id"], "serial_number": "SN-INJ",
         "acquisition_date": "2023-01-10", "acquisition_cost_cents": 1_000_000,
         "function_code": 5, "physical_risk_code": 3, "maintenance_requirement_code": 2,
         "risk_score": 47},
        ce_manager_headers,
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)

    listed, _ = validate_paginated(
        api.list_devices(ce_manager_headers, params={"facility_id": facility["id"]})
    )
    assert listed == [], "A rejected device create must not persist a row"


def test_device_creation_with_unknown_department_returns_department_not_found(api, ce_manager_headers):
    """PRD §2.11: "Existence of every foreign key supplied in the request body — again the
    matching not-found code from the set `ERR_FACILITY_NOT_FOUND`, `ERR_DEPARTMENT_NOT_FOUND`,
    `ERR_VENDOR_NOT_FOUND`, `ERR_DEVICE_MODEL_NOT_FOUND`, `ERR_DEVICE_NOT_FOUND`,
    `ERR_WORK_ORDER_NOT_FOUND` and `ERR_SECURITY_FINDING_NOT_FOUND`. This step guards device
    creation, department creation, PM-task creation, work-order intake, loaner creation,
    recall-notice filing, service-contract creation and security-finding filing."

    Design: Corner/entities/device_create_with_unknown_department_returns_department_not_found
    """
    facility = create_facility()
    model = create_monitor_model()

    response = api.create_device(
        {"facility_id": facility["id"],
         "department_id": "00000000-0000-4000-8000-000000000000",
         "device_model_id": model["id"], "serial_number": "SN-FK",
         "acquisition_date": "2023-01-10", "acquisition_cost_cents": 1_000_000,
         "function_code": 5, "physical_risk_code": 3, "maintenance_requirement_code": 2},
        ce_manager_headers,
    )
    validate_error(response, ApiErrorId.ERR_DEPARTMENT_NOT_FOUND.value, 404)


def test_device_optional_inputs_fall_back_to_their_declared_defaults(api, ce_manager_headers):
    """PRD §3.2: "Three further optional inputs round out the record: `condition_score`, an
    integer from 1 through 5 where 1 is as-new and 5 is end of life, defaulting to 1;
    `utilization_hours`, the cumulative run hours, defaulting to 0; and `is_loaner_pool`,
    declaring the unit part of the loaner pool, defaulting to `false`."
    PRD §3.1: "The optional `is_network_connected` flag, defaulting to `false`, declares that
    units of this model attach to the hospital network — a single boolean that will go on to
    raise every such unit's risk score, gate its eligibility as a loaner, and bring it into
    the security coordinator's remit."

    Design: Corner/entities/device_create_optional_fields_apply_declared_defaults
    """
    facility = create_facility()
    department = create_department(facility["id"])
    model = create_monitor_model()
    assert model["is_network_connected"] is False

    response = api.create_device(
        {"facility_id": facility["id"], "department_id": department["id"],
         "device_model_id": model["id"], "serial_number": "SN-DEF",
         "acquisition_date": "2023-01-10", "acquisition_cost_cents": 1_000_000,
         "function_code": 2, "physical_risk_code": 1, "maintenance_requirement_code": 1},
        ce_manager_headers,
    )
    data = validate_success(response, 201)
    assert_device(data)

    assert data["condition_score"] == 1
    assert data["utilization_hours"] == 0
    assert data["is_loaner_pool"] is False
    # 2*2 + 1*3 + 1*1 with no network adder and a 3-year-old unit contributing no age adder.
    assert data["risk_score"] == 8
    assert data["risk_class"] == "LOW"
    assert data["pm_interval_days"] == 365


def test_device_creation_stamps_server_generated_identity_and_states(api, ce_manager_headers):
    """PRD §2.4: "The `id` is a server-minted UUID with no type prefix — clients never supply one."
    PRD §3.2: "The unit is created with `operational_state` at `IN_SERVICE` and
    `security_state` at `UNASSESSED`."
    PRD §3.9: "Each returned unit's `plan_rank` is written as its 1-based position in that
    ranking — a device that has never appeared in a plan read carries `plan_rank` 0."

    Design: Corner/entities/device_create_system_fields_generated_by_server
    """
    scene = bootstrap_campus(device_overrides={"serial_number": "SN-SYS"})
    data = read_device(scene["device"]["id"])
    assert_device(data)

    assert is_valid_uuid(data["id"]), f"id must be a bare UUID, got {data['id']!r}"
    assert data["version"] == 1
    assert data["operational_state"] == "IN_SERVICE"
    assert data["security_state"] == "UNASSESSED"
    assert data["recall_hold"] is False
    assert data["plan_rank"] == 0
    assert data["plan_funded"] is False


def test_device_update_recomputes_risk_and_replacement_score(api, biomed_tech_headers):
    """PRD §3.2: "Updating a unit accepts exactly three mutable attributes —
    `condition_score`, `utilization_hours` and `is_loaner_pool` — and every supplied field
    re-runs both the risk classification and the capital-replacement score of §3.9,
    incrementing the device's `version` by 1."
    PRD §3.9: "The **condition factor** is `condition_score` minus 1, divided by 4, so an
    as-new unit contributes 0 and an end-of-life unit contributes 1."

    Design: Corner/endpoints/device_patch_recomputes_risk_and_replacement_score
    """
    scene = bootstrap_pump_campus()
    device = scene["device"]
    assert device["risk_score"] == 38
    assert float(device["replacement_priority_score"]) == 60.63

    data = validate_success(
        api.update_device(device["id"], {"condition_score": 5, "utilization_hours": 18000},
                          biomed_tech_headers),
        200,
    )
    assert data["condition_score"] == 5
    assert data["utilization_hours"] == 18000
    # condition_score is not a risk input, so the risk classification is unchanged.
    assert data["risk_score"] == 38
    assert data["risk_class"] == "CRITICAL"
    assert data["pm_interval_days"] == 90
    assert float(data["replacement_priority_score"]) == 75.63
    assert data["version"] == 2


def test_risk_score_twenty_six_classifies_high(api, ce_manager_headers):
    """PRD §3.2: "The `risk_class` follows from the score by inclusive lower bounds:
    `CRITICAL` when `risk_score` is 34 or more, `HIGH` when it is 26 or more but below 34,
    `MEDIUM` when it is 16 or more but below 26, and `LOW` otherwise."
    PRD §3.2: "From the band comes the preventive-maintenance cadence `pm_interval_days`:
    90 days for a `CRITICAL` unit, 180 days for a `HIGH` unit, 270 days for a `MEDIUM` unit,
    and 365 days for a `LOW` unit."

    Design: Difficulty/boundary_precision_check/risk_score_26_is_high_25_is_medium
    """
    facility = create_facility()
    department = create_department(facility["id"])
    model = create_monitor_model()

    response = api.create_device(
        {"facility_id": facility["id"], "department_id": department["id"],
         "device_model_id": model["id"], "serial_number": "SN-EDGE-26",
         "acquisition_date": "2023-01-10", "acquisition_cost_cents": 1_000_000,
         "function_code": 7, "physical_risk_code": 3, "maintenance_requirement_code": 3,
         "condition_score": 1},
        ce_manager_headers,
    )
    data = validate_success(response, 201)
    assert data["risk_score"] == 26, f"Expected 7*2 + 3*3 + 3*1 == 26, got {data['risk_score']}"
    assert data["risk_class"] == "HIGH"
    assert data["pm_interval_days"] == 180


def test_risk_score_twenty_five_classifies_medium(api, ce_manager_headers):
    """PRD §3.2: "The boundaries are inclusive on the lower side, so a score of exactly 26 is
    `HIGH` while 25 is `MEDIUM`."
    PRD §3.2: "From the band comes the preventive-maintenance cadence `pm_interval_days`:
    90 days for a `CRITICAL` unit, 180 days for a `HIGH` unit, 270 days for a `MEDIUM` unit,
    and 365 days for a `LOW` unit."

    Design: Difficulty/boundary_precision_check/risk_score_26_is_high_25_is_medium
    """
    facility = create_facility()
    department = create_department(facility["id"])
    model = create_monitor_model()

    response = api.create_device(
        {"facility_id": facility["id"], "department_id": department["id"],
         "device_model_id": model["id"], "serial_number": "SN-EDGE-25",
         "acquisition_date": "2023-01-10", "acquisition_cost_cents": 1_000_000,
         "function_code": 7, "physical_risk_code": 3, "maintenance_requirement_code": 2,
         "condition_score": 1},
        ce_manager_headers,
    )
    data = validate_success(response, 201)
    assert data["risk_score"] == 25, f"Expected 7*2 + 3*3 + 2*1 == 25, got {data['risk_score']}"
    assert data["risk_class"] == "MEDIUM"
    assert data["pm_interval_days"] == 270
