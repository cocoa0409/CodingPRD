"""Rate contracts: create / list / terminate."""

from __future__ import annotations

from flask import Blueprint, request

from ..auth import require_auth
from ..envelope import ok_array, ok_object
from ..errors import (
    ApiError,
    ERR_INVALID_REQUEST,
    ERR_RATE_CONTRACT_NOT_FOUND,
    ERR_RATE_CONTRACT_OVERLAP,
    ERR_SHIPPER_NOT_FOUND,
)
from ..helpers import (
    check_version,
    get_body,
    get_brokerage_or_404,
    get_scoped,
    paginate,
    parse_pagination,
    require_field,
    require_iso,
)
from ..store import store
from ..timeutil import iso_now, parse_iso


rate_contracts_bp = Blueprint("rate_contracts", __name__, url_prefix="/brokerages")


VALID_EQUIPMENT = {"DRY_VAN", "REEFER", "FLATBED"}


@rate_contracts_bp.post("/<brokerage_id>/rate-contracts")
@require_auth(["BrokerOps"])
def create_rate_contract(brokerage_id):
    body = get_body()
    shipper_id = require_field(body, "shipper_id", str)
    lane_origin_zip = require_field(body, "lane_origin_zip", str)
    lane_destination_zip = require_field(body, "lane_destination_zip", str)
    equipment_type = require_field(body, "equipment_type", str)
    if equipment_type not in VALID_EQUIPMENT:
        raise ApiError(ERR_INVALID_REQUEST, 400, "Invalid equipment_type.")

    if "flat_rate_cents" not in body or body["flat_rate_cents"] is None:
        raise ApiError(ERR_INVALID_REQUEST, 400, "Missing required field: flat_rate_cents")
    flat_rate = body["flat_rate_cents"]
    if isinstance(flat_rate, bool) or not isinstance(flat_rate, int) or flat_rate < 0:
        raise ApiError(ERR_INVALID_REQUEST, 400, "flat_rate_cents must be a non-negative integer.")

    effective_from = require_iso(body, "effective_from")
    effective_to = require_iso(body, "effective_to")
    if effective_to <= effective_from:
        raise ApiError(ERR_INVALID_REQUEST, 400, "effective_to must be strictly after effective_from.")

    with store.lock:
        get_brokerage_or_404(brokerage_id)
        # Body-referenced shipper must exist in this brokerage
        get_scoped(store.shippers, shipper_id, brokerage_id, ERR_SHIPPER_NOT_FOUND)

        # Overlap check: any ACTIVE row on the same shipper+lane+equipment whose
        # [effective_from, effective_to) intersects ours?
        for r in store.rate_contracts.values():
            if r.get("brokerage_id") != brokerage_id:
                continue
            if r.get("status") != "ACTIVE":
                continue
            if r.get("shipper_id") != shipper_id:
                continue
            if r.get("lane_origin_zip") != lane_origin_zip:
                continue
            if r.get("lane_destination_zip") != lane_destination_zip:
                continue
            if r.get("equipment_type") != equipment_type:
                continue
            ef = parse_iso(r["effective_from"])
            et = parse_iso(r["effective_to"])
            if effective_from < et and ef < effective_to:
                raise ApiError(ERR_RATE_CONTRACT_OVERLAP, 409, "Overlapping active contract.")

        rc = {
            "brokerage_id": brokerage_id,
            "shipper_id": shipper_id,
            "lane_origin_zip": lane_origin_zip,
            "lane_destination_zip": lane_destination_zip,
            "equipment_type": equipment_type,
            "flat_rate_cents": int(flat_rate),
            "effective_from": iso_now(effective_from),
            "effective_to": iso_now(effective_to),
            "status": "ACTIVE",
        }
        store.stamp_create(rc)
        store.rate_contracts[rc["id"]] = rc
    return ok_object(rc, status=201)


@rate_contracts_bp.get("/<brokerage_id>/rate-contracts")
@require_auth(["BrokerOps", "ShipperUser", "PlatformAdmin"])
def list_rate_contracts(brokerage_id):
    limit, offset = parse_pagination()
    shipper_id = request.args.get("shipper_id")
    status_filter = request.args.get("status")
    with store.lock:
        get_brokerage_or_404(brokerage_id)
        rows = [r for r in store.rate_contracts.values() if r.get("brokerage_id") == brokerage_id]
        if shipper_id:
            rows = [r for r in rows if r.get("shipper_id") == shipper_id]
        if status_filter:
            rows = [r for r in rows if r.get("status") == status_filter]
        page, total, has_more = paginate(rows, limit, offset)
    return ok_array(page, limit=limit, offset=offset, total_count=total, has_more=has_more)


@rate_contracts_bp.post("/<brokerage_id>/rate-contracts/<contract_id>/terminate")
@require_auth(["BrokerOps"])
def terminate_rate_contract(brokerage_id, contract_id):
    body = get_body()
    with store.lock:
        get_brokerage_or_404(brokerage_id)
        rc = get_scoped(store.rate_contracts, contract_id, brokerage_id, ERR_RATE_CONTRACT_NOT_FOUND)
        check_version(rc, body)
        rc["status"] = "TERMINATED"
        store.bump(rc)
    return ok_object(rc)
