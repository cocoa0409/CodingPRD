"""Payload factories — one per writable entity, input fields only (PRD §3)."""

_TRACKING_SEQ = {"n": 0}


def unique_tracking(prefix: str = "T") -> str:
    """Return a per-process-unique tracking number, so within-property uniqueness holds."""
    _TRACKING_SEQ["n"] += 1
    return f"{prefix}-{_TRACKING_SEQ['n']}"


def create_property_payload(**overrides) -> dict:
    """POST /parcelroom/properties. Only `name` is required; policy fields default server-side."""
    defaults = {"name": "Test Court"}
    defaults.update(overrides)
    return defaults


def create_locker_bank_payload(property_id: str, **overrides) -> dict:
    defaults = {
        "property_id": property_id,
        "label": "A",
        "storage_class": "AMBIENT",
    }
    defaults.update(overrides)
    return defaults


def create_locker_payload(locker_bank_id: str, **overrides) -> dict:
    defaults = {
        "locker_bank_id": locker_bank_id,
        "size_class": "LARGE",
        # storage_class is optional: defaults to the owning bank's class when omitted.
    }
    defaults.update(overrides)
    return defaults


def create_shelf_payload(property_id: str, **overrides) -> dict:
    defaults = {
        "property_id": property_id,
        "zone": "Z1",
        "storage_class": "AMBIENT",
        "capacity": 5,
    }
    defaults.update(overrides)
    return defaults


def create_resident_payload(property_id: str, **overrides) -> dict:
    defaults = {
        "property_id": property_id,
        "unit_number": "101",
        "full_name": "Ada Resident",
        "email": "ada@example.com",
    }
    defaults.update(overrides)
    return defaults


def create_carrier_payload(property_id: str, **overrides) -> dict:
    defaults = {
        "property_id": property_id,
        "name": "UPS",
        "scac": "UPSN",
    }
    defaults.update(overrides)
    return defaults


def create_package_payload(property_id: str, resident_id: str, carrier_id: str, **overrides) -> dict:
    defaults = {
        "property_id": property_id,
        "resident_id": resident_id,
        "carrier_id": carrier_id,
        "tracking_number": unique_tracking(),
        "size_class": "MEDIUM",
        "storage_type": "AMBIENT",
    }
    defaults.update(overrides)
    return defaults


def create_retail_return_payload(property_id: str, resident_id: str, carrier_id: str, **overrides) -> dict:
    defaults = {
        "property_id": property_id,
        "resident_id": resident_id,
        "carrier_id": carrier_id,
        "tracking_number": unique_tracking("RR"),
    }
    defaults.update(overrides)
    return defaults


def notify_payload(storage_target: str = None, locker_id: str = None, shelf_id: str = None) -> dict:
    """POST /packages/{id}/notify body. All fields optional; empty body == reminder / auto-assign."""
    payload = {}
    if storage_target is not None:
        payload["storage_target"] = storage_target
    if locker_id is not None:
        payload["locker_id"] = locker_id
    if shelf_id is not None:
        payload["shelf_id"] = shelf_id
    return payload


def pickup_payload(pickup_code: str) -> dict:
    return {"pickup_code": pickup_code}


def policy_update_payload(expected_property_version: int, **overrides) -> dict:
    defaults = {"expected_property_version": expected_property_version}
    defaults.update(overrides)
    return defaults


def pms_sync_payload(event_type: str) -> dict:
    return {"event_type": event_type}
