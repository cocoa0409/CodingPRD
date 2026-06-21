"""QueueEntry endpoints and lifecycle (PRD §3.1–§3.4)."""
from flask import Blueprint, request

import clock
import serialize
from db import db, stamp_create, touch
from errors import err
from middleware import authorize
from response import ok_object, ok_array
from util import add_minutes
from validation import get_json_body, parse_pagination, paginate, require_str
from routes.lookup import get_path
from services import compute

bp = Blueprint("queue_entries", __name__)

READ_ROLES = ["ClinicManager", "FrontDeskClerk", "TriageNurse", "Provider", "Patient"]
RESERVATION_HOLD_MINUTES = 30
ARRIVAL_CHANNELS = {"ONLINE", "WALK_IN"}


def _check_qid_under_clinic(clinic, qid):
    qe = get_path("queue_entry", qid)
    if qe["clinic_id"] != clinic["id"]:
        raise err("ERR_NOT_FOUND", "queue entry not under clinic")
    return qe


@bp.route("/clinics/<cid>/queue-entries", methods=["POST"])
def create_queue_entry(cid):
    authorize(["FrontDeskClerk", "Patient"])
    clinic = get_path("clinic", cid)
    body = get_json_body()
    channel = body.get("arrival_channel")
    if channel not in ARRIVAL_CHANNELS:
        raise err("ERR_INVALID_REQUEST", "invalid arrival_channel")
    require_str(body, "chief_complaint")

    # Diversion check (business rule, evaluated after well-formedness).
    if compute.compute_posture(clinic) == "DIVERSION":
        raise err("ERR_CLINIC_ON_DIVERSION", "clinic is on diversion")

    now = clock.now()
    entry = {
        "clinic_id": clinic["id"],
        "patient_id": None,
        "arrival_channel": channel,
        "chief_complaint": body["chief_complaint"],
        "reserved_at": None,
        "hold_expires_at": None,
        "esi_level": None,
        "airborne_precaution": False,
        "priority_rank": None,
        "estimated_wait_minutes": None,
        "triaged_at": None,
    }
    if channel == "ONLINE":
        entry["status"] = "RESERVED"
        entry["reserved_at"] = now
        entry["hold_expires_at"] = add_minutes(now, RESERVATION_HOLD_MINUTES)
    else:
        entry["status"] = "WAITING"

    stamp_create(entry)
    db.queue_entries[entry["id"]] = entry

    if channel == "WALK_IN":
        # WALK_IN counts toward depth immediately -> recompute posture.
        compute.recompute_clinic(clinic)
    return ok_object(serialize.queue_entry(entry), 201)


@bp.route("/clinics/<cid>/queue-entries", methods=["GET"])
def list_clinic_queue_entries(cid):
    authorize(READ_ROLES)
    clinic = get_path("clinic", cid)
    limit, offset = parse_pagination()
    items = [q for q in db.queue_entries.values() if q["clinic_id"] == clinic["id"]]
    status_filter = request.args.get("status")
    if status_filter is not None:
        items = [q for q in items if q["status"] == status_filter]
    items.sort(key=lambda q: (q["created_at"], q["id"]))
    page = paginate(items, limit, offset)
    return ok_array([serialize.queue_entry(q) for q in page], limit, offset, len(items))


@bp.route("/queue-entries/<qid>", methods=["GET"])
def get_queue_entry(qid):
    authorize(READ_ROLES)
    qe = get_path("queue_entry", qid)
    return ok_object(serialize.queue_entry(qe))


@bp.route("/queue-entries", methods=["GET"])
def list_queue_entries():
    authorize(READ_ROLES)
    limit, offset = parse_pagination()
    items = list(db.queue_entries.values())
    patient_id = request.args.get("patient_id")
    status_filter = request.args.get("status")
    if patient_id is not None:
        items = [q for q in items if q["patient_id"] == patient_id]
    if status_filter is not None:
        items = [q for q in items if q["status"] == status_filter]
    items.sort(key=lambda q: (q["created_at"], q["id"]))
    page = paginate(items, limit, offset)
    return ok_array([serialize.queue_entry(q) for q in page], limit, offset, len(items))


@bp.route("/clinics/<cid>/queue-entries/<qid>/arrive", methods=["POST"])
def arrive(cid, qid):
    authorize(["FrontDeskClerk", "Patient"])
    clinic = get_path("clinic", cid)
    qe = _check_qid_under_clinic(clinic, qid)
    if qe["status"] != "RESERVED":
        raise err("ERR_INVALID_STATE", "entry not RESERVED")
    now = clock.now()
    if qe["hold_expires_at"] is not None and now > qe["hold_expires_at"]:
        raise err("ERR_INVALID_STATE", "hold has expired")
    qe["status"] = "WAITING"
    qe["hold_expires_at"] = None
    touch(qe)
    compute.recompute_clinic(clinic)
    return ok_object(serialize.queue_entry(qe))


