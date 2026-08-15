"""Entity assertions and domain invariant checkers (PRD §2.2, §2.4, §3)."""
from datetime import datetime

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


# --- Instant helpers ---
# PRD §2.5 pins deadline arithmetic to second precision on ISO 8601 UTC instants;
# comparisons parse to instants rather than pinning one serialization format.

def parse_instant(value) -> datetime:
    """Parse an ISO 8601 UTC instant string into an aware datetime."""
    assert isinstance(value, str) and value, f"expected ISO 8601 instant string, got {value!r}"
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    return datetime.fromisoformat(text)


def assert_instant_equal(actual, expected_iso: str, label: str = "instant") -> None:
    """Assert two ISO 8601 instants denote the same point in time."""
    actual_dt = parse_instant(actual)
    expected_dt = parse_instant(expected_iso)
    assert actual_dt == expected_dt, f"{label}: expected {expected_iso}, got {actual}"


def _assert_common_fields(data: dict, entity: str) -> None:
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be ISO 8601"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity}.updated_at must be ISO 8601"
    )
    assert isinstance(data.get("version"), int), f"{entity}.version must be an integer"


def _assert_immutable_fields(data: dict, entity: str) -> None:
    # PRD §2.4: ReasonCodeRule, ReserveLedgerEntry and RatioSnapshot carry only
    # id + created_at — no updated_at, no version.
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be ISO 8601"
    )
    assert "updated_at" not in data, f"{entity} is immutable; updated_at must be absent"
    assert "version" not in data, f"{entity} is immutable; version must be absent"


def assert_merchant(data: dict) -> None:
    _assert_common_fields(data, "Merchant")
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["merchant_category_code"], str)
    assert data["risk_tier"] in ("STANDARD", "HIGH_RISK")
    assert data["reserve_mode"] in ("FIXED_TIER", "EXPOSURE_BASED")
    assert isinstance(data["reserve_rate_bps"], int)
    assert 0 <= data["reserve_rate_bps"] <= 10000
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    assert isinstance(data["clearing_balance_cents"], int)
    assert data.get("current_count_ratio_bps") is None or isinstance(
        data["current_count_ratio_bps"], int
    )


def assert_reason_code_rule(data: dict) -> None:
    _assert_immutable_fields(data, "ReasonCodeRule")
    assert data["network"] in ("VISA", "MASTERCARD")
    assert isinstance(data["reason_code"], str) and data["reason_code"]
    assert data["category"] in (
        "FRAUD",
        "AUTHORIZATION",
        "PROCESSING_ERROR",
        "CONSUMER_DISPUTE",
    )
    assert isinstance(data["required_evidence_types"], list)
    assert isinstance(data["merchant_response_days"], int) and data["merchant_response_days"] >= 1
    assert isinstance(data["representment_days"], int) and data["representment_days"] >= 1
    assert isinstance(data["chargeback_fee_cents"], int) and data["chargeback_fee_cents"] >= 0
    assert is_iso8601_timestamp(data["effective_from"])
    assert data.get("effective_to") is None or is_iso8601_timestamp(data["effective_to"])


def assert_transaction(data: dict) -> None:
    _assert_common_fields(data, "Transaction")
    assert is_valid_uuid(data.get("merchant_id", ""))
    assert isinstance(data["external_ref"], str) and data["external_ref"]
    assert data["network"] in ("VISA", "MASTERCARD")
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert is_iso8601_timestamp(data["occurred_at"])
    assert data["status"] in ("SETTLED", "REFUNDED", "CHARGED_BACK")


def assert_chargeback(data: dict) -> None:
    _assert_common_fields(data, "Chargeback")
    assert is_valid_uuid(data.get("merchant_id", ""))
    assert isinstance(data["transaction_external_ref"], str)
    assert is_valid_uuid(data.get("transaction_id", ""))
    assert isinstance(data["network_case_id"], str) and data["network_case_id"]
    assert isinstance(data["reason_code"], str) and data["reason_code"]
    assert data["network"] in ("VISA", "MASTERCARD")
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert is_iso8601_timestamp(data["received_at"])
    assert data.get("merchant_notified_at") is None or is_iso8601_timestamp(
        data["merchant_notified_at"]
    )
    assert data.get("merchant_response_due_at") is None or is_iso8601_timestamp(
        data["merchant_response_due_at"]
    )
    assert is_iso8601_timestamp(data["representment_due_at"])
    assert data["case_status"] in (
        "RECEIVED",
        "MERCHANT_NOTIFIED",
        "REPRESENTED",
        "DECIDED_WON",
        "DECIDED_LOST",
        "MERCHANT_ACCEPTED",
        "PRE_ARBITRATION",
        "EXPIRED",
        "REVERSED",
    )
    assert data["funds_status"] in (
        "MERCHANT_DEBITED",
        "FUNDS_RETURNED",
        "DEBIT_FINAL",
        "NOT_DEBITED",
    )
    assert isinstance(data["recredited_cents"], int)
    assert isinstance(data["is_ratio_counted"], bool)


