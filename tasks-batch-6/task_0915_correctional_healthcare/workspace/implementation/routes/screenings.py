"""Intake screenings: the receiving/full-assessment clock and its disposition."""

from flask import Blueprint, request

import calc
import serializers
import store
from constants import DISPOSITION, FINDINGS_CODE, SCREENING_STATUS, SCREENING_TYPE
from envelope import created, listing, ok, page_params
from errors import ApiError
from ladder import Ctx

bp = Blueprint("screenings", __name__)


@bp.post("/inmates/<inmate_id>/intake-screenings")
def open_screening(inmate_id):
    ctx = Ctx(roles=("IntakeOfficer", "Nurse"))
    ctx.path_inmate(inmate_id)
    ctx.freeze_gate()
    ctx.require("screening_type")
    ctx.enum("screening_type", SCREENING_TYPE)
    ctx.run()

    screening_type = ctx.body["screening_type"]
    row = store.base_row()
    row.update({
        "inmate_id": inmate_id,
        "screening_type": screening_type,
        "due_at": calc.intake_screening_due_at(ctx.inmate, screening_type),
        "completed_at": None,
        "status": "PENDING",
        "findings_code": None,
        "completed_late": False,
    })
    store.intake_screenings[row["id"]] = row
    return created(serializers.intake_screening(row))


@bp.get("/inmates/<inmate_id>/intake-screenings")
def list_screenings(inmate_id):
    ctx = Ctx(roles=("IntakeOfficer", "Nurse", "Provider", "HealthServicesAdmin"))
    ctx.path_inmate(inmate_id)
    ctx.run()

    limit, offset = page_params(request.args)
    rows = [s for s in store.intake_screenings.values() if s["inmate_id"] == inmate_id]
    wanted_type = request.args.get("screening_type")
    if wanted_type:
        rows = [s for s in rows if s["screening_type"] == wanted_type]
    wanted_status = request.args.get("status")
    if wanted_status:
        rows = [s for s in rows if s["status"] == wanted_status]
    rows = store.sort_rows(rows)
    return listing(serializers.many(serializers.intake_screening, rows), limit, offset)


@bp.post("/intake-screenings/<screening_id>/disposition")
def dispose_screening(screening_id):
    ctx = Ctx(roles=("Nurse",))

    def bind(row):
        ctx.inmate = store.inmates.get(row["inmate_id"])
    ctx.need("screening", store.intake_screenings, screening_id,
             "ERR_RECORD_NOT_FOUND", on_found=bind)
    ctx.freeze_gate()
    ctx.require("disposition")

    def findings_required():
        if ctx.body.get("disposition") == "COMPLETED" and ctx.body.get("findings_code") is None:
            raise ApiError("ERR_VALIDATION", "findings_code is required on a COMPLETED disposition")
    ctx.at(8, findings_required, sub=0)
    ctx.enum("disposition", DISPOSITION)
    ctx.enum("findings_code", FINDINGS_CODE)
    ctx.status_in(lambda: ctx.row("screening"), ("PENDING", "OVERDUE"))
    ctx.run()

    row = ctx.row("screening")
    if ctx.body["disposition"] == "COMPLETED":
        completed_at = store.now()
        row["status"] = "COMPLETED"
        row["completed_at"] = completed_at
        row["findings_code"] = ctx.body["findings_code"]
        row["completed_late"] = completed_at.dt > row["due_at"].dt
        if row["screening_type"] == "FULL_ASSESSMENT" and ctx.inmate is not None:
            ctx.inmate["prior_full_assessment_at"] = completed_at
    else:
        row["status"] = "REFUSED"
        row["completed_at"] = None
        row["completed_late"] = False
    store.touch(row)
    return ok(serializers.intake_screening(row))
