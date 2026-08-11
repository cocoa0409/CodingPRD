"""Offense codes and progressive-matrix sanction bands (PRD §3.1)."""
from flask import Blueprint

from db import db, stamp, serialize
from errors import raise_err, ERR_INVALID_REQUEST, ERR_DUPLICATE_BAND
from middleware import endpoint
from response import success
from routes.common import get_or_404, render_list
from util import is_int

bp = Blueprint("offense_codes", __name__)

CATEGORIES = {
    "DRUGS",
    "WEAPONS",
    "VIOLENCE",
    "PROPERTY",
    "DISRUPTION",
    "ATTENDANCE",
    "TECHNOLOGY",
}


@bp.post("/offense-codes")
@endpoint("DistrictAdmin")
def create_offense_code(ctx):
    b = ctx.body
    code = b.get("code")
    title = b.get("title")
    category = b.get("category")
    severity = b.get("severity_level")
    expellable = b.get("expellable")

    if not isinstance(code, str) or not code:
        raise_err(ERR_INVALID_REQUEST, "code is required")
    if not isinstance(title, str) or not title:
        raise_err(ERR_INVALID_REQUEST, "title is required")
    if category not in CATEGORIES:
        raise_err(ERR_INVALID_REQUEST, "category is not a declared value")
    if not is_int(severity) or severity < 1 or severity > 4:
        raise_err(ERR_INVALID_REQUEST, "severity_level must be an integer in [1, 4]")
    if not isinstance(expellable, bool):
        raise_err(ERR_INVALID_REQUEST, "expellable must be a boolean")

    # Code uniqueness (reported as ERR_INVALID_REQUEST per PRD §3.1)
    if any(oc["code"] == code for oc in db.offense_codes.values()):
        raise_err(ERR_INVALID_REQUEST, "duplicate offense code")

    offense = stamp(
        {
            "code": code,
            "title": title,
            "category": category,
            "severity_level": severity,
            "expellable": expellable,
        },
        light=True,
    )
    db.offense_codes[offense["id"]] = offense
    return success(serialize(offense), 201)


@bp.get("/offense-codes/<oid>")
@endpoint("DistrictAdmin", "SchoolAdministrator")
def get_offense_code(ctx, oid):
    return success(serialize(get_or_404(db.offense_codes, oid, "offense code")))


@bp.post("/offense-codes/<oid>/sanction-bands")
@endpoint("DistrictAdmin")
def create_sanction_band(ctx, oid):
    offense = get_or_404(db.offense_codes, oid, "offense code")
    b = ctx.body
    idx = b.get("occurrence_index")
    min_days = b.get("min_days")
    max_days = b.get("max_days")

    if not is_int(idx) or idx not in (1, 2, 3):
        raise_err(ERR_INVALID_REQUEST, "occurrence_index must be an integer in {1, 2, 3}")
    if not is_int(min_days) or not is_int(max_days):
        raise_err(ERR_INVALID_REQUEST, "min_days and max_days must be integers")
    if min_days < 0 or min_days > max_days or max_days > 10:
        raise_err(
            ERR_INVALID_REQUEST, "band bounds must satisfy 0 <= min_days <= max_days <= 10"
        )

    if any(
        band["offense_code_id"] == offense["id"] and band["occurrence_index"] == idx
        for band in db.sanction_bands.values()
    ):
        raise_err(ERR_DUPLICATE_BAND, "band already exists for (offense_code_id, occurrence_index)")

    band = stamp(
        {
            "offense_code_id": offense["id"],
            "occurrence_index": idx,
            "min_days": min_days,
            "max_days": max_days,
        },
        light=True,
    )
    db.sanction_bands[band["id"]] = band
    return success(serialize(band), 201)


@bp.get("/offense-codes/<oid>/sanction-bands")
@endpoint("DistrictAdmin", "SchoolAdministrator")
def list_sanction_bands(ctx, oid):
    offense = get_or_404(db.offense_codes, oid, "offense code")
    bands = {k: v for k, v in db.sanction_bands.items() if v["offense_code_id"] == offense["id"]}
    return render_list(bands)
