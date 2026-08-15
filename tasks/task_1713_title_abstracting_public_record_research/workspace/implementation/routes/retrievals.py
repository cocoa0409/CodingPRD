"""CountyRetrieval endpoints: retrieval requests and the pass-through fee
ledger (post / reverse with fiscal-audit precedence)."""

import db
from errors import (
    ApiError,
    ERR_ORDER_NOT_FOUND,
    ERR_DOCUMENT_NOT_FOUND,
    ERR_RETRIEVAL_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_ORDER_TERMINAL,
    ERR_PAGE_COUNT_INVALID,
    ERR_FEE_ALREADY_POSTED,
    ERR_ALREADY_INVOICED,
)
from middleware import authenticate, ALL_ROLES
from response import success_obj, success_list
from routes import make_blueprint
from services import (
    TERMINAL_ORDER_STATES,
    PER_DOCUMENT_FEE_CENTS,
    PER_PAGE_FEE_CENTS,
    retrieval_view,
    recompute_order_fees,
)
from util import (
    body_json,
    check_shape,
    pagination_params,
    paginate,
    apply_filters,
    require_fk,
)

bp = make_blueprint("retrievals")

_CREATE_SPEC = {
    "order_id": {"type": "string", "required": True},
    "record_document_id": {"type": "string", "required": True},
    "county": {"type": "string", "required": True},
    "fee_mode": {"type": "enum", "values": {"PER_DOCUMENT", "PER_PAGE"}},
    "page_count": {"type": "integer"},
}

_REVERSE_SPEC = {
    "reason": {"type": "string"},
}


def _get_retrieval_or_404(rid):
    return require_fk("retrievals", rid, ERR_RETRIEVAL_NOT_FOUND, "county retrieval")


def _require_order_not_terminal(order):
    if order["status"] in TERMINAL_ORDER_STATES:
        raise ApiError(ERR_ORDER_TERMINAL, 409, "parent order is terminal")


@bp.post("/county-retrievals")
def create_retrieval():
    uid, role = authenticate(["Abstracter"])
    body = body_json()
    check_shape(body, _CREATE_SPEC)
    order = require_fk("orders", body["order_id"], ERR_ORDER_NOT_FOUND, "order")
    require_fk("documents", body["record_document_id"], ERR_DOCUMENT_NOT_FOUND, "document")
    _require_order_not_terminal(order)
    fee_mode = body.get("fee_mode") or "PER_DOCUMENT"
    page_count = body.get("page_count")
    if fee_mode == "PER_PAGE":
        if page_count is None or page_count < 1:
            raise ApiError(ERR_PAGE_COUNT_INVALID, 422, "PER_PAGE fee_mode requires page_count >= 1")
    retrieval = db.new_entity("retrievals", {
        "order_id": body["order_id"],
        "record_document_id": body["record_document_id"],
        "county": body["county"],
        "fee_mode": fee_mode,
        "page_count": page_count if fee_mode == "PER_PAGE" else body.get("page_count"),
        "fee_cents": None,
        "status": "REQUESTED",
    })
    return success_obj(retrieval_view(retrieval), 201)


@bp.get("/county-retrievals/<rid>")
def get_retrieval(rid):
    authenticate(ALL_ROLES)
    return success_obj(retrieval_view(_get_retrieval_or_404(rid)), 200)


@bp.get("/county-retrievals")
def list_retrievals():
    authenticate(ALL_ROLES)
    limit, offset = pagination_params()
    items = apply_filters(db.all_of("retrievals"), ["order_id", "record_document_id", "status"])
    page, total, has_more = paginate(items, limit, offset)
    return success_list([retrieval_view(r) for r in page], limit, offset, total, has_more)


@bp.post("/county-retrievals/<rid>/post-fee")
def post_fee(rid):
    uid, role = authenticate(["OperationsManager"])
    body_json()
    retrieval = _get_retrieval_or_404(rid)
    # Fiscal lifecycle guards run BEFORE the terminal-order guard (PRD 2.10).
    if retrieval["status"] in ("FEE_POSTED", "FEE_REVERSED"):
        raise ApiError(ERR_FEE_ALREADY_POSTED, 409, "fee already posted for this retrieval")
    if retrieval["status"] == "INVOICED":
        raise ApiError(ERR_ALREADY_INVOICED, 409, "an invoiced fee cannot be touched")
    _require_order_not_terminal(db.get("orders", retrieval["order_id"]))
    if retrieval["status"] != "REQUESTED":
        raise ApiError(ERR_INVALID_STATE, 409, "retrieval is not REQUESTED")
    if retrieval["fee_mode"] == "PER_PAGE":
        retrieval["fee_cents"] = retrieval["page_count"] * PER_PAGE_FEE_CENTS
    else:
        retrieval["fee_cents"] = PER_DOCUMENT_FEE_CENTS
    retrieval["status"] = "FEE_POSTED"
    db.touch(retrieval)
    order = db.get("orders", retrieval["order_id"])
    recompute_order_fees(order)
    db.touch(order)
    return success_obj(retrieval_view(retrieval), 200)


@bp.post("/county-retrievals/<rid>/reverse-fee")
def reverse_fee(rid):
    uid, role = authenticate(["OperationsManager"])
    body = body_json()
    check_shape(body, _REVERSE_SPEC)
    retrieval = _get_retrieval_or_404(rid)
    # Fiscal lifecycle guards run BEFORE the terminal-order guard (PRD 2.10).
    if retrieval["status"] == "INVOICED":
        raise ApiError(ERR_ALREADY_INVOICED, 409, "an invoiced fee cannot be touched")
    _require_order_not_terminal(db.get("orders", retrieval["order_id"]))
    if retrieval["status"] != "FEE_POSTED":
        raise ApiError(ERR_INVALID_STATE, 409, "only a FEE_POSTED retrieval can be reversed")
    retrieval["status"] = "FEE_REVERSED"
    db.touch(retrieval)
    order = db.get("orders", retrieval["order_id"])
    recompute_order_fees(order)
    db.touch(order)
    return success_obj(retrieval_view(retrieval), 200)
