"""Entity assertions and domain invariant checkers (PRD §2.4, §2.7, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    AccountStatus,
    BackupStatus,
    CalibrationResult,
    CardStatus,
    ClaimStatus,
    CompressorCondition,
    ContractStatus,
    DispenserStatus,
    InspectionStatus,
    InspectionType,
    PolicyStatus,
    SessionStatus,
    StationStatus,
    UptimePosture,
    WindowStatus,
)

_ENUM_VALUES = {e.value for e in StationStatus}
_COMPRESSOR_VALUES = {e.value for e in CompressorCondition}
_DISPENSER_VALUES = {e.value for e in DispenserStatus}
_POLICY_VALUES = {e.value for e in PolicyStatus}
_ACCOUNT_VALUES = {e.value for e in AccountStatus}
_CARD_VALUES = {e.value for e in CardStatus}
_CONTRACT_VALUES = {e.value for e in ContractStatus}
_SESSION_VALUES = {e.value for e in SessionStatus}
_WINDOW_VALUES = {e.value for e in WindowStatus}
_BACKUP_VALUES = {e.value for e in BackupStatus}
_INSPECTION_VALUES = {e.value for e in InspectionStatus}
_INSPECTION_TYPE_VALUES = {e.value for e in InspectionType}
_CLAIM_VALUES = {e.value for e in ClaimStatus}
_POSTURE_VALUES = {e.value for e in UptimePosture}
_CAL_RESULT_VALUES = {e.value for e in CalibrationResult}


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        "version must be an integer starting at 1"
    )


def _assert_immutable_common_fields(data: dict):
    """Immutable records (calibration records, monthly settlements) carry only
    id and created_at among the common fields; version/updated_at are absent."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "immutable record must not expose version"
    assert "updated_at" not in data, "immutable record must not expose updated_at"


def assert_station(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["station_name"], str) and data["station_name"]
    assert isinstance(data["station_code"], str) and data["station_code"]
    assert data["access_mode"] in ("PUBLIC", "PRIVATE", "DUAL")
    assert isinstance(data["backup_capacity_gge"], int) and data["backup_capacity_gge"] > 0
    assert data["uptime_posture"] in _POSTURE_VALUES
    assert data["status"] in _ENUM_VALUES


def assert_compressor(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["station_id"])
    assert isinstance(data["compressor_code"], str) and data["compressor_code"]
    assert data["capacity_scf_per_minute"] > 0
    assert data["condition"] in _COMPRESSOR_VALUES


def assert_dispenser(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["station_id"])
    assert isinstance(data["dispenser_code"], str) and data["dispenser_code"]
    assert data["fuel_type"] in ("CNG", "RNG")
    assert data["status"] in _DISPENSER_VALUES


def assert_calibration_record(data: dict):
    _assert_immutable_common_fields(data)
    assert is_valid_uuid(data["dispenser_id"])
    assert data["result"] in _CAL_RESULT_VALUES
    assert is_iso8601_timestamp(data.get("performed_at", ""))


def assert_pricing_policy(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["station_id"])
    assert data["access_scope"] in ("PUBLIC", "PRIVATE")
    assert data["fuel_type"] in ("CNG", "RNG")
    assert isinstance(data["price_per_gge_cents"], int) and data["price_per_gge_cents"] > 0
    assert data["status"] in _POLICY_VALUES


def assert_fleet_account(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["account_name"], str) and data["account_name"]
    assert isinstance(data["credit_limit_cents"], int) and data["credit_limit_cents"] > 0
    assert isinstance(data["outstanding_balance_cents"], int)
    assert data["status"] in _ACCOUNT_VALUES


def assert_fleet_card(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["fleet_account_id"])
    assert isinstance(data["card_number"], str) and data["card_number"]
    assert data["daily_gge_limit"] > 0
    assert data["status"] in _CARD_VALUES
    assert isinstance(data["current_day_gge"], (int, float))
    assert isinstance(data["current_day_date"], str)


def assert_supply_contract(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["fleet_account_id"])
    assert is_valid_uuid(data["station_id"])
    assert data["committed_monthly_gge"] > 0
    assert data["contract_price_per_gge_cents"] > 0
    assert data["status"] in _CONTRACT_VALUES


def assert_monthly_settlement(data: dict):
    _assert_immutable_common_fields(data)
    assert is_valid_uuid(data["supply_contract_id"])
    assert isinstance(data["month"], str) and len(data["month"]) == 7
    assert isinstance(data["delivered_gge"], (int, float))
    assert isinstance(data["shortfall_gge"], (int, float))
    assert isinstance(data["penalty_cents"], int)
    assert is_iso8601_timestamp(data.get("settled_at", ""))


def assert_fueling_session(data: dict):
    _assert_common_fields(data)
    assert data["access_type"] in ("PUBLIC", "PRIVATE")
    assert is_valid_uuid(data["station_id"])
    assert is_valid_uuid(data["dispenser_id"])
    assert data["status"] in _SESSION_VALUES
    assert isinstance(data["client_ref"], str) and data["client_ref"]
    assert is_iso8601_timestamp(data.get("authorized_at", ""))


def assert_maintenance_window(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["station_id"])
    assert data["window_type"] in ("PREVENTIVE", "CORRECTIVE", "EMERGENCY")
    assert data["status"] in _WINDOW_VALUES


def assert_backup_arrangement(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["station_id"])
    assert isinstance(data["partner_station_code"], str)
    assert isinstance(data["committed_gge"], int) and data["committed_gge"] > 0
    assert isinstance(data["used_gge"], (int, float))
    assert data["status"] in _BACKUP_VALUES


def assert_safety_inspection(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["station_id"])
    assert data["inspection_type"] in _INSPECTION_TYPE_VALUES
    assert data["status"] in _INSPECTION_VALUES


def assert_tax_credit_claim(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["station_id"])
    assert data["status"] in _CLAIM_VALUES


def assert_account_balance_conserved(
    account: dict, authorized_holds: int = 0, completed_totals: int = 0, penalties: int = 0
):
    """PRD §3.3: outstanding_balance_cents == holds on AUTHORIZED sessions +
    totals of non-voided COMPLETED/SETTLED sessions + settlement penalties."""
    assert account["outstanding_balance_cents"] == (
        authorized_holds + completed_totals + penalties
    ), (
        f"Balance {account['outstanding_balance_cents']} != holds {authorized_holds} "
        f"+ totals {completed_totals} + penalties {penalties}"
    )
