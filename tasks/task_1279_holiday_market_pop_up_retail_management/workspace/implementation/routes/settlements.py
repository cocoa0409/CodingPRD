"""SalesSettlement endpoints (PRD 3.6): create/PUT with computed POS fee and
net payable, submit/reconcile/dispute/pay lifecycle."""
import re

from flask import Blueprint

import db
from errors import ApiError, invalid_state, posture_forbidden, validation
from middleware import auth, require_roles, require_vendor_owner
from response import success
from services import calc, cascades, posture
from services.core import (
    arg,
    base_record,
    body,
    get_child,
    get_market,
    list_response,
    required,
    serialize,
    touch,
)

bp = Blueprint("settlements", __name__)

VENDOR = ("VendorRole",)
FINANCE = ("FinanceOfficer",)
GET_ONE = ("MarketOperator", "VendorRole", "FinanceOfficer")
GET_LIST = ("MarketOperator", "FinanceOfficer")

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _amounts_error(message):
    return ApiError("ERR_INVALID_SETTLEMENT_AMOUNTS", message, 422)


def _read_amount(data, name, default=None):
    if name not in data or data[name] is None:
        if default is not None:
            return default
        raise _amounts_error("missing required amount field: %s" % name)
    value = data[name]
    if isinstance(value, bool) or not isinstance(value, int):
        raise _amounts_error("field %s must be integer cents" % name)
    return value


def _validate_amounts(gross_card, gross_cash, refund):
    if gross_card < 0 or gross_cash < 0:
        raise _amounts_error("gross amounts must be non-negative")
    if refund < 0:
        raise _amounts_error("refund_cents must be non-negative")
    if refund > gross_card + gross_cash:
        raise _amounts_error("refund_cents exceeds gross_card_cents + gross_cash_cents")


def _recompute(market, settlement):
    settlement["pos_fee_cents"] = calc.compute_pos_fee_cents(
        market, settlement["assignment_id"], settlement["gross_card_cents"]
    )
    settlement["net_payable_cents"] = calc.compute_net_payable_cents(
        settlement["gross_card_cents"],
        settlement["gross_cash_cents"],
        settlement["refund_cents"],
        settlement["pos_fee_cents"],
    )


def _owner_vendor_id(settlement):
    assignment = db.STORES["assignments"].get(settlement["assignment_id"])
    if assignment is None:
        return None
    app = db.STORES["applications"].get(assignment["application_id"])
    return app["vendor_id"] if app else None


def _resolve(marketId, settlementId):
    get_market(marketId)
    return get_child("settlements", settlementId, marketId)


@bp.post("/markets/<marketId>/settlements")
def create_settlement(marketId):
    user = auth()
    require_roles(user, VENDOR)
    market = get_market(marketId)
    data = body()
    assignment_id = data.get("assignment_id")
    if not isinstance(assignment_id, str):
        raise validation("missing required field: assignment_id")
    get_child("assignments", assignment_id, marketId)
    business_date = required(data, "business_date")
    if not isinstance(business_date, str) or not _DATE_RE.match(business_date):
        raise validation("business_date must be an ISO-8601 calendar date (YYYY-MM-DD)")
    gross_card = _read_amount(data, "gross_card_cents")
    gross_cash = _read_amount(data, "gross_cash_cents")
    refund = _read_amount(data, "refund_cents", default=0)
    _validate_amounts(gross_card, gross_cash, refund)
    rec = base_record()
    rec.update(
        {
            "market_id": marketId,
            "assignment_id": assignment_id,
            "business_date": business_date,
            "gross_card_cents": gross_card,
            "gross_cash_cents": gross_cash,
            "refund_cents": refund,
            "pos_fee_cents": 0,
            "net_payable_cents": 0,
            "status": "DRAFT",
        }
    )
    require_vendor_owner(user, _owner_vendor_id(rec))
    _recompute(market, rec)
    db.STORES["settlements"][rec["id"]] = rec
    return success(serialize(rec), 201)


@bp.get("/markets/<marketId>/settlements/<settlementId>")
def get_settlement(marketId, settlementId):
    user = auth()
    require_roles(user, GET_ONE)
    return success(serialize(_resolve(marketId, settlementId)))


@bp.get("/markets/<marketId>/settlements")
def list_settlements(marketId):
    user = auth()
    require_roles(user, GET_LIST)
    get_market(marketId)
    status = arg("status")
    assignment_id = arg("assignment_id")
    business_date = arg("business_date")
    records = []
    for s in db.STORES["settlements"].values():
        if s["market_id"] != marketId:
            continue
        if status is not None and s["status"] != status:
            continue
        if assignment_id is not None and s["assignment_id"] != assignment_id:
            continue
        if business_date is not None and s["business_date"] != business_date:
            continue
        records.append(s)
    return list_response(records)


