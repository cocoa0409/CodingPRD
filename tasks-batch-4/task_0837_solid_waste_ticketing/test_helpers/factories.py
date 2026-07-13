"""Payload factories — one per input surface, input fields only."""


def facility_payload(**overrides) -> dict:
    defaults = {"name": "Test Facility", "total_airspace_cubic_yards": 1000}
    defaults.update(overrides)
    return defaults


def cell_payload(**overrides) -> dict:
    defaults = {"name": "Test Cell", "capacity_cubic_yards": 1000}
    defaults.update(overrides)
    return defaults


def hauler_account_payload(**overrides) -> dict:
    defaults = {"name": "Test Hauler", "credit_limit_cents": 100_000_000}
    defaults.update(overrides)
    return defaults


def manifest_payload(hauler_account_id, **overrides) -> dict:
    defaults = {
        "hauler_account_id": hauler_account_id,
        "declared_material": "MSW",
        "declared_weight_tons": 7.0,
    }
    defaults.update(overrides)
    return defaults


def special_waste_approval_payload(**overrides) -> dict:
    defaults = {"waste_type": "ASBESTOS", "profile_ref": "PRF-1"}
    defaults.update(overrides)
    return defaults


def decide_payload(decision, **overrides) -> dict:
    defaults = {"decision": decision}
    defaults.update(overrides)
    return defaults


def ticket_payload(facility_id, hauler_account_id, **overrides) -> dict:
    defaults = {
        "facility_id": facility_id,
        "hauler_account_id": hauler_account_id,
        "material": "MSW",
        "gross_weight_tons": 10.0,
    }
    defaults.update(overrides)
    return defaults


def weigh_out_payload(tare_weight_tons) -> dict:
    return {"tare_weight_tons": tare_weight_tons}


def inspect_payload(result, reject_reason=None) -> dict:
    payload = {"result": result}
    if reject_reason is not None:
        payload["reject_reason"] = reject_reason
    return payload


def post_payload(expected_facility_version) -> dict:
    return {"expected_facility_version": expected_facility_version}


def gas_reading_payload(methane_ppm, reading_at) -> dict:
    return {"methane_ppm": methane_ppm, "reading_at": reading_at}


def disposal_window_payload(waste_type, window_start, window_end) -> dict:
    return {"waste_type": waste_type, "window_start": window_start, "window_end": window_end}


def scale_reservation_payload(lane_number, truck_ref, window_start, window_end) -> dict:
    return {
        "lane_number": lane_number,
        "truck_ref": truck_ref,
        "window_start": window_start,
        "window_end": window_end,
    }


def invoice_payload(hauler_account_id) -> dict:
    return {"hauler_account_id": hauler_account_id}


def payment_payload(amount_cents, method="ACH") -> dict:
    return {"amount_cents": amount_cents, "method": method}
