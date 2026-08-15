from flask import Blueprint, request

from db import store, new_entity, touch
from errors import (
    ApiError, ERR_DUPLICATE, ERR_INVALID_STATE, ERR_STALE_VERSION,
)
from middleware import require_roles
from response import object_response
from serializers import dashboard_view
from services.aggregates import compute_dashboard_panel
from validation import Payload, require_exists, list_page

bp = Blueprint("dashboards", __name__, url_prefix="/legal-ops/dashboards")

ALL = ("LegalOpsManager", "LegalOpsAnalyst", "LegalOpsExecutive")


@bp.post("")
@require_roles("LegalOpsAnalyst")
def create_dashboard(user_id, role):
    p = Payload()
    fp_id = p.req_str("fiscal_period_id")
    label = p.req_str("snapshot_label")
    if fp_id is not None:
        require_exists(store.fiscal_periods, fp_id, "fiscal period")
    # Uniqueness on (fiscal_period_id, snapshot_label) — priority 10.
    if fp_id is not None and label is not None:
        for d in store.dashboards.values():
            if d["fiscal_period_id"] == fp_id and d["snapshot_label"] == label:
                raise ApiError(ERR_DUPLICATE, 409, "Dashboard snapshot_label already exists for this period")
    p.finish()
    d = new_entity({
        "fiscal_period_id": fp_id,
        "snapshot_label": label,
        "status": "DRAFT",
        "_panel": compute_dashboard_panel(fp_id),
    })
    store.dashboards[d["id"]] = d
    return object_response(dashboard_view(d), 201)


@bp.get("")
@require_roles(*ALL)
def list_dashboards(user_id, role):
    items = list(store.dashboards.values())
    for param in ("fiscal_period_id", "status"):
        v = request.args.get(param)
        if v is not None:
            items = [d for d in items if d[param] == v]
    return list_page(items, dashboard_view)


@bp.get("/<did>")
@require_roles(*ALL)
def get_dashboard(user_id, role, did):
    return object_response(dashboard_view(require_exists(store.dashboards, did, "dashboard")))


@bp.post("/<did>/publish")
@require_roles("LegalOpsManager")
def publish(user_id, role, did):
    d = require_exists(store.dashboards, did, "dashboard")
    # State gate (priority 4): DRAFT only, and period must be SOFT_CLOSED/HARD_CLOSED.
    if d["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, 409, "Dashboard is not DRAFT")
    period = store.fiscal_periods.get(d["fiscal_period_id"])
    if period is None or period["status"] not in ("SOFT_CLOSED", "HARD_CLOSED"):
        raise ApiError(ERR_INVALID_STATE, 409, "Dashboard publish requires period SOFT_CLOSED or HARD_CLOSED")
    # OCC (priority 18) after the state gate.
    p = Payload()
    expected = p.opt_int("expected_dashboard_version", nullable=False)
    if expected is not None and expected != d["version"]:
        raise ApiError(ERR_STALE_VERSION, 412, "expected_dashboard_version does not match current version")
    p.finish()
    # Freeze the computed panel at publish time; supersede prior published rows.
    d["_panel"] = compute_dashboard_panel(d["fiscal_period_id"])
    d["status"] = "PUBLISHED"
    touch(d)
    for other in store.dashboards.values():
        if other["id"] != d["id"] and other["fiscal_period_id"] == d["fiscal_period_id"] \
                and other["status"] == "PUBLISHED":
            other["status"] = "SUPERSEDED"
            touch(other)
    return object_response(dashboard_view(d))
