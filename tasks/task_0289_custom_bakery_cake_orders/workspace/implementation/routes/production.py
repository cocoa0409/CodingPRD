"""Production progression: start-production, mark-ready, fulfill."""
from flask import Blueprint

import serializers as S
from db import store
from errors import err, ERR_INVALID_STATE, ERR_PROOF_NOT_APPROVED
from middleware import require_auth
from response import success
from services.orders import get_order_or_404

bp = Blueprint("production", __name__)


def _has_committed_reservation(oid):
    return any(r["order_id"] == oid and r["status"] == "COMMITTED"
               for r in store.reservations.values())


@bp.route("/orders/<oid>/start-production", methods=["POST"])
@require_auth(["BakeryStaff"])
def start_production(oid):
    order = get_order_or_404(oid)

    # proof gate (priority 13): before a proof is APPROVED.
    if order["production_status"] != "PROOF_APPROVED":
        raise err(ERR_PROOF_NOT_APPROVED, "proof must be approved to start production")

    # a COMMITTED slot must exist and payment must be PAID_IN_FULL.
    if not _has_committed_reservation(oid):
        raise err(ERR_INVALID_STATE, "a committed slot reservation is required")
    if order["payment_status"] != "PAID_IN_FULL":
        raise err(ERR_INVALID_STATE, "order must be paid in full")

    order["production_status"] = "IN_PRODUCTION"
    store.touch(order)
    return success(S.order(order), status=200)


@bp.route("/orders/<oid>/mark-ready", methods=["POST"])
@require_auth(["BakeryStaff"])
def mark_ready(oid):
    order = get_order_or_404(oid)
    if order["production_status"] != "IN_PRODUCTION":
        raise err(ERR_INVALID_STATE, "order not in production")
    order["production_status"] = "READY"
    store.touch(order)
    return success(S.order(order), status=200)


@bp.route("/orders/<oid>/fulfill", methods=["POST"])
@require_auth(["BakeryStaff"])
def fulfill(oid):
    order = get_order_or_404(oid)
    if order["production_status"] != "READY":
        raise err(ERR_INVALID_STATE, "order not ready")
    if not _has_committed_reservation(oid):
        raise err(ERR_INVALID_STATE, "a committed slot reservation is required")
    order["production_status"] = "FULFILLED"
    store.touch(order)
    return success(S.order(order), status=200)