@bp.route("/clinics/<cid>/queue-entries/<qid>/triage", methods=["POST"])
def triage(cid, qid):
    authorize(["TriageNurse"])
    clinic = get_path("clinic", cid)
    qe = _check_qid_under_clinic(clinic, qid)
    body = get_json_body()
    esi = body.get("esi_level")
    if not isinstance(esi, int) or isinstance(esi, bool) or esi < 1 or esi > 5:
        raise err("ERR_INVALID_REQUEST", "esi_level must be 1..5")
    airborne = body.get("airborne_precaution", False)
    if not isinstance(airborne, bool):
        raise err("ERR_INVALID_REQUEST", "airborne_precaution must be boolean")
    if qe["status"] != "WAITING":
        raise err("ERR_INVALID_STATE", "entry not WAITING")
    qe["esi_level"] = esi
    qe["airborne_precaution"] = airborne
    qe["triaged_at"] = clock.now()
    qe["status"] = "TRIAGED"
    touch(qe)
    compute.recompute_clinic(clinic)
    return ok_object(serialize.queue_entry(qe))


@bp.route("/clinics/<cid>/queue-entries/<qid>/re-triage", methods=["POST"])
def re_triage(cid, qid):
    authorize(["TriageNurse"])
    clinic = get_path("clinic", cid)
    qe = _check_qid_under_clinic(clinic, qid)
    body = get_json_body()
    esi = body.get("esi_level")
    if not isinstance(esi, int) or isinstance(esi, bool) or esi < 1 or esi > 5:
        raise err("ERR_INVALID_REQUEST", "esi_level must be 1..5")
    airborne = body.get("airborne_precaution", None)
    if airborne is not None and not isinstance(airborne, bool):
        raise err("ERR_INVALID_REQUEST", "airborne_precaution must be boolean")
    if qe["status"] != "IN_REGISTRATION":
        raise err("ERR_INVALID_STATE", "entry not IN_REGISTRATION")
    qe["esi_level"] = esi
    if airborne is not None:
        qe["airborne_precaution"] = airborne
    qe["triaged_at"] = clock.now()
    qe["status"] = "TRIAGED"
    touch(qe)
    compute.recompute_clinic(clinic)
    return ok_object(serialize.queue_entry(qe))


@bp.route("/clinics/<cid>/queue-entries/<qid>/mark-ready", methods=["POST"])
def mark_ready(cid, qid):
    authorize(["FrontDeskClerk"])
    clinic = get_path("clinic", cid)
    qe = _check_qid_under_clinic(clinic, qid)
    if qe["status"] != "IN_REGISTRATION":
        raise err("ERR_INVALID_STATE", "entry not IN_REGISTRATION")

    # Registration completeness (business rule): a consent-signed Patient and a
    # Coverage for that patient must exist.
    patient = _find_patient_for_qe(qe["id"])
    if patient is None or not patient["consent_signed"]:
        raise err("ERR_REGISTRATION_INCOMPLETE", "consent-signed patient required")
    if _find_coverage_for_patient(patient["id"]) is None:
        raise err("ERR_REGISTRATION_INCOMPLETE", "coverage required")

    qe["status"] = "READY_FOR_PROVIDER"
    touch(qe)
    compute.recompute_clinic(clinic)
    return ok_object(serialize.queue_entry(qe))


@bp.route("/clinics/<cid>/queue-entries/<qid>/lwbs", methods=["POST"])
def lwbs(cid, qid):
    authorize(["FrontDeskClerk"])
    clinic = get_path("clinic", cid)
    qe = _check_qid_under_clinic(clinic, qid)
    if qe["status"] not in ("WAITING", "TRIAGED", "IN_REGISTRATION", "READY_FOR_PROVIDER"):
        raise err("ERR_INVALID_STATE", "entry not in an active pre-rooming state")
    qe["status"] = "LEFT_WITHOUT_SEEN"
    touch(qe)
    compute.recompute_clinic(clinic)
    return ok_object(serialize.queue_entry(qe))


@bp.route("/clinics/<cid>/queue-entries/<qid>/cancel", methods=["POST"])
def cancel(cid, qid):
    authorize(["FrontDeskClerk", "Patient"])
    clinic = get_path("clinic", cid)
    qe = _check_qid_under_clinic(clinic, qid)
    if qe["status"] not in ("RESERVED", "WAITING"):
        raise err("ERR_INVALID_STATE", "entry not RESERVED or WAITING")
    qe["status"] = "CANCELLED"
    touch(qe)
    compute.recompute_clinic(clinic)
    return ok_object(serialize.queue_entry(qe))


# --- helpers shared with patients/coverages routes ---
def _find_patient_for_qe(qe_id):
    for p in db.patients.values():
        if p["queue_entry_id"] == qe_id:
            return p
    return None


def _find_coverage_for_patient(patient_id):
    for c in db.coverages.values():
        if c["patient_id"] == patient_id:
            return c
    return None
