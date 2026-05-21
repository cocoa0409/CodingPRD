"""Customer endpoints."""

from flask import Blueprint, request

import auth
import envelope
import projection
import state
import validators
from services import customers as svc


bp = Blueprint("customers", __name__)


def _read_payload():
    try:
        return request.get_json(silent=True) or {}
    except Exception:
        return {}


@bp.route("/api/customers", methods=["POST"])
def register_customer():
    user_id, role = auth.headers()
    if not user_id:
        return envelope.auth_required()
    if role not in ("PlatformAdmin", "CustomerService"):
        return envelope.forbidden()

    payload = _read_payload()
    err = validators.require_body(payload)
    if err:
        return err

    for field in ("name", "phone", "address", "lat", "lng"):
        if field not in payload:
            return envelope.validation(f"Missing required field '{field}'.")

    name = payload["name"]
    phone = payload["phone"]
    address = payload["address"]
    lat = payload["lat"]
    lng = payload["lng"]

    if not isinstance(name, str) or not name:
        return envelope.validation("name must be a non-empty string.")
    if not isinstance(phone, str) or not phone:
        return envelope.validation("phone must be a non-empty string.")
    if not isinstance(address, str) or not address:
        return envelope.validation("address must be a non-empty string.")
    if not (isinstance(lat, (int, float)) and -90 <= float(lat) <= 90 and not isinstance(lat, bool)):
        return envelope.validation("lat must be a number in [-90, 90].")
    if not (isinstance(lng, (int, float)) and -180 <= float(lng) <= 180 and not isinstance(lng, bool)):
        return envelope.validation("lng must be a number in [-180, 180].")

    with state.lock():
        if phone in state.STORE.customer_phones:
            return envelope.error(
                409, "ERR_INVALID_STATE", "phone already registered to a customer."
            )
        rec = svc.new_customer(name, phone, address, float(lat), float(lng))
        return envelope.created(projection.render(rec))


@bp.route("/api/customers/<cid>", methods=["GET"])
def get_customer(cid):
    user_id, role = auth.headers()
    if not user_id:
        return envelope.auth_required()
    if role not in ("PlatformAdmin", "Customer", "CustomerService"):
        return envelope.forbidden()
    with state.lock():
        rec = state.STORE.customers.get(cid)
        if rec is None:
            return envelope.not_found("Customer not found.")
        if role == "Customer" and user_id != cid:
            return envelope.forbidden()
        return envelope.success(projection.render(rec))
