"""Monitoring visit endpoints."""
from flask import Blueprint, g, request

import db
import utils
from errors import ApiError
from middleware import ANY_ROLE, body, paginate, require_roles
from response import ok
from services import domain

bp = Blueprint("visits", __name__)


def get_visit_or_404(visit_id):
    r = db.monitoring_visits.get(visit_id)
    if r is None:
        raise ApiError("ERR_MONITORING_VISIT_NOT_FOUND", "MonitoringVisit id does not exist.", 404)
    return r


@bp.route("/stewardship/monitoring-visits", methods=["POST"])
@require_roles("StewardshipCoordinator")
def create_visit():
    b = body()
    easement_id = b.get("easement_id")
    if easement_id is not None and easement_id not in db.easements:
        raise ApiError("ERR_EASEMENT_NOT_FOUND", "Easement id does not exist.", 404)
    e = db.easements.get(easement_id)
    if e is not None and e["status"] != "RECORDED":
        raise ApiError("ERR_EASEMENT_NOT_RECORDED", "Child operational create requires a RECORDED easement.", 409)
    monitor = b.get("monitor_user_id")
    start = utils.parse_date(b.get("window_start_on"))
    end = utils.parse_date(b.get("window_end_on"))
    if e is None or not isinstance(monitor, str) or start is None or end is None or end <= start:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "easement_id, monitor_user_id and a window with window_end_on > window_start_on are required.",
            400,
        )
    # Per-monitor half-open [start, end) overlap; CANCELLED visits do not participate.
    for v in db.monitoring_visits.values():
        if v["monitor_user_id"] == monitor and v["status"] in ("SCHEDULED", "COMPLETED"):
            if start < v["window_end_on"] and v["window_start_on"] < end:
                raise ApiError(
                    "ERR_MONITOR_WINDOW_OVERLAP",
                    "Window overlaps another visit of the same monitor.",
                    409,
                )
    now = utils.now_iso()
    r = {
        "id": utils.new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "easement_id": easement_id,
        "monitor_user_id": monitor,
        "window_start_on": start,
        "window_end_on": end,
        "actual_visit_on": None,
        "findings_summary": None,
        "stewardship_cost_cents": None,
        "on_time": None,
        "status": "SCHEDULED",
    }
    db.monitoring_visits[r["id"]] = r
    return ok(domain.visit_json(r), 201)


@bp.route("/stewardship/monitoring-visits", methods=["GET"])
@require_roles(*ANY_ROLE)
def list_visits():
    filters = {}
    for key in ("easement_id", "monitor_user_id", "status"):
        v = request.args.get(key)
        if v is not None:
            filters[key] = v
    return paginate(list(db.monitoring_visits.values()), domain.visit_json, filters)


@bp.route("/stewardship/monitoring-visits/<monitoringVisitId>", methods=["GET"])
@require_roles(*ANY_ROLE)
def get_visit(monitoringVisitId):
    return ok(domain.visit_json(get_visit_or_404(monitoringVisitId)))


@bp.route("/stewardship/monitoring-visits/<monitoringVisitId>/complete", methods=["POST"])
@require_roles("FieldMonitor")
def complete_visit(monitoringVisitId):
    r = get_visit_or_404(monitoringVisitId)
    if r["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_VISIT_STATE", "Complete requires SCHEDULED.", 409)
    if g.user_id != r["monitor_user_id"]:
        raise ApiError("ERR_NOT_ASSIGNED_MONITOR", "Only the assigned monitor may complete the visit.", 403)
    b = body()
    actual = utils.parse_date(b.get("actual_visit_on"))
    findings = b.get("findings_summary")
    cost = b.get("stewardship_cost_cents")
    if actual is None or not isinstance(findings, str) or not utils.is_int(cost) or cost < 0:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "actual_visit_on, findings_summary and a non-negative integer stewardship_cost_cents are required.",
            400,
        )
    if not (r["window_start_on"] <= actual < r["window_end_on"]):
        raise ApiError("ERR_VISIT_OUTSIDE_WINDOW", "actual_visit_on must lie within [window_start_on, window_end_on).", 422)
    e = db.easements[r["easement_id"]]
    due_before = domain.next_monitoring_due_on(e)
    r["on_time"] = actual <= due_before if due_before is not None else None
    r["actual_visit_on"] = actual
    r["findings_summary"] = findings
    r["stewardship_cost_cents"] = cost
    r["status"] = "COMPLETED"
    domain.bump(r)
    # Cascade: easement calendar + posture, one version increment (PRD §2.5).
    e["last_monitoring_completed_on"] = actual
    domain.bump(e)
    return ok(domain.visit_json(r))


@bp.route("/stewardship/monitoring-visits/<monitoringVisitId>/cancel", methods=["POST"])
@require_roles("StewardshipCoordinator")
def cancel_visit(monitoringVisitId):
    r = get_visit_or_404(monitoringVisitId)
    if r["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_VISIT_STATE", "Cancel requires SCHEDULED.", 409)
    r["status"] = "CANCELLED"
    domain.bump(r)
    return ok(domain.visit_json(r))
