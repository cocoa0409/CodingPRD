"""Entity assertions and domain invariant checks (PRD §2.5, §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def _assert_light(data: dict):
    """Append-only records (PRD §2.5): id + created_at only — no updated_at/version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "append-only record must not carry updated_at"
    assert "version" not in data, "append-only record must not carry version"


def assert_hospital_unit(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["category"] in [
        "INPATIENT", "EMERGENCY", "OUTPATIENT", "SURGICAL", "ICU", "OTHER",
    ]
    assert data["posture"] in ["STANDARD", "RESTRICTED"]
    assert isinstance(data["max_concurrent_roundings"], int)
    assert data["max_concurrent_roundings"] >= 1
    assert isinstance(data["open_case_count"], int)
    assert isinstance(data["late_filed_event_count"], int)


def assert_staff_member(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["capabilities"], list) and len(data["capabilities"]) > 0
    for cap in data["capabilities"]:
        assert cap in ["ADVOCATE", "INVESTIGATOR", "QRO", "DIRECTOR"]
    assert isinstance(data["on_leave"], bool)
    assert isinstance(data["max_concurrent_assignments"], int)
    assert data["max_concurrent_assignments"] >= 1
    assert isinstance(data["open_assignment_count"], int)
    assert isinstance(data["recovery_issuance_limit_cents"], int)


def assert_patient_case(data: dict):
    _assert_common(data)
    assert isinstance(data["patient_ref"], str) and data["patient_ref"]
    assert is_valid_uuid(data.get("unit_id", ""))
    assert is_iso8601_timestamp(data.get("received_at", ""))
    assert data["channel"] in ["PHONE", "EMAIL", "PORTAL", "IN_PERSON", "LETTER"]
    assert data["grievance_category"] in [
        "BILLING", "CARE_QUALITY", "STAFF_CONDUCT", "ACCESS_DELAY",
        "RIGHTS_ABUSE", "COMMUNICATION", "OTHER",
    ]
    assert data["severity_tier"] in ["STANDARD", "URGENT", "CRITICAL"]
    assert data["classification"] in ["UNCLASSIFIED", "COMPLAINT", "GRIEVANCE"]
    assert data["lifecycle_status"] in [
        "INTAKE", "CLASSIFIED", "ASSIGNED", "UNDER_INVESTIGATION", "FINDINGS_REVIEW",
        "RESPONSE_DRAFTING", "RESPONSE_REVIEW", "PENDING_CLOSURE", "CLOSED",
        "REOPENED", "WITHDRAWN",
    ]
    assert data["regulatory_clock_status"] in [
        "ON_TRACK", "ACK_BREACH", "RESPONSE_BREACH", "SUSPENDED",
    ]
    assert isinstance(data["tolling_credit_seconds"], int)
    assert isinstance(data["outstanding_recovery_cents"], int)
    assert isinstance(data["priority_score"], int)
    assert isinstance(data["requires_qro_cosign"], bool)
    assert data["resolution_timeliness"] in ["NA", "ON_TIME", "LATE"]
    assert isinstance(data["reopen_count"], int)


def assert_classification_decision(data: dict):
    _assert_light(data)
    assert data["decision"] in ["COMPLAINT", "GRIEVANCE"]
    assert data["rationale_code"] in [
        "INITIAL_INTAKE", "PATIENT_REQUEST", "ESCALATION_OF_CONCERN",
        "REGULATORY_REVIEW", "DIRECTOR_OVERRIDE",
    ]
    assert isinstance(data["case_id"], str)
    assert isinstance(data["decided_by_id"], str)


def assert_case_assignment(data: dict):
    _assert_common(data)
    assert data["assignment_role"] in ["PRIMARY", "SUPPORTING"]
    assert data["status"] in ["ACTIVE", "RELEASED", "COMPLETED"]
    assert is_valid_uuid(data.get("case_id", ""))
    assert isinstance(data["investigator_id"], str)
    assert isinstance(data["assigned_by_id"], str)


def assert_investigation(data: dict):
    _assert_common(data)
    assert data["status"] in [
        "OPEN", "FINDINGS_SUBMITTED", "FINDINGS_ACCEPTED", "REOPENED", "CANCELLED",
    ]
    assert is_valid_uuid(data.get("case_id", ""))
    assert isinstance(data["note_count"], int)
    assert isinstance(data["interview_note_count"], int)


def assert_investigation_note(data: dict):
    _assert_light(data)
    assert data["note_type"] in ["INTERVIEW", "DOCUMENT_REVIEW", "SITE_VISIT", "PHONE_CALL"]
    assert isinstance(data["body"], str)
    assert is_valid_uuid(data.get("investigation_id", ""))
    assert isinstance(data["author_id"], str)


def assert_response_letter(data: dict):
    _assert_common(data)
    assert data["status"] in [
        "DRAFT", "IN_REVIEW", "RETURNED", "APPROVED", "ISSUED", "SUPERSEDED", "CANCELLED",
    ]
    assert isinstance(data["sections"], list)
    for section in data["sections"]:
        assert section in [
            "PATIENT_SUMMARY", "INVESTIGATION_STEPS", "FINDINGS", "RESOLUTION",
            "CONTACT_INFO", "RISK_DISCLOSURE", "QAPI_REFERENCE",
        ]
    assert isinstance(data["body_summary"], str)
    assert is_valid_uuid(data.get("case_id", ""))


def assert_recovery_action(data: dict):
    _assert_common(data)
    assert data["action_type"] in [
        "MEAL_VOUCHER", "PARKING_COMP", "BILL_ADJUSTMENT",
        "GOODWILL_GESTURE", "EXPEDITED_APPOINTMENT",
    ]
    assert isinstance(data["value_cents"], int) and data["value_cents"] > 0
    assert data["status"] in ["ISSUED", "PENDING_APPROVAL", "REJECTED", "REVOKED"]
    assert is_valid_uuid(data.get("case_id", ""))
    assert isinstance(data["issued_by_id"], str)


def assert_escalation(data: dict):
    _assert_common(data)
    assert data["escalation_type"] in ["CARE_CONCERN", "SYSTEMIC"]
    assert data["source"] in ["MANUAL", "AUTO_CARE_FLAG", "AUTO_SYSTEMIC_THRESHOLD"]
    assert data["status"] in [
        "FILED", "IN_REVIEW", "REVIEWS_COMPLETE",
        "ADJUDICATED_SUBSTANTIATED", "ADJUDICATED_UNSUBSTANTIATED",
    ]
    assert is_valid_uuid(data.get("case_id", ""))
    assert isinstance(data["filed_by_id"], str)


def assert_reportable_event(data: dict):
    _assert_common(data)
    assert data["authority_code"] in [
        "STATE_HEALTH_DEPT", "CMS_REGIONAL", "ACCREDITATION_BODY",
    ]
    assert data["trigger_reason"] in [
        "ALLEGED_ABUSE", "SUBSTANTIATED_CARE_CONCERN", "SYSTEMIC_ISSUE",
    ]
    assert data["status"] in ["PENDING_FILING", "FILED", "LATE_FILED", "ACKNOWLEDGED"]
    assert is_valid_uuid(data.get("case_id", ""))
    assert isinstance(data["late_filing"], bool)


def assert_rounding_session(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("unit_id", ""))
    assert isinstance(data["advocate_id"], str)
    assert is_iso8601_timestamp(data.get("start_at", ""))
    assert is_iso8601_timestamp(data.get("end_at", ""))
    assert data["status"] in ["SCHEDULED", "COMPLETED", "CANCELLED"]


def assert_interview_room(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["location"], str)
    assert isinstance(data["active"], bool)


def assert_interview_booking(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("investigation_id", ""))
    assert is_valid_uuid(data.get("room_id", ""))
    assert is_iso8601_timestamp(data.get("start_at", ""))
    assert is_iso8601_timestamp(data.get("end_at", ""))
    assert data["status"] in ["BOOKED", "CANCELLED"]
    assert isinstance(data["booked_by_id"], str)


def assert_follow_up(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("case_id", ""))
    assert data["status"] in ["PENDING", "RESPONDED", "EXPIRED"]
    assert is_iso8601_timestamp(data.get("due_at", ""))
    assert is_iso8601_timestamp(data.get("expires_at", ""))


def assert_clock_suspension(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("case_id", ""))
    assert data["reason"] in [
        "AWAITING_PATIENT", "AWAITING_FAMILY", "AWAITING_RECORDS", "LANGUAGE_ACCESS",
    ]
    assert data["status"] in ["OPEN", "CLOSED"]
    assert is_iso8601_timestamp(data.get("started_at", ""))
    assert isinstance(data["credited_seconds"], int)


def assert_trend_snapshot(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("unit_id", ""))
    assert data["case_category"] in [
        "BILLING", "CARE_QUALITY", "STAFF_CONDUCT", "ACCESS_DELAY",
        "RIGHTS_ABUSE", "COMMUNICATION", "OTHER",
    ]
    assert isinstance(data["period"], str)
    for field in ("grievances_closed", "complaints_closed", "breaches",
                  "headcount_rate_bp", "exposure_weighted_rate_bp", "systemic_new_count"):
        assert isinstance(data[field], int), f"{field} must be an integer"


def assert_holiday(data: dict):
    _assert_light(data)
    assert isinstance(data["observance_date"], str)
    assert isinstance(data["name"], str)
