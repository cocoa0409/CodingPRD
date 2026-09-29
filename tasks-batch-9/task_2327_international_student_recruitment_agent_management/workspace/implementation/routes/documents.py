"""Document reads and the verification fork-join (PRD 3.5)."""

from flask import Blueprint

import errors
import serializers
from db import db, base_record, touch, today
from errors import fail
from middleware import check_scope
from response import obj
from routes.common import auth, need
from services import calc, domain
from validation import body, fmt_date, opt_str, req_enum

bp = Blueprint("documents", __name__)

OUTCOMES = ("VERIFIED", "FLAGGED", "CLEARED", "CONFIRMED_FRAUD")
OUTCOME_SOURCE = {
    "VERIFIED": "PENDING",
    "FLAGGED": "PENDING",
    "CLEARED": "FLAGGED",
    "CONFIRMED_FRAUD": "FLAGGED",
}


def _document_agency_id(document):
    app = db.applications.get(document["application_id"])
    return app["agency_id"] if app is not None else None


@bp.route("/recruitment/documents/<document_id>", methods=["GET"])
def read_document(document_id):
    user_id, role = auth("RecruitmentOfficer", "ComplianceOfficer", "AgencyOwner")
    document = db.documents.get(document_id)
    if document is not None:
        check_scope(role, user_id, _document_agency_id(document))
    if document is None:
        fail(errors.ERR_DOCUMENT_NOT_FOUND, "Document not found")
    return obj(serializers.document(document))


@bp.route("/recruitment/documents/<document_id>/verification", methods=["POST"])
def verify_document(document_id):
    user_id, _role = auth("ComplianceOfficer")
    data = body()
    outcome = req_enum(data, "outcome", OUTCOMES)
    opt_str(data, "note")
    document = need(db.documents, document_id, errors.ERR_DOCUMENT_NOT_FOUND)

    if document["verification_state"] != OUTCOME_SOURCE[outcome]:
        fail(errors.ERR_INVALID_DOCUMENT_STATE,
             "Outcome %s is not defined from verification_state %s"
             % (outcome, document["verification_state"]))
    if outcome == "VERIFIED" and document["fraud_index"] >= calc.FLAG_THRESHOLD:
        fail(errors.ERR_INVALID_DOCUMENT_STATE,
             "A document with fraud_index >= 60 cannot be verified in one step")

    app = db.applications.get(document["application_id"])
    agency = db.agencies.get(app["agency_id"]) if app is not None else None

    document["verification_state"] = outcome
    document["verified_by_user_id"] = user_id
    touch(document)

    if outcome == "VERIFIED":
        if agency is not None:
            domain.recompute_risk(agency)
    elif outcome == "FLAGGED":
        if app is not None:
            domain.commit(app, {"integrity_hold": True})
        if agency is not None:
            domain.recompute_risk(agency)
    elif outcome == "CLEARED":
        if app is not None:
            domain.refresh_integrity_hold(app)
        if agency is not None:
            domain.recompute_risk(agency)
    else:
        _confirmed_fraud_cascade(document, app, agency)
    return obj(serializers.document(document))


def _confirmed_fraud_cascade(document, app, agency):
    """Hops 2..5 of the deepest cascade in the system."""
    incident = base_record()
    incident.update({
        "agency_id": app["agency_id"] if app is not None else None,
        "application_id": document["application_id"],
        "document_id": document["id"],
        "category": "DOCUMENT_FRAUD",
        "severity": "HIGH",
        "occurred_on": fmt_date(today()),
        "source": "DOCUMENT_REVIEW",
        "status": "CONFIRMED",
        "resolved_by_user_id": None,
    })
    db.incidents[incident["id"]] = incident

    if agency is not None:
        domain.recompute_risk(agency)
    if app is not None and not app["integrity_hold"]:
        domain.commit(app, {"integrity_hold": True})
