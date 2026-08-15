"""Entity assertions and domain invariant checkers."""
from datetime import datetime, timezone

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp into an aware datetime."""
    assert isinstance(value, str), f"expected an ISO 8601 string, got {value!r}"
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def assert_instant_equal(actual: str, expected_iso: str, label: str = ""):
    """Two ISO 8601 UTC renderings of the same instant compare equal, whatever
    the offset suffix or fractional-second rendering."""
    assert parse_instant(actual) == parse_instant(expected_iso), (
        f"{label + ': ' if label else ''}expected instant {expected_iso}, "
        f"got {actual}"
    )

from .types import (
    AdvisorySeverity,
    BaggageItemStatus,
    BerthAssignmentStatus,
    BerthStatus,
    CabinClass,
    CustomsCaseStatus,
    InvoiceKind,
    InvoiceStatus,
    ManifestDirection,
    ManifestEntryStatus,
    PortCallStatus,
    ScreeningLaneStatus,
    ServiceOrderKind,
    ServiceOrderStatus,
    TerminalPosture,
    TransportSlotStatus,
    VehicleClass,
    WeatherAdvisoryStatus,
)


def _assert_common(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"{entity}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"{entity}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"{entity}.version must be a positive integer"


def assert_terminal(data: dict):
    _assert_common(data, "Terminal")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["max_apron_slots"], int) and data["max_apron_slots"] >= 1
    assert isinstance(data["taxi_dispatch_capacity_per_window"], int)
    assert data["taxi_dispatch_capacity_per_window"] >= 1
    assert isinstance(data["occupied_berth_count"], int)
    assert isinstance(data["active_berth_count"], int)
    assert isinstance(data["free_berth_count"], int)
    assert data["posture"] in [p.value for p in TerminalPosture]
    assert isinstance(data["ops_run_index"], int)


def assert_terminal_counters(data: dict):
    """The berth counters are internally consistent on every terminal read."""
    assert data["free_berth_count"] == (
        data["active_berth_count"] - data["occupied_berth_count"]), (
        f"free ({data['free_berth_count']}) must equal active "
        f"({data['active_berth_count']}) minus occupied "
        f"({data['occupied_berth_count']})"
    )


def assert_berth(data: dict):
    _assert_common(data, "Berth")
    assert isinstance(data["terminal_id"], str)
    assert isinstance(data["berth_code"], str) and data["berth_code"]
    assert isinstance(data["length_ft"], int) and data["length_ft"] >= 100
    assert data["max_draft_ft"] > 0
    assert data["status"] in [s.value for s in BerthStatus]


def assert_vessel(data: dict):
    _assert_common(data, "Vessel")
    assert isinstance(data["terminal_id"], str)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["loa_ft"], int) and data["loa_ft"] >= 50
    assert data["draft_ft"] > 0
    assert isinstance(data["pax_capacity"], int) and data["pax_capacity"] >= 1
    assert isinstance(data["crew_count"], int) and data["crew_count"] >= 0


def assert_port_call(data: dict):
    _assert_common(data, "PortCall")
    assert isinstance(data["terminal_id"], str)
    assert isinstance(data["vessel_id"], str)
    assert isinstance(data["voyage_ref"], str) and data["voyage_ref"]
    assert is_iso8601_timestamp(data["scheduled_eta"])
    assert is_iso8601_timestamp(data["scheduled_etd"])
    assert isinstance(data["booked_embark_pax"], int) and data["booked_embark_pax"] >= 0
    assert isinstance(data["booked_debark_pax"], int) and data["booked_debark_pax"] >= 0
    assert data["status"] in [s.value for s in PortCallStatus]
    assert isinstance(data["passengers_aboard"], int) and data["passengers_aboard"] >= 0
    assert isinstance(data["bags_aboard"], int) and data["bags_aboard"] >= 0


def assert_berth_assignment(data: dict):
    _assert_common(data, "BerthAssignment")
    assert isinstance(data["port_call_id"], str)
    assert isinstance(data["berth_id"], str)
    assert is_iso8601_timestamp(data["window_start"])
    assert is_iso8601_timestamp(data["window_end"])
    assert data["status"] in [s.value for s in BerthAssignmentStatus]


def assert_manifest_entry(data: dict):
    _assert_common(data, "ManifestEntry")
    assert isinstance(data["port_call_id"], str)
    assert isinstance(data["passenger_ref"], str) and data["passenger_ref"]
    assert data["direction"] in [d.value for d in ManifestDirection]
    assert data["cabin_class"] in [c.value for c in CabinClass]
    assert data["status"] in [s.value for s in ManifestEntryStatus]
    assert isinstance(data["is_taxable"], bool)


def assert_baggage_item(data: dict):
    _assert_common(data, "BaggageItem")
    assert isinstance(data["manifest_entry_id"], str)
    assert isinstance(data["port_call_id"], str)
    assert isinstance(data["tag_code"], str) and data["tag_code"]
    assert data["status"] in [s.value for s in BaggageItemStatus]


def assert_screening_lane(data: dict):
    _assert_common(data, "ScreeningLane")
    assert isinstance(data["terminal_id"], str)
    assert isinstance(data["lane_code"], str) and data["lane_code"]
    assert isinstance(data["officers_assigned"], int) and data["officers_assigned"] >= 0
    assert data["status"] in [s.value for s in ScreeningLaneStatus]


def assert_customs_case(data: dict):
    _assert_common(data, "CustomsCase")
    assert isinstance(data["port_call_id"], str)
    assert data["status"] in [s.value for s in CustomsCaseStatus]


def assert_service_order(data: dict):
    _assert_common(data, "ServiceOrder")
    assert isinstance(data["port_call_id"], str)
    assert data["kind"] in [k.value for k in ServiceOrderKind]
    assert isinstance(data["units"], int) and data["units"] >= 1
    assert is_iso8601_timestamp(data["window_start"])
    assert is_iso8601_timestamp(data["window_end"])
    assert isinstance(data["requested_by_user_id"], str)
    assert isinstance(data["surcharge_applied"], bool)
    assert data["status"] in [s.value for s in ServiceOrderStatus]


def assert_invoice(data: dict):
    _assert_common(data, "Invoice")
    assert isinstance(data["port_call_id"], str)
    assert data["kind"] in [k.value for k in InvoiceKind]
    assert data["status"] in [s.value for s in InvoiceStatus]
    for field in ("dockage_fee_cents", "head_tax_cents", "service_fee_cents",
                  "adjustments_total_cents", "gross_cents", "total_cents"):
        assert isinstance(data[field], int), f"Invoice.{field} must be integer cents"
    assert data["gross_cents"] == (
        data["dockage_fee_cents"] + data["head_tax_cents"] + data["service_fee_cents"]
    ), "gross_cents must equal dockage + head tax + service fees"
    assert data["total_cents"] == data["gross_cents"] - data["adjustments_total_cents"], \
        "total_cents must equal gross_cents minus adjustments_total_cents"


def assert_transport_slot(data: dict):
    _assert_common(data, "TransportSlot")
    assert isinstance(data["terminal_id"], str)
    assert isinstance(data["port_call_id"], str)
    assert data["vehicle_class"] in [v.value for v in VehicleClass]
    assert isinstance(data["party_size"], int) and data["party_size"] >= 1
    assert isinstance(data["queue_seq"], int)
    assert isinstance(data["requeue_count"], int) and data["requeue_count"] >= 0
    assert data["status"] in [s.value for s in TransportSlotStatus]


def assert_weather_advisory(data: dict):
    _assert_common(data, "WeatherAdvisory")
    assert isinstance(data["terminal_id"], str)
    assert data["severity"] in [s.value for s in AdvisorySeverity]
    assert is_iso8601_timestamp(data["window_start"])
    assert is_iso8601_timestamp(data["window_end"])
    assert data["status"] in [s.value for s in WeatherAdvisoryStatus]
