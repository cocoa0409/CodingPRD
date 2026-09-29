"""Financing applications and underwriting decisions (PRD 3.8)."""

from flask import Blueprint

import auth
import calc
import derive
import errors
import validators
from envelope import created, listing, ok
from errors import fail
from helpers import collect, get_agreement, get_financing, page
from store import db, ordered

bp = Blueprint("financing", __name__)

FINANCING_STATUSES = ("SUBMITTED", "APPROVED", "DECLINED", "WITHDRAWN", "CANCELLED")
TERM_MONTHS = (60, 120, 180)


@bp.post("/financing-applications")
def create_application():
    user_id, _ = auth.require(auth.SALES_REPRESENTATIVE)
    data = validators.body()
    agreement_id = validators.identifier(data, "agreement_id")
    requested = validators.integer(data, "requested_amount_cents", 1)
    fico = validators.integer(data, "applicant_fico", 300, 850)
    term_months = validators.one_of_int(data, "term_months", TERM_MONTHS)
    expected_version = validators.integer(data, "expected_agreement_version", 1)

    agreement = get_agreement(agreement_id)
    if agreement["rep_id"] != user_id:
        fail(
            errors.ERR_REPRESENTATIVE_MISMATCH,
            "the acting representative does not own this agreement",
        )
    if agreement["version"] != expected_version:
        fail(
            errors.ERR_STALE_AGREEMENT_VERSION,
            "agreement version is %d" % agreement["version"],
        )

    superseded = [
        application
        for application in ordered(db.financings.values())
        if application["agreement_id"] == agreement["id"]
        and application["status"] in ("SUBMITTED", "APPROVED")
    ]
    if any(application["status"] == "APPROVED" for application in superseded):
        if agreement["fulfillment_status"] != "AWAITING_FUNDING":
            fail(
                errors.ERR_INVALID_AGREEMENT_STATE,
                "an approved application cannot be superseded once the agreement moved on",
            )

    now = db.now()
    application = {
        "id": db.new_id(),
        "_seq": db.next_seq(),
        "agreement_id": agreement["id"],
        "requested_amount_cents": requested,
        "applicant_fico": fico,
        "term_months": term_months,
        "status": "SUBMITTED",
        "apr_bps": None,
        "max_ltv_rate": None,
        "ltv_cap_cents": None,
        "approved_amount_cents": None,
        "monthly_payment_cents": None,
        "decided_at": None,
        "decided_by_user_id": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.financings[application["id"]] = application

    for prior in superseded:
        derive.setf(prior, "status", "WITHDRAWN")
    # A successful submission always advances the agreement's version.
    derive.touch(agreement)
    return created(application)


@bp.post("/financing-applications/<application_id>/decision")
def decide_application(application_id):
    user_id, _ = auth.require(auth.CONTRACT_ADMINISTRATOR)
    data = validators.body()
    decision = validators.enum(data, "decision", ("APPROVE", "DECLINE"))
    application = get_financing(application_id)

    if decision == "APPROVE" and application["applicant_fico"] < calc.MIN_UNDERWRITABLE_FICO:
        fail(
            errors.ERR_INVALID_REQUEST,
            "APPROVE is unavailable below a FICO of %d" % calc.MIN_UNDERWRITABLE_FICO,
        )
    if application["status"] != "SUBMITTED":
        fail(errors.ERR_INVALID_FINANCING_STATE, "application is not SUBMITTED")

    agreement = db.agreements.get(application["agreement_id"])
    if decision == "APPROVE" and agreement["rescission_status"] == "RESCINDED":
        fail(errors.ERR_INVALID_AGREEMENT_STATE, "the agreement has been rescinded")

    now = db.now()
    derive.setf(application, "decided_at", now)
    derive.setf(application, "decided_by_user_id", user_id)
    if decision == "DECLINE":
        derive.setf(application, "status", "DECLINED")
        return ok(application)

    priced = calc.financing_underwriting(application, agreement)
    derive.setf(application, "apr_bps", priced["apr_bps"])
    derive.setf(application, "max_ltv_rate", priced["max_ltv_rate"])
    derive.setf(application, "ltv_cap_cents", priced["ltv_cap_cents"])
    derive.setf(application, "approved_amount_cents", priced["approved_amount_cents"])
    derive.setf(application, "monthly_payment_cents", priced["monthly_payment_cents"])
    derive.setf(application, "status", "APPROVED")
    return ok(application)


@bp.get("/financing-applications/<application_id>")
def read_application(application_id):
    auth.require_any()
    return ok(get_financing(application_id))


@bp.get("/financing-applications")
def list_applications():
    auth.require_any()
    limit, offset = page()
    rows = collect(
        db.financings,
        (("agreement_id", "agreement_id"), ("status", "status", FINANCING_STATUSES)),
    )
    return listing(rows, limit, offset)
