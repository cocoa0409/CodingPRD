"""Unlicensed-activity investigations (PRD 3.9). Remediation is deliberately
NOT segregated: the same officer may find and later remediate."""
from flask import Blueprint, g

import serializers
from db import create, db, touch
from errors import ApiError
from middleware import ALL_ROLES, endpoint
from response import created, ok, paginated
from routes.common import filters, gate, get_or_404, get_referenced, listing, matches
from services import audit
from validators import Body, body_fk, raw_body

bp = Blueprint("investigations", __name__)

TRIGGER_REASONS = ("AUTHORITY_LAPSE", "STATE_NOT_AUTHORIZED", "SPONSORSHIP_GAP",
                   "MANUAL_REFERRAL")
FINDINGS = ("SUBSTANTIATED", "UNSUBSTANTIATED")


@bp.route("/unlicensed-activity-investigations", methods=["POST"])
@endpoint("ComplianceOfficer")
def open_investigation():
    raw = raw_body()
    loan_ref = body_fk(raw, "loan_application_id")
    loan = None
    if loan_ref is not None:
        loan = get_referenced(db.loan_applications, loan_ref)
    body = Body(raw)
    body.string("loan_application_id")
    trigger_reason = body.enum("trigger_reason", TRIGGER_REASONS)
    row = create(db.investigations, {
        # originator_id is copied from the loan, never accepted from the caller.
        "originator_id": loan["originator_id"],
        "loan_application_id": loan["id"],
        "opened_by": "MANUAL",
        "detected_at": db.clock,
        "trigger_reason": trigger_reason,
        "status": "OPEN",
        "finding_by_user_id": None,
        "restitution_cents": 0,
        "remediated_at": None,
    })
    return created(serializers.investigation(row))


@bp.route("/unlicensed-activity-investigations", methods=["GET"])
@endpoint(*ALL_ROLES)
def list_investigations():
    active = filters("originator_id", "loan_application_id", "status", "opened_by")
    rows = listing(db.investigations, lambda r: matches(r, active))
    return paginated(rows, serializers.investigation)


@bp.route("/unlicensed-activity-investigations/<row_id>", methods=["GET"])
@endpoint(*ALL_ROLES)
def get_investigation(row_id):
    row = get_or_404(db.investigations, row_id)
    return ok(serializers.investigation(row))


@bp.route("/unlicensed-activity-investigations/<row_id>/findings", methods=["POST"])
@endpoint("ComplianceOfficer")
def enter_finding(row_id):
    investigation = get_or_404(db.investigations, row_id)
    body = Body(raw_body())
    finding = body.enum("finding", FINDINGS)
    restitution_cents = body.integer("restitution_cents", minimum=0)
    gate("UnlicensedActivityInvestigation", investigation, ("OPEN",))

    # The finding and the amount must agree.
    if finding == "SUBSTANTIATED" and restitution_cents < 1:
        raise ApiError("ERR_RESTITUTION_MISMATCH")
    if finding == "UNSUBSTANTIATED" and restitution_cents != 0:
        raise ApiError("ERR_RESTITUTION_MISMATCH")

    investigation["status"] = finding
    investigation["finding_by_user_id"] = g.user_id
    investigation["restitution_cents"] = restitution_cents
    touch(investigation)
    loan = db.loan_applications.get(investigation["loan_application_id"])
    if loan is not None:
        loan["authority_flag"] = (
            "UNAUTHORIZED" if finding == "SUBSTANTIATED" else "VERIFIED")
        touch(loan)
    audit.append("UnlicensedActivityInvestigation", investigation["id"],
                 "INVESTIGATION_FINDING",
                 {"finding": finding,
                  "restitution_cents": restitution_cents,
                  "loan_application_id": investigation["loan_application_id"]})
    return ok(serializers.investigation(investigation))


@bp.route("/unlicensed-activity-investigations/<row_id>/remediate", methods=["POST"])
@endpoint("ComplianceOfficer")
def remediate(row_id):
    investigation = get_or_404(db.investigations, row_id)
    body = Body(raw_body())
    body.string("remediation_note", max_len=8000)
    gate("UnlicensedActivityInvestigation", investigation, ("SUBSTANTIATED",))
    if (investigation["restitution_cents"] or 0) < 1:
        raise ApiError("ERR_RESTITUTION_MISMATCH")
    investigation["status"] = "REMEDIATED"
    investigation["remediated_at"] = db.clock
    touch(investigation)
    loan = db.loan_applications.get(investigation["loan_application_id"])
    if loan is not None:
        loan["authority_flag"] = "VERIFIED"
        touch(loan)
    return ok(serializers.investigation(investigation))
