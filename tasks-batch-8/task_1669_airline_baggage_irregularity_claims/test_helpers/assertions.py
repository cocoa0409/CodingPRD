"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from datetime import datetime

from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _to_instant(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def assert_same_instant(actual: str, expected: str):
    """Both ISO-8601 strings must denote the same instant.

    PRD pins instant semantics for client-supplied datetimes (e.g. §3.5: a
    reschedule "replaces `pickup_at` with `new_pickup_at`") but does not pin the
    serialization form of such fields, so equality is checked on the instant.
    """
    assert _to_instant(actual) == _to_instant(expected), (
        f"{actual!r} and {expected!r} denote different instants"
    )


def _assert_common_fields(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"{entity}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"{entity}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"{entity}.version must be a positive integer"


def assert_station(data: dict):
    _assert_common_fields(data, "Station")
    assert isinstance(data["station_code"], str) and data["station_code"]
    assert isinstance(data["name"], str)
    assert isinstance(data["bags_handled_total"], int) and data["bags_handled_total"] >= 0
    assert isinstance(data["open_report_count"], int)
    assert isinstance(data["recovered_bag_count"], int)
    assert isinstance(data["mishandled_report_count"], int)


def assert_carrier(data: dict):
    _assert_common_fields(data, "Carrier")
    assert isinstance(data["carrier_code"], str) and data["carrier_code"]
    assert isinstance(data["is_interline_partner"], bool)


def assert_courier_service(data: dict):
    _assert_common_fields(data, "CourierService")
    assert isinstance(data["name"], str)
    assert isinstance(data["serves_station_ids"], list)
    assert isinstance(data["turnaround_buffer_minutes"], int)
    assert data["turnaround_buffer_minutes"] >= 0
    assert isinstance(data["active_dispatch_count"], int)


def assert_repair_vendor(data: dict):
    _assert_common_fields(data, "RepairVendor")
    assert isinstance(data["name"], str)
    assert isinstance(data["bench_capacity"], int) and data["bench_capacity"] >= 1
    assert isinstance(data["occupied_bench_slots"], int)
    assert isinstance(data["available_bench_slots"], int)


def assert_passenger(data: dict):
    _assert_common_fields(data, "Passenger")
    assert isinstance(data["full_name"], str)
    assert isinstance(data["email"], str)
    assert data["tier"] in ["STANDARD", "PREMIUM", "ELITE"]


def assert_bag_tag(data: dict):
    _assert_common_fields(data, "BagTag")
    assert isinstance(data["tag_number"], str)
    assert isinstance(data["passenger_id"], str)
    assert isinstance(data["routing_carrier_ids"], list)
    assert isinstance(data["is_international"], bool)
    assert isinstance(data["weight_kg"], int) and data["weight_kg"] >= 1
    assert isinstance(data["declared_value_cents"], int)
    assert data["status"] in [
        "CHECKED", "MISHANDLED", "IN_RECOVERY",
        "DELIVERED", "DELIVERED_DAMAGED", "CLAIMED_LOST",
    ]


def assert_report(data: dict):
    _assert_common_fields(data, "IrregularityReport")
    assert isinstance(data["report_reference"], str)
    assert data["type"] in ["DELAYED", "DAMAGED", "PILFERED"]
    assert data["status"] in [
        "OPEN", "TRACING", "FOUND_PENDING_DELIVERY", "DELIVERY_IN_PROGRESS",
        "DELIVERED", "DECLARED_LOST", "DAMAGE_REVIEW", "CLAIM_REVIEW",
        "SETTLEMENT_OFFERED", "SETTLEMENT_ACCEPTED", "CLOSED",
    ]
    assert isinstance(data["opened_on"], str)
    assert data["liability_regime"] in ["MONTREAL", "DOMESTIC"]
    assert isinstance(data["liable_carrier_id"], str)
    assert isinstance(data["effective_cap_cents"], int)
    assert isinstance(data["repair_payout_cents"], int)
    assert isinstance(data["amount_payable_cents"], int)
    assert isinstance(data["expenses_approved_unpaid_cents"], int)
    assert isinstance(data["expenses_paid_cents"], int)


def assert_tracing_event(data: dict):
    # Append-only record (PRD §2.4): id + created_at only; no updated_at/version.
    assert is_valid_uuid(data.get("id", "")), "TracingEvent.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "TracingEvent.created_at must be ISO 8601"
    assert "updated_at" not in data, "TracingEvent must not carry updated_at"
    assert "version" not in data, "TracingEvent must not carry version"
    assert data["event_type"] in [
        "FORWARDED", "LOCATED", "ON_HAND_AT_STATION",
        "IN_TRANSIT_TO", "DELIVERY_ARRANGED", "MISSCAN_CORRECTED",
    ]
    assert isinstance(data["report_id"], str)
    assert isinstance(data["carrier_id"], str)
    assert isinstance(data["station_id"], str)


def assert_dispatch(data: dict):
    _assert_common_fields(data, "DeliveryDispatch")
    assert isinstance(data["report_id"], str)
    assert isinstance(data["courier_service_id"], str)
    assert isinstance(data["pickup_at"], str)
    assert isinstance(data["travel_minutes"], int) and data["travel_minutes"] >= 1
    assert isinstance(data["attempt_count"], int) and data["attempt_count"] >= 1
    assert data["status"] in [
        "DISPATCHED", "FAILED_ATTEMPT", "DELIVERED", "FAILED_PERMANENT",
    ]


def assert_repair_order(data: dict):
    _assert_common_fields(data, "RepairOrder")
    assert isinstance(data["report_id"], str)
    assert isinstance(data["vendor_id"], str)
    assert isinstance(data["intake_date"], str)
    assert isinstance(data["promised_date"], str)
    assert isinstance(data["purchase_price_cents"], int)
    assert isinstance(data["purchase_date"], str)
    assert isinstance(data["repair_estimate_cents"], int)
    assert data["status"] in [
        "INTAKE", "REPAIR_IN_PROGRESS", "REPLACEMENT_PENDING",
        "REPAIR_SETTLED", "REPLACE_SETTLED", "CANCELLED",
    ]


def assert_expense_claim(data: dict):
    _assert_common_fields(data, "ExpenseClaim")
    assert isinstance(data["report_id"], str)
    assert isinstance(data["receipts"], list)
    assert isinstance(data["claimed_total_cents"], int)
    assert isinstance(data["eligible_receipt_count"], int)
    assert data["status"] in [
        "SUBMITTED", "APPROVED", "SETTLEMENT_EARMARKED", "PAID", "REJECTED",
    ]


def assert_settlement_payment(data: dict):
    _assert_common_fields(data, "SettlementPayment")
    assert isinstance(data["report_id"], str)
    assert isinstance(data["settlement_component_cents"], int)
    assert isinstance(data["expense_component_cents"], int)
    assert isinstance(data["amount_cents"], int)
    assert data["status"] in ["ISSUED", "PAID", "VOIDED"]


def assert_vendor_slot_invariants(vendor: dict):
    """Bench slots conserved: occupied + available == bench_capacity (PRD §3.1/§3.7)."""
    assert vendor["occupied_bench_slots"] + vendor["available_bench_slots"] == \
        vendor["bench_capacity"], (
            f"Bench slots not conserved: {vendor['occupied_bench_slots']} + "
            f"{vendor['available_bench_slots']} != {vendor['bench_capacity']}"
        )
