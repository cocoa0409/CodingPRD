"""Patient registration, record identity and the logical clock's default reading."""

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_patient,
    assert_same_instant,
    assert_three_fractional_digits,
    create_patient_payload,
    is_valid_uuid,
    make_clinic_admin_headers,
    make_front_desk_headers,
    make_optometrist_headers,
    new_patient,
    new_therapist,
    open_assessment,
    set_clock,
    validate_error,
    validate_success,
)


def test_registered_patient_opens_in_intake_with_server_minted_identity(api):
    """PRD §3.1: "The new record begins life in `clinical_status` `INTAKE`, with
    `discharge_reason`, `discharged_at` and `discharged_by_user_id` all null."
    PRD §2.4: "Every resource is created with a server-minted `id`: a UUID string
    carrying no type prefix."
    PRD §2.4: "Most resources additionally carry `updated_at`, in the same ISO 8601
    UTC format with three fractional digits, and `version`, an integer that begins
    at 1 when the row is created and increments by exactly 1 on every mutation of
    that row."

    Design: Corner/entities/patient_creation_starts_in_intake_with_system_fields
    """
    set_clock("2026-06-01T00:00:00Z")

    response = api.create_patient(create_patient_payload(), make_front_desk_headers())
    data = validate_success(response, 201)

    assert_patient(data)
    assert data["clinical_status"] == "INTAKE"
    assert data["version"] == 1, f"Expected version 1 on creation, got {data['version']}"
    assert data["discharge_reason"] is None
    assert data["discharged_at"] is None
    assert data["discharged_by_user_id"] is None
    assert is_valid_uuid(data["id"]) and "_" not in data["id"]

    body = response.json()
    assert body["response_type"] == "object"
    assert body["meta"]["api_request_id"].startswith("req_")
    assert_three_fractional_digits(
        body["meta"]["api_request_timestamp"], "meta.api_request_timestamp"
    )


def test_patient_read_returns_the_stored_guardian_and_diagnosis(api):
    """PRD §3.1: "Reception or the clinic administrator registers a patient with a
    `full_name`, a `date_of_birth` given as an ISO 8601 calendar date, and a
    `diagnosis_category` drawn from `CONVERGENCE_INSUFFICIENCY`,
    `ACCOMMODATIVE_DYSFUNCTION`, `OCULOMOTOR_DYSFUNCTION` and `AMBLYOPIA`."
    PRD §3.1: "A `guardian_name` may be supplied for a minor and defaults to null
    when it is not."

    Design: Corner/entities/patient_retrieval_returns_stored_row
    """
    set_clock("2026-06-01T00:00:00Z")
    patient = new_patient(diagnosis_category="AMBLYOPIA", guardian_name="Marta Ruiz")

    data = validate_success(api.get_patient(patient["id"], make_front_desk_headers()), 200)

    assert data["guardian_name"] == "Marta Ruiz"
    assert data["diagnosis_category"] == "AMBLYOPIA"
    assert data["id"] == patient["id"]


def test_reading_an_unknown_patient_reports_patient_not_found(api):
    """PRD §2.7 rung 5: "**Patient existence.** The `Patient` named in the path, or
    in a `patient_id` field, exists. Otherwise `ERR_PATIENT_NOT_FOUND`, HTTP 404."

    Design: Corner/entities/patient_get_with_unknown_uuid_not_found
    """
    set_clock("2026-06-01T00:00:00Z")

    response = api.get_patient(NON_EXISTENT_UUID, make_front_desk_headers())

    validate_error(response, ApiErrorId.ERR_PATIENT_NOT_FOUND.value, 404)
    assert response.json()["response_type"] == "error"


