"""The binocular battery: reference bands, immutability, signature and amendment."""

from test_helpers import (
    ApiErrorId,
    amplitude_measurement_payload,
    assert_measurement,
    assert_pct,
    build_battery,
    build_signed_evaluation,
    create_plan_payload,
    finalize,
    make_optometrist_headers,
    new_patient,
    new_therapist,
    npc_measurement_payload,
    open_assessment,
    read_patient,
    set_clock,
    setup_active_plan,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import api_client as _client
from test_helpers import append_measurement, get_success_data


def _ten_year_old_with_optometrist():
    set_clock("2026-06-01T00:00:00Z")
    patient = new_patient(date_of_birth="2016-06-01")
    optometrist = new_therapist(full_name="Dr Lee", credential="OPTOMETRIST")
    return patient, optometrist


def test_amplitude_band_uses_the_standard_variant_on_a_diagnostic_battery(api):
    """PRD §3.1: "When the `purpose` is `DIAGNOSTIC` or `PROGRESS`, the row's
    `reference_variant` is `STANDARD`: `expected_min_value` is 15.0 dioptres less one
    quarter of a dioptre — 0.25 — for each whole year of `patient_age_years`, rounded
    half-up to two decimal places, and `expected_band_high` is that minimum plus a
    band width of 2.00 dioptres, again rounded half-up to two decimals."
    PRD §3.1: "In both variants `within_reference_band` is true when `amplitude_d` is
    at or above `expected_min_value` and at or below `expected_band_high`."

    Design: Difficulty/dual_variant_calc/amplitude_reference_band_standard_versus_functional
    """
    patient, optometrist = _ten_year_old_with_optometrist()
    evaluation = open_assessment(
        patient["id"],
        optometrist["id"],
        assessment_type="EVALUATION",
        purpose="DIAGNOSTIC",
        encounter_date="2026-06-01",
    )
    assert evaluation["patient_age_years"] == 10
    append_measurement(evaluation["id"], npc_measurement_payload(12.0, 16.0), optometrist["id"])

    row = validate_success(
        api.create_measurement(
            evaluation["id"],
            amplitude_measurement_payload(13.00),
            make_optometrist_headers(optometrist["id"]),
        ),
        201,
    )

    assert row["reference_variant"] == "STANDARD"
    assert_pct(row["expected_min_value"], 12.50, "expected_min_value")
    assert_pct(row["expected_band_high"], 14.50, "expected_band_high")
    assert row["within_reference_band"] is True


def test_amplitude_band_uses_the_functional_variant_on_a_discharge_readiness_battery(api):
    """PRD §3.1: "When the `purpose` is `DISCHARGE_READINESS`, the row's
    `reference_variant` is `FUNCTIONAL` and the practice's narrower functional band
    applies: `expected_min_value` is 16.0 dioptres less 0.28 dioptres for each whole
    year of age, rounded half-up to two decimals, and `expected_band_high` is that
    minimum plus a band width of only 1.00 dioptre."
    PRD §3.1: "The two variants really do disagree: at age 10 the standard minimum is
    12.50 dioptres and the functional minimum is 13.20, so an amplitude of 13.00 sits
    inside the standard band and below the functional one."

    Design: Difficulty/dual_variant_calc/amplitude_reference_band_standard_versus_functional
    """
    patient, optometrist = _ten_year_old_with_optometrist()
    evaluation = build_signed_evaluation(
        patient["id"], optometrist["id"], measurements=[npc_measurement_payload(12.0, 16.0)]
    )
    plan = get_success_data(
        _client.create_therapy_plan(
            create_plan_payload(patient["id"], evaluation["id"]),
            make_optometrist_headers(optometrist["id"]),
        )
    )
    reassessment = open_assessment(
        patient["id"],
        optometrist["id"],
        assessment_type="REASSESSMENT",
        purpose="DISCHARGE_READINESS",
        encounter_date="2026-06-01",
        plan_id=plan["id"],
    )
    assert reassessment["patient_age_years"] == 10

    row = validate_success(
        api.create_measurement(
            reassessment["id"],
            amplitude_measurement_payload(13.00),
            make_optometrist_headers(optometrist["id"]),
        ),
        201,
    )

    assert row["reference_variant"] == "FUNCTIONAL"
    assert_pct(row["expected_min_value"], 13.20, "expected_min_value")
    assert_pct(row["expected_band_high"], 14.20, "expected_band_high")
    assert row["within_reference_band"] is False


def test_measurement_with_an_unknown_metric_code_is_an_enum_failure(api):
    """PRD §2.7 rung 4: "This is the exhaustive list of fields that route to
    `ERR_INVALID_ENUM`: `diagnosis_category`, `discharge_reason`, `payer_type`,
    `assessment_type`, `purpose`, `metric_code`, `eye`, `discharge_criteria_mode`,
    `procedure_code`, `cancel_reason`, `item_class`, `returned_condition`,
    `service_class`, `direction`, `urgency`, `response_outcome`, `severity`,
    `close_reason`, `suspension_reason`, `equipment_class`, `credential`, the
    `outcome` supplied on a claim adjudication, and every status-valued filter on a
    list endpoint."

    Design: Corner/entities/measurement_invalid_enum_metric_code_rejected
    """
    patient, optometrist = _ten_year_old_with_optometrist()
    evaluation = open_assessment(patient["id"], optometrist["id"])

    response = api.create_measurement(
        evaluation["id"],
        {"metric_code": "STEREOPSIS", "eye": "OU", "npc_break_cm": 9.0},
        make_optometrist_headers(optometrist["id"]),
    )

    validate_error(response, ApiErrorId.ERR_INVALID_ENUM.value, 400)


def test_measurement_rows_carry_no_version_and_take_their_parent_from_the_path(api):
    """PRD §2.4: "`BinocularMeasurement` is the single exception. A measurement row is
    an immutable instrument reading: it carries `id` and `created_at` only. It has no
    `updated_at` and no `version`, and nothing in the service ever bumps a
    measurement's version, even when finalization recomputes the row's derived fields."
    PRD §2.12: "Where a child's parent identifier also exists as a field on the child —
    `assessment_id` on a measurement, `plan_id` on a phase or a session — the value is
    always taken from the path and never from the request body, and a body attempting
    to set it is ignored rather than honoured."

    Design: Corner/entities/binocular_measurement_is_immutable_and_carries_no_version
    """
    patient, optometrist = _ten_year_old_with_optometrist()
    evaluation = open_assessment(patient["id"], optometrist["id"])

    created = validate_success(
        api.create_measurement(
            evaluation["id"],
            npc_measurement_payload(12.0, 16.0),
            make_optometrist_headers(optometrist["id"]),
        ),
        201,
    )
    assert created["assessment_id"] == evaluation["id"]
    assert_measurement(created)

    rows, meta = validate_paginated(
        api.list_measurements(
            evaluation["id"],
            make_optometrist_headers(optometrist["id"]),
            {"metric_code": "NPC", "limit": 10, "offset": 0},
        )
    )
    assert len(rows) == 1, f"Expected one NPC row, got {len(rows)}"
    assert meta["total_count"] == 1
    for row in rows:
        assert "version" not in row, "A measurement row must not carry version"
        assert "updated_at" not in row, "A measurement row must not carry updated_at"


def test_signing_a_draft_battery_is_an_illegal_transition(api):
    """PRD §3.2: "Signing is reserved to an optometrist and moves the battery
    `FINALIZED → SIGNED`."
    PRD §2.7 rung 14: "**Transition legality.** The target row is in a state from
    which the requested transition is declared, and every state precondition on a
    directly referenced row holds"
    PRD §2.7 rung 14: "Otherwise `ERR_INVALID_STATE`, HTTP 409."

    Design: Corner/state_machines/assessment_sign_from_draft_returns_invalid_state
    """
    patient, optometrist = _ten_year_old_with_optometrist()
    evaluation = open_assessment(patient["id"], optometrist["id"])
    append_measurement(evaluation["id"], npc_measurement_payload(12.0, 16.0), optometrist["id"])

    response = api.sign_assessment(
        evaluation["id"], make_optometrist_headers(optometrist["id"])
    )

    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value, 409)
    stored = validate_success(
        api.get_assessment(evaluation["id"], make_optometrist_headers(optometrist["id"])), 200
    )
    assert stored["status"] == "DRAFT"
    assert stored["signed_by_therapist_id"] is None
    assert read_patient(patient["id"])["clinical_status"] == "INTAKE"


