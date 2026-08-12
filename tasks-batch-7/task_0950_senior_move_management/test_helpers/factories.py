"""Payload factories - one per creating endpoint, input fields only."""

CLOCK_START = "2026-05-02T09:00:00.000Z"
MOVE_START = "2026-06-15T14:00:00.000Z"
FREEZE_INSTANT = "2026-06-12T14:00:00.000Z"

DEFAULTS = {
    "CLIENT_NAME": "Ada Whitfield",
    "CLIENT_PHONE": "+1-555-0142",
    "CLIENT_EMAIL": "ada@example.com",
    "MILEAGE_MILES": 22,
    "STAIRS_FLIGHTS": 2,
    "LONG_CARRY_FEET": 100,
    "TRUCK_CAPACITY_CFT": 1000,
    "TRUCK_COUNT": 1,
    "ROOM_NOMINAL_LINEAR_INCHES": 240,
    "ROOM_NOMINAL_VOLUME_CFT": 400,
}


def create_client_payload(**overrides) -> dict:
    payload = {
        "full_name": DEFAULTS["CLIENT_NAME"],
        "phone": DEFAULTS["CLIENT_PHONE"],
        "email": DEFAULTS["CLIENT_EMAIL"],
    }
    payload.update(overrides)
    return payload


def create_engagement_payload(client_id, **overrides) -> dict:
    payload = {
        "client_id": client_id,
        "billing_mode": "HOURLY",
        "home_tier": "STUDIO",
        "scheduled_move_start_utc": MOVE_START,
        "mileage_miles": DEFAULTS["MILEAGE_MILES"],
        "origin_stairs_flights": DEFAULTS["STAIRS_FLIGHTS"],
        "origin_long_carry_feet": DEFAULTS["LONG_CARRY_FEET"],
    }
    payload.update(overrides)
    if payload.get("package_tier") is None:
        payload.pop("package_tier", None)
    return payload


def create_portal_party_payload(engagement_id, party_type="CLIENT", **overrides) -> dict:
    payload = {
        "engagement_id": engagement_id,
        "party_type": party_type,
        "display_name": DEFAULTS["CLIENT_NAME"],
        "email": DEFAULTS["CLIENT_EMAIL"],
    }
    payload.update(overrides)
    return payload


def create_authority_record_payload(engagement_id, holder_party_id, **overrides) -> dict:
    payload = {
        "engagement_id": engagement_id,
        "holder_party_id": holder_party_id,
        "authority_scope": "FULL",
        "effective_from_utc": "2026-05-01T00:00:00.000Z",
        "effective_to_utc": "2026-12-31T00:00:00.000Z",
    }
    payload.update(overrides)
    return payload


def create_destination_residence_payload(engagement_id, **overrides) -> dict:
    payload = {
        "engagement_id": engagement_id,
        "name": "Maple Grove 12B",
        "unit_type": "APARTMENT",
        "address_line": "12B Maple Grove Way",
    }
    payload.update(overrides)
    return payload


def create_destination_room_payload(destination_residence_id, **overrides) -> dict:
    payload = {
        "destination_residence_id": destination_residence_id,
        "room_type": "LIVING",
        "nominal_linear_inches": DEFAULTS["ROOM_NOMINAL_LINEAR_INCHES"],
        "nominal_volume_cft": DEFAULTS["ROOM_NOMINAL_VOLUME_CFT"],
    }
    payload.update(overrides)
    return payload


def create_inventory_item_payload(engagement_id, **overrides) -> dict:
    payload = {
        "engagement_id": engagement_id,
        "label": "Walnut sideboard",
        "category": "FURNITURE",
        "footprint_linear_inches": 96,
        "volume_cft": 40,
    }
    payload.update(overrides)
    return payload


def create_family_hold_payload(inventory_item_id, raised_by_party_id, **overrides) -> dict:
    payload = {
        "inventory_item_id": inventory_item_id,
        "raised_by_party_id": raised_by_party_id,
        "reason": "My mother promised this piece to me",
    }
    payload.update(overrides)
    return payload


def create_sort_plan_payload(engagement_id, expected_engagement_version, **overrides) -> dict:
    payload = {
        "engagement_id": engagement_id,
        "expected_engagement_version": expected_engagement_version,
    }
    payload.update(overrides)
    return payload


