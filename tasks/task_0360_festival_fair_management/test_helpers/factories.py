"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "FESTIVAL_NAME": "Test Festival",
    "START_DATE": "2026-08-01",
    "END_DATE": "2026-08-03",
    "STAGE_NAME": "Main Stage",
    "PARKING_NAME": "Lot A",
    "CAMPING_NAME": "Field A",
    "PURCHASER_EMAIL": "patron@example.com",
    "VENDOR_NAME": "Test Vendor Co",
    "VENDOR_EMAIL": "vendor@example.com",
    "ARTIST_NAME": "Test Artist",
}


def create_festival_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["FESTIVAL_NAME"],
        "start_date": DEFAULTS["START_DATE"],
        "end_date": DEFAULTS["END_DATE"],
    }
    payload.update(overrides)
    return payload


def create_zone_payload(code: str = "A", slot_capacity: int = 1, **overrides) -> dict:
    payload = {"code": code, "slot_capacity": slot_capacity}
    payload.update(overrides)
    return payload


def create_stage_payload(name: str = None, changeover_minutes: int = 30, **overrides) -> dict:
    payload = {"name": name or DEFAULTS["STAGE_NAME"], "changeover_minutes": changeover_minutes}
    payload.update(overrides)
    return payload


def create_parking_lot_payload(name: str = None, capacity: int = 10,
                               price_per_pass: float = 25.00, **overrides) -> dict:
    payload = {
        "name": name or DEFAULTS["PARKING_NAME"],
        "capacity": capacity,
        "price_per_pass": price_per_pass,
    }
    payload.update(overrides)
    return payload


def create_camping_area_payload(name: str = None, capacity: int = 10,
                                price_per_night: float = 30.00, **overrides) -> dict:
    payload = {
        "name": name or DEFAULTS["CAMPING_NAME"],
        "capacity": capacity,
        "price_per_night": price_per_night,
    }
    payload.update(overrides)
    return payload


def create_ticket_payload(ticket_type: str = "GA", day_count: int = 2,
                          purchaser_email: str = None, **overrides) -> dict:
    payload = {
        "ticket_type": ticket_type,
        "day_count": day_count,
        "purchaser_email": purchaser_email or DEFAULTS["PURCHASER_EMAIL"],
    }
    payload.update(overrides)
    return payload


def create_wristband_payload(rfid_uid: str, **overrides) -> dict:
    payload = {"rfid_uid": rfid_uid}
    payload.update(overrides)
    return payload


def create_vendor_payload(company_name: str = None, contact_email: str = None, **overrides) -> dict:
    payload = {
        "company_name": company_name or DEFAULTS["VENDOR_NAME"],
        "contact_email": contact_email or DEFAULTS["VENDOR_EMAIL"],
    }
    payload.update(overrides)
    return payload


def create_vendor_application_payload(vendor_id: str, booth_zone_id: str,
                                      booth_tier: str = "STANDARD", day_count: int = 2,
                                      power_addon: bool = False, **overrides) -> dict:
    payload = {
        "vendor_id": vendor_id,
        "booth_zone_id": booth_zone_id,
        "booth_tier": booth_tier,
        "day_count": day_count,
        "power_addon": power_addon,
    }
    payload.update(overrides)
    return payload


def create_performance_payload(artist_name: str, starts_at: str, ends_at: str, **overrides) -> dict:
    payload = {"artist_name": artist_name, "starts_at": starts_at, "ends_at": ends_at}
    payload.update(overrides)
    return payload


def create_parking_addon_payload(parking_lot_id: str, expected_lot_version, **overrides) -> dict:
    payload = {
        "kind": "PARKING",
        "parking_lot_id": parking_lot_id,
        "expected_lot_version": expected_lot_version,
    }
    payload.update(overrides)
    return payload


def create_camping_addon_payload(camping_area_id: str, nights: int = 1, **overrides) -> dict:
    payload = {"kind": "CAMPING", "camping_area_id": camping_area_id, "nights": nights}
    payload.update(overrides)
    return payload


def create_incident_payload(incident_type: str = "MEDICAL", severity: str = "LOW", **overrides) -> dict:
    payload = {"incident_type": incident_type, "severity": severity}
    payload.update(overrides)
    return payload


def topup_payload(amount: float, **overrides) -> dict:
    payload = {"amount": amount}
    payload.update(overrides)
    return payload


def spend_payload(amount: float, booth_zone_id: str, **overrides) -> dict:
    payload = {"amount": amount, "booth_zone_id": booth_zone_id}
    payload.update(overrides)
    return payload


def gate_scan_payload(wristband_id: str, direction: str, **overrides) -> dict:
    payload = {"wristband_id": wristband_id, "direction": direction}
    payload.update(overrides)
    return payload
