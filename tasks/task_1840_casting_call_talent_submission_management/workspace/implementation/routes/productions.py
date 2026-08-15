"""Clock, Production, Role, Breakdown endpoints."""
from flask import Blueprint, request

import db
from errors import (err_invalid_state, err_not_found, err_ref_not_found,
                    err_role_unfilled)
from middleware import require_roles
from response import success_object, success_list
from services import domain, sweeps
from util import (check_datetime, check_enum, check_int, check_string, check_bool,
                  filter_status, get_payload, iso, logical_now, new_record,
                  paginate, parse_dt, serialize, set_logical_clock, touch)

S = db.STORE
bp = Blueprint("productions", __name__)

PRODUCTION_TYPES = {"FILM", "TV_SERIES", "COMMERCIAL", "THEATER", "NEW_MEDIA"}
RELEASED = ("RELEASED_AGENT_ONLY", "RELEASED_OPEN")


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

@bp.post("/casting/_clock/set_current_utc")
def set_clock():
    require_roles("CastingDirector", "ProductionCoordinator")
    body = get_payload()
    target = parse_dt(body.get("to_iso8601")) if "to_iso8601" in body else None
    if target is None:
        from errors import err_invalid_request
        raise err_invalid_request("to_iso8601 must be an ISO 8601 datetime")
    set_logical_clock(target)
    sweeps.run_sweeps()
    return success_object({"current_utc": iso(logical_now())})


# ---------------------------------------------------------------------------
# Productions
# ---------------------------------------------------------------------------

@bp.post("/casting/productions")
def create_production():
    require_roles("CastingDirector")
    body = get_payload()
    rec = new_record({
        "title": body.get("title"),
        "production_type": body.get("production_type"),
        "union_signatory": body.get("union_signatory"),
        "shoot_city": body.get("shoot_city"),
        "shoot_state": body.get("shoot_state"),
        "start_date": parse_dt(body.get("start_date")) if body.get("start_date") is not None else None,
        "wrap_date": parse_dt(body.get("wrap_date")) if body.get("wrap_date") is not None else None,
        "casting_office_id": body.get("casting_office_id"),
        "status": "SETUP",
        "active_breakdown_count": 0,
    })
    # Field validation (pipeline step 8)
    check_string(body, "title")
    check_enum(body, "production_type", PRODUCTION_TYPES)
    check_bool(body, "union_signatory")
    check_string(body, "shoot_city")
    check_string(body, "shoot_state")
    start = check_datetime(body, "start_date")
    wrap = check_datetime(body, "wrap_date")
    check_string(body, "casting_office_id")
    if wrap < start:
        from errors import err_invalid_request
        raise err_invalid_request("wrap_date must be on or after start_date")
    S["productions"][rec["id"]] = rec
    return success_object(serialize(rec), 201)


def _get_production(pid):
    p = domain.find("productions", pid)
    if p is None:
        raise err_not_found("Production not found")
    return p


@bp.get("/casting/productions/<pid>")
def get_production(pid):
    require_roles("CastingDirector", "CastingAssociate", "ProductionCoordinator", "Agent", "Guardian")
    return success_object(serialize(_get_production(pid)))


@bp.get("/casting/productions")
def list_productions():
    require_roles("CastingDirector", "CastingAssociate", "ProductionCoordinator")
    records = filter_status(S["productions"].values())
    us = request.args.get("union_signatory")
    if us is not None:
        want = us.lower() == "true"
        records = [r for r in records if r.get("union_signatory") == want]
    page, limit, offset, total = paginate(records)
    return success_list([serialize(r) for r in page], limit, offset, total)


@bp.post("/casting/productions/<pid>/open-casting")
def open_casting(pid):
    require_roles("CastingDirector")
    p = _get_production(pid)
    has_live_breakdown = any(
        b["production_id"] == pid and b["status"] != "CANCELLED"
        for b in S["breakdowns"].values())
    if p["status"] != "SETUP" or not has_live_breakdown:
        raise err_invalid_state("Production must be SETUP with at least one non-CANCELLED breakdown")
    p["status"] = "CASTING"
    touch(p)
    return success_object(serialize(p))


@bp.post("/casting/productions/<pid>/lock")
def lock_production(pid):
    require_roles("CastingDirector")
    p = _get_production(pid)
    if p["status"] != "CASTING":
        raise err_invalid_state("Production must be CASTING to lock")
    for role in S["roles"].values():
        if role["production_id"] != pid or role["status"] != "OPEN":
            continue
        filled = False
        for b in S["breakdowns"].values():
            if b["role_id"] != role["id"]:
                continue
            for sub in S["submissions"].values():
                if sub["breakdown_id"] != b["id"]:
                    continue
                if any(bk["submission_id"] == sub["id"] and bk["status"] == "CONFIRMED"
                       for bk in S["bookings"].values()):
                    filled = True
                    break
            if filled:
                break
        if not filled:
            raise err_role_unfilled("An OPEN role lacks a CONFIRMED booking")
    p["status"] = "LOCKED"
    touch(p)
    return success_object(serialize(p))


