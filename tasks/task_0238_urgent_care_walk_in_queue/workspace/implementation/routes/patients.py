"""Patient registration endpoints (PRD §3.4)."""
from flask import Blueprint, request

import clock
import serialize
from db import db, stamp_create, touch
from errors import err
from middleware import authorize
from response import ok_object, ok_array
from util import parse_date
from validation import get_json_body, parse_pagination, paginate, require_str
from routes.lookup import get_path, get_fk

bp = Blueprint("patients", __name__)

READ_ROLES = ["ClinicManager", "FrontDeskClerk", "TriageNurse", "Provider"]
MAJORITY_AGE = 18


def _compute_is_minor(dob):
    today = clock.now().date()
    years = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
    return years < MAJORITY_AGE


@bp.route("/patients", methods=["POST"])
def create_patient():
    authorize(["FrontDeskClerk"])
    body = get_json_body()

    # Body FK resolution comes before body well-formedness (PRD §2.6).
    qe_id = body.get("queue_entry_id")
    if qe_id is None:
        raise err("ERR_INVALID_REQUEST", "queue_entry_id required")
    qe = get_fk("queue_entry", qe_id)

    require_str(body, "legal_name")
    dob_raw = body.get("date_of_birth")
    dob = parse_date(dob_raw)
    if dob is None:
        raise err("ERR_INVALID_REQUEST", "date_of_birth must be YYYY-MM-DD")
    consent = body.get("consent_signed", False)
    if not isinstance(consent, bool):
        raise err("ERR_INVALID_REQUEST", "consent_signed must be boolean")
    guarantor = body.get("guarantor_name", None)

    # State legality: registration only from TRIAGED.
    if qe["status"] != "TRIAGED":
        raise err("ERR_INVALID_STATE", "queue entry not TRIAGED")

    is_minor = _compute_is_minor(dob)
    if is_minor and not guarantor:
        raise err("ERR_GUARANTOR_REQUIRED", "guarantor_name required for a minor")

    patient = stamp_create({
        "queue_entry_id": qe["id"],
        "legal_name": body["legal_name"],
        "date_of_birth": dob_raw,
        "is_minor": is_minor,
        "guarantor_name": guarantor,
        "consent_signed": consent,
    })
    db.patients[patient["id"]] = patient

    # Link patient to queue entry; advance TRIAGED -> IN_REGISTRATION.
    # (Active depth is unchanged — both states are active — so no clinic
    # posture recompute is triggered here per PRD §2.9.)
    qe["patient_id"] = patient["id"]
    qe["status"] = "IN_REGISTRATION"
    touch(qe)

    return ok_object(serialize.patient(patient), 201)


@bp.route("/patients/<pid>", methods=["GET"])
def get_patient(pid):
    authorize(READ_ROLES)
    patient = get_path("patient", pid)
    return ok_object(serialize.patient(patient))


@bp.route("/patients", methods=["GET"])
def list_patients():
    authorize(READ_ROLES)
    limit, offset = parse_pagination()
    items = list(db.patients.values())
    qe_id = request.args.get("queue_entry_id")
    if qe_id is not None:
        items = [p for p in items if p["queue_entry_id"] == qe_id]
    items.sort(key=lambda p: (p["created_at"], p["id"]))
    page = paginate(items, limit, offset)
    return ok_array([serialize.patient(p) for p in page], limit, offset, len(items))
