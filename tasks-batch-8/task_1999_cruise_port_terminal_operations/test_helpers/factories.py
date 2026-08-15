"""Payload factories — one per entity, input fields only."""
from .constants import (
    DEFAULT_ETA,
    DEFAULT_ETD,
    DEFAULT_SERVICE_WINDOW_END,
    DEFAULT_SERVICE_WINDOW_START,
    DEFAULT_WINDOW_END,
    DEFAULT_WINDOW_START,
)

TERMINAL_DEFAULTS = {
    "name": "T1",
    "max_apron_slots": 4,
    "taxi_dispatch_capacity_per_window": 2,
}

BERTH_DEFAULTS = {
    "berth_code": "B1",
    "length_ft": 1200,
    "max_draft_ft": 40.0,
}

VESSEL_DEFAULTS = {
    "name": "MV A",
    "loa_ft": 950,
    "draft_ft": 30.0,
    "pax_capacity": 4000,
    "crew_count": 900,
}

PORT_CALL_DEFAULTS = {
    "voyage_ref": "V1",
    "scheduled_eta": DEFAULT_ETA,
    "scheduled_etd": DEFAULT_ETD,
    "booked_embark_pax": 10,
    "booked_debark_pax": 10,
}


def create_terminal_payload(**overrides) -> dict:
    defaults = dict(TERMINAL_DEFAULTS)
    defaults.update(overrides)
    return defaults


def create_berth_payload(terminal_id, **overrides) -> dict:
    defaults = dict(BERTH_DEFAULTS, terminal_id=terminal_id)
    defaults.update(overrides)
    return defaults


def create_vessel_payload(terminal_id, **overrides) -> dict:
    defaults = dict(VESSEL_DEFAULTS, terminal_id=terminal_id)
    defaults.update(overrides)
    return defaults


def create_port_call_payload(terminal_id, vessel_id, **overrides) -> dict:
    defaults = dict(PORT_CALL_DEFAULTS, terminal_id=terminal_id, vessel_id=vessel_id)
    defaults.update(overrides)
    return defaults


def create_berth_assignment_payload(berth_id, expected_port_call_version, **overrides) -> dict:
    defaults = {
        "berth_id": berth_id,
        "window_start": DEFAULT_WINDOW_START,
        "window_end": DEFAULT_WINDOW_END,
        "expected_port_call_version": expected_port_call_version,
    }
    defaults.update(overrides)
    return defaults


def delay_port_call_payload(**overrides) -> dict:
    defaults = {
        "revised_eta": "2026-08-11T08:00:00Z",
        "revised_etd": "2026-08-11T20:00:00Z",
        "reason": "weather",
    }
    defaults.update(overrides)
    return defaults


def create_manifest_entry_payload(passenger_ref, direction="EMBARK",
                                  cabin_class="STANDARD", **overrides) -> dict:
    defaults = {
        "passenger_ref": passenger_ref,
        "direction": direction,
        "cabin_class": cabin_class,
    }
    defaults.update(overrides)
    return defaults


def create_baggage_item_payload(manifest_entry_id, tag_code="TAG1", **overrides) -> dict:
    defaults = {"manifest_entry_id": manifest_entry_id, "tag_code": tag_code}
    defaults.update(overrides)
    return defaults


def create_screening_lane_payload(terminal_id, lane_code="L1", **overrides) -> dict:
    defaults = {"terminal_id": terminal_id, "lane_code": lane_code}
    defaults.update(overrides)
    return defaults


def open_lane_payload(officers_assigned=2, **overrides) -> dict:
    defaults = {"officers_assigned": officers_assigned}
    defaults.update(overrides)
    return defaults


def create_service_order_payload(kind="PROVISIONING", units=5, **overrides) -> dict:
    defaults = {
        "kind": kind,
        "units": units,
        "window_start": DEFAULT_SERVICE_WINDOW_START,
        "window_end": DEFAULT_SERVICE_WINDOW_END,
    }
    defaults.update(overrides)
    return defaults


def create_transport_slot_payload(terminal_id, port_call_id, vehicle_class="TAXI",
                                  party_size=2, **overrides) -> dict:
    defaults = {
        "terminal_id": terminal_id,
        "port_call_id": port_call_id,
        "vehicle_class": vehicle_class,
        "party_size": party_size,
    }
    defaults.update(overrides)
    return defaults


def create_weather_advisory_payload(terminal_id, severity="WARNING", **overrides) -> dict:
    defaults = {
        "terminal_id": terminal_id,
        "severity": severity,
        "window_start": "2026-08-01T00:00:00Z",
        "window_end": "2026-09-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def settle_invoice_payload(payment_cents, **overrides) -> dict:
    defaults = {"payment_cents": payment_cents}
    defaults.update(overrides)
    return defaults


def post_adjustment_payload(amount_cents, reason, expected_invoice_version,
                            **overrides) -> dict:
    defaults = {
        "amount_cents": amount_cents,
        "reason": reason,
        "expected_invoice_version": expected_invoice_version,
    }
    defaults.update(overrides)
    return defaults
