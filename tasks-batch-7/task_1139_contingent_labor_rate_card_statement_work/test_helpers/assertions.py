"""Entity assertions and domain invariant checkers.

These assert only field presence/types and enum membership stated in the PRD;
business values are asserted in the tests themselves.
"""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    AssignmentStatus,
    AuditFinding,
    AuditSeverity,
    AuditStatus,
    ConversionRequestStatus,
    ConversionStatus,
    EngagementStatus,
    EngagementType,
    InvoiceStatus,
    LedgerEntryType,
    MilestoneAcceptanceStatus,
    MilestonePaymentStatus,
    OfferStatus,
    PaymentBasis,
    RateCardStatus,
    SupervisionLevel,
    SupplierStatus,
    SupplierTier,
    TimesheetStatus,
    WorkerStatus,
)


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a server-minted UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def _assert_append_only_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a server-minted UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "append-only kinds must not expose updated_at"
    assert "version" not in data, "append-only kinds must not expose version"


def assert_supplier(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["supplier_code"], str) and data["supplier_code"]
    assert data["tier"] in {t.value for t in SupplierTier}
    assert data["status"] in {s.value for s in SupplierStatus}
    assert data["tier_score"] is None or isinstance(data["tier_score"], int)
    for counter in (
        "offers_made_count",
        "offers_filled_count",
        "open_offers_count",
        "completed_assignments_count",
        "open_violation_count",
        "milestones_delivered_count",
        "milestones_accepted_count",
        "spend_ytd_cents",
    ):
        assert isinstance(data[counter], int), f"{counter} must be an integer"


def assert_rate_card(data: dict):
    _assert_common_fields(data)
    for key in ("role_code", "skill_code", "geo_code", "currency"):
        assert isinstance(data[key], str) and data[key]
    assert isinstance(data["pay_rate_floor_cents"], int)
    assert isinstance(data["bill_rate_ceiling_cents"], int)
    assert isinstance(data["max_markup_pct"], (int, float))
    assert isinstance(data["effective_from"], str)
    assert isinstance(data["effective_to"], str)
    assert data["status"] in {s.value for s in RateCardStatus}
    assert data["supersedes_id"] is None or is_valid_uuid(data["supersedes_id"])


def assert_engagement(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["title"], str)
    assert data["engagement_type"] in {t.value for t in EngagementType}
    for key in ("role_code", "skill_code", "geo_code"):
        assert isinstance(data[key], str) and data[key]
    assert data["payment_basis"] in {b.value for b in PaymentBasis}
    assert data["supervision_level"] in {s.value for s in SupervisionLevel}
    assert isinstance(data["duration_months"], int)
    assert isinstance(data["budget_cents"], int)
    assert isinstance(data["prorata_conversion"], bool)
    assert data["status"] in {s.value for s in EngagementStatus}
    assert data["misclassification_risk"] in (None, "LOW", "HIGH")
    assert data["awarded_supplier_id"] is None or is_valid_uuid(data["awarded_supplier_id"])
    assert isinstance(data["committed_spend_cents"], int)
    assert isinstance(data["budget_audit_raised"], bool)


def assert_distribution_offer(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["engagement_id"])
    assert is_valid_uuid(data["supplier_id"])
    assert data["status"] in {s.value for s in OfferStatus}
    assert is_iso8601_timestamp(data["offered_at"])
    assert is_iso8601_timestamp(data["response_due_at"])
    assert data["responded_at"] is None or is_iso8601_timestamp(data["responded_at"])


def assert_worker(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["supplier_id"])
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert isinstance(data["tenure_carryover_days"], int)
    assert data["status"] in {s.value for s in WorkerStatus}
    assert data["conversion_status"] in {s.value for s in ConversionStatus}
    assert isinstance(data["cumulative_tenure_days"], int)


def assert_assignment(data: dict):
    _assert_common_fields(data)
    for key in ("worker_id", "engagement_id", "offer_id", "supplier_id", "rate_card_id"):
        assert is_valid_uuid(data[key]), f"{key} must be a UUID"
    assert isinstance(data["bill_rate_cents"], int)
    assert isinstance(data["pay_rate_cents"], int)
    assert isinstance(data["start_date"], str)
    assert isinstance(data["end_date"], str)
    assert data["actual_end_date"] is None or isinstance(data["actual_end_date"], str)
    assert data["status"] in {s.value for s in AssignmentStatus}
    assert data["termination_reason"] in (None, "MANUAL", "ENGAGEMENT_CLOSED", "CONVERTED")


def assert_timesheet(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["assignment_id"])
    assert isinstance(data["period_start"], str)
    assert isinstance(data["period_end"], str)
    assert isinstance(data["submitted_hours"], (int, float))
    assert data["approved_hours"] is None or isinstance(data["approved_hours"], (int, float))
    assert data["status"] in {s.value for s in TimesheetStatus}
    assert data["provisional_amount_cents"] is None or isinstance(
        data["provisional_amount_cents"], int
    )
    assert data["final_amount_cents"] is None or isinstance(data["final_amount_cents"], int)


def assert_milestone(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["engagement_id"])
    assert isinstance(data["name"], str)
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["due_date"], str)
    assert data["acceptance_status"] in {s.value for s in MilestoneAcceptanceStatus}
    assert data["payment_status"] in {s.value for s in MilestonePaymentStatus}


def assert_invoice(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["supplier_id"])
    assert isinstance(data["period_start"], str)
    assert isinstance(data["period_end"], str)
    assert data["status"] in {s.value for s in InvoiceStatus}
    for field in (
        "line_count",
        "subtotal_cents",
        "processing_fee_cents",
        "total_cents",
        "consolidation_savings_cents",
    ):
        assert isinstance(data[field], int), f"{field} must be an integer"


def assert_invoice_line(data: dict):
    _assert_append_only_fields(data)
    assert is_valid_uuid(data["invoice_id"])
    assert isinstance(data["amount_cents"], int)
    # Each line sources exactly one event: timesheet XOR milestone.
    has_ts = data.get("timesheet_id") is not None
    has_ms = data.get("milestone_id") is not None
    assert has_ts != has_ms, "line must source exactly one of timesheet_id / milestone_id"


def assert_conversion_request(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["worker_id"])
    assert is_valid_uuid(data["assignment_id"])
    assert isinstance(data["tenure_days_at_request"], int)
    assert data["fee_variant"] in ("SCHEDULE", "PRORATA")
    assert isinstance(data["fee_cents"], int)
    assert data["status"] in {s.value for s in ConversionRequestStatus}


def assert_compliance_audit(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["supplier_id"])
    assert data["finding"] in {f.value for f in AuditFinding}
    assert data["severity"] in {s.value for s in AuditSeverity}
    assert data["status"] in {s.value for s in AuditStatus}
    assert isinstance(data["details"], str)


def assert_spend_ledger_entry(data: dict):
    _assert_append_only_fields(data)
    assert is_valid_uuid(data["supplier_id"])
    assert is_valid_uuid(data["engagement_id"])
    assert data["entry_type"] in {t.value for t in LedgerEntryType}
    assert isinstance(data["delta_cents"], int)
    assert isinstance(data["running_balance_cents"], int)


def assert_ledger_sums_to_spend(entries: list, expected_spend_cents: int):
    """Domain invariant: supplier spend equals the sum of ledger deltas."""
    total = sum(e["delta_cents"] for e in entries)
    assert total == expected_spend_cents, (
        f"Ledger sum {total} != expected spend {expected_spend_cents}"
    )
