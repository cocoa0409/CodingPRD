"""QuoteRequest endpoints (PRD §3.3, §3.4)."""
from __future__ import annotations

import re
from datetime import timedelta

from flask import Blueprint, request

import db
from errors import (
    APIError,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_STALE_VERSION,
    ERR_TIME_WINDOW_INVALID,
    ERR_QUOTE_WINDOW_OVERLAP,
    ERR_CREDIT_LIMIT_EXCEEDED,
    ERR_FK_NOT_FOUND,
    ERR_INSURANCE_EXPIRED,
    ERR_SMARTWAY_INELIGIBLE,
    ERR_CONTRACT_RATE_STALE,
    ERR_UNAUTHORIZED,
)
from middleware import require_auth, get_json_body, current_role, current_user_id
from response import ok_object, ok_array, paginate_params, slice_page, sort_default
from services.validation import (
    require_fields,
    require_enum,
    require_int_or_str_int,
    lookup_path_or_404,
    lookup_fk_or_422,
    parse_iso_or_400,
    current_utc_dt,
)
from services.calculations import (
    compute_quote_total,
    estimate_quote_for_credit_guard,
)


bp = Blueprint("quote_requests", __name__)

ZIP_RE = re.compile(r"^[0-9]{5}$")
EQUIPMENT_VALUES = {"DRY_VAN", "REEFER", "FLATBED"}


@bp.post("/freight/quote-requests")
def create_quote_request():
    require_auth(["Shipper", "BrokerOps"])()
    body = get_json_body()
    require_fields(body, [
        "shipper_id", "lane_origin", "lane_destination",
        "distance_miles", "pickup_window_start_utc", "pickup_window_end_utc",
        "requested_equipment",
    ])
    # FK existence
    shipper = lookup_fk_or_422(db.shippers, body["shipper_id"], "Shipper")

    # Shipper-role ownership: shipper may only quote for own shipper_id.
    if current_role() == "Shipper" and body["shipper_id"] != current_user_id():
        raise APIError(ERR_UNAUTHORIZED, 403, "Shipper may only request quotes for own shipper_id")

    origin = body["lane_origin"]
    dest = body["lane_destination"]
    if not (isinstance(origin, str) and ZIP_RE.match(origin)):
        raise APIError(ERR_INVALID_REQUEST, 400, "lane_origin must be 5-digit ZIP")
    if not (isinstance(dest, str) and ZIP_RE.match(dest)):
        raise APIError(ERR_INVALID_REQUEST, 400, "lane_destination must be 5-digit ZIP")

    distance = require_int_or_str_int(body["distance_miles"], "distance_miles")
    if distance <= 0:
        raise APIError(ERR_INVALID_REQUEST, 400, "distance_miles must be > 0")

    equipment = body["requested_equipment"]
    require_enum(equipment, EQUIPMENT_VALUES, "requested_equipment")

    requires_smartway = bool(body.get("requires_smartway", False))

    start_dt = parse_iso_or_400(body["pickup_window_start_utc"], "pickup_window_start_utc")
    end_dt = parse_iso_or_400(body["pickup_window_end_utc"], "pickup_window_end_utc")
    now = current_utc_dt()

    # priority 11: window validity (start < end and start > current_utc)
    if not (start_dt < end_dt) or not (start_dt > now):
        raise APIError(ERR_TIME_WINDOW_INVALID, 422, "Invalid pickup window")

    # priority 22: overlap with another OPEN quote on same lane (120-min left buffer)
    BUFFER = timedelta(minutes=120)
    new_eff_start = start_dt - BUFFER
    for other in db.quote_requests.values():
        if other.get("status") != "OPEN":
            continue
        if other.get("shipper_id") != body["shipper_id"]:
            continue
        if other.get("lane_origin") != origin or other.get("lane_destination") != dest:
            continue
        o_start = db.parse_iso_dt(other["pickup_window_start_utc"]) - BUFFER
        o_end = db.parse_iso_dt(other["pickup_window_end_utc"])
        # closed-left buffered overlap: a <= d AND c <= b (adjacency at buffered edge counts)
        if new_eff_start <= o_end and o_start <= end_dt:
            raise APIError(ERR_QUOTE_WINDOW_OVERLAP, 422, "Buffered pickup window overlaps another OPEN quote")

    # priority 17: credit guard with conservative SPOT estimate
    estimated = estimate_quote_for_credit_guard(distance, equipment)
    if int(shipper.get("open_ar_cents", 0)) + estimated > int(shipper.get("credit_limit_cents", 0)):
        raise APIError(ERR_CREDIT_LIMIT_EXCEEDED, 422, "Credit limit would be exceeded")

    # rate_mode and quoted_total_cents
    priced = compute_quote_total(
        shipper_id=body["shipper_id"],
        lane_origin=origin,
        lane_destination=dest,
        distance_miles=distance,
        pickup_window_start_utc=body["pickup_window_start_utc"],
        requested_equipment=equipment,
    )

    qr = {
        "shipper_id": body["shipper_id"],
        "lane_origin": origin,
        "lane_destination": dest,
        "distance_miles": distance,
        "pickup_window_start_utc": body["pickup_window_start_utc"],
        "pickup_window_end_utc": body["pickup_window_end_utc"],
        "requested_equipment": equipment,
        "requires_smartway": requires_smartway,
        "rate_mode": priced["rate_mode"],
        "contract_rate_id": priced["contract_rate_id"],
        "contract_rate_version": priced["contract_rate_version"],
        "quoted_total_cents": priced["quoted_total_cents"],
        "status": "OPEN",
        "expires_at_utc": body["pickup_window_start_utc"],
    }
    db.stamp_common(qr)
    db.quote_requests[qr["id"]] = qr
    return ok_object(qr, 201)


