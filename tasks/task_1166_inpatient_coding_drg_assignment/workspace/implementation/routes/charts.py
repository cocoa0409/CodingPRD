"""Chart endpoints (PRD §3.1)."""
from flask import Blueprint, request

from db import sort_default, stamp_new, store
from errors import (ERR_ACCOUNT_NOT_FOUND, ERR_CHART_NOT_FOUND,
                    ERR_INVALID_REQUEST, fail)
from middleware import ALL_ROLES, require_roles
from response import ok_obj, paginate
from services.core import ACUITIES, ser_chart
from validators import body, has, req_enum

bp = Blueprint("charts", __name__)


def get_chart_or_404(chart_id):
    c = store.charts.get(chart_id)
    if c is None:
        fail(404, ERR_CHART_NOT_FOUND, f"Chart {chart_id} does not exist")
    return c


@bp.route("/charts", methods=["POST"])
def create_chart():
    require_roles("CodingManager")
    b = body()
    if not has(b, "account_id"):
        fail(400, ERR_INVALID_REQUEST, "account_id is required")
    account = store.accounts.get(b["account_id"])
    if account is None:
        fail(404, ERR_ACCOUNT_NOT_FOUND,
             f"PatientAccount {b['account_id']} does not exist")
    if any(c["account_id"] == account["id"] for c in store.charts.values()):
        fail(400, ERR_INVALID_REQUEST, "One chart per account")
    acuity = req_enum(b, "acuity", ACUITIES)
    chart = stamp_new({
        "account_id": account["id"],
        "acuity": acuity,
        "status": "OPEN",
        "open_deficiency_count": 0,
    })
    # Readiness interlock evaluated at creation: an already-discharged account
    # with a clean chart satisfies both conditions immediately.
    if account["status"] == "DISCHARGED":
        chart["status"] = "READY_FOR_CODING"
    store.charts[chart["id"]] = chart
    return ok_obj(ser_chart(chart), 201)


@bp.route("/charts/<id>", methods=["GET"])
def get_chart(id):
    require_roles(*ALL_ROLES)
    return ok_obj(ser_chart(get_chart_or_404(id)), 200)


@bp.route("/charts", methods=["GET"])
def list_charts():
    require_roles(*ALL_ROLES)
    items = list(store.charts.values())
    account_id = request.args.get("account_id")
    if account_id is not None:
        items = [c for c in items if c["account_id"] == account_id]
    status = request.args.get("status")
    if status is not None:
        items = [c for c in items if c["status"] == status]
    return paginate([ser_chart(c) for c in sort_default(items)])
