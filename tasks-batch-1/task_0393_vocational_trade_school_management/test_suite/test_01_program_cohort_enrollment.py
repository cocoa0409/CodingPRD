"""Program/cohort/student creation, defaults, and enrollment preconditions.

Covers corner queue B:
  entities:
    - create_program_returns_all_fields_201
    - get_program_not_found_returns_404
    - create_program_missing_required_field_returns_400
    - create_program_invalid_enum_credential_returns_400
    - create_program_default_sap_thresholds_applied
    - system_fields_minted_on_student_input_ignored
    - duplicate_student_email_returns_409
  state_machines:
    - cohort_create_starts_in_forming
    - cohort_create_under_draft_program_rejected
    - enroll_twice_second_returns_invalid_state
    - terminal_cancelled_agreement_rejects_enroll
    - enroll_admission_prereq_unmet_rejected
    - enroll_into_full_cohort_rejected
  consistency_model:
    - enroll_increments_cohort_count_same_response_cycle
"""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    is_valid_uuid, NON_EXISTENT_UUID, ApiErrorId, TEST_USERS,
    assert_program, assert_cohort, assert_student,
)
from test_helpers import fixtures as fx

ADMIN = TEST_USERS["system_admin_headers"]
REGISTRAR = TEST_USERS["registrar_headers"]


# ==========================================================================
# entities
# ==========================================================================
def test_create_program_returns_all_fields_201(api):
    """PRD §3.1: "A program's status advances through DRAFT, then OPEN, then
    CLOSED. A newly created program is DRAFT."
    PRD §2.4: "an integer version that begins at its initial value on creation
    and increments by one on every mutation."

    Design: Corner/entities/create_program_returns_all_fields_201
    """
    resp = api.create_program(
        {"name": "HVAC", "credential_type": "DIPLOMA", "required_clock_hours": 1000,
         "required_theory_hours": 600, "required_externship_hours": 400, "tuition_cents": 900_000},
        ADMIN)
    data = validate_success(resp, expected_status=201)
    assert_program(data)
    assert data["status"] == "DRAFT", data
    assert data["version"] == 1, data
    assert data["required_clock_hours"] == 1000, data


