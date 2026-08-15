"""ResponsibilityDetermination standalone endpoints: get / finalize."""
from flask import Blueprint

import clock
import db
import domain
import response
from auth import require_roles
from errors import ApiError
from routes.common import (check_incident_read_scope, load_determination,
                           load_incident)

bp = Blueprint("determinations", __name__)

ALL = ("SystemAdmin", "Dispatcher", "FieldTechnician", "Supervisor", "Regulator")


@bp.route("/gas-ops/responsibility-determinations/<determinationId>", methods=["GET"])
@require_roles(*ALL)
def get_determination(determinationId, user_id, role):
    det = load_determination(determinationId)
    incident = load_incident(det["incident_id"])
    check_incident_read_scope(incident, role, user_id)
    return response.success(domain.ser_determination(det), 200)


@bp.route("/gas-ops/responsibility-determinations/<determinationId>/finalize", methods=["POST"])
@require_roles("Supervisor")
def finalize(determinationId, user_id, role):
    det = load_determination(determinationId)
    # Segregation of duties (cascade priority 4) precedes state legality (priority 6).
    if det["drafted_by_user_id"] == user_id:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "The determination finalizer must differ from its drafter", 403)
    if det["status"] != "DRAFT":
        raise ApiError("ERR_DETERMINATION_NOT_DRAFT",
                       "Finalize requires a DRAFT determination", 409)
    incident = load_incident(det["incident_id"])
    now = clock.now()
    det["status"] = "FINAL"
    det["finalized_at"] = now
    det["finalized_by_user_id"] = user_id
    domain.bump(det)
    for other in domain.determinations_of(incident["id"]):
        if other["id"] != det["id"] and other["status"] == "FINAL":
            other["status"] = "SUPERSEDED"
            domain.bump(other)
    if det["responsibility"] in ("OUTSIDE_COMPANY", "SHARED"):
        estimate = domain.provisional_estimate(det["responsibility"], incident["priority"])
        rec = domain.new_record(common_fields=True)
        rec.update({
            "incident_id": incident["id"],
            "origin": "AUTO_DETERMINATION",
            "status": "OPEN",
            "crew_id": None,
            "provisional_estimate_cents": estimate,
            "current_estimate_cents": estimate,
            "scheduled_window_start": None,
            "scheduled_window_end": None,
            "lines": None,
            "labor_minutes": None,
            "labor_billed_minutes": None,
            "final_cost_cents": None,
            "completed_at": None,
            "cancel_reason": None,
        })
        db.work_orders[rec["id"]] = rec
    domain.bump(incident)
    domain.mark_reports_stale(incident)
    return response.success(domain.ser_determination(det), 200)
