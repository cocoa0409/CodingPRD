"""Portfolio endpoints (§3.1, §3.2 ladder read, §3.7 compliance read)."""
from flask import Blueprint, request

from middleware import authorized, READ_ROLES
from response import success_object
from services.core import new_record, serialize_portfolio, compute_ladder, compute_compliance
from routes.helpers import (
    resolve_portfolio, sorted_items, paged,
)
from validate import get_body, req_str, req_int

bp = Blueprint("portfolios", __name__)


@bp.post("/portfolios")
def create_portfolio():
    authorized(["PlatformAdmin"])
    body = get_body()
    name = req_str(body, "name")
    region = req_str(body, "region")
    cap = req_int(body, "laddering_max_pct_per_year", minimum=0, maximum=100)
    p = new_record("portfolios", {
        "name": name,
        "region": region,
        "laddering_max_pct_per_year": cap,
        "total_active_square_feet": 0,
        "posture": "LADDER_OK",
        "posture_year": None,
    })
    return success_object(serialize_portfolio(p), 201)


@bp.get("/portfolios")
def list_portfolios():
    authorized(READ_ROLES)
    items = sorted_items("portfolios", {"region": request.args.get("region")})
    return paged(items, serialize_portfolio)


@bp.get("/portfolios/<pid>")
def get_portfolio(pid):
    authorized(READ_ROLES)
    p = resolve_portfolio(pid)
    return success_object(serialize_portfolio(p))


@bp.get("/portfolios/<pid>/ladder")
def get_ladder(pid):
    authorized(READ_ROLES)
    resolve_portfolio(pid)
    lad = compute_ladder(pid)
    return success_object({
        "years": lad["years"],
        "posture": lad["posture"],
        "posture_year": lad["posture_year"],
    })


@bp.get("/portfolios/<pid>/negotiations/compliance")
def get_compliance(pid):
    authorized(["PlatformAdmin", "AssetManager", "LandlordCounsel"])
    resolve_portfolio(pid)
    return success_object({"items": compute_compliance(pid)})
