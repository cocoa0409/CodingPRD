"""Entity assertions and domain invariant checkers.

Field names follow the PRD exactly. Every resource carries the common
properties of PRD §2.4 (id, created_at, updated_at, version).
"""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), (
        f"id must be a server-minted UUID, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "created_at must be an ISO 8601 timestamp"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        "updated_at must be an ISO 8601 timestamp"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be an integer >= 1, got {data.get('version')!r}"
    )


def assert_bank(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["routing_number"], str) and data["routing_number"]
    assert isinstance(data["current_business_date"], str)
    assert isinstance(data["current_analysis_cycle_index"], int)
    assert isinstance(data["default_earnings_credit_rate_bp"], int)
    assert data["posture"] in ("OPERATING", "SUSPENDED", "LIQUIDATING")


def assert_customer(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["bank_id"], str)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["tax_id"], str) and data["tax_id"]
    assert isinstance(data["deposit_account_number"], str)
    assert data["status"] in ("PROSPECT", "ONBOARDING", "ACTIVE", "SUSPENDED",
                              "TERMINATED")
    assert isinstance(data["collected_balance_accumulator_cents"], int)
    assert isinstance(data["days_in_cycle_elapsed"], int)


def assert_agreement(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["customer_id"], str)
    assert isinstance(data["bank_id"], str)
    assert isinstance(data["agreement_number"], str) and data["agreement_number"]
    assert isinstance(data["monthly_maintenance_fee_cents"], int)
    assert isinstance(data["per_item_capture_fee_cents"], int)
    assert isinstance(data["per_exception_decision_fee_cents"], int)
    assert isinstance(data["per_image_retrieval_fee_cents"], int)
    assert data["status"] in ("DRAFT", "IMPLEMENTED", "ACTIVE", "SUSPENDED",
                              "TERMINATED")


def assert_site(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["agreement_id"], str)
    assert isinstance(data["customer_id"], str)
    assert isinstance(data["bank_id"], str)
    assert isinstance(data["site_code"], str) and data["site_code"]
    assert isinstance(data["postal_box_address"], str)
    assert isinstance(data["daily_cutoff_time_local"], str)
    assert isinstance(data["timezone"], str)
    assert data["status"] in ("PROVISIONING", "LIVE", "SUSPENDED", "DECOMMISSIONED")


def assert_transmission_format(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["agreement_id"], str)
    assert data["format_kind"] in ("BAI2", "EDI820", "CUSTOM_CSV")
    assert isinstance(data["version_label"], str)
    assert data["status"] in ("DRAFT", "ACTIVE", "SUPERSEDED", "RETIRED")


def assert_batch(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["site_id"], str)
    assert isinstance(data["agreement_id"], str)
    assert isinstance(data["customer_id"], str)
    assert isinstance(data["bank_id"], str)
    assert isinstance(data["batch_reference"], str)
    assert isinstance(data["business_date"], str)
    assert isinstance(data["received_at"], str)
    for field in ("declared_item_count", "captured_item_count",
                  "accepted_item_count"):
        assert isinstance(data[field], int), f"{field} must be an integer"
    for field in ("declared_total_cents", "captured_total_cents",
                  "accepted_total_cents", "same_day_credit_cents"):
        assert isinstance(data[field], int), f"{field} must be an integer"
    assert data["capture_status"] in ("RECEIVED", "CAPTURING", "BALANCED",
                                      "OUT_OF_BALANCE", "CLOSED")
    assert data["transmission_status"] in ("PENDING", "TRANSMITTED",
                                           "TRANSMISSION_FAILED", "ACKED")
    assert data["batch_status"] in ("OPEN", "HELD", "DECISIONS_PENDING",
                                    "READY_TO_SETTLE", "SETTLED", "REJECTED")


def assert_item(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["batch_id"], str)
    assert isinstance(data["check_number"], str)
    assert isinstance(data["payer_routing_number"], str)
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["payee_name"], str)
    assert data["status"] in ("CAPTURED", "ACCEPTED", "RETURNED", "ON_EXCEPTION",
                              "DECISIONED_PAY", "DECISIONED_RETURN")


