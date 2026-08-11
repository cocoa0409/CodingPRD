"""Routes: logical clock, daily sweep, reps, customers, CIP documents,
beneficial ownership certifications and owners."""

from datetime import date, timedelta
from decimal import Decimal

from flask import Blueprint, g

from db import store, new_record, bump, serialize, fmt_ts
from errors import ApiError
from services import (
    owners_of_certification, recompute_posture, accounts_of_customer,
    run_sweep, to_dec,
)
from util import (
    endpoint, ok_object, list_response, field, MISSING, require_fields,
    check_enum, get_or_404, parse_date, parse_iso_datetime, is_bool, is_num,
    is_nonempty_str, ALL_ROLES,
)

bp = Blueprint("core", __name__)

CUSTOMER_TYPES = {"INDIVIDUAL", "LEGAL_ENTITY"}
COUNTRY_TIERS = {"LOW", "MEDIUM", "HIGH", "PROHIBITED"}
DOC_TYPES = {"GOVERNMENT_ID", "FORMATION_DOC", "PROOF_OF_ADDRESS", "W9"}
DOC_STATUSES = {"SUBMITTED", "VERIFIED", "REJECTED", "EXPIRED", "SUPERSEDED"}
CERT_STATUSES = {"DRAFT", "CERTIFIED", "SUPERSEDED"}


def _current_rep_active():
    """Actor-entity state gate (priority 5) for rep-driven creations."""
    rep = store.reps.get(g.user_id)
    if rep is None:
        raise ApiError("ERR_REP_NOT_FOUND", 404, "RegisteredRep %s does not exist" % g.user_id)
    if rep["status"] != "ACTIVE":
        raise ApiError("ERR_REP_SUSPENDED", 409,
                       "Suspended reps cannot create customers, accounts, documents, or certifications")
    return rep


# ---------------------------------------------------------------------------
# Logical clock & sweep
# ---------------------------------------------------------------------------

@bp.post("/aml/_clock/set_current_utc")
@endpoint(["SystemAdmin"])
def set_clock():
    v = field("to_iso8601")
    dt = parse_iso_datetime(v)
    if dt is None:
        raise ApiError("ERR_INVALID_REQUEST", 400, "to_iso8601 must be a valid ISO 8601 instant")
    store.clock = dt
    return ok_object({"current_utc": fmt_ts(store.clock)})


@bp.post("/aml/maintenance/run-daily-sweep")
@endpoint(["SystemAdmin"])
def daily_sweep():
    counts = run_sweep()
    return ok_object(counts)


# ---------------------------------------------------------------------------
# Registered reps
# ---------------------------------------------------------------------------

@bp.post("/aml/reps")
@endpoint(["SystemAdmin"])
def create_rep():
    crd = field("crd_number")
    if isinstance(crd, str) and any(r["crd_number"] == crd for r in store.reps.values()):
        raise ApiError("ERR_DUPLICATE_CRD_NUMBER", 409, "crd_number already registered")
    require_fields([("full_name", "nstr", True), ("crd_number", "nstr", True)])
    rec = new_record()
    rec.update({"full_name": field("full_name"), "crd_number": crd, "status": "ACTIVE"})
    store.reps[rec["id"]] = rec
    return ok_object(serialize(rec), 201)


@bp.get("/aml/reps")
@endpoint(ALL_ROLES)
def list_reps():
    return list_response(
        list(store.reps.values()),
        {"status": __import__("flask").request.args.get("status")},
        enum_filters=[("status", {"ACTIVE", "SUSPENDED"})],
    )


@bp.get("/aml/reps/<rid>")
@endpoint(ALL_ROLES)
def get_rep(rid):
    return ok_object(serialize(get_or_404("reps", rid, "ERR_REP_NOT_FOUND")))


