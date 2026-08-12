"""Term lifecycle routes (SCAFFOLD 1.5: terms block)."""

from flask import Blueprint, request

import db
import domain
import engine
import serializers as ser
from auth import require_role, body
from envelope import success_object, success_list, paginate
from errors import (ApiError, invalid_posture, invalid_request, not_found,
                    ERR_PUBLISH_BLOCKED, ERR_CLOSE_WINDOW_BLOCKED)
from validate import (new_record, touch, req_field, as_str, as_int, opt_int,
                      occ_early, occ_required, get_or_404)

bp = Blueprint("terms", __name__)


def _get_term(tid):
    return get_or_404(db.terms, tid)


@bp.post("/scheduling/terms")
def create_term():
    require_role("Administrator")
    data = body()
    code = as_str(req_field(data, "code"), "code")
    ppd = as_int(req_field(data, "periods_per_day"), "periods_per_day")
    if not 4 <= ppd <= 10:
        raise invalid_request("periods_per_day must be between 4 and 10")
    cap = as_int(req_field(data, "max_students_per_section"),
                 "max_students_per_section")
    if not 1 <= cap <= 40:
        raise invalid_request("max_students_per_section must be between 1 and 40")
    target = as_int(req_field(data, "class_size_target"), "class_size_target")
    if not 1 <= target < cap:
        raise invalid_request("class_size_target must be >= 1 and < "
                              "max_students_per_section")
    ssc = opt_int(data, "singleton_section_cap", 2)
    if not 0 <= ssc <= ppd:
        raise invalid_request("singleton_section_cap must be between 0 and "
                              "periods_per_day")
    crm = opt_int(data, "change_request_max_per_student", 3)
    if crm < 1:
        raise invalid_request("change_request_max_per_student must be >= 1")
    if any(t["code"] == code for t in db.terms.values()):
        raise invalid_request("code must be unique")
    t = new_record()
    t.update({
        "code": code, "posture": "COLLECTING", "periods_per_day": ppd,
        "max_students_per_section": cap, "class_size_target": target,
        "singleton_section_cap": ssc, "change_request_max_per_student": crm,
        "rebalance_epoch": 0,
    })
    db.terms[t["id"]] = t
    return success_object(ser.term(t), 201)


@bp.get("/scheduling/terms")
def list_terms():
    require_role("Administrator", "Counselor", "Student")
    rows = list(db.terms.values())
    posture = request.args.get("posture")
    if posture is not None:
        rows = [t for t in rows if t["posture"] == posture]
    page, limit, offset, total = paginate(rows, request.args)
    return success_list([ser.term(t) for t in page], limit, offset, total)


@bp.get("/scheduling/terms/<tid>")
def get_term(tid):
    require_role("Administrator", "Counselor", "Student")
    return success_object(ser.term(_get_term(tid)))


@bp.post("/scheduling/terms/<tid>/close-collection")
def close_collection(tid):
    require_role("Administrator")
    t = _get_term(tid)
    if t["posture"] != "COLLECTING":
        raise invalid_posture()
    for r in db.course_requests.values():
        if r["term_id"] == t["id"] and r["state"] == "DRAFT":
            r["state"] = "WITHDRAWN"
            touch(r)
    t["posture"] = "TALLYING"
    t["version"] += 1
    touch(t)
    return success_object(ser.term(t))


@bp.post("/scheduling/terms/<tid>/generate-sections")
def generate_sections(tid):
    require_role("Administrator")
    t = _get_term(tid)
    if t["posture"] != "TALLYING":
        raise invalid_posture()
    for row in domain.tally_rows(t, optimistic=False):
        course = row["_course"]
        existing = [s for s in db.sections.values()
                    if s["term_id"] == t["id"] and s["course_id"] == course["id"]
                    and s["state"] != "CANCELLED"]
        if existing:
            continue
        for _ in range(row["projected_sections"]):
            s = new_record()
            s.update({"term_id": t["id"], "course_id": course["id"],
                      "teacher_id": None, "room_id": None, "period": None,
                      "capacity": None, "state": "DRAFT"})
            db.sections[s["id"]] = s
    for r in db.course_requests.values():
        if r["term_id"] == t["id"] and r["state"] == "SUBMITTED":
            r["state"] = "LOCKED"
            touch(r)
    t["posture"] = "BUILDING"
    t["version"] += 1
    touch(t)
    return success_object(ser.term(t))


