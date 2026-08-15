"""Pre-punch walks (PRD 3.2): scheduling with half-open inspector overlap,
completion gating on the logical clock."""
from datetime import timedelta

from flask import Blueprint

from authz import GCPM, GCINSP, ALL_ROLES, require_roles
from db import store
from derived import recompute_project, recompute_trade
from errors import (
    invalid_request, invalid_state, scheduled_in_past, trade_not_in_project,
    walk_not_started, walk_overlap,
)
from respond import success
from serialize import ser_walk
from store_ops import (
    get_or_404, json_body, new_common_fields, new_id, paginate, query_filters,
    req_str, req_temporal, sorted_by_creation, touch,
)

bp = Blueprint("walks", __name__, url_prefix="/closeout")

MIN_WALK_DURATION = timedelta(minutes=30)


@bp.route("/punch-walks", methods=["POST"])
def create_walk():
    require_roles([GCPM])
    data = json_body()
    project_id = req_str(data, "project_id")
    trade_package_id = req_str(data, "trade_package_id")
    lead_inspector_id = req_str(data, "lead_inspector_id")
    start = req_temporal(data, "scheduled_start")
    end = req_temporal(data, "scheduled_end")
    # Schema (priority 5): the window must span at least 30 minutes.
    if end - start < MIN_WALK_DURATION:
        raise invalid_request("Walk window must be at least 30 minutes")
    p = get_or_404(store.projects, project_id)
    t = get_or_404(store.trade_packages, trade_package_id)
    if p["status"] != "PUNCH_ACTIVE":
        raise invalid_state("Walks may only be scheduled while PUNCH_ACTIVE")
    # Temporal (priority 10): no scheduling in the past.
    if start < store.clock:
        raise scheduled_in_past()
    # Domain (priority 11): half-open [start, end) overlap per lead inspector —
    # a walk starting exactly when another ends is permissible.
    for w in store.punch_walks.values():
        if w["lead_inspector_id"] != lead_inspector_id:
            continue
        if start < w["scheduled_end"] and w["scheduled_start"] < end:
            raise walk_overlap()
    # Referential (priority 12).
    if t["project_id"] != project_id:
        raise trade_not_in_project()
    w = {
        "id": new_id(),
        "_seq": next(store.seq),
        "project_id": project_id,
        "trade_package_id": trade_package_id,
        "lead_inspector_id": lead_inspector_id,
        "scheduled_start": start,
        "scheduled_end": end,
        "status": "SCHEDULED",
    }
    w.update(new_common_fields())
    store.punch_walks[w["id"]] = w
    return success(ser_walk(w), status=201)


@bp.route("/punch-walks/<wid>", methods=["GET"])
def get_walk(wid):
    require_roles(ALL_ROLES)
    return success(ser_walk(get_or_404(store.punch_walks, wid)))


@bp.route("/punch-walks", methods=["GET"])
def list_walks():
    require_roles(ALL_ROLES)
    filters = query_filters("project_id", "trade_package_id", "lead_inspector_id")
    items = [w for w in store.punch_walks.values()
             if all(w[k] == v for k, v in filters.items())]
    page, pagination = paginate(sorted_by_creation(items))
    return success([ser_walk(w) for w in page], response_type="array",
                   pagination=pagination)


@bp.route("/punch-walks/<wid>/complete", methods=["POST"])
def complete_walk(wid):
    require_roles([GCINSP, GCPM])
    w = get_or_404(store.punch_walks, wid)
    if w["status"] != "SCHEDULED":
        raise invalid_state("Only a SCHEDULED walk can be completed")
    # Completion allowed once the logical clock reaches scheduled_start (>=).
    if store.clock < w["scheduled_start"]:
        raise walk_not_started()
    w["status"] = "COMPLETED"
    touch(w)
    # Bubble-up: the trade's has_completed_walk flips; project sc_eligible is
    # recomputed (PRD 3.2).
    recompute_trade(store.trade_packages[w["trade_package_id"]])
    recompute_project(store.projects[w["project_id"]])
    return success(ser_walk(w))