@bp.put("/markets/<marketId>/settlements/<settlementId>")
def update_settlement(marketId, settlementId):
    user = auth()
    require_roles(user, VENDOR)
    market = get_market(marketId)
    settlement = get_child("settlements", settlementId, marketId)
    require_vendor_owner(user, _owner_vendor_id(settlement))
    if settlement["status"] != "DRAFT":
        raise invalid_state("only a DRAFT settlement can be updated")
    data = body()
    gross_card = _read_amount(data, "gross_card_cents", default=settlement["gross_card_cents"])
    gross_cash = _read_amount(data, "gross_cash_cents", default=settlement["gross_cash_cents"])
    refund = _read_amount(data, "refund_cents", default=settlement["refund_cents"])
    _validate_amounts(gross_card, gross_cash, refund)
    settlement["gross_card_cents"] = gross_card
    settlement["gross_cash_cents"] = gross_cash
    settlement["refund_cents"] = refund
    _recompute(market, settlement)
    touch(settlement)
    return success(serialize(settlement))


@bp.post("/markets/<marketId>/settlements/<settlementId>/submit")
def submit_settlement(marketId, settlementId):
    user = auth()
    require_roles(user, VENDOR)
    market = get_market(marketId)
    settlement = get_child("settlements", settlementId, marketId)
    require_vendor_owner(user, _owner_vendor_id(settlement))
    if posture.derive_posture(market) not in ("OPEN", "WEATHER_ALERT"):
        raise posture_forbidden("settlement submission requires OPEN or WEATHER_ALERT posture")
    if settlement["status"] != "DRAFT":
        raise invalid_state("only a DRAFT settlement can be submitted")
    duplicate = any(
        s["id"] != settlementId
        and s["assignment_id"] == settlement["assignment_id"]
        and s["business_date"] == settlement["business_date"]
        and s["status"] == "SUBMITTED"
        for s in db.STORES["settlements"].values()
    )
    if duplicate:
        raise ApiError(
            "ERR_DUPLICATE_SETTLEMENT",
            "a SUBMITTED settlement already exists for this assignment and business_date",
            409,
        )
    _recompute(market, settlement)
    settlement["status"] = "SUBMITTED"
    touch(settlement)
    vendor = cascades.vendor_of_assignment(
        db.STORES["assignments"].get(settlement["assignment_id"])
    )
    if vendor is not None:
        vendor["lifetime_gross_sales_cents"] += (
            settlement["gross_card_cents"]
            + settlement["gross_cash_cents"]
            - settlement["refund_cents"]
        )
        touch(vendor)
    return success(serialize(settlement))


@bp.post("/markets/<marketId>/settlements/<settlementId>/reconcile")
def reconcile_settlement(marketId, settlementId):
    user = auth()
    require_roles(user, FINANCE)
    market = get_market(marketId)
    settlement = get_child("settlements", settlementId, marketId)
    if posture.derive_posture(market) not in ("OPEN", "WEATHER_ALERT", "CLOSED_SEASON"):
        raise posture_forbidden(
            "reconciliation requires OPEN, WEATHER_ALERT, or CLOSED_SEASON posture"
        )
    if settlement["status"] != "SUBMITTED":
        raise invalid_state("only a SUBMITTED settlement can be reconciled")
    settlement["status"] = "RECONCILED"
    touch(settlement)
    vendor = cascades.vendor_of_assignment(
        db.STORES["assignments"].get(settlement["assignment_id"])
    )
    if vendor is not None:
        if cascades.recompute_vendor_score(vendor):
            touch(vendor)
    return success(serialize(settlement))


@bp.post("/markets/<marketId>/settlements/<settlementId>/dispute")
def dispute_settlement(marketId, settlementId):
    user = auth()
    require_roles(user, FINANCE)
    settlement = _resolve(marketId, settlementId)
    if settlement["status"] != "SUBMITTED":
        raise invalid_state("only a SUBMITTED settlement can be disputed")
    settlement["status"] = "DISPUTED"
    touch(settlement)
    return success(serialize(settlement))


@bp.post("/markets/<marketId>/settlements/<settlementId>/pay")
def pay_settlement(marketId, settlementId):
    user = auth()
    require_roles(user, FINANCE)
    settlement = _resolve(marketId, settlementId)
    if settlement["status"] != "RECONCILED":
        raise invalid_state("only a RECONCILED settlement can be paid")
    settlement["status"] = "PAID"
    touch(settlement)
    return success(serialize(settlement))
