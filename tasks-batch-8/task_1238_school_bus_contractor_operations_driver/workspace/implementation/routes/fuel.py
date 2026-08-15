"""FuelPriceEntry endpoints (append-only)."""
from flask import Blueprint, request

import db
from envelope import success_list, success_object
from errors import ERR_FUEL_ENTRY_DUPLICATE_MONTH, raise_err
from middleware import authenticate, get_or_404, require_roles
from validation import (
    get_body,
    paginate,
    pagination_params,
    req_int,
    req_month,
    req_str,
)

bp = Blueprint("fuel_entries", __name__)

READ_ROLES = {"SystemAdmin", "DistrictAdmin", "ContractorOps", "FinanceClerk"}


@bp.route("/busops/fuel-price-entries", methods=["POST"])
def create_fuel_entry():
    body = get_body()
    district_id = req_str(body, "district_id")
    month = req_month(body, "effective_month")
    price = req_int(body, "avg_price_cents_per_gallon", minimum=0)
    source = req_str(body, "source")
    actor = authenticate()
    require_roles(actor, {"FinanceClerk"})
    get_or_404("districts", district_id, "District")
    for e in db.all_of("fuel_entries"):
        if e["district_id"] == district_id and e["effective_month"] == month:
            raise_err(
                ERR_FUEL_ENTRY_DUPLICATE_MONTH,
                "A fuel price entry already exists for this district and month",
            )
    rec = {
        "id": db.new_id(),
        "district_id": district_id,
        "effective_month": month,
        "avg_price_cents_per_gallon": price,
        "source": source,
    }
    db.stamp_append_only(rec)
    db.STORES["fuel_entries"][rec["id"]] = rec
    return success_object(db.public(rec), status=201)


@bp.route("/busops/fuel-price-entries", methods=["GET"])
def list_fuel_entries():
    limit, offset = pagination_params()
    actor = authenticate()
    require_roles(actor, READ_ROLES)
    items = list(db.all_of("fuel_entries"))
    district_id = request.args.get("district_id")
    month = request.args.get("effective_month")
    if district_id is not None:
        items = [e for e in items if e["district_id"] == district_id]
    if month is not None:
        items = [e for e in items if e["effective_month"] == month]
    page, info = paginate(items, limit, offset)
    return success_list(page, info)


@bp.route("/busops/fuel-price-entries/<rid>", methods=["GET"])
def get_fuel_entry(rid):
    actor = authenticate()
    require_roles(actor, READ_ROLES)
    rec = get_or_404("fuel_entries", rid, "FuelPriceEntry")
    return success_object(db.public(rec))
