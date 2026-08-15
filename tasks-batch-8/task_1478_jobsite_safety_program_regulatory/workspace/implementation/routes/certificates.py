from flask import Blueprint, request

from db import store, now
from helpers import (
    require_roles,
    body,
    reject_unknown,
    f_str,
    f_enum,
    f_date,
    ok,
    paginate,
    invalid,
    end_of_day,
)
from errors import ApiError
from services import (
    get_worker,
    get_certificate,
    new_entity,
    ser_certificate,
    bump,
    certificate_window_conflicts,
)

bp = Blueprint("certificates", __name__)

ALL_ROLES = (
    "SafetyManager",
    "SiteSuperintendent",
    "SafetyInspector",
    "SubcontractorRep",
    "ComplianceAuditor",
)

CERT_TYPES = {"OSHA_10", "OSHA_30", "FIRST_AID", "FLAGGING"}


@bp.route("/safety/training-certificates", methods=["POST"])
def create_certificate():
    require_roles("SiteSuperintendent")
    b = body()
    # priority 3: body FK existence
    raw_wid = b.get("worker_id")
    if isinstance(raw_wid, str):
        get_worker(raw_wid)
    # priority 4: shape
    reject_unknown(b, {"worker_id", "cert_type", "issued_date", "expires_date"})
    worker_id = f_str(b, "worker_id")
    worker = get_worker(worker_id)
    cert_type = f_enum(b, "cert_type", CERT_TYPES)
    issued_date = f_date(b, "issued_date")
    expires_date = f_date(b, "expires_date")
    if expires_date <= issued_date:
        invalid("expires_date must be strictly after issued_date")
    # priority 8 (b): same-type window overlap (non-EXPIRED; half-open expiry edge)
    if certificate_window_conflicts(worker_id, cert_type, issued_date, expires_date):
        raise ApiError(
            "ERR_CERTIFICATE_WINDOW_OVERLAP",
            409,
            "Same worker + cert_type window overlaps an existing non-EXPIRED certificate",
        )
    c = new_entity()
    c.update(
        {
            "worker_id": worker_id,
            "cert_type": cert_type,
            "issued_date": issued_date,
            "expires_date": expires_date,
            "status": "UNVERIFIED",
            "verified_by_user_id": None,
        }
    )
    store.certificates[c["id"]] = c
    return ok(ser_certificate(c), 201)


@bp.route("/safety/training-certificates", methods=["GET"])
def list_certificates():
    require_roles(*ALL_ROLES)
    records = list(store.certificates.values())
    wid = request.args.get("worker_id")
    if wid is not None:
        records = [c for c in records if c["worker_id"] == wid]
    ct = request.args.get("cert_type")
    if ct is not None:
        records = [c for c in records if c["cert_type"] == ct]
    status = request.args.get("status")
    if status is not None:
        records = [c for c in records if c["status"] == status]
    return paginate(records, ser_certificate)


@bp.route("/safety/training-certificates/<certificateId>", methods=["GET"])
def get_one_certificate(certificateId):
    require_roles(*ALL_ROLES)
    return ok(ser_certificate(get_certificate(certificateId)))


@bp.route("/safety/training-certificates/<certificateId>/verify", methods=["POST"])
def verify_certificate(certificateId):
    uid, _ = require_roles("SafetyInspector")
    cert = get_certificate(certificateId)
    b = body()
    reject_unknown(b, set())
    if cert["status"] != "UNVERIFIED":
        raise ApiError(
            "ERR_CERTIFICATE_INVALID_STATE",
            409,
            "verify requires status UNVERIFIED",
        )
    if now() > end_of_day(cert["expires_date"]):
        raise ApiError(
            "ERR_CERTIFICATE_EXPIRED",
            409,
            "Certificate expiry date has passed",
        )
    cert["status"] = "VERIFIED"
    cert["verified_by_user_id"] = uid
    bump(cert)
    return ok(ser_certificate(cert))
