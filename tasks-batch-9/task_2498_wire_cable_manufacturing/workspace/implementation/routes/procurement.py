"""Settlement price series and rod receipt (PRD 3.1)."""

from flask import Blueprint

import constants as C
import errors
import lookups
import response
import validation
from auth import require_auth
from db import all_sorted, db, new_record
from serializers import view, views
from services.pricing import _quote_rank_key
from util import money

bp = Blueprint("procurement", __name__)


# --------------------------------------------------------------------------
# Settlement prices
# --------------------------------------------------------------------------
@bp.route("/metal-price-quotes", methods=["POST"])
def create_quote():
    require_auth("ProcurementBuyer", "PlantAdmin")
    b = validation.body()
    metal = validation.f_enum(b, "metal", C.METALS)
    effective_date = validation.f_date(b, "effective_date")
    price = validation.f_num(b, "settlement_price_usd_per_lb", gt=0)
    source = validation.f_enum(b, "source", C.QUOTE_SOURCES, required=False, default="COMEX")

    for q in db.metal_price_quotes.values():
        if q["metal"] == metal and q["effective_date"] == effective_date:
            errors.fail(
                errors.ERR_DUPLICATE_METAL_QUOTE,
                "A settlement price for %s on %s already exists" % (metal, effective_date),
            )

    rec = new_record(common_fields=False)
    rec.update({
        "metal": metal,
        "effective_date": effective_date,
        "settlement_price_usd_per_lb": price,
        "source": source,
    })
    db.metal_price_quotes[rec["id"]] = rec
    return response.created(view("metal_price_quote", rec))


@bp.route("/metal-price-quotes", methods=["GET"])
def list_quotes():
    require_auth("ProcurementBuyer", "ProcessEngineer", "BillingAnalyst", "PlantAdmin")
    limit, offset = validation.pagination()
    metal = validation.q_enum("metal", C.METALS)
    date_from = validation.q_date("effective_date_from")
    date_to = validation.q_date("effective_date_to")

    rows = list(db.metal_price_quotes.values())
    if metal is not None:
        rows = [r for r in rows if r["metal"] == metal]
    if date_from is not None:
        rows = [r for r in rows if r["effective_date"] >= date_from]
    if date_to is not None:
        rows = [r for r in rows if r["effective_date"] <= date_to]

    # The price series reads newest settlement date first (PRD 2.3).
    rows.sort(key=_quote_rank_key, reverse=True)
    page, total = response.paginate(rows, limit, offset)
    return response.ok_list(views("metal_price_quote", page), limit, offset, total)


# --------------------------------------------------------------------------
# Rod purchase lots
# --------------------------------------------------------------------------
@bp.route("/rod-purchase-lots", methods=["POST"])
def create_rod_lot():
    require_auth("ProcurementBuyer", "PlantAdmin")
    b = validation.body()
    metal = validation.f_enum(b, "metal", C.METALS)
    supplier_code = validation.f_str(b, "supplier_code")
    diameter = validation.f_num(b, "rod_diameter_mm", gt=0)
    heat_number = validation.f_str(b, "heat_number")
    weight = validation.f_num(b, "purchase_weight_lbs", gt=0)
    price = validation.f_num(b, "purchase_price_usd_per_lb", gt=0)
    basis = validation.f_enum(b, "pricing_basis", C.PRICING_BASES)
    received_date = validation.f_date(b, "received_date")

    rec = new_record()
    rec.update({
        "metal": metal,
        "supplier_code": supplier_code,
        "rod_diameter_mm": diameter,
        "heat_number": heat_number,
        "purchase_weight_lbs": weight,
        "purchase_price_usd_per_lb": price,
        "pricing_basis": basis,
        "received_date": received_date,
        "remaining_lbs": money(weight),
        "committed_lbs": money("0"),
        "scrapped_lbs": money("0"),
        "status": "RECEIVED",
    })
    db.rod_purchase_lots[rec["id"]] = rec
    return response.created(view("rod_purchase_lot", rec))


@bp.route("/rod-purchase-lots/<rod_lot_id>", methods=["GET"])
def get_rod_lot(rod_lot_id):
    require_auth("ProcurementBuyer", "ProcessEngineer", "QualityEngineer", "PlantAdmin")
    rec = lookups.rod_lot(rod_lot_id)
    return response.ok(view("rod_purchase_lot", rec))


@bp.route("/rod-purchase-lots", methods=["GET"])
def list_rod_lots():
    require_auth("ProcurementBuyer", "ProcessEngineer", "QualityEngineer", "PlantAdmin")
    limit, offset = validation.pagination()
    metal = validation.q_enum("metal", C.METALS)
    status = validation.q_enum("status", C.ROD_LOT_STATUSES)

    rows = all_sorted(db.rod_purchase_lots)
    if metal is not None:
        rows = [r for r in rows if r["metal"] == metal]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = response.paginate(rows, limit, offset)
    return response.ok_list(views("rod_purchase_lot", page), limit, offset, total)
