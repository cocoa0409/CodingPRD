"""Testing and commissioning notice endpoints (PRD 3.5)."""
from flask import Blueprint

import calc
import lookup
from db import by_policy, by_project, new_row, ordered, store, touch
from enums import DECISIONS_APPROVE_REJECT, SYSTEM_TYPES
from errors import ApiError
from middleware import authenticate, body, get_bool, get_dt, get_enum, get_str
from response import created, ok

bp = Blueprint("notices", __name__)


@bp.post("/testing-notices")
def schedule_notice():
    user_id, role = authenticate("ProjectContact", "RiskEngineer")
    payload = body()
    project = lookup.fk_project(payload)
    if role == "ProjectContact" and project["id"] != user_id:
        raise ApiError(
            "ERR_NOT_RESOURCE_OWNER",
            "A ProjectContact may only schedule notices on its own project.",
        )
    system_type = get_enum(payload, "system_type", SYSTEM_TYPES)
    window_start = get_dt(payload, "window_start")
    window_end = get_dt(payload, "window_end")
    hot_work = get_bool(payload, "hot_work", required=False, default=False)
    water_charged = get_bool(payload, "water_charged", required=False, default=False)
    mitigation_plan_ref = get_str(payload, "mitigation_plan_ref", required=False, default=None)
    if window_end <= window_start:
        raise ApiError("ERR_DATE_RANGE_INVALID", "window_end must be later than window_start.")
    if (hot_work or water_charged) and project["engineering_grade"] in ("C", "D") \
            and mitigation_plan_ref is None:
        raise ApiError(
            "ERR_MITIGATION_PLAN_REQUIRED",
            "A C- or D-graded site needs a mitigation_plan_ref for this activity.",
        )
    if calc.testing_window_conflict(project["id"], hot_work, window_start, window_end):
        raise ApiError(
            "ERR_TESTING_WINDOW_CONFLICT",
            "The window collides with another live notice on this project.",
        )
    row = new_row()
    row.update({
        "project_id": project["id"],
        "system_type": system_type,
        "window_start": window_start,
        "window_end": window_end,
        "hot_work": hot_work,
        "water_charged": water_charged,
        "mitigation_plan_ref": mitigation_plan_ref,
        "status": "SCHEDULED",
        "decided_by_user_id": None,
        "rejection_reason": None,
    })
    store.notices[row["id"]] = row
    return created(row)


@bp.post("/testing-notices/<notice_id>/decision")
def decide_notice(notice_id):
    user_id, _role = authenticate("RiskEngineer")
    notice = lookup.notice(notice_id)
    payload = body()
    decision = get_enum(payload, "decision", DECISIONS_APPROVE_REJECT)
    rejection_reason = get_str(payload, "rejection_reason", required=False, default=None)
    if notice["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_NOTICE_STATE", "Only a SCHEDULED notice may be dispositioned.")
    if decision == "APPROVE":
        if notice["water_charged"] and notice["mitigation_plan_ref"] is None:
            in_force = next(
                (row for row in ordered(by_project(store.policies, notice["project_id"]))
                 if row["status"] == "IN_FORCE"), None
            )
            if in_force is not None:
                for part in by_policy(store.coverage_parts, in_force["id"]):
                    if part["part_type"] == "WATER_DAMAGE" \
                            and part["condition_code"] == "MITIGATION_PLAN_REQUIRED":
                        raise ApiError(
                            "ERR_MITIGATION_PLAN_REQUIRED",
                            "The policy's WATER_DAMAGE part requires a mitigation plan.",
                        )
        notice["status"] = "APPROVED"
    else:
        notice["status"] = "REJECTED"
        notice["rejection_reason"] = rejection_reason
    notice["decided_by_user_id"] = user_id
    touch(notice)
    return ok(notice)


@bp.get("/testing-notices/<notice_id>")
def read_notice(notice_id):
    user_id, role = authenticate(
        "Underwriter", "UnderwritingManager", "RiskEngineer", "ClaimAdjuster", "ProjectContact"
    )
    notice = lookup.notice(notice_id)
    if role == "ProjectContact" and notice["project_id"] != user_id:
        raise ApiError(
            "ERR_NOT_RESOURCE_OWNER", "A ProjectContact may only read notices of its own project."
        )
    return ok(notice)
