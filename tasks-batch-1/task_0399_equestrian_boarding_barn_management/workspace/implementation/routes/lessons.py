"""Lesson routes & resolution branches (PRD §3.7 Lessons, §3.5 lesson cascades)."""
from decimal import Decimal

from flask import Blueprint, request

from db import db
from errors import err
from middleware import get_caller, require_role
from response import success
from clock import parse_iso, format_iso
from datetime import timedelta
from services.common import new_common, touch, require_str, require_int, pct
from services.serialize import view
from services.lookups import get_horse, get_lesson, require_owner_owns

bp = Blueprint("lessons", __name__)

NO_SHOW_PCT = Decimal("0.50")
CANCEL_CUTOFF_HOURS = 24


@bp.route("/lessons", methods=["POST"])
def create_lesson():
    caller = get_caller()
    require_role(caller, ["BarnManager", "Owner"])
    body = request.get_json(silent=True) or {}
    horse_id = require_str(body, "horse_id")
    instructor_name = require_str(body, "instructor_name")
    lesson_fee = require_int(body, "lesson_fee_cents")
    starts_at = require_str(body, "starts_at")
    ends_at = require_str(body, "ends_at")
    horse = get_horse(horse_id)
    require_owner_owns(caller, horse["owner_id"])
    try:
        s = parse_iso(starts_at)
        e = parse_iso(ends_at)
    except ValueError:
        raise err("ERR_INVALID_REQUEST", "starts_at/ends_at must be ISO-8601 UTC")
    # field-shape: ends_at strictly after starts_at (PRD §2.7)
    if not (e > s):
        raise err("ERR_INVALID_REQUEST", "ends_at must be after starts_at")
    lesson = new_common()
    lesson.update({
        "horse_id": horse["id"],
        "instructor_name": instructor_name,
        "lesson_fee_cents": lesson_fee,
        "starts_at": format_iso(s),
        "ends_at": format_iso(e),
        "billed_fee_cents": 0,
        "invoiced": False,
        "status": "SCHEDULED",
    })
    db.lessons[lesson["id"]] = lesson
    return success(view(lesson), 201)


# per-target_status role gating (PRD §2.1, §1.7)
_LESSON_TARGET_ROLES = {
    "COMPLETED": {"Instructor"},
    "NO_SHOW": {"Instructor"},
    "CANCELLED": {"BarnManager", "Owner", "Instructor"},
}


@bp.route("/lessons/<lesson_id>/transition", methods=["POST"])
def transition_lesson(lesson_id):
    caller = get_caller()
    # endpoint-level role gate (any of the three) first, then per-target gate
    require_role(caller, ["BarnManager", "Owner", "Instructor"])
    lesson = get_lesson(lesson_id)
    body = request.get_json(silent=True) or {}
    target = body.get("target_status")
    if target not in _LESSON_TARGET_ROLES:
        raise err("ERR_INVALID_STATE", "Unknown or illegal target_status")
    # per-target_status role gating (ERR_FORBIDDEN_ROLE)
    if caller.role not in _LESSON_TARGET_ROLES[target]:
        raise err("ERR_FORBIDDEN_ROLE", "Role %s not permitted for target %s" % (caller.role, target))
    # ownership: Owner may only act on own resource (only CANCELLED is owner-permitted)
    horse = db.horses.get(lesson["horse_id"])
    require_owner_owns(caller, horse["owner_id"] if horse else None)

    if target == "COMPLETED":
        return _complete(lesson)
    if target == "NO_SHOW":
        return _no_show(lesson)
    return _cancel(lesson)


def _boarding_active_for_horse(horse_id):
    for a in db.agreements.values():
        if a["horse_id"] == horse_id and a["status"] == "ACTIVE":
            return True
    return False


def _complete(lesson):
    if lesson["status"] != "SCHEDULED":
        raise err("ERR_INVALID_STATE", "Lesson is not SCHEDULED")
    if not _boarding_active_for_horse(lesson["horse_id"]):
        raise err("ERR_BOARDING_NOT_ACTIVE", "Horse boarding agreement is not ACTIVE")
    lesson["billed_fee_cents"] = lesson["lesson_fee_cents"]
    lesson["status"] = "COMPLETED"
    touch(lesson)
    return success(view(lesson), 200)


def _no_show(lesson):
    if lesson["status"] != "SCHEDULED":
        raise err("ERR_INVALID_STATE", "Lesson is not SCHEDULED")
    lesson["billed_fee_cents"] = pct(lesson["lesson_fee_cents"], NO_SHOW_PCT)
    lesson["status"] = "NO_SHOW"
    touch(lesson)
    return success(view(lesson), 200)


def _cancel(lesson):
    if lesson["status"] != "SCHEDULED":
        raise err("ERR_INVALID_STATE", "Lesson is not SCHEDULED")
    now = db.clock.now
    starts = parse_iso(lesson["starts_at"])
    cutoff = starts - timedelta(hours=CANCEL_CUTOFF_HOURS)
    # inclusive boundary: now <= starts - CANCEL_CUTOFF_HOURS allowed (PRD §3.7)
    if now > cutoff:
        raise err("ERR_CANCEL_TOO_LATE", "Cancellation later than cutoff before start")
    lesson["billed_fee_cents"] = 0
    lesson["status"] = "CANCELLED"
    touch(lesson)
    return success(view(lesson), 200)
