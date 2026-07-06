from flask import Blueprint, request

from db import db
from middleware import require_auth
from response import success
from helpers import (
    stamp_create, serialize, get_json_body, get_or_404,
    as_str, paginate, sorted_by_created,
)
from errors import err

bp = Blueprint("patients", __name__)


@bp.post("/refractive/patients")
@require_auth(["Anonymous", "Coordinator"])
def create_patient():
    body = get_json_body()
    name = as_str(body, "full_name")
    dob = as_str(body, "date_of_birth")
    co_od = body.get("co_managing_optometrist_id")
    if co_od is not None:
        if not isinstance(co_od, str):
            raise err("ERR_INVALID_REQUEST", "co_managing_optometrist_id must be a string")
        get_or_404(db.optometrists, co_od)
    rec = {
        "full_name": name,
        "date_of_birth": dob,
        "co_managing_optometrist_id": co_od,
        "status": "PROSPECT",
    }
    stamp_create(rec)
    db.patients[rec["id"]] = rec
    return success(serialize(rec), 201)


@bp.get("/refractive/patients/<pid>")
@require_auth(["Coordinator", "Surgeon", "Optometrist", "Patient"])
def get_patient(pid):
    return success(serialize(get_or_404(db.patients, pid)), 200)


@bp.get("/refractive/patients")
@require_auth(["Coordinator", "Surgeon", "Optometrist"])
def list_patients():
    items = list(db.patients.values())
    co_od = request.args.get("co_managing_optometrist_id")
    if co_od is not None:
        items = [x for x in items if x["co_managing_optometrist_id"] == co_od]
    status = request.args.get("status")
    if status is not None:
        items = [x for x in items if x["status"] == status]
    items = sorted_by_created(items)
    page, meta = paginate(items)
    return success([serialize(x) for x in page], 200, is_array=True, pagination=meta)


@bp.get("/refractive/patients/<pid>/screenings")
@require_auth(["Coordinator", "Surgeon", "Optometrist", "Patient"])
def list_patient_screenings(pid):
    get_or_404(db.patients, pid)
    items = [s for s in db.screenings.values() if s["patient_id"] == pid]
    items = sorted_by_created(items)
    page, meta = paginate(items)
    return success([serialize(x) for x in page], 200, is_array=True, pagination=meta)
