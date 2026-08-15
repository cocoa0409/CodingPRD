"""Terms and scheduled breaks."""

import uuid

import clock
import db
import errors
import serializers
from flask import Blueprint, request
from middleware import (ALL_ROLES, get_auth, require_roles, parse_json_body,
                        parse_pagination)
from response import success_object, success_list
from services.term_days import parse_date, recompute_term_day_counts

bp = Blueprint("terms", __name__)

DEFAULT_REFUND_SCHEDULE = [
    {"through_day": 7, "refund_pct": 1.0},
    {"through_day": 14, "refund_pct": 0.75},
    {"through_day": 28, "refund_pct": 0.5},
]


@bp.post("/r2t4/terms")
def create_term():
    auth = get_auth()
    require_roles(auth, ["RegistrarClerk"])
    body = parse_json_body()

    name = body.get("name")
    start_date = body.get("start_date")
    end_date = body.get("end_date")
    if name is None or start_date is None or end_date is None:
        errors.raise_error(errors.ERR_INVALID_REQUEST,
                           "name, start_date and end_date are required")
    if not isinstance(name, str):
        errors.raise_error(errors.ERR_INVALID_REQUEST, "name must be a string")

    start = parse_date(start_date)
    end = parse_date(end_date)
    if start is None or end is None:
        errors.raise_error(errors.ERR_INVALID_REQUEST,
                           "start_date and end_date must be ISO dates (YYYY-MM-DD)")
    if end <= start:
        errors.raise_error(errors.ERR_INVALID_FIELD,
                           "end_date must be strictly after start_date")

    attendance = body.get("attendance_taking_required", False)
    if not isinstance(attendance, bool):
        errors.raise_error(errors.ERR_INVALID_REQUEST,
                           "attendance_taking_required must be a boolean")

    refund_method = body.get("refund_method", "TIERED")
    if refund_method not in ("TIERED", "PRO_RATA"):
        errors.raise_error(errors.ERR_INVALID_REQUEST,
                           "refund_method must be TIERED or PRO_RATA")

    refund_schedule = body.get("refund_schedule")
    if refund_schedule is None:
        refund_schedule = [dict(t) for t in DEFAULT_REFUND_SCHEDULE]
    else:
        if not isinstance(refund_schedule, list):
            errors.raise_error(errors.ERR_INVALID_REQUEST,
                               "refund_schedule must be an array of tiers")
        for tier in refund_schedule:
            if (not isinstance(tier, dict)
                    or "through_day" not in tier or "refund_pct" not in tier
                    or not isinstance(tier["through_day"], int)
                    or not isinstance(tier["refund_pct"], (int, float))):
                errors.raise_error(
                    errors.ERR_INVALID_REQUEST,
                    "each refund_schedule tier must have integer through_day and numeric refund_pct")

    # Priority 10: closed-interval term overlap (adjacency allowed).
    for existing in db.terms.values():
        e_start = parse_date(existing["start_date"])
        e_end = parse_date(existing["end_date"])
        if start <= e_end and end >= e_start:
            errors.raise_error(errors.ERR_TERM_OVERLAP,
                               "term date interval overlaps an existing term")

    term = {
        "id": str(uuid.uuid4()),
        "name": name,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "attendance_taking_required": attendance,
        "refund_method": refund_method,
        "refund_schedule": refund_schedule,
        "calendar_days": 0,
        "deductible_break_days": 0,
        "total_days": 0,
        "created_at": clock.now_iso(),
        "updated_at": clock.now_iso(),
        "version": 1,
        "_seq": db.next_seq(),
    }
    db.terms[term["id"]] = term
    recompute_term_day_counts(term["id"])
    return success_object(serializers.term(term), status_code=201)


@bp.get("/r2t4/terms")
def list_terms():
    auth = get_auth()
    require_roles(auth, ALL_ROLES)
    limit, offset = parse_pagination(request.args)
    items = sorted(db.terms.values(), key=lambda t: (t["created_at"], t["_seq"]))
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serializers.term(t) for t in page], total, limit, offset)


@bp.get("/r2t4/terms/<term_id>")
def get_term(term_id):
    auth = get_auth()
    require_roles(auth, ALL_ROLES)
    term = db.terms.get(term_id)
    if term is None:
        errors.raise_error(errors.ERR_NOT_FOUND, "term not found")
    return success_object(serializers.term(term))


@bp.post("/r2t4/terms/<term_id>/breaks")
def create_break(term_id):
    auth = get_auth()
    require_roles(auth, ["RegistrarClerk"])
    term = db.terms.get(term_id)
    if term is None:
        errors.raise_error(errors.ERR_NOT_FOUND, "term not found")
    body = parse_json_body()

    start_date = body.get("start_date")
    end_date = body.get("end_date")
    if start_date is None or end_date is None:
        errors.raise_error(errors.ERR_INVALID_REQUEST,
                           "start_date and end_date are required")
    start = parse_date(start_date)
    end = parse_date(end_date)
    if start is None or end is None:
        errors.raise_error(errors.ERR_INVALID_REQUEST,
                           "start_date and end_date must be ISO dates (YYYY-MM-DD)")
    if end < start:
        errors.raise_error(errors.ERR_INVALID_FIELD,
                           "end_date must not precede start_date")

    t_start = parse_date(term["start_date"])
    t_end = parse_date(term["end_date"])
    if start < t_start or end > t_end:
        errors.raise_error(errors.ERR_BREAK_OUTSIDE_TERM,
                           "break dates must lie inside the parent term")

    for existing in db.breaks.values():
        if existing["term_id"] != term_id:
            continue
        b_start = parse_date(existing["start_date"])
        b_end = parse_date(existing["end_date"])
        if start <= b_end and end >= b_start:
            errors.raise_error(errors.ERR_BREAK_OVERLAP,
                               "break overlaps another break of the same term")

    brk = {
        "id": str(uuid.uuid4()),
        "term_id": term_id,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "length_days": 0,
        "deductible_days": 0,
        "created_at": clock.now_iso(),
        "_seq": db.next_seq(),
    }
    db.breaks[brk["id"]] = brk
    recompute_term_day_counts(term_id)
    term["version"] += 1
    term["updated_at"] = clock.now_iso()
    return success_object(serializers.scheduled_break(brk), status_code=201)


@bp.get("/r2t4/terms/<term_id>/breaks")
def list_breaks(term_id):
    auth = get_auth()
    require_roles(auth, ALL_ROLES)
    if term_id not in db.terms:
        errors.raise_error(errors.ERR_NOT_FOUND, "term not found")
    limit, offset = parse_pagination(request.args)
    items = [b for b in db.breaks.values() if b["term_id"] == term_id]
    items.sort(key=lambda b: (b["created_at"], b["_seq"]))
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serializers.scheduled_break(b) for b in page],
                        total, limit, offset)
