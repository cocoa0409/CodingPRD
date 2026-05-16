"""Related services + sessions."""

from flask import Blueprint, request

from core.auth import require_role
from core.envelope import success_object, success_array
from core.errors import APIError
from core.pagination import parse_pagination, paginate
from core.store import (
    SERVICES, SESSIONS, CONSENTS, EVALUATIONS, STUDENTS, IEPS,
    stamp_create, stamp_update,
)
from core.validation import (
    get_district, get_student, get_iep, get_service, get_session,
    require_json_body, check_version,
)
from core.clock import parse_dt, format_dt

from services.cascades import (
    cascade_iep_revoke,
)
from services.computations import (
    compute_compensatory_minutes,
    recompute_iep_lre,
    recompute_student_lre_classification,
    recompute_service_utilization,
)
from services.serializers import service_dto, session_dto


bp = Blueprint("related_services", __name__)


ALLOWED_SERVICE_TYPES = {"OT", "PT", "SPEECH", "COUNSELING", "ORIENTATION_MOBILITY"}
ALLOWED_LOCATIONS = {"PULL_OUT", "PUSH_IN", "COMMUNITY"}


# ---------- Services ----------

@bp.route("/districts/<district_id>/students/<student_id>/ieps/<iep_id>/related-services", methods=["POST"])
def propose_service(district_id, student_id, iep_id):
    require_role(["SpecialEducationTeacher"])
    get_district(district_id)
    get_student(district_id, student_id)
    iep = get_iep(district_id, student_id, iep_id)
    body = require_json_body()

    service_type = body.get("service_type")
    minutes_per_week = body.get("minutes_per_week")
    provider_user_id = body.get("provider_user_id")
    location_setting = body.get("location_setting")

    if service_type not in ALLOWED_SERVICE_TYPES:
        raise APIError("ERR_INVALID_REQUEST", "service_type is invalid.")
    if not isinstance(minutes_per_week, int) or isinstance(minutes_per_week, bool) or minutes_per_week <= 0:
        raise APIError("ERR_INVALID_REQUEST", "minutes_per_week must be a positive integer.")
    if not isinstance(provider_user_id, str) or not provider_user_id:
        raise APIError("ERR_INVALID_REQUEST", "provider_user_id is required.")
    if location_setting not in ALLOWED_LOCATIONS:
        raise APIError("ERR_INVALID_REQUEST", "location_setting is invalid.")

    service = {
        "iep_id": iep_id,
        "student_id": student_id,
        "district_id": district_id,
        "service_type": service_type,
        "minutes_per_week": minutes_per_week,
        "provider_user_id": provider_user_id,
        "location_setting": location_setting,
        "consent_id": None,
        "total_prescribed_minutes_to_date": 0,
        "total_delivered_minutes": 0,
        "total_cancelled_minutes": 0,
        "compensatory_minutes_owed": 0,
        "utilization_percent": 0.00,
        "status": "PROPOSED",
        "first_active_at": None,
        "suspended_at": None,
    }
    stamp_create(service)
    SERVICES[service["id"]] = service
    return success_object(service_dto(service), http_status=201)


@bp.route("/districts/<district_id>/students/<student_id>/ieps/<iep_id>/related-services", methods=["GET"])
def list_services(district_id, student_id, iep_id):
    user_id, role = require_role(["DistrictAdmin", "SpecialEducationTeacher", "RelatedServiceProvider", "Parent"])
    student = get_student(district_id, student_id)
    if role == "Parent" and user_id != student.get("parent_user_id"):
        raise APIError("ERR_PARENT_OWNERSHIP_MISMATCH", "Parent may only act on their own student.")
    get_iep(district_id, student_id, iep_id)
    limit, offset = parse_pagination()
    status_q = request.args.get("status")
    type_q = request.args.get("service_type")
    rows = [s for s in SERVICES.values() if s.get("iep_id") == iep_id]
    if status_q:
        rows = [s for s in rows if s.get("status") == status_q]
    if type_q:
        rows = [s for s in rows if s.get("service_type") == type_q]
    rows.sort(key=lambda r: r.get("created_at", ""))
    page, total = paginate([service_dto(s) for s in rows], limit, offset)
    return success_array(page, limit=limit, offset=offset, total_count=total)


