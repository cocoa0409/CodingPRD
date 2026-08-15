"""Instruments and training certifications."""
from flask import Blueprint, request

from db import db, new_entity, now_iso
from errors import ApiError
from middleware import require_roles
from response import ok_object, ok_list
from util import (
    get_body,
    req_str,
    req_datetime,
    get_or_404,
    page_of,
    serialize,
    touch,
)
import services

bp = Blueprint("instruments", __name__)

INSTRUMENT_READ_ROLES = ("ProgramDirector", "EvaluationLead", "DataSteward", "FieldCollector")
CERT_READ_ROLES = ("ProgramDirector", "EvaluationLead", "DataSteward")


# --------------------------------------------------------------- instruments
@bp.post("/programs/<pid>/instruments")
@require_roles("EvaluationLead")
def create_instrument(pid):
    get_or_404(db.programs, pid)
    body = get_body()
    code = req_str(body, "code")
    title = req_str(body, "title")
    ent = new_entity(
        db.instruments,
        {
            "program_id": pid,
            "code": code,
            "title": title,
            "instrument_version": 1,
            "status": "DRAFT",
        },
    )
    return ok_object(serialize(ent), 201)


@bp.get("/programs/<pid>/instruments")
@require_roles(*INSTRUMENT_READ_ROLES)
def list_instruments(pid):
    get_or_404(db.programs, pid)
    items = [i for i in db.instruments.values() if i["program_id"] == pid]
    status = request.args.get("status")
    if status is not None:
        items = [i for i in items if i["status"] == status]
    data, limit, offset, total = page_of(items)
    return ok_list(data, limit, offset, total)


@bp.get("/instruments/<iid>")
@require_roles(*INSTRUMENT_READ_ROLES)
def get_instrument(iid):
    return ok_object(serialize(get_or_404(db.instruments, iid)))


def _stale_certifications_of(instrument_id):
    """Every CERTIFIED certification pinned to this instrument goes STALE."""
    for cert in db.certifications.values():
        if cert["instrument_id"] == instrument_id and cert["status"] == "CERTIFIED":
            cert["status"] = "STALE"
            touch(db.certifications, cert)


@bp.post("/instruments/<iid>/publish")
@require_roles("EvaluationLead")
def publish_instrument(iid):
    instrument = get_or_404(db.instruments, iid)
    get_body()
    if instrument["status"] != "DRAFT":
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            f"Instrument in state {instrument['status']} cannot be published.",
        )
    instrument["status"] = "PUBLISHED"
    touch(db.instruments, instrument)
    # Predecessor hop: same program + code, version exactly one less, PUBLISHED.
    for other in db.instruments.values():
        if (
            other["program_id"] == instrument["program_id"]
            and other["code"] == instrument["code"]
            and other["instrument_version"] == instrument["instrument_version"] - 1
            and other["status"] == "PUBLISHED"
        ):
            other["status"] = "RETIRED"
            touch(db.instruments, other)
            # Certification hop: collectors are never left silently certified
            # on a superseded instrument.
            _stale_certifications_of(other["id"])
    return ok_object(serialize(instrument))


@bp.post("/instruments/<iid>/new-revision")
@require_roles("EvaluationLead")
def new_revision(iid):
    instrument = get_or_404(db.instruments, iid)
    get_body()
    ent = new_entity(
        db.instruments,
        {
            "program_id": instrument["program_id"],
            "code": instrument["code"],
            "title": instrument["title"],
            "instrument_version": instrument["instrument_version"] + 1,
            "status": "DRAFT",
        },
    )
    return ok_object(serialize(ent), 201)


@bp.post("/instruments/<iid>/retire")
@require_roles("EvaluationLead")
def retire_instrument(iid):
    instrument = get_or_404(db.instruments, iid)
    get_body()
    if instrument["status"] != "PUBLISHED":
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            f"Instrument in state {instrument['status']} cannot be retired.",
        )
    instrument["status"] = "RETIRED"
    touch(db.instruments, instrument)
    _stale_certifications_of(iid)
    return ok_object(serialize(instrument))


