"""Penalty + Appeal endpoints."""
from datetime import timedelta

from flask import Blueprint, request

import db
from errors import (ApiError, ERR_VALIDATION, ERR_INVALID_STATE, ERR_DRAFT_LEGAL_WAVE,
                    ERR_APPEAL_WINDOW_EXPIRED, ERR_PENALTY_NOT_ASSESSED,
                    ERR_SEGREGATION_OF_DUTIES, ERR_STALE_PENALTY_VERSION, ERR_FORBIDDEN,
                    not_found)
from middleware import require_roles
from response import success_object, success_list, paginate
from services.core import confirm_penalty, recompute_totals, recompute_ranks
from util import stamp_common, touch, require_fields, require_enum, require_int, clock_dt, parse_dt

bp = Blueprint("penalties", __name__)

ALL = ("RaceDirector", "PermitCoordinator", "Referee", "Timer", "VolunteerCoordinator", "Athlete")
KINDS = ("DRAFTING", "COURSE_VIOLATION", "EQUIPMENT")
DECISIONS = ("UPHELD", "OVERTURNED", "REDUCED")


def get_reg_or_404(reg_id):
    r = db.registrations.get(reg_id)
    if not r:
        raise not_found("registration not found")
    return r


def get_penalty_or_404(pid):
    p = db.penalties.get(pid)
    if not p:
        raise not_found("penalty not found")
    return p


def get_appeal_or_404(aid):
    a = db.appeals.get(aid)
    if not a:
        raise not_found("appeal not found")
    return a


def compute_penalty_seconds(kind, registration_id, exclude_penalty_id=None):
    """Returns (seconds, triggers_dsq) per the penalty calculation rules."""
    if kind == "DRAFTING":
        prior = sum(1 for p in db.penalties.values()
                    if p["registration_id"] == registration_id
                    and p["kind"] == "DRAFTING"
                    and p["status"] in ("ASSESSED", "CONFIRMED")
                    and p["id"] != exclude_penalty_id)
        if prior == 0:
            return 120, False
        if prior == 1:
            return 300, False
        return 0, True
    if kind == "COURSE_VIOLATION":
        return 300, False
    # EQUIPMENT
    return 60, False


def _check_draft_legal(reg, kind):
    if kind == "DRAFTING" and reg.get("wave_id"):
        wave = db.waves.get(reg["wave_id"])
        if wave and wave.get("draft_legal"):
            raise ApiError(ERR_DRAFT_LEGAL_WAVE, "DRAFTING penalty invalid on draft-legal wave", 400)


def _refresh_result_for(penalty):
    result = next((r for r in db.results.values()
                   if r["registration_id"] == penalty["registration_id"]), None)
    if result:
        recompute_totals(result)
        touch(result)
        reg = db.registrations[penalty["registration_id"]]
        recompute_ranks(reg["event_id"])


@bp.post("/registrations/<reg_id>/penalties")
def create_penalty(reg_id):
    user_id, role = require_roles("Referee")
    reg = get_reg_or_404(reg_id)
    body = request.get_json(silent=True) or {}
    require_fields(body, ["kind"])
    kind = require_enum(body["kind"], KINDS, "kind")
    notes = body.get("notes")
    if notes is not None and not isinstance(notes, str):
        raise ApiError(ERR_VALIDATION, "notes must be a string", 400)

    _check_draft_legal(reg, kind)
    seconds, triggers_dsq = compute_penalty_seconds(kind, reg["id"])

    ev = db.events[reg["event_id"]]
    assessed_at = db.get_clock()
    expires = parse_dt(assessed_at) + timedelta(minutes=ev["appeal_window_minutes"])
    if "." in assessed_at:
        expires_iso = expires.strftime("%Y-%m-%dT%H:%M:%S.") + f"{expires.microsecond // 1000:03d}Z"
    else:
        expires_iso = expires.strftime("%Y-%m-%dT%H:%M:%SZ")

    p = stamp_common({
        "registration_id": reg["id"],
        "kind": kind,
        "notes": notes,
        "seconds": seconds,
        "triggers_dsq": triggers_dsq,
        "status": "ASSESSED",
        "assessed_by_user_id": user_id,
        "assessed_at": assessed_at,
        "appeal_window_expires_at": expires_iso,
    })
    db.penalties[p["id"]] = p
    return success_object(p, status=201)


@bp.get("/registrations/<reg_id>/penalties")
def list_penalties(reg_id):
    require_roles(*ALL)
    reg = get_reg_or_404(reg_id)
    items = [p for p in db.penalties.values() if p["registration_id"] == reg["id"]]
    page, limit, offset, total = paginate(items, request.args)
    return success_list(page, limit, offset, total)


@bp.get("/penalties/<pid>")
def get_penalty(pid):
    require_roles(*ALL)
    return success_object(get_penalty_or_404(pid))


