"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    AtmCashPosture,
    AtmForecastStatus,
    AtmForecastVariant,
    AtmServiceStatus,
    CarrierStatus,
    CashShipmentStatus,
    CounterfeitCaseStatus,
    FedOrderDirection,
    FedOrderStatus,
    FitnessBatchStatus,
    LedgerBucket,
    LedgerEntryType,
    ReconciliationStatus,
    SiteType,
    VaultPosture,
)

_VALID_DENOMINATIONS = {100, 200, 500, 1000, 2000, 5000, 10000}


def _assert_audit_fields(data: dict):
    """Full-audit entities carry id, created_at, updated_at, version (PRD §2.5)."""
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        "version must be an integer >= 1"
    )


def _assert_append_only_fields(data: dict):
    """DenominationLine / CashLedgerEntry carry ONLY id and created_at (PRD §2.5)."""
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "updated_at must be absent on append-only types"
    assert "version" not in data, "version must be absent on append-only types"


def assert_vault_site(data: dict):
    _assert_audit_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["site_type"] in {e.value for e in SiteType}
    assert isinstance(data["vault_limit_cents"], int)
    assert isinstance(data["insurance_coverage_cents"], int)
    assert isinstance(data["dock_capacity"], int) and data["dock_capacity"] >= 1
    for field in (
        "on_hand_fit_cents",
        "on_hand_unfit_cents",
        "reserved_out_cents",
        "in_transit_inbound_cents",
        "pending_inbound_order_cents",
        "on_hand_total_cents",
        "insurance_headroom_cents",
    ):
        assert isinstance(data[field], int), f"{field} must be integer cents"
    assert data["posture"] in {e.value for e in VaultPosture}
    assert_site_derived_invariants(data)


def assert_staff_member(data: dict):
    _assert_audit_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert is_valid_uuid(data["home_site_id"])
    assert isinstance(data["active"], bool)


def assert_carrier(data: dict):
    _assert_audit_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["liability_cap_per_truck_cents"], int)
    assert data["status"] in {e.value for e in CarrierStatus}


def assert_atm_machine(data: dict):
    _assert_audit_fields(data)
    assert is_valid_uuid(data["site_id"])
    assert isinstance(data["terminal_code"], str) and data["terminal_code"]
    assert isinstance(data["cash_capacity_cents"], int)
    assert isinstance(data["current_balance_cents"], int)
    assert data["cash_posture"] in {e.value for e in AtmCashPosture}
    assert data["service_status"] in {e.value for e in AtmServiceStatus}


def assert_seasonal_window(data: dict):
    _assert_audit_fields(data)
    assert is_valid_uuid(data["site_id"])
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["start_date"], str)
    assert isinstance(data["end_date"], str)
    assert data["end_date"] >= data["start_date"], "end_date must be >= start_date"
    assert isinstance(data["multiplier_bps"], int)


def assert_fed_order(data: dict):
    _assert_audit_fields(data)
    assert is_valid_uuid(data["site_id"])
    assert data["direction"] in {e.value for e in FedOrderDirection}
    assert isinstance(data["business_date"], str)
    for field in ("face_total_cents", "fee_total_cents", "grand_total_cents"):
        assert isinstance(data[field], int), f"{field} must be integer cents"
    assert data["face_total_cents"] + data["fee_total_cents"] == data["grand_total_cents"], (
        "grand_total_cents must equal face_total_cents + fee_total_cents"
    )
    assert isinstance(data["advice_count"], int) and data["advice_count"] >= 0
    assert data["status"] in {e.value for e in FedOrderStatus}


def assert_denomination_line(data: dict):
    _assert_append_only_fields(data)
    assert is_valid_uuid(data["fed_order_id"])
    assert data["denomination_cents"] in _VALID_DENOMINATIONS
    assert isinstance(data["strap_count"], int) and data["strap_count"] >= 1
    assert isinstance(data["line_cents"], int)
    assert data["line_cents"] == data["denomination_cents"] * 100 * data["strap_count"], (
        "line_cents must equal denomination_cents * 100 notes per strap * strap_count"
    )
    assert isinstance(data["fee_cents"], int)