@bp.post("/scheduling/terms/<tid>/publish")
def publish(tid):
    require_role("Administrator")
    t = _get_term(tid)
    if t["posture"] != "BUILDING":
        raise invalid_posture()
    active = [s for s in db.sections.values()
              if s["term_id"] == t["id"] and s["state"] != "CANCELLED"]
    # Publish precondition: no DRAFT sections, no grid conflicts.
    if any(s["state"] == "DRAFT" for s in active):
        raise ApiError(ERR_PUBLISH_BLOCKED, 409,
                       "Unscheduled DRAFT sections remain in the term")
    seen_tp, seen_rp = set(), set()
    for s in active:
        tp = (s["teacher_id"], s["period"])
        rp = (s["room_id"], s["period"])
        if tp in seen_tp or rp in seen_rp:
            raise ApiError(ERR_PUBLISH_BLOCKED, 409,
                           "Grid conflicts exist among non-CANCELLED sections")
        seen_tp.add(tp)
        seen_rp.add(rp)
    for s in active:
        if s["state"] == "SCHEDULED":
            s["state"] = "PUBLISHED"
            touch(s)
    t["posture"] = "PUBLISHED"
    engine.run_auto_placement(t)
    t["version"] += 1
    touch(t)
    return success_object(ser.term(t))


@bp.post("/scheduling/terms/<tid>/open-change-window")
def open_change_window(tid):
    require_role("Administrator")
    t = _get_term(tid)
    if t["posture"] != "PUBLISHED":
        raise invalid_posture()
    t["posture"] = "CHANGE_WINDOW"
    t["version"] += 1
    touch(t)
    return success_object(ser.term(t))


@bp.post("/scheduling/terms/<tid>/close-change-window")
def close_change_window(tid):
    require_role("Administrator")
    t = _get_term(tid)
    if t["posture"] != "CHANGE_WINDOW":
        raise invalid_posture()
    in_flight = [r for r in db.change_requests.values()
                 if r["term_id"] == t["id"] and r["state"] in
                 ("SUBMITTED", "COUNSELOR_REVIEW", "REVISED", "APPROVED")]
    if in_flight:
        raise ApiError(ERR_CLOSE_WINDOW_BLOCKED, 409,
                       "In-flight change requests remain in the term")
    for r in db.change_requests.values():
        if (r["term_id"] == t["id"] and r["state"] in
                ("SUBMITTED", "COUNSELOR_REVIEW", "REVISED")):
            r["state"] = "CANCELLED"
            touch(r)
    for p in db.recovery_placements.values():
        if p["term_id"] == t["id"] and p["state"] == "PENDING":
            p["state"] = "EXPIRED"
            touch(p)
    t["posture"] = "LOCKED"
    t["version"] += 1
    touch(t)
    return success_object(ser.term(t))


@bp.get("/scheduling/terms/<tid>/tally-preview")
def tally_preview(tid):
    require_role("Administrator", "Counselor")
    t = _get_term(tid)
    if t["posture"] != "COLLECTING":
        raise invalid_posture()
    rows = [{"course_id": r["course_id"], "course_code": r["course_code"],
             "demand": r["demand"], "projected_sections": r["projected_sections"]}
            for r in domain.tally_rows(t, optimistic=True)]
    return success_object({"rows": rows})


@bp.post("/scheduling/terms/<tid>/rebalance-runs")
def create_rebalance_run(tid):
    require_role("Administrator")
    t = _get_term(tid)
    data = body()
    occ_early(data, t)
    if t["posture"] != "LOCKED":
        raise invalid_posture()
    occ_required(data)
    run = engine.run_rebalance(t)
    t["version"] += 1
    touch(t)
    return success_object(ser.rebalance_run(run), 201)


@bp.get("/scheduling/terms/<tid>/rebalance-runs")
def list_rebalance_runs(tid):
    require_role("Administrator", "Counselor")
    t = _get_term(tid)
    rows = [r for r in db.rebalance_runs.values() if r["term_id"] == t["id"]]
    page, limit, offset, total = paginate(rows, request.args)
    return success_list([ser.rebalance_run(r) for r in page], limit, offset, total)
