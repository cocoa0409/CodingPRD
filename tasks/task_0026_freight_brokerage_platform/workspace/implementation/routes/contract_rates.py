"""ContractRate endpoints (PRD §3.2)."""
from __future__ import annotations

import re
from flask import Blueprint, request

import db
from errors import (
    APIError,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_STALE_VERSION,
    ERR_CONTRACT_WINDOW_INVALID,
    ERR_CONTRACT_WINDOW_OVERLAP,
    ERR_UNAUTHORIZED,
)
from middleware import require_auth, get_json_body, current_role, current_user_id
from response import ok_object, ok_array, paginate_params, slice_page, sort_default
from services.validation import (
    require_fields,
    require_int_or_str_int,
    lookup_path_or_404,
    lookup_fk_or_422,
    parse_iso_or_400,
    current_utc_dt,
)


bp = Blueprint("contract_rates", __name__)


ZIP_RE = re.compile(r"^[0-9]{5}$")


@bp.post("/freight/contract-rates")
def create_contract_rate():
    require_auth(["BrokerOps"])()
    body = get_json_body()
    require_fields(body, [
        "shipper_id", "lane_origin", "lane_destination",
        "rate_per_mile_cents", "fuel_surcharge_per_mile_cents",
        "detention_free_minutes", "detention_rate_per_hour_cents",
        "effective_from_utc", "effective_until_utc",
    ])
    # FK existence
    lookup_fk_or_422(db.shippers, body["shipper_id"], "Shipper")

    origin = body["lane_origin"]
    dest = body["lane_destination"]
    if not (isinstance(origin, str) and ZIP_RE.match(origin)):
        raise APIError(ERR_INVALID_REQUEST, 400, "lane_origin must be 5-digit ZIP")
    if not (isinstance(dest, str) and ZIP_RE.match(dest)):
        raise APIError(ERR_INVALID_REQUEST, 400, "lane_destination must be 5-digit ZIP")

    rate = require_int_or_str_int(body["rate_per_mile_cents"], "rate_per_mile_cents")
    fuel = require_int_or_str_int(body["fuel_surcharge_per_mile_cents"], "fuel_surcharge_per_mile_cents")
    det_free = require_int_or_str_int(body["detention_free_minutes"], "detention_free_minutes")
    det_rate = require_int_or_str_int(body["detention_rate_per_hour_cents"], "detention_rate_per_hour_cents")
    if rate <= 0:
        raise APIError(ERR_INVALID_REQUEST, 400, "rate_per_mile_cents must be > 0")
    if fuel < 0:
        raise APIError(ERR_INVALID_REQUEST, 400, "fuel_surcharge_per_mile_cents must be >= 0")
    if det_free < 0:
        raise APIError(ERR_INVALID_REQUEST, 400, "detention_free_minutes must be >= 0")
    if det_rate < 0:
        raise APIError(ERR_INVALID_REQUEST, 400, "detention_rate_per_hour_cents must be >= 0")

    eff_from = parse_iso_or_400(body["effective_from_utc"], "effective_from_utc")
    eff_until = parse_iso_or_400(body["effective_until_utc"], "effective_until_utc")
    if not (eff_from < eff_until):
        raise APIError(ERR_CONTRACT_WINDOW_INVALID, 422, "effective_from_utc must be strictly before effective_until_utc")

    cr = {
        "shipper_id": body["shipper_id"],
        "lane_origin": origin,
        "lane_destination": dest,
        "rate_per_mile_cents": rate,
        "fuel_surcharge_per_mile_cents": fuel,
        "detention_free_minutes": det_free,
        "detention_rate_per_hour_cents": det_rate,
        "effective_from_utc": body["effective_from_utc"],
        "effective_until_utc": body["effective_until_utc"],
        "status": "DRAFT",
    }
    db.stamp_common(cr)
    db.contract_rates[cr["id"]] = cr
    return ok_object(cr, 201)


