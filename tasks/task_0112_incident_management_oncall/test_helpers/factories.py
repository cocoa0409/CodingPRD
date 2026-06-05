"""Payload factories — one per entity, input fields only.

Field names are PRD-exact. Only source:input fields appear here.
"""
import itertools

# Per-process counters so default unique fields (responder email, sms) do not
# collide when a test creates several responders. Each test still runs against
# a fresh server/database; counters only de-duplicate within a single test.
_email_counter = itertools.count(1)
_sms_counter = itertools.count(10000)


def create_service_payload(**overrides) -> dict:
    """POST /services. Inputs: name, tier? (default TIER_2), error_budget_minutes."""
    defaults = {
        "name": "Checkout Service",
        "tier": "TIER_2",
        "error_budget_minutes": 1000,
    }
    defaults.update(overrides)
    return defaults


def create_responder_payload(**overrides) -> dict:
    """POST /responders. Inputs: full_name, email, sms_number?, voice_number?, push_token?."""
    n = next(_email_counter)
    defaults = {
        "full_name": "Test Responder",
        "email": f"responder{n}@example.com",
        "sms_number": f"+1555{next(_sms_counter)}",
    }
    defaults.update(overrides)
    return defaults


def create_on_call_schedule_payload(service_id, **overrides) -> dict:
    """POST /on-call-schedules. Inputs: name, service_id, handoff_interval_hours?."""
    defaults = {
        "name": "Primary Rotation",
        "service_id": service_id,
    }
    defaults.update(overrides)
    return defaults


def create_schedule_shift_payload(schedule_id, responder_id, starts_at, ends_at, **overrides) -> dict:
    """POST /schedule-shifts. Inputs: schedule_id, responder_id, starts_at, ends_at."""
    defaults = {
        "schedule_id": schedule_id,
        "responder_id": responder_id,
        "starts_at": starts_at,
        "ends_at": ends_at,
    }
    defaults.update(overrides)
    return defaults


def create_escalation_policy_payload(service_id, **overrides) -> dict:
    """POST /escalation-policies. Inputs: name, service_id, repeat_rounds?."""
    defaults = {
        "name": "Standard Policy",
        "service_id": service_id,
    }
    defaults.update(overrides)
    return defaults


def create_escalation_tier_payload(policy_id, schedule_id, tier_level, delay_minutes, **overrides) -> dict:
    """POST /escalation-tiers. Inputs: policy_id, schedule_id, tier_level, delay_minutes."""
    defaults = {
        "policy_id": policy_id,
        "schedule_id": schedule_id,
        "tier_level": tier_level,
        "delay_minutes": delay_minutes,
    }
    defaults.update(overrides)
    return defaults


def create_maintenance_window_payload(service_id, starts_at, ends_at, **overrides) -> dict:
    """POST /maintenance-windows. Inputs: service_id, starts_at, ends_at, reason?."""
    defaults = {
        "service_id": service_id,
        "starts_at": starts_at,
        "ends_at": ends_at,
    }
    defaults.update(overrides)
    return defaults


def create_incident_payload(service_id, policy_id, severity="SEV2", **overrides) -> dict:
    """POST /incidents. Inputs: service_id, policy_id, title, severity."""
    defaults = {
        "service_id": service_id,
        "policy_id": policy_id,
        "title": "Test Incident",
        "severity": severity,
    }
    defaults.update(overrides)
    return defaults


def escalate_payload(expected_incident_version, **overrides) -> dict:
    """POST /incidents/{id}/escalate. Input: expected_incident_version."""
    defaults = {"expected_incident_version": expected_incident_version}
    defaults.update(overrides)
    return defaults


def create_war_room_payload(incident_id, **overrides) -> dict:
    """POST /war-rooms. Inputs: incident_id, bridge_url?."""
    defaults = {"incident_id": incident_id}
    defaults.update(overrides)
    return defaults


def create_war_room_message_payload(body="status update", **overrides) -> dict:
    """POST /war-rooms/{id}/messages. Input: body."""
    defaults = {"body": body}
    defaults.update(overrides)
    return defaults


def create_postmortem_payload(incident_id, summary="root cause analysis", **overrides) -> dict:
    """POST /postmortems. Inputs: incident_id, summary."""
    defaults = {"incident_id": incident_id, "summary": summary}
    defaults.update(overrides)
    return defaults


def create_action_item_payload(postmortem_id, owner_responder_id, description="fix the bug", **overrides) -> dict:
    """POST /action-items. Inputs: postmortem_id, owner_responder_id, description."""
    defaults = {
        "postmortem_id": postmortem_id,
        "owner_responder_id": owner_responder_id,
        "description": description,
    }
    defaults.update(overrides)
    return defaults