@bp.post("/aml/reps/<rid>/suspend")
@endpoint(["SystemAdmin"])
def suspend_rep(rid):
    rep = get_or_404("reps", rid, "ERR_REP_NOT_FOUND")
    if rep["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_LIFECYCLE_TRANSITION", 409, "Rep must be ACTIVE to suspend")
    rep["status"] = "SUSPENDED"
    bump(rep)
    return ok_object(serialize(rep))


@bp.post("/aml/reps/<rid>/reinstate")
@endpoint(["SystemAdmin"])
def reinstate_rep(rid):
    rep = get_or_404("reps", rid, "ERR_REP_NOT_FOUND")
    if rep["status"] != "SUSPENDED":
        raise ApiError("ERR_INVALID_LIFECYCLE_TRANSITION", 409, "Rep must be SUSPENDED to reinstate")
    rep["status"] = "ACTIVE"
    bump(rep)
    return ok_object(serialize(rep))


# ---------------------------------------------------------------------------
# Customers
# ---------------------------------------------------------------------------

@bp.post("/aml/customers")
@endpoint(["RegisteredRep"])
def create_customer():
    _current_rep_active()
    ct = check_enum("customer_type", CUSTOMER_TYPES)
    crt = check_enum("country_risk_tier", COUNTRY_TIERS)
    require_fields([
        ("customer_type", "str", True),
        ("full_name", "nstr", True),
        ("tax_id", "nstr", True),
        ("country_risk_tier", "str", True),
        ("is_pep", "bool", False),
        ("date_of_birth", "date", False),
    ])
    rec = new_record()
    rec.update({
        "registered_rep_id": g.user_id,
        "customer_type": ct,
        "full_name": field("full_name"),
        "tax_id": field("tax_id"),
        "country_risk_tier": crt,
        "is_pep": field("is_pep") if field("is_pep") is not MISSING else False,
        "date_of_birth": field("date_of_birth") if field("date_of_birth") is not MISSING else None,
    })
    store.customers[rec["id"]] = rec
    return ok_object(serialize(rec), 201)


@bp.get("/aml/customers")
@endpoint(ALL_ROLES)
def list_customers():
    from flask import request
    return list_response(
        list(store.customers.values()),
        {
            "registered_rep_id": request.args.get("registered_rep_id"),
            "tax_id": request.args.get("tax_id"),
            "customer_type": request.args.get("customer_type"),
        },
        enum_filters=[("customer_type", CUSTOMER_TYPES)],
    )


@bp.get("/aml/customers/<cid>")
@endpoint(ALL_ROLES)
def get_customer(cid):
    return ok_object(serialize(get_or_404("customers", cid, "ERR_CUSTOMER_NOT_FOUND")))


# ---------------------------------------------------------------------------
# Identification documents
# ---------------------------------------------------------------------------

@bp.post("/aml/customers/<customerId>/identification-documents")
@endpoint(["RegisteredRep"])
def create_document(customerId):
    customer = get_or_404("customers", customerId, "ERR_CUSTOMER_NOT_FOUND")
    _current_rep_active()
    dt = check_enum("doc_type", DOC_TYPES)
    require_fields([
        ("doc_type", "str", True),
        ("document_number", "nstr", True),
        ("expiry_date", "date", True),
    ])
    rec = new_record()
    rec.update({
        "customer_id": customer["id"],
        "doc_type": dt,
        "document_number": field("document_number"),
        "expiry_date": field("expiry_date"),
        "status": "SUBMITTED",
        "rejection_reason": None,
    })
    store.documents[rec["id"]] = rec
    return ok_object(serialize(rec), 201)


@bp.get("/aml/identification-documents")
@endpoint(ALL_ROLES)
def list_documents():
    from flask import request
    return list_response(
        list(store.documents.values()),
        {
            "customer_id": request.args.get("customer_id"),
            "status": request.args.get("status"),
            "doc_type": request.args.get("doc_type"),
        },
        enum_filters=[("status", DOC_STATUSES), ("doc_type", DOC_TYPES)],
    )


