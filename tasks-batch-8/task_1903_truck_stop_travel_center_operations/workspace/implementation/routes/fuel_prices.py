"""Fuel price book endpoints (PRD 3.1; OCC rule fuel-price-supersede-stale-site)."""
from flask import Blueprint

from db import db
from errors import (
    raise_error, ERR_INVALID_REQUEST, ERR_OVERLAPPING_PRICE_WINDOW, ERR_STALE_VERSION,
)
from middleware import authorized
from response import success_object
from routes.helpers import list_response, public
from services.core import FUEL_TYPES, new_record, recompute_site_mirrors, touch
from util import CLOCK, fmt_dt, parse_dt
from validate import get_body, query_filter, require_path_resource, valid_dt, valid_int

bp = Blueprint("fuel_prices", __name__)


@bp.post("/sites/<sid>/fuel-prices")
def create_fuel_price(sid):
    authorized(["FuelDeskLead"])
    # Priority 5: path existence
    site = require_path_resource("sites", sid)
    body = get_body()

    # OCC guard (SCAFFOLD concurrency_rules): expected_site_version required.
    if valid_int(body.get("expected_site_version")):
        if body["expected_site_version"] != site["version"]:
            raise_error(ERR_STALE_VERSION, "expected_site_version does not match site version")
    # missing/malformed OCC field is deferred to the final shape validation

    fuel_type = body.get("fuel_type")
    eff_from_raw = body.get("effective_from")
    eff_to_raw = body.get("effective_to")

    # Priority 20: window shape + overlap resolution (only when inputs well-formed)
    if valid_dt(eff_from_raw):
        new_from = parse_dt(eff_from_raw)
        new_to = parse_dt(eff_to_raw) if (eff_to_raw is not None and valid_dt(eff_to_raw)) else None
        if eff_to_raw is not None and valid_dt(eff_to_raw) and new_to <= new_from:
            raise_error(ERR_OVERLAPPING_PRICE_WINDOW, "effective_from must be < effective_to")
        if new_from < CLOCK.now():
            raise_error(ERR_OVERLAPPING_PRICE_WINDOW, "effective_from must not be in the past")
        if fuel_type in FUEL_TYPES:
            for existing in list(db["fuel_prices"].values()):
                if (existing["site_id"] != site["id"] or existing["fuel_type"] != fuel_type
                        or existing["status"] != "ACTIVE"):
                    continue
                ex_from = parse_dt(existing["effective_from"])
                ex_to = parse_dt(existing["effective_to"]) if existing["effective_to"] else None
                if ex_from == new_from:
                    raise_error(ERR_OVERLAPPING_PRICE_WINDOW,
                                "duplicate effective_from for an ACTIVE same-fuel price")
                if ex_from < new_from:
                    # Truncate only when the windows actually overlap (half-open)
                    if ex_to is None or ex_to > new_from:
                        existing["effective_to"] = fmt_dt(new_from)
                        touch(existing)
                else:
                    # existing starts strictly later: supersede when the new window covers its start
                    if new_to is None or ex_from < new_to:
                        existing["status"] = "SUPERSEDED"
                        touch(existing)

    # Priority 41: final shape validation
    if fuel_type not in FUEL_TYPES:
        raise_error(ERR_INVALID_REQUEST, "fuel_type must be one of DIESEL/GAS_REGULAR/GAS_PREMIUM/DEF")
    if not valid_int(body.get("retail_cents_per_gallon")) or body.get("retail_cents_per_gallon") < 0:
        raise_error(ERR_INVALID_REQUEST, "retail_cents_per_gallon must be a non-negative integer")
    if not valid_dt(eff_from_raw):
        raise_error(ERR_INVALID_REQUEST, "effective_from must be an ISO 8601 datetime")
    if eff_to_raw is not None and not valid_dt(eff_to_raw):
        raise_error(ERR_INVALID_REQUEST, "effective_to must be an ISO 8601 datetime or null")
    if not valid_int(body.get("expected_site_version")):
        raise_error(ERR_INVALID_REQUEST, "expected_site_version is required")

    rec = new_record("fuel_prices", {
        "site_id": site["id"],
        "fuel_type": fuel_type,
        "retail_cents_per_gallon": body["retail_cents_per_gallon"],
        "effective_from": fmt_dt(new_from),
        "effective_to": fmt_dt(new_to) if new_to else None,
        "status": "ACTIVE",
    })
    # Side effects: mirrors recomputed; site version +1 for the whole posting
    recompute_site_mirrors(site)
    touch(site)
    return success_object(public(rec), status=201)


@bp.get("/sites/<sid>/fuel-prices")
def list_fuel_prices(sid):
    authorized(["GeneralManager", "FuelDeskLead", "ShiftManager"])
    require_path_resource("sites", sid)
    filters = {
        "site_id": sid,
        "fuel_type": query_filter("fuel_type", FUEL_TYPES),
        "status": query_filter("status", ["ACTIVE", "SUPERSEDED"]),
    }
    return list_response("fuel_prices", filters)


@bp.get("/fuel-prices/<rid>")
def get_fuel_price(rid):
    authorized(["GeneralManager", "FuelDeskLead"])
    rec = require_path_resource("fuel_prices", rid)
    return success_object(public(rec))
