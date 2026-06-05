"""Serialize internal records into API-facing JSON dicts.

Datetimes stored internally as aware datetime objects; serialized to
ISO 8601 UTC with three fractional digits, except SLA deadlines which are
stamped to whole seconds (.000).
"""
from db import iso_ms, iso_sec
from services import budget


def _common(record, out, common_fields=True):
    out["id"] = record["id"]
    out["created_at"] = iso_ms(record["created_at"])
    if common_fields:
        out["updated_at"] = iso_ms(record["updated_at"])
        out["version"] = record["version"]
    return out


def service_out(svc):
    consumed = budget.consumed_minutes(svc)
    remaining = max(0, svc["error_budget_minutes"] - consumed)
    status = budget.budget_status(svc, consumed)
    out = {
        "name": svc["name"],
        "tier": svc["tier"],
        "error_budget_minutes": svc["error_budget_minutes"],
        "budget_status": status,
        "error_budget_consumed_minutes": consumed,
        "error_budget_remaining_minutes": remaining,
    }
    return _common(svc, out)


def responder_out(r):
    out = {
        "full_name": r["full_name"],
        "email": r["email"],
        "sms_number": r.get("sms_number"),
        "voice_number": r.get("voice_number"),
        "push_token": r.get("push_token"),
    }
    return _common(r, out)


def schedule_out(s):
    out = {
        "name": s["name"],
        "service_id": s["service_id"],
        "handoff_interval_hours": s["handoff_interval_hours"],
    }
    return _common(s, out)


def shift_out(sh):
    out = {
        "schedule_id": sh["schedule_id"],
        "responder_id": sh["responder_id"],
        "starts_at": iso_ms(sh["starts_at"]),
        "ends_at": iso_ms(sh["ends_at"]),
    }
    return _common(sh, out)


def policy_out(p):
    out = {
        "name": p["name"],
        "service_id": p["service_id"],
        "repeat_rounds": p["repeat_rounds"],
    }
    return _common(p, out)


def tier_out(t):
    out = {
        "policy_id": t["policy_id"],
        "schedule_id": t["schedule_id"],
        "tier_level": t["tier_level"],
        "delay_minutes": t["delay_minutes"],
    }
    return _common(t, out)


def window_out(w):
    out = {
        "service_id": w["service_id"],
        "status": w["status"],
        "starts_at": iso_ms(w["starts_at"]),
        "ends_at": iso_ms(w["ends_at"]),
        "reason": w.get("reason"),
    }
    return _common(w, out)


def incident_out(inc):
    out = {
        "service_id": inc["service_id"],
        "policy_id": inc["policy_id"],
        "title": inc["title"],
        "severity": inc["severity"],
        "lifecycle_status": inc["lifecycle_status"],
        "escalation_status": inc["escalation_status"],
        "current_tier_level": inc["current_tier_level"],
        "triggered_at": iso_ms(inc["triggered_at"]),
        "acknowledged_at": iso_ms(inc.get("acknowledged_at")),
        "resolved_at": iso_ms(inc.get("resolved_at")),
        "ack_deadline_at": iso_sec(inc["ack_deadline_at"]),
        "resolve_deadline_at": iso_sec(inc["resolve_deadline_at"]),
        "ack_sla_breached": _ack_breached_now(inc),
        "counts_against_budget": inc["counts_against_budget"],
        "downtime_minutes": inc.get("downtime_minutes", 0),
    }
    return _common(inc, out)


def _ack_breached_now(inc):
    """ack_sla_breached: true once acknowledged_at > ack_deadline_at, OR
    current clock > ack_deadline_at while unacknowledged (PRD 3.5)."""
    from db import db
    deadline = inc["ack_deadline_at"]
    if inc.get("acknowledged_at") is not None:
        return inc["acknowledged_at"] > deadline
    return db.clock.now() > deadline


def page_attempt_out(pa):
    out = {
        "incident_id": pa["incident_id"],
        "responder_id": pa["responder_id"],
        "tier_level": pa["tier_level"],
        "channel": pa["channel"],
        "round_index": pa["round_index"],
    }
    return _common(pa, out, common_fields=False)


def war_room_out(wr):
    out = {
        "incident_id": wr["incident_id"],
        "status": wr["status"],
        "bridge_url": wr.get("bridge_url"),
    }
    return _common(wr, out)


def war_room_message_out(m):
    out = {
        "war_room_id": m["war_room_id"],
        "author_role": m["author_role"],
        "author_id": m.get("author_id"),
        "body": m["body"],
    }
    return _common(m, out, common_fields=False)


def postmortem_out(pm):
    out = {
        "incident_id": pm["incident_id"],
        "status": pm["status"],
        "summary": pm["summary"],
        "open_action_item_count": _open_action_item_count(pm["id"]),
    }
    return _common(pm, out)


def _open_action_item_count(postmortem_id):
    """count of child ActionItem rows whose status IN {OPEN, IN_PROGRESS}."""
    from db import db
    return sum(
        1 for ai in db.action_items.values()
        if ai["postmortem_id"] == postmortem_id
        and ai["status"] in ("OPEN", "IN_PROGRESS")
    )


def action_item_out(ai):
    out = {
        "postmortem_id": ai["postmortem_id"],
        "owner_responder_id": ai["owner_responder_id"],
        "description": ai["description"],
        "status": ai["status"],
    }
    return _common(ai, out)
