"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_record(data: dict):
    """Full first-class record: id, created_at, updated_at, version present."""
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version starts at 1"


def _assert_ledger_line(data: dict):
    """Append-only ledger line: only id + created_at, no version/updated_at."""
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def assert_customer(data: dict):
    _assert_common_record(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["email"], str)


def assert_unit(data: dict):
    _assert_common_record(data)
    assert isinstance(data["vin"], str) and len(data["vin"]) == 17
    assert data["category"] in ["MOTORCYCLE", "ATV", "UTV", "PWC", "SNOWMOBILE"]
    assert data["status"] in ["IN_TRANSIT", "IN_STOCK", "ON_HOLD", "SOLD", "DELIVERED"]
    assert data["acquisition_kind"] in ["NEW_FLOORED", "TRADE_IN", "CASH_OWNED"]
    assert isinstance(data["msrp_cents"], int)
    assert isinstance(data["dealer_cost_cents"], int)


def assert_floor_plan_loan(data: dict):
    _assert_common_record(data)
    assert data["status"] in ["OPEN", "CURTAILMENT_DUE", "PAID_OFF"]
    assert data["principal_outstanding_cents"] >= 0
    assert data["original_advance_cents"] >= 0


def assert_floor_plan_loan_principal_conserved(data: dict):
    """PRD invariant: principal_outstanding + cumulative_curtailment == original_advance."""
    assert (data["principal_outstanding_cents"] + data["cumulative_curtailment_cents"]
            == data["original_advance_cents"]), (
        "principal_outstanding + cumulative_curtailment must equal original_advance"
    )


def assert_deal(data: dict):
    _assert_common_record(data)
    assert data["status"] in [
        "DRAFT", "QUOTED", "FINANCE_SUBMITTED", "APPROVED",
        "DELIVERED", "DECLINED", "CANCELLED",
    ]
    assert isinstance(data["sale_price_cents"], int)


def assert_trade_in(data: dict):
    _assert_common_record(data)
    assert data["status"] in ["APPRAISED", "ACCEPTED", "TITLED", "REJECTED"]


def assert_repair_order(data: dict):
    _assert_common_record(data)
    assert data["work_status"] in ["OPEN", "IN_PROGRESS", "WORK_COMPLETE", "CANCELLED"]
    assert data["billing_status"] in ["UNBILLED", "INVOICED", "PAID", "VOID"]


def assert_part(data: dict):
    _assert_common_record(data)
    assert data["on_hand_qty"] >= 0
    assert data["reserved_qty"] >= 0
    assert data["consumed_qty"] >= 0
    assert data["available_qty"] >= 0


def assert_part_inventory_conserved(data: dict):
    """PRD invariant: on_hand == available + reserved + consumed."""
    assert (data["available_qty"] + data["reserved_qty"] + data["consumed_qty"]
            == data["on_hand_qty"]), (
        "available + reserved + consumed must equal on_hand"
    )


def assert_storage_agreement(data: dict):
    _assert_common_record(data)
    assert data["status"] in ["RESERVED", "CHECKED_IN", "CHECKED_OUT", "CANCELLED"]


def assert_test_ride_waiver(data: dict):
    _assert_common_record(data)
    assert data["status"] in ["SIGNED", "RIDE_LOGGED", "EXPIRED", "VOID"]


def assert_warranty_claim(data: dict):
    _assert_common_record(data)
    assert data["status"] in ["SUBMITTED", "APPROVED", "REJECTED", "PAID"]
    assert data["kind"] in ["WARRANTY", "RECALL"]


def assert_curtailment(data: dict):
    _assert_ledger_line(data)
    assert data["status"] == "POSTED"


def assert_service_line(data: dict):
    _assert_ledger_line(data)


def assert_part_line(data: dict):
    _assert_ledger_line(data)
    assert data["status"] in ["RESERVED", "CONSUMED", "RELEASED"]
