"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

_CUSTOMER_STATUSES = ["ACTIVE", "FROZEN", "CLOSED"]
_ACCOUNT_STATUSES = ["ACTIVE", "DORMANT", "CLOSED"]
_BENEFICIARY_STATUSES = ["ACTIVE", "RETIRED"]
_BUSINESS_DATE_STATUSES = ["OPEN", "CUTOFF_PASSED", "CLOSED"]
_WIRE_STATUSES = [
    "INITIATED", "CALLBACK_PENDING", "PENDING_APPROVAL", "APPROVED",
    "RELEASING", "EXECUTED", "REJECTED", "CANCELLED", "REPAIR", "RECALLED",
]
_SCREENING_STATUSES = ["NOT_SCREENED", "CLEAR", "REVIEW", "CONFIRMED_HIT"]
_CALLBACK_STATUSES = ["NONE", "PENDING", "VERIFIED", "WAIVED"]
_CALLBACK_CASE_STATUSES = ["OPEN", "CONFIRMED", "DENIED", "EXPIRED", "SUPERSEDED"]
_HIT_STATUSES = ["OPEN", "RELEASED_FALSE_POSITIVE", "CONFIRMED", "ESCALATED"]
_FRAUD_HOLD_STATUSES = ["OPEN", "CONFIRMED_FRAUD", "CLEARED"]
_FRAUD_RESOLUTIONS = ["NONE", "CUSTOMER_CONFIRMED", "CUSTOMER_DENIED", "AUTO_LAPSED"]
_RECALL_STATUSES = [
    "REQUESTED", "SENT_TO_BENEFICIARY_BANK", "BENEFICIARY_RESPONDED",
    "COMPLETED", "DECLINED", "EXPIRED",
]
_BENEFICIARY_BANK_RESPONSES = ["NONE", "FUNDS_RETURNED", "FUNDS_DECLINED"]
_FEE_STATUSES = ["OPEN", "BILLED", "SUPERSEDED", "WAIVED"]
_FEE_KINDS = ["PROVISIONAL", "FINAL"]
_CHARGE_STATUSES = ["POSTED", "SUPERSEDED", "CANCELLED"]
_INVESTIGATION_STATUSES = ["OPEN", "AWAITING_RESPONSE", "RESOLVED", "CLOSED"]


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_customer(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert data["risk_rating"] in ["LOW", "MEDIUM", "HIGH"]
    assert isinstance(data["high_risk_jurisdiction"], bool)
    assert data["status"] in _CUSTOMER_STATUSES
    assert data.get("frozen_at") is None or is_iso8601_timestamp(data["frozen_at"])


def assert_account(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["customer_id"], str)
    assert isinstance(data["account_number"], str) and data["account_number"]
    assert data["currency"] == "USD"
    assert data["status"] in _ACCOUNT_STATUSES
    assert isinstance(data["daily_outgoing_limit_cents"], int)
    assert data["daily_outgoing_limit_cents"] > 0
    assert isinstance(data["daily_reserved_cents"], int)
    assert data["daily_reserved_cents"] >= 0
    assert isinstance(data["daily_released_cents"], int)
    assert data["daily_released_cents"] >= 0


def assert_beneficiary(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["customer_id"], str)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["bank_name"], str) and data["bank_name"]
    assert isinstance(data["account_number"], str) and data["account_number"]
    assert isinstance(data["country_code"], str) and len(data["country_code"]) == 2
    assert data["status"] in _BENEFICIARY_STATUSES
    assert data.get("first_used_at") is None or is_iso8601_timestamp(data["first_used_at"])


def assert_business_date(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["business_date"], str) and len(data["business_date"]) == 10
    assert data["status"] in _BUSINESS_DATE_STATUSES


def assert_wire(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["ordering_account_id"], str)
    assert isinstance(data["beneficiary_id"], str)
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert data["currency"] == "USD"
    assert data["method"] in ["Fedwire", "SWIFT", "CHIPS"]
    assert data["priority"] in ["NORMAL", "SAME_DAY"]
    assert data["charge_mode"] in ["OUR", "BENEFICIARY_REMUNERATION"]
    assert isinstance(data["purpose"], str)
    assert isinstance(data["requires_callback"], bool)
    assert data["callback_status"] in _CALLBACK_STATUSES
    assert isinstance(data["initiated_by"], str) and data["initiated_by"]
    assert data.get("first_approved_by") is None or isinstance(data["first_approved_by"], str)
    assert data.get("second_approved_by") is None or isinstance(data["second_approved_by"], str)
    assert data.get("value_date") is None or isinstance(data["value_date"], str)
    assert data["status"] in _WIRE_STATUSES
    assert data["screening_status"] in _SCREENING_STATUSES
    assert isinstance(data["reservation_active"], bool)
    assert data.get("risk_score") is None or isinstance(data["risk_score"], int)
    assert data.get("fee_assessed_cents") is None or isinstance(data["fee_assessed_cents"], int)
    assert data.get("net_principal_cents") is None or isinstance(data["net_principal_cents"], int)
    assert data.get("executed_at") is None or is_iso8601_timestamp(data["executed_at"])
    assert data.get("hold_reason_code") in (None, "SANCTIONS_HOLD", "FRAUD_HOLD", "REPAIR_HOLD")
    assert isinstance(data["repair_attempts"], int) and data["repair_attempts"] >= 0


