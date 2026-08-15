"""Entity assertions and domain invariant checkers (PRD §2.5, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

_ACCOUNT_STATUSES = [
    "OPEN", "IN_EARLY_OUT", "IN_COLLECTIONS", "WRITTEN_OFF",
    "CLOSED_PAID", "CLOSED_CHARITY",
]
_AGING_BUCKETS = ["CURRENT", "BUCKET_30", "BUCKET_60", "BUCKET_90", "BUCKET_120_PLUS"]
_CREDIT_STATUSES = [
    "NOT_REPORTED", "REPORTABLE", "REPORTED",
    "FROZEN_BY_DISPUTE", "SUPPRESSED_BY_CHARITY",
]


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def _assert_append_only_fields(data: dict):
    # PRD §2.5: append-only families carry only id + created_at from the
    # standard set — no updated_at, no version.
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def assert_self_pay_account(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["patient_mrn"], str) and data["patient_mrn"]
    assert isinstance(data["patient_name"], str)
    assert isinstance(data["original_balance_cents"], int)
    assert isinstance(data["current_balance_cents"], int)
    assert isinstance(data["guarantor_liability_date"], str)
    assert data["aging_bucket"] in _AGING_BUCKETS
    assert isinstance(data["statements_sent_count"], int)
    assert isinstance(data["charity_writeoff_total_cents"], int)
    assert isinstance(data["bad_debt_writeoff_total_cents"], int)
    assert isinstance(data["recovery_total_cents"], int)
    assert data["credit_reporting_status"] in _CREDIT_STATUSES
    assert data["status"] in _ACCOUNT_STATUSES


def assert_statement(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["account_id"], str)
    assert isinstance(data["statement_index"], int) and data["statement_index"] >= 1
    assert is_iso8601_timestamp(data.get("issued_at", ""))
    assert isinstance(data["due_date"], str)
    assert isinstance(data["balance_at_issue_cents"], int)
    assert data["status"] in ["SENT", "DELIVERED", "RETURNED_UNDELIVERABLE"]


def assert_screening(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["account_id"], str)
    assert data["screening_model"] in ["FPL_TIERED", "SCORE_BASED"]
    assert data["eligibility_outcome"] in [
        "FULL_CHARITY", "PARTIAL_CHARITY", "NOT_ELIGIBLE", "PENDING",
    ]
    assert data["charity_writeoff_percent"] in (0, 50, 100) or data["charity_writeoff_percent"] is None
    assert data["status"] in ["PENDING", "EVALUATED", "SUPERSEDED", "APPLIED"]


def assert_early_out_placement(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["account_id"], str)
    assert isinstance(data["vendor_name"], str)
    assert isinstance(data["placement_balance_cents"], int)
    assert isinstance(data["contingency_fee_bps"], int)
    assert is_iso8601_timestamp(data.get("placed_at", ""))
    assert isinstance(data["recall_deadline"], str)
    assert isinstance(data["recovered_cents"], int)
    assert data["status"] in ["ACTIVE", "RECALLED", "ESCALATED_TO_AGENCY", "COMPLETED_PAID"]


def assert_agency_placement(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["account_id"], str)
    assert isinstance(data["agency_name"], str)
    assert isinstance(data["placement_balance_cents"], int)
    assert isinstance(data["contingency_fee_bps"], int)
    assert is_iso8601_timestamp(data.get("placed_at", ""))
    assert isinstance(data["recall_window_closes_at"], str)
    assert isinstance(data["recovered_cents"], int)
    assert data["status"] in [
        "ACTIVE", "RECALLED_NO_FEE", "RECALLED_WITH_FEE", "CLOSED_PAID", "CLOSED_DISPUTE",
    ]


def assert_dispute(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["account_id"], str)
    assert isinstance(data["dispute_reason"], str)
    assert isinstance(data["dispute_amount_cents"], int)
    assert is_iso8601_timestamp(data.get("filed_at", ""))
    assert isinstance(data["investigation_due_at"], str)
    assert data["status"] in ["OPEN", "RESOLVED", "EXPIRED"]


def assert_payment_plan(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["account_id"], str)
    assert isinstance(data["installment_amount_cents"], int) and data["installment_amount_cents"] > 0
    assert isinstance(data["installment_count"], int) and data["installment_count"] >= 2
    assert isinstance(data["first_installment_due"], str)
    assert isinstance(data["installments_paid_count"], int)
    assert isinstance(data["missed_installment_count"], int)
    assert data["status"] in ["ACTIVE", "IN_DEFAULT", "CURED", "COMPLETED", "TERMINATED_DEFAULT"]


def assert_write_off(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["account_id"], str)
    assert data["write_off_kind"] in ["BAD_DEBT", "CHARITY_CARE"]
    assert data["status"] in ["PENDING_APPROVAL", "POSTED", "REVERSED"]


def assert_recovery_transaction(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["account_id"], str)
    assert data["payment_kind"] in [
        "INSTALLMENT", "LUMP_SUM", "AGENCY_REMITTANCE",
        "EARLY_OUT_REMITTANCE", "POST_WRITEOFF_RECOVERY",
    ]
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["net_to_hospital_cents"], int)
    assert is_iso8601_timestamp(data.get("posted_at", ""))


def assert_medicare_log_entry(data: dict):
    _assert_append_only_fields(data)
    assert isinstance(data["write_off_id"], str)
    assert isinstance(data["account_id"], str)
    assert isinstance(data["cost_report_year"], int)
    assert isinstance(data["claimed_amount_cents"], int)
    assert isinstance(data["indigence_documented"], bool)
    assert isinstance(data["collection_effort_days"], int)


def assert_vendor_snapshot(data: dict):
    _assert_append_only_fields(data)
    assert isinstance(data["vendor_name"], str)
    assert isinstance(data["snapshot_period_start"], str)
    assert isinstance(data["snapshot_period_end"], str)
    assert isinstance(data["placements_in_window"], int)
    assert isinstance(data["recovered_in_window_cents"], int)
    assert isinstance(data["recovery_rate_bps"], int)
    assert isinstance(data["meets_minimum_threshold"], bool)


def assert_account_invariants(data: dict):
    """Balance-integrity invariants (PRD §2.8) that must hold after any read."""
    assert data["current_balance_cents"] >= 0, "current_balance_cents may never go negative"
    assert data["charity_writeoff_total_cents"] >= 0
    assert data["bad_debt_writeoff_total_cents"] >= 0
    assert data["recovery_total_cents"] >= 0
    assert data["statements_sent_count"] >= 0
