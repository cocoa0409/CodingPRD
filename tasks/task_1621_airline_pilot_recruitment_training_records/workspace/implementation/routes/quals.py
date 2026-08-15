"""Qualifications & currency, flight activity, and medical certificates."""

from datetime import timedelta

from flask import Blueprint, request

from db import store
from errors import ApiError
from middleware import require_roles
from services import (
    evaluate_currency, get_applicant, get_equipment, get_flight_activity,
    get_medical, get_qualification, grounding_cascade, medical_status_at,
    medical_windows, recompute_landings, ser_flight_activity, ser_medical,
    ser_qualification, stamp_new, bump, touch,
)
from util import (
    get_body, is_int, is_number, pagination_params, req_int, req_str, req_ts,
    sort_rows, success_list, success_object,
)

bp = Blueprint("quals", __name__)

QUAL_READ_ROLES = ("Recruiter", "CrewScheduler", "TrainingCoordinator", "SystemAdmin")
ACTIVITY_TYPES = ("REVENUE", "TRAINING", "CHECK")
CERT_CLASSES = ("FIRST", "SECOND", "THIRD")


# ---- Qualifications --------------------------------------------------------------

@bp.post("/qualifications")
def create_qualification():
    require_roles("CrewScheduler", "SystemAdmin")
    body = get_body()
    applicant_id = req_str(body, "applicant_id")
    equipment_id = req_str(body, "equipment_id")
    applicant = get_applicant(applicant_id)   # existence, §2.8 order
    get_equipment(equipment_id)
    if applicant["status"] != "CLEARED":
        raise ApiError("ERR_APPLICANT_INVALID_STATE",
                       "qualification grant requires a CLEARED applicant, found %s" % applicant["status"])
    if any(q["applicant_id"] == applicant_id and q["equipment_id"] == equipment_id
           for q in store.qualifications.values()):
        raise ApiError("ERR_DUPLICATE_QUALIFICATION",
                       "A qualification already exists for this applicant-equipment pair")
    qual = stamp_new({
        "applicant_id": applicant_id,
        "equipment_id": equipment_id,
        "currency_state": "QUALIFIED",
        "operating_state": "ACTIVE",
        "qualified_at": store.now(),
        "landings_90d": 0,
        "landings_expiring_7d": 0,
        "lapsed_since": None,
        "last_evaluated_at": None,
        "_requalifying_since": None,
    })
    store.qualifications[qual["id"]] = qual
    return success_object(ser_qualification(qual), 201)


@bp.get("/qualifications")
def list_qualifications():
    require_roles(*QUAL_READ_ROLES)
    limit, offset = pagination_params()
    rows = list(store.qualifications.values())
    applicant_id = request.args.get("applicant_id")
    equipment_id = request.args.get("equipment_id")
    currency_state = request.args.get("currency_state")
    if applicant_id is not None:
        rows = [q for q in rows if q["applicant_id"] == applicant_id]
    if equipment_id is not None:
        rows = [q for q in rows if q["equipment_id"] == equipment_id]
    if currency_state is not None:
        rows = [q for q in rows if q["currency_state"] == currency_state]
    rows = sort_rows(rows)
    total = len(rows)
    return success_list([ser_qualification(q) for q in rows[offset:offset + limit]], limit, offset, total)


@bp.get("/qualifications/<qid>")
def read_qualification(qid):
    require_roles(*QUAL_READ_ROLES)
    qual = get_qualification(qid)
    recompute_landings(qual)  # single reads recompute the counters (no timestamps touched)
    return success_object(ser_qualification(qual))


@bp.post("/qualifications/<qid>/refresh-currency")
def refresh_currency(qid):
    require_roles("CrewScheduler", "SystemAdmin")
    qual = get_qualification(qid)
    transitioned = evaluate_currency(qual)
    if transitioned:
        qual["version"] += 1  # version increments on transition only
    return success_object(ser_qualification(qual))


