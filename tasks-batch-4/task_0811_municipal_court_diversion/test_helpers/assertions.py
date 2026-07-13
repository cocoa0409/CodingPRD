"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import (
    is_valid_uuid,
    is_iso8601_timestamp,
    assert_cost_precision,
)


def _common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def _common_with_version(data: dict):
    _common(data)
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1


def assert_defendant(data: dict):
    _common_with_version(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["date_of_birth"], str)
    assert isinstance(data["email"], str)
    assert isinstance(data["prior_diversion_count"], int) and data["prior_diversion_count"] >= 0


def assert_case(data: dict):
    _common_with_version(data)
    assert isinstance(data["defendant_id"], str)
    assert isinstance(data["citation_number"], str)
    assert data["status"] in [
        "DOCKETED", "ARRAIGNED", "DIVERSION_GRANTED",
        "FAILED_TO_COMPLY", "COMPLIED", "DISMISSED",
    ]


def assert_charge(data: dict):
    _common_with_version(data)
    assert isinstance(data["case_id"], str)
    assert isinstance(data["offense_code"], str)
    assert data["severity"] in ["INFRACTION", "MISDEMEANOR"]
    assert isinstance(data["base_fine_amount"], (int, float)) and data["base_fine_amount"] >= 0
    assert isinstance(data["is_diversion_eligible"], bool)


def assert_courtroom(data: dict):
    _common_with_version(data)
    assert isinstance(data["name"], str)
    assert isinstance(data["room_code"], str)
    assert isinstance(data["changeover_buffer_minutes"], int) and data["changeover_buffer_minutes"] >= 0


def assert_arraignment(data: dict):
    _common_with_version(data)
    assert isinstance(data["case_id"], str)
    assert isinstance(data["courtroom_id"], str)
    assert data["status"] in ["SCHEDULED", "HELD"]


def assert_diversion_agreement(data: dict):
    _common_with_version(data)
    assert isinstance(data["case_id"], str)
    assert data["status"] in ["OFFERED", "IN_PROGRESS", "COMPLETED", "DEFAULTED"]
    assert isinstance(data["mandated_service_hours"], (int, float))
    assert isinstance(data["required_class_sessions"], int)


def assert_service_site(data: dict):
    _common_with_version(data)
    assert isinstance(data["name"], str)
    assert data["site_type"] in ["COMMUNITY_SERVICE", "EDUCATION_CLASS"]
    assert isinstance(data["concurrent_capacity"], int) and data["concurrent_capacity"] >= 1


def assert_service_assignment(data: dict):
    _common_with_version(data)
    assert isinstance(data["diversion_id"], str)
    assert isinstance(data["service_site_id"], str)
    assert data["assignment_type"] in ["COMMUNITY_SERVICE", "EDUCATION_CLASS"]
    assert data["status"] in ["ASSIGNED", "IN_PROGRESS", "COMPLETED", "WAIVED"]


def assert_ledger_account(data: dict):
    _common_with_version(data)
    assert isinstance(data["case_id"], str)
    assert data["status"] in ["PROVISIONAL", "ASSESSED", "SETTLED", "CLOSED"]
    for field in ("assessed_amount", "collected_amount", "balance"):
        assert isinstance(data[field], (int, float)), f"{field} must be numeric"
        assert_cost_precision(data[field])


def assert_installment_plan(data: dict):
    _common_with_version(data)
    assert isinstance(data["ledger_account_id"], str)
    assert isinstance(data["num_installments"], int)
    assert data["status"] in ["ACTIVE", "DELINQUENT", "PAID_OFF", "SUPERSEDED"]


def assert_payment(data: dict):
    # Payment is an immutable ledger entry: id + created_at only, no updated_at/version.
    _common(data)
    assert "updated_at" not in data, "Payment must not carry updated_at"
    assert "version" not in data, "Payment must not carry version"
    assert isinstance(data["amount"], (int, float)) and data["amount"] > 0
    assert isinstance(data["reversed"], bool)


def assert_warrant(data: dict):
    _common_with_version(data)
    assert isinstance(data["case_id"], str)
    assert data["status"] in ["ISSUED", "RECALLED"]


def assert_amnesty_program(data: dict):
    _common_with_version(data)
    assert isinstance(data["name"], str)
    assert 0 <= data["penalty_waiver_pct"] <= 1


def assert_expungement_referral(data: dict):
    _common_with_version(data)
    assert isinstance(data["case_id"], str)
    assert data["status"] in ["PENDING", "SUBMITTED"]


def assert_ledger_balance_invariant(account: dict, non_reversed_payment_sum: float):
    """Conserved money quantity (PRD §2.10): balance == assessed_amount -
    sum(Payment.amount where reversed == false)."""
    assert account["balance"] == account["assessed_amount"] - account["collected_amount"], (
        "balance must equal assessed_amount - collected_amount"
    )
    assert account["collected_amount"] == non_reversed_payment_sum, (
        "collected_amount must equal the sum of non-reversed payment amounts"
    )


def assert_assigned_hours_invariant(agreement: dict, expected_non_waived_sum: float):
    """Conserved service quantity (PRD §2.10): assigned_service_hours ==
    sum(required_hours over assignments whose status != WAIVED)."""
    assert agreement["assigned_service_hours"] == expected_non_waived_sum, (
        "assigned_service_hours must equal the sum of required_hours over non-WAIVED assignments"
    )
