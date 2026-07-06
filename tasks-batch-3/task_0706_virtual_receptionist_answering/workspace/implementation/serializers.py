"""Serializers: build the public JSON view of each entity.

Each serializer emits exactly the fields declared in SCAFFOLD §1.1 plus the
common fields (id, created_at, updated_at, version) per PRD §2.4. ServicePlan
omits updated_at/version (immutable price card).
"""


def _base(rec, include_version=True):
    out = {"id": rec["id"], "created_at": rec["created_at"]}
    if include_version:
        out["updated_at"] = rec["updated_at"]
        out["version"] = rec["version"]
    return out


def service_plan(rec):
    # Immutable: only id + created_at among common fields (PRD §2.4).
    out = _base(rec, include_version=False)
    out.update({
        "name": rec["name"],
        "billing_model": rec["billing_model"],
        "included_minutes": rec["included_minutes"],
        "included_calls": rec["included_calls"],
        "base_fee_cents": rec["base_fee_cents"],
        "overage_rate_cents": rec["overage_rate_cents"],
        "overage_tier2_threshold": rec["overage_tier2_threshold"],
        "overage_tier2_rate_cents": rec["overage_tier2_rate_cents"],
        "hard_cap_overage_cents": rec["hard_cap_overage_cents"],
        "minute_rounding": rec["minute_rounding"],
    })
    return out


def account(rec):
    out = _base(rec)
    out.update({
        "business_name": rec["business_name"],
        "plan_id": rec["plan_id"],
        "default_language": rec["default_language"],
        "status": rec["status"],
        "current_period_id": rec["current_period_id"],
        "open_call_count": rec["open_call_count"],
        "lifetime_calls_answered": rec["lifetime_calls_answered"],
    })
    return out


def call_script(rec):
    out = _base(rec)
    out.update({
        "account_id": rec["account_id"],
        "greeting_en": rec["greeting_en"],
        "greeting_es": rec["greeting_es"],
        "business_open_minute": rec["business_open_minute"],
        "business_close_minute": rec["business_close_minute"],
        "after_hours_action": rec["after_hours_action"],
        "overflow_action": rec["overflow_action"],
        "escalation_threshold_seconds": rec["escalation_threshold_seconds"],
        "status": rec["status"],
    })
    return out


def spam_rule(rec):
    out = _base(rec)
    out.update({
        "account_id": rec["account_id"],
        "blocked_area_codes": rec["blocked_area_codes"],
        "spam_score_threshold": rec["spam_score_threshold"],
        "anonymous_penalty": rec["anonymous_penalty"],
        "status": rec["status"],
    })
    return out


def receptionist(rec):
    out = _base(rec)
    out.update({
        "display_name": rec["display_name"],
        "languages": rec["languages"],
        "max_concurrent_calls": rec["max_concurrent_calls"],
        "status": rec["status"],
        "active_call_count": rec["active_call_count"],
    })
    return out


def availability_window(rec):
    out = _base(rec)
    out.update({
        "receptionist_id": rec["receptionist_id"],
        "start_minute": rec["start_minute"],
        "end_minute": rec["end_minute"],
        "status": rec["status"],
    })
    return out


def calendar_slot(rec):
    out = _base(rec)
    out.update({
        "account_id": rec["account_id"],
        "window_start": rec["window_start"],
        "window_end": rec["window_end"],
        "buffer_minutes": rec["buffer_minutes"],
        "capacity": rec["capacity"],
        "booked_count": rec["booked_count"],
        "available_count": rec["available_count"],
        "status": rec["status"],
    })
    return out


def call(rec):
    out = _base(rec)
    out.update({
        "account_id": rec["account_id"],
        "script_id": rec["script_id"],
        "caller_id": rec["caller_id"],
        "requested_language": rec["requested_language"],
        "received_minute": rec["received_minute"],
        "is_after_hours": rec["is_after_hours"],
        "spam_score": rec["spam_score"],
        "answered_by_receptionist_id": rec["answered_by_receptionist_id"],
        "handling_status": rec["handling_status"],
        "billing_status": rec["billing_status"],
        "start_second": rec["start_second"],
        "end_second": rec["end_second"],
        "duration_seconds": rec["duration_seconds"],
        "billed_units": rec["billed_units"],
        "charge_cents": rec["charge_cents"],
    })
    return out


def message(rec):
    out = _base(rec)
    out.update({
        "call_id": rec["call_id"],
        "caller_name": rec["caller_name"],
        "callback_number": rec["callback_number"],
        "body": rec["body"],
        "is_lead": rec["is_lead"],
        "status": rec["status"],
    })
    return out


def escalation(rec):
    out = _base(rec)
    out.update({
        "call_id": rec["call_id"],
        "reason": rec["reason"],
        "escalated_to_receptionist_id": rec["escalated_to_receptionist_id"],
        "status": rec["status"],
    })
    return out


def crm_handoff(rec):
    out = _base(rec)
    out.update({
        "call_id": rec["call_id"],
        "crm_target": rec["crm_target"],
        "messages_pushed": rec["messages_pushed"],
        "status": rec["status"],
    })
    return out


def appointment(rec):
    out = _base(rec)
    out.update({
        "account_id": rec["account_id"],
        "slot_id": rec["slot_id"],
        "origin_call_id": rec["origin_call_id"],
        "start_at": rec["start_at"],
        "end_at": rec["end_at"],
        "status": rec["status"],
        "reschedule_count": rec["reschedule_count"],
    })
    return out


def billing_period(rec):
    out = _base(rec)
    out.update({
        "account_id": rec["account_id"],
        "plan_id": rec["plan_id"],
        "period_index": rec["period_index"],
        "included_units": rec["included_units"],
        "consumed_units": rec["consumed_units"],
        "overage_units": rec["overage_units"],
        "overage_charge_cents": rec["overage_charge_cents"],
        "status": rec["status"],
    })
    return out
