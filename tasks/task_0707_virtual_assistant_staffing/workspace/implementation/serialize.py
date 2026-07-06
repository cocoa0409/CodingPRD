"""Public serialization for each entity (computes computed fields).

Strips internal-only keys (e.g. _seq). Computed fields (§1.1 source: computed)
are derived here at read time so reads always reflect current state.
"""
from db import db
from sla import sla_state
from calculations import billable_hours

TERMINAL_TASK = {"DONE", "CANCELLED"}

# Fields that are internal-only and must never appear in API output.
_HIDDEN = {"_seq", "_pre_suspend_status"}


def _public(record):
    return {k: v for k, v in record.items() if k not in _HIDDEN}


# --- helpers over the store -------------------------------------------------
def _approved_entries_for_cycle(cycle_id):
    return [te for te in db.time_entries.values()
            if te.get("cycle_id") == cycle_id and te["status"] == "APPROVED"]


def _approved_entries_for_task(task_id):
    return [te for te in db.time_entries.values()
            if te["task_id"] == task_id and te["status"] == "APPROVED"]


def client_active_engagement_id(client_id):
    c = db.clients.get(client_id)
    return c.get("active_engagement_id") if c else None


# --- SkillTag (reference record) --------------------------------------------
def skill_tag(rec):
    return _public(rec)


# --- SlaPolicy (reference record) -------------------------------------------
def sla_policy(rec):
    return _public(rec)


# --- Clock (reference record) -----------------------------------------------
def clock_view():
    return {
        "id": "clock",
        "created_at": db.clock_iso(),
        "current_utc": db.clock.iso_clock(),
    }


# --- Client -----------------------------------------------------------------
def client(rec):
    out = _public(rec)
    out["open_task_count"] = sum(
        1 for t in db.tasks.values()
        if t["client_id"] == rec["id"] and t["status"] not in TERMINAL_TASK
    )
    return out


# --- VirtualAssistant -------------------------------------------------------
def virtual_assistant(rec):
    out = _public(rec)
    out["active_engagement_count"] = sum(
        1 for e in db.engagements.values()
        if e["va_id"] == rec["id"] and e["status"] == "ACTIVE"
    )
    return out


# --- Engagement -------------------------------------------------------------
def engagement(rec):
    return _public(rec)


# --- RetainerCycle ----------------------------------------------------------
def retainer_cycle(rec):
    out = _public(rec)
    approved = _approved_entries_for_cycle(rec["id"])
    from calculations import cycle_balance
    consumed, available, overage = cycle_balance(
        rec["granted_hours"], rec["rolled_in_hours"],
        [te["billable_hours"] for te in approved],
    )
    out["consumed_hours"] = consumed
    out["available_hours"] = available
    out["overage_hours"] = overage
    return out


def cycle_consumed_hours(rec):
    approved = _approved_entries_for_cycle(rec["id"])
    from calculations import cycle_balance
    consumed, _, _ = cycle_balance(
        rec["granted_hours"], rec["rolled_in_hours"],
        [te["billable_hours"] for te in approved],
    )
    return consumed


# --- Task -------------------------------------------------------------------
def task(rec):
    out = _public(rec)
    out["sla_state"] = sla_state(rec)
    out["billed_hours"] = task_billed_hours(rec)
    return out


def task_billed_hours(rec):
    approved = _approved_entries_for_task(rec["id"])
    from calculations import round_hours2
    total = sum(te["billable_hours"] for te in approved)
    return round_hours2(total)


# --- TimeEntry --------------------------------------------------------------
def time_entry(rec):
    return _public(rec)


# --- AddOn ------------------------------------------------------------------
def addon(rec):
    return _public(rec)


# --- Escalation -------------------------------------------------------------
def escalation(rec):
    return _public(rec)


# --- Invoice ----------------------------------------------------------------
def invoice(rec):
    return _public(rec)
