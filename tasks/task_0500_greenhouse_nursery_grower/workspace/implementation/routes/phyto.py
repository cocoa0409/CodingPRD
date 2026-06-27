import re
from flask import Blueprint, request

from core import (store, require, get_body, get_or_404, ok, ok_list, paginate, common_create, clock,
                  req_str, req_datetime, ApiError, ERR_NOT_FOUND, ERR_INVALID_REQUEST, ERR_FORBIDDEN)

bp = Blueprint("phyto", __name__)

ROLES = ["SalesCoordinator", "Broker"]


@bp.post("/nursery/phyto-certificates")
def issue_cert():
    require(["SalesCoordinator"])
    body = get_body()
    raw_bid = body.get("broker_id")
    if isinstance(raw_bid, str) and raw_bid not in store.brokers:
        raise ApiError(ERR_NOT_FOUND, "Broker not found")
    broker_id = req_str(body, "broker_id")
    certificate_number = req_str(body, "certificate_number")
    origin_state = req_str(body, "origin_state")
    if not re.fullmatch(r"[A-Z]{2}", origin_state):
        raise ApiError(ERR_INVALID_REQUEST, "origin_state must be two uppercase letters")
    valid_until = req_datetime(body, "valid_until")
    if broker_id not in store.brokers:
        raise ApiError(ERR_NOT_FOUND, "Broker not found")
    broker = store.brokers[broker_id]
    cert = common_create({
        "broker_id": broker_id,
        "certificate_number": certificate_number,
        "origin_state": origin_state,
        "destination_state": broker["ship_to_state"],
        "inspected_at": clock.now_iso(),
        "valid_until": valid_until,
        "status": "VALID",
    })
    store.phyto_certs[cert["id"]] = cert
    return ok(cert, 201)


@bp.get("/nursery/phyto-certificates/<cid>")
def get_cert(cid):
    uid, role = require(ROLES)
    cert = get_or_404(store.phyto_certs, cid)
    if role == "Broker" and cert["broker_id"] != uid:
        raise ApiError(ERR_FORBIDDEN, "Broker may only read its own certificates")
    return ok(cert)


@bp.get("/nursery/phyto-certificates")
def list_certs():
    uid, role = require(ROLES)
    rows = list(store.phyto_certs.values())
    if role == "Broker":
        rows = [r for r in rows if r["broker_id"] == uid]
    for key in ("broker_id", "status"):
        val = request.args.get(key)
        if val is not None:
            rows = [r for r in rows if r[key] == val]
    page, limit, offset, total = paginate(rows)
    return ok_list(page, limit, offset, total)