@bp.post("/qualifications/<qid>/requalify")
def requalify(qid):
    require_roles("CrewScheduler", "SystemAdmin")
    qual = get_qualification(qid)
    if qual["currency_state"] != "LAPSED":
        raise ApiError("ERR_QUALIFICATION_INVALID_STATE",
                       "requalify requires currency_state LAPSED, found %s" % qual["currency_state"])
    # Prerequisite: a passing SIMULATOR MILESTONE for this applicant completed
    # within the 30 days preceding now.
    now = store.now()
    window_low = now - timedelta(days=30)
    enrollment_ids = {e["id"] for e in store.enrollments.values()
                      if e["applicant_id"] == qual["applicant_id"]}
    evidence = any(
        ev["enrollment_id"] in enrollment_ids
        and ev["phase"] == "SIMULATOR"
        and ev["event_type"] == "MILESTONE"
        and ev["status"] == "COMPLETED"
        and ev["score"] is not None and ev["score"] >= 80
        and window_low < ev["updated_at"] <= now
        for ev in store.training_events.values())
    if not evidence:
        raise ApiError("ERR_QUALIFICATION_INVALID_STATE",
                       "requalify requires a recent passing SIMULATOR milestone")
    qual["currency_state"] = "REQUALIFYING"
    qual["_requalifying_since"] = now
    bump(qual)
    return success_object(ser_qualification(qual))


@bp.post("/qualifications/<qid>/certify-requalification")
def certify_requalification(qid):
    require_roles("CheckAirman", "SystemAdmin")
    qual = get_qualification(qid)
    if qual["currency_state"] != "REQUALIFYING":
        raise ApiError("ERR_QUALIFICATION_INVALID_STATE",
                       "certify-requalification requires currency_state REQUALIFYING, found %s"
                       % qual["currency_state"])
    # Prerequisite: a PRACTICAL checkride COMPLETED_PASS for this applicant on
    # this equipment after the LAPSED -> REQUALIFYING transition.
    since = qual.get("_requalifying_since")
    enrollment_ids = {
        e["id"] for e in store.enrollments.values()
        if e["applicant_id"] == qual["applicant_id"]
        and (store.training_classes.get(e["training_class_id"]) or {}).get("equipment_id")
        == qual["equipment_id"]
    }
    evidence = any(
        c["enrollment_id"] in enrollment_ids
        and c["ride_type"] == "PRACTICAL"
        and c["status"] == "COMPLETED_PASS"
        and c["completed_at"] is not None
        and (since is None or c["completed_at"] >= since)
        for c in store.checkrides.values())
    if not evidence:
        raise ApiError("ERR_QUALIFICATION_INVALID_STATE",
                       "certify-requalification requires a passed PRACTICAL checkride after requalification")
    qual["currency_state"] = "QUALIFIED"
    qual["lapsed_since"] = None
    qual["last_evaluated_at"] = store.now()
    recompute_landings(qual)
    bump(qual)
    return success_object(ser_qualification(qual))


# ---- Flight activities ------------------------------------------------------------

@bp.post("/flight-activities")
def create_flight_activity():
    require_roles("CrewScheduler", "SystemAdmin")
    body = get_body()
    qualification_id = req_str(body, "qualification_id")
    activity_date = req_ts(body, "activity_date")
    get_qualification(qualification_id)
    # (13) logical-clock window: activity_date may not be in the future.
    if activity_date > store.now():
        raise ApiError("ERR_FUTURE_ACTIVITY_DATE", "activity_date is in the future")
    # (16) constraint band.
    landings = body.get("landings")
    hours = body.get("hours")
    activity_type = body.get("activity_type")
    if not is_int(landings) or landings < 0:
        raise ApiError("ERR_INVALID_REQUEST", "landings must be an integer >= 0")
    if not is_number(hours) or hours < 0:
        raise ApiError("ERR_INVALID_REQUEST", "hours must be a number >= 0")
    if activity_type not in ACTIVITY_TYPES:
        raise ApiError("ERR_INVALID_REQUEST", "activity_type must be one of %s" % ", ".join(ACTIVITY_TYPES))
    activity = stamp_new({
        "qualification_id": qualification_id,
        "activity_date": activity_date,
        "landings": landings,
        "hours": hours,
        "activity_type": activity_type,
    })
    store.flight_activities[activity["id"]] = activity
    return success_object(ser_flight_activity(activity), 201)


