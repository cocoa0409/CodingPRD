"""Change control in live space: methods of procedure and their approval trail."""

from flask import Blueprint, g

import db
import validation as v
from constants import (
    APPROVAL_DECISIONS,
    MAX_MOP_REVISIONS,
    MOP_AUTHOR_ROLES,
    MOP_TARGET_TYPES,
    RISK_CLASSES,
    ROLE_CHANGE_MANAGER,
    ROLE_OPERATIONS_MANAGER,
    STAFF_ROLES,
)
from errors import ApiError
from middleware import endpoint
from output import created, filtered, listing, ok, require
from services import calc, cascade

bp = Blueprint("mops", __name__)

READ_ROLES = list(STAFF_ROLES)
AUTHORS = list(MOP_AUTHOR_ROLES)
APPROVERS = [ROLE_CHANGE_MANAGER, ROLE_OPERATIONS_MANAGER]


@bp.post("/mops")
@endpoint(AUTHORS, needs_user_id=True)
def create_mop():
    payload = v.body()
    hall_id = v.fk_field(payload, "hall_id")
    target_type = v.enum_field(payload, "target_resource_type", MOP_TARGET_TYPES)
    target_id = v.fk_field(payload, "target_resource_id")
    title = v.string_field(payload, "title")
    risk_class = v.enum_field(payload, "risk_class", RISK_CLASSES)
    backout_plan = v.string_field(payload, "backout_plan")
    window_start = v.datetime_field(payload, "window_start")
    window_end = v.datetime_field(payload, "window_end")
    v.window_order(window_start, window_end)

    hall = require("halls", hall_id)

    target = db.get(cascade.TARGET_KINDS[target_type], target_id)
    if target is None or target.get("hall_id") != hall["id"]:
        raise ApiError("ERR_MOP_TARGET_NOT_FOUND")

    mop = db.new_row(
        "mops",
        {
            "hall_id": hall["id"],
            "target_resource_type": target_type,
            "target_resource_id": target["id"],
            "title": title,
            "risk_class": risk_class,
            "backout_plan": backout_plan,
            "window_start": window_start,
            "window_end": window_end,
            "status": "DRAFT",
            "author_user_id": g.user_id,
            "revision_count": 0,
            "approval_count": 0,
            "required_approval_count": 0,
            "tenant_notified_ids": [],
            "pre_execution_target_state": None,
            "executed_at": None,
            "closed_at": None,
        },
    )
    return created(mop)


@bp.get("/mops")
@endpoint(READ_ROLES)
def list_mops():
    return listing(
        filtered(
            "mops",
            {
                "hall_id": "hall_id",
                "status": "status",
                "target_resource_id": "target_resource_id",
                "risk_class": "risk_class",
            },
        )
    )


@bp.get("/mops/<mop_id>")
@endpoint(READ_ROLES)
def read_mop(mop_id):
    return ok(require("mops", mop_id))


@bp.post("/mops/<mop_id>/submit")
@endpoint(AUTHORS, needs_user_id=True)
def submit_mop(mop_id):
    mop = require("mops", mop_id)
    if mop["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE")
    if not (mop["backout_plan"] or "").strip():
        raise ApiError("ERR_VALIDATION", "backout_plan must be non-empty at submit.")

    if mop["window_start"] < db.clock_now():
        raise ApiError("ERR_OUTSIDE_EXECUTION_WINDOW")

    hall = db.get("halls", mop["hall_id"])
    if (
        hall["status"] == "LIVE"
        and mop["target_resource_type"] in ("BUSWAY", "COOLING_UNIT")
        and mop["risk_class"] != "HIGH"
    ):
        raise ApiError("ERR_RISK_CLASS_TOO_LOW")

    mop["status"] = "UNDER_REVIEW"
    mop["required_approval_count"] = calc.required_approvals_for(mop["risk_class"])
    db.touch(mop)
    return ok(mop)


@bp.post("/mops/<mop_id>/approvals")
@endpoint(APPROVERS, needs_user_id=True)
def decide_mop(mop_id):
    payload = v.body()
    decision = v.enum_field(payload, "decision", APPROVAL_DECISIONS)
    comment = v.string_field(payload, "comment", required=False)
    mop = require("mops", mop_id)

    if mop["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_STATE")
    if g.user_id == mop["author_user_id"]:
        raise ApiError("ERR_APPROVER_IS_AUTHOR")

    round_votes = calc.round_approvals(mop)
    if decision == "APPROVE":
        if any(a["approver_user_id"] == g.user_id for a in round_votes):
            raise ApiError("ERR_DUPLICATE_APPROVER")
        if mop["risk_class"] == "HIGH" and round_votes:
            if any(a["approver_role"] == g.role for a in round_votes):
                raise ApiError("ERR_APPROVAL_ROLE_NOT_DISTINCT")

    sequence = len(calc.approvals_of(mop)) + 1
    db.new_row(
        "approvals",
        {
            "mop_id": mop["id"],
            "approver_role": g.role,
            "approver_user_id": g.user_id,
            "decision": decision,
            "comment": comment,
            "sequence": sequence,
        },
        versioned=False,
    )

    if decision == "APPROVE":
        mop["approval_count"] = len(calc.round_approvals(mop))
        if mop["approval_count"] >= mop["required_approval_count"]:
            mop["status"] = "APPROVED"
    elif decision == "REQUEST_REVISION":
        mop["status"] = "REVISION_REQUESTED"
        mop["approval_count"] = 0
    else:
        mop["status"] = "REJECTED"
    db.touch(mop)
    return ok(mop)


