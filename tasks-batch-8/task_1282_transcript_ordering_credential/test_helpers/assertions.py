"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def assert_student(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1
    assert isinstance(data["student_number"], str) and len(data["student_number"]) > 0
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["date_of_birth"], str) and len(data["date_of_birth"]) > 0
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert data["status"] in ["ACTIVE", "INACTIVE", "GRADUATED", "WITHDRAWN", "DECEASED"]
    assert isinstance(data["ferpa_restricted"], bool)
    assert isinstance(data["archived_record_flag"], bool)


def assert_student_record(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["student_id"], str)
    assert isinstance(data["effective_term"], str)
    assert isinstance(data["gpa_cents"], int) and data["gpa_cents"] >= 0
    assert isinstance(data["earned_credits"], int)
    assert isinstance(data["degree_awarded"], bool)
    assert isinstance(data["record_version"], int) and data["record_version"] >= 1
    assert isinstance(data["is_current"], bool)


def assert_recipient(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1
    assert data["kind"] in ["ELECTRONIC_NETWORK", "EMAIL_PDF", "PAPER_MAIL", "PICKUP"]
    assert isinstance(data["display_name"], str) and len(data["display_name"]) > 0
    assert isinstance(data["active"], bool)


def assert_hold(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1
    assert isinstance(data["student_id"], str)
    assert data["hold_type"] in ["FINANCIAL", "LIBRARY", "REGISTRAR", "DISCIPLINARY"]
    assert data["status"] in ["ACTIVE", "RELEASED", "EXPIRED"]
    assert data["blocking_scope"] in ["OFFICIAL", "ALL", "NONE"]
    assert isinstance(data["amount_cents"], int)


def assert_identity_verification(data: dict):
    # IdentityVerification carries only id + created_at — no updated_at, no version.
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "IdentityVerification must not carry version"
    assert "updated_at" not in data, "IdentityVerification must not carry updated_at"
    assert isinstance(data["student_id"], str)
    assert isinstance(data["order_id"], str)
    assert data["method"] in ["SSN_DOB", "GOVERNMENT_ID", "IN_PERSON", "NOTARIZED"]
    assert data["status"] in ["PENDING", "VERIFIED", "REJECTED", "EXPIRED"]


def assert_transcript_order(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1
    assert isinstance(data["student_id"], str)
    assert data["order_kind"] in ["OFFICIAL", "UNOFFICIAL"]
    assert data["fulfillment_status"] in [
        "DRAFT",
        "SUBMITTED",
        "IDENTITY_PENDING",
        "HOLD_CHECK",
        "READY_TO_FULFILL",
        "IN_TRANSIT",
        "DELIVERED",
        "REISSUE_PENDING",
        "CANCELLED",
        "FAILED",
    ]
    assert data["payment_status"] in [
        "UNPAID",
        "AUTHORIZED",
        "CAPTURED",
        "PARTIALLY_REFUNDED",
        "REFUNDED",
        "WAIVED",
    ]
    assert isinstance(data["rush_requested"], bool)
    assert isinstance(data["rush_qualified"], bool)
    assert isinstance(data["quoted_fee_cents"], int)
    assert isinstance(data["final_fee_cents"], int)


def assert_order_line_item(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1
    assert isinstance(data["order_id"], str)
    assert isinstance(data["recipient_id"], str)
    assert data["delivery_kind"] in ["ELECTRONIC_NETWORK", "EMAIL_PDF", "PAPER_MAIL", "PICKUP"]
    assert isinstance(data["quantity"], int) and 1 <= data["quantity"] <= 10
    assert isinstance(data["unit_price_cents"], int)
    assert data["line_status"] in ["PENDING", "QUEUED", "SENT", "DELIVERED", "BOUNCED", "CANCELLED"]


def assert_consent_grant(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1
    assert isinstance(data["student_id"], str)
    assert isinstance(data["grantee_name"], str)
    assert data["scope"] in ["ENROLLMENT_ONLY", "DEGREE_ONLY", "FULL_RECORD"]
    assert data["status"] in ["ACTIVE", "REVOKED", "EXPIRED"]


def assert_verification_request(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1
    assert isinstance(data["requester_name"], str)
    assert isinstance(data["subject_student_id"], str)
    assert data["scope"] in ["ENROLLMENT_ONLY", "DEGREE_ONLY", "FULL_RECORD"]
    assert data["status"] in [
        "RECEIVED",
        "CONSENT_CHECK",
        "APPROVED",
        "DENIED",
        "REPORTED",
        "CANCELLED",
    ]
    assert isinstance(data["fee_cents"], int)


def assert_fee_schedule(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1
    assert isinstance(data["code"], str) and len(data["code"]) > 0
    assert isinstance(data["official_base_cents"], int)
    assert isinstance(data["unofficial_base_cents"], int)
    assert isinstance(data["paper_surcharge_cents"], int)
    assert isinstance(data["pickup_surcharge_cents"], int)
    assert isinstance(data["rush_flat_cents"], int)
    assert isinstance(data["rush_multiplier_bp"], int)
    assert isinstance(data["volume_tiers"], list)
    assert isinstance(data["active"], bool)


def assert_payment(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1
    assert isinstance(data["order_id"], str)
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["captured_cents"], int)
    assert isinstance(data["refunded_cents"], int)
    assert data["status"] in [
        "AUTHORIZED",
        "CAPTURED",
        "PARTIALLY_REFUNDED",
        "REFUNDED",
        "VOIDED",
        "FAILED",
    ]
    assert isinstance(data["idempotency_key"], str)


def assert_reissue_request(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1
    assert isinstance(data["original_order_id"], str)
    assert data["reason"] in [
        "NAME_CORRECTION",
        "RECORD_CORRECTION",
        "DAMAGED_IN_MAIL",
        "NEVER_RECEIVED",
        "WRONG_RECIPIENT",
    ]
    assert data["status"] in ["REQUESTED", "APPROVED", "REJECTED", "FULFILLED"]


def assert_clearinghouse_batch(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1
    assert data["status"] in ["OPEN", "LOCKED", "TRANSMITTED", "ACKED", "FAILED"]
    assert isinstance(data["order_count"], int) and data["order_count"] >= 0
    assert isinstance(data["verification_count"], int) and data["verification_count"] >= 0


def assert_payment_invariants(data: dict):
    """Refund waterfall invariant: 0 <= refunded_cents <= captured_cents always."""
    assert data["captured_cents"] >= 0
    assert data["refunded_cents"] >= 0
    assert data["refunded_cents"] <= data["captured_cents"]