def test_a_third_amendment_is_refused_once_the_cap_is_reached(api):
    """PRD §3.2: "Amendment is an optometrist operation, takes the battery
    `SIGNED → DRAFT`, increments `amendment_count` by 1, clears
    `signed_by_therapist_id` and `signed_at` back to null, bumps `version`, and may
    record a free-text `amendment_reason`."
    PRD §3.2: "It is permitted only while `amendment_count` is still below 2, so the
    loop `DRAFT → FINALIZED → SIGNED → DRAFT` can be walked twice; a third amendment
    is refused with `ERR_INVALID_STATE`, as is any amendment of a battery that is not
    currently `SIGNED`."

    Design: Corner/state_machines/assessment_amend_cap_third_attempt_rejected
    """
    patient, optometrist = _ten_year_old_with_optometrist()
    headers = make_optometrist_headers(optometrist["id"])
    evaluation = build_signed_evaluation(
        patient["id"], optometrist["id"], measurements=[npc_measurement_payload(12.0, 16.0)]
    )

    for reason in ("Transcription error", "Second correction"):
        get_success_data(
            api.amend_assessment(evaluation["id"], {"amendment_reason": reason}, headers)
        )
        finalize(evaluation["id"], optometrist["id"])
        signed = get_success_data(api.sign_assessment(evaluation["id"], headers))

    assert signed["amendment_count"] == 2
    assert signed["status"] == "SIGNED"

    response = api.amend_assessment(
        evaluation["id"], {"amendment_reason": "Third correction"}, headers
    )

    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value, 409)
    stored = validate_success(api.get_assessment(evaluation["id"], headers), 200)
    assert stored["amendment_count"] == 2
    assert stored["status"] == "SIGNED"


