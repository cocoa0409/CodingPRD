"""Entity assertions and domain invariant checkers for the Marine Dealer API."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

UNIT_STATUSES = ["INTAKE", "AVAILABLE", "RESERVED", "SOLD", "DELIVERED", "RETURNED"]
FLOOR_PLAN_STATUSES = ["ACTIVE", "CURTAILED", "PAID_OFF", "SUPERSEDED"]
DEAL_STATUSES = ["DRAFT", "SIGNED", "FUNDED", "DELIVERED", "CANCELLED"]
CONSIGNMENT_STATUSES = ["ACTIVE", "SOLD", "RETURNED"]
RO_STATUSES = ["OPEN", "IN_PROGRESS", "COMPLETED", "INVOICED"]
SERVICE_LINE_STATUSES = ["ACTIVE", "VOID", "CONSUMED"]
BERTH_STATUSES = ["OPEN", "CLOSED"]
RESERVATION_STATUSES = ["RESERVED", "ENDED", "CANCELLED"]


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_unit(data: dict):
    _assert_common(data)
    assert isinstance(data["hin"], str) and len(data["hin"]) > 0
    assert data["unit_type"] in ["BOAT", "MOTOR", "TRAILER"]
    assert data["acquisition_type"] in ["FLOOR_PLAN", "CASH", "CONSIGNMENT", "TRADE_IN"]
    assert data["status"] in UNIT_STATUSES
    assert isinstance(data["open_recall"], bool)
    assert isinstance(data["warranty_registered"], bool)
    assert isinstance(data["aging_days"], int)
    assert isinstance(data["floor_plan_balance_cents"], int)


def assert_floor_plan(data: dict):
    _assert_common(data)
    assert data["status"] in FLOOR_PLAN_STATUSES
    assert isinstance(data["principal_cents"], int)
    assert isinstance(data["outstanding_principal_cents"], int)
    assert isinstance(data["accrued_interest_cents"], int)
    assert isinstance(data["payoff_cents"], int)


def assert_deal(data: dict):
    _assert_common(data)
    assert data["status"] in DEAL_STATUSES
    assert data["financing_type"] in ["CASH", "RETAIL_FINANCE"]
    assert isinstance(data["trade_equity_cents"], int)
    assert isinstance(data["tax_cents"], int)
    assert isinstance(data["amount_due_cents"], int)


def assert_consignment(data: dict):
    _assert_common(data)
    assert data["status"] in CONSIGNMENT_STATUSES
    assert isinstance(data["payout_cents"], int)


def assert_repair_order(data: dict):
    _assert_common(data)
    assert data["status"] in RO_STATUSES
    assert data["ro_type"] in ["DIAGNOSTIC", "FLAT_RATE", "CUSTOM"]
    assert isinstance(data["estimate_total_cents"], int)


def assert_service_line(data: dict):
    _assert_common(data)
    assert data["status"] in SERVICE_LINE_STATUSES
    assert data["line_type"] in ["LABOR", "PART"]
    assert isinstance(data["extended_cents"], int)


def assert_part(data: dict):
    _assert_common(data)
    assert isinstance(data["on_hand_qty"], int)
    assert isinstance(data["reserved_qty"], int)
    assert isinstance(data["available_qty"], int)
    assert isinstance(data["is_low"], bool)
    # PRD §3.6: available_qty is on_hand_qty minus reserved_qty.
    assert data["available_qty"] == data["on_hand_qty"] - data["reserved_qty"]


def assert_berth(data: dict):
    _assert_common(data)
    assert data["status"] in BERTH_STATUSES
    assert data["berth_type"] in ["WET_SLIP", "DRY_RACK"]


def assert_service_bay(data: dict):
    _assert_common(data)
    assert data["bay_type"] in ["RIGGING", "MECHANICAL", "HAUL_OUT"]


def assert_slip_reservation(data: dict):
    _assert_common(data)
    assert data["status"] in RESERVATION_STATUSES
    assert isinstance(data["nights"], int)
    assert isinstance(data["total_cents"], int)
