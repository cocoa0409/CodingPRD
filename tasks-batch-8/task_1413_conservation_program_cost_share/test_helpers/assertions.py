"""Entity assertions and domain invariant checkers (PRD §2.4, §2.8, §3.6)."""
from datetime import datetime

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    AdvanceStatus,
    ApplicationStatus,
    CertificationStatus,
    ContractStatus,
    DemandStatus,
    ModificationStatus,
    ObligationStatus,
    PaymentRequestStatus,
    PaymentStatus,
    ProgramStatus,
    SpotCheckStatus,
)


def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 instant, tolerating 'Z' and optional fractional digits."""
    v = value.strip()
    if v.endswith("Z"):
        v = v[:-1] + "+00:00"
    return datetime.fromisoformat(v)


def assert_instant_equal(actual: str, expected_iso: str, label: str = "instant"):
    """Assert two ISO 8601 strings denote the same instant (format-agnostic)."""
    assert parse_instant(actual) == parse_instant(expected_iso), (
        f"{label}: expected instant {expected_iso}, got {actual}"
    )


def _assert_common_fields(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{entity}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"{entity}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity}.version must be a positive integer"
    )


def _assert_config_row_fields(data: dict, entity: str):
    # Immutable configuration rows carry only id + created_at (PRD §2.4).
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{entity}.created_at must be ISO 8601"
    assert "updated_at" not in data, f"{entity} must not expose updated_at"
    assert "version" not in data, f"{entity} must not expose version"


def assert_program(data: dict):
    _assert_common_fields(data, "ConservationProgram")
    assert data["status"] in [s.value for s in ProgramStatus]
    assert isinstance(data["program_name"], str)
    assert isinstance(data["fiscal_year"], int)
    assert isinstance(data["state_code"], str)
    assert isinstance(data["ranking_run_count"], int)


def assert_pool(data: dict):
    _assert_common_fields(data, "FundingPool")
    assert isinstance(data["allocated_cents"], int)
    assert isinstance(data["obligated_cents"], int)
    assert isinstance(data["paid_cents"], int)
    assert isinstance(data["available_cents"], int)


def assert_rate(data: dict):
    _assert_config_row_fields(data, "PaymentScheduleRate")
    assert isinstance(data["practice_code"], str)
    assert isinstance(data["standard_rate_cents"], int)
    assert isinstance(data["hu_rate_cents"], int)
    assert isinstance(data["lifespan_years"], int)


def assert_criterion(data: dict):
    _assert_config_row_fields(data, "RankingCriterion")
    assert isinstance(data["criterion_code"], str)
    assert isinstance(data["max_points"], int)


def assert_applicant(data: dict):
    _assert_common_fields(data, "Applicant")
    assert isinstance(data["legal_name"], str)
    assert isinstance(data["historically_underserved"], bool)
    assert isinstance(data["parcel_ids"], list)


def assert_application(data: dict):
    _assert_common_fields(data, "Application")
    assert data["status"] in [s.value for s in ApplicationStatus]
    assert isinstance(data["program_id"], str)
    assert isinstance(data["applicant_id"], str)
    assert isinstance(data["parcel_id"], str)


def assert_contract(data: dict):
    _assert_common_fields(data, "Contract")
    assert data["status"] in [s.value for s in ContractStatus]
    assert isinstance(data["program_id"], str)
    assert isinstance(data["application_id"], str)
    assert isinstance(data["applicant_id"], str)
    assert isinstance(data["pool_id"], str)
    assert isinstance(data["obligated_amount_cents"], int)
    assert isinstance(data["paid_amount_cents"], int)


def assert_practice_item(data: dict):
    _assert_common_fields(data, "ContractPracticeItem")
    assert data["certification_status"] in [s.value for s in CertificationStatus]
    assert data["payment_status"] in [s.value for s in PaymentStatus]
    assert isinstance(data["contract_id"], str)
    assert isinstance(data["practice_code"], str)
    assert isinstance(data["scheduled_amount_cents"], int)
    assert isinstance(data["applicable_rate_cents"], int)


def assert_payment_request(data: dict):
    _assert_common_fields(data, "PaymentRequest")
    assert data["status"] in [s.value for s in PaymentRequestStatus]
    assert isinstance(data["contract_id"], str)
    assert isinstance(data["practice_item_id"], str)
    assert isinstance(data["sequence_number"], int)
    assert isinstance(data["sampled"], bool)
    assert isinstance(data["computed_amount_cents"], int)


def assert_advance(data: dict):
    _assert_common_fields(data, "AdvancePayment")
    assert data["status"] in [s.value for s in AdvanceStatus]
    assert isinstance(data["contract_id"], str)
    assert isinstance(data["practice_item_id"], str)
    assert isinstance(data["issued_cents"], int)
    assert isinstance(data["outstanding_cents"], int)


def assert_modification(data: dict):
    _assert_common_fields(data, "ContractModification")
    assert data["status"] in [s.value for s in ModificationStatus]
    assert isinstance(data["contract_id"], str)
    assert isinstance(data["kind"], str)


def assert_spot_check(data: dict):
    _assert_common_fields(data, "SpotCheck")
    assert data["status"] in [s.value for s in SpotCheckStatus]
    assert isinstance(data["contract_id"], str)
    assert isinstance(data["practice_item_id"], str)
    assert isinstance(data["inspector_user_id"], str)


def assert_maintenance_obligation(data: dict):
    _assert_common_fields(data, "MaintenanceObligation")
    assert data["status"] in [s.value for s in ObligationStatus]
    assert isinstance(data["contract_id"], str)
    assert isinstance(data["practice_item_id"], str)
    assert isinstance(data["parcel_id"], str)
    assert isinstance(data["practice_code"], str)


def assert_recoupment_demand(data: dict):
    _assert_common_fields(data, "RecoupmentDemand")
    assert data["status"] in [s.value for s in DemandStatus]
    assert isinstance(data["contract_id"], str)
    assert isinstance(data["amount_cents"], int)


def assert_pool_invariants(pool: dict):
    """Funding-pool conservation invariant (PRD §2.8):
    allocated always equals available + obligated + paid."""
    assert pool["allocated_cents"] == (
        pool["available_cents"] + pool["obligated_cents"] + pool["paid_cents"]
    ), (
        f"pool conservation broken: allocated {pool['allocated_cents']} != "
        f"available {pool['available_cents']} + obligated {pool['obligated_cents']} "
        f"+ paid {pool['paid_cents']}"
    )
    assert pool["obligated_cents"] >= 0
    assert pool["paid_cents"] >= 0
    assert pool["available_cents"] >= 0


def assert_advance_invariants(advance: dict):
    """Advance accounting invariant (PRD §3.6):
    issued always equals applied + returned + outstanding."""
    assert advance["issued_cents"] == (
        advance["applied_cents"] + advance["returned_cents"] + advance["outstanding_cents"]
    ), (
        f"advance accounting broken: issued {advance['issued_cents']} != "
        f"applied {advance['applied_cents']} + returned {advance['returned_cents']} "
        f"+ outstanding {advance['outstanding_cents']}"
    )
