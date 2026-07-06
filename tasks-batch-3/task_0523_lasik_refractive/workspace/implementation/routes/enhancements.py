from datetime import timedelta

from flask import Blueprint, request

from db import db
from middleware import require_auth
from response import success
from helpers import (
    stamp_create, touch, serialize, get_json_body, get_or_404,
    as_str, as_enum, paginate, sorted_by_created,
)
from errors import err

bp = Blueprint("enhancements", __name__)


def _deadline(origin_case):
    package = db.packages[origin_case["package_id"]]
    return origin_case["surgery_completed_at"] + timedelta(days=package["enhancement_window_days"])


@bp.post("/refractive/enhancements")
@require_auth(["Patient", "Coordinator"])
def create_enhancement():
    body = get_json_body()
    origin_case_id = as_str(body, "origin_case_id")
    patient_id = as_str(body, "patient_id")
    reason = as_str(body, "reason")

    origin = get_or_404(db.cases, origin_case_id)
    get_or_404(db.patients, patient_id)

    # origin must be HEALED and patient must match
    if origin["clinical_status"] != "HEALED":
        raise err("ERR_INVALID_STATE", "origin case must be HEALED")
    if origin["patient_id"] != patient_id:
        raise err("ERR_INVALID_REQUEST", "patient_id must equal origin case patient")

    # window eval: within iff now strictly before deadline
    deadline = _deadline(origin)
    within = db.now() < deadline
    if not within:
        raise err("ERR_ENHANCEMENT_WINDOW_EXPIRED", "enhancement window expired")

    rec = {
        "origin_case_id": origin_case_id,
        "patient_id": patient_id,
        "reason": reason,
        "re_screening_id": None,
        "status": "REQUESTED",
        "within_window": within,
    }
    stamp_create(rec)
    db.enhancements[rec["id"]] = rec
    return success(serialize(rec), 201)


@bp.get("/refractive/enhancements/<eid>")
@require_auth(["Coordinator", "Surgeon", "Optometrist", "Patient"])
def get_enhancement(eid):
    return success(serialize(get_or_404(db.enhancements, eid)), 200)


@bp.get("/refractive/enhancements")
@require_auth(["Coordinator", "Surgeon", "Optometrist", "Patient"])
def list_enhancements():
    items = list(db.enhancements.values())
    for field in ("origin_case_id", "patient_id", "re_screening_id", "status"):
        v = request.args.get(field)
        if v is not None:
            items = [x for x in items if x[field] == v]
    items = sorted_by_created(items)
    page, meta = paginate(items)
    return success([serialize(x) for x in page], 200, is_array=True, pagination=meta)


@bp.post("/refractive/enhancements/<eid>/rescreen")
@require_auth(["Optometrist"])
def rescreen(eid):
    enh = get_or_404(db.enhancements, eid)
    body = get_json_body()
    re_screening_id = as_str(body, "re_screening_id")
    screening = get_or_404(db.screenings, re_screening_id)

    if enh["status"] != "REQUESTED":
        raise err("ERR_INVALID_STATE", "enhancement must be REQUESTED to rescreen")

    # still within window
    origin = db.cases[enh["origin_case_id"]]
    if not (db.now() < _deadline(origin)):
        raise err("ERR_ENHANCEMENT_WINDOW_EXPIRED", "enhancement window expired")

    # re-screening must belong to enhancement's patient
    if screening["patient_id"] != enh["patient_id"]:
        raise err("ERR_INVALID_REQUEST", "re_screening must belong to enhancement patient")

    enh["re_screening_id"] = re_screening_id
    enh["status"] = "RE_SCREENING"
    touch(enh)
    return success(serialize(enh), 200)


@bp.post("/refractive/enhancements/<eid>/return-for-revision")
@require_auth(["Surgeon"])
def return_for_revision(eid):
    enh = get_or_404(db.enhancements, eid)
    if enh["status"] != "RE_SCREENING":
        raise err("ERR_INVALID_STATE", "enhancement must be RE_SCREENING")
    enh["re_screening_id"] = None
    enh["status"] = "REQUESTED"
    touch(enh)
    return success(serialize(enh), 200)


@bp.post("/refractive/enhancements/<eid>/adjudicate")
@require_auth(["Surgeon"])
def adjudicate_enhancement(eid):
    enh = get_or_404(db.enhancements, eid)
    body = get_json_body()
    decision = as_enum(body, "decision", {"APPROVE", "DENY"})

    if enh["status"] != "RE_SCREENING":
        raise err("ERR_INVALID_STATE", "enhancement must be RE_SCREENING to adjudicate")

    if decision == "APPROVE":
        screening = db.screenings.get(enh["re_screening_id"])
        if screening is None or screening["status"] != "APPROVED":
            raise err("ERR_INVALID_STATE", "attached re-screening must be APPROVED")
        enh["status"] = "APPROVED"
    else:
        enh["status"] = "DENIED"
    touch(enh)
    return success(serialize(enh), 200)


@bp.post("/refractive/enhancements/<eid>/fulfill")
@require_auth(["Surgeon"])
def fulfill_enhancement(eid):
    enh = get_or_404(db.enhancements, eid)
    if enh["status"] != "APPROVED":
        raise err("ERR_INVALID_STATE", "enhancement must be APPROVED to fulfill")
    enh["status"] = "FULFILLED"
    touch(enh)
    return success(serialize(enh), 200)
