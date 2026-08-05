"""Registration, required-field validation, defaults, retrieval, and FK existence.

Corner-design breadth probes over entities and retrieval endpoints.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, NON_EXISTENT_UUID,
    create_clinician_payload, create_patient_payload,
    create_membership_plan_payload, create_membership_payload,
    create_lab_panel_payload,
    assert_clinician, assert_membership,
    TEST_USERS, make_clinician_headers,
)

ADMIN = TEST_USERS["clinic_admin_headers"]


def test_create_clinician_returns_201_with_system_fields(api):
    """PRD §3.1: "A `ClinicAdmin` registers a prescriber as a `Clinician`, supplying
    `full_name`, the provider's `npi`, and the `dea_number` under which controlled
    substances are prescribed."
    PRD §2.4: "The `version` field is an integer that starts at 1 (or its initial
    persisted value) and increments by one on every mutation to the resource".

    Design: Corner/entities/create_clinician_returns_201_envelope_and_system_fields
    """
    data = validate_success(
        api.create_clinician(create_clinician_payload(full_name="Dr Corner"), ADMIN), 201
    )
    assert_clinician(data)
    assert data["version"] == 1, "newly created clinician version must be 1"
    assert data["full_name"] == "Dr Corner"


def test_patient_missing_required_email_returns_validation(api):
    """PRD §3.1: "capturing the patient's `full_name`, `date_of_birth` (a `YYYY-MM-DD`
    string), `sex` (one of `MALE` or `OTHER`), and contact `email`."
    PRD §2.8: "well-formedness of the request body — required fields present, enum
    values legal, numeric values in range (`ERR_VALIDATION`, 400)".

    Design: Corner/entities/patient_missing_required_field_returns_validation
    """
    payload = {"full_name": "No Email", "date_of_birth": "1980-01-01", "sex": "MALE"}
    validate_error(api.create_patient(payload, ADMIN), ApiErrorId.ERR_VALIDATION, 400)


def test_patient_invalid_sex_enum_returns_validation(api):
    """PRD §3.1: "`sex` (one of `MALE` or `OTHER`)".
    PRD §2.8: "well-formedness of the request body — required fields present, enum
    values legal, numeric values in range (`ERR_VALIDATION`, 400)".

    Design: Corner/entities/patient_invalid_sex_enum_returns_validation
    """
    payload = create_patient_payload(sex="FEMALEISH")
    validate_error(api.create_patient(payload, ADMIN), ApiErrorId.ERR_VALIDATION, 400)


def test_membership_created_with_default_statuses_and_credits(api):
    """PRD §3.2: "At creation the membership begins with `subscription_status` of
    `TRIAL` and `payment_status` of `CURRENT`; its `lab_draw_credits_remaining` is
    initialized to the plan's `included_lab_draw_credits`".

    Design: Corner/entities/membership_created_with_default_statuses_and_credits
    """
    patient = validate_success(api.create_patient(create_patient_payload(), ADMIN), 201)
    plan = validate_success(
        api.create_membership_plan(create_membership_plan_payload(included_lab_draw_credits=4), ADMIN), 201
    )
    data = validate_success(
        api.create_membership(create_membership_payload(patient["id"], plan["id"]), ADMIN), 201
    )
    assert_membership(data)
    assert data["subscription_status"] == "TRIAL"
    assert data["payment_status"] == "CURRENT"
    assert data["lab_draw_credits_remaining"] == 4


def test_get_patient_not_found_returns_404(api):
    """PRD §2.6: "The same existence check applies to every identifier supplied in a
    request body — a `patient_id`, `plan_id`, `prescription_id`, `membership_id`,
    `draw_station_id`, `clinician_id`, `plan_id`, or `baseline_panel_id` that does not
    resolve yields `ERR_NOT_FOUND`."
    PRD §2.8: "existence of every referenced identifier, left to right
    (`ERR_NOT_FOUND`, 404)".

    Design: Corner/endpoints/get_patient_not_found_returns_404
    """
    validate_error(api.get_patient(NON_EXISTENT_UUID, ADMIN), ApiErrorId.ERR_NOT_FOUND, 404)


def test_filter_lab_panels_by_patient_id(api):
    """PRD §3.3: "Panels may be listed and filtered by `patient_id` or `clinician_id`."

    Design: Corner/endpoints/filter_lab_panels_by_patient_id_reverse_reachability
    """
    clinician = validate_success(api.create_clinician(create_clinician_payload(), ADMIN), 201)
    patient = validate_success(api.create_patient(create_patient_payload(), ADMIN), 201)
    cln = make_clinician_headers(clinician["id"])
    panel = validate_success(
        api.create_lab_panel(create_lab_panel_payload(patient["id"], clinician["id"]), cln), 201
    )
    data, meta = validate_paginated(api.list_lab_panels(ADMIN, params={"patient_id": patient["id"]}))
    assert meta["total_count"] == 1
    assert any(p["id"] == panel["id"] for p in data), "listed panels must contain the patient's panel"


def test_create_membership_unknown_plan_id_returns_404(api):
    """PRD §2.6: "The same existence check applies to every identifier supplied in a
    request body — a `patient_id`, `plan_id`, `prescription_id`, `membership_id`,
    `draw_station_id`, `clinician_id`, `plan_id`, or `baseline_panel_id` that does not
    resolve yields `ERR_NOT_FOUND`."

    Design: Corner/endpoints/create_membership_unknown_plan_id_returns_404
    """
    patient = validate_success(api.create_patient(create_patient_payload(), ADMIN), 201)
    payload = create_membership_payload(patient["id"], NON_EXISTENT_UUID)
    validate_error(api.create_membership(payload, ADMIN), ApiErrorId.ERR_NOT_FOUND, 404)
