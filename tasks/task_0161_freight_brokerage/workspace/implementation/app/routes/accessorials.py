"""Accessorial-charge approve / deny endpoints (flat path under brokerage)."""

from __future__ import annotations

from flask import Blueprint

from ..auth import require_auth
from ..envelope import ok_object
from ..errors import (
    ApiError,
    ERR_ACCESSORIAL_CHARGE_NOT_FOUND,
    ERR_ACCESSORIAL_NOT_REQUESTED,
)
from ..helpers import check_version, get_body, get_brokerage_or_404, get_scoped
from ..store import store


accessorials_bp = Blueprint("accessorials", __name__, url_prefix="/brokerages")


@accessorials_bp.post("/<brokerage_id>/accessorial-charges/<charge_id>/approve")
@require_auth(["BrokerOps"])
def approve_accessorial(brokerage_id, charge_id):
    body = get_body()
    with store.lock:
        get_brokerage_or_404(brokerage_id)
        ac = get_scoped(store.accessorial_charges, charge_id, brokerage_id, ERR_ACCESSORIAL_CHARGE_NOT_FOUND)
        check_version(ac, body)
        if ac.get("status") != "REQUESTED":
            raise ApiError(ERR_ACCESSORIAL_NOT_REQUESTED, 409, "Accessorial not in REQUESTED.")
        ac["status"] = "APPROVED"
        store.bump(ac)
    return ok_object(ac)


@accessorials_bp.post("/<brokerage_id>/accessorial-charges/<charge_id>/deny")
@require_auth(["BrokerOps"])
def deny_accessorial(brokerage_id, charge_id):
    body = get_body()
    with store.lock:
        get_brokerage_or_404(brokerage_id)
        ac = get_scoped(store.accessorial_charges, charge_id, brokerage_id, ERR_ACCESSORIAL_CHARGE_NOT_FOUND)
        check_version(ac, body)
        if ac.get("status") != "REQUESTED":
            raise ApiError(ERR_ACCESSORIAL_NOT_REQUESTED, 409, "Accessorial not in REQUESTED.")
        ac["status"] = "DENIED"
        store.bump(ac)
    return ok_object(ac)
