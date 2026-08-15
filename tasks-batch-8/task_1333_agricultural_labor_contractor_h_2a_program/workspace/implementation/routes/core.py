"""Clock, growers, wage determinations."""

from flask import Blueprint, request

import calc
from calc import d, iso
from common import (ALL_ROLES, ApiError, auth, body, clock_date, created_order,
                    fmt_instant, get_or_404, invalid, ok, ok_list, paginate,
                    parse_instant, req_enum, req_int, req_str, stamp_new, touch)
from services import (ser_grower, ser_wage_determination)
from store import db

bp = Blueprint("core", __name__)


@bp.post("/h2a/_clock/set_current_utc")
@auth("SystemAdmin")
def set_clock():
    b = body()
    dt = parse_instant(b.get("to_iso8601"))
    db.clock = dt
    return ok({"current_utc": fmt_instant(db.clock)})


# ------------------------------------------------------------------ growers

@bp.post("/h2a/growers")
@auth("ContractorAdmin")
def create_grower():
    b = body()
    fein = b.get("fein")
    if isinstance(fein, str) and any(g["fein"] == fein
                                     for g in db.growers.values()):
        raise ApiError("ERR_DUPLICATE_FEIN", 409, "fein already registered")
    legal_name = req_str(b, "legal_name")
    fein = req_str(b, "fein")
    state_code = req_str(b, "state_code")
    rec = {
        "legal_name": legal_name,
        "fein": fein,
        "state_code": state_code,
        "status": "ACTIVE",
        "debarment_ends_on": None,
    }
    stamp_new(rec)
    db.growers[rec["id"]] = rec
    return ok(ser_grower(rec), 201)


@bp.get("/h2a/growers")
@auth(*ALL_ROLES)
def list_growers():
    status = request.args.get("status")
    rows = [g for g in db.growers.values()
            if status is None or g["status"] == status]
    rows = created_order(rows)
    page, total, limit, offset = paginate(rows)
    return ok_list([ser_grower(g) for g in page], total, limit, offset)


@bp.post("/h2a/growers/<growerId>/refresh-status")
@auth("WageAuditor")
def refresh_grower(growerId):
    g = get_or_404(db.growers, growerId, "ERR_GROWER_NOT_FOUND", "grower")
    today = clock_date()
    if g["status"] == "SUSPENDED":
        has_open = any(
            c["grower_id"] == g["id"] and c["status"] in ("OPEN", "FINDINGS_ISSUED")
            for c in db.audit_cases.values())
        if not has_open:
            g["status"] = "ACTIVE"
            touch(g)
    elif g["status"] == "DEBARRED":
        if g["debarment_ends_on"] is not None and \
                today >= d(g["debarment_ends_on"]):
            g["status"] = "ACTIVE"
            g["debarment_ends_on"] = None
            touch(g)
    return ok(ser_grower(g))


# -------------------------------------------------------- wage determinations

@bp.post("/h2a/wage-determinations")
@auth("ProgramReviewer")
def create_wage_determination():
    b = body()
    state_code = req_str(b, "state_code")
    crop = req_str(b, "crop")
    activity = req_enum(b, "activity", calc.ACTIVITY_ENUM)
    effective_year = req_int(b, "effective_year")
    aewr = req_int(b, "aewr_hourly_cents")
    prev = req_int(b, "prevailing_hourly_cents")
    if aewr <= 0:
        raise invalid("aewr_hourly_cents must be positive")
    if prev <= 0:
        raise invalid("prevailing_hourly_cents must be positive")
    piece = b.get("prevailing_piece_rate_cents_per_unit")
    if piece is not None:
        if isinstance(piece, bool) or not isinstance(piece, int):
            raise invalid("prevailing_piece_rate_cents_per_unit must be an integer")
        if piece <= 0:
            raise invalid("prevailing_piece_rate_cents_per_unit must be positive")
    piece_unit = b.get("piece_unit_name")
    if piece_unit is not None and not isinstance(piece_unit, str):
        raise invalid("piece_unit_name must be a string")

    # Supersede any matching PUBLISHED row (crop compared case-insensitively).
    for w in db.wage_determinations.values():
        if (w["status"] == "PUBLISHED"
                and w["state_code"] == state_code
                and w["crop"].lower() == crop.lower()
                and w["activity"] == activity
                and w["effective_year"] == effective_year):
            w["status"] = "SUPERSEDED"
            touch(w)

    rec = {
        "state_code": state_code,
        "crop": crop,
        "activity": activity,
        "effective_year": effective_year,
        "aewr_hourly_cents": aewr,
        "prevailing_hourly_cents": prev,
        "prevailing_piece_rate_cents_per_unit": piece,
        "piece_unit_name": piece_unit,
        "status": "PUBLISHED",
    }
    stamp_new(rec)
    db.wage_determinations[rec["id"]] = rec
    return ok(ser_wage_determination(rec), 201)


@bp.get("/h2a/wage-determinations")
@auth(*ALL_ROLES)
def list_wage_determinations():
    q = request.args
    rows = list(db.wage_determinations.values())
    if q.get("state_code") is not None:
        rows = [w for w in rows if w["state_code"] == q.get("state_code")]
    if q.get("crop") is not None:
        rows = [w for w in rows if w["crop"] == q.get("crop")]
    if q.get("activity") is not None:
        rows = [w for w in rows if w["activity"] == q.get("activity")]
    if q.get("effective_year") is not None:
        rows = [w for w in rows
                if str(w["effective_year"]) == q.get("effective_year")]
    if q.get("status") is not None:
        rows = [w for w in rows if w["status"] == q.get("status")]
    rows = created_order(rows)
    page, total, limit, offset = paginate(rows)
    return ok_list([ser_wage_determination(w) for w in page], total, limit, offset)