def _service_route_perm_check(district_id, student_id, iep_id, service_id):
    """Common auth + path resolution + return (district, student, iep, service, body)."""
    require_role(["RelatedServiceProvider"])
    district = get_district(district_id)
    student = get_student(district_id, student_id)
    iep = get_iep(district_id, student_id, iep_id)
    service = get_service(district_id, student_id, iep_id, service_id)
    body = require_json_body()
    return district, student, iep, service, body


@bp.route("/districts/<district_id>/students/<student_id>/ieps/<iep_id>/related-services/<service_id>/activate",
          methods=["PUT"])
def activate_service(district_id, student_id, iep_id, service_id):
    district, student, iep, service, body = _service_route_perm_check(district_id, student_id, iep_id, service_id)
    check_version(body.get("version"), service.get("version", 1))

    if service.get("status") != "PROPOSED":
        raise APIError("ERR_SERVICE_NOT_PROPOSED", "Service is not in PROPOSED.")
    if iep.get("status") not in ("ACTIVE", "AMENDMENT_PENDING"):
        raise APIError("ERR_IEP_NOT_ACTIVE", "Parent IEP must be ACTIVE or AMENDMENT_PENDING.")

    consent_id = body.get("consent_id")
    if not isinstance(consent_id, str) or not consent_id:
        raise APIError("ERR_INVALID_REQUEST", "consent_id is required.")
    consent = CONSENTS.get(consent_id)
    if consent is None:
        raise APIError("ERR_CONSENT_NOT_FOUND", "Consent not found.")
    if consent.get("student_id") != student_id or consent.get("district_id") != district_id:
        raise APIError("ERR_CROSS_STUDENT_REFERENCE", "Consent belongs to a different student/district.")
    if consent.get("scope") != "RELATED_SERVICE" or consent.get("status") != "APPROVED":
        raise APIError("ERR_SERVICE_CONSENT_NOT_APPROVED", "Consent is not APPROVED RELATED_SERVICE.")

    # Student eligibility
    ev_id = student.get("current_eligibility_evaluation_id")
    eligible = False
    if ev_id:
        ev = EVALUATIONS.get(ev_id)
        eligible = bool(ev and ev.get("status") == "ELIGIBLE")
    if not eligible:
        raise APIError("ERR_STUDENT_NOT_ELIGIBLE", "Student is not eligible.")

    # At most one ACTIVE service per (iep_id, service_type)
    for other in SERVICES.values():
        if other["id"] == service_id:
            continue
        if other.get("iep_id") == iep_id and other.get("service_type") == service.get("service_type") \
                and other.get("status") == "ACTIVE":
            raise APIError("ERR_SERVICE_TYPE_ALREADY_ACTIVE",
                           "Another ACTIVE service exists for this (iep, service_type).")

    # Instructional-time cap check (priority 19, 422).
    # Compute projected sped_minutes if we add this service's minutes.
    projected = 0
    for s in SERVICES.values():
        if s.get("iep_id") != iep_id:
            continue
        if s.get("status") == "ACTIVE":
            projected += s.get("minutes_per_week", 0)
    projected += service.get("minutes_per_week", 0)
    if projected > iep.get("total_instructional_minutes_per_week", 0):
        raise APIError(
            "ERR_SERVICE_MINUTES_EXCEED_INSTRUCTIONAL_TIME",
            "Activating would exceed total_instructional_minutes_per_week.",
        )

    # Activate.
    service["status"] = "ACTIVE"
    service["consent_id"] = consent_id
    if service.get("first_active_at") is None:
        service["first_active_at"] = district["current_date"]
    service["suspended_at"] = None
    stamp_update(service)

    recompute_iep_lre(iep)
    stamp_update(iep)
    if student.get("current_iep_id") == iep_id:
        recompute_student_lre_classification(student)
        stamp_update(student)
    return success_object(service_dto(service))


@bp.route("/districts/<district_id>/students/<student_id>/ieps/<iep_id>/related-services/<service_id>/suspend",
          methods=["PUT"])
def suspend_service(district_id, student_id, iep_id, service_id):
    district, student, iep, service, body = _service_route_perm_check(district_id, student_id, iep_id, service_id)
    check_version(body.get("version"), service.get("version", 1))
    if service.get("status") != "ACTIVE":
        raise APIError("ERR_SERVICE_NOT_ACTIVE", "Service is not in ACTIVE.")
    service["status"] = "SUSPENDED"
    service["compensatory_minutes_owed"] = compute_compensatory_minutes(service, district["current_date"])
    service["suspended_at"] = district["current_date"]
    recompute_service_utilization(service, district["current_date"])
    stamp_update(service)

    recompute_iep_lre(iep)
    stamp_update(iep)
    if student.get("current_iep_id") == iep_id:
        recompute_student_lre_classification(student)
        stamp_update(student)
    return success_object(service_dto(service))