@bp.post("/penalties/<pid>/amend")
def amend_penalty(pid):
    require_roles("Referee")
    p = get_penalty_or_404(pid)
    body = request.get_json(silent=True) or {}
    require_fields(body, ["expected_penalty_version"])
    expected = require_int(body["expected_penalty_version"], "expected_penalty_version")
    kind = body.get("kind", p["kind"])
    notes = body.get("notes", p["notes"])
    if kind is not None:
        kind = require_enum(kind, KINDS, "kind")
    if notes is not None and not isinstance(notes, str):
        raise ApiError(ERR_VALIDATION, "notes must be a string", 400)

    if p["status"] != "ASSESSED":
        raise ApiError(ERR_INVALID_STATE, f"cannot amend from {p['status']}", 409)
    if expected != p["version"]:
        raise ApiError(ERR_STALE_PENALTY_VERSION, "stale penalty version", 412)

    reg = db.registrations[p["registration_id"]]
    _check_draft_legal(reg, kind)
    seconds, triggers_dsq = compute_penalty_seconds(kind, p["registration_id"], exclude_penalty_id=p["id"])
    p["kind"] = kind
    p["notes"] = notes
    p["seconds"] = seconds
    p["triggers_dsq"] = triggers_dsq
    touch(p)
    return success_object(p)


@bp.post("/penalties/<pid>/appeals")
def file_appeal(pid):
    user_id, role = require_roles("Athlete", "RaceDirector")
    p = get_penalty_or_404(pid)
    reg = db.registrations[p["registration_id"]]
    # Athlete ownership: the penalized registration's athlete_id must equal X-User-ID
    if role == "Athlete" and reg["athlete_id"] != user_id:
        raise ApiError(ERR_FORBIDDEN, "Athlete may only appeal own penalties", 403)
    body = request.get_json(silent=True) or {}
    require_fields(body, ["grounds"])
    if not isinstance(body["grounds"], str):
        raise ApiError(ERR_VALIDATION, "grounds must be a string", 400)

    if p["status"] != "ASSESSED":
        raise ApiError(ERR_INVALID_STATE, f"cannot appeal penalty in {p['status']}", 409)
    if clock_dt() > parse_dt(p["appeal_window_expires_at"]):
        raise ApiError(ERR_APPEAL_WINDOW_EXPIRED, "appeal window expired", 409)

    a = stamp_common({
        "penalty_id": p["id"],
        "grounds": body["grounds"],
        "status": "FILED",
        "decision": None,
        "reduced_seconds": None,
        "decided_by_user_id": None,
    })
    db.appeals[a["id"]] = a
    return success_object(a, status=201)


@bp.get("/penalties/<pid>/appeals")
def list_appeals(pid):
    require_roles(*ALL)
    p = get_penalty_or_404(pid)
    items = [a for a in db.appeals.values() if a["penalty_id"] == p["id"]]
    page, limit, offset, total = paginate(items, request.args)
    return success_list(page, limit, offset, total)


@bp.get("/appeals/<aid>")
def get_appeal(aid):
    require_roles(*ALL)
    return success_object(get_appeal_or_404(aid))


@bp.post("/appeals/<aid>/begin-review")
def begin_review(aid):
    require_roles("Referee")
    a = get_appeal_or_404(aid)
    if a["status"] != "FILED":
        raise ApiError(ERR_INVALID_STATE, f"cannot begin review from {a['status']}", 409)
    a["status"] = "UNDER_REVIEW"
    touch(a)
    return success_object(a)


@bp.post("/appeals/<aid>/decide")
def decide_appeal(aid):
    user_id, role = require_roles("Referee")
    a = get_appeal_or_404(aid)
    body = request.get_json(silent=True) or {}
    require_fields(body, ["decision"])
    decision = require_enum(body["decision"], DECISIONS, "decision")
    reduced_seconds = body.get("reduced_seconds")

    penalty = db.penalties[a["penalty_id"]]

    # priority 5: body validation for REDUCED range (against current penalty seconds)
    if decision == "REDUCED":
        if reduced_seconds is None or isinstance(reduced_seconds, bool) or not isinstance(reduced_seconds, int):
            raise ApiError(ERR_VALIDATION, "reduced_seconds required for REDUCED", 400)
        if not (0 <= reduced_seconds < penalty["seconds"]):
            raise ApiError(ERR_VALIDATION,
                           "reduced_seconds must satisfy 0 <= reduced_seconds < penalty.seconds", 400)

    # priority 6: segregation of duties
    if user_id == penalty["assessed_by_user_id"]:
        raise ApiError(ERR_SEGREGATION_OF_DUTIES, "decider must differ from assessor", 403)

    # priority 7: appeal from-state
    if a["status"] != "UNDER_REVIEW":
        raise ApiError(ERR_INVALID_STATE, f"cannot decide from {a['status']}", 409)
    # priority 8: penalty must still be ASSESSED
    if penalty["status"] != "ASSESSED":
        raise ApiError(ERR_PENALTY_NOT_ASSESSED, "penalty no longer ASSESSED", 409)

    a["status"] = "DECIDED"
    a["decision"] = decision
    a["decided_by_user_id"] = user_id
    if decision == "REDUCED":
        a["reduced_seconds"] = reduced_seconds
    touch(a)

    if decision == "UPHELD":
        confirm_penalty(penalty)
    elif decision == "REDUCED":
        penalty["seconds"] = reduced_seconds
        # triggers_dsq recomputed? REDUCED confirms with substituted seconds; dsq flag
        # stays as computed (a REDUCED decision on a dsq-triggering penalty sets seconds
        # but the dsq flag remains per triggers_dsq). Apply confirmation cascade.
        confirm_penalty(penalty)
    else:  # OVERTURNED
        penalty["status"] = "OVERTURNED"
        touch(penalty)
        _refresh_result_for(penalty)
    return success_object(a)
