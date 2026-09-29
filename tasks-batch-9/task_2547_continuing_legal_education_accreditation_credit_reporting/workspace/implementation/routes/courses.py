"""Course registration, discovery and the individual-approval application
lifecycle (PRD 3.2, 3.3)."""
import random
import string

from flask import Blueprint, request

import calc
import constants as C
import db
import listing
import middleware
import response
import util
from errors import fail
from routes.providers import load_provider
from services import cascades

bp = Blueprint("courses", __name__)

CATEGORIES = ["GENERAL", "ETHICS", "TECHNOLOGY", "BIAS_ELIMINATION"]
VERIFICATION_COMMITMENTS = ["ROSTER", "ATTENDANCE_CODE", "CERTIFICATE", "AFFIRMATION_ONLY"]
_CODE_ALPHABET = string.ascii_uppercase + string.digits


def load_course(course_id):
    course = db.get("courses", course_id)
    if course is None:
        fail("ERR_COURSE_NOT_FOUND", "No course matches that identifier.")
    return course


def load_application(application_id):
    application = db.get("course_applications", application_id)
    if application is None:
        fail("ERR_APPLICATION_NOT_FOUND", "No course application matches that identifier.")
    return application


def _mint_attendance_code():
    return "".join(random.choice(_CODE_ALPHABET) for _ in range(6))


def _expires_at(delivery_format, presented_at, total_minutes):
    if delivery_format in ("LIVE_IN_PERSON", "LIVE_WEBCAST"):
        return util.add_minutes(presented_at, total_minutes)
    return util.add_months(presented_at, C.APPROVAL_VALID_MONTHS)


def _session_conflict(provider_id, new_start, new_end):
    """More than two LIVE_IN_PERSON windows of one sponsor covering a common
    instant is ERR_SESSION_WINDOW_CONFLICT (PRD 3.2)."""
    windows = [(new_start, new_end)]
    for course in db.all_rows("courses"):
        if course.get("provider_id") != provider_id:
            continue
        if course.get("delivery_format") != "LIVE_IN_PERSON":
            continue
        start = util.parse_dt(course.get("presented_at"))
        end = util.parse_dt(course.get("expires_at"))
        if start is None or end is None:
            continue
        windows.append((start, end))
    for probe, _ignored in windows:
        overlapping = sum(1 for start, end in windows if start <= probe <= end)
        if overlapping > C.PROVIDER_CONCURRENT_LIVE_CAPACITY:
            return True
    return False


