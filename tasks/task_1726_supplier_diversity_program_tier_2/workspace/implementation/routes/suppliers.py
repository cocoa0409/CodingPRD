"""Suppliers: registration, lifecycle (suspend/reinstate), nested certification
submission and listing (PRD 3.1, 3.2)."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error,
    ERR_DUPLICATE_TAX_ID,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_AUDIT_COOLING_OFF,
)
from middleware import authorized
from response import success_object
from routes.helpers import list_response
from services.core import (
    SUPPLIER_KINDS,
    CERT_TYPES,
    make_record,
    touch,
    pub_supplier,
    pub_certification,
    refresh_diverse_eligible,
    suspend_supplier_cascade,
    recompute_events_for_supplier,
    supplier_audits,
)
from util import clock_date
from validate import get_body, req_str, req_enum, req_date, get_resource

bp = Blueprint("suppliers", __name__)

ADMIN_ANALYST = ["DiversityAdmin", "DiversityAnalyst"]
ALL_READ = ["DiversityAdmin", "DiversityAnalyst", "BusinessUnitLead", "Auditor", "PrimeContact"]


@bp.route("/api/v1/suppliers", methods=["POST"])
def create_supplier():
    authorized(ADMIN_ANALYST)
    body = get_body()
    legal_name = req_str(body, "legal_name")
    tax_id = req_str(body, "tax_id")
    for existing in db["suppliers"].values():
        if existing["tax_id"] == tax_id:
            raise_error(ERR_DUPLICATE_TAX_ID, f"tax_id already registered: {tax_id}")
    kind = req_enum(body, "kind", SUPPLIER_KINDS)
    contact_email = req_str(body, "contact_email")
    rec = make_record({
        "legal_name": legal_name,
        "tax_id": tax_id,
        "kind": kind,
        "contact_email": contact_email,
        "status": "REGISTERED",
        "diverse_eligible": False,
        "risk_score_standard": 0,
        "risk_score_conservative": 0,
    })
    db["suppliers"][rec["id"]] = rec
    return success_object(pub_supplier(rec), status=201)


@bp.route("/api/v1/suppliers/<rid>", methods=["GET"])
def get_supplier(rid):
    authorized(ALL_READ)
    rec = get_resource("suppliers", rid)
    return success_object(pub_supplier(rec))


@bp.route("/api/v1/suppliers/<rid>/suspend", methods=["POST"])
def suspend_supplier(rid):
    authorized(["DiversityAdmin"])
    supplier = get_resource("suppliers", rid)
    if supplier["status"] != "ACTIVE":
        raise_error(ERR_INVALID_STATE, "only an ACTIVE supplier can be suspended")
    suspend_supplier_cascade(supplier)
    return success_object(pub_supplier(supplier))


@bp.route("/api/v1/suppliers/<rid>/reinstate", methods=["POST"])
def reinstate_supplier(rid):
    authorized(["DiversityAdmin"])
    supplier = get_resource("suppliers", rid)
    if supplier["status"] != "SUSPENDED":
        raise_error(ERR_INVALID_STATE, "only a SUSPENDED supplier can be reinstated")
    # Blocked while any audit case for the supplier is OPEN (PRD 3.1)
    if any(a["status"] == "OPEN" for a in supplier_audits(supplier["id"])):
        raise_error(ERR_INVALID_STATE, "supplier has an OPEN audit case")
    supplier["status"] = "ACTIVE"
    changed = True
    if refresh_diverse_eligible(supplier):
        recompute_events_for_supplier(supplier["id"])
    if changed:
        touch(supplier)
    return success_object(pub_supplier(supplier))


# ---------------------------------------------------------------------------
# Certifications of a supplier (nested)
# ---------------------------------------------------------------------------

@bp.route("/api/v1/suppliers/<rid>/certifications", methods=["POST"])
def create_certification(rid):
    caller = authorized(ADMIN_ANALYST)
    supplier = get_resource("suppliers", rid)
    body = get_body()
    cert_type = req_enum(body, "cert_type", CERT_TYPES)
    # Supplier-level guard on submission (PRD 3.2): SELF_CERT within 90 days
    # of a FAILED audit outcome -> cooling-off rejection.
    if cert_type == "SELF_CERT":
        today = clock_date()
        for case in supplier_audits(supplier["id"]):
            if case["status"] != "FAILED" or case["outcome_recorded_at"] is None:
                continue
            days = (today - case["outcome_recorded_at"].date()).days
            if days < 90:
                raise_error(
                    ERR_AUDIT_COOLING_OFF,
                    "SELF_CERT submission within 90 days of a FAILED audit outcome",
                )
    certifying_body = req_str(body, "certifying_body")
    certificate_number = req_str(body, "certificate_number")
    valid_from = req_date(body, "valid_from")
    valid_to = req_date(body, "valid_to")
    if cert_type == "SELF_CERT" and certifying_body != "SELF":
        raise_error(ERR_INVALID_REQUEST, "certifying_body must be 'SELF' for SELF_CERT")
    if valid_to < valid_from:
        raise_error(ERR_INVALID_REQUEST, "valid_to must be on or after valid_from")
    rec = make_record({
        "supplier_id": supplier["id"],
        "cert_type": cert_type,
        "certifying_body": certifying_body,
        "certificate_number": certificate_number,
        "valid_from": valid_from,
        "valid_to": valid_to,
        "status": "SUBMITTED",
        "submitted_by_user_id": caller.user_id,
        "verified_by_user_id": None,
        "review_note": None,
    })
    db["certifications"][rec["id"]] = rec
    return success_object(pub_certification(rec), status=201)


@bp.route("/api/v1/suppliers/<rid>/certifications", methods=["GET"])
def list_certifications(rid):
    authorized(ALL_READ)
    supplier = get_resource("suppliers", rid)
    filters = {
        "status": request.args.get("status"),
        "cert_type": request.args.get("cert_type"),
    }
    records = [c for c in db["certifications"].values() if c["supplier_id"] == supplier["id"]]
    return list_response(records, filters, pub_certification)
