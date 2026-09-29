"""Patient admission defaults, the two-state patient machine and the patient
version token that guards bedside assessment filing."""
from test_helpers import (
    as_instant,
    assert_patient,
    assign_consult,
    create_candidate_nurse,
    create_consult,
    create_unit,
    get_success_data,
    triage_consult,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.constants import UNKNOWN_UNIT_ID
from test_helpers.test_users import (
    make_director_headers,
    make_nurse_headers,
    make_unit_charge_headers,
)


DIRECTOR = make_director_headers()


def test_the_three_optional_clinical_flags_default_together(api):
    """Admission with only the required trio leaves every risk input at its floor.

    PRD §3.2: "Three optional clinical flags round out the record and all three
    feed the acuity calculation. `comorbidity_count` counts acuity-relevant
    comorbidities, defaults to 0, and must be between 0 and 10 inclusive.
    `device_related_risk` defaults to false and is set true when a medical device —
    a tracheostomy collar, a brace, a length of tubing — sits over an at-risk skin
    site. `ostomy_present` defaults to false and is set true when the patient has a
    stoma; it is a hard precondition for opening an ostomy education plan."
    PRD §3.2: "`poa_skin_assessment_documented` starts false and is flipped to true
    the first time any skin assessment for that patient reaches a validated staging
    with a present-on-admission determination."

    Design: Corner/entities/patient_optional_risk_flags_default_to_zero_and_false
    """
    unit = create_unit(
        api,
        unit_code="3E",
        name="Three East",
        bed_count=18,
        rental_budget_cap_cents=250000,
    )
    data = validate_success(
        api.create_patient(
            {"mrn": "MRN-D1", "unit_id": unit["id"], "admitted_at": "2026-07-31T00:00:00Z"},
            make_unit_charge_headers(unit["id"]),
        ),
        expected_status=201,
    )
    assert data["comorbidity_count"] == 0
    assert data["device_related_risk"] is False
    assert data["ostomy_present"] is False
    assert data["status"] == "ADMITTED"
    assert data["discharged_at"] is None
    assert data["version"] == 1
    assert data["poa_skin_assessment_documented"] is False
    assert data["pending_outpatient_followup_count"] == 0
    assert data["unit_id"] == unit["id"]
    assert data["mrn"] == "MRN-D1"
    assert_patient(data)


def test_reading_a_patient_echoes_the_stored_row_without_mutating_it(api):
    """The single-patient read returns the whole record and bumps nothing.

    PRD §3.2: "Reading a single patient returns the full record including
    `version`, and that read is how a client seeds the `expected_patient_version`
    value described in §2.6."

    Design: Corner/entities/patient_get_by_id_returns_stored_row
    """
    unit = create_unit(
        api,
        unit_code="3E",
        name="Three East",
        bed_count=18,
        rental_budget_cap_cents=250000,
    )
    charge = make_unit_charge_headers(unit["id"])
    created = validate_success(
        api.create_patient(
            {
                "mrn": "MRN-D2",
                "unit_id": unit["id"],
                "admitted_at": "2026-07-30T06:00:00Z",
                "comorbidity_count": 3,
                "device_related_risk": True,
                "ostomy_present": True,
            },
            charge,
        ),
        expected_status=201,
    )
    nurse = create_candidate_nurse(unit, api=api)

    response = api.get_patient(created["id"], make_nurse_headers(nurse["id"]))
    data = validate_success(response)
    assert response.json()["response_type"] == "object"
    assert data["id"] == created["id"]
    assert data["mrn"] == "MRN-D2"
    assert as_instant(data["admitted_at"]) == as_instant("2026-07-30T06:00:00Z")
    assert data["comorbidity_count"] == 3
    assert data["device_related_risk"] is True
    assert data["ostomy_present"] is True
    assert data["version"] == 1, "a GET performs no mutation, so no version increment"
    assert data["status"] == "ADMITTED"
    assert data["unit_id"] == unit["id"]


def test_admitting_onto_an_unknown_unit_reports_the_units_own_not_found(api):
    """A body foreign key that resolves to nothing is refused with the parent's code.

    PRD §2.5: "Foreign-key identifiers supplied inside a request body are resolved
    after every path identifier has resolved, and they are resolved in the order in
    which the endpoint declares them."
    PRD §2.5: "The same not-found codes apply, keyed by what the reference points at
    rather than by the field name: a payload `patient_id`, `unit_id`,
    `home_unit_id`, `requesting_unit_id`, `assigned_nurse_id`, `rca_lead_nurse_id`,
    `observer_nurse_id`, `consult_request_id`, `support_surface_id`,
    `formulary_product_id`, `survey_round_id` or `skin_assessment_id` that matches
    no row yields the not-found code for that row's type."

    Design: Corner/entities/patient_create_with_unknown_unit_id_returns_unit_not_found
    """
    validate_error(
        api.create_patient(
            {
                "mrn": "MRN-X1",
                "unit_id": UNKNOWN_UNIT_ID,
                "admitted_at": "2026-07-31T00:00:00Z",
            },
            make_unit_charge_headers(UNKNOWN_UNIT_ID),
        ),
        "ERR_UNIT_NOT_FOUND",
        expected_status=404,
    )
    _, meta = validate_paginated(api.list_patients(DIRECTOR))
    assert meta["total_count"] == 0, "the refused admission inserted no row"


def test_discharge_flips_the_status_and_stamps_the_supplied_instant(api):
    """The only two-state machine in the service moves once and stamps once.

    PRD §3.2: "A patient's `status` begins at `ADMITTED`. Discharge moves it
    `ADMITTED → DISCHARGED`, stamping the supplied `discharged_at` onto the record."
    PRD §3.2: "The supplied `discharged_at` must be at or after `admitted_at`."

    Design: Corner/state_machines/patient_discharge_moves_admitted_to_discharged
    """
    unit = create_unit(
        api,
        unit_code="3E",
        name="Three East",
        bed_count=18,
        rental_budget_cap_cents=250000,
    )
    charge = make_unit_charge_headers(unit["id"])
    patient = validate_success(
        api.create_patient(
            {"mrn": "MRN-G1", "unit_id": unit["id"], "admitted_at": "2026-07-31T00:00:00Z"},
            charge,
        ),
        expected_status=201,
    )
    data = validate_success(
        api.discharge_patient(
            patient["id"], {"discharged_at": "2026-08-02T00:00:00Z"}, charge
        )
    )
    assert data["status"] == "DISCHARGED"
    assert as_instant(data["discharged_at"]) == as_instant("2026-08-02T00:00:00Z")
    assert as_instant(data["admitted_at"]) == as_instant("2026-07-31T00:00:00Z"), "admission is not rewritten"
    assert data["version"] == 2, "exactly one increment"
    assert get_success_data(api.get_unit(unit["id"], DIRECTOR))["version"] == 1, (
        "discharging a patient touches no unit counter"
    )


def test_discharging_a_discharged_patient_is_refused_and_writes_nothing(api):
    """`DISCHARGED` is terminal and carries its own domain-specific refusal.

    PRD §3.2: "Discharging a patient who is already `DISCHARGED` is refused with
    `ERR_PATIENT_DISCHARGED`, which is also the code raised whenever any clinical
    write — a new consult, a triage, an assignment, a bedside assessment, a survey
    observation or a rental order — is attempted against a discharged patient."
    PRD §2.10 rung 16: "The patient's `status` is `ADMITTED` wherever a clinical
    write is attempted against them — `ERR_PATIENT_DISCHARGED` (409), on
    `POST /consult-requests`, `POST /consult-requests/{consult_id}/triage`,
    `POST /consult-requests/{consult_id}/assign`, `POST /skin-assessments`,
    `POST /support-surface-orders`, `POST /survey-observations` and
    `POST /patients/{patient_id}/discharge`."

    Design: Corner/state_machines/second_discharge_of_same_patient_rejected
    """
    unit = create_unit(
        api,
        unit_code="3E",
        name="Three East",
        bed_count=18,
        rental_budget_cap_cents=250000,
    )
    charge = make_unit_charge_headers(unit["id"])
    patient = validate_success(
        api.create_patient(
            {"mrn": "MRN-G4", "unit_id": unit["id"], "admitted_at": "2026-07-31T00:00:00Z"},
            charge,
        ),
        expected_status=201,
    )
    validate_success(
        api.discharge_patient(
            patient["id"], {"discharged_at": "2026-08-02T00:00:00Z"}, charge
        )
    )

    validate_error(
        api.discharge_patient(
            patient["id"], {"discharged_at": "2026-08-03T00:00:00Z"}, charge
        ),
        "ERR_PATIENT_DISCHARGED",
        expected_status=409,
    )
    after = get_success_data(api.get_patient(patient["id"], charge))
    assert as_instant(after["discharged_at"]) == as_instant("2026-08-02T00:00:00Z"), (
        "the refused second discharge did not overwrite the stamp"
    )
    assert after["version"] == 2, "the refused second discharge performed no write"


def test_a_patient_token_goes_stale_after_the_first_filing_and_works_after_reread(api):
    """The token that filed the first assessment is stale for the second one.

    PRD §2.6: "Filing a bedside skin assessment requires a non-optional
    `expected_patient_version` field in the payload, carrying the `version` the
    client last observed on that patient. If it does not equal the patient's current
    `version`, the assessment is not created and the request is rejected with
    `ERR_STALE_PATIENT_VERSION` (HTTP 412)."
    PRD §2.6: "This guard exists because a second assessment for the same patient
    and body site legitimately supersedes the first, so no state precondition would
    stop the write; the stale-version check is what stops a writer whose view of the
    patient predates that supersession from silently discarding it."
    PRD §3.5: "And it versions the patient row, which is precisely why a client's
    `expected_patient_version` goes stale after each filing."

    Design: Corner/cross_cutting_complexity_layers/stale_expected_patient_version_rejected_then_accepted_after_reread
    """
    unit = create_unit(
        api,
        unit_code="OCC-U1",
        name="OCC Probe Med-Surg",
        bed_count=20,
        rental_budget_cap_cents=100000,
    )
    charge = make_unit_charge_headers(unit["id"])
    patient = validate_success(
        api.create_patient(
            {
                "mrn": "OCCMRN0001",
                "unit_id": unit["id"],
                "admitted_at": "2026-07-31T00:00:00Z",
                "comorbidity_count": 0,
                "device_related_risk": False,
                "ostomy_present": False,
            },
            charge,
        ),
        expected_status=201,
    )
    original_token = patient["version"]
    assert original_token == 1
    nurse = create_candidate_nurse(unit, api=api, full_name="Omar Concurrent", ce_credits=30)
    nurse_headers = make_nurse_headers(nurse["id"])
    consult = create_consult(
        unit,
        patient,
        api=api,
        consult_type="WOUND",
        reported_stage="STAGE_2",
        clinical_note="Non-blanchable sacral erythema found on the 06:00 turn.",
    )
    triage_consult(consult, nurse, api=api)
    assign_consult(consult, nurse, api=api)

    first = validate_success(
        api.create_skin_assessment(
            {
                "consult_request_id": consult["id"],
                "patient_id": patient["id"],
                "anatomic_location": "SACRUM",
                "observed_stage": "STAGE_2",
                "measured_area_cm2": 6.0,
                "observed_at": "2026-08-01T00:00:00Z",
                "expected_patient_version": original_token,
                "present_on_admission_claimed": False,
            },
            nurse_headers,
        ),
        expected_status=201,
    )
    assert first["validation_status"] == "PENDING_VALIDATION"
    assert first["staged_by_nurse_id"] == nurse["id"]
    assert get_success_data(api.get_patient(patient["id"], charge))["version"] == 2
    after_first = get_success_data(api.get_consult_request(consult["id"], charge))
    assert after_first["status"] == "ASSESSED"
    assert after_first["acuity_score"] == 35.0
    assert after_first["priority_band"] == "P3"

    stale_payload = {
        "consult_request_id": consult["id"],
        "patient_id": patient["id"],
        "anatomic_location": "SACRUM",
        "observed_stage": "STAGE_3",
        "measured_area_cm2": 8.0,
        "observed_at": "2026-08-01T00:00:00Z",
        "expected_patient_version": original_token,
        "present_on_admission_claimed": False,
    }
    validate_error(
        api.create_skin_assessment(stale_payload, nurse_headers),
        "ERR_STALE_PATIENT_VERSION",
        expected_status=412,
    )
    assert get_success_data(api.get_patient(patient["id"], charge))["version"] == 2, (
        "a rejected filing bumps nothing"
    )
    _, meta = validate_paginated(
        api.list_skin_assessments(nurse_headers, {"patient_id": patient["id"]})
    )
    assert meta["total_count"] == 1, "the rejected filing inserted no row"
    assert (
        get_success_data(api.get_skin_assessment(first["id"], nurse_headers))["validation_status"]
        == "PENDING_VALIDATION"
    )
    assert get_success_data(api.get_consult_request(consult["id"], charge))["acuity_score"] == 35.0

    reread = validate_success(api.get_patient(patient["id"], charge))
    assert reread["version"] == 2

    retry_payload = dict(stale_payload, expected_patient_version=reread["version"])
    second = validate_success(
        api.create_skin_assessment(retry_payload, nurse_headers), expected_status=201
    )
    assert second["validation_status"] == "PENDING_VALIDATION"
    assert (
        get_success_data(api.get_skin_assessment(first["id"], nurse_headers))["validation_status"]
        == "SUPERSEDED"
    ), "the state machine always allowed the supersession; only the stale token blocked it"
    assert get_success_data(api.get_patient(patient["id"], charge))["version"] == 3

    final_consult = get_success_data(api.get_consult_request(consult["id"], charge))
    assert final_consult["version"] == 5, (
        "one create, one triage, one assign and one per accepted assessment"
    )
    assert final_consult["acuity_score"] == 60.0, "recomputed from the new row alone"
    assert final_consult["priority_band"] == "P2"

    _, case_meta = validate_paginated(
        api.list_pressure_injury_cases(DIRECTOR, {"patient_id": patient["id"]})
    )
    assert case_meta["total_count"] == 2, "each accepted assessment opened its own case file"
