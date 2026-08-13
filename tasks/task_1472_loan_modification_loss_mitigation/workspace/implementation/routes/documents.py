from flask import Blueprint, request

import clock
import store
from auth import ALL_ROLES, authenticate, authorize, check_borrower_ownership
from errors import (
    ERR_APPLICATION_NOT_FOUND,
    ERR_APPLICATION_STATE_INVALID,
    ERR_DOCUMENT_ALREADY_RESOLVED,
    ERR_DOCUMENT_NOT_FOUND,
    raise_err,
)
from services import (
    DOC_TYPES,
    PAY_FREQUENCIES,
    TERMINAL_APP_STATES,
    document_out,
    loan_of_application,
    recompute_application_package,
)
from util import (
    body_json,
    bump,
    get_or_404,
    list_response,
    new_record,
    opt_date,
    opt_int,
    req_date,
    req_enum,
    req_int,
    req_str,
    success_object,
)

bp = Blueprint("documents", __name__)


@bp.route("/applications/<rid>/documents", methods=["POST"])
def submit_document(rid):
    uid, role = authenticate()
    authorize(role, ["Borrower"])
    body = body_json()
    doc_type = req_enum(body, "doc_type", DOC_TYPES)

    # per-type payload fields (PRD 3.3)
    gross_per_period = None
    pay_frequency = None
    pay_period_end = None
    annual_gross = None
    ytd_net = None
    ytd_months = None
    if doc_type == "PAYSTUB":
        gross_per_period = req_int(body, "gross_per_period_cents")
        pay_frequency = req_enum(body, "pay_frequency", PAY_FREQUENCIES)
        pay_period_end = req_date(body, "pay_period_end_date")
    elif doc_type == "TAX_RETURN":
        annual_gross = req_int(body, "annual_gross_cents")
    elif doc_type == "PROFIT_LOSS":
        ytd_net = req_int(body, "ytd_net_income_cents")
        ytd_months = req_int(body, "ytd_months")
    else:
        # BANK_STATEMENT / HARDSHIP_AFFIDAVIT: no income payload required,
        # but validate any provided typed fields
        opt_int(body, "gross_per_period_cents")
        if body.get("pay_frequency") is not None:
            req_enum(body, "pay_frequency", PAY_FREQUENCIES)
        opt_date(body, "pay_period_end_date")
        opt_int(body, "annual_gross_cents")
        opt_int(body, "ytd_net_income_cents")
        opt_int(body, "ytd_months")

    app = get_or_404(store.applications, rid, ERR_APPLICATION_NOT_FOUND, "Application")
    check_borrower_ownership(uid, loan_of_application(app))

    # supersede the existing ACCEPTED same-type document, if any
    for d in store.documents.values():
        if (d["application_id"] == app["id"] and d["doc_type"] == doc_type
                and d["status"] == "ACCEPTED"):
            d["status"] = "SUPERSEDED"
            bump(d)

    rec = new_record()
    rec.update({
        "application_id": app["id"],
        "doc_type": doc_type,
        "status": "SUBMITTED",
        "gross_per_period_cents": gross_per_period,
        "pay_frequency": pay_frequency,
        "pay_period_end_date": pay_period_end,
        "annual_gross_cents": annual_gross,
        "ytd_net_income_cents": ytd_net,
        "ytd_months": ytd_months,
        "rejection_reason": None,
        "received_at": clock.now(),
    })
    store.documents[rec["id"]] = rec

    # supersession side effect: income + completeness recompute; may re-open
    # the package (COMPLETE_PACKAGE -> ACKNOWLEDGED, completed_at retained)
    recompute_application_package(app)
    return success_object(document_out(rec), 201)


@bp.route("/applications/<rid>/documents", methods=["GET"])
def list_documents(rid):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    app = get_or_404(store.applications, rid, ERR_APPLICATION_NOT_FOUND, "Application")
    records = [d for d in store.documents.values() if d["application_id"] == app["id"]]
    doc_type = request.args.get("doc_type")
    status = request.args.get("status")
    if doc_type is not None:
        records = [d for d in records if d["doc_type"] == doc_type]
    if status is not None:
        records = [d for d in records if d["status"] == status]
    return list_response(records, document_out)


@bp.route("/documents/<rid>/accept", methods=["POST"])
def accept_document(rid):
    _, role = authenticate()
    authorize(role, ["LossMitAgent"])
    doc = get_or_404(store.documents, rid, ERR_DOCUMENT_NOT_FOUND, "PackageDocument")
    if doc["status"] != "SUBMITTED":
        raise_err(ERR_DOCUMENT_ALREADY_RESOLVED,
                  "Document in %s cannot be accepted" % doc["status"])
    app = store.applications.get(doc["application_id"])
    if app is not None and app["status"] in TERMINAL_APP_STATES:
        raise_err(ERR_APPLICATION_STATE_INVALID,
                  "Parent application is terminal (%s)" % app["status"])
    doc["status"] = "ACCEPTED"
    bump(doc)
    if app is not None:
        recompute_application_package(app)
    return success_object(document_out(doc))


@bp.route("/documents/<rid>/reject", methods=["POST"])
def reject_document(rid):
    _, role = authenticate()
    authorize(role, ["LossMitAgent"])
    body = body_json()
    reason = req_str(body, "rejection_reason")
    doc = get_or_404(store.documents, rid, ERR_DOCUMENT_NOT_FOUND, "PackageDocument")
    if doc["status"] != "SUBMITTED":
        raise_err(ERR_DOCUMENT_ALREADY_RESOLVED,
                  "Document in %s cannot be rejected" % doc["status"])
    app = store.applications.get(doc["application_id"])
    if app is not None and app["status"] in TERMINAL_APP_STATES:
        raise_err(ERR_APPLICATION_STATE_INVALID,
                  "Parent application is terminal (%s)" % app["status"])
    doc["status"] = "REJECTED"
    doc["rejection_reason"] = reason
    bump(doc)
    return success_object(document_out(doc))
