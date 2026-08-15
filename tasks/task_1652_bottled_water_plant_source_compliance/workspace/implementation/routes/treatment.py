"""Treatment runs: schedule, start, record parameters, validate, reprocess, cancel."""
from flask import Blueprint, g, request

from db import store, new_resource, touch, by_creation
from errors import ApiError, err_invalid_state
from middleware import auth, ALL_ROLES
from response import ok_object, ok_list
from services import (
    as_datetime,
    as_number,
    get_body,
    get_or_404,
    run_json,
    raise_shape,
    treatment_verdict,
)

bp = Blueprint("treatment", __name__)

PL = ["ProductionLead"]


@bp.post("/api/plants/<plant_id>/treatment-runs")
@auth(PL)
def create_run(plant_id):
    plant = get_or_404(store.plants, plant_id, "plant")
    body = get_body()

    # Rung 3 — body FK existence.
    permit_id = body.get("source_permit_id")
    permit = None
    if isinstance(permit_id, str):
        permit = store.permits.get(permit_id)
    if permit_id is not None and permit is None:
        raise ApiError("ERR_NOT_FOUND", "source_permit_id does not reference an existing permit", 404)

    # Rung 11 — input shape.
    errs = []
    if permit is None:
        errs.append("source_permit_id is required")
    start, ok_s = as_datetime(body.get("scheduled_start"))
    if not ok_s:
        errs.append("scheduled_start must be a valid ISO 8601 datetime")
    end, ok_e = as_datetime(body.get("scheduled_end"))
    if not ok_e:
        errs.append("scheduled_end must be a valid ISO 8601 datetime")
    if ok_s and ok_e and end <= start:
        errs.append("scheduled_end must fall after scheduled_start")
    raise_shape(errs)

    run = new_resource(
        {
            "plant_id": plant["id"],
            "source_permit_id": permit_id,
            "scheduled_start": body.get("scheduled_start"),
            "scheduled_end": body.get("scheduled_end"),
            "uv_dose_mj_cm2": None,
            "ozone_ct_mg_min_l": None,
            "turbidity_ntu": None,
            "micro_pore_micron": None,
            "ro_rejection_pct": None,
            "status": "SCHEDULED",
            "validation_round": 0,
            "parameters_recorded_by_user_id": None,
            "validated_by_user_id": None,
        }
    )
    run["_start"] = start
    run["_end"] = end
    store.treatment_runs[run["id"]] = run
    return ok_object(run_json(run), 201)


@bp.get("/api/treatment-runs")
@auth(ALL_ROLES)
def list_runs():
    items = list(store.treatment_runs.values())
    plant_id = request.args.get("plant_id")
    source_permit_id = request.args.get("source_permit_id")
    status = request.args.get("status")
    if plant_id is not None:
        items = [r for r in items if r["plant_id"] == plant_id]
    if source_permit_id is not None:
        items = [r for r in items if r["source_permit_id"] == source_permit_id]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    return ok_list([run_json(r) for r in by_creation(items)])


@bp.get("/api/treatment-runs/<run_id>")
@auth(ALL_ROLES)
def get_run(run_id):
    run = get_or_404(store.treatment_runs, run_id, "treatment run")
    return ok_object(run_json(run))


@bp.post("/api/treatment-runs/<run_id>/start")
@auth(PL)
def start_run(run_id):
    run = get_or_404(store.treatment_runs, run_id, "treatment run")
    if run["status"] not in ("SCHEDULED", "REPROCESSING"):
        raise err_invalid_state("only a SCHEDULED or REPROCESSING run can be started")
    permit = store.permits.get(run["source_permit_id"])
    if permit is None or permit["status"] != "ACTIVE":
        raise ApiError("ERR_PERMIT_NOT_ACTIVE", "the run's source permit is not ACTIVE", 409)
    run["status"] = "IN_PROGRESS"
    touch(run)
    return ok_object(run_json(run))


@bp.post("/api/treatment-runs/<run_id>/record-parameters")
@auth(["ProductionLead", "QAOfficer"])
def record_parameters(run_id):
    run = get_or_404(store.treatment_runs, run_id, "treatment run")
    if run["status"] != "IN_PROGRESS":
        raise err_invalid_state("parameters may only be recorded while the run is IN_PROGRESS")
    body = get_body()

    errs = []
    uv, ok1 = as_number(body.get("uv_dose_mj_cm2"))
    if not ok1:
        errs.append("uv_dose_mj_cm2 must be a number")
    ozone, ok2 = as_number(body.get("ozone_ct_mg_min_l"))
    if not ok2:
        errs.append("ozone_ct_mg_min_l must be a number")
    turbidity, ok3 = as_number(body.get("turbidity_ntu"))
    if not ok3:
        errs.append("turbidity_ntu must be a number")
    micro, ok4 = as_number(body.get("micro_pore_micron"))
    if not ok4:
        errs.append("micro_pore_micron must be a number")
    ro = None
    if body.get("ro_rejection_pct") is not None:
        ro, ok5 = as_number(body.get("ro_rejection_pct"))
        if not ok5:
            errs.append("ro_rejection_pct must be a number")
    raise_shape(errs)

    run["uv_dose_mj_cm2"] = uv
    run["ozone_ct_mg_min_l"] = ozone
    run["turbidity_ntu"] = turbidity
    run["micro_pore_micron"] = micro
    run["ro_rejection_pct"] = ro
    run["parameters_recorded_by_user_id"] = g.user_id
    touch(run)
    return ok_object(run_json(run))


@bp.post("/api/treatment-runs/<run_id>/validate")
@auth(["QAOfficer"])
def validate_run(run_id):
    run = get_or_404(store.treatment_runs, run_id, "treatment run")
    if run["status"] != "IN_PROGRESS":
        raise err_invalid_state("only an IN_PROGRESS run can be validated")
    # Segregation of duties: validator != parameter recorder.
    if run.get("parameters_recorded_by_user_id") is not None and g.user_id == run["parameters_recorded_by_user_id"]:
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES",
            "the operator who recorded the parameters may not validate the run",
            409,
        )
    verdict = treatment_verdict(run)
    run["status"] = "VALIDATED" if verdict == "PASS" else "FAILED"
    run["validation_round"] += 1
    run["validated_by_user_id"] = g.user_id
    touch(run)
    return ok_object(run_json(run))


@bp.post("/api/treatment-runs/<run_id>/reprocess")
@auth(PL)
def reprocess_run(run_id):
    run = get_or_404(store.treatment_runs, run_id, "treatment run")
    if run["status"] != "FAILED":
        raise err_invalid_state("only a FAILED run can move to REPROCESSING")
    run["status"] = "REPROCESSING"
    touch(run)
    return ok_object(run_json(run))


@bp.post("/api/treatment-runs/<run_id>/cancel")
@auth(PL)
def cancel_run(run_id):
    run = get_or_404(store.treatment_runs, run_id, "treatment run")
    if run["status"] not in ("SCHEDULED", "FAILED"):
        raise err_invalid_state("only a SCHEDULED or FAILED run can be cancelled")
    run["status"] = "CANCELLED"
    touch(run)
    return ok_object(run_json(run))
