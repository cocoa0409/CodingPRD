from flask import Blueprint, request

from db import db
from errors import (
    ApiError, ERR_AGREEMENT_NOT_ACTIVE, ERR_AGREEMENT_NOT_PROPOSED,
    ERR_AGREEMENT_NOT_SUSPENDED, not_found,
)
from helpers import (
    get_body, list_query, new_entity, ser_agreement, touch,
)
from middleware import require_roles
from response import success_list, success_object

bp = Blueprint("agreements", __name__)

_ROLES = ["PlatformAdmin", "ExchangeCoordinator", "TerminalOperator"]


def _get_agreement(agreement_id):
    a = db.exchange_agreements.get(agreement_id)
    if a is None:
        raise not_found("ExchangeAgreement {} does not exist".format(agreement_id))
    return a


@bp.post("/rack/exchange-agreements")
def create_agreement():
    require_roles(["ExchangeCoordinator"])
    body = get_body()
    if body.get("delivering_terminal_id") not in db.terminals:
        raise not_found(
            "Terminal {} does not exist".format(body.get("delivering_terminal_id"))
        )
    if body.get("product_id") not in db.products:
        raise not_found("Product {} does not exist".format(body.get("product_id")))
    a = new_entity({
        "delivering_terminal_id": body.get("delivering_terminal_id"),
        "receiving_supplier_code": body.get("receiving_supplier_code"),
        "product_id": body.get("product_id"),
        "monthly_exchange_cap_gallons": body.get("monthly_exchange_cap_gallons", 0),
        "delivered_this_month_gallons": 0,
        "status": "PROPOSED",
    })
    db.exchange_agreements[a["id"]] = a
    return success_object(ser_agreement(a), 201)


@bp.get("/rack/exchange-agreements/<agreementId>")
def get_agreement(agreementId):
    require_roles(_ROLES)
    return success_object(ser_agreement(_get_agreement(agreementId)))


@bp.get("/rack/exchange-agreements")
def list_agreements():
    require_roles(_ROLES)
    page, total, limit, offset = list_query(
        db.exchange_agreements.values(), request.args,
        ["delivering_terminal_id", "product_id", "status"],
    )
    return success_list([ser_agreement(a) for a in page], total, limit, offset)


@bp.post("/rack/exchange-agreements/<agreementId>/activate")
def activate_agreement(agreementId):
    require_roles(["ExchangeCoordinator"])
    a = _get_agreement(agreementId)
    if a["status"] != "PROPOSED":
        raise ApiError(
            ERR_AGREEMENT_NOT_PROPOSED, 409,
            "ExchangeAgreement must be PROPOSED to activate",
        )
    a["status"] = "ACTIVE"
    touch(a)
    return success_object(ser_agreement(a))


@bp.post("/rack/exchange-agreements/<agreementId>/suspend")
def suspend_agreement(agreementId):
    require_roles(["ExchangeCoordinator"])
    a = _get_agreement(agreementId)
    if a["status"] != "ACTIVE":
        raise ApiError(
            ERR_AGREEMENT_NOT_ACTIVE, 409,
            "ExchangeAgreement must be ACTIVE to suspend",
        )
    a["status"] = "SUSPENDED"
    touch(a)
    return success_object(ser_agreement(a))


@bp.post("/rack/exchange-agreements/<agreementId>/reinstate")
def reinstate_agreement(agreementId):
    require_roles(["ExchangeCoordinator"])
    a = _get_agreement(agreementId)
    if a["status"] != "SUSPENDED":
        raise ApiError(
            ERR_AGREEMENT_NOT_SUSPENDED, 409,
            "ExchangeAgreement must be SUSPENDED to reinstate",
        )
    a["status"] = "ACTIVE"
    touch(a)
    return success_object(ser_agreement(a))


@bp.post("/rack/exchange-agreements/<agreementId>/terminate")
def terminate_agreement(agreementId):
    require_roles(["ExchangeCoordinator"])
    a = _get_agreement(agreementId)
    if a["status"] not in ("ACTIVE", "SUSPENDED"):
        raise ApiError(
            ERR_AGREEMENT_NOT_ACTIVE, 409,
            "ExchangeAgreement must be ACTIVE or SUSPENDED to terminate",
        )
    a["status"] = "TERMINATED"
    touch(a)
    return success_object(ser_agreement(a))
