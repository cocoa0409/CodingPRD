"""SaleRecord endpoints (PRD §3.4, §3.8)."""

from flask import Blueprint, request

from db import DB
from errors import (
    ERR_SESSION_NOT_FOUND,
    ERR_ALLOCATION_NOT_FOUND,
    ERR_SALE_NOT_FOUND,
    ERR_SESSION_NOT_OPEN,
    ERR_NOT_RESOURCE_OWNER,
    ERR_CROSS_TOUR_REFERENCE,
    ERR_PRICE_NOT_SET,
    ERR_INSUFFICIENT_ALLOCATION,
    ERR_ALREADY_TERMINAL,
    ERR_INVALID_SETTLEMENT_STATE,
    ERR_VALIDATION,
    err,
)
from middleware import (
    require_role,
    require_auth,
    get_json_body,
    require_int,
    require_enum,
    require_string,
    base_fields,
    touch,
    paginate,
)
from response import success_object, success_list
from services.core import allocation_on_hand, settlement_of_show
from services.serializers import sale_record_view

bp = Blueprint("sale_records", __name__)


def get_sale_or_404(sale_id):
    r = DB.sale_records.get(sale_id)
    if r is None:
        raise err(ERR_SALE_NOT_FOUND, 404, "No SaleRecord with the given id")
    return r


@bp.post("/merch/sale-records")
def create_sale_record():
    user_id, role = require_role("Seller")
    body = get_json_body()
    session_id = body.get("session_id")
    allocation_id = body.get("allocation_id")

    if session_id is None:
        raise err(ERR_VALIDATION, 400, "Missing required field: session_id")
    session = DB.sessions.get(session_id)
    if session is None:
        raise err(ERR_SESSION_NOT_FOUND, 404, "No SellerSession with the given id")

    # Ownership (priority 2): the seller records into their own session.
    if session["seller_id"] != user_id:
        raise err(ERR_NOT_RESOURCE_OWNER, 403,
                  "A seller records sales only into their own session")

    if allocation_id is None:
        raise err(ERR_VALIDATION, 400, "Missing required field: allocation_id")
    alloc = DB.allocations.get(allocation_id)
    if alloc is None:
        raise err(ERR_ALLOCATION_NOT_FOUND, 404, "No Allocation with the given id")

    if session["status"] != "OPEN":
        raise err(ERR_SESSION_NOT_OPEN, 409, "Sales require an OPEN session")

    if alloc["show_id"] != session["show_id"]:
        raise err(ERR_CROSS_TOUR_REFERENCE, 422,
                  "Allocation must belong to the session's show")

    price_row = None
    for sp in DB.show_products.values():
        if sp["show_id"] == session["show_id"] and sp["product_id"] == alloc["product_id"]:
            price_row = sp
            break
    if price_row is None:
        raise err(ERR_PRICE_NOT_SET, 422,
                  "No ShowProduct price row exists for the sale's (show, product)")

    quantity = require_int(body, "quantity", gt=0, required=True)
    tender = require_enum(body, "tender", ("CASH", "CARD"), required=True)

    if quantity > allocation_on_hand(alloc):
        raise err(ERR_INSUFFICIENT_ALLOCATION, 409,
                  "Requested quantity exceeds the allocation's quantity_on_hand")

    record = {
        **base_fields(),
        "session_id": session_id,
        "allocation_id": allocation_id,
        "show_id": session["show_id"],
        "product_id": alloc["product_id"],
        "quantity": quantity,
        "tender": tender,
        "unit_price_cents": price_row["price_cents"],
        "gross_cents": quantity * price_row["price_cents"],
        "status": "ACTIVE",
        "void_reason": None,
        "voided_by_user_id": None,
    }
    DB.sale_records[record["id"]] = record
    return success_object(sale_record_view(record), status=201)


@bp.get("/merch/sale-records")
def list_sale_records():
    require_auth()
    session_id = request.args.get("session_id")
    show_id = request.args.get("show_id")
    allocation_id = request.args.get("allocation_id")
    product_id = request.args.get("product_id")
    items = list(DB.sale_records.values())
    if session_id is not None:
        items = [r for r in items if r["session_id"] == session_id]
    if show_id is not None:
        items = [r for r in items if r["show_id"] == show_id]
    if allocation_id is not None:
        items = [r for r in items if r["allocation_id"] == allocation_id]
    if product_id is not None:
        items = [r for r in items if r["product_id"] == product_id]
    items.sort(key=lambda r: r["created_at"])
    page, limit, offset, total = paginate(items)
    return success_list([sale_record_view(r) for r in page], limit, offset, total)


@bp.get("/merch/sale-records/<sale_id>")
def get_sale_record(sale_id):
    require_auth()
    return success_object(sale_record_view(get_sale_or_404(sale_id)))


@bp.post("/merch/sale-records/<sale_id>/void")
def void_sale_record(sale_id):
    user_id, role = require_role("Seller", "Accountant")
    record = get_sale_or_404(sale_id)
    session = DB.sessions[record["session_id"]]
    show = DB.shows[record["show_id"]]

    if role == "Seller":
        if session["seller_id"] != user_id:
            raise err(ERR_NOT_RESOURCE_OWNER, 403,
                      "A seller voids only records from their own session")
        if record["status"] != "ACTIVE":
            raise err(ERR_ALREADY_TERMINAL, 409, "Record already voided")
        if session["status"] != "OPEN":
            raise err(ERR_SESSION_NOT_OPEN, 409,
                      "Seller voids require the session to be OPEN")
    else:  # Accountant audit void
        if record["status"] != "ACTIVE":
            raise err(ERR_ALREADY_TERMINAL, 409, "Record already voided")
        settlement = settlement_of_show(show["id"])
        if show["status"] != "RECONCILING" or settlement is None \
                or settlement["status"] not in ("PROVISIONAL", "DISPUTED"):
            raise err(ERR_INVALID_SETTLEMENT_STATE, 409,
                      "Audit void requires the show RECONCILING and the settlement "
                      "PROVISIONAL or DISPUTED")

    body = get_json_body()
    void_reason = require_string(body, "void_reason")

    record["status"] = "VOIDED"
    record["void_reason"] = void_reason
    record["voided_by_user_id"] = user_id
    touch(record)
    return success_object(sale_record_view(record))
