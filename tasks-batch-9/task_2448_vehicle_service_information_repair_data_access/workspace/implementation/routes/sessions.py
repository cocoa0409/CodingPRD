"""Secure gateway sessions, tool occupation and module programming jobs."""

from flask import Blueprint

from auth import authenticate, require_seat_holder
from envelope import object_response
from errors import err
from serialize import project
from services import (
    abort_session_jobs,
    append_audit,
    decrement_pin_count,
    find,
    increment_pin_count,
    jobs_of_session,
    price_and_close_session,
    technician_of_session,
)
from store import store
from validate import body_object, check_allowed, get_dt, get_enum, get_ref, get_str, pagination, q_enum, q_str

from routes.common import JOB_STATUSES, JOB_TYPES, SESSION_STATUSES, VIN_RE, paged

bp = Blueprint("sessions", __name__)

SESSION_READERS = ("PlatformAdmin", "ComplianceOfficer", "ShopManager", "Technician")


def _seat_of(session):
    return store.seat_assignments.get(session["seat_assignment_id"])


def _entitlement_of(seat):
    return store.entitlements.get(seat["entitlement_id"]) if seat is not None else None


def _guard_seat_holder(role, user_id, session):
    seat = _seat_of(session)
    if seat is not None:
        require_seat_holder(role, user_id, seat["technician_id"])
    return seat


# -- gateway sessions -----------------------------------------------------


@bp.post("/gateway-sessions")
def request_session():
    user_id, role = authenticate(("Technician",))
    body = body_object()
    seat_id = body.get("seat_assignment_id")
    if not isinstance(seat_id, str) or not seat_id:
        raise err(
            "ERR_INVALID_REQUEST",
            "Field seat_assignment_id must be a non-empty string identifier.",
        )
    seat = find(store.seat_assignments, seat_id, "ERR_SEAT_ASSIGNMENT_NOT_FOUND")
    require_seat_holder(role, user_id, seat["technician_id"])

    check_allowed(
        body,
        ("seat_assignment_id", "diagnostic_tool_id", "vin", "window_start", "window_end"),
    )
    tool_id = get_ref(body, "diagnostic_tool_id")
    vin = get_str(body, "vin", min_len=1)
    if not VIN_RE.match(vin):
        raise err(
            "ERR_INVALID_REQUEST",
            "vin must be exactly 17 characters of uppercase A-Z (no I, O, Q) and digits.",
        )
    start_raw, start = get_dt(body, "window_start")
    end_raw, end = get_dt(body, "window_end")

    tool = store.diagnostic_tools.get(tool_id)
    if tool is None:
        raise err("ERR_REFERENCED_RESOURCE_NOT_FOUND", "diagnostic_tool_id does not resolve.")

    entitlement = _entitlement_of(seat)
    if entitlement is None or entitlement["status"] != "ACTIVE":
        raise err("ERR_ENTITLEMENT_NOT_ACTIVE", "The entitlement behind this seat is not ACTIVE.")
    if tool["shop_id"] != entitlement["shop_id"]:
        raise err("ERR_TOOL_SHOP_MISMATCH", "The tool belongs to another shop.")
    if (
        end <= start
        or start < entitlement["_window_start"]
        or end > entitlement["_window_end"]
    ):
        raise err(
            "ERR_SESSION_WINDOW_OUTSIDE_ENTITLEMENT",
            "The session window must sit wholly inside the entitlement's coverage window.",
        )

    row = store.base_row()
    row["seat_assignment_id"] = seat["id"]
    row["diagnostic_tool_id"] = tool["id"]
    row["vin"] = vin
    row["window_start"] = start_raw
    row["window_end"] = end_raw
    row["_window_start"] = start
    row["_window_end"] = end
    row["status"] = "REQUESTED"
    row["credential_token"] = None
    row["base_subtotal_cents"] = 0
    row["discount_cents"] = 0
    row["surcharge_cents"] = 0
    row["total_access_fee_cents"] = 0
    row["termination_reason"] = None
    store.gateway_sessions[row["id"]] = row
    return object_response(project("gateway_session", row), 201)


