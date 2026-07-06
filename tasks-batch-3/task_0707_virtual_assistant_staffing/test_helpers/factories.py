"""Payload factories — one per entity, input fields only.

Field names follow the PRD verbatim. Optional fields are only included when a
test wants to control them (passed via **overrides), except where the factory
supplies a sensible default so the bare call succeeds.
"""
from .constants import TEST_DEFAULTS

_email_counter = [0]


def unique_email(prefix: str = "user") -> str:
    """Generate a process-unique email so uniqueness constraints don't collide
    across calls within one test."""
    _email_counter[0] += 1
    return f"{prefix}{_email_counter[0]}@example.com"


# ─── SkillTag ──────────────────────────────────────────────────────────────
def create_skill_tag_payload(code="BOOKKEEPING", name="Bookkeeping", **overrides) -> dict:
    payload = {"code": code, "name": name}
    payload.update(overrides)
    return payload


# ─── SlaPolicy ─────────────────────────────────────────────────────────────
def create_sla_policy_payload(tier="STANDARD", **overrides) -> dict:
    payload = {
        "tier": tier,
        "response_minutes": TEST_DEFAULTS["RESPONSE_MINUTES"],
        "resolution_hours": TEST_DEFAULTS["RESOLUTION_HOURS"],
        "breach_penalty_pct": TEST_DEFAULTS["BREACH_PENALTY_PCT"],
    }
    payload.update(overrides)
    return payload


# ─── VirtualAssistant ──────────────────────────────────────────────────────
def create_virtual_assistant_payload(full_name="Test VA", email=None,
                                      skill_tag_ids=None, **overrides) -> dict:
    payload = {
        "full_name": full_name,
        "email": email if email is not None else unique_email("va"),
        "skill_tag_ids": skill_tag_ids if skill_tag_ids is not None else [],
        "weekly_capacity_hours": TEST_DEFAULTS["WEEKLY_CAPACITY_HOURS"],
        "rating": TEST_DEFAULTS["RATING"],
    }
    payload.update(overrides)
    return payload


# ─── Client ────────────────────────────────────────────────────────────────
def create_client_payload(company_name="Test Co", contact_email=None, **overrides) -> dict:
    payload = {
        "company_name": company_name,
        "contact_email": contact_email if contact_email is not None else unique_email("client"),
    }
    payload.update(overrides)
    return payload


def scope_client_payload(required_skill_tag_ids=None, **overrides) -> dict:
    payload = {
        "scope_summary": "admin",
        "required_skill_tag_ids": required_skill_tag_ids if required_skill_tag_ids is not None else [],
        "monthly_retainer_hours": TEST_DEFAULTS["MONTHLY_RETAINER_HOURS"],
        "base_rate_cents": TEST_DEFAULTS["BASE_RATE_CENTS"],
        "overage_rate_cents": TEST_DEFAULTS["OVERAGE_RATE_CENTS"],
        "rollover_cap_hours": TEST_DEFAULTS["ROLLOVER_CAP_HOURS"],
    }
    payload.update(overrides)
    return payload


# ─── Engagement ────────────────────────────────────────────────────────────
def create_engagement_payload(client_id, va_id=None, **overrides) -> dict:
    payload = {"client_id": client_id}
    if va_id is not None:
        payload["va_id"] = va_id
    payload.update(overrides)
    return payload


def activate_engagement_payload(onboarding_checklist_done=True, **overrides) -> dict:
    payload = {"onboarding_checklist_done": onboarding_checklist_done}
    payload.update(overrides)
    return payload


# ─── AddOn ─────────────────────────────────────────────────────────────────
def create_addon_payload(engagement_id, skill_tag_id, surcharge_rate_cents=3000, **overrides) -> dict:
    payload = {
        "engagement_id": engagement_id,
        "skill_tag_id": skill_tag_id,
        "surcharge_rate_cents": surcharge_rate_cents,
    }
    payload.update(overrides)
    return payload


# ─── Task ──────────────────────────────────────────────────────────────────
def create_task_payload(client_id, title="Test Task", priority="STANDARD",
                        required_skill_tag_id=None, estimated_hours=1, **overrides) -> dict:
    payload = {
        "client_id": client_id,
        "title": title,
        "priority": priority,
        "estimated_hours": estimated_hours,
    }
    if required_skill_tag_id is not None:
        payload["required_skill_tag_id"] = required_skill_tag_id
    payload.update(overrides)
    return payload


# ─── TimeEntry ─────────────────────────────────────────────────────────────
def create_time_entry_payload(task_id, raw_minutes=60, **overrides) -> dict:
    payload = {"task_id": task_id, "raw_minutes": raw_minutes}
    payload.update(overrides)
    return payload


# ─── Escalation ────────────────────────────────────────────────────────────
def create_escalation_payload(client_id, reason="QUALITY", **overrides) -> dict:
    payload = {"client_id": client_id, "reason": reason}
    payload.update(overrides)
    return payload


def replace_escalation_payload(va_id, **overrides) -> dict:
    payload = {"va_id": va_id}
    payload.update(overrides)
    return payload


# ─── Invoice ───────────────────────────────────────────────────────────────
def create_invoice_payload(client_id, cycle_id, variant="FINAL", **overrides) -> dict:
    payload = {"client_id": client_id, "cycle_id": cycle_id, "variant": variant}
    payload.update(overrides)
    return payload


def close_cycle_payload(expected_cycle_version, **overrides) -> dict:
    payload = {"expected_cycle_version": expected_cycle_version}
    payload.update(overrides)
    return payload
