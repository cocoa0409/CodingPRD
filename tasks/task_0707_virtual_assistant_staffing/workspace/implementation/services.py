"""State-machine transitions, cascades, and cross-entity side effects.

Every mutation atomically refreshes updated_at + bumps version on each touched
full-lifecycle entity (§2.4 / §2.10). Computed fields (open_task_count,
active_engagement_count, billed_hours, cycle balances) are derived at read time
in serialize.py, so transitions only mutate stored state + back-pointers.
"""
from db import db, stamp_create, touch
from errors import err
import sla as sla_mod
import calculations as calc

NON_TERMINAL_TASK = {"QUEUED", "ASSIGNED", "IN_PROGRESS", "BLOCKED"}


# --- VA availability counter -------------------------------------------------
def va_active_count(va_id):
    return sum(1 for e in db.engagements.values()
               if e["va_id"] == va_id and e["status"] == "ACTIVE")


def refresh_va_availability(va_id):
    """If a VA holds 0 ACTIVE engagements, return it to AVAILABLE.

    Only used by transitions that may drop the count to 0 (end/return/replace).
    """
    va = db.virtual_assistants.get(va_id)
    if va is None:
        return
    if va_active_count(va_id) == 0:
        va["status"] = "AVAILABLE"
        touch(va)


# --- RetainerCycle helpers ---------------------------------------------------
def open_cycle_for_client(client_id):
    for c in db.retainer_cycles.values():
        if c["client_id"] == client_id and c["status"] == "OPEN":
            return c
    return None


def open_first_cycle(client_rec):
    """Open RetainerCycle #1 for a client becoming ACTIVE (§3.3)."""
    cyc = {
        "client_id": client_rec["id"],
        "sequence_no": 1,
        "status": "OPEN",
        "granted_hours": client_rec["monthly_retainer_hours"],
        "rolled_in_hours": 0,
        "opened_at_iso": db.clock_iso_logical(),
        "closed_at_iso": None,
    }
    stamp_create(cyc)
    db.retainer_cycles[cyc["id"]] = cyc
    return cyc


# --- Client transitions ------------------------------------------------------
def client_to_active_via_engagement(client_rec, engagement_rec):
    """SCOPED -> ACTIVE driven by an engagement activating (§3.2/§3.3)."""
    client_rec["status"] = "ACTIVE"
    open_first_cycle(client_rec)
    touch(client_rec)


# --- Task transitions / cascades --------------------------------------------
def reject_logged_entries_of_task(task_rec):
    for te in db.time_entries.values():
        if te["task_id"] == task_rec["id"] and te["status"] == "LOGGED":
            te["status"] = "REJECTED"
            touch(te)


def cancel_task_cascade(task_rec):
    """Task -> CANCELLED; its LOGGED entries -> REJECTED (§3.4)."""
    task_rec["status"] = "CANCELLED"
    reject_logged_entries_of_task(task_rec)
    touch(task_rec)


def restamp_task_sla(task_rec):
    """Re-stamp assigned_at + due dates against the current clock."""
    task_rec["assigned_at_iso"] = db.clock_iso_logical()
    resp, res = sla_mod.compute_due(task_rec["assigned_at_iso"], task_rec["priority"])
    task_rec["response_due_iso"] = resp
    task_rec["resolution_due_iso"] = res


def reset_task_sla(task_rec):
    """Clear SLA timers when a task is re-queued (engagement end, §3.3)."""
    task_rec["engagement_id"] = None
    task_rec["status"] = "QUEUED"
    task_rec["assigned_at_iso"] = None
    task_rec["first_action_at_iso"] = None
    task_rec["response_due_iso"] = None
    task_rec["resolution_due_iso"] = None


# --- Engagement end / re-home ------------------------------------------------
def end_engagement(engagement_rec, repoint_to=None):
    """ACTIVE -> ENDED with VA + client + task side effects (§3.3).

    repoint_to: when set (replacement), non-terminal tasks are re-pointed to the
    replacement engagement id and SLA re-stamped (ASSIGNED/IN_PROGRESS). When
    None (plain end / client close), non-terminal tasks are re-queued with SLA
    reset.
    """
    engagement_rec["status"] = "ENDED"
    va = db.virtual_assistants.get(engagement_rec["va_id"])

    client = db.clients.get(engagement_rec["client_id"])
    if client is not None and client.get("active_engagement_id") == engagement_rec["id"]:
        # On replacement the new engagement has already claimed active_engagement_id;
        # only clear if it still points here.
        client["active_engagement_id"] = None
        touch(client)

    # Re-home / re-queue the engagement's non-terminal tasks.
    for t in db.tasks.values():
        if t.get("engagement_id") == engagement_rec["id"] and t["status"] in NON_TERMINAL_TASK:
            if repoint_to is not None:
                t["engagement_id"] = repoint_to
                if t["status"] in ("ASSIGNED", "IN_PROGRESS"):
                    restamp_task_sla(t)
                touch(t)
            else:
                reset_task_sla(t)
                touch(t)

    touch(engagement_rec)
    # VA count drop -> AVAILABLE if 0.
    if va is not None:
        refresh_va_availability(va["id"])
