"""AvailabilityHold endpoints (PIN/AVAIL holds and priority contests)."""
from flask import Blueprint, request

import db
from errors import (err_hold_outranked, err_hold_talent_mismatch,
                    err_invalid_request, err_invalid_state, err_invalid_window,
                    err_not_found, err_ref_not_found)
from middleware import require_roles
from response import success_object, success_list
from services import domain
from util import (check_datetime, check_enum, check_int, check_string,
                  filter_status, get_payload, logical_now, new_record, paginate,
                  parse_dt, serialize, touch)

S = db.STORE
bp = Blueprint("holds", __name__)

READ_ROLES = ("CastingDirector", "CastingAssociate", "ProductionCoordinator", "Agent")


def _get_hold(hid):
    h = domain.find("holds", hid)
    if h is None:
        raise err_not_found("AvailabilityHold not found")
    return h


@bp.post("/casting/submissions/<sid>/holds")
def create_hold(sid):
    require_roles("CastingDirector", "CastingAssociate")
    sub = domain.find("submissions", sid)
    if sub is None:
        raise err_not_found("Submission not found")
    body = get_payload()
    talent = None
    if body.get("talent_id") is not None:
        talent = domain.find("talents", body.get("talent_id"))
        if talent is None:
            raise err_ref_not_found("talent_id does not reference a Talent")
    # 1) hold talent must equal the submission's talent
    if talent is not None and talent["id"] != sub["talent_id"]:
        raise err_hold_talent_mismatch()
    # 2) window well-formedness
    ws = parse_dt(body.get("window_start")) if body.get("window_start") is not None else None
    we = parse_dt(body.get("window_end")) if body.get("window_end") is not None else None
    exp = parse_dt(body.get("expires_at")) if body.get("expires_at") is not None else None
    if ws is not None and we is not None and exp is not None:
        if not (ws < we) or not (exp > ws):
            raise err_invalid_window()
    elif ws is not None and we is not None and not (ws < we):
        raise err_invalid_window()
    elif ws is not None and exp is not None and not (exp > ws):
        raise err_invalid_window()
    # Final field validation
    check_string(body, "talent_id")
    check_enum(body, "hold_kind", {"PIN", "AVAIL"})
    ws = check_datetime(body, "window_start")
    we = check_datetime(body, "window_end")
    rank = check_int(body, "priority_rank", min_v=1)
    exp = check_datetime(body, "expires_at")
    if not (ws < we) or not (exp > ws):
        raise err_invalid_window()
    rec = new_record({
        "submission_id": sid,
        "talent_id": talent["id"],
        "hold_kind": body["hold_kind"],
        "window_start": ws,
        "window_end": we,
        "priority_rank": rank,
        "expires_at": exp,
        "status": "ACTIVE",
    })
    S["holds"][rec["id"]] = rec
    return success_object(serialize(rec), 201)


@bp.get("/casting/holds")
def list_holds():
    require_roles(*READ_ROLES)
    records = filter_status(S["holds"].values())
    for param in ("talent_id", "submission_id", "hold_kind"):
        v = request.args.get(param)
        if v is not None:
            records = [r for r in records if r.get(param) == v]
    page, limit, offset, total = paginate(records)
    return success_list([serialize(r) for r in page], limit, offset, total)


@bp.get("/casting/holds/<hid>")
def get_hold(hid):
    require_roles(*READ_ROLES)
    return success_object(serialize(_get_hold(hid)))


@bp.get("/casting/submissions/<sid>/holds")
def list_submission_holds(sid):
    require_roles(*READ_ROLES)
    if domain.find("submissions", sid) is None:
        raise err_not_found("Submission not found")
    records = filter_status(domain.children("holds", "submission_id", sid))
    page, limit, offset, total = paginate(records)
    return success_list([serialize(r) for r in page], limit, offset, total)


@bp.post("/casting/holds/<hid>/confirm")
def confirm_hold(hid):
    require_roles("CastingDirector")
    h = _get_hold(hid)
    if h["status"] != "ACTIVE":
        raise err_invalid_state("Only an ACTIVE hold can be confirmed")
    candidates = domain.hold_outranking_candidates(h)
    if domain.hold_is_outranked(h, candidates):
        raise err_hold_outranked()
    h["status"] = "CONFIRMED"
    touch(h)
    for c in candidates:
        c["status"] = "OUTBID"
        touch(c)
    return success_object(serialize(h))


@bp.post("/casting/holds/<hid>/release")
def release_hold(hid):
    require_roles("CastingDirector", "CastingAssociate")
    h = _get_hold(hid)
    if h["status"] != "ACTIVE":
        raise err_invalid_state("Only an ACTIVE hold can be released")
    h["status"] = "RELEASED"
    touch(h)
    return success_object(serialize(h))