def assert_evidence_item(data: dict) -> None:
    _assert_common_fields(data, "EvidenceItem")
    assert is_valid_uuid(data.get("chargeback_id", ""))
    assert data["evidence_type"] in (
        "RECEIPT",
        "AVS_MATCH",
        "CVV_MATCH",
        "DELIVERY_PROOF",
        "SIGNED_AGREEMENT",
        "REFUND_PROOF",
        "PRIOR_TXN_HISTORY",
        "IP_DEVICE_LOG",
        "CARDHOLDER_COMMUNICATION",
    )
    assert isinstance(data["document_uri"], str) and data["document_uri"]
    assert data["status"] in ("DRAFT", "ATTACHED", "WITHDRAWN")


def assert_representment(data: dict) -> None:
    _assert_common_fields(data, "Representment")
    assert is_valid_uuid(data.get("chargeback_id", ""))
    assert isinstance(data["evidence_item_ids"], list)
    assert data["status"] in (
        "ASSEMBLED",
        "SUBMITTED",
        "WON",
        "PARTIAL_WON",
        "LOST",
        "RETURNED_FOR_CURE",
        "SUPERSEDED",
    )
    assert isinstance(data["cure_count"], int) and data["cure_count"] >= 0
    assert data.get("submitted_at") is None or is_iso8601_timestamp(data["submitted_at"])
    assert data.get("won_amount_cents") is None or isinstance(data["won_amount_cents"], int)
    assert data.get("decided_at") is None or is_iso8601_timestamp(data["decided_at"])


def assert_fee_assessment(data: dict) -> None:
    _assert_common_fields(data, "FeeAssessment")
    assert is_valid_uuid(data.get("merchant_id", ""))
    assert data.get("chargeback_id") is None or is_valid_uuid(data["chargeback_id"])
    assert data.get("enrollment_id") is None or is_valid_uuid(data["enrollment_id"])
    assert data["kind"] in ("CHARGEBACK_FEE", "PROGRAM_FINE", "ARBITRATION_FEE")
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert data["status"] in ("ASSESSED", "SETTLED", "WAIVED")
    assert isinstance(data["assessed_by_user_id"], str) and data["assessed_by_user_id"]
    assert data.get("waived_by_user_id") is None or isinstance(data["waived_by_user_id"], str)
    assert data.get("settled_at") is None or is_iso8601_timestamp(data["settled_at"])
    assert data.get("waived_at") is None or is_iso8601_timestamp(data["waived_at"])


def assert_reserve_account(data: dict) -> None:
    _assert_common_fields(data, "ReserveAccount")
    assert is_valid_uuid(data.get("merchant_id", ""))
    assert isinstance(data["held_cents"], int) and data["held_cents"] >= 0
    assert isinstance(data["target_cents"], int) and data["target_cents"] >= 0
    assert data.get("last_recomputed_at") is None or is_iso8601_timestamp(
        data["last_recomputed_at"]
    )


def assert_reserve_ledger_entry(data: dict) -> None:
    _assert_immutable_fields(data, "ReserveLedgerEntry")
    assert is_valid_uuid(data.get("reserve_account_id", ""))
    assert data["entry_type"] in ("HOLD", "RELEASE", "FORFEIT")
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert data["source_kind"] in (
        "TRANSACTION_SETTLEMENT",
        "CHARGEBACK_RECEIPT",
        "CHARGEBACK_WON",
        "CHARGEBACK_LOST",
        "SCHEDULED_RELEASE",
    )
    assert data.get("source_id") is None or isinstance(data["source_id"], str)
    assert data.get("release_eligible_at") is None or is_iso8601_timestamp(
        data["release_eligible_at"]
    )


