"""Patient intake, program creation, candidacy determination, and access control.

Covers difficulty queue A instances (candidacy tier selection, BMI boundary) and
corner queue B instances (computed fields, defaults, not-found, validation, RBAC,
listing, invalid-state).
"""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS,
    create_patient, create_program, create_program_for_new_patient,
    create_operating_room, create_insurance_plan,
    create_patient_payload, create_program_payload, create_operating_room_payload,
    assert_program, assert_operating_room,
    NON_EXISTENT_UUID,
)

PC = TEST_USERS["program_coordinator_headers"]
DT = TEST_USERS["dietitian_headers"]


# ---------------- Difficulty A: candidacy tier selection ----------------

def test_candidacy_qualifies_on_bmi35_comorbidity_tier(api):
    """PRD §3.2: "if the baseline_bmi is at or above the with-comorbidity floor and
    the intersection of the program's documented comorbidities with the accepted set
    is non-empty, the program qualifies on the comorbidity tier: candidacy_status
    becomes QUALIFIED and qualifying_reason becomes BMI_35_PLUS_COMORBIDITY."

    Design: Difficulty/combinatorial_formula/candidacy_bmi35_comorbidity_tier_selection
    """
    prog = create_program_for_new_patient(
        api, payment_pathway="SELF_PAY", comorbidities=["TYPE_2_DIABETES"],
        sex="FEMALE", height_cm=170, baseline_weight_kg=101.15)
    data = validate_success(api.candidacy_review(prog["id"], PC))
    assert data["baseline_bmi"] == 35.0, f"expected baseline_bmi 35.0, got {data['baseline_bmi']}"
    assert data["candidacy_status"] == "QUALIFIED"
    assert data["qualifying_reason"] == "BMI_35_PLUS_COMORBIDITY"


def test_candidacy_bmi35_comorbidity_advances_to_eligible(api):
    """PRD §3.2: "a QUALIFIED result advances the program through CANDIDACY_REVIEW to
    ELIGIBLE, while a NOT_QUALIFIED result advances it to the terminal INELIGIBLE
    state, from which it cannot proceed to clearance."

    Design: Difficulty/combinatorial_formula/candidacy_bmi35_comorbidity_tier_selection
    """
    prog = create_program_for_new_patient(
        api, payment_pathway="SELF_PAY", comorbidities=["TYPE_2_DIABETES"],
        sex="FEMALE", height_cm=170, baseline_weight_kg=101.15)
    data = validate_success(api.candidacy_review(prog["id"], PC))
    assert data["status"] == "ELIGIBLE", f"expected ELIGIBLE, got {data['status']}"


# ---------------- Difficulty A: BMI boundary just below 35 ----------------

def test_candidacy_bmi_just_below_35_not_qualified(api):
    """PRD §3.2: "If neither tier is satisfied, candidacy_status becomes NOT_QUALIFIED
    and qualifying_reason becomes NOT_MET. Both floor comparisons are inclusive — a BMI
    exactly equal to a floor meets it — and are performed against the stored one-decimal
    baseline_bmi."

    Design: Difficulty/boundary_precision_check/candidacy_bmi_just_below_35_not_qualified
    """
    prog = create_program_for_new_patient(
        api, payment_pathway="SELF_PAY", comorbidities=["TYPE_2_DIABETES"],
        sex="FEMALE", height_cm=170, baseline_weight_kg=100)
    data = validate_success(api.candidacy_review(prog["id"], PC))
    assert data["baseline_bmi"] == 34.6, f"expected baseline_bmi 34.6, got {data['baseline_bmi']}"
    assert data["candidacy_status"] == "NOT_QUALIFIED"
    assert data["qualifying_reason"] == "NOT_MET"


def test_candidacy_below_35_advances_to_ineligible(api):
    """PRD §3.2: "a NOT_QUALIFIED result advances it to the terminal INELIGIBLE state,
    from which it cannot proceed to clearance."

    Design: Difficulty/boundary_precision_check/candidacy_bmi_just_below_35_not_qualified
    """
    prog = create_program_for_new_patient(
        api, payment_pathway="SELF_PAY", comorbidities=["TYPE_2_DIABETES"],
        sex="FEMALE", height_cm=170, baseline_weight_kg=100)
    data = validate_success(api.candidacy_review(prog["id"], PC))
    assert data["status"] == "INELIGIBLE", f"expected INELIGIBLE, got {data['status']}"