@bp.get("/freight/quote-requests/<qid>")
def get_quote_request(qid: str):
    require_auth(["Shipper", "BrokerOps"])()
    qr = lookup_path_or_404(db.quote_requests, qid, "QuoteRequest")
    if current_role() == "Shipper" and qr.get("shipper_id") != current_user_id():
        raise APIError(ERR_UNAUTHORIZED, 403, "Shipper may only view own quotes")
    return ok_object(qr, 200)


@bp.get("/freight/quote-requests")
def list_quote_requests():
    require_auth(["Shipper", "BrokerOps"])()
    limit, offset = paginate_params(request.args)
    shipper_filter = request.args.get("shipper_id")
    status_filter = request.args.get("status")
    rate_mode_filter = request.args.get("rate_mode")
    cr_filter = request.args.get("contract_rate_id")
    items = list(db.quote_requests.values())
    if current_role() == "Shipper":
        items = [q for q in items if q.get("shipper_id") == current_user_id()]
    if shipper_filter:
        items = [q for q in items if q.get("shipper_id") == shipper_filter]
    if status_filter:
        items = [q for q in items if q.get("status") == status_filter]
    if rate_mode_filter:
        items = [q for q in items if q.get("rate_mode") == rate_mode_filter]
    if cr_filter:
        items = [q for q in items if q.get("contract_rate_id") == cr_filter]
    items = sort_default(items)
    page, total = slice_page(items, limit, offset)
    return ok_array(page, limit, offset, total, 200)


@bp.post("/freight/quote-requests/<qid>/award")
def award_quote(qid: str):
    require_auth(["BrokerOps"])()
    qr = lookup_path_or_404(db.quote_requests, qid, "QuoteRequest")
    body = get_json_body()
    require_fields(body, ["carrier_id", "expected_quote_request_version"])
    expected = require_int_or_str_int(body["expected_quote_request_version"], "expected_quote_request_version")
    carrier_id = body["carrier_id"]
    # FK existence on body
    carrier = lookup_fk_or_422(db.carriers, carrier_id, "Carrier")

    # priority 5: state
    if qr.get("status") != "OPEN":
        raise APIError(ERR_INVALID_STATE, 409, "QuoteRequest must be OPEN to award")
    # priority 6: OCC
    if int(qr.get("version", 0)) != expected:
        raise APIError(ERR_STALE_VERSION, 412, "expected_quote_request_version does not match")
    # Expiry check: current_utc < expires_at_utc
    now = current_utc_dt()
    expires_at = db.parse_iso_dt(qr["expires_at_utc"])
    if not (now < expires_at):
        raise APIError(ERR_INVALID_STATE, 409, "Quote has expired")
    # Carrier qualified
    if carrier.get("qualification_status") != "QUALIFIED":
        raise APIError(ERR_INVALID_STATE, 409, "Carrier is not QUALIFIED")
    # priority 8: insurance not expired
    expiry = db.parse_iso_dt(carrier.get("insurance_expiry_utc"))
    if expiry is None or expiry <= now:
        raise APIError(ERR_INSURANCE_EXPIRED, 422, "Carrier insurance expired")
    # priority 9: smartway
    if qr.get("requires_smartway"):
        if carrier.get("smartway_tier") not in {"BRONZE", "SILVER", "GOLD"}:
            raise APIError(ERR_SMARTWAY_INELIGIBLE, 422, "Carrier smartway_tier ineligible")
    # priority 10: contract pinning when CONTRACT mode
    if qr.get("rate_mode") == "CONTRACT":
        cr = db.contract_rates.get(qr.get("contract_rate_id"))
        if cr is None:
            raise APIError(ERR_CONTRACT_RATE_STALE, 422, "Pinned ContractRate no longer exists")
        if cr.get("status") != "ACTIVE":
            raise APIError(ERR_CONTRACT_RATE_STALE, 422, "Pinned ContractRate not ACTIVE")
        if int(cr.get("version", 0)) != int(qr.get("contract_rate_version", -1)):
            raise APIError(ERR_CONTRACT_RATE_STALE, 422, "ContractRate version drift")

    # All checks passed — atomically advance quote + create Load.
    qr["status"] = "AWARDED"
    db.bump(qr)

    load = {
        "quote_request_id": qr["id"],
        "carrier_id": carrier_id,
        "agreed_rate_cents": int(qr["quoted_total_cents"]),
        "detention_charge_cents": 0,
        "accessorial_total_cents": 0,
        "pod_received_at_utc": None,
        "actual_pickup_at_utc": None,
        "actual_delivery_at_utc": None,
        "status": "AWARDED",
    }
    db.stamp_common(load)
    db.loads[load["id"]] = load
    return ok_object(load, 200)


@bp.post("/freight/quote-requests/<qid>/withdraw")
def withdraw_quote(qid: str):
    require_auth(["Shipper"])()
    qr = lookup_path_or_404(db.quote_requests, qid, "QuoteRequest")
    if qr.get("shipper_id") != current_user_id():
        raise APIError(ERR_UNAUTHORIZED, 403, "Shipper may only withdraw own quotes")
    if qr.get("status") != "OPEN":
        raise APIError(ERR_INVALID_STATE, 409, "QuoteRequest must be OPEN to withdraw")
    qr["status"] = "WITHDRAWN"
    db.bump(qr)
    return ok_object(qr, 200)
