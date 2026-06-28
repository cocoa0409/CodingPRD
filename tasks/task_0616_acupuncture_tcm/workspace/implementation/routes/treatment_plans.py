"""TreatmentPlan routes (PRD 3.3) — cyclic lifecycle + cancel cascade."""

from flask import Blueprint, request

from common import (
    get_json_body,
    paginate,
    public,
    require_fields,
    require_int_min,
    stamp_new,
    touch,
)
from db import db
from errors import err
from lookups import get_intake, get_patient, get_plan, get_practitioner
from middleware import get_auth, require_role
from response import success
from services.appointment import cancel as cancel_appointment

bp = Blueprint("treatment_plans", __name__)


@bp.route("/treatment-plans", methods=["POST"])
def create_plan():
    _, role = get_auth()
    require_role(role, ["Practitioner"])
    body = get_json_body()
    require_fields(
        body,
        ["patient_id", "practitioner_id", "intake_id", "acupoints", "planned_sessions"],
    )
    # Body FK existence (priority 5), left-to-right per the listed vocabulary.
    patient = get_patient(body["patient_id"])
    practitioner = get_practitioner(body["practitioner_id"])
    intake = get_intake(body["intake_id"])

    # Well-formedness.
    acupoints = body.get("acupoints")
    if not isinstance(acupoints, list) or not all(isinstance(x, str) for x in acupoints):
        raise err("ERR_INVALID_REQUEST", "acupoints must be an array of point codes.")
    planned_sessions = require_int_min(body, "planned_sessions", 1)

    # Cross-entity referential: intake must be FINALIZED and belong to same patient.
    if intake["status"] != "FINALIZED" or intake["patient_id"] != patient["id"]:
        raise err(
            "ERR_INTAKE_NOT_FINALIZED",
            "Plan creation requires the referenced Intake to be FINALIZED and belong to the same patient.",
        )

    rec = {
        "patient_id": patient["id"],
        "practitioner_id": practitioner["id"],
        "intake_id": intake["id"],
        "acupoints": acupoints,
        "planned_sessions": planned_sessions,
        "status": "ACTIVE",
    }
    stamp_new(rec)
    db.treatment_plans[rec["id"]] = rec
    return success(public(rec), status=201)


@bp.route("/treatment-plans", methods=["GET"])
def list_plans():
    user_id, role = get_auth()
    require_role(role, ["ClinicAdmin", "Practitioner", "Patient"])
    items = list(db.treatment_plans.values())
    if role == "Patient":
        items = [p for p in items if p["patient_id"] == user_id]
    else:
        pf = request.args.get("patient_id")
        if pf is not None:
            items = [p for p in items if p["patient_id"] == pf]
    prf = request.args.get("practitioner_id")
    if prf is not None:
        items = [p for p in items if p["practitioner_id"] == prf]
    itf = request.args.get("intake_id")
    if itf is not None:
        items = [p for p in items if p["intake_id"] == itf]
    data, pg = paginate(items, public)
    return success(data, status=200, pagination=pg)


@bp.route("/treatment-plans/<rid>", methods=["GET"])
def get_plan_route(rid):
    user_id, role = get_auth()
    require_role(role, ["ClinicAdmin", "Practitioner", "Patient"])
    rec = get_plan(rid)
    if role == "Patient" and user_id != rec["patient_id"]:
        raise err("ERR_OWNERSHIP_MISMATCH", "Patient may read only their own plans.")
    return success(public(rec), status=200)


@bp.route("/treatment-plans/<rid>/hold", methods=["POST"])
def hold_plan(rid):
    _, role = get_auth()
    require_role(role, ["Practitioner"])
    rec = get_plan(rid)
    if rec["status"] != "ACTIVE":
        raise err("ERR_PLAN_NOT_ACTIVE", "Hold requires TreatmentPlan.status == ACTIVE.")
    rec["status"] = "ON_HOLD"
    touch(rec)
    return success(public(rec), status=200)


@bp.route("/treatment-plans/<rid>/resume", methods=["POST"])
def resume_plan(rid):
    _, role = get_auth()
    require_role(role, ["Practitioner"])
    rec = get_plan(rid)
    if rec["status"] != "ON_HOLD":
        raise err("ERR_PLAN_NOT_ON_HOLD", "Resume requires TreatmentPlan.status == ON_HOLD.")
    rec["status"] = "ACTIVE"
    touch(rec)
    return success(public(rec), status=200)


@bp.route("/treatment-plans/<rid>/complete", methods=["POST"])
def complete_plan(rid):
    _, role = get_auth()
    require_role(role, ["Practitioner"])
    rec = get_plan(rid)
    if rec["status"] != "ACTIVE":
        raise err("ERR_PLAN_NOT_ACTIVE", "Complete requires TreatmentPlan.status == ACTIVE.")
    # No open appointments (SCHEDULED or CHECKED_IN) of this plan.
    for appt in db.appointments.values():
        if appt["treatment_plan_id"] == rec["id"] and appt["clinical_status"] in (
            "SCHEDULED",
            "CHECKED_IN",
        ):
            raise err(
                "ERR_PLAN_HAS_OPEN_APPOINTMENTS",
                "Complete requires no SCHEDULED/CHECKED_IN appointments on the plan.",
            )
    rec["status"] = "COMPLETED"
    touch(rec)
    return success(public(rec), status=200)


@bp.route("/treatment-plans/<rid>/cancel", methods=["POST"])
def cancel_plan(rid):
    _, role = get_auth()
    require_role(role, ["Practitioner"])
    rec = get_plan(rid)
    body = get_json_body()
    # State precondition: ACTIVE or ON_HOLD.
    if rec["status"] not in ("ACTIVE", "ON_HOLD"):
        raise err(
            "ERR_PLAN_NOT_CANCELLABLE",
            "Cancel requires TreatmentPlan.status IN {ACTIVE, ON_HOLD}.",
        )
    # OCC on the plan's own version.
    require_fields(body, ["expected_treatment_plan_version"])
    expected = body.get("expected_treatment_plan_version")
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise err("ERR_INVALID_REQUEST", "expected_treatment_plan_version must be an integer.")
    if expected != rec["version"]:
        raise err("ERR_STALE_VERSION", "expected_treatment_plan_version does not match.")

    rec["status"] = "CANCELLED"
    touch(rec)

    # CASCADE: cancel every SCHEDULED/CHECKED_IN appointment of this plan,
    # firing each appointment's full cancellation side-effects.
    for appt in list(db.appointments.values()):
        if appt["treatment_plan_id"] == rec["id"] and appt["clinical_status"] in (
            "SCHEDULED",
            "CHECKED_IN",
        ):
            patient = db.patients.get(appt["patient_id"])
            cancel_appointment(appt, patient)

    return success(public(rec), status=200)