# ---------------- Corner B: computed fields on program creation ----------------

def test_program_create_computes_baseline_bmi_and_ibw(api):
    """PRD §3.1: "It computes baseline_bmi from the referenced patient's height and
    weight ... the result is stored to one decimal place, rounded half-up ... for a
    FEMALE patient it is 45.5 kilograms plus 2.3 kilograms per inch. This ideal weight
    is stored to three decimal places, rounded half-up."

    Design: Corner/entities/program_create_computes_baseline_bmi_and_ibw
    """
    patient = create_patient(api, sex="FEMALE", height_cm=170, baseline_weight_kg=120)
    data = validate_success(api.create_program(
        create_program_payload(patient["id"], payment_pathway="SELF_PAY"), PC), expected_status=201)
    assert_program(data)
    assert data["baseline_bmi"] == 41.5, f"expected 41.5, got {data['baseline_bmi']}"
    assert data["ideal_body_weight_kg"] == 61.437, f"expected 61.437, got {data['ideal_body_weight_kg']}"
    assert data["status"] == "SCREENING"
    assert data["candidacy_status"] == "UNDETERMINED"
    assert data["version"] == 1


# ---------------- Corner B: default turnover buffer ----------------

def test_operating_room_default_turnover_buffer(api):
    """PRD §3.4: "the room carries a turnover_buffer_minutes value (defaulting to 30)
    representing mandatory cleaning time between cases".

    Design: Corner/entities/operating_room_default_turnover_buffer
    """
    payload = create_operating_room_payload()
    payload.pop("turnover_buffer_minutes", None)
    data = validate_success(api.create_operating_room(payload, TEST_USERS["system_admin_headers"]),
                            expected_status=201)
    assert_operating_room(data)
    assert data["turnover_buffer_minutes"] == 30, f"expected 30, got {data['turnover_buffer_minutes']}"


# ---------------- Corner B: not-found ----------------

def test_program_not_found_on_get(api):
    """PRD §2.8: "a program ERR_PROGRAM_NOT_FOUND ... each with HTTP status 404."

    Design: Corner/entities/program_not_found_on_get_returns_404
    """
    validate_error(api.get_program(NON_EXISTENT_UUID, PC), ApiErrorId.ERR_PROGRAM_NOT_FOUND.value)


def test_patient_not_found_on_program_create(api):
    """PRD §2.8: "body foreign keys (patient_id, ...) are resolved, with the
    corresponding not-found error (404) when any does not reference an existing row ...
    an unresolved patient yields ERR_PATIENT_NOT_FOUND".

    Design: Corner/entities/patient_not_found_on_program_create_returns_404
    """
    validate_error(
        api.create_program(create_program_payload(NON_EXISTENT_UUID, payment_pathway="SELF_PAY"), PC),
        ApiErrorId.ERR_PATIENT_NOT_FOUND.value)


def test_insurance_plan_not_found_on_program_create(api):
    """PRD §2.8: "an insurance plan ERR_INSURANCE_PLAN_NOT_FOUND ... used for both
    path-id and body-foreign-key resolution".

    Design: Corner/entities/insurance_plan_not_found_on_program_create_returns_404
    """
    patient = create_patient(api, sex="MALE", height_cm=180, baseline_weight_kg=140)
    payload = create_program_payload(patient["id"], payment_pathway="INSURANCE",
                                     insurance_plan_id=NON_EXISTENT_UUID)
    validate_error(api.create_program(payload, PC), ApiErrorId.ERR_INSURANCE_PLAN_NOT_FOUND.value)


# ---------------- Corner B: pathway / plan coherence ----------------

def test_pathway_plan_mismatch_self_pay_with_plan(api):
    """PRD §3.1: "A mismatch on this rule — an insurance program with no plan, or a
    self-pay program that supplies one — is rejected with ERR_PATHWAY_PLAN_MISMATCH
    (HTTP 422)."

    Design: Corner/entities/pathway_plan_mismatch_self_pay_with_plan
    """
    plan = create_insurance_plan(api, required_supervised_diet_months=6)
    patient = create_patient(api, sex="MALE", height_cm=180, baseline_weight_kg=140)
    payload = create_program_payload(patient["id"], payment_pathway="SELF_PAY",
                                     insurance_plan_id=plan["id"])
    validate_error(api.create_program(payload, PC), ApiErrorId.ERR_PATHWAY_PLAN_MISMATCH.value)


