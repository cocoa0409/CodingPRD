"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_audit_fields(data: dict):
    """id + created_at + updated_at + version present and well-formed."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an int"
    assert data["version"] >= 1, "version starts at 1"


def _assert_ledger_fields(data: dict):
    """Append-only ledger line: id + created_at only; NO updated_at, NO version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def assert_employer(data: dict):
    _assert_audit_fields(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["state_account_number"], str) and data["state_account_number"]
    assert isinstance(data["experience_rate"], (int, float))
    assert isinstance(data["reserve_account_balance_cents"], int)
    assert isinstance(data["charge_protest_count"], int)
    assert data["charge_protest_count"] >= 0


def assert_claimant(data: dict):
    _assert_audit_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["ssn_last4"], str)
    assert isinstance(data["is_able_and_available"], bool)


def assert_wage_record(data: dict):
    _assert_ledger_fields(data)
    assert "version" not in data, "WageRecord is append-only: must not expose version"
    assert "updated_at" not in data, "WageRecord is append-only: must not expose updated_at"
    assert isinstance(data["gross_wages_cents"], int)
    assert isinstance(data["is_disputed"], bool)


def assert_claim(data: dict):
    _assert_audit_fields(data)
    assert is_valid_uuid(data.get("claimant_id", "")), "claimant_id must be a UUID"
    assert data["status"] in [
        "DRAFT", "MONETARY_PENDING", "MONETARILY_ELIGIBLE",
        "MONETARILY_INELIGIBLE", "EXHAUSTED", "CLOSED",
    ]
    assert isinstance(data["weekly_benefit_amount_cents"], int)
    assert isinstance(data["maximum_benefit_amount_cents"], int)
    assert isinstance(data["remaining_balance_cents"], int)
    assert isinstance(data["extension_weeks_granted"], int)


def assert_determination(data: dict):
    _assert_audit_fields(data)
    assert data["determination_type"] in ["MONETARY", "NONMONETARY"]
    assert data["outcome"] in ["PENDING", "ALLOWED", "DENIED", "REVERSED"]
    assert isinstance(data["base_period_total_wages_cents"], int)
    assert isinstance(data["high_quarter_wages_cents"], int)
    assert isinstance(data["is_appealable"], bool)


def assert_weekly_certification(data: dict):
    _assert_audit_fields(data)
    assert data["adjudication_status"] in ["PENDING", "ELIGIBLE", "INELIGIBLE", "HELD"]
    assert data["payment_status"] in ["UNPAID", "PAID", "OFFSET", "DENIED"]
    assert isinstance(data["work_search_required"], bool)
    assert isinstance(data["payable_amount_cents"], int)


def assert_work_search_contact(data: dict):
    _assert_ledger_fields(data)
    assert "version" not in data, "WorkSearchContact is append-only: must not expose version"
    assert "updated_at" not in data, "WorkSearchContact is append-only: must not expose updated_at"
    assert data["contact_type"] in [
        "EMPLOYER_APPLICATION", "INTERVIEW", "JOB_FAIR", "REEMPLOYMENT_WORKSHOP",
    ]


def assert_employer_charge(data: dict):
    _assert_audit_fields(data)
    assert data["status"] in ["POSTED", "PROTESTED", "RELIEVED"]
    assert isinstance(data["charge_amount_cents"], int)


def assert_overpayment(data: dict):
    _assert_audit_fields(data)
    assert data["cause"] in ["FRAUD", "NONFRAUD"]
    assert data["status"] in ["ESTABLISHED", "RECOVERING", "SATISFIED", "WAIVED"]
    assert isinstance(data["principal_cents"], int)
    assert isinstance(data["penalty_cents"], int)
    assert isinstance(data["total_assessed_cents"], int)
    assert isinstance(data["recovered_cents"], int)


def assert_overpayment_recovery(data: dict):
    _assert_audit_fields(data)
    assert data["status"] == "APPLIED"
    assert data["recovery_method"] in ["OFFSET", "CASH"]
    assert isinstance(data["amount_cents"], int)


def assert_appeal(data: dict):
    _assert_audit_fields(data)
    assert data["filed_by"] in ["CLAIMANT", "EMPLOYER"]
    assert data["status"] in [
        "SUBMITTED", "UNDER_REVIEW", "REMANDED", "DECIDED_AFFIRMED",
        "DECIDED_REVERSED", "WITHDRAWN", "DISMISSED",
    ]
    assert isinstance(data["remand_count"], int)


def assert_extension_program(data: dict):
    _assert_audit_fields(data)
    assert isinstance(data["program_code"], str) and data["program_code"]
    assert isinstance(data["extra_weeks"], int)
    assert isinstance(data["is_active"], bool)


def assert_overpayment_conserved(data: dict):
    """Invariant: recovered_cents never exceeds total_assessed_cents, and a
    SATISFIED overpayment has recovered_cents == total_assessed_cents exactly."""
    assert data["recovered_cents"] <= data["total_assessed_cents"], (
        "recovered_cents must never exceed total_assessed_cents"
    )
    if data["status"] == "SATISFIED":
        assert data["recovered_cents"] == data["total_assessed_cents"], (
            "SATISFIED overpayment must have recovered_cents == total_assessed_cents"
        )
