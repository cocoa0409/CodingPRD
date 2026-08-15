"""CurativeRequirement endpoints: raise, satisfy, and waive (with
criticality and segregation-of-duties safety checks)."""

import db
from errors import (
    ApiError,
    ERR_ORDER_NOT_FOUND,
    ERR_DOCUMENT_NOT_FOUND,
    ERR_CURATIVE_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_ORDER_TERMINAL,
    ERR_CRITICAL_NOT_WAIVABLE,
    ERR_SOD_WAIVER_FORBIDDEN,
)
from middleware import authenticate, ALL_ROLES
from response import success_obj, success_list
from routes import make_blueprint
from services import TERMINAL_ORDER_STATES, curative_view
from util import (
    body_json,
    check_shape,
    pagination_params,
    paginate,
    apply_filters,
    require_fk,
)

bp = make_blueprint("curatives")

_CREATE_SPEC = {
    "order_id": {"type": "string", "required": True},
    "description": {"type": "string", "required": True},
    "record_document_id": {"type": "string"},
    "severity": {"type": "enum", "values": {"LOW", "STANDARD", "CRITICAL"}},
}

_NOTE_SPEC = {
    "resolution_note": {"type": "string", "required": True},
}


def _get_curative_or_404(cid):
    return require_fk("curatives", cid, ERR_CURATIVE_NOT_FOUND, "curative requirement")


def _require_order_not_terminal(order):
    if order["status"] in TERMINAL_ORDER_STATES:
        raise ApiError(ERR_ORDER_TERMINAL, 409, "parent order is terminal")


@bp.post("/curative-requirements")
def create_curative():
    uid, role = authenticate(["Examiner"])
    body = body_json()
    check_shape(body, _CREATE_SPEC)
    order = require_fk("orders", body["order_id"], ERR_ORDER_NOT_FOUND, "order")
    if body.get("record_document_id") is not None:
        require_fk("documents", body["record_document_id"], ERR_DOCUMENT_NOT_FOUND, "document")
    _require_order_not_terminal(order)
    curative = db.new_entity("curatives", {
        "order_id": body["order_id"],
        "record_document_id": body.get("record_document_id"),
        "raised_by_examiner_ref": uid,
        "description": body["description"],
        "severity": body.get("severity") or "STANDARD",
        "resolution_note": None,
        "status": "OPEN",
    })
    return success_obj(curative_view(curative), 201)


@bp.get("/curative-requirements/<cid>")
def get_curative(cid):
    authenticate(ALL_ROLES)
    return success_obj(curative_view(_get_curative_or_404(cid)), 200)


@bp.get("/curative-requirements")
def list_curatives():
    authenticate(ALL_ROLES)
    limit, offset = pagination_params()
    items = apply_filters(
        db.all_of("curatives"),
        ["order_id", "record_document_id", "raised_by_examiner_ref", "status"],
    )
    page, total, has_more = paginate(items, limit, offset)
    return success_list([curative_view(c) for c in page], limit, offset, total, has_more)


@bp.post("/curative-requirements/<cid>/satisfy")
def satisfy_curative(cid):
    uid, role = authenticate(["Abstracter"])
    body = body_json()
    check_shape(body, _NOTE_SPEC)
    curative = _get_curative_or_404(cid)
    _require_order_not_terminal(db.get("orders", curative["order_id"]))
    if curative["status"] != "OPEN":
        raise ApiError(ERR_INVALID_STATE, 409, "curative requirement is not OPEN")
    curative["status"] = "SATISFIED"
    curative["resolution_note"] = body["resolution_note"]
    db.touch(curative)
    return success_obj(curative_view(curative), 200)


@bp.post("/curative-requirements/<cid>/waive")
def waive_curative(cid):
    uid, role = authenticate(["Examiner"])
    body = body_json()
    check_shape(body, _NOTE_SPEC)
    curative = _get_curative_or_404(cid)
    _require_order_not_terminal(db.get("orders", curative["order_id"]))
    if curative["status"] != "OPEN":
        raise ApiError(ERR_INVALID_STATE, 409, "curative requirement is not OPEN")
    # Safety checks evaluated after the generic guards (PRD section 3.8):
    # criticality first (priority 8), then segregation of duties (priority 9).
    if curative["severity"] == "CRITICAL":
        raise ApiError(ERR_CRITICAL_NOT_WAIVABLE, 422, "a CRITICAL requirement cannot be waived")
    if curative["raised_by_examiner_ref"] is not None and curative["raised_by_examiner_ref"] == uid:
        raise ApiError(ERR_SOD_WAIVER_FORBIDDEN, 403, "an examiner may not waive a requirement they raised")
    curative["status"] = "WAIVED"
    curative["resolution_note"] = body["resolution_note"]
    db.touch(curative)
    return success_obj(curative_view(curative), 200)