def test_signing_the_intake_evaluation_activates_the_patient(api):
    """PRD §3.2: "Signing an `EVALUATION` for a patient still in `clinical_status`
    `INTAKE` is what activates the patient: the patient moves `INTAKE → ACTIVE` and
    the patient's `version` is bumped."
    PRD §3.2: "The signature stamps `signed_by_therapist_id` with the acting
    `X-User-ID` and `signed_at` with the current clock instant, and bumps `version`."
    PRD §3.2: "It is a **diagnostic breach** when `npc_break_cm` is strictly greater
    than 6.0 centimetres or `npc_recovery_cm` is strictly greater than 9.0
    centimetres; the row's `diagnostic_flag` is set to exactly that answer."

    Design: Corner/state_machines/evaluation_signature_promotes_patient_from_intake_to_active
    """
    patient, optometrist = _ten_year_old_with_optometrist()
    headers = make_optometrist_headers(optometrist["id"])
    evaluation = build_battery(
        patient["id"],
        optometrist["id"],
        measurements=[npc_measurement_payload(12.0, 16.0)],
        finalize_it=True,
    )

    assert evaluation["therapy_indicated"] is True
    assert evaluation["discharge_metric_met"] is False
    assert read_patient(patient["id"])["clinical_status"] == "INTAKE"

    signed = validate_success(api.sign_assessment(evaluation["id"], headers), 200)

    assert signed["signed_by_therapist_id"] == optometrist["id"]
    assert signed["signed_at"] is not None
    assert read_patient(patient["id"])["clinical_status"] == "ACTIVE"


def test_a_reassessment_may_not_be_signed_by_the_clinician_who_performed_it(api):
    """PRD §3.2: "On a `REASSESSMENT` the signer must not be the performer: when
    `X-User-ID` equals the battery's `performed_by_therapist_id` the signature is
    refused with `ERR_SEGREGATION_OF_DUTIES`."
    PRD §3.2: "That restriction applies only to a `REASSESSMENT`; an `EVALUATION` may
    be signed by whoever performed it."

    Design: Corner/validations/reassessment_signer_must_differ_from_performer
    """
    scn = setup_active_plan()
    reassessment = build_battery(
        scn["pt"],
        scn["od1"],
        measurements=[npc_measurement_payload(7.0, 9.0)],
        finalize_it=True,
        assessment_type="REASSESSMENT",
        purpose="PROGRESS",
        encounter_date="2026-06-01",
        plan_id=scn["plan"],
    )

    self_signature = api.sign_assessment(reassessment["id"], scn["hdr_od1"])
    validate_error(self_signature, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 409)

    countersigned = validate_success(
        api.sign_assessment(reassessment["id"], scn["hdr_od2"]), 200
    )
    assert countersigned["status"] == "SIGNED"
    assert countersigned["signed_by_therapist_id"] == scn["od2"]
