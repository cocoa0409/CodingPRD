"""Dues schedules + increase notices routes."""
from flask import Blueprint, request

import db
import errors
import middleware
from response import success
from services import lifecycle

bp = Blueprint("schedules", __name__)


def _body():
    return request.get_json(silent=True) or {}


def _overlaps(a_from, a_to, b_from, b_to):
    # [from, to) interval overlap; None to = +inf
    a_to = a_to or db.parse_dt("9999-12-31T00:00:00Z")
    b_to = b_to or db.parse_dt("9999-12-31T00:00:00Z")
    return a_from < b_to and b_from < a_to


def _check_overlap(candidate, exclude_id=None):
    ef = db.parse_dt(candidate["effective_from"])
    et = db.parse_dt(candidate["effective_to"]) if candidate.get("effective_to") else None
    for s in db.dues_schedules.values():
        if s["id"] == exclude_id:
            continue
        if s["category_id"] != candidate["category_id"]:
            continue
        if s["status"] != "PUBLISHED":
            continue
        sf = db.parse_dt(s["effective_from"])
        st = db.parse_dt(s["effective_to"]) if s.get("effective_to") else None
        if not _overlaps(ef, et, sf, st):
            continue
        # Supersession (PRD §3.2): a prior PUBLISHED schedule that is open-ended
        # (effective_to IS NULL) and starts before the new schedule is superseded
        # by the new publication — it does not block the publish. Overlap with a
        # bounded prior, or with a prior whose effective_from is not strictly
        # earlier, cannot be resolved by supersession and is rejected.
        if s.get("effective_to") is None and sf < ef:
            continue
        raise errors.ApiError(errors.ERR_SCHEDULE_OVERLAP,
                              "Schedule interval overlaps existing PUBLISHED schedule", 409)


@bp.post("/api/dues-schedules")
def create_schedule():
    middleware.require_roles("DuesAdministrator")
    b = _body()
    cat = db.membership_categories.get(b.get("category_id"))
    if not cat:
        raise errors.not_found()
    s = lifecycle.new_entity({
        "category_id": b.get("category_id"),
        "effective_from": db.iso(db.parse_dt(b.get("effective_from"))) if b.get("effective_from") else None,
        "effective_to": db.iso(db.parse_dt(b.get("effective_to"))) if b.get("effective_to") else None,
        "annual_amount_cents": int(b.get("annual_amount_cents", 0)),
        "chapter_share_bps": int(b.get("chapter_share_bps", 0)),
        "increase_notice_days": int(b.get("increase_notice_days", 0)),
        "status": "DRAFT",
    })
    db.dues_schedules[s["id"]] = s
    return success(lifecycle.schedule_out(s), status=201)


@bp.get("/api/dues-schedules/<sid>")
def get_schedule(sid):
    middleware.require_roles("DuesAdministrator", "MembershipAdministrator")
    s = db.dues_schedules.get(sid)
    if not s:
        raise errors.not_found()
    return success(lifecycle.schedule_out(s))


@bp.get("/api/membership-categories/<cid>/dues-schedules")
def list_schedules_for_category(cid):
    middleware.require_roles("DuesAdministrator", "MembershipAdministrator")
    if cid not in db.membership_categories:
        raise errors.not_found()
    rows = [s for s in db.dues_schedules.values() if s["category_id"] == cid]
    rows.sort(key=lambda s: s["created_at"])
    return success([lifecycle.schedule_out(s) for s in rows], response_type="array",
                   pagination={"limit": len(rows) or 10, "offset": 0,
                               "total_count": len(rows), "has_more": False})


@bp.post("/api/dues-schedules/<sid>/publish")
def publish_schedule(sid):
    middleware.require_roles("DuesAdministrator")
    s = db.dues_schedules.get(sid)
    if not s:
        raise errors.not_found()
    if s["status"] != "DRAFT":
        raise errors.invalid_state("Schedule is not in DRAFT")
    # overlap check
    _check_overlap(s, exclude_id=s["id"])
    # increase-notice gap
    prior = None
    for other in db.dues_schedules.values():
        if other["id"] == s["id"] or other["category_id"] != s["category_id"]:
            continue
        if other["status"] != "PUBLISHED":
            continue
        if prior is None or db.parse_dt(other["effective_from"]) > db.parse_dt(prior["effective_from"]):
            prior = other
    if prior and int(s["annual_amount_cents"]) > int(prior["annual_amount_cents"]):
        # need a notice for the new schedule with sufficient gap
        notice = None
        for n in db.dues_increase_notices.values():
            if n["schedule_id"] == s["id"]:
                if notice is None or n["noticed_at"] > notice["noticed_at"]:
                    notice = n
        gap_ok = False
        if notice is not None:
            gap = (db.parse_dt(s["effective_from"]) - db.parse_dt(notice["noticed_at"])).days
            if gap >= int(s["increase_notice_days"]):
                gap_ok = True
        if not gap_ok:
            raise errors.ApiError(errors.ERR_INCREASE_NOTICE_GAP,
                                  "Insufficient increase-notice gap", 409)
    # publish + supersede prior PUBLISHED for category
    s["status"] = "PUBLISHED"
    db.touch(s)
    for other in db.dues_schedules.values():
        if other["id"] != s["id"] and other["category_id"] == s["category_id"] and other["status"] == "PUBLISHED":
            other["status"] = "SUPERSEDED"
            db.touch(other)
    return success(lifecycle.schedule_out(s))


@bp.post("/api/dues-schedules/<sid>/retire")
def retire_schedule(sid):
    middleware.require_roles("DuesAdministrator")
    s = db.dues_schedules.get(sid)
    if not s:
        raise errors.not_found()
    if s["status"] != "PUBLISHED":
        raise errors.invalid_state("Schedule is not PUBLISHED")
    for inv in db.dues_invoices.values():
        if inv["dues_schedule_id"] == sid and inv["payment_status"] == "PENDING":
            raise errors.invalid_state("PENDING invoice references this schedule")
    s["status"] = "RETIRED"
    db.touch(s)
    return success(lifecycle.schedule_out(s))


@bp.post("/api/dues-schedules/<sid>/increase-notices")
def create_notice(sid):
    middleware.require_roles("DuesAdministrator")
    s = db.dues_schedules.get(sid)
    if not s:
        raise errors.not_found()
    audience = sum(1 for m in db.members.values()
                   if m["category_id"] == s["category_id"] and m["status"] == "ACTIVE")
    n = lifecycle.new_entity({
        "schedule_id": sid,
        "noticed_at": db.iso(db.now_utc()),
        "effective_from": s["effective_from"],
        "audience_size": audience,
        "status": "SCHEDULED",
    })
    db.dues_increase_notices[n["id"]] = n
    return success(lifecycle.notice_out(n), status=201)


@bp.get("/api/dues-schedules/<sid>/increase-notices")
def list_notices(sid):
    middleware.require_roles("DuesAdministrator", "MembershipAdministrator")
    if sid not in db.dues_schedules:
        raise errors.not_found()
    rows = [n for n in db.dues_increase_notices.values() if n["schedule_id"] == sid]
    rows.sort(key=lambda n: n["created_at"])
    return success([lifecycle.notice_out(n) for n in rows], response_type="array",
                   pagination={"limit": len(rows) or 10, "offset": 0,
                               "total_count": len(rows), "has_more": False})
