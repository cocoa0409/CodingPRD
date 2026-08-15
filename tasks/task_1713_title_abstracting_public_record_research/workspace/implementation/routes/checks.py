"""LegalDescriptionCheck endpoints: intake QC, verdicts, and mismatch
resolution with legal-hold handling."""

import db
from errors import (
    ApiError,
    ERR_ORDER_NOT_FOUND,
    ERR_CHECK_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_ORDER_TERMINAL,
)
from middleware import authenticate, ALL_ROLES
from response import success_obj, success_list
from routes import make_blueprint
from services import (
    TERMINAL_ORDER_STATES,
    check_view,
    reevaluate_search_completion,
)
from util import (
    body_json,
    check_shape,
    pagination_params,
    paginate,
    apply_filters,
    require_fk,
)

bp = make_blueprint("checks")

_CREATE_SPEC = {
    "order_id": {"type": "string", "required": True},
    "survey_reference": {"type": "string", "required": True},
    "checked_legal_description": {"type": "string", "required": True},
}

_VERDICT_SPEC = {
    "verdict": {"type": "enum", "required": True, "values": {"VERIFIED", "MISMATCH"}},
    "survey_exception_applied": {"type": "boolean", "required": True},
}

_RESOLVE_SPEC = {
    "resolved_description": {"type": "string", "required": True},
}


def _get_check_or_404(cid):
    return require_fk("checks", cid, ERR_CHECK_NOT_FOUND, "legal description check")


def _require_order_not_terminal(order):
    if order["status"] in TERMINAL_ORDER_STATES:
        raise ApiError(ERR_ORDER_TERMINAL, 409, "parent order is terminal")


@bp.post("/legal-description-checks")
def create_check():
    uid, role = authenticate(["OperationsManager"])
    body = body_json()
    check_shape(body, _CREATE_SPEC)
    order = require_fk("orders", body["order_id"], ERR_ORDER_NOT_FOUND, "order")
    _require_order_not_terminal(order)
    check = db.new_entity("checks", {
        "order_id": body["order_id"],
        "survey_reference": body["survey_reference"],
        "checked_legal_description": body["checked_legal_description"],
        "survey_exception_applied": False,
        "resolved_description": None,
        "status": "PENDING",
    })
    return success_obj(check_view(check), 201)


@bp.get("/legal-description-checks/<cid>")
def get_check(cid):
    authenticate(ALL_ROLES)
    return success_obj(check_view(_get_check_or_404(cid)), 200)


@bp.get("/legal-description-checks")
def list_checks():
    authenticate(ALL_ROLES)
    limit, offset = pagination_params()
    items = apply_filters(db.all_of("checks"), ["order_id", "status"])
    page, total, has_more = paginate(items, limit, offset)
    return success_list([check_view(c) for c in page], limit, offset, total, has_more)


@bp.post("/legal-description-checks/<cid>/submit-verdict")
def submit_verdict(cid):
    uid, role = authenticate(["OperationsManager"])
    body = body_json()
    check_shape(body, _VERDICT_SPEC)
    check = _get_check_or_404(cid)
    _require_order_not_terminal(db.get("orders", check["order_id"]))
    if check["status"] != "PENDING":
        raise ApiError(ERR_INVALID_STATE, 409, "check is not PENDING")
    check["survey_exception_applied"] = body["survey_exception_applied"]
    check["status"] = body["verdict"]  # VERIFIED or MISMATCH
    db.touch(check)
    # A MISMATCH sets the order's legal hold; the hold is derived at read
    # time from any check sitting in MISMATCH, so no order write is needed.
    return success_obj(check_view(check), 200)


@bp.post("/legal-description-checks/<cid>/resolve")
def resolve_check(cid):
    uid, role = authenticate(["OperationsManager"])
    body = body_json()
    check_shape(body, _RESOLVE_SPEC)
    check = _get_check_or_404(cid)
    order = db.get("orders", check["order_id"])
    _require_order_not_terminal(order)
    if check["status"] != "MISMATCH":
        raise ApiError(ERR_INVALID_STATE, 409, "check is not MISMATCH")
    check["resolved_description"] = body["resolved_description"]
    check["status"] = "RESOLVED"
    db.touch(check)
    # Resolution overwrites the order's legal description of record, clears
    # the hold when no other MISMATCH remains (derived at read time), bumps
    # the order version, and re-evaluates search completion.
    order["legal_description_text"] = body["resolved_description"]
    db.touch(order)
    reevaluate_search_completion(order)
    return success_obj(check_view(check), 200)
