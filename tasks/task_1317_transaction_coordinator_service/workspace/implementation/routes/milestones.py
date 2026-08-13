"""Milestones."""
from flask import Blueprint, request

import errors as E
import middleware as mw
from db import store, touch, pub, pub_list, fmt_dt
from response import ok_object, ok_list

bp = Blueprint("milestones", __name__)


@bp.get("/tc/milestones/<milestoneId>")
def get_milestone(milestoneId):
    mw.auth()
    rec = mw.get_or_404("milestone", milestoneId)
    return ok_object(pub("milestone", rec))


@bp.get("/tc/milestones")
def list_milestones():
    mw.auth()
    limit, offset = mw.page_params()
    recs = list(store.milestones.values())
    recs = mw.filter_eq(recs, "file_id", request.args.get("file_id"))
    recs = mw.filter_eq(recs, "status", request.args.get("status"))
    recs = mw.filter_eq(recs, "name", request.args.get("name"))
    page, total = mw.apply_page(recs, limit, offset)
    return ok_list(pub_list("milestone", page), limit, offset, total)


@bp.post("/tc/milestones/<milestoneId>/start")
def start_milestone(milestoneId):
    uid, role = mw.auth()
    mw.require_roles(role, {"Coordinator"})
    rec = mw.get_or_404("milestone", milestoneId)
    file_rec = mw.own_file_chain(uid, rec, "milestone")
    if rec["status"] != "PENDING":
        E.raise_err(E.ERR_MILESTONE_INVALID_STATE, "Only a PENDING milestone can be started")
    if file_rec is None or file_rec["status"] != "ACTIVE":
        E.raise_err(E.ERR_FILE_NOT_ACTIVE, "Owning file must be ACTIVE")
    rec["status"] = "IN_PROGRESS"
    touch(rec)
    return ok_object(pub("milestone", rec))


@bp.post("/tc/milestones/<milestoneId>/complete")
def complete_milestone(milestoneId):
    uid, role = mw.auth()
    mw.require_roles(role, {"Coordinator"})
    rec = mw.get_or_404("milestone", milestoneId)
    mw.own_file_chain(uid, rec, "milestone")
    if rec["status"] not in ("IN_PROGRESS", "OVERDUE"):
        E.raise_err(E.ERR_MILESTONE_INVALID_STATE,
                    "Only an IN_PROGRESS or OVERDUE milestone can be completed")
    rec["late_completion"] = rec["status"] == "OVERDUE"
    rec["status"] = "COMPLETED"
    rec["completed_at"] = fmt_dt(store.now)
    touch(rec)
    return ok_object(pub("milestone", rec))


@bp.post("/tc/milestones/<milestoneId>/waive")
def waive_milestone(milestoneId):
    uid, role = mw.auth()
    mw.require_roles(role, {"Coordinator"})
    rec = mw.get_or_404("milestone", milestoneId)
    mw.own_file_chain(uid, rec, "milestone")
    if rec["status"] not in ("PENDING", "IN_PROGRESS", "OVERDUE"):
        E.raise_err(E.ERR_MILESTONE_INVALID_STATE,
                    "Milestone is not in a waivable state")
    if rec["mandatory"]:
        E.raise_err(E.ERR_MILESTONE_MANDATORY, "A mandatory milestone cannot be waived")
    rec["status"] = "WAIVED"
    touch(rec)
    return ok_object(pub("milestone", rec))
