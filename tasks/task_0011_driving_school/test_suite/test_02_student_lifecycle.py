"""Student onboarding lifecycle: PENDING_VERIFICATION → ... → ACTIVE, plus
suspend/reinstate (PRD §3.1)."""
import pytest
from datetime import timedelta

from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    create_student_payload,
    create_default_package,
    create_pending_student,
    create_active_student,
    medical_cert_payload,
    select_package_payload,
    iso_z,
    _server_clock_now,
    ADMIN_HEADERS,
    assert_student,
)


class TestStudentEnrollmentHappyPath:
    """PRD §3.1 — the four-stage onboarding."""

    def test_create_student_initial_defaults(self, api):
        """PRD §3.1: "A student record is created at PENDING_VERIFICATION, holding
        only the inputs full_name, id_number, and id_card_country together with
        the system-managed defaults — id_verified is false, medical_cert_status
        is PENDING, enrollment_status is PENDING_VERIFICATION, training_stage is
        THEORY, no_show_count_this_cycle and reschedule_count_this_cycle are
        both 0, has_passed_theory and has_passed_basic_practical are both false,
        and suspension_reason is null."
        """
        resp = api.create_student(create_student_payload(), ADMIN_HEADERS)
        assert resp.status_code == 201
        data = validate_success(resp, expected_status=201)
        assert_student(data)
        assert data["enrollment_status"] == "PENDING_VERIFICATION"
        assert data["id_verified"] is False
        assert data["medical_cert_status"] == "PENDING"
        assert data["training_stage"] == "THEORY"
        assert data["no_show_count_this_cycle"] == 0
        assert data["reschedule_count_this_cycle"] == 0
        assert data["has_passed_theory"] is False
        assert data["has_passed_basic_practical"] is False
        assert data["suspension_reason"] is None

    def test_verify_identity_advances_state(self, api):
        """PRD §3.1: "Identity verification advances enrollment_status from
        PENDING_VERIFICATION to PENDING_MEDICAL ... the side-effect sets
        id_verified to true."
        """
        student = create_pending_student(api)
        resp = api.verify_identity(student["id"], ADMIN_HEADERS)
        data = validate_success(resp)
        assert data["enrollment_status"] == "PENDING_MEDICAL"
        assert data["id_verified"] is True

    def test_submit_medical_cert_advances_and_sets_valid(self, api):
        """PRD §3.1: "Medical-certificate validation advances enrollment_status
        from PENDING_MEDICAL to PENDING_PACKAGE ... The side-effect sets
        medical_cert_status to VALID."
        """
        student = create_pending_student(api)
        get_success_data(api.verify_identity(student["id"], ADMIN_HEADERS))
        now = _server_clock_now(api)
        expires = (now + timedelta(days=180)).strftime("%Y-%m-%d")
        resp = api.submit_medical_cert(student["id"], medical_cert_payload(expires), ADMIN_HEADERS)
        data = validate_success(resp)
        assert data["enrollment_status"] == "PENDING_PACKAGE"
        assert data["medical_cert_status"] == "VALID"

    def test_select_package_advances_state(self, api):
        """PRD §3.1: "Course-package selection advances enrollment_status from
        PENDING_PACKAGE to PENDING_CONTRACT."
        """
        student = create_pending_student(api)
        get_success_data(api.verify_identity(student["id"], ADMIN_HEADERS))
        now = _server_clock_now(api)
        expires = (now + timedelta(days=180)).strftime("%Y-%m-%d")
        get_success_data(api.submit_medical_cert(student["id"], medical_cert_payload(expires), ADMIN_HEADERS))
        package = create_default_package(api)
        resp = api.select_package(student["id"], select_package_payload(package["id"]), ADMIN_HEADERS)
        data = validate_success(resp)
        assert data["enrollment_status"] == "PENDING_CONTRACT"
        assert data["course_package_id"] == package["id"]

    def test_sign_contract_activates(self, api):
        """PRD §3.1: "Contract signing advances enrollment_status from
        PENDING_CONTRACT to ACTIVE ... contract_signed_at is set to the logical
        clock; cycle_start_date is set to the logical clock; training_stage is
        set to THEORY."
        """
        student, _ = create_active_student(api)
        assert student["enrollment_status"] == "ACTIVE"
        assert student["contract_signed_at"] is not None
        assert student["cycle_start_date"] is not None
        assert student["training_stage"] == "THEORY"


