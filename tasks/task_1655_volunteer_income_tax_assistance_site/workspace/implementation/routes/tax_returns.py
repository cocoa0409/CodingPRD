"""Tax return opening, intake editing, and the full lifecycle (PRD §3.4-§3.8)."""
from flask import Blueprint

import db
from db import store
from errors import ApiError
from middleware import get_context, require_roles
from response import created, ok, paginate
from services import calcs, certs, cascades
from services.serialize import (documents_complete, out_of_scope_reasons,
                                return_json)
from validation import get_body, parse_body, require_entity

bp = Blueprint("tax_returns", __name__)

RETURN_STATUSES = ["INTAKE_STARTED", "IN_PREPARATION", "PENDING_QR", "QR_FAILED",
                   "QR_PASSED", "TRANSMITTED", "ACCEPTED", "REJECTED",
                   "COMPLETED", "REFERRED", "WITHDRAWN"]

TERMINAL_STATUSES = ("COMPLETED", "REFERRED", "WITHDRAWN")

FILING_STATUSES = ["SINGLE", "MARRIED_JOINT", "HEAD_OF_HOUSEHOLD",
                   "MARRIED_SEPARATE"]

SCOPE_FLAGS = ["RENTAL_INCOME", "BUSINESS_WITH_LOSS", "FOREIGN_EARNED_INCOME",
               "CASUALTY_LOSS"]

DOCUMENTS = ["PHOTO_ID", "SSN_CARD", "W2", "FORM_1099", "PRIOR_YEAR_RETURN",
             "BANK_INFO"]

REFERRABLE = ("INTAKE_STARTED", "IN_PREPARATION", "PENDING_QR", "QR_FAILED",
              "QR_PASSED", "REJECTED")

CREATE_SCHEMA = {
    "appointment_id": {"kind": "string", "required": True},
    "tax_year": {"kind": "integer", "required": True},
    "filing_status": {"kind": "enum", "required": True, "values": FILING_STATUSES},
    "has_advanced_scope_items": {"kind": "boolean"},
    "out_of_scope_flags": {"kind": "array_enum", "values": SCOPE_FLAGS},
}

PATCH_SCHEMA = {
    "documents_received": {"kind": "array_enum", "values": DOCUMENTS},
    "interview_confirmed": {"kind": "boolean"},
    "wages_cents": {"kind": "integer", "min": 0},
    "other_income_cents": {"kind": "integer", "min": 0},
    "earned_income_cents": {"kind": "integer", "min": 0},
    "qualifying_children": {"kind": "integer", "min": 0, "max": 10},
    "withholding_reported_cents": {"kind": "integer", "min": 0},
    "withholding_verified_cents": {"kind": "integer", "min": 0,
                                   "allow_null": True},
    "has_advanced_scope_items": {"kind": "boolean"},
    "out_of_scope_flags": {"kind": "array_enum", "values": SCOPE_FLAGS},
    "refund_method": {"kind": "enum", "values": ["PAPER_CHECK", "DIRECT_DEPOSIT"]},
    "expected_return_version": {"kind": "integer", "required": True},
}

STATE_SCHEMA = {
    "to_status": {"kind": "enum", "required": True, "values": RETURN_STATUSES},
    "review_notes": {"kind": "string"},
    "rejection_code": {"kind": "string"},
    "rejection_text": {"kind": "string"},
    "referral_reason": {"kind": "string"},
    "referral_destination": {"kind": "string"},
    "withdrawal_reason": {"kind": "string"},
    "disbursement_confirmed": {"kind": "boolean"},
    "taxpayer_notified": {"kind": "boolean"},
}

# to_status -> (source states, allowed roles, requires return ownership)
TRANSITIONS = {
    "IN_PREPARATION": (("INTAKE_STARTED", "QR_FAILED", "REJECTED"),
                       ("Preparer",), True),
    "PENDING_QR": (("IN_PREPARATION",), ("Preparer",), True),
    "QR_PASSED": (("PENDING_QR",), ("QualityReviewer",), False),
    "QR_FAILED": (("PENDING_QR",), ("QualityReviewer",), False),
    "TRANSMITTED": (("QR_PASSED",), ("SiteCoordinator",), False),
    "ACCEPTED": (("TRANSMITTED",), ("SiteCoordinator",), False),
    "REJECTED": (("TRANSMITTED",), ("SiteCoordinator",), False),
    "COMPLETED": (("ACCEPTED",), ("SiteCoordinator",), False),
    "REFERRED": (REFERRABLE, ("Preparer", "QualityReviewer", "SiteCoordinator"),
                 False),
    "WITHDRAWN": (REFERRABLE, ("Preparer", "SiteCoordinator"), False),
    "INTAKE_STARTED": ((), (), False),  # never a transition target
}

