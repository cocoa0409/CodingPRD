"""SupportOrder endpoints (PRD §3.6). Amount is computed server-side, never quoted."""
from __future__ import annotations

from flask import Blueprint, request

import db
from errors import (
    APIError,
    ERR_INVALID_REQUEST,
    ERR_NO_RESPONDENT,
    ERR_INCOME_NOT_AVAILABLE,
    ERR_SUPPORT_TYPE_MISMATCH,
)
from middleware import require_auth, get_json_body, paginate_params, slice_page
from response import ok_object, ok_array
from services.common import (
    serialize,
    serialize_list,
    sorted_by_creation,
    get_case,
    get_party,
    assert_case_not_terminal,
    petitioner_of,
    respondent_of,
    verified_disclosure_for_party,
    require,
)
from services.support import compute_support

bp = Blueprint("support_orders", __name__)

READ_ROLES = ["Clerk", "Judge", "Mediator", "Petitioner", "Respondent"]


@bp.post("/api/support-orders")
def create_support_order():
    require_auth(["Clerk"])()
    body = get_json_body()

    # Existence (404) left-to-right: case, payor, payee.
    case_id = body.get("case_id")
    case = get_case(case_id)
    payor_id = body.get("payor_party_id")
    payor = get_party(payor_id)
    payee_id = body.get("payee_party_id")
    payee = get_party(payee_id)

    assert_case_not_terminal(case)

    # Schema (422): enums.
    support_type = body.get("support_type")
    if support_type not in ("CHILD", "SPOUSAL"):
        raise APIError(ERR_INVALID_REQUEST, 422, "support_type must be CHILD or SPOUSAL")
    variant = body.get("variant")
    if variant not in ("TEMPORARY", "FINAL"):
        raise APIError(ERR_INVALID_REQUEST, 422, "variant must be TEMPORARY or FINAL")

    if payor["case_id"] != case_id or payee["case_id"] != case_id:
        raise APIError(ERR_INVALID_REQUEST, 422, "payor/payee must belong to the case")

    # ERR_SUPPORT_TYPE_MISMATCH (422): the requested computation must match
    # support_type. If the body declares a contradictory computed_type, reject.
    declared = body.get("computed_support_type")
    if declared is not None and declared != support_type:
        raise APIError(ERR_SUPPORT_TYPE_MISMATCH, 422, "computation does not match support_type")

    # ERR_NO_RESPONDENT (409): both PETITIONER and RESPONDENT must exist.
    if petitioner_of(case_id) is None or respondent_of(case_id) is None:
        raise APIError(ERR_NO_RESPONDENT, 409, "Both parties are required on the case")

    # ERR_INCOME_NOT_AVAILABLE (409): FINAL requires VERIFIED disclosures.
    if variant == "FINAL":
        if verified_disclosure_for_party(payor_id) is None:
            raise APIError(ERR_INCOME_NOT_AVAILABLE, 409, "Payor disclosure not verified")
        if verified_disclosure_for_party(payee_id) is None:
            raise APIError(ERR_INCOME_NOT_AVAILABLE, 409, "Payee disclosure not verified")

    order = {
        "case_id": case_id,
        "support_type": support_type,
        "payor_party_id": payor_id,
        "payee_party_id": payee_id,
        "variant": variant,
        "monthly_amount_cents": 0,
        "support_term_months": 0,
        "status": "CALCULATED",
    }
    amount, term = compute_support(order, case)
    order["monthly_amount_cents"] = amount
    order["support_term_months"] = term

    db.stamp_common(order)
    db.support_orders[order["id"]] = order
    return ok_object(serialize(order), 201)


@bp.get("/api/support-orders/<rid>")
def get_support_order(rid):
    require_auth(READ_ROLES)()
    so = require(db.support_orders, rid, "SupportOrder")
    return ok_object(serialize(so), 200)


@bp.get("/api/support-orders")
def list_support_orders():
    require_auth(READ_ROLES)()
    limit, offset = paginate_params(request.args)
    items = sorted_by_creation(list(db.support_orders.values()))
    case_id = request.args.get("case_id")
    payor = request.args.get("payor_party_id")
    payee = request.args.get("payee_party_id")
    if case_id is not None:
        items = [s for s in items if s["case_id"] == case_id]
    if payor is not None:
        items = [s for s in items if s["payor_party_id"] == payor]
    if payee is not None:
        items = [s for s in items if s["payee_party_id"] == payee]
    page, total = slice_page(items, limit, offset)
    return ok_array(serialize_list(page), limit, offset, total, 200)
