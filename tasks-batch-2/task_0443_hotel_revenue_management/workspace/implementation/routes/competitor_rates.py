"""CompetitorRate endpoints (PRD §3.10). Immutable: only id + created_at."""
from flask import Blueprint, request

from db import db, new_id
from middleware import authenticate, require_role
from response import success, list_success
from errors import err, ERR_INVALID_REQUEST, ERR_FK_NOT_FOUND
from services.common import (
    get_body, require_str, require_number, require_datetime,
    stay_date_midnight, iso_out, stamp_new,
    parse_pagination, sort_by_created, get_or_404,
)
from services.serialize import ser_competitor_rate

bp = Blueprint("competitor_rates", __name__)

READ_ROLES = {"RevenueManager", "ChannelManager", "Analyst"}
WRITE_ROLES = {"RevenueManager", "ChannelManager"}


@bp.route("/competitor-rates", methods=["POST"])
def create_competitor_rate():
    _, role = authenticate()
    require_role(role, WRITE_ROLES)
    body = get_body()
    property_id = require_str(body, "property_id")
    competitor_name = require_str(body, "competitor_name")
    stay_dt = require_datetime(body, "stay_date")
    shopped_rate = require_number(body, "shopped_rate")
    if shopped_rate < 0:
        raise err(ERR_INVALID_REQUEST, "shopped_rate must be >= 0")
    shopped_at = require_datetime(body, "shopped_at")

    if property_id not in db.properties:
        raise err(ERR_FK_NOT_FOUND, "property_id does not reference an existing property")

    stay_mid = stay_date_midnight(stay_dt)
    rec = {
        "id": new_id(),
        "property_id": property_id,
        "competitor_name": competitor_name,
        "stay_date": iso_out(stay_mid),
        "stay_date_key": stay_mid.strftime("%Y-%m-%d"),
        "shopped_rate": shopped_rate,
        "shopped_at": iso_out(shopped_at),
        "_seq": db.next_seq(),
    }
    # Immutable: carries only id + created_at (no updated_at / version).
    stamp_new(rec, mutable=False)
    db.competitor_rates[rec["id"]] = rec
    return success(ser_competitor_rate(rec), status=201)


@bp.route("/competitor-rates/<cid>", methods=["GET"])
def get_competitor_rate(cid):
    _, role = authenticate()
    require_role(role, READ_ROLES)
    rec = get_or_404(db.competitor_rates, cid)
    return success(ser_competitor_rate(rec), status=200)


@bp.route("/competitor-rates", methods=["GET"])
def list_competitor_rates():
    _, role = authenticate()
    require_role(role, READ_ROLES)
    limit, offset = parse_pagination()
    property_id = request.args.get("property_id")
    stay_date = request.args.get("stay_date")
    stay_key = None
    if stay_date:
        from services.common import parse_iso
        stay_key = stay_date_midnight(parse_iso(stay_date, "stay_date")).strftime("%Y-%m-%d")
    items = []
    for c in db.competitor_rates.values():
        if property_id is not None and c["property_id"] != property_id:
            continue
        if stay_key is not None and c["stay_date_key"] != stay_key:
            continue
        items.append(c)
    items = sort_by_created(items)
    total = len(items)
    page = [ser_competitor_rate(c) for c in items[offset:offset + limit]]
    return list_success(page, limit, offset, total)