MAX_SUBMISSIONS = 3


@bp.post("/tax-returns")
def create_return():
    uid, role, volunteer = get_context()
    require_roles(["Preparer"])
    raw = get_body()
    appointment_id = raw.get("appointment_id")
    if isinstance(appointment_id, str) and appointment_id not in store.appointments:
        raise ApiError("ERR_NOT_FOUND", 404, "Referenced appointment does not exist")
    body = parse_body(CREATE_SCHEMA)
    appt = store.appointments.get(body["appointment_id"])
    if appt is None:
        raise ApiError("ERR_INVALID_REQUEST", 400, "appointment_id has a wrong type")
    taxpayer = store.taxpayers[appt["taxpayer_id"]]
    site = store.sites[appt["site_id"]]

    # Compliance gates (tier 6), fixed sub-order: identity, then preparer certs.
    if taxpayer["identity_status"] != "VERIFIED":
        raise ApiError("ERR_IDENTITY_NOT_VERIFIED", 422,
                       "Taxpayer identity must be VERIFIED before a return opens")
    has_advanced = body.get("has_advanced_scope_items", False)
    if not certs.preparer_certified(volunteer, has_advanced):
        raise ApiError("ERR_VOLUNTEER_NOT_CERTIFIED", 403,
                       "Preparer must be ACTIVE and hold CURRENT passed "
                       "ETHICS+BASIC (+ADVANCED) certifications for season 2026")

    # Cardinality (tier 7): one return per appointment, then one in-flight
    # return per (taxpayer, site).
    for r in store.tax_returns.values():
        if r["appointment_id"] == appt["id"]:
            raise ApiError("ERR_APPOINTMENT_ALREADY_USED", 409,
                           "Appointment already originates another return")
    for r in store.tax_returns.values():
        if (r["taxpayer_id"] == appt["taxpayer_id"]
                and r["site_id"] == appt["site_id"]
                and r["status"] not in TERMINAL_STATUSES):
            raise ApiError("ERR_OPEN_RETURN_EXISTS", 409,
                           "Taxpayer already has an in-flight return at this site")

    # Cross-entity state gates (tier 9).
    if appt["status"] != "CHECKED_IN":
        raise ApiError("ERR_APPOINTMENT_NOT_CHECKED_IN", 409,
                       "Return creation requires a CHECKED_IN appointment")
    if site["status"] != "OPEN":
        raise ApiError("ERR_SITE_NOT_OPEN", 409,
                       "Return creation requires the site to be OPEN")

    ret = db.new_common({
        "appointment_id": appt["id"],
        "taxpayer_id": appt["taxpayer_id"],
        "site_id": appt["site_id"],
        "preparer_id": uid,
        "reviewer_id": None,
        "tax_year": body["tax_year"],
        "filing_status": body["filing_status"],
        "has_advanced_scope_items": has_advanced,
        "out_of_scope_flags": body.get("out_of_scope_flags", []),
        "status": "INTAKE_STARTED",
        "documents_received": [],
        "interview_confirmed": False,
        "wages_cents": 0,
        "other_income_cents": 0,
        "earned_income_cents": 0,
        "withholding_reported_cents": 0,
        "withholding_verified_cents": None,
        "qualifying_children": 0,
        "refund_method": "PAPER_CHECK",
        "final_refund_cents": None,
        "submission_count": 0,
        "first_ack_outcome": None,
        "qr_failure_count": 0,
        "reached_preparation": False,
        "transmitted_at": None,
        "referral_reason": None,
        "referral_destination": None,
        "withdrawal_reason": None,
    })
    store.tax_returns[ret["id"]] = ret
    return created(return_json(ret))


@bp.get("/tax-returns")
def list_returns():
    get_context()
    rows = list(store.tax_returns.values())
    for f in ("taxpayer_id", "site_id", "appointment_id", "preparer_id",
              "reviewer_id", "status"):
        rows = paginate.filter(rows, f)
    page = paginate(rows)
    return ok([return_json(r) for r in page], rtype="array", pagination=paginate)


