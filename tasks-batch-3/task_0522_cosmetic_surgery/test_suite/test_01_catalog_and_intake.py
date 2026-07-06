"""Procedure catalog and patient intake: creation, defaults, computed risk, not-found."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    assert_procedure, assert_patient, ApiErrorId, NON_EXISTENT_UUID,
    create_procedure_payload, create_patient_payload,
    TEST_USERS, api_client,
)

ADMIN = TEST_USERS["practice_admin_headers"]
FRONT = TEST_USERS["front_desk_headers"]
SURGEON = TEST_USERS["surgeon_headers"]


def test_create_procedure_returns_201_with_active_defaults(api):
    """PRD §3.1: "A freshly created procedure has active set to true and status of
    ACTIVE." PRD §3.1: "The admin may optionally supply revision_window_days ... it
    defaults to 90 and must be zero or greater."

    Design: Corner/entities/procedure_creation_returns_201_with_fields
    """
    resp = api.create_procedure(create_procedure_payload(
        code="BROW01", name="Brow Lift", surgical_fee_cents=400000,
        facility_fee_cents=100000, anesthesia_fee_cents=90000), ADMIN)
    data = validate_success(resp, 201)
    assert_procedure(data)
    assert data["status"] == "ACTIVE"
    assert data["active"] is True
    assert data["revision_window_days"] == 90
    assert data["surgical_fee_cents"] == 400000


def test_get_procedure_unknown_id_returns_not_found(api):
    """PRD §2.4: "The not-found errors are ERR_PROCEDURE_NOT_FOUND ... each carrying
    HTTP 404."

    Design: Corner/entities/procedure_not_found_returns_404
    """
    resp = api.get_procedure(NON_EXISTENT_UUID, ADMIN)
    validate_error(resp, ApiErrorId.ERR_PROCEDURE_NOT_FOUND, 404)


def test_create_procedure_missing_surgical_fee_returns_validation(api):
    """PRD §2.6: "A request whose body is malformed — a required field absent, or a
    field of the wrong type — is rejected with ERR_VALIDATION (HTTP 400) before any
    business rule is considered."

    Design: Corner/entities/procedure_missing_required_field_returns_validation
    """
    resp = api.create_procedure(
        {"code": "X", "name": "X", "facility_fee_cents": 100000, "anesthesia_fee_cents": 90000},
        ADMIN)
    validate_error(resp, ApiErrorId.ERR_VALIDATION, 400)


def test_patient_defaults_applied_on_create(api):
    """PRD §3.1: "asa_class (the ASA physical status, an integer from 1 through 4)
    defaults to 1, smoker defaults to false, and prior_complication_count (the count
    of prior surgical complications, which must be zero or greater) defaults to 0."
    PRD §3.1: "a score below 40 yields NONE."

    Design: Corner/entities/patient_defaults_applied_on_create
    """
    resp = api.create_patient(create_patient_payload(
        full_name="Def D", date_of_birth="1990-01-01", age_years=34, bmi=24), FRONT)
    data = validate_success(resp, 201)
    assert_patient(data)
    assert data["asa_class"] == 1
    assert data["smoker"] is False
    assert data["prior_complication_count"] == 0
    assert data["surgical_risk_score"] == 0
    assert data["clearance_tier"] == "NONE"


def test_patient_risk_recompute_on_patch_medical_tier(api):
    """PRD §3.1: "whenever a Surgeon updates the clinical fields asa_class, bmi, smoker,
    age_years, or prior_complication_count, the system computes two derived attributes:
    surgical_risk_score and clearance_tier."
    PRD §3.1: "a score of at least 70 yields MEDICAL."

    Design: Corner/entities/patient_risk_recompute_on_patch_medical_tier
    """
    patient = get_success_data(api.create_patient(create_patient_payload(
        full_name="R", date_of_birth="1986-01-01", age_years=40, bmi=25,
        asa_class=1, smoker=False), FRONT))
    resp = api.update_patient(patient["id"], {"asa_class": 3, "smoker": True}, SURGEON)
    data = validate_success(resp, 200)
    # (3-1)*25=50 + smoker 20 = 70 ; >=70 -> MEDICAL
    assert data["surgical_risk_score"] == 70
    assert data["clearance_tier"] == "MEDICAL"


def test_get_patient_unknown_id_returns_not_found(api):
    """PRD §2.4: "The not-found errors are ... ERR_PATIENT_NOT_FOUND ... each carrying
    HTTP 404."

    Design: Corner/entities/patient_not_found_returns_404
    """
    resp = api.get_patient(NON_EXISTENT_UUID, FRONT)
    validate_error(resp, ApiErrorId.ERR_PATIENT_NOT_FOUND, 404)


def test_risk_score_nonlinear_penalties_standard_tier(api):
    """PRD §3.1: "the ASA class contributes 25 points for each step above the minimum
    ... Body mass adds 20 points when bmi is at least 35, or 10 points when bmi is at
    least 30 but below 35 ... A patient who smokes adds 20 points. Age adds 15 points
    when age_years is at least 65, or 8 points when age_years is at least 50 but below
    65 ... a score of at least 40 but below 70 yields STANDARD."

    Design: Difficulty/combinatorial_formula/combinatorial_risk_score_nonlinear_penalties
    """
    resp = api.create_patient(create_patient_payload(
        full_name="Risky R", date_of_birth="1974-01-01", age_years=52, bmi=31,
        asa_class=2, smoker=True, prior_complication_count=0), FRONT)
    data = validate_success(resp, 201)
    # (2-1)*25=25 + bmi31 10 + smoker 20 + age52 8 + prior 0 = 63 ; [40,70) -> STANDARD
    assert data["surgical_risk_score"] == 63
    assert data["clearance_tier"] == "STANDARD"


def test_risk_score_nonlinear_penalties_standard_tier_second_reading(api):
    """PRD §3.1: "The risk score starts at zero and accumulates penalty points ... The
    accumulated total is then clamped to the range 0 through 100 to yield
    surgical_risk_score. From that score the clearance_tier is derived: a score of at
    least 70 yields MEDICAL, a score of at least 40 but below 70 yields STANDARD, and a
    score below 40 yields NONE."

    Design: Difficulty/combinatorial_formula/combinatorial_risk_score_nonlinear_penalties
    """
    data = get_success_data(api.create_patient(create_patient_payload(
        full_name="Risky R2", date_of_birth="1974-01-01", age_years=52, bmi=31,
        asa_class=2, smoker=True, prior_complication_count=0), FRONT))
    assert data["surgical_risk_score"] == 63
    assert data["clearance_tier"] == "STANDARD"
    assert 0 <= data["surgical_risk_score"] <= 100
