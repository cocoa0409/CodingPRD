"""Resale endpoints (PRD §3.8)."""

from flask import Blueprint, request

from calculations import (
    compute_resale_commission,
    compute_resale_spread,
    effective_avm,
)
from constants import DEFAULT_RESALE_COMMISSION_PCT
from db import store
from errors import err
from helpers import (
    get_resale_or_404,
    get_transaction_or_404,
    pagination_params,
    paginate,
)
from middleware import authenticate, require_role
from models import serialize, stamp_create, touch
from response import array_response, object_response
from validators import as_number, get_body, require

bp = Blueprint("resales", __name__)


def _acquisition_cost(tx):
    """Effective AVM the iBuyer paid the seller (revised if re-traded, else snapshot)."""
    offer = store.offers[tx["offer_id"]]
    prop = store.properties[tx["property_id"]]
    return effective_avm(prop, offer)


@bp.route("/resales", methods=["POST"])
def create_resale():
    _uid, role = authenticate()
    require_role(role, {"OperationsAdmin", "PricingAnalyst"})

    body = get_body(request)
    transaction_id = require(body, "transaction_id")
    if not isinstance(transaction_id, str):
        raise err("ERR_INVALID_REQUEST", "transaction_id must be a string")
    list_price = as_number(require(body, "list_price"), "list_price", minimum=0)

    commission_pct = DEFAULT_RESALE_COMMISSION_PCT
    if body.get("resale_commission_pct") is not None:
        commission_pct = as_number(
            body["resale_commission_pct"], "resale_commission_pct", minimum=0, maximum=0.10
        )

    tx = get_transaction_or_404(transaction_id)

    # Priority 16: only from a CLOSED transaction
    if tx["status"] != "CLOSED":
        raise err("ERR_TRANSACTION_NOT_CLOSED", "Transaction is not CLOSED")

    acquisition_cost = _acquisition_cost(tx)
    repair_credit = tx["repair_credit"]
    projected_commission = compute_resale_commission(list_price, commission_pct)
    projected_spread = compute_resale_spread(
        list_price, acquisition_cost, repair_credit, projected_commission
    )

    rec = {
        "transaction_id": transaction_id,
        "list_price": list_price,
        "sold_price": None,
        "resale_commission_pct": commission_pct,
        "projected_spread": projected_spread,
        "net_spread": None,
        "status": "LISTED",
    }
    stamp_create(rec)
    store.resales[rec["id"]] = rec
    return object_response(serialize(rec), 201)


@bp.route("/resales", methods=["GET"])
def list_resales():
    _uid, role = authenticate()
    require_role(role, {"OperationsAdmin", "PricingAnalyst", "Seller"})
    records = list(store.resales.values())
    tx_filter = request.args.get("transaction_id")
    status_filter = request.args.get("status")
    if tx_filter is not None:
        records = [r for r in records if r["transaction_id"] == tx_filter]
    if status_filter is not None:
        records = [r for r in records if r["status"] == status_filter]
    limit, offset = pagination_params()
    page, total = paginate(records, limit, offset)
    return array_response([serialize(r) for r in page], limit, offset, total)


@bp.route("/resales/<resale_id>", methods=["GET"])
def get_resale(resale_id):
    _uid, role = authenticate()
    require_role(role, {"OperationsAdmin", "PricingAnalyst", "Seller"})
    rec = get_resale_or_404(resale_id)
    return object_response(serialize(rec), 200)


@bp.route("/resales/<resale_id>/sell", methods=["POST"])
def sell_resale(resale_id):
    _uid, role = authenticate()
    require_role(role, {"OperationsAdmin", "PricingAnalyst"})
    rec = get_resale_or_404(resale_id)

    # State (priority 5): must be LISTED
    if rec["status"] != "LISTED":
        raise err("ERR_INVALID_STATE", "Resale is not LISTED")

    body = get_body(request)
    sold_price = as_number(require(body, "sold_price"), "sold_price", minimum=0)

    tx = store.transactions[rec["transaction_id"]]
    acquisition_cost = _acquisition_cost(tx)
    repair_credit = tx["repair_credit"]
    net_commission = compute_resale_commission(sold_price, rec["resale_commission_pct"])
    net_spread = compute_resale_spread(
        sold_price, acquisition_cost, repair_credit, net_commission
    )

    rec["sold_price"] = sold_price
    rec["net_spread"] = net_spread
    rec["status"] = "SOLD"
    touch(rec)
    return object_response(serialize(rec), 200)


@bp.route("/resales/<resale_id>/delist", methods=["POST"])
def delist_resale(resale_id):
    _uid, role = authenticate()
    require_role(role, {"OperationsAdmin", "PricingAnalyst"})
    rec = get_resale_or_404(resale_id)

    # State (priority 5): must be LISTED
    if rec["status"] != "LISTED":
        raise err("ERR_INVALID_STATE", "Resale is not LISTED")

    rec["status"] = "DELISTED"
    touch(rec)
    return object_response(serialize(rec), 200)