@bp.route("/districts/<district_id>/students/<student_id>/ieps/<iep_id>/related-services/<service_id>/resume",
          methods=["PUT"])
def resume_service(district_id, student_id, iep_id, service_id):
    district, student, iep, service, body = _service_route_perm_check(district_id, student_id, iep_id, service_id)
    check_version(body.get("version"), service.get("version", 1))
    if service.get("status") != "SUSPENDED":
        raise APIError("ERR_SERVICE_NOT_SUSPENDED", "Service is not in SUSPENDED.")
    consent_id = body.get("consent_id")
    if not isinstance(consent_id, str) or not consent_id:
        raise APIError("ERR_INVALID_REQUEST", "consent_id is required.")
    consent = CONSENTS.get(consent_id)
    if consent is None:
        raise APIError("ERR_CONSENT_NOT_FOUND", "Consent not found.")
    if consent.get("student_id") != student_id or consent.get("district_id") != district_id:
        raise APIError("ERR_CROSS_STUDENT_REFERENCE", "Consent belongs to a different student/district.")
    if consent.get("status") != "APPROVED" or consent.get("scope") != "RELATED_SERVICE":
        raise APIError("ERR_SERVICE_CONSENT_NOT_APPROVED", "Consent is not APPROVED RELATED_SERVICE.")
    if iep.get("status") != "ACTIVE":
        raise APIError("ERR_IEP_NOT_ACTIVE", "Parent IEP must be ACTIVE.")

    # Same-type uniqueness check (priority 13).
    for other in SERVICES.values():
        if other["id"] == service_id:
            continue
        if other.get("iep_id") == iep_id and other.get("service_type") == service.get("service_type") \
                and other.get("status") == "ACTIVE":
            raise APIError("ERR_SERVICE_TYPE_ALREADY_ACTIVE",
                           "Another ACTIVE service exists for this (iep, service_type).")

    # Instructional time cap.
    projected = 0
    for s in SERVICES.values():
        if s.get("iep_id") != iep_id:
            continue
        if s.get("status") == "ACTIVE":
            projected += s.get("minutes_per_week", 0)
    projected += service.get("minutes_per_week", 0)
    if projected > iep.get("total_instructional_minutes_per_week", 0):
        raise APIError(
            "ERR_SERVICE_MINUTES_EXCEED_INSTRUCTIONAL_TIME",
            "Resuming would exceed total_instructional_minutes_per_week.",
        )

    service["status"] = "ACTIVE"
    service["consent_id"] = consent_id
    service["suspended_at"] = None
    stamp_update(service)
    recompute_iep_lre(iep)
    stamp_update(iep)
    if student.get("current_iep_id") == iep_id:
        recompute_student_lre_classification(student)
        stamp_update(student)
    return success_object(service_dto(service))


# ---------- Sessions ----------

@bp.route("/districts/<district_id>/students/<student_id>/ieps/<iep_id>/related-services/<service_id>/sessions",
          methods=["POST"])