def test_get_program_not_found_returns_404(api):
    """PRD §2.5: "the first identifier that does not resolve to an existing
    resource causes immediate rejection with ERR_NOT_FOUND before any later
    identifier or business rule is evaluated."

    Design: Corner/entities/get_program_not_found_returns_404
    """
    resp = api.get_program(NON_EXISTENT_UUID, ADMIN)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_create_program_missing_required_field_returns_400(api):
    """PRD §2.5: "request-body well-formedness — required fields present, enums
    drawn from their legal sets, numbers within their ranges — failing with
    ERR_INVALID_REQUEST ..."
    PRD §3.1: "required_clock_hours is the total clock hours required to graduate
    and must be an integer greater than 0."

    Design: Corner/entities/create_program_missing_required_field_returns_400
    """
    resp = api.create_program(
        {"name": "HVAC", "credential_type": "DIPLOMA",
         "required_theory_hours": 600, "required_externship_hours": 400, "tuition_cents": 900_000},
        ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_create_program_invalid_enum_credential_returns_400(api):
    """PRD §2.5: "request-body well-formedness — required fields present, enums
    drawn from their legal sets, numbers within their ranges — failing with
    ERR_INVALID_REQUEST ..."
    PRD §3.1: "a credential_type that is one of DIPLOMA, CERTIFICATE, or
    ASSOCIATE ..."

    Design: Corner/entities/create_program_invalid_enum_credential_returns_400
    """
    resp = api.create_program(
        {"name": "HVAC", "credential_type": "MASTERS", "required_clock_hours": 1000,
         "required_theory_hours": 600, "required_externship_hours": 400, "tuition_cents": 900_000},
        ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_create_program_default_sap_thresholds_applied(api):
    """PRD §3.1: "Three policy ratios may be supplied or left to default:
    sap_warning_min_pace_pct (the minimum completion-pace below which a SAP review
    yields a warning, default 0.667, greater than 0 and at most 1);
    sap_probation_min_pace_pct (the floor below which a review enters the
    probation/dismissal track, default 0.5 ...); and licensure_min_attendance_pct
    (the minimum cumulative attendance fraction for licensure eligibility, default
    0.9, greater than 0 and at most 1)."

    Design: Corner/entities/create_program_default_sap_thresholds_applied
    """
    resp = api.create_program(
        {"name": "HVAC", "credential_type": "DIPLOMA", "required_clock_hours": 1000,
         "required_theory_hours": 600, "required_externship_hours": 400, "tuition_cents": 900_000},
        ADMIN)
    data = validate_success(resp, expected_status=201)
    assert data["sap_warning_min_pace_pct"] == pytest.approx(0.667, abs=1e-9), data
    assert data["sap_probation_min_pace_pct"] == pytest.approx(0.5, abs=1e-9), data
    assert data["licensure_min_attendance_pct"] == pytest.approx(0.9, abs=1e-9), data


def test_system_fields_minted_on_student_create(api):
    """PRD §2.4: "Every resource in the system carries a server-minted id
    formatted as a UUID with no type prefix ..."
    PRD §2.4: "an integer version that begins at its initial value on creation and
    increments by one on every mutation."

    Design: Corner/entities/system_fields_minted_on_student_input_ignored
    """
    resp = api.create_student(
        {"full_name": "Aa Bb", "email": fx.f.unique_email("sysf"), "hs_diploma_verified": True},
        REGISTRAR)
    data = validate_success(resp, expected_status=201)
    assert_student(data)
    assert data["version"] == 1, data
    assert is_valid_uuid(data["id"]), data


def test_duplicate_student_email_returns_409(api):
    """PRD §3.2: "Email is unique on a case-insensitive basis; an attempt to
    create a student whose email collides (ignoring case) with an existing student
    is rejected with ERR_DUPLICATE_KEY."

    Design: Corner/entities/duplicate_student_email_returns_409
    """
    email = fx.f.unique_email("dup")
    validate_success(
        api.create_student({"full_name": "First", "email": email, "hs_diploma_verified": True}, REGISTRAR),
        expected_status=201)
    resp = api.create_student(
        {"full_name": "Second", "email": email.upper(), "hs_diploma_verified": False}, REGISTRAR)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_KEY.value)


# ==========================================================================
# state_machines
# ==========================================================================
def test_cohort_create_starts_in_forming(api):
    """PRD §3.3: "A cohort tracks a computed enrolled_count that begins at 0. Its
    status moves FORMING → RUNNING → COMPLETED."

    Design: Corner/state_machines/cohort_create_starts_in_forming
    """
    program = fx.create_open_program(tuition_cents=900_000)
    resp = api.create_cohort(
        {"program_id": program["id"], "code": fx.f.unique_code(), "start_term_index": 0,
         "end_term_index": 8, "seat_capacity": 5}, REGISTRAR)
    data = validate_success(resp, expected_status=201)
    assert_cohort(data)
    assert data["status"] == "FORMING", data
    assert data["enrolled_count"] == 0, data


def test_cohort_create_under_draft_program_rejected(api):
    """PRD §3.3: "Creating a cohort requires the referenced program to be OPEN;
    otherwise the request is rejected with ERR_PROGRAM_NOT_OPEN."

    Design: Corner/state_machines/cohort_create_under_draft_program_rejected
    """
    program = validate_success(
        api.create_program(fx.f.create_program_payload(tuition_cents=900_000), ADMIN),
        expected_status=201)
    # Program left in DRAFT (never opened).
    resp = api.create_cohort(
        {"program_id": program["id"], "code": fx.f.unique_code(), "start_term_index": 0,
         "end_term_index": 8, "seat_capacity": 5}, REGISTRAR)
    validate_error(resp, ApiErrorId.ERR_PROGRAM_NOT_OPEN.value)


def test_enroll_twice_second_returns_invalid_state(api):
    """PRD §3.3: "Enrolling a drafted agreement requires the agreement to be
    DRAFTED (else ERR_INVALID_STATE) ..."

    Design: Corner/state_machines/enroll_twice_second_returns_invalid_state
    """
    _, _, agreement = fx.setup_enrolled_agreement(
        program_overrides={"tuition_cents": 0},
        agreement_overrides={"contract_tuition_cents": 0})
    resp = api.enroll_agreement(agreement["id"], REGISTRAR)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_terminal_cancelled_agreement_rejects_enroll(api):
    """PRD §3.3: "Cancelling a drafted agreement requires it to be DRAFTED (else
    ERR_INVALID_STATE) and moves it to CANCELLED with no side effects."
    PRD §3.3: "Enrolling a drafted agreement requires the agreement to be DRAFTED
    (else ERR_INVALID_STATE) ..."

    Design: Corner/state_machines/terminal_cancelled_agreement_rejects_enroll
    """
    program, cohort = fx.setup_program_and_cohort(program_overrides={"tuition_cents": 0})
    agr = fx.create_drafted_agreement(cohort["id"], contract_tuition_cents=0)
    validate_success(api.cancel_agreement(agr["id"], REGISTRAR))
    resp = api.enroll_agreement(agr["id"], REGISTRAR)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_enroll_admission_prereq_unmet_rejected(api):
    """PRD §3.3: "Enrolling a drafted agreement requires ... the student's
    hs_diploma_verified to be true (else ERR_ADMISSION_PREREQ_UNMET) ..."

    Design: Corner/state_machines/enroll_admission_prereq_unmet_rejected
    """
    program, cohort = fx.setup_program_and_cohort(program_overrides={"tuition_cents": 0})
    student = fx.create_student(hs_diploma_verified=False)
    agr = fx.create_drafted_agreement(cohort["id"], student_id=student["id"], contract_tuition_cents=0)
    resp = api.enroll_agreement(agr["id"], REGISTRAR)
    validate_error(resp, ApiErrorId.ERR_ADMISSION_PREREQ_UNMET.value)


def test_enroll_into_full_cohort_rejected(api):
    """PRD §3.3: "Enrolling a drafted agreement requires ... the cohort's
    enrolled_count to be strictly less than its seat_capacity (else
    ERR_COHORT_FULL) ..."

    Design: Corner/state_machines/enroll_into_full_cohort_rejected
    """
    program, cohort = fx.setup_program_and_cohort(
        program_overrides={"tuition_cents": 0},
        cohort_overrides={"seat_capacity": 1})
    fx.create_enrolled_agreement(cohort["id"], contract_tuition_cents=0)  # fills the single seat
    agr2 = fx.create_drafted_agreement(cohort["id"], contract_tuition_cents=0)
    resp = api.enroll_agreement(agr2["id"], REGISTRAR)
    validate_error(resp, ApiErrorId.ERR_COHORT_FULL.value)


# ==========================================================================
# consistency_model
# ==========================================================================
def test_enroll_increments_cohort_count_same_cycle(api):
    """PRD §2.8: "Enrolling an agreement increments the parent cohort's
    enrolled_count and bumps the cohort's version."
    PRD §3.3: "on success the agreement moves to ENROLLED, the cohort's
    enrolled_count increases by 1, and the cohort's version increments by 1."

    Design: Corner/consistency_model/enroll_increments_cohort_count_same_response_cycle
    """
    program, cohort = fx.setup_program_and_cohort(program_overrides={"tuition_cents": 0})
    agr = fx.create_drafted_agreement(cohort["id"], contract_tuition_cents=0)
    validate_success(api.enroll_agreement(agr["id"], REGISTRAR))
    cohort_after = validate_success(api.get_cohort(cohort["id"], REGISTRAR))
    assert cohort_after["enrolled_count"] == 1, cohort_after
