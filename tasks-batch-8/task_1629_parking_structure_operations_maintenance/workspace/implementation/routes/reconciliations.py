"""Reconciliation endpoints (PRD 3.5)."""
from flask import Blueprint, request

import db
from errors import (
    err_invalid_state, err_segregation, err_ref_not_found, err_validation,
    err_variance_incident,
)
from middleware import get_actor, require_roles, ALL_ROLES
from response import success_object, success_list
from services.common import (
    body, parse_pagination, paginate, get_reconciliation, public_view,
)
from services.fees import (
    refresh_shift_expected, classify_variance, variance_incident_severity,
)

bp = Blueprint("reconciliations", __name__)

NON_TERMINAL = ("DRAFT", "SUBMITTED", "VARIANCE_REVIEW")


@bp.post("/ops/reconciliations")
def create_reconciliation():
    actor = get_actor()
    require_roles(actor, ["RevenueAuditor"])
    payload = body()
    shift_id = payload.get("shift_id")
    if shift_id is None:
        raise err_validation("missing required field: shift_id")
    shift = db.shifts.get(shift_id)
    if shift is None:
        raise err_ref_not_found("shift_id not found")
    # segregation of duties (stage 4): auditor must differ from the attendant
    if actor.user_id == shift["attendant_user_id"]:
        raise err_segregation()
    if shift["shift_status"] not in ("CLOSED", "FORCE_CLOSED"):
        raise err_invalid_state("reconciliation requires a CLOSED or FORCE_CLOSED shift")
    if any(r["shift_id"] == shift["id"] and r["reconciliation_status"] in NON_TERMINAL
           for r in db.reconciliations.values()):
        raise err_invalid_state("shift already has a non-terminal reconciliation")
    ent = {
        "id": db.new_id(),
        "shift_id": shift["id"],
        "auditor_user_id": None,
        "reconciliation_status": "DRAFT",
        "variance_cents": None,
    }
    db.stamp_new(ent)
    db.reconciliations[ent["id"]] = ent
    return success_object(public_view(ent), status=201)


@bp.get("/ops/reconciliations/<reconciliation_id>")
def get_reconciliation_route(reconciliation_id):
    actor = get_actor()
    require_roles(actor, ALL_ROLES)
    return success_object(public_view(get_reconciliation(reconciliation_id)))


@bp.get("/ops/reconciliations")
def list_reconciliations():
    actor = get_actor()
    require_roles(actor, ALL_ROLES)
    limit, offset = parse_pagination()
    items = list(db.reconciliations.values())
    shift_id = request.args.get("shift_id")
    status = request.args.get("reconciliation_status")
    if shift_id is not None:
        items = [r for r in items if r["shift_id"] == shift_id]
    if status is not None:
        items = [r for r in items if r["reconciliation_status"] == status]
    page, total = paginate(items, limit, offset)
    return success_list([public_view(r) for r in page], limit, offset, total)


@bp.post("/ops/reconciliations/<reconciliation_id>/submit")
def submit_reconciliation(reconciliation_id):
    actor = get_actor()
    require_roles(actor, ["RevenueAuditor"])
    rec = get_reconciliation(reconciliation_id)
    shift = db.shifts[rec["shift_id"]]
    if actor.user_id == shift["attendant_user_id"]:
        raise err_segregation()
    if shift["counted_cash_cents"] is None:
        raise err_validation("shift has no declared counted_cash_cents")
    if rec["reconciliation_status"] != "DRAFT":
        raise err_invalid_state("only a DRAFT reconciliation may be submitted")
    refresh_shift_expected(shift)
    variance = shift["counted_cash_cents"] - shift["expected_cash_cents"]
    rec["variance_cents"] = variance
    rec["auditor_user_id"] = actor.user_id
    outcome = classify_variance(variance)
    rec["reconciliation_status"] = outcome
    db.touch(rec)
    if outcome == "VARIANCE_REVIEW":
        # auto-create the CASH_VARIANCE incident in OPEN
        incident = {
            "id": db.new_id(),
            "facility_id": shift["facility_id"],
            "patrol_round_id": None,
            "reconciliation_id": rec["id"],
            "incident_type": "CASH_VARIANCE",
            "severity": variance_incident_severity(variance),
            "description": f"Auto-created: cash variance {variance} cents on shift {shift['id']}",
            "incident_status": "OPEN",
            "duplicate_of_incident_id": None,
            "auto_created": True,
            "resolution_note": None,
        }
        db.stamp_new(incident)
        db.incidents[incident["id"]] = incident
    return success_object(public_view(rec))


@bp.post("/ops/reconciliations/<reconciliation_id>/approve")
def approve_reconciliation(reconciliation_id):
    actor = get_actor()
    require_roles(actor, ["RevenueAuditor"])
    rec = get_reconciliation(reconciliation_id)
    shift = db.shifts[rec["shift_id"]]
    payload = body()
    incident_id = payload.get("incident_id")
    incident = None
    if incident_id is not None:
        incident = db.incidents.get(incident_id)
        if incident is None:
            raise err_ref_not_found("incident_id not found")
    if actor.user_id == shift["attendant_user_id"]:
        raise err_segregation()
    if rec["reconciliation_status"] not in ("SUBMITTED", "VARIANCE_REVIEW"):
        raise err_invalid_state("only a SUBMITTED or VARIANCE_REVIEW reconciliation may be approved")
    if rec["reconciliation_status"] == "VARIANCE_REVIEW":
        if (incident is None
                or incident.get("reconciliation_id") != rec["id"]
                or incident["incident_type"] != "CASH_VARIANCE"
                or incident["incident_status"] != "INVESTIGATING"):
            raise err_variance_incident()
        incident["incident_status"] = "RESOLVED"
        db.touch(incident)
    rec["reconciliation_status"] = "APPROVED"
    db.touch(rec)
    shift["shift_status"] = "RECONCILED"
    db.touch(shift)
    return success_object(public_view(rec))
