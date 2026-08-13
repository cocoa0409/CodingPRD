"""Callback verification cases (PRD §3.2): record outcomes, lazy expiry."""

from flask import Blueprint

from db import STORE, iso, now, parse_dt, pub, touch
from errors import (
    ERR_CALLBACK_WINDOW_EXPIRED,
    ERR_INVALID_STATE,
    ApiError,
)
from listing import list_response
from middleware import ALL_INTERNAL, get_body, require_roles, validate_body
from response import ok
from services import (
    audit,
    get_or_404,
    lazy_eval_callback,
    lazy_eval_wire,
    release_reservation,
)

bp = Blueprint("callbacks", __name__, url_prefix="/wire-ops")


@bp.get("/wires/<wid>/callbacks")
def list_callbacks(wid):
    require_roles(*ALL_INTERNAL)
    wire = get_or_404(STORE.wires, wid, "wire")
    lazy_eval_wire(wire)
    items = [c for c in STORE.callbacks.values() if c["wire_id"] == wid]
    return list_response(items)


@bp.get("/callbacks/<cid>")
def get_callback(cid):
    require_roles(*ALL_INTERNAL)
    case = get_or_404(STORE.callbacks, cid, "callback verification case")
    lazy_eval_callback(case)
    return ok(pub(case))


@bp.post("/callbacks/<cid>/record")
def record_callback(cid):
    uid, role = require_roles("WireOperator")
    case = get_or_404(STORE.callbacks, cid, "callback verification case")
    data = get_body()
    validate_body(data, {
        "outcome": ("str", True, {"CONFIRMED", "DENIED", "UNREACHABLE"}),
        "contact_name": ("str", True, None),
        "contact_phone": ("str", True, None),
    })
    if case["status"] != "OPEN":
        raise ApiError(*ERR_INVALID_STATE, "Only an OPEN callback case can be recorded.")
    # Strict window: at or after expires_at the case has already auto-expired.
    if now() >= parse_dt(case["expires_at"]):
        lazy_eval_callback(case)
        raise ApiError(*ERR_CALLBACK_WINDOW_EXPIRED,
                       "The callback verification window has expired.")

    case["contact_name"] = data["contact_name"]
    case["contact_phone"] = data["contact_phone"]
    case["outcome"] = data["outcome"]
    wire = STORE.wires[case["wire_id"]]
    outcome = data["outcome"]
    if outcome == "CONFIRMED":
        case["status"] = "CONFIRMED"
        case["resolved_at"] = iso(now())
        wire["callback_status"] = "VERIFIED"
        touch(wire)
    elif outcome == "DENIED":
        case["status"] = "DENIED"
        case["resolved_at"] = iso(now())
        if wire["status"] in ("CALLBACK_PENDING", "PENDING_APPROVAL", "REPAIR", "INITIATED", "APPROVED"):
            release_reservation(wire)
            wire["status"] = "CANCELLED"
        wire["callback_status"] = "NONE"
        touch(wire)
        audit("callback.denied", "CallbackVerification", cid, wire["id"],
              "status: OPEN -> DENIED; wire CANCELLED", actor_user_id=uid, actor_role=role)
    # UNREACHABLE is non-terminal: the case remains OPEN and retryable.
    touch(case)
    return ok(pub(case))
