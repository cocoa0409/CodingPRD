"""Sales: quoting, completion with round-up settlement, void (PRD §3.9)."""

from flask import Blueprint, request

from db import db
from errors import ApiError
from middleware import require_roles, get_body, validate_payload
from response import success
from services.core import make_common, touch, paginate, sorted_by_created, sale_price, ROUNDUP_STEP

bp = Blueprint("sales", __name__)

PAYMENT_METHODS = ["CASH", "CARD", "VOUCHER"]


def sale_view(s):
    return {
        "id": s["id"],
        "bike_id": s["bike_id"],
        "buyer_name": s["buyer_name"],
        "buyer_email": s["buyer_email"],
        "buyer_membership_id": s["buyer_membership_id"],
        "quoted_price_cents": s["quoted_price_cents"],
        "final_price_cents": s["final_price_cents"],
        "round_up": s["round_up"],
        "grand_total_cents": s["grand_total_cents"],
        "donation_cents": s["donation_cents"],
        "payment_method": s["payment_method"],
        "status": s["status"],
        "completed_at": s["completed_at"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def _get_sale(sale_id):
    sale = db.sales.get(sale_id)
    if sale is None:
        raise ApiError("ERR_NOT_FOUND", f"Sale {sale_id} does not exist")
    return sale


@bp.post("/sales")
def create_sale():
    require_roles("ShopCoordinator")
    body = get_body()
    validate_payload(body, {
        "bike_id": {"type": "string", "required": True},
        "buyer_name": {"type": "string", "required": True},
        "buyer_email": {"type": "string", "required": True},
        "buyer_membership_id": {"type": "string"},
    })
    bike = db.bikes.get(body["bike_id"])
    if bike is None:
        raise ApiError("ERR_NOT_FOUND", f"Bike {body['bike_id']} does not exist")
    membership = None
    if body.get("buyer_membership_id") is not None:
        membership = db.memberships.get(body["buyer_membership_id"])
        if membership is None:
            raise ApiError("ERR_NOT_FOUND", f"ToolMembership {body['buyer_membership_id']} does not exist")
    if bike["status"] != "READY_FOR_DISPOSITION":
        raise ApiError("ERR_BIKE_NOT_AVAILABLE", "Bike is not READY_FOR_DISPOSITION")
    if membership is not None and membership["status"] != "ACTIVE":
        raise ApiError("ERR_MEMBERSHIP_NOT_ACTIVE", "Buyer membership must be ACTIVE")
    if any(s["bike_id"] == bike["id"] and s["status"] == "PENDING" for s in db.sales.values()):
        raise ApiError("ERR_SALE_ALREADY_PENDING", "Bike already has a PENDING sale")

    sale = make_common()
    sale.update({
        "bike_id": bike["id"],
        "buyer_name": body["buyer_name"],
        "buyer_email": body["buyer_email"],
        "buyer_membership_id": body.get("buyer_membership_id"),
        "quoted_price_cents": sale_price(bike, body.get("buyer_membership_id")),
        "final_price_cents": None,
        "round_up": body.get("round_up", False) if isinstance(body.get("round_up", False), bool) else False,
        "grand_total_cents": None,
        "donation_cents": None,
        "payment_method": None,
        "status": "PENDING",
        "completed_at": None,
    })
    db.sales[sale["id"]] = sale
    return success(sale_view(sale), status=201)


@bp.get("/sales/<sale_id>")
def get_sale(sale_id):
    require_roles("ShopCoordinator", "ProgramDirector")
    return success(sale_view(_get_sale(sale_id)))


@bp.get("/sales")
def list_sales():
    require_roles("ShopCoordinator", "ProgramDirector")
    rows = list(db.sales.values())
    for param in ("bike_id", "buyer_membership_id", "status"):
        value = request.args.get(param)
        if value is not None:
            rows = [s for s in rows if s[param] == value]
    rows = sorted_by_created(rows)
    page, pg = paginate(rows)
    return success([sale_view(s) for s in page], pagination=pg)


@bp.post("/sales/<sale_id>/complete")
def complete_sale(sale_id):
    require_roles("ShopCoordinator")
    body = get_body()
    validate_payload(body, {
        "payment_method": {"type": "string", "required": True, "enum": PAYMENT_METHODS},
        "round_up": {"type": "boolean"},
    })
    sale = _get_sale(sale_id)
    bike = db.bikes.get(sale["bike_id"])
    if bike is None:
        raise ApiError("ERR_NOT_FOUND", f"Bike {sale['bike_id']} does not exist")
    if sale["status"] != "PENDING":
        raise ApiError("ERR_SALE_NOT_PENDING", "Only a PENDING sale can be completed")
    if bike["status"] != "READY_FOR_DISPOSITION":
        raise ApiError("ERR_BIKE_NOT_AVAILABLE", "Bike is not READY_FOR_DISPOSITION")
    if not any(d["recipient_kind"] == "SALE_BUYER" and d.get("sale_id") == sale["id"]
               for d in db.helmet_distributions.values()):
        raise ApiError("ERR_HELMET_REQUIRED", "A helmet must be distributed to the buyer first")

    # FINAL price: re-evaluated against current bike data and membership status.
    final_price = sale_price(bike, sale["buyer_membership_id"])
    round_up = body.get("round_up")
    if round_up is None:
        round_up = sale["round_up"]
    if round_up:
        grand_total = ((final_price + ROUNDUP_STEP - 1) // ROUNDUP_STEP) * ROUNDUP_STEP
        donation = grand_total - final_price
    else:
        grand_total = final_price
        donation = 0

    sale["final_price_cents"] = final_price
    sale["round_up"] = round_up
    sale["grand_total_cents"] = grand_total
    sale["donation_cents"] = donation
    sale["payment_method"] = body["payment_method"]
    sale["completed_at"] = db.now_iso()
    sale["status"] = "COMPLETED"
    touch(sale)
    bike["status"] = "SOLD"
    touch(bike)
    return success(sale_view(sale))


@bp.post("/sales/<sale_id>/void")
def void_sale(sale_id):
    require_roles("ProgramDirector")
    get_body()
    sale = _get_sale(sale_id)
    if sale["status"] != "PENDING":
        raise ApiError("ERR_SALE_NOT_PENDING", "Only a PENDING sale can be voided")
    sale["status"] = "VOIDED"
    touch(sale)
    return success(sale_view(sale))