def assert_ratio_snapshot(data: dict) -> None:
    _assert_immutable_fields(data, "RatioSnapshot")
    assert is_valid_uuid(data.get("merchant_id", ""))
    assert data["network"] in ("VISA", "MASTERCARD")
    assert isinstance(data["period_month"], str) and len(data["period_month"]) == 7
    assert isinstance(data["sales_count"], int) and data["sales_count"] >= 0
    assert isinstance(data["sales_amount_cents"], int) and data["sales_amount_cents"] >= 0
    assert isinstance(data["chargeback_count"], int) and data["chargeback_count"] >= 0
    assert isinstance(data["gross_chargeback_count"], int)
    assert data["gross_chargeback_count"] >= data["chargeback_count"]
    assert isinstance(data["count_ratio_bps"], int) and data["count_ratio_bps"] >= 0
    assert isinstance(data["gross_count_ratio_bps"], int)
    assert data["gross_count_ratio_bps"] >= data["count_ratio_bps"]
    assert is_iso8601_timestamp(data["computed_at"])


def assert_program_enrollment(data: dict) -> None:
    _assert_common_fields(data, "ProgramEnrollment")
    assert is_valid_uuid(data.get("merchant_id", ""))
    assert data["network"] in ("VISA", "MASTERCARD")
    assert data["program_code"] in ("VDMP_STANDARD", "VDMP_EXCESSIVE", "ECM", "HECM")
    assert isinstance(data["enrolled_month"], str) and len(data["enrolled_month"]) == 7
    assert data.get("exited_month") is None or isinstance(data["exited_month"], str)
    assert isinstance(data["months_over_count"], int) and data["months_over_count"] >= 1
    assert data["status"] in ("ACTIVE", "REMEDIATION", "EXITED")


def assert_remediation_plan(data: dict) -> None:
    _assert_common_fields(data, "RemediationPlan")
    assert is_valid_uuid(data.get("enrollment_id", ""))
    assert isinstance(data["root_cause_codes"], list) and len(data["root_cause_codes"]) >= 1
    for code in data["root_cause_codes"]:
        assert code in (
            "FRAUD_GAP",
            "FULFILLMENT_GAP",
            "CUSTOMER_SERVICE_GAP",
            "POLICY_GAP",
        )
    assert isinstance(data["corrective_actions"], list) and len(data["corrective_actions"]) >= 1
    assert data["status"] in ("DRAFT", "SUBMITTED", "APPROVED", "RETURNED")
    assert data.get("reviewed_by_user_id") is None or isinstance(
        data["reviewed_by_user_id"], str
    )


def assert_prevention_alert(data: dict) -> None:
    _assert_common_fields(data, "PreventionAlert")
    assert is_valid_uuid(data.get("transaction_id", ""))
    assert is_valid_uuid(data.get("merchant_id", ""))
    assert data["alert_type"] in ("FRAUD_ALERT", "DISPUTE_ALERT", "REFUND_OPPORTUNITY")
    assert is_iso8601_timestamp(data["received_at"])
    assert is_iso8601_timestamp(data["response_due_at"])
    assert data["status"] in ("OPEN", "ACTIONED_REFUND", "DISMISSED", "EXPIRED")


def assert_education_assignment(data: dict) -> None:
    _assert_common_fields(data, "EducationAssignment")
    assert is_valid_uuid(data.get("merchant_id", ""))
    assert data.get("enrollment_ref") is None or isinstance(data["enrollment_ref"], str)
    assert data["module_code"] in (
        "CHARGEBACK_BASICS",
        "EVIDENCE_BEST_PRACTICE",
        "FRAUD_PREVENTION",
    )
    assert data["assigned_reason"] == "PROGRAM_ENROLLMENT"
    assert data["status"] in ("ASSIGNED", "COMPLETED")
    assert is_iso8601_timestamp(data["assigned_at"])
    assert data.get("completed_at") is None or is_iso8601_timestamp(data["completed_at"])


def assert_reserve_ledger_fold(data_entries: list, held_cents: int) -> None:
    """Domain invariant (PRD §3.3): held_cents == sum(HOLD) - sum(RELEASE) - sum(FORFEIT)."""
    fold = 0
    for entry in data_entries:
        if entry["entry_type"] == "HOLD":
            fold += entry["amount_cents"]
        elif entry["entry_type"] in ("RELEASE", "FORFEIT"):
            fold -= entry["amount_cents"]
    assert fold == held_cents, (
        f"ledger fold {fold} does not equal held_cents {held_cents}"
    )
    assert held_cents >= 0, "held_cents must never be negative"
