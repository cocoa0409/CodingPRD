"""AssetSale endpoints — analyze (prohibited-transaction), confirm, void."""

from flask import Blueprint, request

import errors
from db import db
from middleware import require_roles
from response import success_object, success_list, parse_pagination, paginate
from services.calculations import calc_prohibited_transaction
from services.common import get_json_body, make_entity, req_date, req_int, touch

bp = Blueprint("asset_sales", __name__)
ALL = ("ComplianceOfficer", "TaxDirector", "BoardDirector")


@bp.route("/reit-compliance/asset-sales", methods=["POST"])
def create_sale():
    require_roles("ComplianceOfficer")
    body = get_json_body()
    reit_id = body.get("reit_id")
    asset_holding_id = body.get("asset_holding_id")
    if not isinstance(reit_id, str) or not reit_id:
        raise errors.validation("Field 'reit_id' is required")
    if not isinstance(asset_holding_id, str) or not asset_holding_id:
        raise errors.validation("Field 'asset_holding_id' is required")
    reit = db.reits.get(reit_id)
    if reit is None:
        raise errors.not_found("reit_id does not resolve to an existing REIT")
    asset = db.asset_holdings.get(asset_holding_id)
    if asset is None:
        raise errors.not_found("asset_holding_id does not resolve to an existing asset")

    sale_price_cents = req_int(body, "sale_price_cents", min_value=0)
    if sale_price_cents <= 0:
        raise errors.validation("sale_price_cents must be > 0")
    basis_cents = req_int(body, "basis_cents", min_value=0)
    sale_date = req_date(body, "sale_date")

    # Cross-reit referential consistency (priority 9)
    if asset["reit_id"] != reit_id:
        raise errors.cross_reit("asset_holding_id belongs to a different REIT than the sale")

    sale = make_entity({
        "reit_id": reit_id,
        "asset_holding_id": asset_holding_id,
        "sale_price_cents": sale_price_cents,
        "basis_cents": basis_cents,
        "sale_date": sale_date,
        "status": "DRAFT",
        "holding_period_months": None,
        "is_prohibited": None,
        "prohibited_tax_cents": None,
    })
    db.asset_sales[sale["id"]] = sale
    return success_object(dict(sale), status=201)


@bp.route("/reit-compliance/asset-sales/<sid>", methods=["GET"])
def get_sale(sid):
    require_roles(*ALL)
    sale = db.asset_sales.get(sid)
    if sale is None:
        raise errors.not_found("Asset sale not found")
    return success_object(dict(sale))


@bp.route("/reit-compliance/asset-sales", methods=["GET"])
def list_sales():
    require_roles(*ALL)
    limit, offset = parse_pagination(request.args)
    rows = list(db.asset_sales.values())
    reit_id = request.args.get("reit_id")
    asset_holding_id = request.args.get("asset_holding_id")
    if reit_id is not None:
        rows = [s for s in rows if s["reit_id"] == reit_id]
    if asset_holding_id is not None:
        rows = [s for s in rows if s["asset_holding_id"] == asset_holding_id]
    page, total = paginate(rows, limit, offset)
    return success_list([dict(s) for s in page], limit, offset, total)


@bp.route("/reit-compliance/asset-sales/<sid>/analyze", methods=["POST"])
def analyze_sale(sid):
    require_roles("ComplianceOfficer")
    sale = db.asset_sales.get(sid)
    if sale is None:
        raise errors.not_found("Asset sale not found")
    if sale["status"] != "DRAFT":
        raise errors.invalid_state("Only DRAFT sales can be analyzed")
    asset = db.asset_holdings.get(sale["asset_holding_id"])
    if asset is None:
        raise errors.not_found("Asset holding not found")
    if asset["status"] != "HELD":
        raise errors.invalid_state("Underlying asset must be HELD to analyze")

    result = calc_prohibited_transaction(
        asset, sale["sale_price_cents"], sale["basis_cents"], sale["sale_date"]
    )
    sale["holding_period_months"] = result["holding_period_months"]
    sale["is_prohibited"] = result["is_prohibited"]
    sale["prohibited_tax_cents"] = result["prohibited_tax_cents"]
    sale["status"] = "ANALYZED"
    touch(sale)
    return success_object(dict(sale))


@bp.route("/reit-compliance/asset-sales/<sid>/confirm", methods=["POST"])
def confirm_sale(sid):
    require_roles("TaxDirector")
    sale = db.asset_sales.get(sid)
    if sale is None:
        raise errors.not_found("Asset sale not found")
    if sale["status"] != "ANALYZED":
        raise errors.invalid_state("Only ANALYZED sales can be confirmed")
    reit = db.reits.get(sale["reit_id"])
    if reit is None:
        raise errors.not_found("REIT not found")
    # Posture gate (priority 12)
    if reit["status"] != "ACTIVE":
        raise errors.reit_suspended("Confirming a sale against a suspended REIT is not permitted")

    asset = db.asset_holdings.get(sale["asset_holding_id"])
    if asset is None:
        raise errors.not_found("Asset holding not found")
    asset["status"] = "SOLD"
    touch(asset)

    sale["status"] = "CONFIRMED"
    touch(sale)
    return success_object(dict(sale))


@bp.route("/reit-compliance/asset-sales/<sid>/void", methods=["POST"])
def void_sale(sid):
    require_roles("ComplianceOfficer")
    sale = db.asset_sales.get(sid)
    if sale is None:
        raise errors.not_found("Asset sale not found")
    if sale["status"] not in ("DRAFT", "ANALYZED"):
        raise errors.invalid_state("Only DRAFT or ANALYZED sales can be voided")
    sale["status"] = "VOID"
    touch(sale)
    return success_object(dict(sale))
