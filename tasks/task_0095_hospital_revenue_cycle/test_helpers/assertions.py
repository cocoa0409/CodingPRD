"""Entity assertions and domain invariant checkers for the Hospital Revenue Cycle API."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_mutable(data: dict):
    """id + created_at + updated_at + version for mutable account entities (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be int >= 1, got {data.get('version')!r}"
    )


def _assert_common_ledger(data: dict):
    """id + created_at ONLY for immutable ledger entries (PRD §2.4): no version, no updated_at."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "immutable ledger entry must NOT carry a version field"
    assert "updated_at" not in data, "immutable ledger entry must NOT carry an updated_at field"


def assert_payer(data: dict):
    _assert_common_mutable(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["payer_type"] in {"COMMERCIAL", "MEDICARE", "MEDICAID", "SELF_PAY"}
    assert isinstance(data["timely_filing_days"], int)
    assert isinstance(data["appeal_window_days"], int)
    assert isinstance(data["active"], bool)


def assert_patient(data: dict):
    _assert_common_mutable(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["date_of_birth"], str)
    assert data["financial_class"] in {"INSURED", "SELF_PAY", "CHARITY"}


def assert_policy(data: dict):
    _assert_common_mutable(data)
    assert is_valid_uuid(data["patient_id"])
    assert is_valid_uuid(data["payer_id"])
    assert isinstance(data["member_number"], str) and len(data["member_number"]) > 0
    assert isinstance(data["deductible_cents"], int)
    assert 0.0 <= data["coinsurance_pct"] <= 1.0
    assert isinstance(data["oop_max_cents"], int)
    assert data["status"] in {"UNVERIFIED", "ACTIVE", "TERMINATED"}


def assert_benefit_accumulator(data: dict):
    _assert_common_mutable(data)
    assert is_valid_uuid(data["policy_id"])
    assert isinstance(data["deductible_met_cents"], int) and data["deductible_met_cents"] >= 0
    assert isinstance(data["oop_met_cents"], int) and data["oop_met_cents"] >= 0


def assert_encounter(data: dict):
    _assert_common_mutable(data)
    assert is_valid_uuid(data["patient_id"])
    assert data["status"] in {
        "REGISTERED", "ELIGIBILITY_VERIFIED", "CHARGES_CAPTURED", "CODED", "BILLED", "CLOSED",
    }
    assert isinstance(data["total_charges_cents"], int)
    assert isinstance(data["patient_responsibility_cents"], int)
    assert isinstance(data["account_balance_cents"], int)


def assert_eligibility_check(data: dict):
    _assert_common_mutable(data)
    assert is_valid_uuid(data["encounter_id"])
    assert is_valid_uuid(data["policy_id"])
    assert data["result"] in {"ELIGIBLE", "INELIGIBLE"}
    assert isinstance(data["estimated_patient_responsibility_cents"], int)


def assert_charge(data: dict):
    _assert_common_mutable(data)
    assert is_valid_uuid(data["encounter_id"])
    assert isinstance(data["cpt_code"], str)
    assert isinstance(data["units"], int) and data["units"] >= 1
    assert isinstance(data["unit_price_cents"], int) and data["unit_price_cents"] >= 0
    assert isinstance(data["amount_cents"], int)
    assert data["status"] in {"POSTED", "VOIDED"}


def assert_coding_assignment(data: dict):
    _assert_common_mutable(data)
    assert is_valid_uuid(data["encounter_id"])
    assert isinstance(data["principal_icd10"], str)
    assert isinstance(data["secondary_icd10"], list)
    assert data["status"] in {"DRAFT", "FINALIZED", "AUDIT_HOLD", "CLEARED"}
    assert isinstance(data["compliance_risk_score"], int)


def assert_claim(data: dict):
    _assert_common_mutable(data)
    assert is_valid_uuid(data["encounter_id"])
    assert is_valid_uuid(data["payer_id"])
    assert data["status"] in {
        "SUBMITTED", "PAID", "PARTIALLY_PAID", "DENIED", "CORRECTED", "APPEALED", "VOID",
    }
    assert isinstance(data["billed_amount_cents"], int)
    assert isinstance(data["patient_responsibility_cents"], int)


def assert_claim_line(data: dict):
    _assert_common_mutable(data)
    assert is_valid_uuid(data["claim_id"])
    assert isinstance(data["line_allowed_cents"], int)
    assert isinstance(data["line_paid_cents"], int)


def assert_patient_statement(data: dict):
    _assert_common_mutable(data)
    assert is_valid_uuid(data["encounter_id"])
    assert isinstance(data["amount_due_cents"], int)
    assert isinstance(data["amount_paid_cents"], int)
    assert isinstance(data["written_off_cents"], int)
    assert data["status"] in {"ISSUED", "PARTIALLY_PAID", "PAID", "IN_COLLECTIONS", "WRITTEN_OFF"}


def assert_payment(data: dict):
    """Payment is an immutable ledger entry: id + created_at only (PRD §2.4)."""
    _assert_common_ledger(data)
    assert is_valid_uuid(data["statement_id"])
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 1
    assert data["method"] in {"CARD", "CASH", "CHECK", "EFT"}


def assert_write_off(data: dict):
    """WriteOff is an immutable ledger entry: id + created_at only (PRD §2.4)."""
    _assert_common_ledger(data)
    assert is_valid_uuid(data["statement_id"])
    assert isinstance(data["amount_cents"], int)
    assert data["reason"] in {"BAD_DEBT", "CHARITY", "SMALL_BALANCE"}
    assert isinstance(data["approved_by_user_id"], str) and len(data["approved_by_user_id"]) > 0


def assert_statement_money_conserved(data: dict):
    """Statement-dollar conservation: amount_due == amount_paid + written_off + outstanding,
    where outstanding floors at 0 (PRD §3.10/§3.11)."""
    outstanding = data["amount_due_cents"] - data["amount_paid_cents"] - data["written_off_cents"]
    assert outstanding >= 0, f"outstanding must not go negative, got {outstanding}"
