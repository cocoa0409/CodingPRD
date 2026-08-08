"""Procedure-log routes — PRD §3.6 (the longest validation chain)."""

from flask import Blueprint

import config
import domain
import serialize
import store
import validate as V
from auth import authenticate, require_owns_artist
from envelope import array_response, force, send, watch
from errors import ApiError

bp = Blueprint("procedure_logs", __name__)

READ_ROLES = [
    "HealthOfficer",
    "Inspector",
    "RecordsClerk",
    "EstablishmentOperator",
    "Artist",
]


@bp.post("/body-art/procedure-logs")
def create_procedure_log():
    caller = authenticate(["Artist"])
    data = V.body()
    establishment_id = V.req_id(data, "establishment_id")
    artist_id = V.req_id(data, "artist_id")
    minor_consent_id = V.opt_id(data, "minor_consent_id")
    client_age = V.req_int(data, "client_age", minimum=0, maximum=120)
    procedure_type = V.req_enum(data, "procedure_type", config.PROCEDURE_TYPES)
    started_at = V.req_datetime(data, "started_at")
    ended_at = V.req_datetime(data, "ended_at")
    if not ended_at > started_at:
        raise V.bad("ended_at must be strictly after started_at.")
    aftercare_provided = V.req_bool(data, "aftercare_provided")

    # step 5 — body foreign keys, left to right
    est = V.get_establishment(establishment_id)
    artist = V.get_artist(artist_id)
    consent = None
    if minor_consent_id is not None:
        consent = V.get_minor_consent(minor_consent_id)

    # step 6 — ownership
    require_owns_artist(caller, artist_id, artist)

    # step 7 — artist/establishment consistency
    if artist["establishment_id"] != est["id"]:
        raise ApiError("ERR_ARTIST_ESTABLISHMENT_MISMATCH")

    # posture gate
    if est["operating_posture"] == "CLOSED":
        raise ApiError("ERR_ESTABLISHMENT_NOT_OPERATING")

    # artist fitness
    expires = artist["bbp_training_expires_on"]
    if expires is None or expires <= started_at:
        raise ApiError("ERR_ARTIST_BBP_EXPIRED")
    if artist["permit_status"] != "ACTIVE":
        raise ApiError("ERR_ARTIST_NOT_PERMITTED")

    # restricted-posture minor block
    if (
        est["operating_posture"] == "RESTRICTED"
        and client_age < config.MINOR_AGE_THRESHOLD
    ):
        raise ApiError("ERR_RESTRICTED_POSTURE_MINOR_BLOCK")

    # the consent chain
    if client_age < config.MINOR_AGE_THRESHOLD:
        if consent is None:
            raise ApiError("ERR_MINOR_CONSENT_REQUIRED")
        if consent["verification_status"] != "VERIFIED":
            raise ApiError("ERR_MINOR_CONSENT_NOT_VERIFIED")
        if not started_at < consent["expires_at"]:
            raise ApiError("ERR_MINOR_CONSENT_EXPIRED")
        if (
            consent["authorized_procedure_type"] != procedure_type
            or consent["establishment_id"] != est["id"]
        ):
            raise ApiError("ERR_MINOR_CONSENT_MISMATCH")
    else:
        if consent is not None:
            raise ApiError("ERR_MINOR_CONSENT_NOT_APPLICABLE")

    # session exclusivity: half-open [started_at, ended_at), no buffer
    for existing in store.procedure_logs.values():
        if existing["artist_id"] != artist_id:
            continue
        if started_at < existing["ended_at"] and existing["started_at"] < ended_at:
            raise ApiError("ERR_ARTIST_SESSION_OVERLAP")

    rec = domain.new_record(
        {
            "establishment_id": est["id"],
            "artist_id": artist["id"],
            "minor_consent_id": minor_consent_id,
            "client_age": client_age,
            "procedure_type": procedure_type,
            "started_at": started_at,
            "ended_at": ended_at,
            "aftercare_provided": aftercare_provided,
            "audit_status": "RECORDED",
            "audit_finding_code": None,
        }
    )
    store.procedure_logs[rec["id"]] = rec
    return send(lambda: serialize.procedure_log(rec), 201)


@bp.get("/body-art/procedure-logs/<procedure_log_id>")
def read_procedure_log(procedure_log_id):
    authenticate(READ_ROLES)
    rec = V.get_procedure_log(procedure_log_id)
    return send(lambda: serialize.procedure_log(rec), 200)


@bp.get("/body-art/procedure-logs")
def list_procedure_logs():
    authenticate(
        ["HealthOfficer", "Inspector", "RecordsClerk", "EstablishmentOperator"]
    )
    limit, offset = V.pagination()
    establishment_id = V.filter_string("establishment_id")
    artist_id = V.filter_string("artist_id")
    minor_consent_id = V.filter_string("minor_consent_id")
    audit_status = V.filter_enum("audit_status", config.PROCEDURE_LOG_AUDIT_STATUSES)

    rows = store.sorted_rows(store.procedure_logs)
    if establishment_id is not None:
        rows = [r for r in rows if r["establishment_id"] == establishment_id]
    if artist_id is not None:
        rows = [r for r in rows if r["artist_id"] == artist_id]
    if minor_consent_id is not None:
        rows = [r for r in rows if r["minor_consent_id"] == minor_consent_id]
    if audit_status is not None:
        rows = [r for r in rows if r["audit_status"] == audit_status]
    page, total = V.paginate(rows, limit, offset)
    return array_response(
        [serialize.procedure_log(r) for r in page], limit, offset, total
    )


@bp.post("/body-art/procedure-logs/<procedure_log_id>/audit")
def audit_procedure_log(procedure_log_id):
    authenticate(["HealthOfficer"])
    rec = V.get_procedure_log(procedure_log_id)
    data = V.body()
    decision = V.req_enum(data, "decision", config.AUDIT_DECISIONS)
    finding_code = V.opt_enum(data, "finding_code", config.AUDIT_FINDING_CODES)

    if decision == "FLAG":
        if rec["audit_status"] != "RECORDED":
            raise ApiError("ERR_PROCEDURE_LOG_STATE_INVALID")
        watch(rec)
        rec["audit_status"] = "FLAGGED"
        rec["audit_finding_code"] = finding_code
    else:
        if rec["audit_status"] != "FLAGGED":
            raise ApiError("ERR_PROCEDURE_LOG_STATE_INVALID")
        watch(rec)
        rec["audit_status"] = "CLEARED"
        rec["audit_finding_code"] = None

    est = store.establishments.get(rec["establishment_id"])
    if est is not None:
        force(est)
        if rec["client_age"] < config.MINOR_AGE_THRESHOLD:
            domain.recompute_risk_and_posture(est)
    return send(lambda: serialize.procedure_log(rec), 200)
