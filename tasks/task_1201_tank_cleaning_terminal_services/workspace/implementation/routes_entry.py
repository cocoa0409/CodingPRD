"""GasFreeCertificate and EntryPermit (PRD §3.6), including the cert-death
cascade and the parallel atmosphere dimension."""

from datetime import timedelta

from flask import Blueprint

from core import (
    db, ApiError, auth, require_role, body_json, req_int, req_str, req_num,
    get_or_404, create_entity, touch, ser, ok, paginate, sorted_all,
    apply_filters, forbid, now,
    ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_GAS_FREE_LIMITS,
    ERR_NO_VALID_CERT, ERR_CERT_EXPIRED, ERR_CERT_ALREADY_REVALIDATED, ERR_SOD,
    ERR_ATMOSPHERE_NOT_CLEAR,
)
import calc
from services import cert_death_cascade, permit_suspend_cascade

bp = Blueprint("entry", __name__)


def _own_job(uid, job):
    if job["contractor_id"] != uid:
        forbid("acting ContractorSupervisor does not own this job")


# ---------------------------------------------------- gas-free certificates ---


@bp.post("/gas-free-certificates")
def create_cert():
    uid, role = auth()
    require_role(role, {"MarineChemist"})
    b = body_json()
    job_id = req_str(b, "job_id")
    lel = req_num(b, "lel_pct")
    o2 = req_num(b, "o2_pct")
    h2s = req_num(b, "h2s_ppm")
    benzene = req_num(b, "benzene_ppm")
    job = get_or_404(db.cleaning_jobs, job_id, "cleaning job")
    if job["status"] != "GAS_FREE_PENDING":
        raise ApiError(ERR_INVALID_STATE, 409, "job is not GAS_FREE_PENDING")
    if not calc.gas_free_within_limits(lel, o2, h2s, benzene):
        raise ApiError(ERR_GAS_FREE_LIMITS, 422,
                       "one or more atmospheric readings are outside limits")
    # A new certificate supersedes any prior VALID one for the same job.
    for c in db.gas_free_certs.values():
        if c["job_id"] == job_id and c["status"] == "VALID":
            c["status"] = "SUPERSEDED"
            touch(c)
    issued_at = now()
    cert = create_entity({
        "job_id": job_id,
        "lel_pct": lel,
        "o2_pct": o2,
        "h2s_ppm": h2s,
        "benzene_ppm": benzene,
        "issued_at": issued_at,
        "expires_at": issued_at + timedelta(hours=calc.CERT_VALIDITY_HOURS),
        "revalidated": False,
        "issued_by_user_id": uid,
        "status": "VALID",
    })
    db.gas_free_certs[cert["id"]] = cert
    job["status"] = "GAS_FREE_CERTIFIED"
    touch(job)
    return ok(ser(cert), 201)


@bp.get("/gas-free-certificates/<certId>")
def get_cert(certId):
    auth()
    return ok(ser(get_or_404(db.gas_free_certs, certId, "certificate")), 200)


@bp.get("/gas-free-certificates")
def list_certs():
    auth()
    items = apply_filters(sorted_all(db.gas_free_certs), [
        ("job_id", "job_id"),
        ("status", "status"),
    ])
    page, pg = paginate(items)
    return ok([ser(e) for e in page], 200, pg)


@bp.post("/gas-free-certificates/<certId>/revalidate")
def revalidate_cert(certId):
    uid, role = auth()
    require_role(role, {"MarineChemist"})
    cert = get_or_404(db.gas_free_certs, certId, "certificate")
    if cert["status"] != "VALID":
        raise ApiError(ERR_INVALID_STATE, 409, "certificate is not VALID")
    # PRD §3.6: the clock is examined first, then the one-shot flag.
    if not now() < cert["expires_at"]:
        raise ApiError(ERR_CERT_EXPIRED, 409, "certificate has expired")
    if cert["revalidated"]:
        raise ApiError(ERR_CERT_ALREADY_REVALIDATED, 409,
                       "certificate was already revalidated once")
    cert["expires_at"] = cert["expires_at"] + timedelta(
        hours=calc.REVALIDATE_EXTENSION_HOURS)
    cert["revalidated"] = True
    touch(cert)
    # Anchored permits awaiting retest clear automatically on revalidation.
    for p in db.entry_permits.values():
        if p["cert_id"] == cert["id"] and p["atmosphere"] == "RETEST_REQUIRED":
            p["atmosphere"] = "CLEAR"
            touch(p)
    return ok(ser(cert), 200)


