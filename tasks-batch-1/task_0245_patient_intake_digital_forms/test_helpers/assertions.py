"""Entity assertions and domain invariant checkers (PRD §2.4, §2.9, §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_clinic(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["form_expiration_hours"], int) and data["form_expiration_hours"] > 0
    assert data["copay_rounding"] in ("PER_LINE_THEN_SUM", "SUM_THEN_ROUND")
    assert isinstance(data["facility_fee_cents"], int) and data["facility_fee_cents"] >= 0
    assert isinstance(data["collected_copay_cents"], int) and data["collected_copay_cents"] >= 0
    assert isinstance(data["active_queue_count"], int) and data["active_queue_count"] >= 0


def assert_provider(data: dict):
    _assert_common(data)
    assert isinstance(data["clinic_id"], str)
    assert isinstance(data["full_name"], str)
    assert isinstance(data["required_consent_codes"], list)
    assert isinstance(data["questionnaire_required_sections"], list)


def assert_exam_room(data: dict):
    _assert_common(data)
    assert isinstance(data["clinic_id"], str)
    assert isinstance(data["label"], str)


def assert_patient(data: dict):
    _assert_common(data)
    assert isinstance(data["clinic_id"], str)
    assert isinstance(data["legal_name"], str)
    assert isinstance(data["demographics_revision"], int)


def assert_appointment(data: dict):
    _assert_common(data)
    assert data["status"] in ("SCHEDULED", "INTAKE_OPENED", "CANCELLED")
    assert isinstance(data["provisional_copay_cents"], int)


def assert_intake_session(data: dict):
    _assert_common(data)
    assert data["workflow_status"] in (
        "DRAFT", "IN_PROGRESS", "READY_FOR_VISIT", "CHECKED_IN",
        "COMPLETED", "EXPIRED", "CANCELLED",
    )
    assert data["financial_status"] in (
        "PENDING_ELIGIBILITY", "INSURED", "SELF_PAY",
        "COPAY_DUE", "COPAY_SETTLED", "WAIVED",
    )
    assert isinstance(data["forms_complete"], bool)


def assert_insurance_card(data: dict):
    _assert_common(data)
    assert data["eligibility_status"] in (
        "UNVERIFIED", "VERIFYING", "ELIGIBLE", "INELIGIBLE", "NEEDS_REVIEW",
    )


def assert_eligibility_check(data: dict):
    # common_fields: false — only id + created_at guaranteed (PRD §2.4)
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["outcome"] in ("ELIGIBLE", "INELIGIBLE", "NEEDS_REVIEW")


def assert_consent_document(data: dict):
    _assert_common(data)
    assert data["status"] in ("PENDING", "SIGNED", "REVOKED")
    assert isinstance(data["revision"], int)


def assert_questionnaire(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "SUBMITTED", "ACCEPTED", "FLAGGED")
    assert isinstance(data["provisional_risk_score"], int)
    assert isinstance(data["high_risk_flag"], bool)


def assert_copay_payment(data: dict):
    _assert_common(data)
    assert data["status"] in ("AUTHORIZED", "CAPTURED", "VOIDED", "REFUNDED")
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["refunded_cents"], int)


def assert_queue_entry(data: dict):
    _assert_common(data)
    assert data["status"] in ("WAITING", "CALLED", "IN_ROOM", "DONE", "NO_SHOW")


def assert_room_booking(data: dict):
    _assert_common(data)
    assert isinstance(data["exam_room_id"], str)
    assert isinstance(data["queue_entry_id"], str)


def assert_reminder(data: dict):
    _assert_common(data)
    assert data["status"] in ("SCHEDULED", "SENT", "CANCELLED", "SUPPRESSED")
    assert data["target_kind"] in ("CONSENT", "QUESTIONNAIRE", "COPAY", "GENERIC")


def assert_demographics_sync_job(data: dict):
    _assert_common(data)
    assert data["status"] in ("QUEUED", "COMMITTED", "SKIPPED_DUPLICATE")
