"""Estoppel certificates, the three-step fee and the lender conditions."""
from flask import Blueprint

import engine
import validate as v
from crud import apply_filters, base, paginate, resolve, strip
from db import store
from errors import ApiError
from middleware import (LIST_READ_ROLES, SINGLE_READ_ROLES, authorize,
                        tenant_scope_lease)
from response import created, listing, ok

bp = Blueprint("estoppel", __name__)


def get_certificate(certificate_id):
    return resolve(store.certificates, certificate_id, "ERR_CERTIFICATE_NOT_FOUND")


@bp.post("/leases/<lease_id>/estoppel-certificates")
def create_certificate(lease_id):
    role, user_id = authorize(["LenderRep", "AssetManager"])
    body = v.body()
    measurement_id = v.opt_id(body, "measurement_id")
    expedite = v.opt_bool(body, "expedite_requested", default=False)

    lease = resolve(store.leases, lease_id, "ERR_LEASE_NOT_FOUND")
    if measurement_id is not None:
        measurement = resolve(store.measurements, measurement_id,
                              "ERR_MEASUREMENT_NOT_FOUND")
        if measurement["center_id"] != lease["center_id"]:
            raise ApiError("ERR_CENTER_SCOPE_MISMATCH")

    breach = engine.has_breached_condition(lease)
    exclusive_count = len([c for c in engine.clauses_of_lease(lease["id"])
                           if c["status"] == "ACTIVE"])
    base_fee, total_fee = engine.estoppel_fees(exclusive_count, breach, expedite)

    cert = base(engine.stamp())
    cert.update({
        "lease_id": lease["id"],
        "measurement_id": measurement_id,
        "requested_by_user_id": user_id,
        "pinned_lease_version": lease["version"],
        "expedite_requested": expedite,
        "disclosed_cotenancy_breach": breach,
        "disclosed_exclusive_count": exclusive_count,
        "disclosed_effective_rent_cents": lease["effective_rent_monthly_cents"],
        "base_fee_cents": base_fee,
        "total_fee_cents": total_fee,
        "lender_conditions_met": False,
        "status": "REQUESTED",
        "signed_at": None,
        "accepted_at": None,
    })
    store.certificates[cert["id"]] = cert
    engine.recompute_lender_conditions(cert)
    return created(strip(cert))


@bp.get("/estoppel-certificates/<certificate_id>")
def read_certificate(certificate_id):
    authorize(SINGLE_READ_ROLES)
    return ok(strip(get_certificate(certificate_id)))


@bp.get("/estoppel-certificates")
def list_certificates():
    authorize(LIST_READ_ROLES)
    limit, offset = v.pagination()
    records = engine._ordered(list(store.certificates.values()))
    records = apply_filters(records, [
        ("lease_id", v.filter_value("lease_id")),
        ("measurement_id", v.filter_value("measurement_id")),
        ("status", v.filter_value("status")),
    ])
    page, total = paginate(records, limit, offset)
    return listing([strip(r) for r in page], limit, offset, total)


@bp.post("/estoppel-certificates/<certificate_id>/sign")
def sign(certificate_id):
    role, user_id = authorize(["TenantRep"])
    v.body()
    cert = get_certificate(certificate_id)
    lease = resolve(store.leases, cert["lease_id"], "ERR_LEASE_NOT_FOUND")
    tenant_scope_lease(role, user_id, lease)

    if cert["status"] == "STALE":
        raise ApiError("ERR_CERTIFICATE_STALE")
    if cert["status"] != "REQUESTED":
        raise ApiError("ERR_CERTIFICATE_STATE_INVALID")
    if cert["pinned_lease_version"] != lease["version"]:
        raise ApiError("ERR_CERTIFICATE_STALE")

    cert["status"] = "TENANT_SIGNED"
    cert["signed_at"] = engine.stamp()
    engine.recompute_lender_conditions(cert)
    engine.touch(cert)
    return ok(strip(cert))


@bp.post("/estoppel-certificates/<certificate_id>/accept")
def accept(certificate_id):
    authorize(["LenderRep"])
    v.body()
    cert = get_certificate(certificate_id)
    lease = resolve(store.leases, cert["lease_id"], "ERR_LEASE_NOT_FOUND")

    if cert["status"] == "STALE":
        raise ApiError("ERR_CERTIFICATE_STALE")
    if cert["status"] != "TENANT_SIGNED":
        raise ApiError("ERR_CERTIFICATE_STATE_INVALID")
    if cert["pinned_lease_version"] != lease["version"]:
        raise ApiError("ERR_CERTIFICATE_STALE")
    engine.recompute_lender_conditions(cert)
    if not cert["lender_conditions_met"]:
        raise ApiError("ERR_LENDER_CONDITIONS_NOT_MET")

    cert["status"] = "LENDER_ACCEPTED"
    cert["accepted_at"] = engine.stamp()
    engine.touch(cert)
    return ok(strip(cert))


@bp.post("/estoppel-certificates/<certificate_id>/reject")
def reject(certificate_id):
    authorize(["LenderRep", "AssetManager"])
    body = v.body()
    v.opt_str(body, "rejection_reason_code")
    cert = get_certificate(certificate_id)
    if cert["status"] not in ("REQUESTED", "TENANT_SIGNED", "STALE"):
        raise ApiError("ERR_CERTIFICATE_STATE_INVALID")
    cert["status"] = "REJECTED"
    cert["lender_conditions_met"] = False
    engine.touch(cert)
    return ok(strip(cert))
