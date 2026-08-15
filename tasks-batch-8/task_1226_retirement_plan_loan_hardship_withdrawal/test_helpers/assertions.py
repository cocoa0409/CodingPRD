"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)


# ---------------------------------------------------------------------------
# Field-shape helpers
# ---------------------------------------------------------------------------


def _assert_common_fields(data: dict, label: str):
    """Every primary resource carries id + created_at + updated_at + version."""
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be ISO 8601"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{label}.updated_at must be ISO 8601"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{label}.version must be a positive integer"
    )


def _assert_append_only_fields(data: dict, label: str):
    """LoanInstallment, HardshipDocument, AuditEvent carry only id + created_at."""
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be ISO 8601"
    )
    assert "updated_at" not in data, f"{label} must not expose updated_at (append-only)"
    assert "version" not in data, f"{label} must not expose version (append-only)"


# ---------------------------------------------------------------------------
# Per-entity assertions
# ---------------------------------------------------------------------------


def assert_plan(data: dict):
    """Validate a Plan response."""
    _assert_common_fields(data, "Plan")
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["status"] in ("ACTIVE", "FROZEN", "TERMINATED")
    assert isinstance(data["max_loans_outstanding"], int)
    assert isinstance(data["min_loan_amount_cents"], int)
    assert isinstance(data["max_loan_amount_cents"], int)
    assert isinstance(data["max_term_months"], int)
    assert isinstance(data["interest_rate_bps"], int)
    assert data["day_count_convention"] in ("THIRTY_360", "ACT_360")
    assert isinstance(data["allows_refinance"], bool)
    assert isinstance(data["refinance_min_months_since_disbursement"], int)
    assert isinstance(data["hardship_suspension_months"], int)
    assert data["substantiation_standard"] in ("FULL_DOCUMENTATION", "SELF_CERTIFY")
    assert isinstance(data["withholding_rate_bps"], int)
    assert isinstance(data["allowed_hardship_reasons"], list)
    assert isinstance(data["loan_approval_chain"], list)
    assert isinstance(data["hardship_approval_chain"], list)


def assert_participant(data: dict):
    """Validate a Participant response."""
    _assert_common_fields(data, "Participant")
    assert is_valid_uuid(data.get("plan_id", "")), "plan_id must be a valid UUID"
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["vested_balance_cents"], int)
    assert data["employment_status"] in ("ACTIVE", "TERMINATED")
    assert data["contribution_status"] in ("NONE", "ACTIVE", "SUSPENDED", "TERMINATED")
    assert isinstance(data["ytd_taxable_distributions_cents"], int)


def assert_contribution_election(data: dict):
    """Validate a ContributionElection response."""
    _assert_common_fields(data, "ContributionElection")
    assert is_valid_uuid(data.get("participant_id", "")), (
        "participant_id must be a valid UUID"
    )
    assert isinstance(data["deferral_pct"], (int, float))
    assert 0 < data["deferral_pct"] <= 60
    assert data["status"] in ("ACTIVE", "SUSPENDED", "TERMINATED")


def assert_loan(data: dict):
    """Validate a Loan response."""
    _assert_common_fields(data, "Loan")
    assert is_valid_uuid(data.get("participant_id", "")), (
        "participant_id must be a valid UUID"
    )
    assert is_valid_uuid(data.get("plan_id", "")), "plan_id must be a valid UUID"
    assert isinstance(data["principal_amount_cents"], int)
    assert data["principal_amount_cents"] > 0
    assert isinstance(data["term_months"], int) and data["term_months"] > 0
    assert isinstance(data["interest_rate_bps"], int)
    assert data["day_count_convention"] in ("THIRTY_360", "ACT_360")
    assert data["lifecycle_status"] in (
        "REQUESTED", "APPROVED", "DENIED", "WITHDRAWN",
        "DISBURSED", "REPAID", "REFINANCED", "OFFSET",
    )
    assert data["delinquency_status"] in ("NONE", "CURRENT", "DELINQUENT", "DEEMED")


def assert_loan_installment(data: dict):
    """Validate a LoanInstallment response (append-only shape)."""
    _assert_append_only_fields(data, "LoanInstallment")
    assert is_valid_uuid(data.get("loan_id", "")), "loan_id must be a valid UUID"
    assert isinstance(data["installment_number"], int) and data["installment_number"] >= 1
    assert isinstance(data["scheduled_amount_cents"], int)
    assert isinstance(data["principal_portion_cents"], int)
    assert isinstance(data["interest_portion_cents"], int)
    assert isinstance(data["paid_amount_cents"], int)
    assert data["status"] in ("PENDING", "PAID", "MISSED", "CURED", "REBUILT", "CLOSED")