# ---------------- Corner B: body validation ----------------

def test_patient_create_missing_required_field(api):
    """PRD §2.8: "the request body is checked for structural validity — required fields
    present, enum values in range, correct types, and numeric constraints honored — with
    ERR_VALIDATION (400) on any violation."

    Design: Corner/validations/patient_create_missing_required_field_returns_validation
    """
    payload = create_patient_payload()
    payload.pop("height_cm")
    validate_error(api.create_patient(payload, PC), ApiErrorId.ERR_VALIDATION.value)


def test_program_create_invalid_pathway_enum(api):
    """PRD §2.8: "the request body is checked for structural validity — required fields
    present, enum values in range, correct types ... with ERR_VALIDATION (400) on any
    violation."

    Design: Corner/validations/program_create_invalid_pathway_enum_returns_validation
    """
    patient = create_patient(api, sex="MALE", height_cm=180, baseline_weight_kg=140)
    payload = create_program_payload(patient["id"], payment_pathway="CASH")
    validate_error(api.create_program(payload, PC), ApiErrorId.ERR_VALIDATION.value)


# ---------------- Corner B: invalid program-state transitions ----------------

def test_request_clearance_from_screening_returns_invalid_state(api):
    """PRD §3.3: "This transition is permitted only from ELIGIBLE; from any other state
    it is rejected with ERR_INVALID_PROGRAM_STATE (HTTP 409)."

    Design: Corner/state_machines/request_clearance_from_screening_returns_invalid_state
    """
    prog = create_program_for_new_patient(api, payment_pathway="SELF_PAY")
    validate_error(api.request_clearance(prog["id"], PC), ApiErrorId.ERR_INVALID_PROGRAM_STATE.value)


def test_candidacy_review_twice_returns_invalid_state(api):
    """PRD §3.2: "This action is permitted only while the program is in SCREENING;
    attempting it from any other state is rejected with ERR_INVALID_PROGRAM_STATE
    (HTTP 409)."

    Design: Corner/state_machines/candidacy_review_twice_returns_invalid_state
    """
    prog = create_program_for_new_patient(api, payment_pathway="SELF_PAY")
    validate_success(api.candidacy_review(prog["id"], PC))
    validate_error(api.candidacy_review(prog["id"], PC), ApiErrorId.ERR_INVALID_PROGRAM_STATE.value)


# ---------------- Corner B: access control ----------------

def test_unauthenticated_missing_headers_returns_401(api):
    """PRD §2.1: "If either header is missing, or if X-User-Role is not one of the
    recognized role names, the request is rejected with ERR_UNAUTHENTICATED (HTTP 401)."

    Design: Corner/rbac/unauthenticated_missing_headers_returns_401
    """
    validate_error(api.get_program(NON_EXISTENT_UUID, {}), ApiErrorId.ERR_UNAUTHENTICATED.value)


def test_unauthorized_dietitian_creates_patient_returns_403(api):
    """PRD §2.1: "When the headers are well-formed but the role is not permitted to
    perform the requested operation, the request is rejected with ERR_UNAUTHORIZED
    (HTTP 403)."

    Design: Corner/rbac/unauthorized_dietitian_creates_patient_returns_403
    """
    validate_error(api.create_patient(create_patient_payload(), DT), ApiErrorId.ERR_UNAUTHORIZED.value)


# ---------------- Corner B: listing / pagination ----------------

def test_list_programs_returns_pagination_envelope(api):
    """PRD §2.3: "The meta block of a list response reports limit, offset, total_count
    (the total number of matching records before pagination), and has_more (true when
    records beyond the current page remain)."

    Design: Corner/endpoints/list_programs_returns_pagination_envelope
    """
    patient = create_patient(api, sex="MALE", height_cm=180, baseline_weight_kg=150)
    prog = create_program(api, patient_id=patient["id"], payment_pathway="SELF_PAY")
    data, meta = validate_paginated(api.list_programs(PC, params={"patient_id": patient["id"]}))
    assert any(p["id"] == prog["id"] for p in data), "created program must appear in the listing"
    assert "total_count" in meta and "has_more" in meta