@bp.get("/gateway-sessions/<session_id>")
def read_session(session_id):
    authenticate(SESSION_READERS)
    row = find(store.gateway_sessions, session_id, "ERR_SESSION_NOT_FOUND")
    return object_response(project("gateway_session", row))


@bp.get("/gateway-sessions")
def list_sessions():
    authenticate(SESSION_READERS)
    seat_id = q_str("seat_assignment_id")
    tool_id = q_str("diagnostic_tool_id")
    status = q_enum("status", SESSION_STATUSES)
    limit, offset = pagination()

    rows = [
        row
        for row in store.gateway_sessions.values()
        if (seat_id is None or row["seat_assignment_id"] == seat_id)
        and (tool_id is None or row["diagnostic_tool_id"] == tool_id)
        and (status is None or row["status"] == status)
    ]
    return paged("gateway_session", rows, limit, offset)


@bp.post("/gateway-sessions/<session_id>/activate")
def activate_session(session_id):
    user_id, role = authenticate(("Technician",))
    session = find(store.gateway_sessions, session_id, "ERR_SESSION_NOT_FOUND")
    seat = _guard_seat_holder(role, user_id, session)
    check_allowed(body_object(), ())

    if session["status"] != "REQUESTED":
        raise err("ERR_INVALID_STATE", "Only a REQUESTED session may be activated.")
    if seat is None or seat["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "The seat behind this session is no longer ACTIVE.")
    entitlement = _entitlement_of(seat)
    if entitlement is None or entitlement["status"] != "ACTIVE":
        raise err("ERR_ENTITLEMENT_NOT_ACTIVE", "The entitlement behind this seat is not ACTIVE.")
    technician = store.technicians.get(seat["technician_id"])
    if technician is None or technician["identity_status"] != "VERIFIED":
        raise err("ERR_TECHNICIAN_NOT_VERIFIED", "The seated technician is not VERIFIED.")
    if technician["_credential_expires_at"] <= store.now():
        raise err("ERR_SECURITY_CREDENTIAL_EXPIRED", "The technician's credential has lapsed.")
    tool = store.diagnostic_tools.get(session["diagnostic_tool_id"])
    if tool is None or tool["_oem_attestation_expires_at"] <= store.now():
        raise err("ERR_TOOL_ATTESTATION_EXPIRED", "The tool's OEM attestation has lapsed.")
    for sibling in store.gateway_sessions.values():
        if sibling["id"] == session["id"]:
            continue
        if sibling["diagnostic_tool_id"] != tool["id"] or sibling["status"] != "ACTIVE":
            continue
        if (
            session["_window_start"] < sibling["_window_end"]
            and sibling["_window_start"] < session["_window_end"]
        ):
            raise err(
                "ERR_TOOL_WINDOW_CONFLICT",
                "Another ACTIVE session already occupies this tool over the window.",
            )

    session["status"] = "ACTIVE"
    session["credential_token"] = "GW-" + session["id"][:8].upper()
    store.touch(session)
    tool["status"] = "OCCUPIED"
    tool["occupied_by_session_id"] = session["id"]
    store.touch(tool)
    append_audit(
        role,
        user_id,
        "GatewaySession",
        session["id"],
        "SESSION_CREDENTIAL_ISSUED",
        "vin=%s" % session["vin"],
    )
    return object_response(project("gateway_session", session))


@bp.post("/gateway-sessions/<session_id>/complete")
def complete_session(session_id):
    user_id, role = authenticate(("Technician",))
    session = find(store.gateway_sessions, session_id, "ERR_SESSION_NOT_FOUND")
    _guard_seat_holder(role, user_id, session)
    check_allowed(body_object(), ())

    if session["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Only an ACTIVE session may be closed.")

    if store.now() < session["_window_end"]:
        for job in jobs_of_session(session):
            if job["status"] == "IN_PROGRESS":
                raise err(
                    "ERR_INVALID_STATE", "A job is IN_PROGRESS; the session cannot be completed."
                )
        price_and_close_session(
            session, "COMPLETED", None, role, user_id, "SESSION_COMPLETED"
        )
        abort_session_jobs(
            session,
            "SESSION_COMPLETED",
            ("QUEUED", "REVALIDATION_REQUIRED"),
            ("QUEUED",),
            "SYSTEM",
            None,
        )
    else:
        price_and_close_session(
            session, "EXPIRED", None, role, user_id, "SESSION_TERMINATED", "reason=SESSION_EXPIRED"
        )
        abort_session_jobs(
            session,
            "SESSION_EXPIRED",
            ("QUEUED", "IN_PROGRESS", "REVALIDATION_REQUIRED"),
            ("QUEUED", "IN_PROGRESS"),
            "SYSTEM",
            None,
        )
    return object_response(project("gateway_session", session))


# -- programming jobs -----------------------------------------------------


def _publication_of_version(version):
    return store.publications.get(version["publication_id"])


def _calibration_doc_available(version):
    publication = _publication_of_version(version)
    if publication is None:
        return False
    for candidate in store.publications.values():
        if (
            candidate["vehicle_model_id"] != publication["vehicle_model_id"]
            or candidate["system_area_id"] != publication["system_area_id"]
            or candidate["publication_type"] != "CALIBRATION_DOC"
        ):
            continue
        for row in store.publication_versions.values():
            if (
                row["publication_id"] == candidate["id"]
                and row["review_status"] == "VALIDATED"
                and row["distribution_status"] == "PUBLISHED"
            ):
                return True
    return False


@bp.post("/programming-jobs")
def queue_job():
    user_id, role = authenticate(("Technician",))
    body = body_object()
    session_id = body.get("session_id")
    if not isinstance(session_id, str) or not session_id:
        raise err("ERR_INVALID_REQUEST", "Field session_id must be a non-empty string identifier.")
    session = find(store.gateway_sessions, session_id, "ERR_SESSION_NOT_FOUND")
    _guard_seat_holder(role, user_id, session)

    check_allowed(body, ("session_id", "job_type", "pinned_publication_version_id"))
    job_type = get_enum(body, "job_type", JOB_TYPES)
    version_id = get_ref(body, "pinned_publication_version_id")
    version = find(store.publication_versions, version_id, "ERR_PUBLICATION_VERSION_NOT_FOUND")

    if version["distribution_status"] == "WITHHELD":
        raise err("ERR_VERSION_NOT_PUBLISHED", "The pinned version was never published.")
    if version["distribution_status"] in ("SUPERSEDED", "RECALLED"):
        raise err("ERR_STALE_PUBLICATION_VERSION", "The pinned version is no longer current.")

    row = store.base_row()
    row["session_id"] = session["id"]
    row["job_type"] = job_type
    row["pinned_publication_version_id"] = version["id"]
    row["status"] = "QUEUED"
    row["repin_count"] = 0
    row["abort_reason"] = None
    store.jobs[row["id"]] = row
    increment_pin_count(version["id"])
    return object_response(project("job", row), 201)


@bp.get("/programming-jobs/<job_id>")
def read_job(job_id):
    authenticate(SESSION_READERS)
    row = find(store.jobs, job_id, "ERR_JOB_NOT_FOUND")
    return object_response(project("job", row))


@bp.get("/programming-jobs")
def list_jobs():
    authenticate(SESSION_READERS)
    session_id = q_str("session_id")
    version_id = q_str("pinned_publication_version_id")
    status = q_enum("status", JOB_STATUSES)
    limit, offset = pagination()

    rows = [
        row
        for row in store.jobs.values()
        if (session_id is None or row["session_id"] == session_id)
        and (version_id is None or row["pinned_publication_version_id"] == version_id)
        and (status is None or row["status"] == status)
    ]
    return paged("job", rows, limit, offset)


@bp.post("/programming-jobs/<job_id>/start")
def start_job(job_id):
    user_id, role = authenticate(("Technician",))
    job = find(store.jobs, job_id, "ERR_JOB_NOT_FOUND")
    session = store.gateway_sessions.get(job["session_id"])
    if session is not None:
        _guard_seat_holder(role, user_id, session)
    check_allowed(body_object(), ())

    if job["status"] != "QUEUED":
        raise err("ERR_INVALID_STATE", "Only a QUEUED job may be started.")
    if session is None or session["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "The session is no longer ACTIVE.")

    version = store.publication_versions.get(job["pinned_publication_version_id"])
    if version is not None and version["distribution_status"] == "WITHHELD":
        raise err("ERR_VERSION_NOT_PUBLISHED", "The pinned version was never published.")

    technician = technician_of_session(session)
    if technician is None or technician["_credential_expires_at"] <= store.now():
        raise err("ERR_SECURITY_CREDENTIAL_EXPIRED", "The technician's credential has lapsed.")

    if job["job_type"] == "ADAS_CALIBRATION":
        if version is None or not _calibration_doc_available(version):
            raise err(
                "ERR_CALIBRATION_DOC_REQUIRED",
                "This cell has no VALIDATED and PUBLISHED calibration document.",
            )

    if version is not None and version["distribution_status"] in ("SUPERSEDED", "RECALLED"):
        raise err("ERR_STALE_PUBLICATION_VERSION", "The pinned version is no longer current.")

    job["status"] = "IN_PROGRESS"
    store.touch(job)
    append_audit(
        role,
        user_id,
        "ModuleProgrammingJob",
        job["id"],
        "JOB_STARTED",
        "job_type=%s" % job["job_type"],
    )
    return object_response(project("job", job))


@bp.post("/programming-jobs/<job_id>/complete")
def complete_job(job_id):
    user_id, role = authenticate(("Technician",))
    job = find(store.jobs, job_id, "ERR_JOB_NOT_FOUND")
    session = store.gateway_sessions.get(job["session_id"])
    if session is not None:
        _guard_seat_holder(role, user_id, session)
    check_allowed(body_object(), ())

    if job["status"] == "REVALIDATION_REQUIRED":
        raise err(
            "ERR_JOB_REVALIDATION_REQUIRED",
            "The job must be re-pinned to a current version before it can complete.",
        )
    if job["status"] != "IN_PROGRESS":
        raise err("ERR_INVALID_STATE", "Only an IN_PROGRESS job may be completed.")
    if session is None or session["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "The session is no longer ACTIVE.")

    job["status"] = "COMPLETED"
    store.touch(job)
    decrement_pin_count(job["pinned_publication_version_id"])
    append_audit(role, user_id, "ModuleProgrammingJob", job["id"], "JOB_COMPLETED")
    return object_response(project("job", job))


@bp.post("/programming-jobs/<job_id>/repin")
def repin_job(job_id):
    user_id, role = authenticate(("Technician",))
    job = find(store.jobs, job_id, "ERR_JOB_NOT_FOUND")
    session = store.gateway_sessions.get(job["session_id"])
    if session is not None:
        _guard_seat_holder(role, user_id, session)

    body = body_object()
    check_allowed(body, ("pinned_publication_version_id",))
    version_id = get_ref(body, "pinned_publication_version_id")
    replacement = find(
        store.publication_versions, version_id, "ERR_PUBLICATION_VERSION_NOT_FOUND"
    )

    current = store.publication_versions.get(job["pinned_publication_version_id"])
    if current is not None and replacement["publication_id"] != current["publication_id"]:
        raise err(
            "ERR_REFERENCED_RESOURCE_NOT_FOUND",
            "The replacement version belongs to a different publication.",
        )

    if job["status"] != "REVALIDATION_REQUIRED":
        raise err("ERR_INVALID_STATE", "Only a REVALIDATION_REQUIRED job may be re-pinned.")
    if session is None or session["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "The session is no longer ACTIVE.")
    if replacement["distribution_status"] != "PUBLISHED":
        raise err("ERR_VERSION_NOT_PUBLISHED", "The replacement version is not PUBLISHED.")

    job["pinned_publication_version_id"] = replacement["id"]
    job["repin_count"] = job["repin_count"] + 1
    job["status"] = "IN_PROGRESS"
    store.touch(job)
    increment_pin_count(replacement["id"])
    return object_response(project("job", job))
