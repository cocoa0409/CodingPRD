"""Payload factories — one per entity, input fields only."""
from .constants import DEFAULT_EFFECTIVE_FROM, DEFAULT_EFFECTIVE_UNTIL


def create_contact_payload(**overrides) -> dict:
    defaults = {"full_name": "Test Contact", "primary_language": "EN"}
    defaults.update(overrides)
    return defaults


def create_channel_payload(**overrides) -> dict:
    defaults = {"channel_type": "SMS", "address": "+15550000"}
    defaults.update(overrides)
    return defaults


def create_group_payload(**overrides) -> dict:
    defaults = {"name": "Test Group"}
    defaults.update(overrides)
    return defaults


def create_subscription_payload(contact_id, subscription_type="GROUP", **overrides) -> dict:
    defaults = {"contact_id": contact_id, "subscription_type": subscription_type}
    defaults.update(overrides)
    return defaults


def create_template_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Template",
        "default_severity": "WARNING",
        "body_by_language": {"EN": "Body."},
    }
    defaults.update(overrides)
    return defaults


def create_alert_payload(**overrides) -> dict:
    defaults = {
        "title": "Test Alert",
        "severity": "WARNING",
        "channels": ["SMS"],
        "target_type": "GROUP",
        "effective_from": DEFAULT_EFFECTIVE_FROM,
        "effective_until": DEFAULT_EFFECTIVE_UNTIL,
    }
    defaults.update(overrides)
    return defaults


def create_localization_payload(**overrides) -> dict:
    defaults = {"language": "EN", "message_text": "Warning."}
    defaults.update(overrides)
    return defaults


def create_gateway_payload(**overrides) -> dict:
    defaults = {"name": "SMS-GW", "channel_type": "SMS", "capacity_per_window": 100}
    defaults.update(overrides)
    return defaults


def create_maintenance_window_payload(start_at, end_at) -> dict:
    return {"start_at": start_at, "end_at": end_at}


def create_drill_payload(group_id, scheduled_start, scheduled_end) -> dict:
    return {"group_id": group_id, "scheduled_start": scheduled_start, "scheduled_end": scheduled_end}
