"""ChartDeficiency endpoints (PRD §3.1)."""
from flask import Blueprint, request

from db import now, sort_default, stamp_new, store, touch
from errors import (ERR_CHART_NOT_FOUND, ERR_INVALID_REQUEST,
                    ERR_INVALID_STATE, fail)
from middleware import ALL_ROLES, require_roles
from response import ok_obj, paginate
from services.calc import maybe_ready_chart
from services.core import DEFICIENCY_TYPES, ser_deficiency
from validators import body, has, req_dt, req_enum

bp = Blueprint("deficiencies", __name__)


def get_deficiency_or_404(def_id):
    d = store.deficiencies.get(def_id)
    if d is None:
        fail(404, ERR_INVALID_REQUEST, f"ChartDeficiency {def_id} does not exist")
    return d


@bp.route("/deficiencies", methods=["POST"])
def create_deficiency():
    require_roles("CodingManager")
    b = body()
    if not has(b, "chart_id"):
        fail(400, ERR_INVALID_REQUEST, "chart_id is required")
    chart = store.charts.get(b["chart_id"])
    if chart is None:
        fail(404, ERR_CHART_NOT_FOUND, f"Chart {b['chart_id']} does not exist")
    dtype = req_enum(b, "type", DEFICIENCY_TYPES)
    due_at = req_dt(b, "due_at")
    deficiency = stamp_new({
        "chart_id": chart["id"],
        "type": dtype,
        "due_at": due_at,
        "status": "OPEN",
        "resolved_at": None,
    })
    store.deficiencies[deficiency["id"]] = deficiency
    chart["open_deficiency_count"] += 1
    touch(chart)
    return ok_obj(ser_deficiency(deficiency), 201)


@bp.route("/deficiencies/<id>", methods=["GET"])
def get_deficiency(id):
    require_roles(*ALL_ROLES)
    return ok_obj(ser_deficiency(get_deficiency_or_404(id)), 200)


@bp.route("/deficiencies", methods=["GET"])
def list_deficiencies():
    require_roles(*ALL_ROLES)
    items = list(store.deficiencies.values())
    chart_id = request.args.get("chart_id")
    if chart_id is not None:
        items = [d for d in items if d["chart_id"] == chart_id]
    status = request.args.get("status")
    if status is not None:
        items = [d for d in items if d["status"] == status]
    return paginate([ser_deficiency(d) for d in sort_default(items)])


@bp.route("/deficiencies/<id>/resolve", methods=["POST"])
def resolve_deficiency(id):
    require_roles("CodingManager")
    deficiency = get_deficiency_or_404(id)
    if deficiency["status"] != "OPEN":
        fail(409, ERR_INVALID_STATE,
             f"Cannot resolve a deficiency in state {deficiency['status']}")
    deficiency["status"] = "RESOLVED"
    deficiency["resolved_at"] = now()
    touch(deficiency)
    chart = store.charts[deficiency["chart_id"]]
    chart["open_deficiency_count"] -= 1
    maybe_ready_chart(chart)
    touch(chart)
    return ok_obj(ser_deficiency(deficiency), 200)