@bp.post("/casting/productions/<pid>/complete")
def complete_production(pid):
    require_roles("CastingDirector")
    p = _get_production(pid)
    if p["status"] != "LOCKED":
        raise err_invalid_state("Production must be LOCKED to complete")
    if not logical_now() > p["wrap_date"]:
        raise err_invalid_state("Logical clock must be past wrap_date to complete")
    p["status"] = "COMPLETED"
    touch(p)
    for rep in S["taft_hartley_reports"].values():
        if rep["production_id"] == pid and rep["status"] == "PENDING":
            rep["status"] = "LATE"
            touch(rep)
    return success_object(serialize(p))


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------

@bp.post("/casting/productions/<pid>/roles")
def create_role(pid):
    require_roles("CastingDirector")
    p = _get_production(pid)
    body = get_payload()
    rec = new_record({
        "production_id": pid,
        "character_name": body.get("character_name"),
        "is_minor_role": body.get("is_minor_role"),
        "is_union_covered": body.get("is_union_covered"),
        "engagement_start": parse_dt(body.get("engagement_start")) if body.get("engagement_start") is not None else None,
        "engagement_end": parse_dt(body.get("engagement_end")) if body.get("engagement_end") is not None else None,
        "status": "OPEN",
    })
    check_string(body, "character_name")
    check_bool(body, "is_minor_role")
    check_bool(body, "is_union_covered")
    start = check_datetime(body, "engagement_start")
    end = check_datetime(body, "engagement_end")
    from errors import err_invalid_request
    if end < start:
        raise err_invalid_request("engagement_end must be on or after engagement_start")
    if start < p["start_date"] or end > p["wrap_date"]:
        raise err_invalid_request("engagement span must lie within production start_date..wrap_date")
    S["roles"][rec["id"]] = rec
    return success_object(serialize(rec), 201)


def _get_role(rid):
    r = domain.find("roles", rid)
    if r is None:
        raise err_not_found("Role not found")
    return r


@bp.get("/casting/roles/<rid>")
def get_role(rid):
    require_roles("CastingDirector", "CastingAssociate", "ProductionCoordinator", "Agent")
    return success_object(serialize(_get_role(rid)))


@bp.get("/casting/productions/<pid>/roles")
def list_roles(pid):
    require_roles("CastingDirector", "CastingAssociate", "ProductionCoordinator", "Agent")
    _get_production(pid)
    records = filter_status(domain.children("roles", "production_id", pid))
    page, limit, offset, total = paginate(records)
    return success_list([serialize(r) for r in page], limit, offset, total)


# ---------------------------------------------------------------------------
# Breakdowns
# ---------------------------------------------------------------------------

@bp.post("/casting/productions/<pid>/breakdowns")
def create_breakdown(pid):
    require_roles("CastingDirector")
    _get_production(pid)
    body = get_payload()
    role = None
    if body.get("role_id") is not None:
        cand = domain.find("roles", body.get("role_id"))
        if cand is not None and cand["production_id"] == pid:
            role = cand
        if role is None:
            raise err_ref_not_found("role_id does not reference a role of this production")
    rec = new_record({
        "production_id": pid,
        "role_id": body.get("role_id"),
        "distribution": body.get("distribution"),
        "submission_deadline": parse_dt(body.get("submission_deadline")) if body.get("submission_deadline") is not None else None,
        "rate_weekly_cents": body.get("rate_weekly_cents"),
        "status": "DRAFT",
        "released_at": None,
        "submission_count": 0,
    })
    check_string(body, "role_id")
    check_enum(body, "distribution", {"AGENT_ONLY", "OPEN_CALL"})
    check_datetime(body, "submission_deadline")
    check_int(body, "rate_weekly_cents", min_v=1)
    S["breakdowns"][rec["id"]] = rec
    return success_object(serialize(rec), 201)


def _get_breakdown(bid):
    b = domain.find("breakdowns", bid)
    if b is None:
        raise err_not_found("Breakdown not found")
    return b


@bp.get("/casting/breakdowns/<bid>")
def get_breakdown(bid):
    require_roles("CastingDirector", "CastingAssociate", "ProductionCoordinator", "Agent")
    return success_object(serialize(_get_breakdown(bid)))


@bp.get("/casting/productions/<pid>/breakdowns")
def list_production_breakdowns(pid):
    require_roles("CastingDirector", "CastingAssociate", "ProductionCoordinator", "Agent")
    _get_production(pid)
    records = filter_status(domain.children("breakdowns", "production_id", pid))
    page, limit, offset, total = paginate(records)
    return success_list([serialize(r) for r in page], limit, offset, total)


