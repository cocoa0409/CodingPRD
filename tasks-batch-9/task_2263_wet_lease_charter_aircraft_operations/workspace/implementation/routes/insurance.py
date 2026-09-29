"""Insurance certificates (PRD 3.3)."""

from flask import Blueprint, request

from db import db, new_row, touch, public, clock_now
from errors import ApiError, bad_request
from middleware import (
    require, check_ownership, scope_for_lessee,
    LESSOR_OPS, LESSEE, INSURANCE_UNDERWRITER,
)
from response import object_response, pagination, paged
from routes.common import find_lease, find_certificate, filtered
from services import calculations as C
from services import workflows as W
import validate as V

bp = Blueprint("insurance", __name__)

CERTIFIABLE_LEASE_STATUSES = (
    "DRAFT", "PENDING_REGULATORY_APPROVAL", "APPROVED", "ACTIVE", "SUSPENDED",
)


@bp.post("/wetlease/insurance-certificates")
def create_certificate():
    require((INSURANCE_UNDERWRITER,))
    body = V.json_body()
    lease_id = V.req_str(body, "lease_id")
    certificate_no = V.req_str(body, "certificate_no")
    hull_limit = V.req_int(body, "hull_limit_usd_cents", minimum=0)
    liability_limit = V.req_int(body, "liability_limit_usd_cents", minimum=0)
    breach_of_warranty = V.req_bool(body, "breach_of_warranty_endorsed")
    additional_insured = V.req_bool(body, "additional_insured_lessee")
    effective_raw, effective_from = V.req_datetime(body, "effective_from")
    expires_raw, expires_at = V.req_datetime(body, "expires_at")

    lease = find_lease(lease_id)
    if lease["status"] not in CERTIFIABLE_LEASE_STATUSES:
        raise ApiError("ERR_LEASE_INVALID_STATE")

    if (hull_limit < C.HULL_LIMIT_FLOOR_CENTS
            or liability_limit < C.LIABILITY_LIMIT_FLOOR_CENTS):
        raise ApiError("ERR_INSURANCE_LIMIT_BELOW_MINIMUM")

    for existing in W.certificates_of_lease(lease_id):
        if existing["status"] != "ACTIVE":
            continue
        # Both comparisons inclusive: intervals that merely touch do conflict.
        if effective_from <= existing["_expires_at"] and \
                existing["_effective_from"] <= expires_at:
            raise ApiError("ERR_INSURANCE_PERIOD_OVERLAP")

    row = new_row()
    row.update({
        "lease_id": lease_id,
        "certificate_no": certificate_no,
        "hull_limit_usd_cents": hull_limit,
        "liability_limit_usd_cents": liability_limit,
        "breach_of_warranty_endorsed": breach_of_warranty,
        "additional_insured_lessee": additional_insured,
        "effective_from": effective_raw,
        "expires_at": expires_raw,
        "status": "ACTIVE",
        "revocation_reason": None,
        "_effective_from": effective_from,
        "_expires_at": expires_at,
    })
    db.insurance_certificates[row["id"]] = row

    if lease["status"] == "SUSPENDED" and lease["suspension_reason"] == "INSURANCE_LAPSED":
        for existing in W.certificates_of_lease(lease_id):
            if existing["id"] == row["id"]:
                continue
            if existing["status"] == "ACTIVE":
                existing["status"] = "SUPERSEDED"
                touch(existing)
        now = clock_now()
        if additional_insured and effective_from <= now <= expires_at:
            lease["status"] = "ACTIVE"
            lease["suspension_reason"] = None
            touch(lease)

    return object_response(public(row), 201)


@bp.get("/wetlease/insurance-certificates/<certificate_id>")
def get_certificate(certificate_id):
    actor = require((INSURANCE_UNDERWRITER, LESSOR_OPS, LESSEE))
    cert = find_certificate(certificate_id)
    check_ownership(actor, "certificate", cert)
    return object_response(public(cert))


@bp.get("/wetlease/insurance-certificates")
def list_certificates():
    actor = require((INSURANCE_UNDERWRITER, LESSOR_OPS, LESSEE))
    limit, offset = pagination(request.args)
    rows = filtered(list(db.insurance_certificates.values()), request.args, {
        "lease_id": "lease_id",
        "status": "status",
    })
    rows = scope_for_lessee(actor, "certificate", rows)
    return paged(rows, limit, offset)


@bp.post("/wetlease/insurance-certificates/<certificate_id>/revoke")
def revoke_certificate(certificate_id):
    require((INSURANCE_UNDERWRITER,))
    body = V.json_body()
    reason = V.req_str(body, "revocation_reason")
    cert = find_certificate(certificate_id)
    if cert["status"] != "ACTIVE":
        raise bad_request("only an ACTIVE certificate may be revoked")

    cert["status"] = "REVOKED"
    cert["revocation_reason"] = reason
    touch(cert)

    W.insurance_lapse_cascade(db.leases.get(cert["lease_id"]))
    return object_response(public(cert))