@bp.post("/gas-free-certificates/<certId>/revoke")
def revoke_cert(certId):
    uid, role = auth()
    require_role(role, {"MarineChemist"})
    cert = get_or_404(db.gas_free_certs, certId, "certificate")
    if cert["status"] != "VALID":
        raise ApiError(ERR_INVALID_STATE, 409, "certificate is not VALID")
    cert["status"] = "REVOKED"
    touch(cert)
    cert_death_cascade(cert, "CERT_REVOKED")
    return ok(ser(cert), 200)


# ------------------------------------------------------------ entry permits ---


@bp.post("/entry-permits")
def create_permit():
    uid, role = auth()
    require_role(role, {"ContractorSupervisor"})
    b = body_json()
    job_id = req_str(b, "job_id")
    cert_id = req_str(b, "cert_id")
    max_entrants = req_int(b, "max_entrants")
    job = get_or_404(db.cleaning_jobs, job_id, "cleaning job")
    get_or_404(db.gas_free_certs, cert_id, "certificate")
    _own_job(uid, job)
    if max_entrants < 1:
        raise ApiError(ERR_INVALID_REQUEST, 400, "max_entrants must be >= 1")
    p = create_entity({
        "job_id": job_id,
        "cert_id": cert_id,
        "max_entrants": max_entrants,
        "issued_by_user_id": None,
        "status": "REQUESTED",
        "atmosphere": "CLEAR",
    })
    db.entry_permits[p["id"]] = p
    return ok(ser(p), 201)


@bp.get("/entry-permits/<permitId>")
def get_permit(permitId):
    auth()
    return ok(ser(get_or_404(db.entry_permits, permitId, "entry permit")), 200)


@bp.get("/entry-permits")
def list_permits():
    auth()
    items = apply_filters(sorted_all(db.entry_permits), [
        ("job_id", "job_id"),
        ("cert_id", "cert_id"),
        ("status", "status"),
    ])
    page, pg = paginate(items)
    return ok([ser(e) for e in page], 200, pg)


@bp.post("/entry-permits/<permitId>/issue")
def issue_permit(permitId):
    uid, role = auth()
    require_role(role, {"EHSOfficer"})
    p = get_or_404(db.entry_permits, permitId, "entry permit")
    if p["status"] != "REQUESTED":
        raise ApiError(ERR_INVALID_STATE, 409, "permit is not REQUESTED")
    job = db.cleaning_jobs.get(p["job_id"])
    if job is None or job["status"] != "GAS_FREE_CERTIFIED":
        raise ApiError(ERR_INVALID_STATE, 409, "job is not GAS_FREE_CERTIFIED")
    cert = db.gas_free_certs.get(p["cert_id"])
    if cert is None or cert["status"] != "VALID":
        raise ApiError(ERR_NO_VALID_CERT, 409,
                       "referenced certificate is not VALID")
    if not now() < cert["expires_at"]:
        raise ApiError(ERR_CERT_EXPIRED, 409, "certificate has expired")
    if uid == cert["issued_by_user_id"]:
        raise ApiError(ERR_SOD, 403,
                       "permit issuer must differ from the certificate issuer")
    p["issued_by_user_id"] = uid
    p["status"] = "ISSUED"
    touch(p)
    return ok(ser(p), 200)


@bp.post("/entry-permits/<permitId>/activate")
def activate_permit(permitId):
    uid, role = auth()
    require_role(role, {"ContractorSupervisor"})
    p = get_or_404(db.entry_permits, permitId, "entry permit")
    job = db.cleaning_jobs.get(p["job_id"])
    if job is not None:
        _own_job(uid, job)
    if p["status"] != "ISSUED":
        raise ApiError(ERR_INVALID_STATE, 409, "permit is not ISSUED")
    if job is None or job["status"] != "GAS_FREE_CERTIFIED":
        raise ApiError(ERR_INVALID_STATE, 409, "job is not GAS_FREE_CERTIFIED")
    cert = db.gas_free_certs.get(p["cert_id"])
    if cert is None or cert["status"] != "VALID" or not now() < cert["expires_at"]:
        raise ApiError(ERR_CERT_EXPIRED, 409,
                       "anchoring certificate is not valid and unexpired")
    if p["atmosphere"] != "CLEAR":
        raise ApiError(ERR_ATMOSPHERE_NOT_CLEAR, 409,
                       "permit atmosphere is not CLEAR")
    p["status"] = "ACTIVE"
    touch(p)
    return ok(ser(p), 200)


