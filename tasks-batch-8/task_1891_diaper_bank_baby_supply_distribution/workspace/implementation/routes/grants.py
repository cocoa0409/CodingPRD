"""Grant endpoints (PRD §3.3, §3.8)."""

from flask import request

from db import store, base_fields, touch, now
from errors import (ERR_NOT_FOUND, ERR_DUPLICATE_CODE, ERR_VALIDATION,
                    ERR_GRANT_HAS_OPEN_POS, ERR_GRANT_NOT_ACTIVE, raise_err)
from middleware import authenticate, require_role
from response import success_object, get_body
from serialize import grant_json
from services.calc import impact_report
from validate import req_str, req_int, parse_datetime, parse_period
from . import make_blueprint

bp = make_blueprint("grants")

RESTRICTIONS = ["UNRESTRICTED", "PRODUCT_PURCHASE_ONLY", "OPERATIONS_ONLY"]
READ_ROLES = ["FinanceManager", "BankAdmin", "WarehouseManager"]


def _get_grant_or_404(grant_id):
    g = store.grants.get(grant_id)
    if g is None:
        raise_err(ERR_NOT_FOUND, "Grant not found.")
    return g


@bp.route("/grants", methods=["POST"])
def create_grant():
    _, role = authenticate()
    require_role(role, ["FinanceManager"])
    body = get_body()
    # Uniqueness (category 6) precedes full body validation (category 10).
    code = body.get("grant_code")
    if isinstance(code, str) and any(g["grant_code"] == code
                                     for g in store.grants.values()):
        raise_err(ERR_DUPLICATE_CODE, "grant_code is already in use.")
    funder = req_str(body, "funder_name")
    code = req_str(body, "grant_code")
    total = req_int(body, "total_amount_cents", minimum=1)
    start = parse_datetime(body.get("start_date"), "start_date")
    end = parse_datetime(body.get("end_date"), "end_date")
    restriction = body.get("restriction", "UNRESTRICTED")
    if restriction is None:
        restriction = "UNRESTRICTED"
    if restriction not in RESTRICTIONS:
        raise_err(ERR_VALIDATION, "restriction must be one of %s." % RESTRICTIONS)
    g = base_fields()
    g.update({
        "funder_name": funder, "grant_code": code, "total_amount_cents": total,
        "restriction": restriction, "start_date": start, "end_date": end,
        "status": "ACTIVE",
    })
    store.grants[g["id"]] = g
    return success_object(grant_json(g), status=201)


@bp.route("/grants/<grant_id>", methods=["GET"])
def get_grant(grant_id):
    _, role = authenticate()
    require_role(role, READ_ROLES)
    return success_object(grant_json(_get_grant_or_404(grant_id)))


@bp.route("/grants/<grant_id>/close", methods=["POST"])
def close_grant(grant_id):
    _, role = authenticate()
    require_role(role, ["FinanceManager"])
    g = _get_grant_or_404(grant_id)
    if g["status"] != "ACTIVE":
        raise_err(ERR_GRANT_NOT_ACTIVE, "Only an ACTIVE grant can be closed.")
    if any(po["grant_id"] == g["id"] and po["status"] == "SUBMITTED"
           for po in store.purchase_orders.values()):
        raise_err(ERR_GRANT_HAS_OPEN_POS,
                  "Grant has SUBMITTED purchase orders outstanding.")
    g["status"] = "CLOSED"
    touch(g)
    return success_object(grant_json(g))


@bp.route("/grants/<grant_id>/impact-report", methods=["GET"])
def grant_impact_report(grant_id):
    _, role = authenticate()
    require_role(role, ["FinanceManager", "BankAdmin"])
    g = _get_grant_or_404(grant_id)
    period = request.args.get("period")
    if period is None:
        c = now()
        year, month = c.year, c.month
    else:
        year, month = parse_period(period)
    return success_object(impact_report(g, year, month))