def test_registering_a_patient_without_a_date_of_birth_is_a_shape_failure(api):
    """PRD §2.7 rung 3: "**Shape and range.** Required body fields are present and
    well typed."
    PRD §3.1: "Reception or the clinic administrator registers a patient with a
    `full_name`, a `date_of_birth` given as an ISO 8601 calendar date, and a
    `diagnosis_category` drawn from `CONVERGENCE_INSUFFICIENCY`,
    `ACCOMMODATIVE_DYSFUNCTION`, `OCULOMOTOR_DYSFUNCTION` and `AMBLYOPIA`."

    Design: Corner/entities/patient_create_missing_required_field_returns_invalid_request
    """
    set_clock("2026-06-01T00:00:00Z")

    response = api.create_patient(
        {"full_name": "Ana Ruiz", "diagnosis_category": "CONVERGENCE_INSUFFICIENCY"},
        make_front_desk_headers(),
    )

    validate_error(response, ApiErrorId.ERR_VALIDATION.value, 400)


def test_assessment_age_and_system_fields_are_computed_by_the_server(api):
    """PRD §3.1: "`patient_age_years` is the number of whole calendar years from the
    patient's `date_of_birth` to the `encounter_date`: take the encounter year minus
    the birth year, and subtract one more year when the encounter's month-and-day
    pair falls before the birth date's month-and-day pair."
    PRD §3.1: "A binocular battery is opened by an optometrist or a vision therapist
    against a `patient_id`, and is created in `status` `DRAFT`."
    PRD §2.4: "Every resource also carries `created_at`, an ISO 8601 UTC timestamp
    with exactly three fractional-second digits, stamped from the logical clock
    described in §2.5 at the moment the row is written."

    Design: Corner/entities/system_fields_are_server_generated_and_client_input_ignored
    """
    set_clock("2026-06-01T00:00:00Z")
    patient = new_patient(date_of_birth="2016-06-01")
    optometrist = new_therapist(full_name="Dr Lee", credential="OPTOMETRIST")

    data = validate_success(
        api.create_assessment(
            {
                "patient_id": patient["id"],
                "assessment_type": "EVALUATION",
                "purpose": "DIAGNOSTIC",
                "encounter_date": "2026-06-01",
                "performed_by_therapist_id": optometrist["id"],
            },
            make_optometrist_headers(optometrist["id"]),
        ),
        201,
    )

    assert data["patient_age_years"] == 10
    assert data["status"] == "DRAFT"
    assert data["version"] == 1
    assert_three_fractional_digits(data["created_at"], "Assessment.created_at")
    assert_three_fractional_digits(data["updated_at"], "Assessment.updated_at")
    assert_same_instant(data["created_at"], "2026-06-01T00:00:00Z", "Assessment.created_at")


def test_logical_clock_reads_the_declared_default_before_any_set_call(api):
    """PRD §2.5: "It maintains a single logical UTC clock which, before any caller
    has set it, reads exactly `2026-05-01T00:00:00Z`."
    PRD §3.11: "`sla_due_at` is the creation instant advanced by twenty-four hours
    for an `URGENT` referral and by one hundred and twenty hours for a `ROUTINE` one."
    PRD §2.5: "A `ClinicAdmin` moves the clock by supplying a `to_iso8601` instant;
    the endpoint answers with a body of the shape `{ current_utc: string }` carrying
    the new reading."

    Design: Corner/endpoints/logical_clock_defaults_to_2026_05_01_before_any_set_call
    """
    patient = new_patient()

    referral = validate_success(
        api.create_referral(
            {
                "patient_id": patient["id"],
                "direction": "INBOUND",
                "urgency": "ROUTINE",
                "referring_provider_name": "Dr Amara Family Eyecare",
                "target_provider_name": "Vision Therapy Clinic",
                "reason": "Convergence insufficiency workup",
            },
            make_front_desk_headers(),
        ),
        201,
    )

    assert referral["status"] == "SENT"
    assert_same_instant(
        referral["sla_due_at"], "2026-05-06T00:00:00Z", "Referral.sla_due_at"
    )

    clock = validate_success(
        api.set_clock("2026-06-01T00:00:00Z", make_clinic_admin_headers()), 200
    )
    assert_same_instant(clock["current_utc"], "2026-06-01T00:00:00Z", "current_utc")