@bp.get("/tax-returns/<return_id>")
def get_return(return_id):
    get_context()
    ret = require_entity(store.tax_returns, return_id)
    return ok(return_json(ret))


@bp.patch("/tax-returns/<return_id>")
def patch_return(return_id):
    uid, role, _ = get_context()
    require_roles(["Screener", "Preparer", "SiteCoordinator"])
    ret = require_entity(store.tax_returns, return_id)
    # Ownership: a Preparer edits only its own returns (PRD §3.4); Screener and
    # SiteCoordinator may edit intake fields of any return.
    if role == "Preparer" and uid != ret["preparer_id"]:
        raise ApiError("ERR_NOT_RETURN_OWNER", 403,
                       "A Preparer may edit only returns it owns")
    body = parse_body(PATCH_SCHEMA)
    # OCC (PRD §2.7).
    if body["expected_return_version"] != ret["version"]:
        raise ApiError("ERR_STALE_VERSION", 412,
                       "expected_return_version does not match the return's "
                       "current version")
    # Editability window (tier 5).
    if ret["status"] not in ("INTAKE_STARTED", "IN_PREPARATION"):
        raise ApiError("ERR_INVALID_TRANSITION", 409,
                       "Return fields are editable only while INTAKE_STARTED or "
                       "IN_PREPARATION")
    for field, value in body.items():
        if field == "expected_return_version":
            continue
        ret[field] = value
    db.touch(ret)
    return ok(return_json(ret))


def _require_fields(body, fields):
    for f in fields:
        if f not in body:
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           "Missing required field: %s" % f)


@bp.post("/tax-returns/<return_id>/state")
def transition_return(return_id):
    uid, role, volunteer = get_context()
    require_roles(["Preparer", "QualityReviewer", "SiteCoordinator"])
    ret = require_entity(store.tax_returns, return_id)
    body = parse_body(STATE_SCHEMA)
    current = ret["status"]
    target = body["to_status"]

    # Transition-level actor rules (tier 2).
    sources, actors, owner_only = TRANSITIONS[target]
    if actors and role not in actors:
        raise ApiError("ERR_FORBIDDEN_ROLE", 403,
                       "Role %s may not drive a return to %s" % (role, target))
    if owner_only and uid != ret["preparer_id"]:
        raise ApiError("ERR_NOT_RETURN_OWNER", 403,
                       "Only the return's owning Preparer may perform this step")

    # Conditional request fields (tier 4).
    if target == "QR_FAILED":
        _require_fields(body, ["review_notes"])
    elif target == "REJECTED":
        _require_fields(body, ["rejection_code", "rejection_text"])
    elif target == "REFERRED":
        _require_fields(body, ["referral_reason", "referral_destination"])
    elif target == "WITHDRAWN":
        _require_fields(body, ["withdrawal_reason"])
    elif target == "COMPLETED":
        if (body.get("disbursement_confirmed") is not True
                or body.get("taxpayer_notified") is not True):
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           "disbursement_confirmed and taxpayer_notified must "
                           "both be true")

    # State legality (tier 5).
    if current not in sources:
        raise ApiError("ERR_INVALID_TRANSITION", 409,
                       "Cannot move return from %s to %s" % (current, target))

    # Transition preconditions (tiers 6, 9, 10).
    if target == "IN_PREPARATION":
        if current == "INTAKE_STARTED":
            if not documents_complete(ret) or not ret["interview_confirmed"]:
                raise ApiError("ERR_DOCUMENTS_INCOMPLETE", 422,
                               "Document checklist is incomplete or the interview "
                               "is not confirmed")
            if out_of_scope_reasons(ret):
                raise ApiError("ERR_OUT_OF_SCOPE", 422,
                               "Return is out of VITA scope")
        elif current == "REJECTED":
            rejections = [r for r in store.efile_rejections.values()
                          if r["tax_return_id"] == ret["id"]]
            if any(r["follow_up_status"] != "RESOLVED" for r in rejections):
                raise ApiError("ERR_REJECTION_UNRESOLVED", 409,
                               "All e-file rejections must be RESOLVED before "
                               "rework")
            if ret["submission_count"] >= MAX_SUBMISSIONS:
                raise ApiError("ERR_MAX_SUBMISSIONS_REACHED", 409,
                               "Return has reached the three-submission limit")
    elif target == "PENDING_QR":
        if ret["withholding_verified_cents"] is None:
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           "withholding_verified_cents must be recorded before "
                           "submitting for review")
        if out_of_scope_reasons(ret):
            raise ApiError("ERR_OUT_OF_SCOPE", 422, "Return is out of VITA scope")
    elif target in ("QR_PASSED", "QR_FAILED"):
        if not certs.reviewer_certified(volunteer):
            raise ApiError("ERR_REVIEWER_NOT_CERTIFIED", 403,
                           "Reviewer must be ACTIVE and hold CURRENT passed "
                           "INTAKE_QR+ADVANCED certifications for season 2026")
        if uid == ret["preparer_id"]:
            raise ApiError("ERR_REVIEWER_IS_PREPARER", 422,
                           "Quality reviewer must not be the return's preparer")
    elif target == "TRANSMITTED":
        site = store.sites[ret["site_id"]]
        if site["status"] != "OPEN":
            raise ApiError("ERR_SITE_NOT_OPEN", 409,
                           "Transmission requires the site to be OPEN")
        if ret["refund_method"] == "DIRECT_DEPOSIT":
            allocations = [a for a in store.refund_allocations.values()
                           if a["tax_return_id"] == ret["id"]]
            total = sum(a["amount_cents"] for a in allocations)
            if (not 1 <= len(allocations) <= 3
                    or total != ret["final_refund_cents"]):
                raise ApiError("ERR_ALLOCATION_SUM_MISMATCH", 422,
                               "Direct-deposit allocations must number 1..3 and "
                               "sum to final_refund_cents")

    # Apply the transition and its side effects.
    ret["status"] = target
    if target == "IN_PREPARATION":
        ret["reached_preparation"] = True
    elif target == "PENDING_QR":
        ret["final_refund_cents"] = calcs.final_refund_cents(ret)
    elif target == "QR_PASSED":
        ret["reviewer_id"] = uid
    elif target == "QR_FAILED":
        ret["reviewer_id"] = uid
        ret["qr_failure_count"] += 1
    elif target == "TRANSMITTED":
        ret["submission_count"] += 1
        ret["transmitted_at"] = db.logical_dt()
    elif target == "ACCEPTED":
        if ret["first_ack_outcome"] is None:
            ret["first_ack_outcome"] = "ACCEPTED"
        _auto_savings_referral(ret)
    elif target == "REJECTED":
        if ret["first_ack_outcome"] is None:
            ret["first_ack_outcome"] = "REJECTED"
        _create_rejection(ret, body)
    elif target == "REFERRED":
        ret["referral_reason"] = body["referral_reason"]
        ret["referral_destination"] = body["referral_destination"]
        cascades.void_referrals(ret["id"])
    elif target == "WITHDRAWN":
        ret["withdrawal_reason"] = body["withdrawal_reason"]
        cascades.void_referrals(ret["id"])
    db.touch(ret)
    return ok(return_json(ret))


