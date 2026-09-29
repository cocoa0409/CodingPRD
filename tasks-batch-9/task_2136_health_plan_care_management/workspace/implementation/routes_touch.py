"""Outreach touches: scheduling, cancellation and the six-step completion."""
from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, request

import core
import domain
import http_util as h
import serializers as S
from core import clock, db, rhu
from errors import ApiError

bp = Blueprint("touch", __name__)

ALL_READ = ["ProgramAdmin", "CareManager", "ClinicalReviewer", "UtilizationAnalyst"]

BUFFER = timedelta(minutes=core.DOCUMENTATION_BUFFER_MINUTES)


@bp.post("/touches")
def create_touch():
    user_id, role = h.authenticate(["CareManager", "ProgramAdmin"])
    data = h.body()
    enrollment_id = h.req_str(data, "enrollment_id")
    care_manager_id = h.req_str(data, "care_manager_id")
    touch_type = h.req_enum(data, "touch_type", core.TOUCH_TYPES)
    modality = h.req_enum(data, "modality", core.TOUCH_MODALITIES)
    start_at = h.req_instant(data, "scheduled_start_at")
    end_at = h.req_instant(data, "scheduled_end_at")

    # ladder step 6 - body references, in input order
    enrollment = domain.get_enrollment(enrollment_id)
    manager = domain.get_care_manager(care_manager_id)

    # ladder step 7 - ownership
    if role == "CareManager" and user_id != manager["id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")

    # ladder step 11 - cross-entity gate: the enrollment needs an ACTIVE plan
    if domain.active_plan(enrollment["id"]) is None:
        raise ApiError("ERR_CARE_PLAN_NOT_ACTIVE")

    # ladder step 12 - credential authorisation
    program = domain.program_of_enrollment(enrollment)
    if program is None or manager["credential_level"] not in program["required_credential_levels"]:
        raise ApiError("ERR_CREDENTIAL_NOT_AUTHORIZED")

    # ladder step 13 - temporal rules
    if not end_at > start_at:
        raise ApiError("ERR_TOUCH_WINDOW_INVALID")
    if start_at < clock.now():
        raise ApiError("ERR_TOUCH_WINDOW_IN_PAST")

    # ladder step 15 - care-manager calendar conflict (buffered candidate)
    cand_lo = start_at - BUFFER
    cand_hi = end_at + BUFFER
    for existing in db.touches.values():
        if existing["care_manager_id"] != manager["id"]:
            continue
        if existing["status"] != "SCHEDULED":
            continue
        if cand_lo < existing["scheduled_end_at"] and existing["scheduled_start_at"] < cand_hi:
            raise ApiError("ERR_CARE_MANAGER_SLOT_CONFLICT")

    # ladder step 16 - care manager capacity posture
    if manager["capacity_status"] != "OPEN":
        raise ApiError("ERR_CARE_MANAGER_OVER_CAPACITY")

    rec = domain.base_record()
    rec.update({
        "enrollment_id": enrollment["id"],
        "care_manager_id": manager["id"],
        "touch_type": touch_type,
        "modality": modality,
        "scheduled_start_at": start_at,
        "scheduled_end_at": end_at,
        "status": "SCHEDULED",
        "outcome": None,
        "documentation_note": None,
        "completed_at": None,
        "cancel_reason": None,
        "satisfied_toc_obligation": False,
    })
    db.touches[rec["id"]] = rec
    return h.ok(S.touch_out(rec), 201)


@bp.get("/touches/<touch_id>")
def read_touch(touch_id):
    h.authenticate(ALL_READ)
    rec = domain.get_touch(touch_id)
    return h.ok(S.touch_out(rec))


@bp.get("/touches")
def list_touches():
    h.authenticate(ALL_READ)
    limit, offset = h.pagination()
    rows = list(db.touches.values())
    for field in ("enrollment_id", "care_manager_id", "status", "touch_type"):
        value = request.args.get(field)
        if value is not None:
            rows = [r for r in rows if r[field] == value]
    rows = domain.sorted_rows(rows)
    page, total = h.paginate(rows, limit, offset)
    return h.ok_list([S.touch_out(r) for r in page], limit, offset, total)


@bp.post("/touches/<touch_id>/cancel")
def cancel_touch(touch_id):
    user_id, role = h.authenticate(["CareManager", "ProgramAdmin"])
    data = h.body()
    cancel_reason = h.req_str(data, "cancel_reason")
    touch = domain.get_touch(touch_id)
    if role == "CareManager" and user_id != touch["care_manager_id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")
    if touch["status"] != "SCHEDULED":
        raise ApiError("ERR_TOUCH_NOT_SCHEDULED")
    touch["status"] = "CANCELLED"
    touch["cancel_reason"] = cancel_reason
    domain.touch_record(touch)
    return h.ok(S.touch_out(touch))