def assert_availability_schedule(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["site_id"], str)
    assert isinstance(data["routing_number_pattern"], str)
    assert data["tier"] in ("SAME_DAY", "ONE_DAY", "TWO_DAY")
    assert isinstance(data["effective_from"], str)
    assert isinstance(data["priority"], int)
    assert data["status"] in ("ACTIVE", "RETIRED")


def assert_exception_item(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["item_id"], str)
    assert isinstance(data["batch_id"], str)
    assert data["reason_code"] in ("AMOUNT_MISMATCH", "PAYEE_MISMATCH",
                                   "MISSING_INVOICE_REF", "STALE_DATED",
                                   "DUPLICATE_SUSPECTED")
    assert data["default_decision"] in ("PAY", "RETURN")
    assert data["status"] in ("PENDING", "DECIDED", "AUTO_DECISIONED", "ESCALATED")


def assert_image_request(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["customer_id"], str)
    assert isinstance(data["item_id"], str)
    assert data["request_reason"] in ("AUDIT", "DISPUTE_SUPPORT", "RESEARCH",
                                      "LEGAL")
    assert isinstance(data["requested_image_kinds"], list)
    assert data["status"] in ("REQUESTED", "FULFILLED", "DENIED", "EXPIRED")


def assert_analysis_cycle(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["customer_id"], str)
    assert isinstance(data["bank_id"], str)
    assert isinstance(data["cycle_index"], int) and data["cycle_index"] >= 1
    assert data["status"] in ("OPEN", "FINALIZED", "SETTLED", "DISPUTED")


def assert_line_item(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["cycle_id"], str)
    assert data["line_kind"] in ("MAINTENANCE", "PER_ITEM_CAPTURE",
                                 "PER_EXCEPTION_DECISION", "PER_IMAGE_RETRIEVAL",
                                 "SLA_CREDIT")
    assert isinstance(data["quantity"], int)
    assert isinstance(data["unit_price_cents"], int)
    assert isinstance(data["extended_amount_cents"], int)


def assert_sla_incident(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["customer_id"], str)
    assert data["incident_kind"] in ("LATE_TRANSMISSION", "LATE_IMAGE_FULFILLMENT",
                                     "MISSED_CUTOFF_POSTING", "DATA_FORMAT_ERROR")
    assert isinstance(data["occurred_on_business_date"], str)
    assert data["status"] in ("REPORTED", "CONFIRMED", "REJECTED", "CREDITED")


def assert_error_credit_request(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["customer_id"], str)
    assert isinstance(data["cycle_id"], str)
    assert isinstance(data["requested_credit_cents"], int)
    assert data["reason_code"] in ("SLA_NOT_APPLIED", "BILLING_RATE_ERROR",
                                   "DUPLICATE_CHARGE", "ECR_MISCALCULATION")
    assert data["status"] in ("SUBMITTED", "APPROVED", "PARTIALLY_APPROVED",
                              "DENIED")


# ---------------------------------------------------------------------------
# Domain invariants
# ---------------------------------------------------------------------------

def assert_batch_balance_invariant(data: dict):
    """The batch-balance reconciliation invariant (PRD §3.4): at BALANCED the
    captured tallies equal the courier manifest."""
    assert data["captured_item_count"] == data["declared_item_count"], (
        f"captured_item_count {data['captured_item_count']} != "
        f"declared_item_count {data['declared_item_count']}"
    )
    assert data["captured_total_cents"] == data["declared_total_cents"], (
        f"captured_total_cents {data['captured_total_cents']} != "
        f"declared_total_cents {data['declared_total_cents']}"
    )


def assert_net_amount_non_negative(data: dict):
    """The net-due non-negativity invariant (PRD §3.7): the bank never pays
    the customer for excess credit."""
    assert data["net_amount_due_cents"] >= 0, (
        f"net_amount_due_cents went negative: {data['net_amount_due_cents']}"
    )
