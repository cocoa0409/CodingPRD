"""Entity assertions and domain invariant checkers.

Each assert_{entity}() validates the structural contract for a returned entity
using the framework's generic validators. Field names mirror the PRD exactly.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

MODES = ["TL", "LTL", "PARCEL", "INTERMODAL"]


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_carrier(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["scac"], str) and len(data["scac"]) > 0
    assert data["mode"] in MODES
    assert data["status"] in ["ACTIVE", "SUSPENDED"]
    assert isinstance(data["delivered_count"], int) and data["delivered_count"] >= 0
    assert isinstance(data["on_time_count"], int) and data["on_time_count"] >= 0
    assert isinstance(data["claim_count"], int) and data["claim_count"] >= 0
    assert data["on_time_pct"] is None or isinstance(data["on_time_pct"], (int, float))
    assert data["scorecard_grade"] in ["A", "B", "C", "PROBATION"]


def assert_contract_rate(data: dict):
    _assert_common(data)
    assert isinstance(data["carrier_id"], str)
    assert data["mode"] in MODES
    assert isinstance(data["origin_zone"], str)
    assert isinstance(data["dest_zone"], str)
    assert isinstance(data["base_rate_per_mile_cents"], int)
    assert isinstance(data["min_charge_cents"], int)
    assert isinstance(data["fuel_surcharge_pct"], (int, float))
    assert isinstance(data["effective_start_minute"], int)
    assert isinstance(data["effective_end_minute"], int)
    assert data["status"] in ["ACTIVE", "RETIRED"]


def assert_order(data: dict):
    _assert_common(data)
    assert isinstance(data["customer_ref"], str)
    assert isinstance(data["origin_zone"], str)
    assert isinstance(data["dest_zone"], str)
    assert isinstance(data["weight_lbs"], int) and data["weight_lbs"] > 0
    assert isinstance(data["declared_value_cents"], int)
    assert data["status"] in ["OPEN", "PLANNED", "CLOSED", "CANCELLED"]


def assert_shipment(data: dict):
    _assert_common(data)
    assert isinstance(data["order_id"], str)
    assert data["mode"] in MODES
    assert isinstance(data["distance_miles"], int) and data["distance_miles"] > 0
    assert isinstance(data["weight_lbs"], int) and data["weight_lbs"] > 0
    assert data["load_id"] is None or isinstance(data["load_id"], str)
    assert data["assigned_carrier_id"] is None or isinstance(data["assigned_carrier_id"], str)
    assert data["contract_rate_id"] is None or isinstance(data["contract_rate_id"], str)
    assert data["quoted_cost_cents"] is None or isinstance(data["quoted_cost_cents"], int)
    assert data["audited_cost_cents"] is None or isinstance(data["audited_cost_cents"], int)
    assert isinstance(data["promised_eta_minute"], int)
    assert data["actual_delivery_minute"] is None or isinstance(data["actual_delivery_minute"], int)
    assert data["tender_status"] in ["UNTENDERED", "TENDERED", "BOOKED"]
    assert data["execution_status"] in ["PENDING", "IN_TRANSIT", "DELIVERED", "CANCELLED"]


def assert_tender(data: dict):
    _assert_common(data)
    assert isinstance(data["shipment_id"], str)
    assert data["carrier_id"] is None or isinstance(data["carrier_id"], str)
    assert data["contract_rate_id"] is None or isinstance(data["contract_rate_id"], str)
    assert isinstance(data["offered_rate_cents"], int)
    assert data["status"] in ["OFFERED", "ACCEPTED", "DECLINED", "EXPIRED"]


def assert_load(data: dict):
    _assert_common(data)
    assert isinstance(data["carrier_id"], str)
    assert isinstance(data["planned_capacity_lbs"], int) and data["planned_capacity_lbs"] > 0
    assert isinstance(data["consolidated_weight_lbs"], int) and data["consolidated_weight_lbs"] >= 0
    assert data["status"] in ["BUILDING", "DISPATCHED", "CLOSED"]


def assert_dock_appointment(data: dict):
    _assert_common(data)
    assert isinstance(data["load_id"], str)
    assert isinstance(data["dock_door"], str)
    assert isinstance(data["start_minute"], int) and data["start_minute"] >= 0
    assert isinstance(data["end_minute"], int) and data["end_minute"] > data["start_minute"]
    assert data["status"] in ["SCHEDULED", "CHECKED_IN", "RELEASED", "CANCELLED"]


def assert_freight_invoice(data: dict):
    _assert_common(data)
    assert isinstance(data["shipment_id"], str)
    assert isinstance(data["invoiced_linehaul_cents"], int)
    assert isinstance(data["invoiced_accessorial_codes"], list)
    assert data["variance_cents"] is None or isinstance(data["variance_cents"], int)
    assert data["status"] in ["RECEIVED", "AUDITED", "APPROVED", "DISPUTED"]


def assert_claim(data: dict):
    _assert_common(data)
    assert isinstance(data["shipment_id"], str)
    assert data["claim_type"] in ["OSD_SHORTAGE", "OSD_OVERAGE", "DAMAGE", "LOSS"]
    assert isinstance(data["claimed_amount_cents"], int) and data["claimed_amount_cents"] > 0
    assert data["approved_amount_cents"] is None or isinstance(data["approved_amount_cents"], int)
    assert data["status"] in ["OPEN", "APPROVED", "DENIED"]
