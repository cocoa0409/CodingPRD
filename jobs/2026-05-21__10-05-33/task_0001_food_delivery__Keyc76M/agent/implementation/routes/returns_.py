"""Return endpoints: read, approve, reject, escalate, reopen."""

from flask import Blueprint, request

import auth
import envelope
import projection
import state
import validators
from services import returns_ as svc


bp = Blueprint("returns_", __name__)


def _read_payload():
    try:
        return request.get_json(silent=True) or {}
    except Exception:
        return {}


@bp.route("/api/returns/<rid>", methods=["GET"])
def get_return(rid):
    user_id, role = auth.headers()
    if not user_id:
        return envelope.auth_required()
    if role not in ("PlatformAdmin", "Customer", "Restaurant", "CustomerService"):
        return envelope.forbidden()
    with state.lock():
        ret = state.STORE.returns.get(rid)
        if ret is None:
            return envelope.not_found("Return not found.")
        order = state.STORE.orders.get(ret["order_id"])
        if role == "Customer" and (order is None
                                   or user_id != order["customer_id"]):
            return envelope.forbidden()
        if role == "Restaurant" and (order is None
                                     or user_id != order["restaurant_id"]):
            return envelope.forbidden()
        return envelope.success(projection.render(ret))


@bp.route("/api/returns/<rid>/approve", methods=["POST"])
def approve(rid):
    user_id, role = auth.headers()
    if not user_id:
        return envelope.auth_required()
    if role != "CustomerService":
        return envelope.forbidden()
    payload = _read_payload()
    err = validators.require_body(payload)
    if err:
        return err
    return svc.approve(rid, user_id, payload)


@bp.route("/api/returns/<rid>/reject", methods=["POST"])
def reject(rid):
    user_id, role = auth.headers()
    if not user_id:
        return envelope.auth_required()
    if role != "CustomerService":
        return envelope.forbidden()
    return svc.reject(rid, user_id)


@bp.route("/api/returns/<rid>/escalate", methods=["POST"])
def escalate(rid):
    user_id, role = auth.headers()
    if not user_id:
        return envelope.auth_required()
    if role != "CustomerService":
        return envelope.forbidden()
    return svc.escalate(rid, user_id)


@bp.route("/api/returns/<rid>/reopen", methods=["POST"])
def reopen(rid):
    user_id, role = auth.headers()
    if not user_id:
        return envelope.auth_required()
    if role != "CustomerService":
        return envelope.forbidden()
    return svc.reopen(rid, user_id)
