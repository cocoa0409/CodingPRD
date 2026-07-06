from datetime import date

from flask import Blueprint, request, g

from db import (
    db, MIN_RESIDUAL_BED_UM, MAX_SAFE_K_DIOPTERS,
    MAX_TREATABLE_DIOPTERS, MIN_AGE_YEARS,
)
from middleware import require_auth
from response import success
from helpers import (
    stamp_create, touch, serialize, get_json_body, get_or_404,
    as_int, as_number, as_str, as_enum, paginate, sorted_by_created,
)
from errors import err
from services.calc import ablation_depth_um, residual_stromal_bed_um

bp = Blueprint("screenings", __name__)


@bp.post("/refractive/screenings")
@require_auth(["Optometrist"])
def create_screening():
    body = get_json_body()
    patient_id = as_str(body, "patient_id")
    performed_by = as_str(body, "performed_by_optometrist_id")
    thickness = as_int(body, "corneal_thickness_um")
    k_max = as_number(body, "topography_k_max")
    error = as_number(body, "refractive_error_diopters")

    # existence: left-to-right on body-referenced ids
    get_or_404(db.patients, patient_id)
    get_or_404(db.optometrists, performed_by)

    if thickness < 0:
        raise err("ERR_INVALID_REQUEST", "corneal_thickness_um must be >= 0")
    if k_max <= 0:
        raise err("ERR_INVALID_REQUEST", "topography_k_max must be > 0")
    if error < 0:
        raise err("ERR_INVALID_REQUEST", "refractive_error_diopters must be >= 0")

    rec = {
        "patient_id": patient_id,
        "performed_by_optometrist_id": performed_by,
        "corneal_thickness_um": thickness,
        "topography_k_max": k_max,
        "refractive_error_diopters": error,
        "ablation_depth_um": None,
        "residual_stromal_bed_um": None,
        "status": "DRAFT",
        "rejection_reason": None,
    }
    stamp_create(rec)
    db.screenings[rec["id"]] = rec
    return success(serialize(rec), 201)


@bp.get("/refractive/screenings/<sid>")
@require_auth(["Coordinator", "Surgeon", "Optometrist", "Patient"])
def get_screening(sid):
    return success(serialize(get_or_404(db.screenings, sid)), 200)


@bp.get("/refractive/screenings")
@require_auth(["Coordinator", "Surgeon", "Optometrist"])
def list_screenings():
    items = list(db.screenings.values())
    pid = request.args.get("patient_id")
    if pid is not None:
        items = [x for x in items if x["patient_id"] == pid]
    performed = request.args.get("performed_by_optometrist_id")
    if performed is not None:
        items = [x for x in items if x["performed_by_optometrist_id"] == performed]
    status = request.args.get("status")
    if status is not None:
        items = [x for x in items if x["status"] == status]
    items = sorted_by_created(items)
    page, meta = paginate(items)
    return success([serialize(x) for x in page], 200, is_array=True, pagination=meta)


@bp.post("/refractive/screenings/<sid>/submit")
@require_auth(["Optometrist"])
def submit_screening(sid):
    scr = get_or_404(db.screenings, sid)
    # state gate
    if scr["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Screening must be DRAFT to submit")
    # ownership: acting optometrist == performed_by
    if g.user_id != scr["performed_by_optometrist_id"]:
        raise err("ERR_FORBIDDEN", "Only the performing optometrist may submit")

    # compute in pinned order: ablation first, then residual
    ab = ablation_depth_um(scr["refractive_error_diopters"])
    scr["ablation_depth_um"] = ab
    scr["residual_stromal_bed_um"] = residual_stromal_bed_um(scr["corneal_thickness_um"], ab)
    scr["status"] = "SUBMITTED"
    touch(scr)
    return success(serialize(scr), 200)


def _age_years(dob_str, now_dt):
    """Whole-year age at now_dt from an ISO date-of-birth string."""
    y, m, d = dob_str.split("-")
    born = date(int(y), int(m), int(d))
    today = now_dt.date()
    years = today.year - born.year
    if (today.month, today.day) < (born.month, born.day):
        years -= 1
    return years


@bp.post("/refractive/screenings/<sid>/adjudicate")
@require_auth(["Surgeon"])
def adjudicate_screening(sid):
    scr = get_or_404(db.screenings, sid)
    body = get_json_body()
    decision = as_enum(body, "decision", {"APPROVE", "REJECT"})

    if scr["status"] != "SUBMITTED":
        raise err("ERR_INVALID_STATE", "Screening must be SUBMITTED to adjudicate")

    patient = db.patients.get(scr["patient_id"])

    # Evaluate the four safety gates in pinned order.
    def failing_gate():
        if scr["residual_stromal_bed_um"] < MIN_RESIDUAL_BED_UM:
            return ("THIN_BED", "ERR_RESIDUAL_BED_TOO_THIN")
        if scr["topography_k_max"] >= MAX_SAFE_K_DIOPTERS:
            return ("HIGH_K", "ERR_ECTASIA_RISK_K")
        if scr["refractive_error_diopters"] > MAX_TREATABLE_DIOPTERS:
            return ("HIGH_ERROR", "ERR_ERROR_UNTREATABLE")
        age = _age_years(patient["date_of_birth"], db.now())
        if age < MIN_AGE_YEARS:
            return ("UNDERAGE", "ERR_PATIENT_UNDERAGE")
        return None

    gate = failing_gate()

    if decision == "APPROVE":
        if gate is not None:
            raise err(gate[1], "Approval refused: %s" % gate[0])
        scr["status"] = "APPROVED"
        touch(scr)
        # bubble-up: patient becomes CANDIDATE
        if patient is not None:
            patient["status"] = "CANDIDATE"
            touch(patient)
        return success(serialize(scr), 200)

    # REJECT: record reason from first failing gate; may downgrade patient
    scr["status"] = "REJECTED"
    scr["rejection_reason"] = gate[0] if gate is not None else None
    touch(scr)
    # if patient has no APPROVED screening -> INELIGIBLE
    if patient is not None:
        has_approved = any(
            s["patient_id"] == patient["id"] and s["status"] == "APPROVED"
            for s in db.screenings.values()
        )
        if not has_approved:
            patient["status"] = "INELIGIBLE"
            touch(patient)
    return success(serialize(scr), 200)
