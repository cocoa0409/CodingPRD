"""Carrier CRUD + qualification lifecycle."""

from __future__ import annotations

from flask import Blueprint, g, request

from ..auth import require_auth
from ..envelope import ok_array, ok_object
from ..errors import (
    ApiError,
    ERR_CARRIER_AUTHORITY_DUPLICATE,
    ERR_CARRIER_HAS_OPEN_LOADS,
    ERR_CARRIER_NOT_FOUND,
    ERR_CARRIER_NOT_PENDING,
    ERR_CARRIER_NOT_SUSPENDED,
    ERR_INSUFFICIENT_PERMISSIONS,
    ERR_INSURANCE_EXPIRED,
    ERR_INVALID_CARRIER_AUTHORITY,
    ERR_INVALID_REQUEST,
    ERR_SAFETY_SCORE_TOO_LOW,
)
from ..helpers import (
    check_version,
    ensure_carrier_self_access,
    get_body,
    get_brokerage_or_404,
    get_scoped,
    optional_field,
    paginate,
    parse_pagination,
    require_field,
    require_iso,
)
from ..services.calc import SAFETY_REQUALIFY_THRESHOLD
from ..store import store
from ..timeutil import iso_now, parse_iso


carriers_bp = Blueprint("carriers", __name__, url_prefix="/brokerages")


def _has_open_load_for(carrier_id: str) -> bool:
    open_states = {"TENDERED", "ACCEPTED", "IN_TRANSIT"}
    for ld in store.loads.values():
        if ld.get("carrier_id") == carrier_id and ld.get("status") in open_states:
            return True
    return False


@carriers_bp.post("/<brokerage_id>/carriers")
@require_auth(["CarrierOps"])
def create_carrier(brokerage_id):
    body = get_body()
    legal_name = require_field(body, "legal_name", str)
    mc_number = require_field(body, "mc_number", str)
    usdot_number = require_field(body, "usdot_number", str)
    insurance_expires_on = require_iso(body, "insurance_expires_on")
    smartway_certified = optional_field(body, "smartway_certified", bool, default=False)

    with store.lock:
        get_brokerage_or_404(brokerage_id)

        # MC#/USDOT uniqueness across non-REVOKED carriers in this brokerage
        for c in store.carriers.values():
            if c.get("brokerage_id") != brokerage_id:
                continue
            if c.get("status") == "REVOKED":
                continue
            if c.get("mc_number") == mc_number or c.get("usdot_number") == usdot_number:
                raise ApiError(
                    ERR_CARRIER_AUTHORITY_DUPLICATE,
                    409,
                    "mc_number or usdot_number already in use.",
                )

        c = {
            "brokerage_id": brokerage_id,
            "legal_name": legal_name,
            "mc_number": mc_number,
            "usdot_number": usdot_number,
            "insurance_expires_on": iso_now(insurance_expires_on),
            "smartway_certified": bool(smartway_certified),
            "safety_score": 1000,
            "status": "PENDING_QUALIFICATION",
        }
        store.stamp_create(c)
        store.carriers[c["id"]] = c
    return ok_object(c, status=201)


@carriers_bp.get("/<brokerage_id>/carriers")
@require_auth(["BrokerOps", "CarrierOps", "PlatformAdmin"])
def list_carriers(brokerage_id):
    limit, offset = parse_pagination()
    status_filter = request.args.get("status")
    smartway_filter = request.args.get("smartway_certified")
    with store.lock:
        get_brokerage_or_404(brokerage_id)
        rows = [c for c in store.carriers.values() if c.get("brokerage_id") == brokerage_id]
        if status_filter:
            rows = [c for c in rows if c.get("status") == status_filter]
        if smartway_filter is not None:
            wanted = smartway_filter.lower() == "true"
            rows = [c for c in rows if bool(c.get("smartway_certified")) == wanted]
        page, total, has_more = paginate(rows, limit, offset)
    return ok_array(page, limit=limit, offset=offset, total_count=total, has_more=has_more)


@carriers_bp.get("/<brokerage_id>/carriers/<carrier_id>")
@require_auth(["BrokerOps", "CarrierOps", "CarrierUser", "PlatformAdmin"])
def get_carrier(brokerage_id, carrier_id):
    with store.lock:
        get_brokerage_or_404(brokerage_id)
        c = get_scoped(store.carriers, carrier_id, brokerage_id, ERR_CARRIER_NOT_FOUND)
        ensure_carrier_self_access(carrier_id)
    return ok_object(c)


