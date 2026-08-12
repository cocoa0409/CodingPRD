"""Caregivers and escalation contact-tree entries."""
from flask import Blueprint, request

import db
import errors
from middleware import (require_roles, get_body, req_str, req_int, req_enum,
                        opt_int, opt_enum, caller_senior_scope, SEVERITIES)
from response import ok, list_ok
from services import create_record, touch, ser, current_subscription

bp = Blueprint("care", __name__)


# ------------------------------------------------------------ caregivers ---

@bp.post("/v1/caregivers")
def create_caregiver():
    require_roles(["PlatformAdmin"])
    b = get_body()
    senior_id = req_str(b, "senior_id")
    if senior_id not in db.seniors:
        raise errors.not_found("Senior not found")
    rec = create_record(db.caregivers, {
        "senior_id": senior_id,
        "full_name": req_str(b, "full_name"),
        "phone": req_str(b, "phone"),
    })
    return ok(ser(rec), 201)


@bp.get("/v1/caregivers/<caregiver_id>")
def get_caregiver(caregiver_id):
    role, uid = require_roles(["PlatformAdmin", "MonitoringAgent", "Caregiver"])
    c = db.caregivers.get(caregiver_id)
    if c is None:
        raise errors.not_found("Caregiver not found")
    if role == "Caregiver":
        if caller_senior_scope(role, uid) != c["senior_id"]:
            raise errors.ownership()
    return ok(ser(c))


@bp.get("/v1/caregivers")
def list_caregivers():
    require_roles(["PlatformAdmin", "MonitoringAgent"])
    recs = list(db.caregivers.values())
    sid = request.args.get("senior_id")
    if sid is not None:
        recs = [r for r in recs if r["senior_id"] == sid]
    return list_ok(recs, ser)


# -------------------------------------------------------- contact tree -----

def _active_entries(senior_id, exclude_id=None):
    return [e for e in db.contacts.values()
            if e["senior_id"] == senior_id and e["status"] == "ACTIVE"
            and (exclude_id is None or e["id"] != exclude_id)]


@bp.post("/v1/contact-tree-entries")
def create_entry():
    require_roles(["PlatformAdmin"])
    b = get_body()
    senior_id = req_str(b, "senior_id")
    caregiver_id = req_str(b, "caregiver_id")
    priority_rank = req_int(b, "priority_rank")
    min_severity = req_enum(b, "min_severity", SEVERITIES)
    timeout = req_int(b, "response_timeout_seconds")
    if senior_id not in db.seniors:
        raise errors.not_found("Senior not found")
    caregiver = db.caregivers.get(caregiver_id)
    if caregiver is None:
        raise errors.not_found("Caregiver not found")
    # pinned order: rank uniqueness -> caregiver/senior match -> plan limit
    if any(e["priority_rank"] == priority_rank for e in _active_entries(senior_id)):
        raise errors.rank_conflict()
    if caregiver["senior_id"] != senior_id:
        raise errors.caregiver_senior_mismatch()
    sub = current_subscription(senior_id)
    plan = db.plans.get(sub["plan_id"]) if sub else None
    if plan is not None and len(_active_entries(senior_id)) >= plan["max_contacts"]:
        raise errors.contact_limit()
    rec = create_record(db.contacts, {
        "senior_id": senior_id,
        "caregiver_id": caregiver_id,
        "priority_rank": priority_rank,
        "min_severity": min_severity,
        "response_timeout_seconds": timeout,
        "status": "ACTIVE",
    })
    return ok(ser(rec), 201)


def _get_entry(entry_id):
    e = db.contacts.get(entry_id)
    if e is None:
        raise errors.not_found("Contact-tree entry not found")
    return e


@bp.get("/v1/contact-tree-entries/<entry_id>")
def get_entry(entry_id):
    require_roles(["PlatformAdmin", "MonitoringAgent"])
    return ok(ser(_get_entry(entry_id)))


@bp.get("/v1/contact-tree-entries")
def list_entries():
    require_roles(["PlatformAdmin", "MonitoringAgent"])
    recs = list(db.contacts.values())
    sid = request.args.get("senior_id")
    if sid is not None:
        recs = [r for r in recs if r["senior_id"] == sid]
    cid = request.args.get("caregiver_id")
    if cid is not None:
        recs = [r for r in recs if r["caregiver_id"] == cid]
    return list_ok(recs, ser)


@bp.patch("/v1/contact-tree-entries/<entry_id>")
def update_entry(entry_id):
    require_roles(["PlatformAdmin"])
    e = _get_entry(entry_id)
    b = get_body()
    new_rank = opt_int(b, "priority_rank", None)
    new_sev = opt_enum(b, "min_severity", SEVERITIES, None)
    new_timeout = opt_int(b, "response_timeout_seconds", None)
    if new_rank is not None and new_rank != e["priority_rank"]:
        if any(x["priority_rank"] == new_rank
               for x in _active_entries(e["senior_id"], exclude_id=e["id"])):
            raise errors.rank_conflict()
    if new_rank is not None:
        e["priority_rank"] = new_rank
    if new_sev is not None:
        e["min_severity"] = new_sev
    if new_timeout is not None:
        e["response_timeout_seconds"] = new_timeout
    touch(e)
    return ok(ser(e))


@bp.delete("/v1/contact-tree-entries/<entry_id>")
def delete_entry(entry_id):
    require_roles(["PlatformAdmin"])
    e = _get_entry(entry_id)
    e["status"] = "REMOVED"
    touch(e)
    return ok(ser(e))
