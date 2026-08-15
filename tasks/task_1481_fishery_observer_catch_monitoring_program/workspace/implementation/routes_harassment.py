"""Harassment / interference reports (PRD 3.7)."""

from flask import Blueprint

import logic
import store
from core import (
    ALL_ROLES, body, err_forbidden, err_state, get_or_404, list_response, ok,
    req_dt, req_enum, req_str, require_roles,
)

bp = Blueprint("harassment", __name__, url_prefix="/observer-program")

REPORT_TYPES = ("HARASSMENT", "INTERFERENCE", "SAFETY_COERCION")


@bp.post("/deployments/<did>/harassment-reports")
def create_report(did):
    a = require_roles("Observer")
    d = get_or_404("deployments", did, "Deployment")
    if d["observer_id"] != a["id"]:
        raise err_forbidden("Only the deployment's own observer may file a report")
    b = body()
    report_type = req_enum(b, "report_type", REPORT_TYPES)
    narrative = req_str(b, "narrative")
    incident_date = req_dt(b, "incident_date")
    report = store.new_entity({
        "deployment_id": d["id"],
        "observer_id": a["id"],
        "vessel_id": d["vessel_id"],
        "report_type": report_type,
        "narrative": narrative,
        "incident_date": incident_date,
        "penalty_applied": False,
        "resolution_notes": None,
        "status": "FILED",
    })
    store.db["harassment_reports"][report["id"]] = report
    return ok(report, status=201)


@bp.get("/harassment-reports")
def list_reports():
    require_roles(*ALL_ROLES)
    return list_response("harassment_reports", {
        "deployment_id": "deployment_id",
        "observer_id": "observer_id",
        "vessel_id": "vessel_id",
        "status": "status",
    })


@bp.get("/harassment-reports/<rid>")
def get_report(rid):
    require_roles(*ALL_ROLES)
    return ok(get_or_404("harassment_reports", rid, "HarassmentReport"))


@bp.post("/harassment-reports/<rid>/start-review")
def start_review(rid):
    require_roles("ProgramCoordinator")
    r = get_or_404("harassment_reports", rid, "HarassmentReport")
    if r["status"] not in ("FILED", "APPEALED"):
        raise err_state("Only a FILED or APPEALED report can enter review")
    r["status"] = "UNDER_REVIEW"
    store.touch(r)
    return ok(r)


@bp.post("/harassment-reports/<rid>/substantiate")
def substantiate(rid):
    require_roles("ProgramAdmin")
    r = get_or_404("harassment_reports", rid, "HarassmentReport")
    b = body()
    notes = req_str(b, "resolution_notes")
    if r["status"] != "UNDER_REVIEW":
        raise err_state("Only an UNDER_REVIEW report can be substantiated")
    # Cascade hop 1: terminate the linked deployment if still at sea.
    d = store.db["deployments"].get(r["deployment_id"])
    if d is not None and d["status"] == "AT_SEA":
        notice = store.db["selection_notices"].get(d["selection_notice_id"])
        if notice is not None:
            logic.harassment_early_termination(d, notice)
    # Cascade hop 2 (first substantiation only): penalize the vessel.
    if not r["penalty_applied"]:
        vessel = store.db["vessels"].get(r["vessel_id"])
        if vessel is not None:
            vessel["selection_penalty_points"] += 3
            vessel["substantiated_harassment_count"] += 1
            store.touch(vessel)
        r["penalty_applied"] = True
    r["resolution_notes"] = notes
    r["status"] = "SUBSTANTIATED"
    store.touch(r)
    return ok(r)


@bp.post("/harassment-reports/<rid>/dismiss")
def dismiss(rid):
    require_roles("ProgramAdmin")
    r = get_or_404("harassment_reports", rid, "HarassmentReport")
    b = body()
    notes = req_str(b, "resolution_notes")
    if r["status"] != "UNDER_REVIEW":
        raise err_state("Only an UNDER_REVIEW report can be dismissed")
    # Compensation fires only when a penalty was previously applied
    # (i.e. dismissal after a successful appeal cycle).
    if r["penalty_applied"]:
        vessel = store.db["vessels"].get(r["vessel_id"])
        if vessel is not None:
            vessel["selection_penalty_points"] -= 3
            vessel["substantiated_harassment_count"] -= 1
            store.touch(vessel)
        r["penalty_applied"] = False
    r["resolution_notes"] = notes
    r["status"] = "DISMISSED"
    store.touch(r)
    return ok(r)


@bp.post("/harassment-reports/<rid>/appeal")
def appeal(rid):
    a = require_roles("VesselOperator")
    r = get_or_404("harassment_reports", rid, "HarassmentReport")
    vessel = store.db["vessels"].get(r["vessel_id"])
    if vessel is None or vessel["operator_id"] != a["id"]:
        raise err_forbidden("The acting operator does not own the report's vessel")
    if r["status"] != "SUBSTANTIATED":
        raise err_state("Only a SUBSTANTIATED report can be appealed")
    r["status"] = "APPEALED"
    store.touch(r)
    return ok(r)


@bp.post("/harassment-reports/<rid>/resolve")
def resolve(rid):
    require_roles("ProgramAdmin")
    r = get_or_404("harassment_reports", rid, "HarassmentReport")
    b = body()
    notes = req_str(b, "resolution_notes")
    if r["status"] != "SUBSTANTIATED":
        raise err_state("Only a SUBSTANTIATED report can be resolved")
    r["resolution_notes"] = notes
    r["status"] = "RESOLVED"
    store.touch(r)
    return ok(r)