@carriers_bp.post("/<brokerage_id>/carriers/<carrier_id>/qualify")
@require_auth(["CarrierOps"])
def qualify_carrier(brokerage_id, carrier_id):
    body = get_body()
    with store.lock:
        bk = get_brokerage_or_404(brokerage_id)
        c = get_scoped(store.carriers, carrier_id, brokerage_id, ERR_CARRIER_NOT_FOUND)
        check_version(c, body)

        if c.get("status") != "PENDING_QUALIFICATION":
            raise ApiError(ERR_CARRIER_NOT_PENDING, 409, "Carrier not in PENDING_QUALIFICATION.")

        if not (c.get("mc_number") or "").strip() or not (c.get("usdot_number") or "").strip():
            raise ApiError(
                ERR_INVALID_CARRIER_AUTHORITY,
                400,
                "mc_number and usdot_number must be non-empty.",
            )

        clock_now = parse_iso(bk["clock_now_iso"])
        insurance_until = parse_iso(c["insurance_expires_on"])
        if insurance_until <= clock_now:
            raise ApiError(ERR_INSURANCE_EXPIRED, 409, "Insurance expired.")

        if c.get("safety_score") is None:
            c["safety_score"] = 1000
        c["status"] = "QUALIFIED"
        store.bump(c)
    return ok_object(c)


@carriers_bp.post("/<brokerage_id>/carriers/<carrier_id>/suspend")
@require_auth(["CarrierOps"])
def suspend_carrier(brokerage_id, carrier_id):
    body = get_body()
    with store.lock:
        get_brokerage_or_404(brokerage_id)
        c = get_scoped(store.carriers, carrier_id, brokerage_id, ERR_CARRIER_NOT_FOUND)
        check_version(c, body)

        # Manual suspension is only allowed from QUALIFIED (PRD §3.3).  Other
        # transitions to SUSPENDED (auto) are handled internally.
        if c.get("status") != "QUALIFIED":
            # Mapping: if not QUALIFIED, no specific error in scaffold for
            # manual-suspend-on-wrong-state — closest is ERR_CARRIER_NOT_QUALIFIED.
            from ..errors import ERR_CARRIER_NOT_QUALIFIED

            raise ApiError(ERR_CARRIER_NOT_QUALIFIED, 409, "Carrier not in QUALIFIED.")

        if _has_open_load_for(carrier_id):
            raise ApiError(ERR_CARRIER_HAS_OPEN_LOADS, 409, "Carrier has open loads.")

        c["status"] = "SUSPENDED"
        store.bump(c)
    return ok_object(c)


@carriers_bp.post("/<brokerage_id>/carriers/<carrier_id>/requalify")
@require_auth(["CarrierOps"])
def requalify_carrier(brokerage_id, carrier_id):
    body = get_body()
    with store.lock:
        bk = get_brokerage_or_404(brokerage_id)
        c = get_scoped(store.carriers, carrier_id, brokerage_id, ERR_CARRIER_NOT_FOUND)
        check_version(c, body)

        if c.get("status") != "SUSPENDED":
            raise ApiError(ERR_CARRIER_NOT_SUSPENDED, 409, "Carrier not in SUSPENDED.")

        clock_now = parse_iso(bk["clock_now_iso"])
        insurance_until = parse_iso(c["insurance_expires_on"])
        if insurance_until <= clock_now:
            raise ApiError(ERR_INSURANCE_EXPIRED, 409, "Insurance expired.")

        if int(c.get("safety_score", 0)) < SAFETY_REQUALIFY_THRESHOLD:
            raise ApiError(ERR_SAFETY_SCORE_TOO_LOW, 409, "Safety score below threshold.")

        c["status"] = "QUALIFIED"
        store.bump(c)
    return ok_object(c)


@carriers_bp.post("/<brokerage_id>/carriers/<carrier_id>/revoke")
@require_auth(["CarrierOps"])
def revoke_carrier(brokerage_id, carrier_id):
    body = get_body()
    with store.lock:
        get_brokerage_or_404(brokerage_id)
        c = get_scoped(store.carriers, carrier_id, brokerage_id, ERR_CARRIER_NOT_FOUND)
        check_version(c, body)

        if c.get("status") != "SUSPENDED":
            raise ApiError(ERR_CARRIER_NOT_SUSPENDED, 409, "Carrier not in SUSPENDED.")

        c["status"] = "REVOKED"
        store.bump(c)
    return ok_object(c)
