"""SalesReport endpoints (PRD §3.5). Append-only: id + created_at only."""
from __future__ import annotations

from flask import Blueprint, request

import db
from errors import APIError, ERR_NOT_FOUND, ERR_FK_NOT_FOUND, ERR_INVALID_REQUEST
from middleware import auth_required, ALL_ROLES
from response import ok_object, ok_array
from routes._helpers import (
    get_body, require_fields, serialize, serialize_list, is_int,
    parse_pagination, paginate, order_by_created,
)
from services.common import new_append_only_fields

bp = Blueprint("sales_reports", __name__)


@bp.post("/sales-reports")
def create_sales_report():
    auth_required(ALL_ROLES)()
    body = get_body()
    require_fields(body, ["lease_id", "period_year", "gross_sales_cents"])

    lease_id = body["lease_id"]
    if db.leases.get(lease_id) is None:
        raise APIError(ERR_FK_NOT_FOUND, 404, "lease_id references a non-existent lease")

    period_year = body["period_year"]
    if not is_int(period_year) or period_year < 2000:
        raise APIError(ERR_INVALID_REQUEST, 400, "period_year must be an integer >= 2000")

    gross_sales = body["gross_sales_cents"]
    if not is_int(gross_sales) or gross_sales < 0:
        raise APIError(ERR_INVALID_REQUEST, 400, "gross_sales_cents must be a non-negative integer")

    report = {
        **new_append_only_fields(),
        "lease_id": lease_id,
        "period_year": period_year,
        "gross_sales_cents": gross_sales,
    }
    db.sales_reports[report["id"]] = report
    return ok_object(serialize(report), http_status=201)


@bp.get("/sales-reports/<sid>")
def get_sales_report(sid):
    auth_required(ALL_ROLES)()
    r = db.sales_reports.get(sid)
    if r is None:
        raise APIError(ERR_NOT_FOUND, 404, "Sales report not found")
    return ok_object(serialize(r))


@bp.get("/sales-reports")
def list_sales_reports():
    auth_required(ALL_ROLES)()
    limit, offset = parse_pagination()
    items = list(db.sales_reports.values())

    lease_id = request.args.get("lease_id")
    if lease_id is not None:
        items = [r for r in items if r["lease_id"] == lease_id]

    period_year = request.args.get("period_year")
    if period_year is not None:
        try:
            py = int(period_year)
        except (TypeError, ValueError):
            raise APIError(ERR_INVALID_REQUEST, 400, "period_year filter must be an integer")
        items = [r for r in items if r["period_year"] == py]

    items = order_by_created(items)
    page, total = paginate(items, limit, offset)
    return ok_array(serialize_list(page), limit, offset, total)