def assert_approval_record(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["wire_id"], str)
    assert data["sequence"] in ["FIRST", "SECOND"]
    assert isinstance(data["approver_user_id"], str) and data["approver_user_id"]
    assert is_iso8601_timestamp(data.get("decided_at", ""))
    assert isinstance(data["superseded"], bool)


def assert_callback_verification(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["wire_id"], str)
    assert data.get("contact_name") is None or isinstance(data["contact_name"], str)
    assert data.get("contact_phone") is None or isinstance(data["contact_phone"], str)
    assert data.get("outcome") in (None, "CONFIRMED", "DENIED", "UNREACHABLE")
    assert data["status"] in _CALLBACK_CASE_STATUSES
    assert is_iso8601_timestamp(data.get("opened_at", ""))
    assert is_iso8601_timestamp(data.get("expires_at", ""))
    assert data.get("resolved_at") is None or is_iso8601_timestamp(data["resolved_at"])


def assert_sanctions_hit(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["wire_id"], str)
    assert data["matched_list"] in ["OFAC_SDN", "INTERNAL_WATCH", "EU_CONSOLIDATED"]
    assert isinstance(data["matched_party"], str) and data["matched_party"]
    assert isinstance(data["match_score"], int)
    assert data["status"] in _HIT_STATUSES
    assert data.get("decided_by") is None or isinstance(data["decided_by"], str)
    assert data.get("decided_at") is None or is_iso8601_timestamp(data["decided_at"])


def assert_fraud_hold(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["wire_id"], str)
    assert data["reason_code"] in [
        "ACCOUNT_TAKEOVER", "VELOCITY", "MULE_SUSPECT", "PHISHING",
    ]
    assert isinstance(data["note"], str)
    assert isinstance(data["placed_by"], str) and data["placed_by"]
    assert data["status"] in _FRAUD_HOLD_STATUSES
    assert isinstance(data["confirmation_window_hours"], int)
    assert is_iso8601_timestamp(data.get("expires_at", ""))
    assert data["resolution"] in _FRAUD_RESOLUTIONS


def assert_recall_request(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["wire_id"], str)
    assert data["reason"] in ["DUPLICATE", "FRAUD", "ERROR_AMOUNT", "ERROR_BENEFICIARY"]
    assert isinstance(data["amount_to_recall_cents"], int)
    assert data["amount_to_recall_cents"] > 0
    assert data["status"] in _RECALL_STATUSES
    assert data["beneficiary_bank_response"] in _BENEFICIARY_BANK_RESPONSES
    assert data.get("response_due_at") is None or is_iso8601_timestamp(data["response_due_at"])
    assert data.get("responded_at") is None or is_iso8601_timestamp(data["responded_at"])


def assert_fee_assessment(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["wire_id"], str)
    assert isinstance(data["base_fee_cents"], int)
    assert isinstance(data["priority_fee_cents"], int)
    assert isinstance(data["beneficiary_share_cents"], int)
    assert isinstance(data["correspondent_share_cents"], int)
    assert isinstance(data["total_fee_cents"], int)
    assert data["kind"] in _FEE_KINDS
    assert data["status"] in _FEE_STATUSES


def assert_correspondent_charge(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["wire_id"], str)
    assert isinstance(data["correspondent_name"], str) and data["correspondent_name"]
    assert data["charge_type"] in ["OUR", "BENEFICIARY", "DEDUCTED_FROM_PRINCIPAL"]
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert data["source"] in ["PROVISIONAL_ESTIMATE", "ACTUAL_ADVICE"]
    assert data["status"] in _CHARGE_STATUSES


def assert_investigation(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["wire_id"], str)
    assert data["type"] in ["TRACER", "NON_RECEIPT", "VALUE_DISPUTE"]
    assert isinstance(data["note"], str)
    assert isinstance(data["opened_by"], str) and data["opened_by"]
    assert data["status"] in _INVESTIGATION_STATUSES
    assert isinstance(data["max_tracers"], int)
    assert isinstance(data["tracer_count"], int)
    assert 0 <= data["tracer_count"] <= data["max_tracers"]


def assert_tracer_message(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["investigation_id"], str)
    assert data["direction"] in ["OUTBOUND", "INBOUND"]
    assert isinstance(data["body"], str)
    assert isinstance(data["sequence_no"], int) and data["sequence_no"] >= 1


def assert_audit_log_entry(data: dict):
    """PRD §2.4: an AuditLogEntry carries id and created_at only — no
    updated_at and no version field."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "audit entries must not expose updated_at"
    assert "version" not in data, "audit entries must not expose version"
    assert isinstance(data["actor_user_id"], str) and data["actor_user_id"]
    assert isinstance(data["actor_role"], str) and data["actor_role"]
    assert isinstance(data["action"], str) and data["action"]
    assert isinstance(data["entity_type"], str) and data["entity_type"]
    assert isinstance(data["entity_id"], str) and data["entity_id"]
    assert data.get("wire_id") is None or isinstance(data["wire_id"], str)
    assert isinstance(data["detail"], str)


def assert_account_reservation_invariant(account: dict):
    """Domain invariant: reservation and released tallies are non-negative and
    the released tally never exceeds the daily outgoing limit."""
    assert account["daily_reserved_cents"] >= 0
    assert account["daily_released_cents"] >= 0
    assert account["daily_released_cents"] <= account["daily_outgoing_limit_cents"]