class TestStudentEnrollmentErrors:

    def test_verify_identity_at_wrong_state(self, api):
        """PRD §3.1: "If the student is not at PENDING_VERIFICATION when this is
        invoked, the request is rejected with ERR_STUDENT_NOT_AT_PENDING_STATE."
        """
        student = create_pending_student(api)
        get_success_data(api.verify_identity(student["id"], ADMIN_HEADERS))
        # Already at PENDING_MEDICAL — second call rejected
        resp = api.verify_identity(student["id"], ADMIN_HEADERS)
        validate_error(resp, ApiErrorId.ERR_STUDENT_NOT_AT_PENDING_STATE.value)

    def test_submit_expired_medical_cert_rejected(self, api):
        """PRD §3.1: "an expired or same-day expiry is rejected with
        ERR_MEDICAL_CERT_EXPIRED."
        """
        student = create_pending_student(api)
        get_success_data(api.verify_identity(student["id"], ADMIN_HEADERS))
        now = _server_clock_now(api)
        # same-day → rejected
        same_day = now.strftime("%Y-%m-%d")
        resp = api.submit_medical_cert(student["id"], medical_cert_payload(same_day), ADMIN_HEADERS)
        validate_error(resp, ApiErrorId.ERR_MEDICAL_CERT_EXPIRED.value)

    def test_select_unknown_package_rejected(self, api):
        """PRD §3.1: "course_package_id, which must resolve to an existing
        package; otherwise the request is rejected with ERR_PACKAGE_NOT_FOUND."
        """
        from test_helpers import NON_EXISTENT_UUID
        student = create_pending_student(api)
        get_success_data(api.verify_identity(student["id"], ADMIN_HEADERS))
        now = _server_clock_now(api)
        expires = (now + timedelta(days=30)).strftime("%Y-%m-%d")
        get_success_data(api.submit_medical_cert(student["id"], medical_cert_payload(expires), ADMIN_HEADERS))
        resp = api.select_package(student["id"], select_package_payload(NON_EXISTENT_UUID), ADMIN_HEADERS)
        validate_error(resp, ApiErrorId.ERR_PACKAGE_NOT_FOUND.value)

    def test_sign_contract_with_slipped_medical_cert(self, api):
        """PRD §3.1: "The student's medical_cert_status is rechecked against
        the logical clock at this point — if the underlying date has slipped
        past expiry between submission and signing, the request is rejected
        with ERR_MEDICAL_CERT_EXPIRED."
        """
        student = create_pending_student(api)
        get_success_data(api.verify_identity(student["id"], ADMIN_HEADERS))
        now = _server_clock_now(api)
        # Set expiry just barely after now, then advance the clock past it.
        expires = (now + timedelta(days=2)).strftime("%Y-%m-%d")
        get_success_data(api.submit_medical_cert(student["id"], medical_cert_payload(expires), ADMIN_HEADERS))
        package = create_default_package(api)
        get_success_data(api.select_package(student["id"], select_package_payload(package["id"]), ADMIN_HEADERS))
        # advance past expiry
        get_success_data(api.advance_clock(60 * 24 * 3, ADMIN_HEADERS))
        resp = api.sign_contract(student["id"], ADMIN_HEADERS)
        validate_error(resp, ApiErrorId.ERR_MEDICAL_CERT_EXPIRED.value)


class TestStudentSuspendReinstate:
    """PRD §3.1 suspension and reinstatement.
    Difficulty design: rule_id=non_linear_state_machine,
    instance=student_active_suspended_cycle.
    """

    def test_admin_can_suspend_active_student(self, api):
        """PRD §3.1: "An admin may suspend an ACTIVE student at any time; the
        side-effect sets suspension_reason to ADMIN_ACTION, and enrollment_status
        becomes SUSPENDED."

        Claim: ACTIVE → SUSPENDED with suspension_reason='ADMIN_ACTION'.
        """
        student, _ = create_active_student(api)
        resp = api.suspend_student(student["id"], ADMIN_HEADERS)
        data = validate_success(resp)
        assert data["enrollment_status"] == "SUSPENDED"
        assert data["suspension_reason"] == "ADMIN_ACTION"

    def test_admin_can_reinstate_suspended_student(self, api):
        """PRD §3.1: "An admin may reinstate a SUSPENDED student; the
        side-effect clears suspension_reason and enrollment_status returns to
        ACTIVE."
        """
        student, _ = create_active_student(api)
        get_success_data(api.suspend_student(student["id"], ADMIN_HEADERS))
        resp = api.reinstate_student(student["id"], ADMIN_HEADERS)
        data = validate_success(resp)
        assert data["enrollment_status"] == "ACTIVE"
        assert data["suspension_reason"] is None

    def test_active_suspended_cycle_unbounded(self, api):
        """PRD §3.1: suspend → reinstate → suspend is allowed; cycle unbounded.

        # difficulty: non_linear_state_machine/student_active_suspended_cycle
        Claim: ACTIVE↔SUSPENDED on Student is a cycle. Re-suspension after
        reinstate is allowed and again sets suspension_reason to ADMIN_ACTION.
        """
        student, _ = create_active_student(api)
        s1 = get_success_data(api.suspend_student(student["id"], ADMIN_HEADERS))
        assert s1["enrollment_status"] == "SUSPENDED"
        assert s1["suspension_reason"] == "ADMIN_ACTION"
        s2 = get_success_data(api.reinstate_student(student["id"], ADMIN_HEADERS))
        assert s2["enrollment_status"] == "ACTIVE"
        assert s2["suspension_reason"] is None
        s3 = get_success_data(api.suspend_student(student["id"], ADMIN_HEADERS))
        assert s3["enrollment_status"] == "SUSPENDED"
        assert s3["suspension_reason"] == "ADMIN_ACTION"
