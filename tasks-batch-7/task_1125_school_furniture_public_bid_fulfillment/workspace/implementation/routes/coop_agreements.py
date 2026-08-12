"""CoopPriceAgreement endpoints."""
from flask import Blueprint

from db import new_record, public, store
from errors import ERR_INVALID_REQUEST, raise_err
from middleware import ALL_ROLES, authenticate, require_roles
from response import success
from validation import body, get_or_404, req_int, req_list, req_str

bp = Blueprint("coop_agreements", __name__)


@bp.route("/v1/coop-agreements", methods=["POST"])
def create_coop_agreement():
    caller = authenticate()
    require_roles(caller, ["ContractManager"])
    data = body()
    name = req_str(data, "name")
    contract_year = req_int(data, "contract_year")
    tier_table = req_list(data, "tier_table")
    if len(tier_table) == 0:
        raise_err(ERR_INVALID_REQUEST, "Field 'tier_table' must contain at least one row")
    for row in tier_table:
        if not isinstance(row, dict):
            raise_err(ERR_INVALID_REQUEST, "Each tier_table row must be an object")
        min_qty = row.get("min_qty")
        unit_price = row.get("unit_price_cents")
        if isinstance(min_qty, bool) or not isinstance(min_qty, int) or min_qty < 1:
            raise_err(ERR_INVALID_REQUEST, "tier_table rows require integer min_qty >= 1")
        if isinstance(unit_price, bool) or not isinstance(unit_price, int) or unit_price < 1:
            raise_err(ERR_INVALID_REQUEST, "tier_table rows require integer unit_price_cents >= 1")

    rec = new_record({
        "name": name,
        "contract_year": contract_year,
        "tier_table": [
            {"min_qty": row["min_qty"], "unit_price_cents": row["unit_price_cents"]}
            for row in tier_table
        ],
        "status": "ACTIVE",
    })
    store.coop_agreements[rec["id"]] = rec
    return success(public(rec), code=201)


@bp.route("/v1/coop-agreements/<rid>", methods=["GET"])
def get_coop_agreement(rid):
    caller = authenticate()
    require_roles(caller, ALL_ROLES)
    rec = get_or_404(store.coop_agreements, rid, "coop agreement")
    return success(public(rec), code=200)