@bp.route("/cle/courses", methods=["POST"])
def create_course():
    user_id, role = middleware.require_roles(
        [C.ROLE_PROVIDER_ADMIN, C.ROLE_ATTORNEY, C.ROLE_BOARD_ADMIN]
    )
    body = middleware.body_json()

    # Step 4: body foreign-key existence.
    provider = None
    provider_supplied = middleware.present(body, "provider_id")
    if provider_supplied:
        if not isinstance(body.get("provider_id"), str):
            fail("ERR_INVALID_REQUEST", "provider_id must be a string.")
        provider = load_provider(body.get("provider_id"))

    # Step 5: ownership.
    if role == C.ROLE_PROVIDER_ADMIN:
        if not provider_supplied or provider["id"] != user_id:
            fail(
                "ERR_NOT_RESOURCE_OWNER",
                "A ProviderAdmin must register courses under its own provider_id.",
            )
    elif role == C.ROLE_ATTORNEY:
        if provider_supplied:
            fail("ERR_NOT_RESOURCE_OWNER", "An Attorney must omit provider_id.")

    # Step 6: request shape.
    title = middleware.req_str(body, "title", 1, 200)
    delivery_format = middleware.req_enum(body, "delivery_format", C.DELIVERY_FORMATS)
    total_minutes = middleware.req_int(body, "total_minutes", 0)
    if total_minutes < 30 or total_minutes % C.ROUNDING_INCREMENT_MINUTES != 0:
        fail(
            "ERR_INVALID_REQUEST",
            "total_minutes must be at least 30 and a whole multiple of 15.",
        )
    presented_at = middleware.req_instant(body, "presented_at")
    verification = middleware.req_enum(body, "attendance_verification_method", VERIFICATION_COMMITMENTS)
    allocations = middleware.req_list(body, "credit_allocations")
    if len(allocations) == 0:
        fail("ERR_INVALID_REQUEST", "credit_allocations must be a non-empty array.")
    seen = []
    parsed = []
    for element in allocations:
        if not isinstance(element, dict):
            fail("ERR_INVALID_REQUEST", "Each credit allocation must be an object.")
        category = middleware.req_enum(element, "category", CATEGORIES)
        minutes = middleware.req_int(element, "minutes", 0)
        if category in seen:
            fail("ERR_INVALID_REQUEST", "credit_allocations may not repeat a category.")
        seen.append(category)
        parsed.append((category, minutes))

    # Step 13: regulatory standing of the named sponsor.
    if provider is not None and provider.get("accreditation_status") not in (
        "ACCREDITED",
        "PROBATIONARY",
    ):
        fail(
            "ERR_PROVIDER_NOT_IN_GOOD_STANDING",
            "Courses cannot be registered against a sponsor that is %s."
            % provider.get("accreditation_status"),
        )

    expires_at = _expires_at(delivery_format, presented_at, total_minutes)

    # Step 15: temporal coherence — concurrent live capacity.
    if delivery_format == "LIVE_IN_PERSON" and provider is not None:
        if _session_conflict(provider["id"], presented_at, expires_at):
            fail(
                "ERR_SESSION_WINDOW_CONFLICT",
                "A third overlapping live session is not permitted for this sponsor.",
            )

    # Step 16: sum and multiple constraints.
    for category, minutes in parsed:
        if minutes <= 0 or minutes % C.ROUNDING_INCREMENT_MINUTES != 0:
            fail(
                "ERR_ALLOCATION_NOT_MULTIPLE_OF_15",
                "Allocation minutes must be a positive whole multiple of 15.",
            )
    if sum(minutes for _c, minutes in parsed) != total_minutes:
        fail(
            "ERR_ALLOCATION_SUM_MISMATCH",
            "Allocated minutes must sum exactly to total_minutes.",
        )

    self_certified = bool(provider is not None and provider.get("self_certification_enabled"))
    pathway = "PROVIDER_ACCREDITED" if self_certified else "INDIVIDUAL_APPROVAL"
    course = db.insert(
        "courses",
        {
            "provider_id": provider["id"] if provider is not None else None,
            "title": title,
            "delivery_format": delivery_format,
            "total_minutes": total_minutes,
            "presented_at": util.iso(presented_at),
            "expires_at": util.iso(expires_at),
            "attendance_verification_method": verification,
            "attendance_code": _mint_attendance_code() if verification == "ATTENDANCE_CODE" else None,
            "approval_pathway": pathway,
            "status": "APPROVED" if self_certified else "PENDING_APPROVAL",
            "denial_reason": None,
            "credited_minutes_total": total_minutes,
            "verified_credit_record_count": 0,
        },
    )
    for category, minutes in parsed:
        db.insert("credit_allocations", {"course_id": course["id"], "category": category, "minutes": minutes})

    if provider is not None:
        updates = {"courses_total_count": int(provider.get("courses_total_count") or 0) + 1}
        if self_certified:
            updates["courses_self_certified_count"] = (
                int(provider.get("courses_self_certified_count") or 0) + 1
            )
        cascades.set_fields(provider, updates)
        if self_certified:
            cascades.refresh_risk(provider)
    return response.success(db.serialize(course), 201)


@bp.route("/cle/courses/<course_id>", methods=["GET"])
def read_course(course_id):
    middleware.require_roles(
        [C.ROLE_BOARD_ADMIN, C.ROLE_REVIEWER, C.ROLE_PANELIST, C.ROLE_PROVIDER_ADMIN, C.ROLE_ATTORNEY]
    )
    return response.success(db.serialize(load_course(course_id)), 200)