@bp.get("/instruments/<iid>/observations")
@require_roles(*INSTRUMENT_READ_ROLES)
def list_instrument_observations(iid):
    get_or_404(db.instruments, iid)
    items = [o for o in db.observations.values() if o["instrument_id"] == iid]
    rs = request.args.get("review_status")
    if rs is not None:
        items = [o for o in items if o["review_status"] == rs]
    data, limit, offset, total = page_of(items)
    return ok_list(data, limit, offset, total)


# ------------------------------------------------------------ certifications
@bp.post("/certifications")
@require_roles("EvaluationLead")
def create_certification():
    body = get_body()
    staff_user_id = req_str(body, "staff_user_id")
    instrument_id = req_str(body, "instrument_id")
    expires_at = req_datetime(body, "expires_at")
    instrument = db.instruments.get(instrument_id)
    if instrument is None:
        raise ApiError("ERR_NOT_FOUND", 404, f"Instrument not found: {instrument_id}")
    if instrument["status"] != "PUBLISHED":
        raise ApiError(
            "ERR_INVALID_STATE", 409, "Certification requires a PUBLISHED instrument."
        )
    ent = new_entity(
        db.certifications,
        {
            "staff_user_id": staff_user_id,
            "instrument_id": instrument_id,
            "certified_instrument_version": instrument["instrument_version"],
            "certified_at": now_iso(),
            "expires_at": expires_at,
            "status": "CERTIFIED",
        },
    )
    return ok_object(serialize(ent), 201)


@bp.get("/certifications")
@require_roles(*CERT_READ_ROLES)
def list_certifications():
    items = list(db.certifications.values())
    staff = request.args.get("staff_user_id")
    if staff is not None:
        items = [c for c in items if c["staff_user_id"] == staff]
    inst = request.args.get("instrument_id")
    if inst is not None:
        items = [c for c in items if c["instrument_id"] == inst]
    status = request.args.get("status")
    if status is not None:
        items = [c for c in items if c["status"] == status]
    for c in items:
        services.refresh_certification(c)  # lazy EXPIRED evaluation
    data, limit, offset, total = page_of(items)
    return ok_list(data, limit, offset, total)


@bp.get("/certifications/<cid>")
@require_roles(*CERT_READ_ROLES)
def get_certification(cid):
    cert = get_or_404(db.certifications, cid)
    services.refresh_certification(cert)  # lazy EXPIRED evaluation
    return ok_object(serialize(cert))


@bp.post("/certifications/<cid>/suspend")
@require_roles("EvaluationLead")
def suspend_certification(cid):
    cert = get_or_404(db.certifications, cid)
    get_body()
    services.refresh_certification(cert)
    if cert["status"] != "CERTIFIED":
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            f"Certification in state {cert['status']} cannot be suspended.",
        )
    cert["status"] = "SUSPENDED"
    touch(db.certifications, cert)
    return ok_object(serialize(cert))


@bp.post("/certifications/<cid>/reinstate")
@require_roles("EvaluationLead")
def reinstate_certification(cid):
    cert = get_or_404(db.certifications, cid)
    get_body()
    if cert["status"] != "SUSPENDED":
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            f"Certification in state {cert['status']} cannot be reinstated.",
        )
    instrument = db.instruments.get(cert["instrument_id"])
    current_version = (
        services.instrument_line_current_version(instrument) if instrument else None
    )
    if cert["certified_instrument_version"] != current_version:
        raise ApiError(
            "ERR_CERTIFICATION_STALE",
            422,
            "Pinned instrument version no longer matches the instrument's current version.",
        )
    cert["status"] = "CERTIFIED"
    touch(db.certifications, cert)
    return ok_object(serialize(cert))
