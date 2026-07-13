"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "BEACH_NAME": "Ocean Park",
    "TOWN_CODE": "OP",
    "SEASON_START": "2026-05-23",
    "SEASON_END": "2026-09-07",
    "ZONE_NAME": "North Cove",
    "TOWER_LABEL": "T4",
    "LIFEGUARD_NAME": "Ana",
    "EMPLOYEE_REF": "E1",
    "LOT_NAME": "Lot A",
    "TECHNICIAN": "T",
}


def create_beach_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["BEACH_NAME"],
        "town_code": DEFAULTS["TOWN_CODE"],
        "season_start_date": DEFAULTS["SEASON_START"],
        "season_end_date": DEFAULTS["SEASON_END"],
    }
    payload.update(overrides)
    return payload


def create_zone_payload(beach_id, **overrides) -> dict:
    payload = {"beach_id": beach_id, "name": DEFAULTS["ZONE_NAME"]}
    payload.update(overrides)
    return payload


def create_tower_payload(zone_id, **overrides) -> dict:
    payload = {"zone_id": zone_id, "label": DEFAULTS["TOWER_LABEL"]}
    payload.update(overrides)
    return payload


def create_lifeguard_payload(beach_id, **overrides) -> dict:
    payload = {
        "beach_id": beach_id,
        "name": DEFAULTS["LIFEGUARD_NAME"],
        "certification_level": "SENIOR",
        "employee_ref": DEFAULTS["EMPLOYEE_REF"],
    }
    payload.update(overrides)
    return payload


def create_shift_payload(lifeguard_id, tower_id, scheduled_start, scheduled_end, **overrides) -> dict:
    payload = {
        "lifeguard_id": lifeguard_id,
        "tower_id": tower_id,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
    }
    payload.update(overrides)
    return payload


def create_incident_payload(zone_id, occurred_at, **overrides) -> dict:
    payload = {
        "zone_id": zone_id,
        "type": "MEDICAL",
        "occurred_at": occurred_at,
        "description": "incident narrative",
    }
    payload.update(overrides)
    return payload


def create_sample_payload(zone_id, enterococci_mpn, sampled_at, **overrides) -> dict:
    payload = {
        "zone_id": zone_id,
        "enterococci_mpn": enterococci_mpn,
        "sampled_at": sampled_at,
        "lab_ref": "L1",
        "technician": DEFAULTS["TECHNICIAN"],
    }
    payload.update(overrides)
    return payload


def create_advisory_payload(basis, expected_zone_version, **overrides) -> dict:
    payload = {"basis": basis, "expected_zone_version": expected_zone_version}
    payload.update(overrides)
    return payload


def create_parking_lot_payload(beach_id, total_spaces, daily_rate_cents, **overrides) -> dict:
    payload = {
        "beach_id": beach_id,
        "name": DEFAULTS["LOT_NAME"],
        "total_spaces": total_spaces,
        "daily_rate_cents": daily_rate_cents,
    }
    payload.update(overrides)
    return payload


def create_parking_pass_payload(lot_id, plate, vehicle_type, pass_type, **overrides) -> dict:
    payload = {
        "lot_id": lot_id,
        "plate": plate,
        "vehicle_type": vehicle_type,
        "pass_type": pass_type,
    }
    payload.update(overrides)
    return payload
