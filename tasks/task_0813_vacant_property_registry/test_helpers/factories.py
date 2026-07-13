"""Payload factories — one per entity, input fields only."""
import itertools

_counter = itertools.count(1)


def _unique(prefix):
    return f"{prefix}-{next(_counter)}"


def create_registrant_payload(**overrides):
    """Registrant creation body. license_number is included only when supplied
    (an OWNER omits it; a LENDER must supply it)."""
    payload = {
        "legal_name": "Test Party",
        "party_type": "OWNER",
        "email": "party@example.com",
        "contact_phone": "555-0100",
        "mailing_address": "1 Test St",
    }
    license_number = overrides.pop("license_number", None)
    if license_number is not None:
        payload["license_number"] = license_number
    payload.update(overrides)
    return payload


def create_property_payload(**overrides):
    """Property creation body. registrant_id and registration_type are required
    from the caller; parcel_id auto-generated unique unless a non-None value is
    supplied (a None override means "auto-generate")."""
    payload = {
        "street_address": "1 Oak Ave",
        "occupancy_status": "VACANT",
        "registration_type": "OWNER",
    }
    payload["parcel_id"] = overrides.get("parcel_id") or _unique("PARCEL")
    for key in ("registrant_id", "street_address", "occupancy_status", "registration_type"):
        if overrides.get(key) is not None:
            payload[key] = overrides[key]
    return payload


def create_maintenance_standard_payload(**overrides):
    payload = {
        "code": _unique("STD"),
        "category": "SECURING",
        "description": "Test maintenance standard",
        "severity_weight": 5,
        "cure_period_days": 5,
        "base_fine_cents": 20000,
    }
    payload.update(overrides)
    return payload


def create_inspection_payload(**overrides):
    payload = {
        "property_id": None,
        "inspector_badge": _unique("BADGE"),
        "scheduled_start": "2026-03-02T09:00:00Z",
        "scheduled_end": "2026-03-02T11:00:00Z",
    }
    payload.update(overrides)
    return payload