@bp.get("/flight-activities")
def list_flight_activities():
    require_roles("CrewScheduler", "TrainingCoordinator", "SystemAdmin")
    limit, offset = pagination_params()
    rows = list(store.flight_activities.values())
    qualification_id = request.args.get("qualification_id")
    if qualification_id is not None:
        rows = [f for f in rows if f["qualification_id"] == qualification_id]
    rows = sort_rows(rows)
    total = len(rows)
    return success_list([ser_flight_activity(f) for f in rows[offset:offset + limit]], limit, offset, total)


@bp.get("/flight-activities/<fid>")
def read_flight_activity(fid):
    require_roles("CrewScheduler", "TrainingCoordinator", "SystemAdmin")
    return success_object(ser_flight_activity(get_flight_activity(fid)))


# ---- Medical certificates ------------------------------------------------------------

@bp.post("/medical-certificates")
def create_medical():
    require_roles("CrewScheduler", "SystemAdmin")
    body = get_body()
    applicant_id = req_str(body, "applicant_id")
    cert_class = body.get("cert_class")
    issued_at = req_ts(body, "issued_at")
    pilot_age_at_issue = body.get("pilot_age_at_issue")
    get_applicant(applicant_id)
    # Constraint band (16).
    if cert_class not in CERT_CLASSES:
        raise ApiError("ERR_INVALID_REQUEST", "cert_class must be one of %s" % ", ".join(CERT_CLASSES))
    if not is_int(pilot_age_at_issue) or pilot_age_at_issue < 17:
        raise ApiError("ERR_INVALID_REQUEST", "pilot_age_at_issue must be an integer >= 17")
    first_through, third_through = medical_windows(issued_at, pilot_age_at_issue)
    cert = stamp_new({
        "applicant_id": applicant_id,
        "cert_class": cert_class,
        "issued_at": issued_at,
        "pilot_age_at_issue": pilot_age_at_issue,
        "first_class_valid_through": first_through,
        "third_class_valid_through": third_through,
        "status": "VALID",
    })
    # Validity is evaluated immediately at issue.
    cert["status"] = medical_status_at(cert, store.now())
    store.medical_certificates[cert["id"]] = cert
    return success_object(ser_medical(cert), 201)


@bp.get("/medical-certificates")
def list_medicals():
    require_roles("Recruiter", "CrewScheduler", "SystemAdmin")
    limit, offset = pagination_params()
    rows = list(store.medical_certificates.values())
    applicant_id = request.args.get("applicant_id")
    status = request.args.get("status")
    if applicant_id is not None:
        rows = [m for m in rows if m["applicant_id"] == applicant_id]
    if status is not None:
        rows = [m for m in rows if m["status"] == status]
    rows = sort_rows(rows)
    total = len(rows)
    return success_list([ser_medical(m) for m in rows[offset:offset + limit]], limit, offset, total)


@bp.get("/medical-certificates/<mid>")
def read_medical(mid):
    require_roles("Recruiter", "CrewScheduler", "SystemAdmin")
    return success_object(ser_medical(get_medical(mid)))


@bp.post("/medical-certificates/<mid>/suspend")
def suspend_medical(mid):
    require_roles("CrewScheduler", "SystemAdmin")
    cert = get_medical(mid)
    if cert["status"] != "VALID":
        # No dedicated medical-state error exists in the catalogue; the
        # constraint band's catch-all applies.
        raise ApiError("ERR_INVALID_REQUEST",
                       "suspend requires status VALID, found %s" % cert["status"])
    cert["status"] = "SUSPENDED"  # terminal; a suspended certificate never resumes
    bump(cert)
    grounding_cascade(cert["applicant_id"])
    return success_object(ser_medical(cert))
