"""Hearing evaluation endpoints."""

from flask import Blueprint

from db import db
import serialize
import validate
import errors
from clock import clock
from timeutil import parse_date, clock_date
from middleware import require_auth, require_role, get_json_body
from response import object_response
from services.domain import get_or_404
from services.calculations import classify_severity

bp = Blueprint("evaluations", __name__)


@bp.post("/clinic/evaluations")
def create_evaluation():
    auth = require_auth()
    require_role(auth, {"Audiologist"})
    body = get_json_body()
    patient_id = validate.require_str(body, "patient_id")
    audiologist_user_id = validate.require_str(body, "audiologist_user_id")
    ptag = validate.require_int(body, "pure_tone_avg_db", minimum=0, maximum=120)

    get_or_404(db.patients, patient_id)

    obj = {
        "patient_id": patient_id,
        "audiologist_user_id": audiologist_user_id,
        "pure_tone_avg_db": ptag,
        "severity": None,
        "is_pediatric": None,
        "candidate": None,
        "status": "DRAFT",
    }
    db.stamp_create(obj)
    with db.lock:
        db.evaluations[obj["id"]] = obj
    return object_response(serialize.evaluation(obj), 201)


@bp.post("/clinic/evaluations/<eid>/finalize")
def finalize_evaluation(eid):
    auth = require_auth()
    require_role(auth, {"Audiologist"})
    with db.lock:
        ev = get_or_404(db.evaluations, eid)
        # State precondition: only DRAFT may be finalized.
        if ev["status"] != "DRAFT":
            raise errors.invalid_state("Evaluation is not in DRAFT.")
        if ev.get("pure_tone_avg_db") is None:
            raise errors.invalid_state("pure_tone_avg_db is not set.")

        severity = classify_severity(ev["pure_tone_avg_db"])
        ev["severity"] = severity
        ev["candidate"] = (severity != "NORMAL")
        ev["is_pediatric"] = _is_pediatric(ev["patient_id"])
        ev["status"] = "FINALIZED"
        db.touch(ev)

        # Supersede any other currently-FINALIZED evaluation for this patient
        # (cascade): a patient may hold at most one FINALIZED evaluation.
        for other in db.evaluations.values():
            if (other["id"] != ev["id"]
                    and other["patient_id"] == ev["patient_id"]
                    and other["status"] == "FINALIZED"):
                other["status"] = "SUPERSEDED"
                db.touch(other)
    return object_response(serialize.evaluation(ev))


@bp.get("/clinic/evaluations/<eid>")
def get_evaluation(eid):
    auth = require_auth()
    require_role(auth, {"Audiologist", "BillingClerk", "ClinicAdmin"})
    ev = get_or_404(db.evaluations, eid)
    return object_response(serialize.evaluation(ev))


def _is_pediatric(patient_id):
    """True when patient age on the clock date is under 18 (PRD §3.2)."""
    patient = db.patients.get(patient_id)
    if patient is None:
        return False
    dob = parse_date(patient.get("date_of_birth"))
    if dob is None:
        return False
    today = clock_date(clock.now())
    age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
    return age < 18
