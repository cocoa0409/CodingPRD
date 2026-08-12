"""District endpoints."""
from flask import Blueprint

from db import new_record, public, store
from middleware import ALL_ROLES, authenticate, require_roles
from response import success
from validation import body, get_or_404, opt_bool, req_int, req_str

bp = Blueprint("districts", __name__)


@bp.route("/v1/districts", methods=["POST"])
def create_district():
    caller = authenticate()
    require_roles(caller, ["ContractorAdmin"])
    data = body()
    name = req_str(data, "name")
    annual_cap_cents = req_int(data, "annual_cap_cents", minimum=1)
    extended = opt_bool(data, "extended_warranty_enrolled", default=False)
    rec = new_record({
        "name": name,
        "annual_cap_cents": annual_cap_cents,
        "extended_warranty_enrolled": extended if extended is not None else False,
    })
    store.districts[rec["id"]] = rec
    return success(public(rec), code=201)


@bp.route("/v1/districts/<rid>", methods=["GET"])
def get_district(rid):
    caller = authenticate()
    require_roles(caller, ALL_ROLES)
    rec = get_or_404(store.districts, rid, "district")
    return success(public(rec), code=200)