@bp.post("/entry-permits/<permitId>/suspend")
def suspend_permit(permitId):
    uid, role = auth()
    require_role(role, {"EHSOfficer"})
    p = get_or_404(db.entry_permits, permitId, "entry permit")
    if p["status"] not in ("ISSUED", "ACTIVE"):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "only an ISSUED or ACTIVE permit can be suspended")
    p["status"] = "SUSPENDED"
    touch(p)
    permit_suspend_cascade(p)
    return ok(ser(p), 200)


@bp.post("/entry-permits/<permitId>/resume")
def resume_permit(permitId):
    uid, role = auth()
    require_role(role, {"EHSOfficer"})
    p = get_or_404(db.entry_permits, permitId, "entry permit")
    if p["status"] != "SUSPENDED":
        raise ApiError(ERR_INVALID_STATE, 409, "permit is not SUSPENDED")
    cert = db.gas_free_certs.get(p["cert_id"])
    if cert is None or cert["status"] != "VALID" or not now() < cert["expires_at"]:
        raise ApiError(ERR_CERT_EXPIRED, 409,
                       "anchoring certificate is not valid and unexpired")
    if p["atmosphere"] != "CLEAR":
        raise ApiError(ERR_ATMOSPHERE_NOT_CLEAR, 409,
                       "permit atmosphere is not CLEAR")
    p["status"] = "ACTIVE"
    touch(p)
    return ok(ser(p), 200)


@bp.post("/entry-permits/<permitId>/close")
def close_permit(permitId):
    uid, role = auth()
    require_role(role, {"ContractorSupervisor"})
    p = get_or_404(db.entry_permits, permitId, "entry permit")
    job = db.cleaning_jobs.get(p["job_id"])
    if job is not None:
        _own_job(uid, job)
    if p["status"] not in ("ACTIVE", "SUSPENDED"):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "only an ACTIVE or SUSPENDED permit can be closed")
    p["status"] = "CLOSED"
    touch(p)
    return ok(ser(p), 200)


@bp.post("/entry-permits/<permitId>/void")
def void_permit(permitId):
    uid, role = auth()
    require_role(role, {"EHSOfficer"})
    p = get_or_404(db.entry_permits, permitId, "entry permit")
    if p["status"] not in ("REQUESTED", "ISSUED", "SUSPENDED"):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "permit cannot be voided from its current state")
    p["status"] = "VOIDED"
    touch(p)
    return ok(ser(p), 200)


# ------------------------------------------- atmosphere parallel dimension ---


@bp.post("/entry-permits/<permitId>/raise-alarm")
def raise_alarm(permitId):
    uid, role = auth()
    require_role(role, {"ContractorSupervisor", "EHSOfficer"})
    p = get_or_404(db.entry_permits, permitId, "entry permit")
    if role == "ContractorSupervisor":
        job = db.cleaning_jobs.get(p["job_id"])
        if job is not None:
            _own_job(uid, job)
    if p["status"] not in ("ISSUED", "ACTIVE", "SUSPENDED"):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "alarms can only be raised on a live permit")
    if p["atmosphere"] != "CLEAR":
        raise ApiError(ERR_INVALID_STATE, 409, "atmosphere is not CLEAR")
    p["atmosphere"] = "ALARM"
    touch(p)
    return ok(ser(p), 200)


@bp.post("/entry-permits/<permitId>/resolve-alarm")
def resolve_alarm(permitId):
    uid, role = auth()
    require_role(role, {"EHSOfficer"})
    p = get_or_404(db.entry_permits, permitId, "entry permit")
    if p["atmosphere"] != "ALARM":
        raise ApiError(ERR_INVALID_STATE, 409, "atmosphere is not ALARM")
    p["atmosphere"] = "RETEST_REQUIRED"
    touch(p)
    return ok(ser(p), 200)


@bp.post("/entry-permits/<permitId>/clear-atmosphere")
def clear_atmosphere(permitId):
    uid, role = auth()
    require_role(role, {"EHSOfficer"})
    p = get_or_404(db.entry_permits, permitId, "entry permit")
    if p["atmosphere"] != "RETEST_REQUIRED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "atmosphere is not RETEST_REQUIRED")
    cert = db.gas_free_certs.get(p["cert_id"])
    if cert is None or cert["status"] != "VALID":
        raise ApiError(ERR_NO_VALID_CERT, 409,
                       "anchoring certificate is not VALID")
    p["atmosphere"] = "CLEAR"
    touch(p)
    return ok(ser(p), 200)
