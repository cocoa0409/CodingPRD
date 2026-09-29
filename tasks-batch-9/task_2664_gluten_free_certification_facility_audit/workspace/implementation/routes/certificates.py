"""Certificate issuance, suspension, reinstatement, revocation and reads."""

from flask import Blueprint

import clock
import db
import middleware as mw
import query
import response
from constants import (
    CERTIFICATE_TERM_DAYS,
    FEE_REFUND_WINDOW_DAYS,
    NC_OPEN_STATUSES,
    READ_CERTIFICATES,
    REVOCATION_REASONS,
    ROLE_DECISION_MAKER,
    SURVEILLANCE_INTERVAL_DAYS,
    SUSPENSION_REASONS,
)
from errors import ApiError
from services import calc, derive

bp = Blueprint("certificates", __name__)


def _facility_audit_critical_open(product):
    for nc in db.nonconformances.values():
        if nc["applicant_id"] != product["applicant_id"]:
            continue
        if not nc.get("audit_id"):
            continue
        audit = db.audits.get(nc["audit_id"])
        if audit is None or audit["facility_id"] != product["facility_id"]:
            continue
        if nc["severity"] == "CRITICAL" and nc["status"] in NC_OPEN_STATUSES:
            return True
    return False


@bp.post("/gfco/certificates")
def issue_certificate():
    user_id, _ = mw.authenticate([ROLE_DECISION_MAKER])
    data = mw.body()
    product_id = mw.req_str(data, "product_id")
    expected_version = mw.req_int(data, "expected_product_version")
    product = query.fetch("product", product_id)

    if expected_version != product["version"]:
        raise ApiError("ERR_STALE_PRODUCT_VERSION")

    facility = db.facilities.get(product["facility_id"])
    if facility is None \
            or facility["sanitation_validation_status"] != "VALIDATED":
        raise ApiError("ERR_FACILITY_SANITATION_NOT_VALIDATED")
    if facility["last_closed_audit_outcome"] not in (
        "CLOSED_PASS",
        "CLOSED_CONDITIONAL",
    ):
        raise ApiError("ERR_FACILITY_AUDIT_NOT_PASSED")
    if _facility_audit_critical_open(product):
        raise ApiError("ERR_OPEN_CRITICAL_NONCONFORMANCE")

    lines = derive.lines_for_product(product["id"])
    if any(ingredient["status"] != "APPROVED" for ingredient, _ in lines):
        raise ApiError("ERR_INGREDIENT_NOT_APPROVED")
    if product["testing_plan_status"] != "ACTIVE":
        raise ApiError("ERR_TESTING_PLAN_NOT_ACTIVE")
    if product["label_status"] != "APPROVED":
        raise ApiError("ERR_LABEL_NOT_APPROVED")
    if product["mark_tier_granted"] == "NONE" \
            or product["mark_tier_granted"] != product["requested_mark_tier"]:
        raise ApiError("ERR_MARK_TIER_NOT_GRANTED")

    latest_audit = derive.latest_closed_audit_for_facility(facility["id"])
    if user_id == product["formula_cleared_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    if latest_audit is not None and user_id == latest_audit["closed_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    for existing in derive.certificates_for_product(product["id"]):
        if existing["status"] in ("ISSUED", "SUSPENDED"):
            raise ApiError("ERR_DUPLICATE_ACTIVE_CERTIFICATE")

    applicant = db.applicants.get(product["applicant_id"])
    if applicant is not None and applicant["compliance_posture"] in (
        "PROBATION",
        "SUSPENDED",
    ):
        raise ApiError("ERR_APPLICANT_POSTURE_BLOCKED")

    derive.recompute_product_counts(product)
    base, surcharge, total = calc.certification_fee(
        product["linked_ingredient_count"], facility["shared_equipment_present"]
    )
    now = clock.now()
    row = db.insert(
        db.certificates,
        {
            "product_id": product["id"],
            "applicant_id": product["applicant_id"],
            "mark_tier_granted": product["mark_tier_granted"],
            "certified_threshold_ppm": product["threshold_ppm"],
            "status": "ISSUED",
            "surveillance_status": "CURRENT",
            "issued_on": now,
            "issued_by_user_id": user_id,
            "expires_on": clock.add_days(now, CERTIFICATE_TERM_DAYS),
            "surveillance_due_on": clock.add_days(now, SURVEILLANCE_INTERVAL_DAYS),
            "suspension_count": 0,
            "suspended_on": None,
            "suspension_reason": None,
            "revoked_on": None,
            "revocation_reason": None,
            "base_fee_cents": base,
            "surveillance_surcharge_cents": surcharge,
            "total_fee_cents": total,
            "fee_charged": True,
            "fee_refunded": False,
            "mark_usage_locked": False,
        },
    )
    db.touch(product)
    if applicant is not None:
        derive.recompute_applicant(applicant)
    return response.created(response.serialize(row))


@bp.get("/gfco/certificates/<certificate_id>")
def get_certificate(certificate_id):
    mw.authenticate(READ_CERTIFICATES)
    return response.ok(response.serialize(query.fetch("certificate", certificate_id)))


@bp.get("/gfco/certificates")
def list_certificates():
    mw.authenticate(READ_CERTIFICATES)
    return query.listing(
        db.certificates,
        {
            "product_id": query.arg("product_id"),
            "applicant_id": query.arg("applicant_id"),
            "status": query.arg("status"),
            "surveillance_status": query.arg("surveillance_status"),
        },
    )


@bp.post("/gfco/certificates/<certificate_id>/suspension")
def suspend(certificate_id):
    mw.authenticate([ROLE_DECISION_MAKER])
    data = mw.body()
    reason = mw.req_enum(data, "suspension_reason", SUSPENSION_REASONS)
    cert = query.fetch("certificate", certificate_id)
    if cert["status"] != "ISSUED":
        raise ApiError("ERR_CERTIFICATE_TERMINAL")
    derive.suspend_certificate(cert, reason)
    return response.ok(response.serialize(cert))


@bp.post("/gfco/certificates/<certificate_id>/reinstatement")
def reinstate(certificate_id):
    mw.authenticate([ROLE_DECISION_MAKER])
    mw.body()
    cert = query.fetch("certificate", certificate_id)

    if cert["status"] != "SUSPENDED":
        raise ApiError("ERR_CERTIFICATE_NOT_SUSPENDED")

    product = db.products.get(cert["product_id"])
    facility = db.facilities.get(product["facility_id"]) if product else None
    if facility is None \
            or facility["sanitation_validation_status"] != "VALIDATED":
        raise ApiError("ERR_FACILITY_SANITATION_NOT_VALIDATED")
    if derive.has_open_critical(
        derive.nonconformances_for_certificate(cert["id"])
    ):
        raise ApiError("ERR_OPEN_CRITICAL_NONCONFORMANCE")
    applicant = db.applicants.get(cert["applicant_id"])
    if applicant is not None and applicant["compliance_posture"] in (
        "PROBATION",
        "SUSPENDED",
    ):
        raise ApiError("ERR_APPLICANT_POSTURE_BLOCKED")
    if product is None or product["formula_status"] != "CLEARED":
        raise ApiError("ERR_INVALID_PRODUCT_STATE")
    if cert["surveillance_status"] == "OVERDUE":
        raise ApiError("ERR_INVALID_PRODUCT_STATE")

    cert["status"] = "ISSUED"
    cert["suspended_on"] = None
    cert["suspension_reason"] = None
    cert["mark_usage_locked"] = False
    db.touch(cert)
    if product["label_status"] == "FROZEN":
        product["label_status"] = "APPROVED"
        db.touch(product)
    if applicant is not None:
        derive.recompute_applicant(applicant)
    return response.ok(response.serialize(cert))


@bp.post("/gfco/certificates/<certificate_id>/revocation")
def revoke(certificate_id):
    mw.authenticate([ROLE_DECISION_MAKER])
    data = mw.body()
    reason = mw.req_enum(data, "revocation_reason", REVOCATION_REASONS)
    cert = query.fetch("certificate", certificate_id)
    if cert["status"] in ("REVOKED", "EXPIRED"):
        raise ApiError("ERR_CERTIFICATE_TERMINAL")

    now = clock.now()
    cert["status"] = "REVOKED"
    cert["revoked_on"] = now
    cert["revocation_reason"] = reason
    cert["mark_usage_locked"] = True
    if _refund_due(cert, reason, now):
        cert["fee_refunded"] = True
    db.touch(cert)

    product = db.products.get(cert["product_id"])
    if product is not None and product["label_status"] == "APPROVED":
        product["label_status"] = "FROZEN"
        db.touch(product)
    applicant = db.applicants.get(cert["applicant_id"])
    if applicant is not None:
        derive.recompute_applicant(applicant)
    return response.ok(response.serialize(cert))


def _refund_due(cert, reason, now):
    if reason != "VOLUNTARY_WITHDRAWAL":
        return False
    if now > clock.add_days(cert["issued_on"], FEE_REFUND_WINDOW_DAYS):
        return False
    for lot_test in db.lot_tests.values():
        if lot_test["product_id"] == cert["product_id"] \
                and lot_test["test_type"] == "UNANNOUNCED":
            return False
    return True