@bp.get("/casting/breakdowns")
def list_breakdowns():
    require_roles("CastingDirector", "CastingAssociate", "ProductionCoordinator", "Agent")
    records = filter_status(S["breakdowns"].values())
    role_id = request.args.get("role_id")
    if role_id is not None:
        records = [r for r in records if r.get("role_id") == role_id]
    prod_id = request.args.get("production_id")
    if prod_id is not None:
        records = [r for r in records if r.get("production_id") == prod_id]
    page, limit, offset, total = paginate(records)
    return success_list([serialize(r) for r in page], limit, offset, total)


@bp.post("/casting/breakdowns/<bid>/release")
def release_breakdown(bid):
    require_roles("CastingDirector")
    b = _get_breakdown(bid)
    body = get_payload()
    p = domain.find("productions", b["production_id"])
    role = domain.find("roles", b["role_id"])
    if b["status"] != "DRAFT":
        raise err_invalid_state("Only a DRAFT breakdown can be released")
    if p is None or p["status"] not in ("SETUP", "CASTING"):
        raise err_invalid_state("Parent production must be SETUP or CASTING to release")
    if role is None or role["status"] != "OPEN":
        raise err_invalid_state("Child role must be OPEN to release")
    distribution = check_enum(body, "distribution", {"AGENT_ONLY", "OPEN_CALL"})
    b["distribution"] = distribution
    b["status"] = "RELEASED_AGENT_ONLY" if distribution == "AGENT_ONLY" else "RELEASED_OPEN"
    b["released_at"] = logical_now()
    touch(b)
    if p is not None:
        domain.recompute_active_breakdown_count(p, bump=True)
    return success_object(serialize(b))


@bp.post("/casting/breakdowns/<bid>/widen")
def widen_breakdown(bid):
    require_roles("CastingDirector")
    b = _get_breakdown(bid)
    if b["status"] != "RELEASED_AGENT_ONLY":
        raise err_invalid_state("Only a RELEASED_AGENT_ONLY breakdown can be widened")
    if not logical_now() < b["submission_deadline"]:
        raise err_invalid_state("Cannot widen at or after the submission deadline")
    b["distribution"] = "OPEN_CALL"
    b["status"] = "RELEASED_OPEN"
    touch(b)
    return success_object(serialize(b))


@bp.post("/casting/breakdowns/<bid>/close")
def close_breakdown(bid):
    require_roles("CastingDirector")
    b = _get_breakdown(bid)
    if b["status"] not in RELEASED:
        raise err_invalid_state("Only a released breakdown can be closed")
    # rejection cascade: SUBMITTED / UNDER_REVIEW -> REJECTED
    for sub in S["submissions"].values():
        if sub["breakdown_id"] == bid and sub["status"] in ("SUBMITTED", "UNDER_REVIEW"):
            if sub.get("reviewed_at") is None:
                sub["reviewed_at"] = logical_now()
            sub["status"] = "REJECTED"
            touch(sub)
            domain.release_active_holds_on_submission(sub["id"])
    b["status"] = "CLOSED"
    touch(b)
    p = domain.find("productions", b["production_id"])
    if p is not None:
        domain.recompute_active_breakdown_count(p, bump=True)
    return success_object(serialize(b))


@bp.post("/casting/breakdowns/<bid>/cancel")
def cancel_breakdown(bid):
    require_roles("CastingDirector")
    b = _get_breakdown(bid)
    if b["status"] == "DRAFT":
        b["status"] = "CANCELLED"
        touch(b)
        return success_object(serialize(b))
    if b["status"] not in RELEASED:
        raise err_invalid_state("Breakdown cannot be cancelled from its current state")
    subs = [s for s in S["submissions"].values() if s["breakdown_id"] == bid]
    if any(s["status"] == "BOOKED" for s in subs):
        raise err_invalid_state("Cannot cancel a breakdown with a BOOKED submission")
    for sub in subs:
        if sub["status"] not in ("WITHDRAWN", "REJECTED", "NOT_BOOKED"):
            sub["status"] = "WITHDRAWN"
            touch(sub)
            domain.release_active_holds_on_submission(sub["id"])
    for sess in [x for x in S["sessions"].values() if x["breakdown_id"] == bid]:
        if sess["status"] == "SCHEDULED":
            sess["status"] = "CANCELLED"
            touch(sess)
            for appt in S["appointments"].values():
                if appt["session_id"] == sess["id"] and appt["status"] in ("PROPOSED", "CONFIRMED"):
                    appt["status"] = "CANCELLED"
                    touch(appt)
            domain.recompute_booked_count(sess, bump=False)
    domain.recompute_submission_count(b, bump=False)
    b["status"] = "CANCELLED"
    touch(b)
    p = domain.find("productions", b["production_id"])
    if p is not None:
        domain.recompute_active_breakdown_count(p, bump=True)
    return success_object(serialize(b))
