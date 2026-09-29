"""Fee credit applications: the cyclic review machine and the credit pool."""

from flask import Blueprint

import enums
import middleware as mw
from db import DB, CLOCK, new_row, touch
from errors import ApiError
from middleware import body, get_enum, get_int, get_number, get_str, require
from routes.common import find, listing, one, settle
from services import calc, derive

bp = Blueprint("credit_applications", __name__)

MAX_RESUBMISSIONS = 2


@bp.post("/fee-credit-applications")
def create_application():
    user_id, _role = require([mw.OWNER, mw.CLERK])
    payload = body()
    account_id = get_str(payload, "stormwater_account_id")
    requested = get_number(
        payload, "requested_credit_pct", exclusive_minimum=0, maximum=0.5000
    )
    description = get_str(payload, "bmp_description")
    expected = get_int(payload, "expected_stormwater_account_version")
    facility_id = get_str(payload, "post_construction_facility_id", required=False, default=None)

    account = find("accounts", account_id)
    facility = find("facilities", facility_id) if facility_id is not None else None
    if int(account.get("version") or 0) != expected:
        raise ApiError("ERR_ACCOUNT_VERSION_CONFLICT")

    row = new_row(
        {
            "stormwater_account_id": account["id"],
            "post_construction_facility_id": facility["id"] if facility else None,
            "requested_credit_pct": calc.num(requested, 4),
            "approved_credit_pct": None,
            "bmp_description": description,
            "status": "SUBMITTED",
            "submitted_at": CLOCK.stamp(),
            "applicant_user_id": user_id,
            "reviewed_by_user_id": None,
            "approved_at": None,
            "return_reason": None,
            "resubmission_count": 0,
            "revoked_reason": None,
            "revoked_at": None,
        }
    )
    DB.credit_applications[row["id"]] = row
    touch(account)
    settle(DB.permit_terms.get(account["permit_term_id"]))
    return one(row, 201)


@bp.get("/fee-credit-applications")
def list_applications():
    require([mw.CLERK, mw.MANAGER, mw.OWNER])
    spec = {
        "stormwater_account_id": ("stormwater_account_id", None),
        "post_construction_facility_id": ("post_construction_facility_id", None),
        "status": ("status", enums.CREDIT_STATUS),
    }
    return listing(spec, lambda: list(DB.credit_applications.values()))


@bp.get("/fee-credit-applications/<application_id>")
def read_application(application_id):
    require([mw.CLERK, mw.MANAGER, mw.OWNER])
    return one(find("credit_applications", application_id))


@bp.post("/fee-credit-applications/<application_id>/review")
def review_application(application_id):
    user_id, _role = require([mw.CLERK])
    payload = body()
    decision = get_enum(payload, "decision", enums.REVIEW_DECISION)
    approved = get_number(
        payload,
        "approved_credit_pct",
        required=False,
        default=None,
        exclusive_minimum=0,
        maximum=0.5000,
    )
    reason = get_str(payload, "return_reason", required=False, default=None, min_len=None)

    application = find("credit_applications", application_id)
    if application["status"] != "SUBMITTED":
        raise ApiError("ERR_CREDIT_APPLICATION_NOT_SUBMITTED")
    account = DB.accounts.get(application["stormwater_account_id"])

    if decision == "APPROVE":
        pct = calc.D(application["requested_credit_pct"]) if approved is None else approved
        facility = DB.facilities.get(application.get("post_construction_facility_id"))
        if facility is not None:
            derive.refresh_facility(facility)
            if not facility.get("credit_eligible"):
                raise ApiError("ERR_FACILITY_NOT_CREDIT_ELIGIBLE")
        existing = calc.D(0)
        for other in derive.applications_of_account(application["stormwater_account_id"]):
            if other["id"] != application["id"] and other["status"] == "APPROVED":
                existing += calc.D(other.get("approved_credit_pct") or 0)
        if existing + calc.D(pct) > calc.MAX_CREDIT_PCT:
            raise ApiError("ERR_CREDIT_CEILING_EXCEEDED")
        application["status"] = "APPROVED"
        application["approved_credit_pct"] = calc.num(pct, 4)
        application["approved_at"] = CLOCK.stamp()
    elif decision == "RETURN":
        application["status"] = "RETURNED"
        application["return_reason"] = reason
    else:
        application["status"] = "DENIED"
        application["return_reason"] = reason

    application["reviewed_by_user_id"] = user_id
    touch(application)
    term = DB.permit_terms.get(account["permit_term_id"]) if account else None
    settle(term)
    return one(application)


@bp.post("/fee-credit-applications/<application_id>/resubmit")
def resubmit_application(application_id):
    user_id, _role = require([mw.OWNER])
    payload = body()
    requested = get_number(
        payload, "requested_credit_pct", exclusive_minimum=0, maximum=0.5000
    )
    description = get_str(payload, "bmp_description")

    application = find("credit_applications", application_id)
    if application["status"] != "RETURNED":
        raise ApiError("ERR_CREDIT_APPLICATION_NOT_RETURNED")
    if application.get("applicant_user_id") != user_id:
        raise ApiError("ERR_NOT_APPLICANT")
    if int(application.get("resubmission_count") or 0) >= MAX_RESUBMISSIONS:
        raise ApiError("ERR_RESUBMISSION_LIMIT_REACHED")

    application["status"] = "SUBMITTED"
    application["requested_credit_pct"] = calc.num(requested, 4)
    application["bmp_description"] = description
    application["return_reason"] = None
    application["resubmission_count"] = int(application.get("resubmission_count") or 0) + 1
    touch(application)
    account = DB.accounts.get(application["stormwater_account_id"])
    settle(DB.permit_terms.get(account["permit_term_id"]) if account else None)
    return one(application)


@bp.post("/fee-credit-applications/<application_id>/revoke")
def revoke_application(application_id):
    require([mw.CLERK])
    payload = body()
    reason = get_str(payload, "reason")
    application = find("credit_applications", application_id)
    if application["status"] != "APPROVED":
        raise ApiError("ERR_CREDIT_APPLICATION_NOT_APPROVED")

    application["status"] = "REVOKED"
    application["revoked_at"] = CLOCK.stamp()
    application["revoked_reason"] = reason
    touch(application)
    account = DB.accounts.get(application["stormwater_account_id"])
    settle(DB.permit_terms.get(account["permit_term_id"]) if account else None)
    return one(application)