def create_move_day_plan_payload(engagement_id, **overrides) -> dict:
    payload = {
        "engagement_id": engagement_id,
        "scheduled_start_utc": MOVE_START,
        "truck_capacity_cft": DEFAULTS["TRUCK_CAPACITY_CFT"],
        "truck_count": DEFAULTS["TRUCK_COUNT"],
    }
    payload.update(overrides)
    return payload


def create_crew_member_payload(full_name, crew_role, **overrides) -> dict:
    payload = {"full_name": full_name, "crew_role": crew_role}
    payload.update(overrides)
    return payload


def create_crew_assignment_payload(
    move_day_plan_id, crew_member_id, expected_move_day_plan_version, **overrides
) -> dict:
    payload = {
        "move_day_plan_id": move_day_plan_id,
        "crew_member_id": crew_member_id,
        "expected_move_day_plan_version": expected_move_day_plan_version,
    }
    payload.update(overrides)
    return payload


def create_time_entry_payload(
    crew_assignment_id, entry_kind, started_at_utc, ended_at_utc, **overrides
) -> dict:
    payload = {
        "crew_assignment_id": crew_assignment_id,
        "entry_kind": entry_kind,
        "started_at_utc": started_at_utc,
        "ended_at_utc": ended_at_utc,
    }
    payload.update(overrides)
    return payload


def create_vendor_payload(name, vendor_type, coi_expires_on, **overrides) -> dict:
    payload = {
        "name": name,
        "vendor_type": vendor_type,
        "coi_expires_on": coi_expires_on,
    }
    payload.update(overrides)
    return payload


def create_vendor_assignment_payload(
    engagement_id, vendor_id, service_kind, service_date, quoted_cents, **overrides
) -> dict:
    payload = {
        "engagement_id": engagement_id,
        "vendor_id": vendor_id,
        "service_kind": service_kind,
        "service_date": service_date,
        "quoted_cents": quoted_cents,
    }
    payload.update(overrides)
    return payload


def create_consignment_lot_payload(
    engagement_id, vendor_id, list_price_cents, listed_on, item_ids, **overrides
) -> dict:
    payload = {
        "engagement_id": engagement_id,
        "vendor_id": vendor_id,
        "list_price_cents": list_price_cents,
        "listed_on": listed_on,
        "item_ids": list(item_ids),
    }
    payload.update(overrides)
    return payload


def create_invoice_line_payload(
    invoice_id, line_type, amount_cents, memo, expected_invoice_version, **overrides
) -> dict:
    payload = {
        "invoice_id": invoice_id,
        "line_type": line_type,
        "amount_cents": amount_cents,
        "memo": memo,
        "expected_invoice_version": expected_invoice_version,
    }
    payload.update(overrides)
    return payload


def create_unpack_session_payload(engagement_id, scheduled_start_utc, priority, **overrides) -> dict:
    payload = {
        "engagement_id": engagement_id,
        "scheduled_start_utc": scheduled_start_utc,
        "priority": priority,
    }
    payload.update(overrides)
    return payload


def create_punch_list_item_payload(engagement_id, description, severity, **overrides) -> dict:
    payload = {
        "engagement_id": engagement_id,
        "description": description,
        "severity": severity,
    }
    payload.update(overrides)
    return payload


__all__ = [
    "CLOCK_START",
    "MOVE_START",
    "FREEZE_INSTANT",
    "DEFAULTS",
    "create_client_payload",
    "create_engagement_payload",
    "create_portal_party_payload",
    "create_authority_record_payload",
    "create_destination_residence_payload",
    "create_destination_room_payload",
    "create_inventory_item_payload",
    "create_family_hold_payload",
    "create_sort_plan_payload",
    "create_move_day_plan_payload",
    "create_crew_member_payload",
    "create_crew_assignment_payload",
    "create_time_entry_payload",
    "create_vendor_payload",
    "create_vendor_assignment_payload",
    "create_consignment_lot_payload",
    "create_invoice_line_payload",
    "create_unpack_session_payload",
    "create_punch_list_item_payload",
]