@bp.route("/cle/courses", methods=["GET"])
def list_courses():
    middleware.require_roles(
        [C.ROLE_BOARD_ADMIN, C.ROLE_REVIEWER, C.ROLE_PROVIDER_ADMIN, C.ROLE_ATTORNEY]
    )
    rows = listing.apply_filters(
        db.all_rows("courses"), ["provider_id", "status", "delivery_format", "approval_pathway"]
    )
    return listing.page(listing.sort_created_desc(rows))


@bp.route("/cle/courses/<course_id>/credit-allocations", methods=["GET"])
def list_allocations(course_id):
    middleware.require_roles(
        [C.ROLE_BOARD_ADMIN, C.ROLE_REVIEWER, C.ROLE_PROVIDER_ADMIN, C.ROLE_ATTORNEY]
    )
    course = load_course(course_id)
    rows = [a for a in db.all_rows("credit_allocations") if a.get("course_id") == course["id"]]
    return listing.page(listing.sort_created_asc(rows))


@bp.route("/cle/courses/<course_id>/attendance-reports", methods=["GET"])
def list_attendance_reports(course_id):
    middleware.require_roles([C.ROLE_BOARD_ADMIN, C.ROLE_REVIEWER, C.ROLE_PROVIDER_ADMIN])
    course = load_course(course_id)
    rows = [r for r in db.all_rows("attendance_reports") if r.get("course_id") == course["id"]]
    return listing.page(listing.sort_created_asc(rows))


# ------------------------------------------------------- approval applications
LIVE_APPLICATION_STATUSES = ("SUBMITTED", "INFO_REQUESTED", "APPEALED")
REVIEW_ACTIONS = ["REQUEST_INFO", "APPROVE", "DENY"]
APPELLANT_ACTIONS = ["SUPPLEMENT", "APPEAL"]
DISPOSITIONS = ["GRANT", "DENY", "REMAND", "GRANT_APPEAL", "DENY_APPEAL"]


@bp.route("/cle/courses/<course_id>/applications", methods=["POST"])
def file_application(course_id):
    user_id, role = middleware.require_roles([C.ROLE_PROVIDER_ADMIN, C.ROLE_ATTORNEY])
    course = load_course(course_id)

    # Step 5: ownership.
    if role == C.ROLE_PROVIDER_ADMIN and course.get("provider_id") != user_id:
        fail("ERR_NOT_RESOURCE_OWNER", "That course is sponsored by another provider.")

    # Step 13: regulatory standing.
    if course.get("status") != "PENDING_APPROVAL":
        fail("ERR_COURSE_NOT_APPROVED", "Applications may only be filed on a PENDING_APPROVAL course.")
    provider = db.get("providers", course.get("provider_id"))
    if provider is not None and provider.get("accreditation_status") not in (
        "ACCREDITED",
        "PROBATIONARY",
    ):
        fail("ERR_PROVIDER_NOT_IN_GOOD_STANDING", "The sponsoring provider is not in good standing.")
    if role == C.ROLE_ATTORNEY:
        attorney = db.get("attorneys", user_id)
        if attorney is not None and attorney.get("status") not in ("ACTIVE", "EXEMPT"):
            fail("ERR_ATTORNEY_NOT_IN_GOOD_STANDING", "The acting attorney is not in good standing.")

    # Step 16: only one live application per course.
    for existing in db.all_rows("course_applications"):
        if existing.get("course_id") == course["id"] and existing.get("status") in LIVE_APPLICATION_STATUSES:
            fail("ERR_DUPLICATE_APPLICATION", "That course already has a live application.")

    application = db.insert(
        "course_applications",
        {
            "course_id": course["id"],
            "applicant_role": "PROVIDER_ADMIN" if role == C.ROLE_PROVIDER_ADMIN else "ATTORNEY",
            "applicant_user_id": user_id,
            "status": "SUBMITTED",
            "info_request_round": 0,
            "supplement_count": 0,
            "remand_count": 0,
            "reviewer_user_id": None,
            "denial_reason": None,
            "appeal_grounds": None,
            "appeal_panelist_user_id": None,
            "appeal_filed_at": None,
            "denied_at": None,
            "decided_at": None,
        },
    )
    return response.success(db.serialize(application), 201)