@bp.get("/mops/<mop_id>/approvals")
@endpoint(READ_ROLES)
def list_approvals(mop_id):
    mop = require("mops", mop_id)
    return listing(db.where("approvals", mop_id=mop["id"]))


@bp.post("/mops/<mop_id>/revise")
@endpoint(AUTHORS, needs_user_id=True)
def revise_mop(mop_id):
    payload = v.body()
    window_start = v.datetime_field(payload, "window_start", required=False)
    window_end = v.datetime_field(payload, "window_end", required=False)
    if window_start is not None and window_end is not None:
        v.window_order(window_start, window_end)
    backout_plan = v.string_field(payload, "backout_plan", required=False)
    risk_class = v.enum_field(payload, "risk_class", RISK_CLASSES, required=False)
    mop = require("mops", mop_id)

    if mop["status"] != "REVISION_REQUESTED":
        raise ApiError("ERR_INVALID_STATE")
    if g.user_id != mop["author_user_id"]:
        raise ApiError("ERR_MOP_EXECUTOR_NOT_AUTHOR")
    if mop["revision_count"] >= MAX_MOP_REVISIONS:
        raise ApiError("ERR_MOP_REVISION_LIMIT_REACHED")

    effective_start = window_start if window_start is not None else mop["window_start"]
    effective_end = window_end if window_end is not None else mop["window_end"]
    v.window_order(effective_start, effective_end)

    mop["window_start"] = effective_start
    mop["window_end"] = effective_end
    if backout_plan is not None:
        mop["backout_plan"] = backout_plan
    if risk_class is not None:
        mop["risk_class"] = risk_class
    mop["revision_count"] = mop["revision_count"] + 1
    mop["status"] = "UNDER_REVIEW"
    mop["required_approval_count"] = calc.required_approvals_for(mop["risk_class"])
    mop["approval_count"] = 0
    db.touch(mop)
    return ok(mop)


@bp.post("/mops/<mop_id>/schedule")
@endpoint([ROLE_CHANGE_MANAGER])
def schedule_mop(mop_id):
    payload = v.body()
    notified = v.id_list_field(payload, "tenant_notified_ids", default=None)
    mop = require("mops", mop_id)

    if mop["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE")

    if calc.mop_window_collision(mop, mop["window_start"], mop["window_end"]):
        raise ApiError("ERR_MOP_WINDOW_CONFLICT")

    hall = db.get("halls", mop["hall_id"])
    supplied = list(notified) if notified is not None else []
    if hall["tenant_mode"] == "MULTI_TENANT" and mop["risk_class"] == "HIGH":
        owners = set(
            c["tenant_id"] for c in db.where("cages", hall_id=hall["id"])
        )
        if not owners.issubset(set(supplied)):
            raise ApiError("ERR_TENANT_NOTIFICATION_INCOMPLETE")

    mop["status"] = "SCHEDULED"
    mop["tenant_notified_ids"] = supplied
    db.touch(mop)
    calc.apply_release_posture(hall)
    return ok(mop)


@bp.post("/mops/<mop_id>/execute")
@endpoint(AUTHORS, needs_user_id=True)
def execute_mop(mop_id):
    mop = require("mops", mop_id)
    if mop["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE")

    now = db.clock_now()
    if now < mop["window_start"] or now >= mop["window_end"]:
        raise ApiError("ERR_OUTSIDE_EXECUTION_WINDOW")

    hall = db.get("halls", mop["hall_id"])
    for peer in db.where("mops", hall_id=hall["id"], status="IN_EXECUTION"):
        if peer["id"] != mop["id"]:
            raise ApiError("ERR_HALL_MOP_ALREADY_EXECUTING")

    if g.user_id != mop["author_user_id"]:
        raise ApiError("ERR_MOP_EXECUTOR_NOT_AUTHOR")

    target = cascade.target_row(mop)
    mop["status"] = "IN_EXECUTION"
    mop["executed_at"] = now
    mop["pre_execution_target_state"] = cascade.target_state(
        target, mop["target_resource_type"]
    )
    db.touch(mop)

    cascade.execute_cascade(mop, hall)
    return ok(mop)


def _finish_mop(mop_id, note_field, terminal_status):
    payload = v.body()
    v.optional_string_or_null(payload, note_field)
    mop = require("mops", mop_id)

    if mop["status"] != "IN_EXECUTION":
        raise ApiError("ERR_INVALID_STATE")
    if g.user_id != mop["author_user_id"]:
        raise ApiError("ERR_MOP_EXECUTOR_NOT_AUTHOR")

    hall = db.get("halls", mop["hall_id"])
    mop["status"] = terminal_status
    mop["closed_at"] = db.clock_now()
    db.touch(mop)

    cascade.restore_cascade(mop, hall)
    return ok(mop)


@bp.post("/mops/<mop_id>/close")
@endpoint(AUTHORS, needs_user_id=True)
def close_mop(mop_id):
    return _finish_mop(mop_id, "closeout_note", "CLOSED")


@bp.post("/mops/<mop_id>/back-out")
@endpoint(AUTHORS, needs_user_id=True)
def back_out_mop(mop_id):
    return _finish_mop(mop_id, "backout_note", "BACKED_OUT")
