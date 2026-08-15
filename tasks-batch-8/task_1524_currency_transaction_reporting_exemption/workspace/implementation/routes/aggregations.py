"""DailyCashAggregation computed-read endpoints."""
from flask import Blueprint, request

from db import store
from errors import ERR_AGGREGATION_NOT_FOUND, ApiError
from middleware import authenticate, sorted_page
from response import ok, ok_list
from serializers import serialize_aggregation

bp = Blueprint("aggregations", __name__)

ALL_ROLES = ["SystemAdmin", "BranchManager", "Teller", "ComplianceAnalyst", "BSAOfficer", "Examiner"]


@bp.get("/daily-aggregations")
def list_aggregations():
    authenticate(ALL_ROLES)
    items = list(store.aggregations.values())
    for param in ("customer_id", "business_date"):
        value = request.args.get(param)
        if value is not None:
            items = [r for r in items if r[param] == value]
    page, limit, offset, total = sorted_page(items)
    return ok_list([serialize_aggregation(r) for r in page], limit, offset, total)


@bp.get("/daily-aggregations/<agg_id>")
def get_aggregation(agg_id):
    authenticate(ALL_ROLES)
    for row in store.aggregations.values():
        if row["id"] == agg_id:
            return ok(serialize_aggregation(row))
    raise ApiError(ERR_AGGREGATION_NOT_FOUND, "Daily cash aggregation not found", 404)