def schedule_session(district_id, student_id, iep_id, service_id):
    require_role(["RelatedServiceProvider"])
    get_district(district_id)
    get_student(district_id, student_id)
    get_iep(district_id, student_id, iep_id)
    service = get_service(district_id, student_id, iep_id, service_id)
    body = require_json_body()

    scheduled_start = body.get("scheduled_start")
    scheduled_end = body.get("scheduled_end")
    if not isinstance(scheduled_start, str) or not scheduled_start:
        raise APIError("ERR_INVALID_REQUEST", "scheduled_start is required.")
    if not isinstance(scheduled_end, str) or not scheduled_end:
        raise APIError("ERR_INVALID_REQUEST", "scheduled_end is required.")
    try:
        start_dt = parse_dt(scheduled_start)
        end_dt = parse_dt(scheduled_end)
    except Exception:
        raise APIError("ERR_INVALID_REQUEST", "scheduled_start/end must be ISO 8601 datetimes.")
    if end_dt <= start_dt:
        raise APIError("ERR_INVALID_REQUEST", "scheduled_end must be strictly after scheduled_start.")

    # Closed-interval overlap (adjacency counts) — priority 14.
    for other in SESSIONS.values():
        if other.get("related_service_id") != service_id:
            continue
        if other.get("status") == "CANCELLED":
            # PRD §1.4 priority 14 mentions "SCHEDULED/DELIVERED session"; cancelled does not block.
            continue
        try:
            o_start = parse_dt(other["scheduled_start"])
            o_end = parse_dt(other["scheduled_end"])
        except Exception:
            continue
        # Closed-interval overlap: a <= o_end AND o_start <= b
        if start_dt <= o_end and o_start <= end_dt:
            raise APIError("ERR_SERVICE_SESSION_OVERLAP",
                           "Session overlaps an existing session on this related service.")

    scheduled_minutes = int((end_dt - start_dt).total_seconds() // 60)

    session = {
        "related_service_id": service_id,
        "iep_id": iep_id,
        "student_id": student_id,
        "scheduled_start": format_dt(start_dt),
        "scheduled_end": format_dt(end_dt),
        "scheduled_minutes": scheduled_minutes,
        "actual_minutes": None,
        "status": "SCHEDULED",
    }
    stamp_create(session)
    SESSIONS[session["id"]] = session
    return success_object(session_dto(session), http_status=201)


@bp.route(
    "/districts/<district_id>/students/<student_id>/ieps/<iep_id>/related-services/<service_id>/sessions/<session_id>/deliver",
    methods=["POST"]
)
def deliver_session(district_id, student_id, iep_id, service_id, session_id):
    require_role(["RelatedServiceProvider"])
    district = get_district(district_id)
    get_student(district_id, student_id)
    get_iep(district_id, student_id, iep_id)
    service = get_service(district_id, student_id, iep_id, service_id)
    session = get_session(district_id, student_id, iep_id, service_id, session_id)
    body = require_json_body()
    check_version(body.get("version"), session.get("version", 1))

    if session.get("status") != "SCHEDULED":
        raise APIError("ERR_SESSION_NOT_SCHEDULED", "Session is not in SCHEDULED.")
    if service.get("status") != "ACTIVE":
        raise APIError("ERR_SERVICE_NOT_ACTIVE", "Parent service is not in ACTIVE.")

    actual_minutes = body.get("actual_minutes")
    sched_min = session.get("scheduled_minutes", 0)
    if (not isinstance(actual_minutes, int)) or isinstance(actual_minutes, bool):
        raise APIError("ERR_INVALID_REQUEST", "actual_minutes must be an integer.")
    if actual_minutes < 0 or actual_minutes > sched_min:
        raise APIError("ERR_INVALID_REQUEST",
                       "actual_minutes must satisfy 0 <= actual_minutes <= scheduled_minutes.")

    # Due-yet check: current_date >= scheduled_start (date-only? per PRD §3.6 it says
    # "the district's current_date be at or after scheduled_start" — datetime compare).
    if parse_dt(session["scheduled_start"]) > parse_dt(district["current_date"]):
        raise APIError("ERR_SESSION_NOT_DUE_YET", "Session is not yet due.")

    session["status"] = "DELIVERED"
    session["actual_minutes"] = actual_minutes
    stamp_update(session)

    service["total_delivered_minutes"] = service.get("total_delivered_minutes", 0) + actual_minutes
    from services.computations import recompute_service_utilization
    recompute_service_utilization(service, district["current_date"])
    stamp_update(service)
    return success_object(session_dto(session))


@bp.route(
    "/districts/<district_id>/students/<student_id>/ieps/<iep_id>/related-services/<service_id>/sessions/<session_id>/cancel",
    methods=["POST"]
)
def cancel_session(district_id, student_id, iep_id, service_id, session_id):
    require_role(["RelatedServiceProvider"])
    get_district(district_id)
    get_student(district_id, student_id)
    get_iep(district_id, student_id, iep_id)
    service = get_service(district_id, student_id, iep_id, service_id)
    session = get_session(district_id, student_id, iep_id, service_id, session_id)
    body = require_json_body()
    check_version(body.get("version"), session.get("version", 1))
    if session.get("status") != "SCHEDULED":
        raise APIError("ERR_SESSION_NOT_SCHEDULED", "Session is not in SCHEDULED.")
    session["status"] = "CANCELLED"
    stamp_update(session)

    service["total_cancelled_minutes"] = service.get("total_cancelled_minutes", 0) + session.get(
        "scheduled_minutes", 0
    )
    stamp_update(service)
    return success_object(session_dto(session))