@bp.get("/freight/contract-rates/<crid>")
def get_contract_rate(crid: str):
    require_auth(["BrokerOps", "Shipper"])()
    cr = lookup_path_or_404(db.contract_rates, crid, "ContractRate")
    if current_role() == "Shipper" and cr.get("shipper_id") != current_user_id():
        raise APIError(ERR_UNAUTHORIZED, 403, "Shipper may only view own contracts")
    return ok_object(cr, 200)


@bp.get("/freight/contract-rates")
def list_contract_rates():
    require_auth(["BrokerOps", "Shipper"])()
    limit, offset = paginate_params(request.args)
    shipper_filter = request.args.get("shipper_id")
    status_filter = request.args.get("status")

    items = list(db.contract_rates.values())
    if current_role() == "Shipper":
        items = [c for c in items if c.get("shipper_id") == current_user_id()]
    if shipper_filter:
        items = [c for c in items if c.get("shipper_id") == shipper_filter]
    if status_filter:
        items = [c for c in items if c.get("status") == status_filter]
    items = sort_default(items)
    page, total = slice_page(items, limit, offset)
    return ok_array(page, limit, offset, total, 200)


@bp.post("/freight/contract-rates/<crid>/activate")
def activate_contract_rate(crid: str):
    require_auth(["BrokerOps"])()
    cr = lookup_path_or_404(db.contract_rates, crid, "ContractRate")
    body = get_json_body()
    require_fields(body, ["expected_contract_rate_version"])
    expected = require_int_or_str_int(body["expected_contract_rate_version"], "expected_contract_rate_version")

    # priority 5: state
    if cr.get("status") != "DRAFT":
        raise APIError(ERR_INVALID_STATE, 409, "ContractRate must be DRAFT to activate")
    # priority 6: OCC
    if int(cr.get("version", 0)) != expected:
        raise APIError(ERR_STALE_VERSION, 412, "expected_contract_rate_version does not match")

    # Business rules: window must bracket current_utc, shipper ACTIVE
    now = current_utc_dt()
    eff_from = db.parse_iso_dt(cr["effective_from_utc"])
    eff_until = db.parse_iso_dt(cr["effective_until_utc"])
    if not (eff_from <= now < eff_until):
        raise APIError(ERR_INVALID_STATE, 409, "ContractRate not active in current window")
    shipper = db.shippers.get(cr["shipper_id"])
    if shipper is None or shipper.get("status") != "ACTIVE":
        raise APIError(ERR_INVALID_STATE, 409, "Shipper not ACTIVE")

    # Overlap check (priority 21): half-open interval, no adjacency overlap.
    for other in db.contract_rates.values():
        if other["id"] == cr["id"]:
            continue
        if other.get("status") != "ACTIVE":
            continue
        if other.get("shipper_id") != cr["shipper_id"]:
            continue
        if other.get("lane_origin") != cr["lane_origin"]:
            continue
        if other.get("lane_destination") != cr["lane_destination"]:
            continue
        o_from = db.parse_iso_dt(other["effective_from_utc"])
        o_until = db.parse_iso_dt(other["effective_until_utc"])
        # [a,b) overlaps [c,d)  iff  a < d AND c < b
        if eff_from < o_until and o_from < eff_until:
            raise APIError(ERR_CONTRACT_WINDOW_OVERLAP, 422, "Overlapping ACTIVE ContractRate exists")

    cr["status"] = "ACTIVE"
    db.bump(cr)
    return ok_object(cr, 200)


@bp.post("/freight/contract-rates/<crid>/terminate")
def terminate_contract_rate(crid: str):
    require_auth(["BrokerOps"])()
    cr = lookup_path_or_404(db.contract_rates, crid, "ContractRate")
    if cr.get("status") != "ACTIVE":
        raise APIError(ERR_INVALID_STATE, 409, "ContractRate must be ACTIVE to terminate")
    cr["status"] = "TERMINATED"
    db.bump(cr)
    return ok_object(cr, 200)
