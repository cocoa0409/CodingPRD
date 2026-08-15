"""Work catalog (PRD 3.1) including the out-of-print sourcing quote."""
from datetime import timedelta

from flask import Blueprint, request

from calc import sourcing_eta_days
from db import db
from errors import (
    ApiError,
    ERR_INVALID_REQUEST,
    ERR_PUBLISHER_NOT_FOUND,
    ERR_WORK_NOT_FOUND,
)
from middleware import require_auth
from response import success_object
from serializers import ser_work
from services import get_or_404
from util import fmt_ts0, is_bool, is_int, is_str, new_record, now_dt, touch
from routes.helpers import body, paginate, require_fields

bp = Blueprint("works", __name__)

ALL_ROLES = ("LibraryAdmin", "LibraryClerk", "ReturnsClerk", "BillingManager", "RightsAdvisor", "Customer")
ENSEMBLE_TIERS = ("CHAMBER", "BAND", "ORCHESTRA")
LICENSE_FORMATS = ("PRINT_ONLY", "DIGITAL_ONLY", "PRINT_AND_DIGITAL")
RIGHTS_CLASSES = ("STANDARD", "GRAND_RIGHTS", "RESTRICTED")
WORK_STATUSES = ("CATALOGED", "WITHDRAWN")


def _positive_cents(data, field):
    v = data.get(field)
    if not is_int(v) or v <= 0:
        raise ApiError(ERR_INVALID_REQUEST, 400, "%s must be an integer > 0" % field)
    return v


@bp.post("/library/works")
def create_work():
    require_auth("LibraryAdmin")
    data = body()
    require_fields(
        data,
        ["publisher_id", "title", "catalog_number", "ensemble_tier",
         "base_rental_rate_cents", "sale_price_cents", "license_format"],
    )
    publisher = db["publishers"].get(data["publisher_id"])
    if publisher is None:
        raise ApiError(ERR_PUBLISHER_NOT_FOUND, 404, "Publisher not found")
    if data["ensemble_tier"] not in ENSEMBLE_TIERS:
        raise ApiError(ERR_INVALID_REQUEST, 400, "Invalid ensemble_tier")
    if data["license_format"] not in LICENSE_FORMATS:
        raise ApiError(ERR_INVALID_REQUEST, 400, "Invalid license_format")
    if not is_str(data["title"]) or not is_str(data["catalog_number"]):
        raise ApiError(ERR_INVALID_REQUEST, 400, "title and catalog_number are required")
    base_rate = _positive_cents(data, "base_rental_rate_cents")
    sale_price = _positive_cents(data, "sale_price_cents")
    perusal_allowed = data.get("perusal_allowed", True)
    if not is_bool(perusal_allowed):
        raise ApiError(ERR_INVALID_REQUEST, 400, "perusal_allowed must be a boolean")
    rights_class = data.get("rights_class", "STANDARD")
    if rights_class not in RIGHTS_CLASSES:
        raise ApiError(ERR_INVALID_REQUEST, 400, "Invalid rights_class")
    for w in db["works"].values():
        if w["publisher_id"] == publisher["id"] and w["catalog_number"] == data["catalog_number"]:
            raise ApiError(ERR_INVALID_REQUEST, 400, "catalog_number must be unique per publisher")
    rec = new_record()
    rec.update(
        {
            "publisher_id": publisher["id"],
            "title": data["title"],
            "catalog_number": data["catalog_number"],
            "ensemble_tier": data["ensemble_tier"],
            "base_rental_rate_cents": base_rate,
            "sale_price_cents": sale_price,
            "license_format": data["license_format"],
            "perusal_allowed": perusal_allowed,
            "rights_class": rights_class,
            "status": "CATALOGED",
        }
    )
    db["works"][rec["id"]] = rec
    return success_object(ser_work(rec), status=201)


@bp.get("/library/works")
def list_works():
    require_auth(*ALL_ROLES)
    rows = list(db["works"].values())
    pub = request.args.get("publisher_id")
    if pub is not None:
        rows = [w for w in rows if w["publisher_id"] == pub]
    return paginate(rows, ser_work)


@bp.get("/library/works/<wid>")
def get_work(wid):
    require_auth(*ALL_ROLES)
    rec = get_or_404("works", wid, ERR_WORK_NOT_FOUND)
    return success_object(ser_work(rec))


@bp.get("/library/works/<wid>/sourcing-quote")
def sourcing_quote(wid):
    require_auth("LibraryAdmin", "LibraryClerk")
    rec = get_or_404("works", wid, ERR_WORK_NOT_FOUND)
    days = sourcing_eta_days(rec)
    expiry = now_dt() + timedelta(days=days)
    return success_object({"estimated_days": days, "quoted_expiry": fmt_ts0(expiry)})


@bp.patch("/library/works/<wid>")
def update_work(wid):
    require_auth("LibraryAdmin")
    rec = get_or_404("works", wid, ERR_WORK_NOT_FOUND)
    data = body()
    changed = False
    if "status" in data and data["status"] is not None:
        if data["status"] not in WORK_STATUSES:
            raise ApiError(ERR_INVALID_REQUEST, 400, "status must be CATALOGED or WITHDRAWN")
        rec["status"] = data["status"]
        changed = True
    for f in ("base_rental_rate_cents", "sale_price_cents"):
        if f in data and data[f] is not None:
            rec[f] = _positive_cents(data, f)
            changed = True
    if "perusal_allowed" in data and data["perusal_allowed"] is not None:
        if not is_bool(data["perusal_allowed"]):
            raise ApiError(ERR_INVALID_REQUEST, 400, "perusal_allowed must be a boolean")
        rec["perusal_allowed"] = data["perusal_allowed"]
        changed = True
    if "rights_class" in data and data["rights_class"] is not None:
        if data["rights_class"] not in RIGHTS_CLASSES:
            raise ApiError(ERR_INVALID_REQUEST, 400, "Invalid rights_class")
        rec["rights_class"] = data["rights_class"]
        changed = True
    if changed:
        touch(rec)
    return success_object(ser_work(rec))