@bp.get("/aml/identification-documents/<did>")
@endpoint(ALL_ROLES)
def get_document(did):
    return ok_object(serialize(get_or_404("documents", did, "ERR_DOCUMENT_NOT_FOUND")))


@bp.post("/aml/identification-documents/<did>/verify")
@endpoint(["AMLAnalyst"])
def verify_document(did):
    doc = get_or_404("documents", did, "ERR_DOCUMENT_NOT_FOUND")
    if doc["status"] != "SUBMITTED":
        raise ApiError("ERR_DOCUMENT_NOT_VERIFIABLE", 409, "Document must be SUBMITTED to verify")
    # Supersede same-customer + same-type docs in VERIFIED or EXPIRED
    for other in store.documents.values():
        if other["id"] != doc["id"] and other["customer_id"] == doc["customer_id"] \
                and other["doc_type"] == doc["doc_type"] \
                and other["status"] in ("VERIFIED", "EXPIRED"):
            other["status"] = "SUPERSEDED"
            bump(other)
    doc["status"] = "VERIFIED"
    bump(doc)
    for acc in accounts_of_customer(doc["customer_id"]):
        recompute_posture(acc)
    return ok_object(serialize(doc))


@bp.post("/aml/identification-documents/<did>/reject")
@endpoint(["AMLAnalyst"])
def reject_document(did):
    doc = get_or_404("documents", did, "ERR_DOCUMENT_NOT_FOUND")
    if doc["status"] != "SUBMITTED":
        raise ApiError("ERR_DOCUMENT_NOT_REJECTABLE", 409, "Document must be SUBMITTED to reject")
    require_fields([("reason", "nstr", True)])
    doc["status"] = "REJECTED"
    doc["rejection_reason"] = field("reason")
    bump(doc)
    return ok_object(serialize(doc))


# ---------------------------------------------------------------------------
# Beneficial ownership certifications
# ---------------------------------------------------------------------------

@bp.post("/aml/customers/<customerId>/beneficial-ownership-certifications")
@endpoint(["RegisteredRep"])
def create_certification(customerId):
    customer = get_or_404("customers", customerId, "ERR_CUSTOMER_NOT_FOUND")
    _current_rep_active()
    if customer["customer_type"] != "LEGAL_ENTITY":
        raise ApiError("ERR_CERTIFICATION_REQUIRES_LEGAL_ENTITY", 400,
                       "Beneficial ownership certification requires a LEGAL_ENTITY customer")
    require_fields([("no_25pct_owner_attested", "bool", False)])
    rec = new_record()
    att = field("no_25pct_owner_attested")
    rec.update({
        "customer_id": customer["id"],
        "no_25pct_owner_attested": att if att is not MISSING else False,
        "status": "DRAFT",
        "certified_at": None,
        "total_ownership_pct": Decimal("0"),
        "covered_owner_count": 0,
    })
    store.certifications[rec["id"]] = rec
    return ok_object(serialize(rec), 201)


@bp.get("/aml/beneficial-ownership-certifications")
@endpoint(ALL_ROLES)
def list_certifications():
    from flask import request
    return list_response(
        list(store.certifications.values()),
        {"customer_id": request.args.get("customer_id"),
         "status": request.args.get("status")},
        enum_filters=[("status", CERT_STATUSES)],
    )


@bp.get("/aml/beneficial-ownership-certifications/<cid>")
@endpoint(ALL_ROLES)
def get_certification(cid):
    return ok_object(serialize(get_or_404("certifications", cid, "ERR_CERTIFICATION_NOT_FOUND")))


