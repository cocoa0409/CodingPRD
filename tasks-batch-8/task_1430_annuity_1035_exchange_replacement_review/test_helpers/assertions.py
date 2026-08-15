"""Entity assertions and domain invariant checkers (PRD §2.5, §3)."""
from datetime import datetime, timezone

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    REQUIRED_DOC_TYPES,
    AnalysisStatus,
    CaseStatus,
    Decision,
    DecisionStage,
    DocType,
    DocumentStatus,
    EventType,
    ExchangeType,
    ProducerStatus,
    ContractStatus,
    TransferStatus,
)


def _parse_instant(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(
        timezone.utc
    )


def assert_logical_instant(actual: str, expected_iso: str, label: str = "timestamp"):
    """Compare two logical-clock instants regardless of ISO serialization
    variant (both readings of the same clock value compare equal)."""
    assert actual is not None and isinstance(actual, str), f"{label} must be set"
    assert _parse_instant(actual) == _parse_instant(expected_iso), (
        f"{label}: expected instant {expected_iso}, got {actual}"
    )


def assert_common_fields(data: dict):
    """Fields carried by every non-audit resource (PRD §2.5)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "created_at must be ISO 8601"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        "updated_at must be ISO 8601"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        "version must be a positive integer"
    )


def assert_producer(data: dict):
    assert_common_fields(data)
    assert isinstance(data["license_number"], str) and data["license_number"]
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["home_state_code"], str) and data["home_state_code"]
    assert data["status"] in [s.value for s in ProducerStatus]
    for counter in (
        "submitted_case_count_12m",
        "completed_exchange_count_12m",
        "rescinded_exchange_count_12m",
        "rescission_rate_completed_bps",
        "rescission_rate_submitted_bps",
    ):
        assert isinstance(data.get(counter), int) and data[counter] >= 0, (
            f"{counter} must be a non-negative integer"
        )


def assert_client(data: dict):
    assert_common_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["date_of_birth"], str) and data["date_of_birth"]
    assert isinstance(data["state_code"], str) and data["state_code"]
    assert isinstance(data.get("age_years"), int) and data["age_years"] >= 0
    assert isinstance(data.get("is_senior"), bool)


def assert_contract(data: dict):
    assert_common_fields(data)
    assert data["status"] in [s.value for s in ContractStatus]
    assert isinstance(data["carrier_name"], str) and data["carrier_name"]
    assert isinstance(data["contract_number"], str) and data["contract_number"]
    assert isinstance(data.get("account_value_cents"), int)
    assert isinstance(data.get("tax_basis_cents"), int)
    assert isinstance(data.get("surrender_schedule"), list)
    for entry in data["surrender_schedule"]:
        assert isinstance(entry["contract_year"], int) and entry["contract_year"] >= 1
        assert 0 <= entry["pct_bps"] <= 10000
    assert isinstance(data.get("living_benefit_rider"), bool)


def assert_case(data: dict):
    assert_common_fields(data)
    assert data["status"] in [s.value for s in CaseStatus]
    assert data["exchange_type"] in [t.value for t in ExchangeType]
    assert isinstance(data.get("producer_id"), str) and data["producer_id"]
    assert isinstance(data.get("client_id"), str) and data["client_id"]
    assert isinstance(data.get("existing_contract_id"), str)
    assert isinstance(data.get("new_product_code"), str)
    assert isinstance(data.get("new_product_surrender_years"), int)


def assert_document(data: dict):
    assert_common_fields(data)
    assert data["doc_type"] in [t.value for t in DocType]
    assert data["status"] in [s.value for s in DocumentStatus]
    assert isinstance(data.get("revision"), int) and data["revision"] >= 1


def assert_analysis(data: dict):
    assert_common_fields(data)
    assert data["status"] in [s.value for s in AnalysisStatus]
    for field in (
        "assumed_old_growth_bps",
        "assumed_new_growth_bps",
        "exchange_base_cents",
        "surrender_pct_bps_today",
        "surrender_charge_today_cents",
        "surrender_pct_bps_at_settlement",
        "surrender_charge_at_settlement_cents",
        "amount_received_cents",
        "bonus_credit_cents",
        "benefit_loss_cents",
        "net_replacement_cost_cents",
        "break_even_years",
        "basis_transferred_cents",
        "basis_remaining_cents",
    ):
        assert isinstance(data.get(field), int), f"{field} must be an integer"
    assert is_iso8601_timestamp(data.get("analysis_date", "")), (
        "analysis_date must be ISO 8601"
    )


def assert_funds_transfer(data: dict):
    assert_common_fields(data)
    assert data["status"] in [s.value for s in TransferStatus]
    for field in (
        "amount_cents",
        "surrender_charge_cents",
        "basis_transferred_cents",
        "pre_exchange_value_cents",
        "pre_exchange_basis_cents",
    ):
        assert isinstance(data.get(field), int), f"{field} must be an integer"
    assert is_iso8601_timestamp(data.get("requested_at", "")), (
        "requested_at must be ISO 8601"
    )


def assert_review_decision(data: dict):
    """Audit record: only id + created_at are guaranteed (PRD §2.5)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "created_at must be ISO 8601"
    )
    assert "updated_at" not in data, "review decisions carry no updated_at"
    assert "version" not in data, "review decisions carry no version"
    assert data["stage"] in [s.value for s in DecisionStage]
    assert data["decision"] in [d.value for d in Decision]
    assert isinstance(data.get("reviewer_id"), str) and data["reviewer_id"]
    assert isinstance(data.get("case_id"), str) and data["case_id"]


def assert_activity_event(data: dict):
    """Audit record: only id + created_at are guaranteed (PRD §2.5)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "created_at must be ISO 8601"
    )
    assert "updated_at" not in data, "activity events carry no updated_at"
    assert "version" not in data, "activity events carry no version"
    assert data["event_type"] in [e.value for e in EventType]
    assert isinstance(data.get("producer_id"), str) and data["producer_id"]
    assert is_iso8601_timestamp(data.get("event_at", "")), (
        "event_at must be ISO 8601"
    )


def assert_basis_conservation(
    basis_transferred_cents: int, basis_remaining_cents: int, original_basis_cents: int
):
    """Tax basis is neither leaked nor created by the pro-rata allocation
    (PRD §3.4)."""
    assert basis_transferred_cents + basis_remaining_cents == original_basis_cents, (
        f"basis not conserved: {basis_transferred_cents} + "
        f"{basis_remaining_cents} != {original_basis_cents}"
    )
