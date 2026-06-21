"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "CARRIER_NAME": "Test Carrier",
    "LANE_CODE": "FROZEN",
    "FROZEN_MIN": -25,
    "FROZEN_MAX": -15,
    "ASSET_TAG": "RU-TEST",
    "SANITATION_AT": "2026-02-28T00:00:00Z",
    "SKU": "SKU-TEST",
}


def create_carrier_payload(**overrides) -> dict:
    """POST /carriers — only legal_name is required; the rest default server-side."""
    defaults = {"legal_name": DEFAULTS["CARRIER_NAME"]}
    defaults.update(overrides)
    return defaults


def create_reefer_unit_payload(carrier_id, **overrides) -> dict:
    """POST /reefer-units."""
    defaults = {
        "carrier_id": carrier_id,
        "asset_tag": DEFAULTS["ASSET_TAG"],
        "compartment_count": 1,
        "last_sanitation_at": DEFAULTS["SANITATION_AT"],
    }
    defaults.update(overrides)
    return defaults


def create_temp_lane_payload(**overrides) -> dict:
    """POST /temp-lanes."""
    defaults = {
        "code": DEFAULTS["LANE_CODE"],
        "setpoint_min_c": DEFAULTS["FROZEN_MIN"],
        "setpoint_max_c": DEFAULTS["FROZEN_MAX"],
        "regulated": True,
        "tolerance_degree_minutes": 30,
    }
    defaults.update(overrides)
    return defaults


def create_shipment_payload(carrier_id, cargo_class="FOOD", **overrides) -> dict:
    """POST /shipments."""
    defaults = {"carrier_id": carrier_id, "cargo_class": cargo_class}
    defaults.update(overrides)
    return defaults


def create_compartment_payload(temp_lane_id, ordinal=1, **overrides) -> dict:
    """POST /shipments/{id}/compartments."""
    defaults = {"temp_lane_id": temp_lane_id, "ordinal": ordinal}
    defaults.update(overrides)
    return defaults


def create_lot_payload(sku=None, pallet_count=1, declared_value_cents=100000, **overrides) -> dict:
    """POST /compartments/{cid}/lots."""
    defaults = {
        "sku": sku if sku is not None else DEFAULTS["SKU"],
        "pallet_count": pallet_count,
        "declared_value_cents": declared_value_cents,
    }
    defaults.update(overrides)
    return defaults


def create_reading_payload(kind, offset_min, temp_c=None, **overrides) -> dict:
    """POST /compartments/{cid}/readings. temp_c omitted entirely when None."""
    payload = {"kind": kind, "offset_min": offset_min}
    if temp_c is not None:
        payload["temp_c"] = temp_c
    payload.update(overrides)
    return payload


def create_stop_payload(kind, appointment_min, pallets_handled=0, compartments_touched=1, **overrides) -> dict:
    """POST /shipments/{id}/stops."""
    defaults = {
        "kind": kind,
        "appointment_min": appointment_min,
        "pallets_handled": pallets_handled,
        "compartments_touched": compartments_touched,
    }
    defaults.update(overrides)
    return defaults


def accept_payload(reefer_unit_id, expected_shipment_version, **overrides) -> dict:
    """POST /shipments/{id}/accept."""
    defaults = {
        "reefer_unit_id": reefer_unit_id,
        "expected_shipment_version": expected_shipment_version,
    }
    defaults.update(overrides)
    return defaults


def arrive_payload(arrived_min, **overrides) -> dict:
    defaults = {"arrived_min": arrived_min}
    defaults.update(overrides)
    return defaults


def close_payload(departed_min, pallets_handled=0, compartments_touched=1, **overrides) -> dict:
    defaults = {
        "departed_min": departed_min,
        "pallets_handled": pallets_handled,
        "compartments_touched": compartments_touched,
    }
    defaults.update(overrides)
    return defaults


def claim_payload(shipment_id, **overrides) -> dict:
    defaults = {"shipment_id": shipment_id}
    defaults.update(overrides)
    return defaults


def clock_payload(to_iso8601) -> dict:
    return {"to_iso8601": to_iso8601}