@bp.route("/cle/courses/<course_id>/applications", methods=["GET"])
def list_course_applications(course_id):
    middleware.require_roles(
        [C.ROLE_BOARD_ADMIN, C.ROLE_REVIEWER, C.ROLE_PANELIST, C.ROLE_PROVIDER_ADMIN, C.ROLE_ATTORNEY]
    )
    course = load_course(course_id)
    rows = [a for a in db.all_rows("course_applications") if a.get("course_id") == course["id"]]
    return listing.page(listing.sort_created_asc(rows))


@bp.route("/cle/course-applications/<application_id>", methods=["GET"])
def read_application(application_id):
    middleware.require_roles(
        [C.ROLE_BOARD_ADMIN, C.ROLE_REVIEWER, C.ROLE_PANELIST, C.ROLE_PROVIDER_ADMIN, C.ROLE_ATTORNEY]
    )
    return response.success(db.serialize(load_application(application_id)), 200)


@bp.route("/cle/course-applications/<application_id>/review-actions", methods=["POST"])
def review_action(application_id):
    user_id, _role = middleware.require_roles([C.ROLE_REVIEWER])
    application = load_application(application_id)
    body = middleware.body_json()
    action = middleware.req_enum(body, "action", REVIEW_ACTIONS)
    middleware.opt_str(body, "note", 1, None, None)
    denial_reason = middleware.opt_str(body, "denial_reason", 1, None, None)
    if action == "DENY" and denial_reason is None:
        fail("ERR_INVALID_REQUEST", "denial_reason is required to deny an application.")

    status = application.get("status")
    course = db.get("courses", application.get("course_id"))

    if action == "REQUEST_INFO":
        if status != "SUBMITTED":
            fail("ERR_INVALID_STATE_TRANSITION", "REQUEST_INFO is not declared from %s." % status)
        if int(application.get("info_request_round") or 0) + 1 > C.MAX_INFO_REQUEST_ROUNDS:
            fail("ERR_INFO_REQUEST_LIMIT_EXCEEDED", "The two-round information budget is exhausted.")
        cascades.set_fields(
            application,
            {
                "status": "INFO_REQUESTED",
                "info_request_round": int(application.get("info_request_round") or 0) + 1,
                "reviewer_user_id": user_id,
            },
        )
    elif action == "APPROVE":
        if status not in ("SUBMITTED", "INFO_REQUESTED"):
            fail("ERR_INVALID_STATE_TRANSITION", "APPROVE is not declared from %s." % status)
        if course is None or course.get("status") != "PENDING_APPROVAL":
            fail("ERR_INVALID_STATE_TRANSITION", "The course is no longer PENDING_APPROVAL.")
        cascades.set_fields(
            application,
            {"status": "APPROVED", "decided_at": util.now_iso(), "reviewer_user_id": user_id},
        )
        cascades.set_fields(course, {"status": "APPROVED"})
    else:  # DENY
        if status not in ("SUBMITTED", "INFO_REQUESTED"):
            fail("ERR_INVALID_STATE_TRANSITION", "DENY is not declared from %s." % status)
        cascades.set_fields(
            application,
            {
                "status": "DENIED",
                "denial_reason": denial_reason,
                "denied_at": util.now_iso(),
                "reviewer_user_id": user_id,
            },
        )
        if course is not None and course.get("status") == "PENDING_APPROVAL":
            cascades.set_fields(course, {"status": "DENIED", "denial_reason": denial_reason})
    return response.success(db.serialize(application), 200)


