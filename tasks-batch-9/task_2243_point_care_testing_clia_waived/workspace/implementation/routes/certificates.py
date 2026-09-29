"""Certificates and certificate coverage (PRD 3.1)."""

from flask import Blueprint

import clock
import db
import errors
import response
import serializers
import valid
from middleware import route
from services import calc, derive

bp = Blueprint("certificates", __name__)

ALL_ROLES = ("ProgramAdmin", "LabDirector", "QualityCoordinator", "Surveyor",
             "Operator")
NON_OPERATOR = ("ProgramAdmin", "LabDirector", "QualityCoordinator", "Surveyor")

CERTIFICATE_TYPES = ("CERTIFICATE_OF_WAIVER", "CERTIFICATE_OF_COMPLIANCE",
                     "CERTIFICATE_OF_ACCREDITATION")
COMPLEXITIES = ("WAIVED", "MODERATE")


@route(bp, "/certificates", ["POST"], ["ProgramAdmin"])
def create_certificate(user_id, role):
    payload = valid.body()
    # Rank 20 — request shape.
    number = valid.req_str(payload, "certificate_number")
    cert_type = valid.req_enum(payload, "certificate_type", CERTIFICATE_TYPES)
    complexity = valid.req_enum(payload, "permitted_complexity", COMPLEXITIES)
    effective = valid.req_date(payload, "effective_date")
    expiration = valid.req_date(payload, "expiration_date")
    if expiration <= effective:
        raise errors.invalid_request(
            "expiration_date must fall strictly after effective_date.")
    if expiration <= clock.today():
        raise errors.invalid_request(
            "expiration_date must fall strictly after the current logical date.")
    if cert_type == "CERTIFICATE_OF_WAIVER" and complexity != "WAIVED":
        raise errors.invalid_request(
            "A waiver certificate must have permitted_complexity WAIVED.")
    if any(c["certificate_number"] == number
           for c in db.data["certificates"].values()):
        raise errors.invalid_request("certificate_number must be unique.")

    row = db.insert("certificates", {
        "certificate_number": number,
        "certificate_type": cert_type,
        "permitted_complexity": complexity,
        "effective_date": effective.isoformat(),
        "expiration_date": expiration.isoformat(),
        "status": "ACTIVE",
        "suspension_reason": None,
        "covered_site_count": 0,
    })
    return response.object_response(serializers.dump("certificates", row), 201)


@route(bp, "/certificates/<cid>", ["GET"], ALL_ROLES)
def read_certificate(user_id, role, cid):
    row = valid.resolve("certificates", cid)
    return response.object_response(serializers.dump("certificates", row))


@route(bp, "/certificates/<cid>/suspend", ["POST"], ["ProgramAdmin"])
def suspend_certificate(user_id, role, cid):
    row = valid.resolve("certificates", cid)
    payload = valid.body()
    reason = valid.req_str(payload, "reason")
    # Rank 40.
    if row["status"] != "ACTIVE":
        raise errors.ApiError("ERR_CERTIFICATE_NOT_ACTIVE", 409)

    snap = db.snapshot(row)
    row["status"] = "SUSPENDED"
    row["suspension_reason"] = reason
    db.touch_if_changed(row, snap)

    derive.cascade_certificate_withdrawal(row, "SITE_SUSPENDED")
    return response.object_response(serializers.dump("certificates", row))


# --------------------------------------------------------------------------
# Certificate coverage
# --------------------------------------------------------------------------

@route(bp, "/certificate-coverages", ["POST"], ["ProgramAdmin"])
def create_coverage(user_id, role):
    payload = valid.body()
    # Rank 10 then rank 14.
    site = valid.resolve_body("sites", payload, "site_id")
    certificate = valid.resolve_body("certificates", payload, "certificate_id")
    # Rank 20.
    start = valid.req_date(payload, "coverage_start")
    end = valid.req_date(payload, "coverage_end")
    if end < start:
        raise errors.invalid_request(
            "coverage_end may not precede coverage_start.")
    # Rank 40.
    if certificate["status"] != "ACTIVE":
        raise errors.ApiError("ERR_CERTIFICATE_NOT_ACTIVE", 409)
    # Rank 58.
    cert_start = clock.parse_date(certificate["effective_date"])
    cert_end = clock.parse_date(certificate["expiration_date"])
    if start < cert_start or end > cert_end:
        raise errors.ApiError("ERR_COVERAGE_OUTSIDE_CERTIFICATE_WINDOW", 422)
    # Rank 67.
    if calc.coverage_collides(site["id"], start, end):
        raise errors.ApiError("ERR_COVERAGE_WINDOW_OVERLAP", 409)

    row = db.insert("coverages", {
        "site_id": site["id"],
        "certificate_id": certificate["id"],
        "coverage_start": start.isoformat(),
        "coverage_end": end.isoformat(),
        "permitted_complexity_snapshot": certificate["permitted_complexity"],
    })
    derive.recompute_covered_site_count(certificate)
    derive.recompute_site(site)
    derive.recompute_scope_creep(site)
    return response.object_response(serializers.dump("coverages", row), 201)


@route(bp, "/certificate-coverages/<coverage_id>", ["GET"], NON_OPERATOR)
def read_coverage(user_id, role, coverage_id):
    row = valid.resolve("coverages", coverage_id)
    return response.object_response(serializers.dump("coverages", row))


@route(bp, "/certificate-coverages", ["GET"], NON_OPERATOR)
def list_coverages(user_id, role):
    limit, offset = valid.pagination()
    site_id = valid.arg("site_id")
    certificate_id = valid.arg("certificate_id")
    items = [c for c in db.rows("coverages")
             if (site_id is None or c["site_id"] == site_id)
             and (certificate_id is None or c["certificate_id"] == certificate_id)]
    return response.list_response(
        serializers.dump_many("coverages", valid.page(items, limit, offset)),
        limit, offset, len(items))