@bp.post("/aml/beneficial-ownership-certifications/<certId>/owners")
@endpoint(["RegisteredRep"])
def add_owner(certId):
    cert = get_or_404("certifications", certId, "ERR_CERTIFICATION_NOT_FOUND")
    if cert["status"] != "DRAFT":
        raise ApiError("ERR_CERTIFICATION_NOT_DRAFT", 409,
                       "Owners can only be added while the certification is DRAFT")
    pct = field("ownership_pct")
    if is_num(pct):
        p = to_dec(pct)
        if p <= 0 or p > Decimal("100"):
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           "ownership_pct must be greater than 0 and at most 100")
    require_fields([
        ("full_name", "nstr", True),
        ("ownership_pct", "num", True),
        ("is_control_person", "bool", False),
        ("is_entity_owner", "bool", False),
        ("tax_id", "str", False),
        ("date_of_birth", "date", False),
        ("address", "str", False),
    ])
    rec = new_record()
    cp = field("is_control_person")
    eo = field("is_entity_owner")
    rec.update({
        "certification_id": cert["id"],
        "full_name": field("full_name"),
        "ownership_pct": to_dec(pct),
        "is_control_person": cp if cp is not MISSING else False,
        "is_entity_owner": eo if eo is not MISSING else False,
        "tax_id": field("tax_id") if field("tax_id") is not MISSING else None,
        "date_of_birth": field("date_of_birth") if field("date_of_birth") is not MISSING else None,
        "address": field("address") if field("address") is not MISSING else None,
    })
    store.owners[rec["id"]] = rec
    # recompute certification total
    total = Decimal("0")
    for o in owners_of_certification(cert["id"]):
        total += o["ownership_pct"]
    cert["total_ownership_pct"] = total
    bump(cert)
    return ok_object(serialize(rec), 201)


@bp.get("/aml/beneficial-owners")
@endpoint(ALL_ROLES)
def list_owners():
    from flask import request
    return list_response(
        list(store.owners.values()),
        {"certification_id": request.args.get("certification_id")},
    )


@bp.get("/aml/beneficial-owners/<oid>")
@endpoint(ALL_ROLES)
def get_owner(oid):
    return ok_object(serialize(get_or_404("owners", oid, "ERR_OWNER_NOT_FOUND")))


COVERAGE_THRESHOLD = Decimal("25.00")


@bp.post("/aml/beneficial-ownership-certifications/<cid>/certify")
@endpoint(["ComplianceOfficer"])
def certify(cid):
    cert = get_or_404("certifications", cid, "ERR_CERTIFICATION_NOT_FOUND")
    if cert["status"] != "DRAFT":
        raise ApiError("ERR_CERTIFICATION_NOT_DRAFT", 409, "Certification must be DRAFT to certify")
    owners = owners_of_certification(cid)
    total = Decimal("0")
    for o in owners:
        total += o["ownership_pct"]
    if total > Decimal("100.0"):
        raise ApiError("ERR_EXCESSIVE_OWNERSHIP_TOTAL", 422,
                       "total_ownership_pct exceeds 100.0")
    if not any(o["is_control_person"] for o in owners):
        raise ApiError("ERR_CONTROL_PERSON_REQUIRED", 422,
                       "At least one control person is required")
    covered = [o for o in owners if o["ownership_pct"] >= COVERAGE_THRESHOLD]
    for o in covered:
        if not o.get("tax_id") or not o.get("date_of_birth") or not o.get("address"):
            raise ApiError("ERR_OWNER_KYC_REQUIRED", 422,
                           "Covered owners (>= 25.00%) must have tax_id, date_of_birth, and address")
    if len(covered) < 1 and not cert.get("no_25pct_owner_attested"):
        raise ApiError("ERR_OWNER_KYC_REQUIRED", 422,
                       "At least one covered owner or a no-25%-owner attestation is required")
    from db import now_iso
    cert["status"] = "CERTIFIED"
    cert["certified_at"] = now_iso()
    cert["total_ownership_pct"] = total
    cert["covered_owner_count"] = len(covered)
    bump(cert)
    for other in store.certifications.values():
        if other["id"] != cert["id"] and other["customer_id"] == cert["customer_id"] \
                and other["status"] == "CERTIFIED":
            other["status"] = "SUPERSEDED"
            bump(other)
    return ok_object(serialize(cert))