@bp.route("/cle/course-applications/<application_id>/appellant-actions", methods=["POST"])
def appellant_action(application_id):
    user_id, _role = middleware.require_roles([C.ROLE_PROVIDER_ADMIN, C.ROLE_ATTORNEY])
    application = load_application(application_id)
    if application.get("applicant_user_id") != user_id:
        fail("ERR_NOT_RESOURCE_OWNER", "Only the application's own applicant may act here.")
    body = middleware.body_json()
    action = middleware.req_enum(body, "action", APPELLANT_ACTIONS)
    appeal_grounds = middleware.opt_str(body, "appeal_grounds", 1, None, None)
    if action == "APPEAL" and appeal_grounds is None:
        fail("ERR_INVALID_REQUEST", "appeal_grounds is required to appeal.")

    status = application.get("status")
    if action == "SUPPLEMENT":
        if status != "INFO_REQUESTED":
            fail("ERR_INVALID_STATE_TRANSITION", "SUPPLEMENT is not declared from %s." % status)
        cascades.set_fields(
            application,
            {
                "status": "SUBMITTED",
                "supplement_count": int(application.get("supplement_count") or 0) + 1,
            },
        )
    else:  # APPEAL
        if status != "DENIED":
            fail("ERR_INVALID_STATE_TRANSITION", "APPEAL is not declared from %s." % status)
        denied_at = util.parse_dt(application.get("denied_at"))
        window_end = util.add_days(denied_at, C.APPEAL_WINDOW_DAYS)
        if util.now_dt() >= window_end:
            fail("ERR_APPEAL_WINDOW_EXPIRED", "The thirty-day appeal window has closed.")
        cascades.set_fields(
            application,
            {
                "status": "APPEALED",
                "appeal_grounds": appeal_grounds,
                "appeal_filed_at": util.now_iso(),
            },
        )
    return response.success(db.serialize(application), 200)


@bp.route("/cle/course-applications/<application_id>/appeal-decisions", methods=["POST"])
def appeal_decision(application_id):
    user_id, _role = middleware.require_roles([C.ROLE_PANELIST])
    application = load_application(application_id)
    body = middleware.body_json()
    disposition = middleware.req_enum(body, "disposition", DISPOSITIONS)
    decision_reason = middleware.opt_str(body, "decision_reason", 1, None, None)

    if application.get("status") != "APPEALED":
        fail(
            "ERR_INVALID_STATE_TRANSITION",
            "An appeal decision requires the application to be APPEALED.",
        )
    if application.get("reviewer_user_id") == user_id:
        fail("ERR_SEGREGATION_OF_DUTIES", "The reviewer below may not decide the appeal.")

    course = db.get("courses", application.get("course_id"))
    if disposition in ("GRANT", "GRANT_APPEAL"):
        cascades.set_fields(
            application,
            {
                "status": "APPEAL_GRANTED",
                "decided_at": util.now_iso(),
                "denial_reason": None,
                "appeal_panelist_user_id": user_id,
            },
        )
        if course is not None:
            cascades.set_fields(course, {"status": "APPROVED", "denial_reason": None})
    elif disposition in ("DENY", "DENY_APPEAL"):
        cascades.set_fields(
            application,
            {
                "status": "APPEAL_DENIED",
                "decided_at": util.now_iso(),
                "denial_reason": decision_reason,
                "appeal_panelist_user_id": user_id,
            },
        )
    else:  # REMAND
        if int(application.get("remand_count") or 0) + 1 > C.MAX_REMANDS:
            fail("ERR_REMAND_LIMIT_EXCEEDED", "The board allows at most one remand.")
        cascades.set_fields(
            application,
            {
                "status": "SUBMITTED",
                "remand_count": int(application.get("remand_count") or 0) + 1,
                "reviewer_user_id": None,
                "denial_reason": None,
                "denied_at": None,
                "info_request_round": 0,
                "appeal_panelist_user_id": user_id,
            },
        )
        if course is not None:
            cascades.set_fields(course, {"status": "PENDING_APPROVAL", "denial_reason": None})
    return response.success(db.serialize(application), 200)
