"""DiagnosisReferral and Specialist endpoints."""

from datetime import timedelta
from flask import request, Blueprint

import db
import util
from middleware import auth_context
from errors import raise_err
from response import success_object, success_list
from services import calculations as calc
from routes.shifts import get_inquiry_or_404, INQUIRY_CATEGORIES

bp = Blueprint("referrals", __name__)

ALL_ROLES = ["ProgramCoordinator", "Volunteer", "Specialist"]
PC = ["ProgramCoordinator"]

SLA_HOURS = 48


def get_referral_or_404(referral_id):
    r = db.diagnosis_referrals.get(referral_id)
    if r is None:
        raise_err("ERR_NOT_FOUND", "DiagnosisReferral not found")
    return r


def get_specialist_or_404(specialist_id):
    s = db.specialists.get(specialist_id)
    if s is None:
        raise_err("ERR_NOT_FOUND", "Specialist not found")
    return s


# =====================================================================
# Specialist endpoints
# =====================================================================

@bp.route("/specialists", methods=["POST"])
def create_specialist():
    auth_context(PC)
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise_err("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    for f in ("name", "specialty", "max_concurrent_referrals"):
        if f not in body:
            raise_err("ERR_INVALID_REQUEST", f"Missing required field: {f}")
    if not isinstance(body["name"], str) or not body["name"]:
        raise_err("ERR_INVALID_REQUEST", "name must be a non-empty string")
    if body["specialty"] not in INQUIRY_CATEGORIES:
        raise_err("ERR_INVALID_REQUEST", "specialty is not a valid enum member")
    if not isinstance(body["max_concurrent_referrals"], int) or isinstance(body["max_concurrent_referrals"], bool):
        raise_err("ERR_INVALID_REQUEST", "max_concurrent_referrals must be an integer")
    if body["max_concurrent_referrals"] < 1:
        raise_err("ERR_INVALID_FIELD_VALUE", "max_concurrent_referrals must be >= 1")
    accepting = body.get("accepting_referrals", True)
    if not isinstance(accepting, bool):
        raise_err("ERR_INVALID_REQUEST", "accepting_referrals must be a boolean")
    specialist = util.new_resource({
        "name": body["name"],
        "specialty": body["specialty"],
        "max_concurrent_referrals": body["max_concurrent_referrals"],
        "accepting_referrals": accepting,
        "open_referral_count": 0,
        "answered_count": 0,
        "late_referral_count": 0,
        "returned_count": 0,
        "rolling_score": 100.0,
        "lifetime_score": 100.0,
    })
    db.specialists[specialist["id"]] = specialist
    return success_object(specialist, 201)


@bp.route("/specialists", methods=["GET"])
def list_specialists():
    auth_context(ALL_ROLES)
    items = list(db.specialists.values())
    specialty = request.args.get("specialty")
    accepting = request.args.get("accepting_referrals")
    if specialty is not None:
        items = [s for s in items if s["specialty"] == specialty]
    if accepting is not None:
        want = accepting.lower() == "true"
        items = [s for s in items if s["accepting_referrals"] == want]
    for s in items:
        calc.recompute_specialist_scores(s)
    items = util.sort_created(items)
    limit, offset = util.paginate(items, request.args)
    return success_list(items[offset:offset + limit], len(items), limit, offset)


@bp.route("/specialists/<specialistId>", methods=["GET"])
def get_specialist(specialistId):
    auth_context(ALL_ROLES)
    specialist = get_specialist_or_404(specialistId)
    calc.recompute_specialist_scores(specialist)
    return success_object(specialist)


@bp.route("/specialists/<specialistId>", methods=["PATCH"])
def update_specialist(specialistId):
    auth_context(PC)
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise_err("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    if "expected_specialist_version" not in body:
        raise_err("ERR_INVALID_REQUEST", "expected_specialist_version is required")
    if not isinstance(body["expected_specialist_version"], int) or isinstance(body["expected_specialist_version"], bool):
        raise_err("ERR_INVALID_REQUEST", "expected_specialist_version must be an integer")
    if "max_concurrent_referrals" in body:
        v = body["max_concurrent_referrals"]
        if not isinstance(v, int) or isinstance(v, bool):
            raise_err("ERR_INVALID_REQUEST", "max_concurrent_referrals must be an integer")
        if v < 1:
            raise_err("ERR_INVALID_FIELD_VALUE", "max_concurrent_referrals must be >= 1")
    if "accepting_referrals" in body:
        if not isinstance(body["accepting_referrals"], bool):
            raise_err("ERR_INVALID_REQUEST", "accepting_referrals must be a boolean")

    specialist = get_specialist_or_404(specialistId)
    if body["expected_specialist_version"] != specialist["version"]:
        raise_err("ERR_STALE_SPECIALIST_VERSION",
                  "expected_specialist_version does not match the specialist's current version")
    if "max_concurrent_referrals" in body:
        specialist["max_concurrent_referrals"] = body["max_concurrent_referrals"]
    if "accepting_referrals" in body:
        specialist["accepting_referrals"] = body["accepting_referrals"]
    util.touch(specialist)
    return success_object(specialist)


# =====================================================================
# DiagnosisReferral endpoints
# =====================================================================

def _assign_specialist(referral, inquiry, explicit_id, note=None):
    """Resolve the assignee for a referral (creation or reassignment).

    Raises on capacity/specialty/availability failures. Returns the Specialist.
    """
    if explicit_id is not None:
        if not isinstance(explicit_id, str):
            raise_err("ERR_INVALID_REQUEST", "specialist_id must be a string")
        specialist = db.specialists.get(explicit_id)
        if specialist is None:
            raise_err("ERR_NOT_FOUND", "specialist_id does not resolve")
        # on reassign: explicit pick equal to last_specialist_id fails
        if referral is not None and referral.get("last_specialist_id") == explicit_id:
            raise_err("ERR_INVALID_REQUEST",
                      "Explicit specialist_id equals last_specialist_id; excluded from reselection")
        if not specialist["accepting_referrals"]:
            raise_err("ERR_NO_SPECIALIST_AVAILABLE", "Specialist is not accepting referrals")
        if specialist["open_referral_count"] >= specialist["max_concurrent_referrals"]:
            raise_err("ERR_SPECIALIST_AT_CAPACITY", "Specialist has reached max concurrent referrals")
        if specialist["specialty"] not in (inquiry["category"], "GENERAL"):
            raise_err("ERR_SPECIALTY_MISMATCH",
                      "Specialist specialty must equal the inquiry category or GENERAL")
        return specialist
    exclude = referral.get("last_specialist_id") if referral is not None else None
    specialist = calc.select_specialist(inquiry, exclude_specialist_id=exclude)
    if specialist is None:
        raise_err("ERR_NO_SPECIALIST_AVAILABLE", "No available specialist for this inquiry category")
    return specialist


@bp.route("/inquiries/<inquiryId>/referrals", methods=["POST"])
def create_referral(inquiryId):
    auth_context(PC)
    body = request.get_json(silent=True) or {}
    if not isinstance(body, dict):
        raise_err("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    inquiry = get_inquiry_or_404(inquiryId)
    # PRD §3.5: "an inquiry may have at most one referral in OPEN, IN_REVIEW,
    # or RETURNED status at a time; a second attempt fails with
    # ERR_REFERRAL_ALREADY_OPEN". A second attempt lands on a REFERRED
    # inquiry, so this specific check must pre-empt the generic TRIAGED
    # state guard (otherwise ERR_REFERRAL_ALREADY_OPEN would be unreachable:
    # an inquiry with an active referral is never TRIAGED).
    for r in db.diagnosis_referrals.values():
        if r["inquiry_id"] == inquiry["id"] and r["status"] in ("OPEN", "IN_REVIEW", "RETURNED"):
            raise_err("ERR_REFERRAL_ALREADY_OPEN",
                      "The inquiry already has an active referral; reassign the RETURNED referral")
    # state: inquiry must be TRIAGED
    if inquiry["status"] != "TRIAGED":
        raise_err("ERR_INQUIRY_NOT_TRIAGED", "Referral requires a TRIAGED inquiry")
    explicit_id = body.get("specialist_id")
    specialist = _assign_specialist(None, inquiry, explicit_id, body.get("note"))

    now = util.logical_clock()
    referral = util.new_resource({
        "inquiry_id": inquiry["id"],
        "specialist_id": specialist["id"],
        "last_specialist_id": None,
        "status": "OPEN",
        "due_at": util._format_dt(now + timedelta(hours=SLA_HOURS)),
        "reassignment_count": 0,
        "diagnosis_text": None,
        "return_reason": None,
        "answered_at": None,
        "answered_by_specialist_id": None,
        "returned_at": None,
        "returned_by_specialist_id": None,
    })
    db.diagnosis_referrals[referral["id"]] = referral
    inquiry["status"] = "REFERRED"
    util.touch(inquiry)
    specialist["open_referral_count"] += 1
    util.touch(specialist)
    return success_object(referral, 201)


@bp.route("/diagnosis-referrals", methods=["GET"])
def list_referrals():
    auth_context(ALL_ROLES)
    items = list(db.diagnosis_referrals.values())
    for param in ("inquiry_id", "specialist_id", "last_specialist_id",
                  "answered_by_specialist_id", "returned_by_specialist_id", "status"):
        v = request.args.get(param)
        if v is not None:
            items = [r for r in items if r.get(param) == v]
    items = util.sort_created(items)
    limit, offset = util.paginate(items, request.args)
    return success_list(items[offset:offset + limit], len(items), limit, offset)


@bp.route("/diagnosis-referrals/<referralId>", methods=["GET"])
def get_referral(referralId):
    auth_context(ALL_ROLES)
    return success_object(get_referral_or_404(referralId))


@bp.route("/diagnosis-referrals/<referralId>/start-review", methods=["POST"])
def start_review(referralId):
    user_id, role = auth_context(["Specialist"])
    referral = get_referral_or_404(referralId)
    if referral["specialist_id"] is not None and user_id != referral["specialist_id"]:
        raise_err("ERR_NOT_RESOURCE_OWNER", "Only the assigned specialist may start review")
    if referral["status"] != "OPEN":
        raise_err("ERR_REFERRAL_NOT_OPEN", "Start-review requires an OPEN referral")
    if user_id != referral["specialist_id"]:
        raise_err("ERR_NOT_RESOURCE_OWNER", "Only the assigned specialist may start review")
    referral["status"] = "IN_REVIEW"
    util.touch(referral)
    return success_object(referral)


@bp.route("/diagnosis-referrals/<referralId>/answer", methods=["POST"])
def answer_referral(referralId):
    user_id, role = auth_context(["Specialist"])
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise_err("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    if "diagnosis_text" not in body or not isinstance(body.get("diagnosis_text"), str):
        raise_err("ERR_INVALID_REQUEST", "diagnosis_text is required")
    referral = get_referral_or_404(referralId)
    if referral["specialist_id"] is not None and user_id != referral["specialist_id"]:
        raise_err("ERR_NOT_RESOURCE_OWNER", "Only the assigned specialist may answer")
    if referral["status"] != "IN_REVIEW":
        raise_err("ERR_REFERRAL_NOT_IN_REVIEW", "Answer requires an IN_REVIEW referral")
    if user_id != referral["specialist_id"]:
        raise_err("ERR_NOT_RESOURCE_OWNER", "Only the assigned specialist may answer")

    now = util.logical_clock()
    referral["diagnosis_text"] = body["diagnosis_text"]
    referral["answered_at"] = util.logical_clock_iso()
    referral["answered_by_specialist_id"] = referral["specialist_id"]
    referral["status"] = "ANSWERED"
    util.touch(referral)

    specialist = db.specialists.get(referral["specialist_id"])
    if specialist is not None:
        specialist["open_referral_count"] = max(0, specialist["open_referral_count"] - 1)
        specialist["answered_count"] += 1
        if now > util.parse_dt(referral["due_at"]):
            specialist["late_referral_count"] += 1
        calc.recompute_specialist_scores(specialist)

    inquiry = db.inquiries.get(referral["inquiry_id"])
    if inquiry is not None and inquiry["status"] == "REFERRED":
        inquiry["status"] = "CLOSED"
        inquiry["resolution"] = "SPECIALIST_DIAGNOSIS"
        inquiry["resolved_at"] = util.logical_clock_iso()
        util.touch(inquiry)
    return success_object(referral)


@bp.route("/diagnosis-referrals/<referralId>/return", methods=["POST"])
def return_referral(referralId):
    user_id, role = auth_context(["Specialist"])
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise_err("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    if "return_reason" not in body or not isinstance(body.get("return_reason"), str):
        raise_err("ERR_INVALID_REQUEST", "return_reason is required")
    referral = get_referral_or_404(referralId)
    if referral["specialist_id"] is not None and user_id != referral["specialist_id"]:
        raise_err("ERR_NOT_RESOURCE_OWNER", "Only the assigned specialist may return")
    if referral["status"] != "IN_REVIEW":
        raise_err("ERR_REFERRAL_NOT_IN_REVIEW", "Return requires an IN_REVIEW referral")
    if user_id != referral["specialist_id"]:
        raise_err("ERR_NOT_RESOURCE_OWNER", "Only the assigned specialist may return")

    referral["return_reason"] = body["return_reason"]
    referral["returned_at"] = util.logical_clock_iso()
    referral["returned_by_specialist_id"] = referral["specialist_id"]
    referral["last_specialist_id"] = referral["specialist_id"]
    referral["status"] = "RETURNED"
    util.touch(referral)

    specialist = db.specialists.get(referral["specialist_id"])
    if specialist is not None:
        specialist["open_referral_count"] = max(0, specialist["open_referral_count"] - 1)
        specialist["returned_count"] += 1
        calc.recompute_specialist_scores(specialist)
    referral["specialist_id"] = None
    return success_object(referral)


@bp.route("/diagnosis-referrals/<referralId>/reassign", methods=["POST"])
def reassign_referral(referralId):
    auth_context(PC)
    body = request.get_json(silent=True) or {}
    if not isinstance(body, dict):
        raise_err("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    referral = get_referral_or_404(referralId)
    if referral["status"] != "RETURNED":
        raise_err("ERR_REFERRAL_NOT_RETURNED", "Reassign requires a RETURNED referral")
    inquiry = db.inquiries.get(referral["inquiry_id"])
    if inquiry is None:
        raise_err("ERR_NOT_FOUND", "Referral's inquiry not found")
    explicit_id = body.get("specialist_id")
    specialist = _assign_specialist(referral, inquiry, explicit_id, body.get("note"))

    referral["specialist_id"] = specialist["id"]
    referral["status"] = "OPEN"
    referral["reassignment_count"] += 1
    referral["due_at"] = util._format_dt(util.logical_clock() + timedelta(hours=SLA_HOURS))
    util.touch(referral)
    specialist["open_referral_count"] += 1
    util.touch(specialist)
    return success_object(referral)