def assert_payroll_remittance(data: dict):
    """Validate a PayrollRemittance response."""
    _assert_common_fields(data, "PayrollRemittance")
    assert is_valid_uuid(data.get("participant_id", "")), (
        "participant_id must be a valid UUID"
    )
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert data["status"] in ("POSTED", "REVERSED")


def assert_hardship_request(data: dict):
    """Validate a HardshipRequest response."""
    _assert_common_fields(data, "HardshipRequest")
    assert is_valid_uuid(data.get("participant_id", "")), (
        "participant_id must be a valid UUID"
    )
    assert is_valid_uuid(data.get("plan_id", "")), "plan_id must be a valid UUID"
    assert data["reason_category"] in (
        "MEDICAL", "FUNERAL", "EVICTION", "TUITION", "HOME_PURCHASE", "DISASTER",
    )
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert data["amount_semantics"] in ("NET", "GROSS")
    assert isinstance(data["gross_withdrawal_cents"], int)
    assert isinstance(data["withholding_cents"], int)
    assert isinstance(data["fee_cents"], int)
    assert isinstance(data["net_disbursed_cents"], int)
    assert data["status"] in (
        "UNDER_REVIEW", "PENDING_DOCUMENTS", "APPROVED", "DENIED", "PAID", "WITHDRAWN",
    )


def assert_hardship_document(data: dict):
    """Validate a HardshipDocument response (append-only shape)."""
    _assert_append_only_fields(data, "HardshipDocument")
    assert is_valid_uuid(data.get("hardship_request_id", "")), (
        "hardship_request_id must be a valid UUID"
    )
    assert data["document_type"] in (
        "INVOICE", "MEDICAL_BILL", "BANK_STATEMENT",
        "ATTESTATION", "EVICTION_NOTICE", "OTHER",
    )
    assert isinstance(data["amount_cents"], int)


def assert_approval_task(data: dict):
    """Validate an ApprovalTask response."""
    _assert_common_fields(data, "ApprovalTask")
    assert is_valid_uuid(data.get("plan_id", "")), "plan_id must be a valid UUID"
    assert data["subject_type"] in ("LOAN", "HARDSHIP")
    assert isinstance(data["step_order"], int) and data["step_order"] >= 1
    assert data["approver_role"] in ("PLAN_SPONSOR", "RECORDKEEPER_ADMIN")
    assert data["status"] in (
        "PENDING", "APPROVED", "REJECTED", "DOCS_REQUESTED", "CANCELLED",
    )


def assert_suspension_record(data: dict):
    """Validate a SuspensionRecord response."""
    _assert_common_fields(data, "SuspensionRecord")
    assert is_valid_uuid(data.get("participant_id", "")), (
        "participant_id must be a valid UUID"
    )
    assert data["status"] in ("ACTIVE", "EXPIRED")


def assert_tax_event(data: dict):
    """Validate a TaxEvent response."""
    _assert_common_fields(data, "TaxEvent")
    assert is_valid_uuid(data.get("participant_id", "")), (
        "participant_id must be a valid UUID"
    )
    assert data["source_type"] in ("LOAN_DEEMED", "LOAN_OFFSET", "HARDSHIP_DISTRIBUTION")
    assert isinstance(data["taxable_amount_cents"], int)
    assert isinstance(data["tax_year"], int)
    assert data["status"] in ("PENDING", "REPORTED")


def assert_audit_event(data: dict):
    """Validate an AuditEvent response (append-only shape)."""
    _assert_append_only_fields(data, "AuditEvent")
    assert isinstance(data["actor_role"], str) and len(data["actor_role"]) > 0
    assert isinstance(data["actor_id"], str) and len(data["actor_id"]) > 0
    assert isinstance(data["action"], str) and len(data["action"]) > 0
    assert isinstance(data["subject_type"], str) and len(data["subject_type"]) > 0


# ---------------------------------------------------------------------------
# Domain invariant checkers
# ---------------------------------------------------------------------------


def assert_hardship_arithmetic_consistent(data: dict):
    """gross_withdrawal_cents - withholding_cents - fee_cents == net_disbursed_cents."""
    gross = data["gross_withdrawal_cents"]
    withholding = data["withholding_cents"]
    fee = data["fee_cents"]
    net = data["net_disbursed_cents"]
    assert gross - withholding - fee == net, (
        f"gross {gross} - withholding {withholding} - fee {fee} "
        f"!= net_disbursed {net}"
    )
