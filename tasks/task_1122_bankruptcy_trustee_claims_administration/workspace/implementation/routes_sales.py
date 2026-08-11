"""Auction sale endpoints: propose, approve (minimum-price gate), consummate,
cancel (objection-window rules)."""
from flask import Blueprint, request

import db
from errors import (
    ApiError, ERR_INVALID_STATE, ERR_REFERENTIAL_INTEGRITY, ERR_SALE_ALREADY_PENDING,
    ERR_BELOW_MINIMUM_PRICE, ERR_OBJECTION_WINDOW_OPEN, ERR_OBJECTION_WINDOW_CLOSED,
    ERR_INVALID_REQUEST, ERR_FORBIDDEN_FOR_ROLE,
)
from logical_clock import CLOCK
from middleware import auth_context, require_roles, json_body, ALL_ROLES
from response import ok_object, paginate
from services_calc import add_days
from services_common import (
    new_entity, touch, bump_case, get_case, get_or_404, ensure_case_open,
    ensure_trustee_binding, ser_sale, sorted_rows,
)
from util import require_str, require_int

bp = Blueprint("sales", __name__)


def _get_sale_case_asset(sale_id):
    sale = get_or_404(db.sales, sale_id, "sale")
    case = db.cases[sale["case_id"]]
    asset = db.assets[sale["asset_id"]]
    return sale, case, asset


@bp.route("/trustee/cases/<id>/sales", methods=["POST"])
def create_sale(id):
    uid, role = auth_context()
    require_roles(role, ("Trustee",))
    case = get_case(id)
    ensure_case_open(case)
    ensure_trustee_binding(case, uid)
    body = json_body()

    raw_asset = body.get("asset_id")
    asset = None
    if isinstance(raw_asset, str):
        asset = db.assets.get(raw_asset)
        if asset is None or asset["case_id"] != id:
            raise ApiError(ERR_REFERENTIAL_INTEGRITY, 422,
                           "asset_id must name an asset of this case.")

    if asset is not None:
        if asset["status"] != "MARKED_FOR_SALE":
            raise ApiError(ERR_INVALID_STATE, 409, "Asset must be MARKED_FOR_SALE to propose a sale.")
        if any(s["asset_id"] == asset["id"] and s["status"] in ("PROPOSED", "APPROVED")
               for s in db.sales.values()):
            raise ApiError(ERR_SALE_ALREADY_PENDING, 409,
                           "Another sale of this asset is PROPOSED or APPROVED.")

    asset_id = require_str(body, "asset_id")
    buyer_name = require_str(body, "buyer_name")
    hammer = require_int(body, "hammer_price_cents", minimum=0)
    costs = require_int(body, "sale_costs_cents", minimum=0)
    net = hammer - costs
    if net < 0:
        raise ApiError(ERR_INVALID_REQUEST, 400, "net_proceeds_cents may not be negative.")

    sale = new_entity({
        "case_id": id,
        "asset_id": asset_id,
        "buyer_name": buyer_name,
        "hammer_price_cents": hammer,
        "sale_costs_cents": costs,
        "net_proceeds_cents": net,
        "sale_approved_on": None,
        "effective_on": None,
        "proceeds_status": "PENDING",
        "status": "PROPOSED",
    })
    db.sales[sale["id"]] = sale
    asset["status"] = "IN_AUCTION"
    touch(asset)
    return ok_object(ser_sale(sale), status=201)


@bp.route("/trustee/cases/<id>/sales", methods=["GET"])
def list_case_sales(id):
    auth_context()
    require_roles(request.headers.get("X-User-Role"), ALL_ROLES)
    get_case(id)
    status = request.args.get("status")
    asset_id = request.args.get("asset_id")
    rows = [s for s in db.sales.values() if s["case_id"] == id]
    if status is not None:
        rows = [s for s in rows if s["status"] == status]
    if asset_id is not None:
        rows = [s for s in rows if s["asset_id"] == asset_id]
    return paginate([ser_sale(s) for s in sorted_rows(rows)])


@bp.route("/trustee/sales/<id>", methods=["GET"])
def get_sale(id):
    auth_context()
    require_roles(request.headers.get("X-User-Role"), ALL_ROLES)
    return ok_object(ser_sale(get_or_404(db.sales, id, "sale")))


@bp.route("/trustee/sales/<id>/approve", methods=["POST"])
def approve_sale(id):
    _, role = auth_context()
    require_roles(role, ("Court",))
    sale, case, asset = _get_sale_case_asset(id)
    ensure_case_open(case)
    if sale["status"] != "PROPOSED":
        raise ApiError(ERR_INVALID_STATE, 409, "Sale must be PROPOSED to approve.")
    min_gross = max(sale["sale_costs_cents"], asset["scheduled_value_cents"] // 2)
    if sale["hammer_price_cents"] < min_gross:
        raise ApiError(ERR_BELOW_MINIMUM_PRICE, 422,
                       "hammer_price_cents is below the minimum price floor.")
    now = CLOCK.now()
    sale["sale_approved_on"] = now
    sale["effective_on"] = add_days(now, case["objection_window_days"])
    sale["status"] = "APPROVED"
    touch(sale)
    bump_case(case)
    return ok_object(ser_sale(sale))


@bp.route("/trustee/sales/<id>/consummate", methods=["POST"])
def consummate_sale(id):
    uid, role = auth_context()
    require_roles(role, ("Trustee",))
    sale, case, asset = _get_sale_case_asset(id)
    ensure_case_open(case)
    if sale["status"] != "APPROVED":
        raise ApiError(ERR_INVALID_STATE, 409, "Sale must be APPROVED to consummate.")
    ensure_trustee_binding(case, uid)
    if CLOCK.now() < sale["effective_on"]:
        raise ApiError(ERR_OBJECTION_WINDOW_OPEN, 409,
                       "The objection window has not elapsed; the sale is not yet effective.")
    sale["proceeds_status"] = "POSTED"
    sale["status"] = "CONSUMMATED"
    case["estate_cash_on_hand_cents"] += sale["net_proceeds_cents"]
    asset["status"] = "SOLD"
    asset["realized_proceeds_cents"] = sale["net_proceeds_cents"]
    touch(sale)
    touch(asset)
    bump_case(case)
    return ok_object(ser_sale(sale))


@bp.route("/trustee/sales/<id>/cancel", methods=["POST"])
def cancel_sale(id):
    uid, role = auth_context()
    require_roles(role, ("Trustee", "Court"))
    sale, case, asset = _get_sale_case_asset(id)
    ensure_case_open(case)
    if sale["status"] not in ("PROPOSED", "APPROVED"):
        raise ApiError(ERR_INVALID_STATE, 409, "Only a PROPOSED or APPROVED sale may be cancelled.")
    if role == "Trustee":
        ensure_trustee_binding(case, uid)
        if sale["status"] == "APPROVED":
            raise ApiError(ERR_FORBIDDEN_FOR_ROLE, 403,
                           "An APPROVED sale may be cancelled only by the Court.")
    else:  # Court cancelling an APPROVED sale: only before effective_on
        if sale["status"] == "APPROVED" and CLOCK.now() >= sale["effective_on"]:
            raise ApiError(ERR_OBJECTION_WINDOW_CLOSED, 409,
                           "The objection window has closed; the sale may no longer be cancelled.")
    sale["status"] = "CANCELLED"
    if asset["status"] == "IN_AUCTION":
        asset["status"] = "MARKED_FOR_SALE"
        touch(asset)
    touch(sale)
    return ok_object(ser_sale(sale))