def assert_cash_shipment(data: dict):
    _assert_audit_fields(data)
    assert is_valid_uuid(data["carrier_id"])
    assert isinstance(data["declared_value_cents"], int)
    assert is_iso8601_timestamp(data["scheduled_departure_at"])
    assert is_iso8601_timestamp(data["scheduled_arrival_at"])
    assert data["scheduled_arrival_at"] > data["scheduled_departure_at"], (
        "scheduled_arrival_at must be strictly later than departure"
    )
    assert data["status"] in {e.value for e in CashShipmentStatus}


def assert_fitness_batch(data: dict):
    _assert_audit_fields(data)
    assert is_valid_uuid(data["site_id"])
    assert isinstance(data["input_unfit_cents"], int)
    for field in ("fit_recovered_cents", "unfit_remaining_cents", "counterfeit_face_cents"):
        assert isinstance(data[field], int)
    assert data["status"] in {e.value for e in FitnessBatchStatus}
    assert_fitness_conservation(data)


def assert_counterfeit_case(data: dict):
    _assert_audit_fields(data)
    assert is_valid_uuid(data["site_id"])
    assert data["denomination_cents"] in _VALID_DENOMINATIONS
    assert isinstance(data["note_count"], int) and data["note_count"] >= 1
    assert isinstance(data["face_value_cents"], int)
    assert data["face_value_cents"] == data["denomination_cents"] * data["note_count"]
    assert data["status"] in {e.value for e in CounterfeitCaseStatus}


def assert_cash_ledger_entry(data: dict):
    _assert_append_only_fields(data)
    assert is_valid_uuid(data["site_id"])
    assert isinstance(data["business_date"], str)
    assert data["entry_type"] in {e.value for e in LedgerEntryType}
    assert isinstance(data["signed_amount_cents"], int)
    assert data["bucket"] in {e.value for e in LedgerBucket}


def assert_reconciliation(data: dict):
    _assert_audit_fields(data)
    assert is_valid_uuid(data["site_id"])
    assert isinstance(data["business_date"], str)
    assert isinstance(data["opening_balance_cents"], int)
    assert isinstance(data["provisional_expected_cents"], int)
    assert isinstance(data["final_expected_cents"], int)
    assert data["status"] in {e.value for e in ReconciliationStatus}


def assert_atm_forecast(data: dict):
    _assert_audit_fields(data)
    assert is_valid_uuid(data["atm_id"])
    assert isinstance(data["forecast_date"], str)
    for field in ("w1_cents", "w2_cents", "w3_cents"):
        assert isinstance(data[field], int)
    assert data["variant_applied"] in {e.value for e in AtmForecastVariant}
    for field in (
        "projected_base_cents",
        "projected_final_cents",
        "recommended_load_cents",
        "residual_target_cents",
    ):
        assert isinstance(data[field], int), f"{field} must be integer cents"
    assert data["status"] in {e.value for e in AtmForecastStatus}


# ---------------------------------------------------------------------------
# Domain invariant checkers
# ---------------------------------------------------------------------------

def assert_site_derived_invariants(data: dict):
    """PRD §2.10: on_hand_total_cents is always the sum of fit and unfit on hand."""
    assert data["on_hand_total_cents"] == (
        data["on_hand_fit_cents"] + data["on_hand_unfit_cents"]
    ), "on_hand_total_cents must equal on_hand_fit_cents + on_hand_unfit_cents"


def assert_fitness_conservation(data: dict):
    """PRD §3.5 conservation invariant: after every sort and after settlement the
    input always equals fit recovered plus unfit remaining plus counterfeit face
    plus shrink."""
    if data.get("status") in (None, FitnessBatchStatus.OPEN.value):
        return
    total = (
        data["fit_recovered_cents"]
        + data["unfit_remaining_cents"]
        + data["counterfeit_face_cents"]
        + data["shrink_cents"]
    )
    assert data["input_unfit_cents"] == total, (
        f"conservation violated: input {data['input_unfit_cents']} != buckets+shrink {total}"
    )
