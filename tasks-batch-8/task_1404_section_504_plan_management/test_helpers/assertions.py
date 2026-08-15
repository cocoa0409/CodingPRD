"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict, entity: str):
    """Primary resources carry id, created_at, updated_at, version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{entity}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"{entity}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity}.version must be an integer beginning at 1"
    )


def assert_school(data: dict):
    _assert_common_fields(data, "School")
    assert isinstance(data["school_name"], str) and data["school_name"]
    assert isinstance(data["district_code"], str) and data["district_code"]
    assert isinstance(data["current_academic_year"], str) and data["current_academic_year"]
    assert data["school_posture"] in ["OPERATIONAL", "PROBATION", "AUDIT_HOLD"]


def assert_student(data: dict):
    _assert_common_fields(data, "Student")
    assert data["section_504_status"] in [
        "NONE", "REFERRED", "EVALUATING", "PLAN_ACTIVE",
        "PLAN_SUSPENDED", "EXITED_TO_IEP", "NOT_ELIGIBLE", "TERMINATED",
    ]
    assert data["iep_status"] in ["NONE", "IEP_ACTIVE", "IEP_EXITED"]
    assert isinstance(data["has_active_504_plan"], bool)
    assert isinstance(data["grade_level"], int)


def assert_staff_member(data: dict):
    _assert_common_fields(data, "StaffMember")
    assert data["staff_role"] in ["TEACHER", "COORDINATOR", "PRINCIPAL", "DISTRICT_DIRECTOR"]
    assert isinstance(data["is_active"], bool)
    assert data["current_training_status"] in ["UNTRAINED", "TRAINED_CURRENT", "TRAINED_EXPIRED"]


def assert_referral(data: dict):
    _assert_common_fields(data, "Section504Referral")
    assert data["referral_status"] in [
        "PENDING", "UNDER_REVIEW", "EVALUATION_INITIATED", "REJECTED", "WITHDRAWN",
    ]
    assert data["suspected_disability_category"] in [
        "PHYSICAL", "MENTAL", "LEARNING", "CHRONIC_HEALTH", "OTHER",
    ]


def assert_evaluation(data: dict):
    _assert_common_fields(data, "EligibilityEvaluation")
    assert data["evaluation_status"] in [
        "INITIATED", "CONSENT_PENDING", "CONSENT_RECEIVED",
        "EVALUATION_IN_PROGRESS", "DETERMINATION_MADE", "CANCELLED",
    ]


def assert_plan(data: dict):
    _assert_common_fields(data, "Section504Plan")
    assert data["plan_status"] in [
        "DRAFT", "PENDING_PARENT_CONSENT", "PENDING_TEACHER_ACK", "ACTIVE",
        "UNDER_ANNUAL_REVIEW", "SUSPENDED", "EXITED_TO_IEP", "TERMINATED",
    ]


def assert_accommodation(data: dict):
    _assert_common_fields(data, "Accommodation")
    assert data["accommodation_status"] in ["DRAFT", "ACTIVE", "SUSPENDED", "DISCONTINUED"]
    assert isinstance(data["applies_to_testing"], bool)


def assert_teacher_ack(data: dict):
    _assert_common_fields(data, "TeacherAcknowledgment")
    assert data["ack_status"] in ["PENDING", "ACKNOWLEDGED", "DECLINED"]


def assert_implementation_log(data: dict):
    _assert_common_fields(data, "ImplementationLog")
    assert isinstance(data["was_implemented_as_planned"], bool)


def assert_review(data: dict):
    _assert_common_fields(data, "ReviewEvent")
    assert data["review_type"] in ["ANNUAL", "RE_EVALUATION", "PARENT_REQUESTED", "DISTRICT_AUDIT"]
    assert data["review_status"] in ["SCHEDULED", "IN_PROGRESS", "COMPLETED", "OVERDUE", "CANCELLED"]


def assert_testing_request(data: dict):
    _assert_common_fields(data, "TestingAccommodationRequest")
    assert data["request_status"] in [
        "SUBMITTED", "PENDING_DISTRICT_REVIEW", "APPROVED", "DENIED", "FLAGGED_FOR_STATE_AUDIT",
    ]


def assert_consent_record(data: dict):
    _assert_common_fields(data, "ParentConsentRecord")
    assert data["consent_scope"] in [
        "INITIAL_PLAN", "PLAN_AMENDMENT", "RE_EVALUATION", "EXIT_TO_IEP", "TESTING_ACCOMMODATION",
    ]
    assert data["consent_status"] in ["REQUESTED", "GRANTED", "DENIED", "REVOKED"]


def assert_grievance(data: dict):
    _assert_common_fields(data, "Grievance")
    assert data["grievance_status"] in [
        "FILED", "INFORMAL_RESOLUTION", "FORMAL_INVESTIGATION",
        "RESOLVED", "ESCALATED_TO_OCR", "CLOSED",
    ]


def assert_training_record(data: dict):
    _assert_common_fields(data, "StaffTrainingRecord")
    assert data["training_topic"] in [
        "SECTION_504_BASICS", "ACCOMMODATION_DELIVERY", "GRIEVANCE_PROCEDURES",
        "TESTING_ACCOMMODATIONS", "TRANSITION_PROCEDURES",
    ]


def assert_audit_event(data: dict):
    """Append-only ledger entry: carries only id + created_at from the common
    set — both updated_at and version are absent (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "ComplianceAuditEvent.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "audit event must not carry updated_at"
    assert "version" not in data, "audit event must not carry version"
    assert "school_id" in data
    assert "event_type" in data
    assert "entity_ref" in data
    assert "actor_staff_id" in data
    assert "event_payload" in data
