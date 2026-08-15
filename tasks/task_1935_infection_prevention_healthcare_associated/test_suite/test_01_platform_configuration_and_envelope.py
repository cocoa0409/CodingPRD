"""Platform configuration, response envelope, patient census, and not-found
coverage (PRD §2.2, §2.4, §2.5, §3.1, §3.2)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_instant_equal,
    assert_patient,
    create_device_day_count,
    create_facility,
    create_facility_payload,
    create_patient,
    create_unit,
    create_unit_payload,
    discharge_patient,
    setup_facility_unit,
    validate_error,
    validate_success,
)


def test_facility_creation_applies_defaults(api, admin_headers):
    """PRD §3.1: "Two optional thresholds govern reporting: `sir_high_threshold`,
    which defaults to 1.25 and sets the SIR value at or above which a monthly
    summary's `sir_flag` reads `HIGH`; and `hh_min_opportunities`, which defaults
    to 30 and sets the minimum number of hand-hygiene opportunities a unit must
    record in a month for its compliance rate to be reportable."
    PRD §2.4: "`version` — an integer that starts at 1 and increments by one on
    every mutation of the resource, including mutations driven by cascades and
    recomputes rather than by a direct client write."

    Design: Corner/entities/facility_creation_applies_defaults
    """
    resp = api.create_facility(
        {
            "name": "F-Def",
            "nhsn_org_id": "ORG-D",
            "clabsi_baseline_per_1000": 2.0,
            "cauti_baseline_per_1000": 1.5,
            "ssi_baseline_per_procedure": 0.25,
        },
        admin_headers,
    )
    facility = validate_success(resp, 201)
    assert facility["sir_high_threshold"] == 1.25, (
        f"default sir_high_threshold must be 1.25, got {facility['sir_high_threshold']}"
    )
    assert facility["hh_min_opportunities"] == 30, (
        f"default hh_min_opportunities must be 30, got {facility['hh_min_opportunities']}"
    )
    assert facility["version"] == 1, f"version must start at 1, got {facility['version']}"
    from test_helpers import is_valid_uuid

    assert is_valid_uuid(facility["id"]), "id must be a bare UUID without type prefix"


def test_facility_creation_missing_required_field_returns_invalid_request(
    api, admin_headers
):
    """PRD §2.5: "Missing required fields, invalid enum values, integer range
    violations (such as a value that must be at least 0 or at least 1), string
    minimum-length violations, and violated conditional-required pairings all
    yield `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/facility_creation_missing_required_field_returns_invalid_request
    """
    payload = create_facility_payload()
    del payload["nhsn_org_id"]
    resp = api.create_facility(payload, admin_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_unit_create_with_unknown_facility_returns_not_found(api, admin_headers):
    """PRD §2.5: "Path identifiers are validated left to right, and then
    foreign-key identifiers in the request body are validated in payload
    declaration order. The first missing reference produces the resource-specific
    not-found error (`ERR_FACILITY_NOT_FOUND`, `ERR_UNIT_NOT_FOUND`,
    `ERR_PATIENT_NOT_FOUND`, `ERR_EMPLOYEE_NOT_FOUND`,
    `ERR_DEVICE_EPISODE_NOT_FOUND`, `ERR_PROCEDURE_NOT_FOUND`,
    `ERR_INFECTION_CASE_NOT_FOUND`, `ERR_DEVICE_DAY_COUNT_NOT_FOUND`,
    `ERR_MONTHLY_SUMMARY_NOT_FOUND`, `ERR_OUTBREAK_NOT_FOUND`,
    `ERR_ISOLATION_ORDER_NOT_FOUND`, `ERR_AUDIT_NOT_FOUND`,
    `ERR_OBSERVATION_NOT_FOUND`, `ERR_EXPOSURE_NOT_FOUND`, or
    `ERR_CAP_NOT_FOUND`, each HTTP 404)."

    Design: Corner/entities/unit_create_with_unknown_facility_returns_not_found
    """
    resp = api.create_unit(
        create_unit_payload(NON_EXISTENT_UUID, name="ICU-X"), admin_headers
    )
    validate_error(resp, ApiErrorId.ERR_FACILITY_NOT_FOUND)


def test_response_envelope_shape_on_success_and_error(api, ip_headers, admin_headers):
    """PRD §2.2: "The `response_type` is either "object" for a single resource or
    "array" for a list of resources."
    PRD §2.2: "Pagination-related fields in `meta` (`limit`, `offset`,
    `total_count`, `has_more`) are included for list endpoints."
    PRD §2.2: "The `meta` object for error responses contains only
    `api_request_id` and `api_request_timestamp`."

    Design: Corner/endpoints/response_envelope_shape_on_success_and_error
    """
    facility, unit = setup_facility_unit()

    obj_resp = api.get_unit(unit["id"], ip_headers)
    obj_body = obj_resp.json()
    assert obj_body["response_type"] == "object"
    assert obj_body["data"]["id"] == unit["id"]
    assert isinstance(obj_body["meta"]["api_request_id"], str) and obj_body["meta"][
        "api_request_id"
    ], "meta.api_request_id must be non-empty"
    assert isinstance(obj_body["meta"]["api_request_timestamp"], str)

    list_resp = api.list_units(ip_headers, params={"facility_id": facility["id"]})
    list_body = list_resp.json()
    assert list_body["response_type"] == "array"
    assert isinstance(list_body["data"], list)
    for field in ("limit", "offset", "total_count", "has_more"):
        assert field in list_body["meta"], f"list meta missing {field}"

    err_resp = api.get_unit(NON_EXISTENT_UUID, ip_headers)
    validate_error(err_resp, ApiErrorId.ERR_UNIT_NOT_FOUND)
    err_body = err_resp.json()
    assert err_body["response_type"] == "error"
    assert err_body["data"]["message"].strip(), "error message must be non-empty"
    assert "api_request_id" in err_body["meta"]
    assert "api_request_timestamp" in err_body["meta"]


def test_not_found_sweep_all_resources(api, admin_headers, ip_headers,
                                       director_headers, nurse_manager_headers,
                                       health_nurse_headers):
    """PRD §2.5: "Path identifiers are validated left to right, and then
    foreign-key identifiers in the request body are validated in payload
    declaration order. The first missing reference produces the resource-specific
    not-found error (`ERR_FACILITY_NOT_FOUND`, `ERR_UNIT_NOT_FOUND`,
    `ERR_PATIENT_NOT_FOUND`, `ERR_EMPLOYEE_NOT_FOUND`,
    `ERR_DEVICE_EPISODE_NOT_FOUND`, `ERR_PROCEDURE_NOT_FOUND`,
    `ERR_INFECTION_CASE_NOT_FOUND`, `ERR_DEVICE_DAY_COUNT_NOT_FOUND`,
    `ERR_MONTHLY_SUMMARY_NOT_FOUND`, `ERR_OUTBREAK_NOT_FOUND`,
    `ERR_ISOLATION_ORDER_NOT_FOUND`, `ERR_AUDIT_NOT_FOUND`,
    `ERR_OBSERVATION_NOT_FOUND`, `ERR_EXPOSURE_NOT_FOUND`, or
    `ERR_CAP_NOT_FOUND`, each HTTP 404)."

    Design: Corner/endpoints/not_found_sweep_all_resources
    """
    facility, unit = setup_facility_unit()
    create_device_day_count(unit["id"], "2026-08-01T00:00:00Z")

    checks = [
        (api.get_infection_case(NON_EXISTENT_UUID, ip_headers),
         ApiErrorId.ERR_INFECTION_CASE_NOT_FOUND),
        (api.submit_summary(NON_EXISTENT_UUID, ip_headers),
         ApiErrorId.ERR_MONTHLY_SUMMARY_NOT_FOUND),
        (api.record_draw(NON_EXISTENT_UUID,
                         {"stage": "BASELINE", "drawn_at": "2026-08-02T10:00:00Z",
                          "result": "NEGATIVE"}, health_nurse_headers),
         ApiErrorId.ERR_EXPOSURE_NOT_FOUND),
        (api.activate_cap(NON_EXISTENT_UUID, ip_headers),
         ApiErrorId.ERR_CAP_NOT_FOUND),
        (api.get_isolation_audit(NON_EXISTENT_UUID, nurse_manager_headers),
         ApiErrorId.ERR_AUDIT_NOT_FOUND),
        (api.get_hand_hygiene_observation(NON_EXISTENT_UUID, nurse_manager_headers),
         ApiErrorId.ERR_OBSERVATION_NOT_FOUND),
        (api.update_device_day_count(
            NON_EXISTENT_UUID,
            {"central_line_days": 1, "urinary_catheter_days": 1, "ventilator_days": 1,
             "patient_days": 10, "expected_device_day_count_version": 1},
            nurse_manager_headers),
         ApiErrorId.ERR_DEVICE_DAY_COUNT_NOT_FOUND),
        (api.remove_device_episode(NON_EXISTENT_UUID,
                                   {"removed_at": "2026-08-05T10:00:00Z"},
                                   nurse_manager_headers),
         ApiErrorId.ERR_DEVICE_EPISODE_NOT_FOUND),
        (api.get_employee(NON_EXISTENT_UUID, health_nurse_headers),
         ApiErrorId.ERR_EMPLOYEE_NOT_FOUND),
        (api.start_isolation_order(NON_EXISTENT_UUID, nurse_manager_headers),
         ApiErrorId.ERR_ISOLATION_ORDER_NOT_FOUND),
        (api.confirm_investigation(NON_EXISTENT_UUID, director_headers),
         ApiErrorId.ERR_OUTBREAK_NOT_FOUND),
        (api.discharge_patient(NON_EXISTENT_UUID,
                               {"discharged_at": "2026-08-10T10:00:00Z"},
                               nurse_manager_headers),
         ApiErrorId.ERR_PATIENT_NOT_FOUND),
        (api.get_surgical_procedure(NON_EXISTENT_UUID, nurse_manager_headers),
         ApiErrorId.ERR_PROCEDURE_NOT_FOUND),
    ]
    for resp, expected_error in checks:
        validate_error(resp, expected_error)


def test_patient_creation_seeds_unit_stay_and_posture_defaults(
    api, nurse_manager_headers
):
    """PRD §3.2: "The new patient starts in `ADMITTED` status with
    `current_unit_id` equal to the admitting unit, and the system seeds the
    patient's `unit_stays` array with a single entry recording that unit, an
    arrival at `admitted_at`, and no departure."
    PRD §3.1: "A new unit begins with `surveillance_posture` set to `NORMAL`."

    Design: Corner/entities/patient_creation_seeds_unit_stay_and_posture_defaults
    """
    facility, unit = setup_facility_unit()
    assert unit["surveillance_posture"] == "NORMAL", (
        f"new unit posture must be NORMAL, got {unit['surveillance_posture']}"
    )

    patient = create_patient(unit["id"], admitted_at="2026-08-01T08:00:00Z")
    assert_patient(patient)
    assert patient["status"] == "ADMITTED"
    assert patient["current_unit_id"] == unit["id"]
    stays = patient["unit_stays"]
    assert len(stays) == 1, f"expected exactly 1 seeded stay, got {len(stays)}"
    assert stays[0]["unit_id"] == unit["id"]
    assert_instant_equal(stays[0]["arrived_at"], "2026-08-01T08:00:00Z", "arrived_at")
    assert stays[0]["departed_at"] is None, "seeded stay must have departed_at null"


def test_patient_state_gates_isolation_transfer_and_discharge(
    api, nurse_manager_headers, ip_headers
):
    """PRD §3.9: "An `InfectionPreventionist` orders isolation for an admitted
    patient — a discharged patient yields `ERR_PATIENT_NOT_ADMITTED` — by
    supplying the `patient_id` and a `precaution_type` of `CONTACT`, `DROPLET`,
    or `AIRBORNE`."
    PRD §3.2: "Transferring a patient requires the patient to be `ADMITTED`
    (otherwise `ERR_PATIENT_NOT_ADMITTED`) and takes `to_unit_id` and
    `transferred_at`; the destination must differ from the patient's current
    unit (`ERR_INVALID_REQUEST` otherwise)."
    PRD §3.2: "Discharge takes `discharged_at`, requires `ADMITTED` status under
    the same `ERR_PATIENT_NOT_ADMITTED` guard, closes the open stay at that
    timestamp, sets the patient's `discharged_at`, moves `current_unit_id` to
    null, and transitions the patient to `DISCHARGED`."

    Design: Corner/validations/patient_state_gates_case_and_transfer
    """
    facility = create_facility()
    unit = create_unit(facility["id"], name="WARD-V6")
    unit_2 = create_unit(facility["id"], name="WARD-V7")
    patient = create_patient(unit["id"])
    discharge_patient(patient["id"], "2026-08-10T10:00:00Z")

    resp_iso = api.create_isolation_order(
        {"patient_id": patient["id"], "precaution_type": "CONTACT"}, ip_headers
    )
    validate_error(resp_iso, ApiErrorId.ERR_PATIENT_NOT_ADMITTED)

    resp_transfer = api.transfer_patient(
        patient["id"],
        {"to_unit_id": unit_2["id"], "transferred_at": "2026-08-11T09:00:00Z"},
        nurse_manager_headers,
    )
    validate_error(resp_transfer, ApiErrorId.ERR_PATIENT_NOT_ADMITTED)

    resp_discharge = api.discharge_patient(
        patient["id"], {"discharged_at": "2026-08-11T10:00:00Z"}, nurse_manager_headers
    )
    validate_error(resp_discharge, ApiErrorId.ERR_PATIENT_NOT_ADMITTED)

    final = validate_success(api.get_patient(patient["id"], nurse_manager_headers))
    assert final["status"] == "DISCHARGED"
    assert final["current_unit_id"] is None
    assert len(final["unit_stays"]) == 1
    assert_instant_equal(
        final["unit_stays"][0]["departed_at"], "2026-08-10T10:00:00Z", "departed_at"
    )
