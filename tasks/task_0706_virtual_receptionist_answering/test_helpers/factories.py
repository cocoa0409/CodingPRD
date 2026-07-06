"""Payload factories — one per entity, input fields only.

Required fields carry concrete defaults; optional fields (those the PRD declares
optional or with a server-side default) are omitted unless overridden.
"""

# --- ServicePlan -------------------------------------------------------------
def create_per_minute_plan_payload(**overrides) -> dict:
    """A valid PER_MINUTE service plan. included_calls is omitted (defaults 0)."""
    defaults = {
        "name": "Per-Minute Plan",
        "billing_model": "PER_MINUTE",
        "base_fee_cents": 0,
        "overage_rate_cents": 100,
        "overage_tier2_rate_cents": 300,
        "hard_cap_overage_cents": 100_000,
        "included_minutes": 60,
        "overage_tier2_threshold": 100,
    }
    defaults.update(overrides)
    return defaults


def create_per_call_plan_payload(**overrides) -> dict:
    """A valid PER_CALL service plan. included_minutes is omitted (defaults 0)."""
    defaults = {
        "name": "Per-Call Plan",
        "billing_model": "PER_CALL",
        "base_fee_cents": 0,
        "overage_rate_cents": 50,
        "overage_tier2_rate_cents": 50,
        "hard_cap_overage_cents": 100_000,
        "included_calls": 100,
        "overage_tier2_threshold": 100,
    }
    defaults.update(overrides)
    return defaults


# --- ClientAccount -----------------------------------------------------------
def create_account_payload(plan_id, **overrides) -> dict:
    """default_language is optional (defaults EN); omitted unless overridden."""
    defaults = {"business_name": "Test Business", "plan_id": plan_id}
    defaults.update(overrides)
    return defaults


# --- CallScript --------------------------------------------------------------
def create_call_script_payload(account_id, **overrides) -> dict:
    """A 24h-open DRAFT script. greeting_es / after_hours_action / overflow_action /
    escalation_threshold_seconds are optional; omitted unless overridden."""
    defaults = {
        "account_id": account_id,
        "greeting_en": "Hello",
        "business_open_minute": 0,
        "business_close_minute": 1440,
    }
    defaults.update(overrides)
    return defaults


# --- SpamRule ----------------------------------------------------------------
def create_spam_rule_payload(account_id, **overrides) -> dict:
    """blocked_area_codes / spam_score_threshold / anonymous_penalty all optional."""
    defaults = {"account_id": account_id}
    defaults.update(overrides)
    return defaults


# --- Receptionist ------------------------------------------------------------
def create_receptionist_payload(**overrides) -> dict:
    """max_concurrent_calls is optional (defaults 1); omitted unless overridden."""
    defaults = {"display_name": "Agent", "languages": ["EN"]}
    defaults.update(overrides)
    return defaults


# --- AvailabilityWindow ------------------------------------------------------
def create_availability_window_payload(**overrides) -> dict:
    defaults = {"start_minute": 0, "end_minute": 1440}
    defaults.update(overrides)
    return defaults


# --- CalendarSlot ------------------------------------------------------------
def create_calendar_slot_payload(account_id, **overrides) -> dict:
    """buffer_minutes (defaults 0) and capacity (defaults 1) are optional."""
    defaults = {
        "account_id": account_id,
        "window_start": "2026-03-02T09:00:00Z",
        "window_end": "2026-03-02T17:00:00Z",
    }
    defaults.update(overrides)
    return defaults


# --- Call --------------------------------------------------------------------
def create_call_payload(account_id, **overrides) -> dict:
    """caller_id (defaults "") and requested_language (defaults EN) are optional."""
    defaults = {"account_id": account_id}
    defaults.update(overrides)
    return defaults


# --- Message -----------------------------------------------------------------
def create_message_payload(call_id, **overrides) -> dict:
    """is_lead is optional (defaults false); the other body fields are required."""
    defaults = {
        "call_id": call_id,
        "caller_name": "Caller",
        "callback_number": "5551212",
        "body": "Message body",
    }
    defaults.update(overrides)
    return defaults


# --- Escalation --------------------------------------------------------------
def escalate_payload(**overrides) -> dict:
    defaults = {"reason": "LONG_RUNNING"}
    defaults.update(overrides)
    return defaults


# --- CrmHandoff --------------------------------------------------------------
def create_crm_handoff_payload(call_id, **overrides) -> dict:
    defaults = {"call_id": call_id, "crm_target": "SALESFORCE"}
    defaults.update(overrides)
    return defaults


# --- Appointment -------------------------------------------------------------
def create_appointment_payload(account_id, slot_id, expected_slot_version, **overrides) -> dict:
    """origin_call_id is optional (defaults ""); the rest are required."""
    defaults = {
        "account_id": account_id,
        "slot_id": slot_id,
        "start_at": "2026-03-02T10:00:00Z",
        "end_at": "2026-03-02T10:30:00Z",
        "expected_slot_version": expected_slot_version,
    }
    defaults.update(overrides)
    return defaults


def reschedule_payload(start_at, end_at) -> dict:
    return {"start_at": start_at, "end_at": end_at}


def adjust_payload(adjusted_units, expected_call_version) -> dict:
    return {"adjusted_units": adjusted_units, "expected_call_version": expected_call_version}
