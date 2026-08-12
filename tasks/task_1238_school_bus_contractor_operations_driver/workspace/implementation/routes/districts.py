"""District endpoints."""
from flask import Blueprint

import db
from envelope import success_list, success_object
from middleware import authenticate, get_or_404, require_roles
from services.pricing import district_outstanding_balance
from validation import get_body, opt_int, paginate, pagination_params, req_int, req_str

bp = Blueprint("districts", __name__)

ALL_ROLES = {
    "SystemAdmin",
    "DistrictAdmin",
    "ContractorOps",
    "HRRecruiter",
    "FleetManager",
    "FinanceClerk",
    "Driver",
}


def serialize(district):
    out = db.public(district)
    out["outstanding_balance_cents"] = district_outstanding_balance(district["id"])
    return out


@bp.route("/busops/districts", methods=["POST"])
def create_district():
    body = get_body()
    name = req_str(body, "name")
    region = req_str(body, "region_fuel_index_code")
    credit_limit = req_int(body, "credit_limit_cents", minimum=0)
    window = opt_int(body, "billing_dispute_window_days", default=30, minimum=0)
    actor = authenticate()
    require_roles(actor, {"SystemAdmin"})

    rec = {
        "id": db.new_id(),
        "name": name,
        "region_fuel_index_code": region,
        "credit_limit_cents": credit_limit,
        "billing_dispute_window_days": window,
        "status": "ACTIVE",
    }
    db.stamp_new(rec)
    db.STORES["districts"][rec["id"]] = rec
    return success_object(serialize(rec), status=201)


@bp.route("/busops/districts", methods=["GET"])
def list_districts():
    limit, offset = pagination_params()
    actor = authenticate()
    require_roles(actor, ALL_ROLES)
    items, info = paginate(list(db.all_of("districts")), limit, offset)
    for i, item in enumerate(items):
        items[i] = serialize(db.find("districts", item["id"]))
    return success_list(items, info)


@bp.route("/busops/districts/<rid>", methods=["GET"])
def get_district(rid):
    actor = authenticate()
    require_roles(actor, ALL_ROLES)
    rec = get_or_404("districts", rid, "District")
    return success_object(serialize(rec))
