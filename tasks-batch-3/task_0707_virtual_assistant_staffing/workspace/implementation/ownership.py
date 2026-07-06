"""Ownership resolution for entity-backed roles (PRD §2.1).

Client (X-User-ID = Client.id): owns any resource whose owning client (resolved
transitively through engagement/task/cycle/entry/escalation/addon/invoice) equals
X-User-ID.

VA (X-User-ID = VirtualAssistant.id): owns a task or time entry when the VA of
that resource's engagement equals X-User-ID.

Violations raise ERR_FORBIDDEN (403). Resolution runs AFTER path existence so the
records are known to exist.
"""
from db import db
from errors import err


# --- transitive owning-client resolvers -------------------------------------
def client_of_engagement(eng):
    return eng["client_id"]


def client_of_task(task):
    return task["client_id"]


def client_of_time_entry(te):
    task = db.tasks.get(te["task_id"])
    return task["client_id"] if task else None


def client_of_cycle(cyc):
    return cyc["client_id"]


def client_of_addon(addon):
    eng = db.engagements.get(addon["engagement_id"])
    return eng["client_id"] if eng else None


def client_of_escalation(esc):
    return esc["client_id"]


def client_of_invoice(inv):
    return inv["client_id"]


# --- VA-of-engagement for task/time-entry -----------------------------------
def va_of_task(task):
    eng_id = task.get("engagement_id")
    if eng_id is None:
        return None
    eng = db.engagements.get(eng_id)
    return eng["va_id"] if eng else None


def va_of_time_entry(te):
    return te.get("va_id")


# --- enforcement ------------------------------------------------------------
def require_client_owner(role, user_id, owning_client_id):
    """For a Client caller, the owning client must be the caller."""
    if role == "Client" and user_id != owning_client_id:
        raise err("ERR_FORBIDDEN", "client does not own this resource")


def require_va_owner(role, user_id, owning_va_id):
    if role == "VA" and user_id != owning_va_id:
        raise err("ERR_FORBIDDEN", "VA does not own this resource")