def _engagement_score(enrollment, now):
    window_start = now - timedelta(days=core.ENGAGEMENT_WINDOW_DAYS)
    interval = core.CADENCE_INTERVAL_DAYS[enrollment["cadence_tier_snapshot"]]
    expected = max(1, core.ENGAGEMENT_WINDOW_DAYS // interval)
    achieved = 0
    for t in db.touches.values():
        if t["enrollment_id"] != enrollment["id"]:
            continue
        if t["status"] != "COMPLETED" or t["outcome"] != "REACHED":
            continue
        completed_at = t.get("completed_at")
        if completed_at is None:
            continue
        if window_start < completed_at <= now:
            achieved += 1
    score = rhu(Decimal(100) * Decimal(achieved) / Decimal(expected), 0)
    return min(100, int(score))


@bp.post("/touches/<touch_id>/complete")
def complete_touch(touch_id):
    user_id, _role = h.authenticate(["CareManager"])
    data = h.body()
    outcome = h.req_enum(data, "outcome", core.TOUCH_OUTCOMES)
    note = h.opt_str(data, "documentation_note", allow_empty=True)

    touch = domain.get_touch(touch_id)
    # ladder step 7 - ownership
    if user_id != touch["care_manager_id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")
    # ladder step 9 - source state
    if touch["status"] != "SCHEDULED":
        raise ApiError("ERR_TOUCH_NOT_SCHEDULED")
    # ladder step 12 - documentation
    if outcome == "REACHED" and (note is None or not note.strip()):
        raise ApiError("ERR_DOCUMENTATION_REQUIRED")
    now = clock.now()
    # ladder step 13 - touch readiness
    if touch["scheduled_start_at"] > now:
        raise ApiError("ERR_TOUCH_NOT_YET_DUE")

    enrollment = db.enrollments.get(touch["enrollment_id"])

    # ---- step 1: record the touch -------------------------------------
    touch["status"] = "COMPLETED"
    touch["completed_at"] = now
    touch["outcome"] = outcome
    touch["documentation_note"] = note

    if enrollment is None:
        domain.touch_record(touch)
        return h.ok(S.touch_out(touch))

    # ---- step 2: move the outreach counters ---------------------------
    if outcome == "REACHED":
        enrollment["last_reached_touch_at"] = touch["completed_at"]
        enrollment["consecutive_failed_outreach_count"] = 0
        enrollment["reached_touch_count"] += 1
        toc_due = enrollment.get("toc_due_at")
        if (touch["touch_type"] == "TOC" and toc_due is not None
                and touch["completed_at"] <= toc_due):
            touch["satisfied_toc_obligation"] = True
            domain.toc_satisfy(enrollment)
    else:
        enrollment["consecutive_failed_outreach_count"] += 1

    # ---- step 3: recompute the engagement score -----------------------
    enrollment["engagement_score"] = _engagement_score(enrollment, now)

    # ---- step 4: settle the engagement dimension ----------------------
    previous_engagement = enrollment["engagement_status"]
    if enrollment["consecutive_failed_outreach_count"] >= core.DISENGAGE_FAILED_TOUCH_THRESHOLD:
        new_engagement = "DISENGAGED"
    elif enrollment["reached_touch_count"] == 0:
        new_engagement = "UNREACHED"
    elif enrollment["engagement_score"] >= core.ENGAGED_SCORE_MIN:
        new_engagement = "ENGAGED"
    else:
        new_engagement = "AT_RISK"
    enrollment["engagement_status"] = new_engagement

    if new_engagement == "DISENGAGED" and previous_engagement != "DISENGAGED":
        domain.suspend_plan(enrollment["id"])
    elif previous_engagement == "DISENGAGED" and new_engagement != "DISENGAGED":
        domain.resume_plan(enrollment["id"])

    # ---- step 5: reassign the cadence tier ----------------------------
    domain.apply_cadence_change(enrollment, domain.cadence_tier_for(enrollment))

    # ---- step 6: project the next contact deadline --------------------
    enrollment["next_touch_due_at"] = domain.project_next_touch_due_at(enrollment)

    domain.touch_record(touch)
    domain.touch_record(enrollment)
    return h.ok(S.touch_out(touch))
