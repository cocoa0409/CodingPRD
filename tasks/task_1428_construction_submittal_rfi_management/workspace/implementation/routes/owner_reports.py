"""OwnerReport routes: create (OCC), publish, metrics."""
from flask import Blueprint, request

import calc
from authz import ALL_ROLES, PROJECT_ENGINEER, require_roles
from db import store
from errors import (
    invalid_date_range,
    project_not_found,
    report_not_draft,
    report_not_found,
    stale_project_version,
)
from respond import success
from serialize import ser_owner_report
from services import require_active_or_closeout
from store_ops import (
    json_body,
    new_common_fields,
    new_id,
    paginate,
    req_date,
    req_int,
    sorted_by_creation,
    touch,
)

bp = Blueprint("owner_reports", __name__)


def get_report_or_404(report_id):
    r = store.owner_reports.get(report_id)
    if r is None:
        raise report_not_found()
    return r


@bp.route("/v1/projects/<projectId>/owner-reports", methods=["POST"])
def create_report(projectId):
    require_roles([PROJECT_ENGINEER])
    project = store.projects.get(projectId)
    if project is None:
        raise project_not_found()
    data = json_body()
    period_start = req_date(data, "period_start")
    period_end = req_date(data, "period_end")
    expected_project_version = req_int(data, "expected_project_version")

    if period_end < period_start:
        raise invalid_date_range("period_end must be on or after period_start")

    if project["version"] != expected_project_version:
        raise stale_project_version()

    require_active_or_closeout(project)

    report = {
        "id": new_id(),
        "_seq": next(store.seq),
        **new_common_fields(),
        "project_id": projectId,
        "period_start": period_start,
        "period_end": period_end,
        "status": "DRAFT",
        "published_at": None,
        "snapshot_metrics": None,
        "superseded_by_report_id": None,
    }
    store.owner_reports[report["id"]] = report

    # Supersede any overlapping PUBLISHED report (inclusive interval overlap)
    for other in store.owner_reports.values():
        if other["id"] == report["id"]:
            continue
        if other["project_id"] != projectId:
            continue
        if other["status"] != "PUBLISHED":
            continue
        # Overlap: new.start <= other.end AND other.start <= new.end
        if period_start <= other["period_end"] and other["period_start"] <= period_end:
            other["status"] = "SUPERSEDED"
            other["superseded_by_report_id"] = report["id"]
            touch(other)
    touch(project)
    return success(ser_owner_report(report), status=201)


@bp.route("/v1/projects/<projectId>/owner-reports", methods=["GET"])
def list_project_reports(projectId):
    require_roles(ALL_ROLES)
    project = store.projects.get(projectId)
    if project is None:
        raise project_not_found()
    items = sorted_by_creation(
        [r for r in store.owner_reports.values() if r["project_id"] == projectId]
    )
    page, pagination = paginate(items)
    return success([ser_owner_report(r) for r in page], response_type="array", pagination=pagination)


@bp.route("/v1/owner-reports", methods=["GET"])
def list_reports():
    require_roles(ALL_ROLES)
    items = list(store.owner_reports.values())
    project_id = request.args.get("project_id")
    if project_id:
        items = [r for r in items if r["project_id"] == project_id]
    status = request.args.get("status")
    if status:
        items = [r for r in items if r["status"] == status]
    items = sorted_by_creation(items)
    page, pagination = paginate(items)
    return success([ser_owner_report(r) for r in page], response_type="array", pagination=pagination)


@bp.route("/v1/owner-reports/<reportId>", methods=["GET"])
def get_report(reportId):
    require_roles(ALL_ROLES)
    rep = get_report_or_404(reportId)
    return success(ser_owner_report(rep))


@bp.route("/v1/owner-reports/<reportId>/publish", methods=["POST"])
def publish_report(reportId):
    require_roles([PROJECT_ENGINEER])
    rep = get_report_or_404(reportId)
    project = store.projects.get(rep["project_id"])
    if project is None:
        raise project_not_found()
    require_active_or_closeout(project)
    if rep["status"] != "DRAFT":
        raise report_not_draft()
    metrics = calc.compute_owner_report_metrics(
        rep["project_id"], rep["period_start"], rep["period_end"]
    )
    rep["snapshot_metrics"] = metrics
    rep["published_at"] = store.clock
    rep["status"] = "PUBLISHED"
    touch(rep)
    return success(ser_owner_report(rep))


@bp.route("/v1/owner-reports/<reportId>/metrics", methods=["GET"])
def get_report_metrics(reportId):
    require_roles(ALL_ROLES)
    rep = get_report_or_404(reportId)
    view = request.args.get("view", "published")
    if view not in ("published", "live"):
        from errors import invalid_request
        raise invalid_request("view must be 'published' or 'live'")
    if view == "live":
        metrics = calc.compute_owner_report_metrics(
            rep["project_id"], rep["period_start"], rep["period_end"]
        )
    else:
        metrics = rep.get("snapshot_metrics") or {
            "open_submittals": 0,
            "overdue_rfis": 0,
            "avg_rfi_response_days": 0.0,
            "first_pass_yield_pct": 0.0,
            "open_escalation_events": 0,
        }
    out = {"view": view}
    out.update(metrics)
    return success(out)