def _auto_savings_referral(ret):
    """Acceptance nudge (PRD §3.7): with a SAVINGS allocation present and no
    SAVINGS_ACCOUNT referral yet, create one AUTO_ON_ACCEPT / OFFERED row."""
    has_savings = any(a["tax_return_id"] == ret["id"]
                      and a["account_type"] == "SAVINGS"
                      for a in store.refund_allocations.values())
    if not has_savings:
        return
    exists = any(f["tax_return_id"] == ret["id"]
                 and f["service_type"] == "SAVINGS_ACCOUNT"
                 for f in store.financial_referrals.values())
    if exists:
        return
    ref = db.new_common({
        "tax_return_id": ret["id"],
        "service_type": "SAVINGS_ACCOUNT",
        "status": "OFFERED",
        "offered_by": None,
        "source": "AUTO_ON_ACCEPT",
    })
    store.financial_referrals[ref["id"]] = ref


def _create_rejection(ret, body):
    from datetime import timedelta
    from services.serialize import FOLLOW_UP_DUE_DAYS
    rej = db.new_common({
        "tax_return_id": ret["id"],
        "rejection_code": body["rejection_code"],
        "rejection_text": body["rejection_text"],
        "submission_number": ret["submission_count"],
        "follow_up_status": "OPEN",
        "follow_up_due_at": db.logical_dt() + timedelta(days=FOLLOW_UP_DUE_DAYS),
        "contacted_at": None,
        "resolved_at": None,
        "resolution_note": None,
    })
    store.efile_rejections[rej["id"]] = rej
    return rej
