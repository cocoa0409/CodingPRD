"""Entity assertions and domain invariant checkers.

Each assert_{entity}() validates the shape/typing of a returned resource. Domain
invariant checkers assert relationships the PRD guarantees at all times.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"version must be an int >= 1, got {data.get('version')!r}"


def assert_portfolio(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str)
    assert isinstance(data["exposure_cap_cents"], int)
    for f in ("total_active_coverage_cents", "total_outstanding_recovery_cents",
              "risk_weighted_exposure_cents"):
        assert isinstance(data[f], int), f"{f} must be int"
    assert data["posture"] in ("OPEN", "RESTRICTED")


def assert_applicant(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str)
    assert isinstance(data["annual_income_cents"], int)
    assert 300 <= data["credit_score"] <= 850
    assert data["employment_type"] in ("SALARIED", "SELF_EMPLOYED", "RETIRED", "UNEMPLOYED")
    assert data["status"] in ("DRAFT", "VERIFIED", "DECLINED")
    assert data["risk_tier"] in (None, "A", "B", "C", "D")
    assert isinstance(data["default_count"], int)
    assert isinstance(data["open_recovery_count"], int)


def assert_landlord(data: dict):
    _assert_common(data)
    assert isinstance(data["legal_name"], str)
    assert data["status"] == "ACTIVE"


def assert_guarantee(data: dict):
    _assert_common(data)
    assert isinstance(data["portfolio_id"], str)
    assert isinstance(data["applicant_id"], str)
    assert isinstance(data["unit_id"], str)
    assert isinstance(data["monthly_rent_cents"], int)
    assert isinstance(data["coverage_months"], int)
    assert isinstance(data["term_months"], int)
    assert isinstance(data["per_month_coverage_cents"], int)
    assert isinstance(data["total_coverage_cents"], int)
    assert isinstance(data["provisional_fee_cents"], int)
    assert isinstance(data["paid_out_cents"], int)
    assert isinstance(data["renewal_count"], int)
    assert isinstance(data["fee_paid"], bool)
    assert data["status"] in ("QUOTED", "APPROVED", "ACTIVE", "RENEWAL_PENDING",
                              "EXHAUSTED", "DEFAULTED", "CANCELLED")


def assert_agreement(data: dict):
    _assert_common(data)
    assert isinstance(data["guarantee_id"], str)
    assert isinstance(data["landlord_id"], str)
    assert isinstance(data["unit_id"], str)
    assert isinstance(data["notice_period_days"], int)
    assert data["status"] in ("DRAFT", "SIGNED", "ACTIVE", "TERMINATED")


def assert_claim(data: dict):
    _assert_common(data)
    assert isinstance(data["guarantee_id"], str)
    assert isinstance(data["missed_months"], int)
    assert isinstance(data["acceleration_requested"], bool)
    assert data["status"] in ("SUBMITTED", "UNDER_REVIEW", "APPROVED", "PAID",
                              "DENIED", "WITHDRAWN")
    assert data["payout_variant"] in (None, "CHRONOLOGICAL", "ACCELERATED")


def assert_recovery_plan(data: dict):
    _assert_common(data)
    assert isinstance(data["principal_cents"], int)
    assert isinstance(data["recovered_cents"], int)
    assert isinstance(data["outstanding_cents"], int)
    assert data["status"] in ("ACTIVE", "SETTLED", "WRITTEN_OFF")
    assert_recovery_principal_conserved(data)


def assert_recovery_installment(data: dict):
    _assert_common(data)
    assert isinstance(data["recovery_plan_id"], str)
    assert isinstance(data["amount_cents"], int)
    assert data["status"] in ("POSTED", "REVERSED")


def assert_compliance_review(data: dict):
    _assert_common(data)
    assert isinstance(data["guarantee_id"], str)
    assert data["reason"] in ("KYC_MISMATCH", "SANCTIONS_HIT", "FRAUD_SUSPECTED",
                              "AUTO_DEFAULT_TRIGGER")
    assert data["status"] in ("OPEN", "CLEARED", "UPHELD")


def assert_ledger_entry(data: dict):
    """LedgerEntry is append-only: carries only id + created_at (no version/updated_at)."""
    assert is_valid_uuid(data.get("id", "")), "ledger id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["entry_type"] in ("FEE_CHARGED", "CLAIM_PAYOUT", "COVERAGE_RESET")
    assert data["direction"] in ("DEBIT", "CREDIT")


# --- Domain invariants (PRD-guaranteed relationships) ---
def assert_recovery_principal_conserved(plan: dict):
    """PRD §3.7: outstanding_cents + recovered_cents == principal_cents at all times."""
    assert plan["outstanding_cents"] + plan["recovered_cents"] == plan["principal_cents"], (
        f"recovery principal not conserved: outstanding {plan['outstanding_cents']} + "
        f"recovered {plan['recovered_cents']} != principal {plan['principal_cents']}"
    )
