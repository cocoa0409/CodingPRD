"""Participants and consent records."""
from flask import Blueprint, request

from db import db, parse_dt, new_entity, now_iso, now_dt
from errors import ApiError
from middleware import require_roles
from response import ok_object, ok_list
from util import (
    get_body,
    req_str,
    opt_str,
    req_enum,
    req_int,
    req_datetime,
    get_or_404,
    page_of,
    serialize,
    touch,
)
import services

bp = Blueprint("people", __name__)

PARTICIPANT_READ_ROLES = (
    "ProgramDirector",
    "EvaluationLead",
    "DataSteward",
    "PrivacyOfficer",
    "FieldCollector",
)
CONSENT_READ_ROLES = ("ProgramDirector", "EvaluationLead", "DataSteward", "PrivacyOfficer")
SCOPES = ("FULL", "AGGREGATE_ONLY")


# -------------------------------------------------------------- enrollment
@bp.post("/cycles/<cid>/participants")
@require_roles("ProgramDirector")
def enroll_participant(cid):
    cycle = get_or_404(db.cycles, cid)
    body = get_body()
    external_ref = req_str(body, "external_ref")
    if cycle["status"] not in ("ENROLLING", "ACTIVE"):
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            "Participants can enroll only while the cycle is ENROLLING or ACTIVE.",
        )
    now = now_dt()
    if not (parse_dt(cycle["enrollment_start"]) <= now <= parse_dt(cycle["enrollment_end"])):
        raise ApiError(
            "ERR_ENROLLMENT_WINDOW_CLOSED", 422, "Current time is outside the enrollment window."
        )
    if any(
        p["program_cycle_id"] == cid and p["external_ref"] == external_ref
        for p in db.participants.values()
    ):
        raise ApiError(
            "ERR_DUPLICATE_CODE", 409, f"external_ref already used in this cycle: {external_ref}"
        )
    ent = new_entity(
        db.participants,
        {
            "program_cycle_id": cid,
            "external_ref": external_ref,
            "enrolled_at": now_iso(),
            "status": "ENROLLED",
            "exit_reason": None,
            "consent_status": "NONE",
        },
    )
    return ok_object(serialize(ent), 201)


@bp.get("/cycles/<cid>/participants")
@require_roles(*PARTICIPANT_READ_ROLES)
def list_participants(cid):
    get_or_404(db.cycles, cid)
    items = [p for p in db.participants.values() if p["program_cycle_id"] == cid]
    status = request.args.get("status")
    if status is not None:
        items = [p for p in items if p["status"] == status]
    data, limit, offset, total = page_of(items)
    return ok_list(data, limit, offset, total)


@bp.get("/participants/<pid>")
@require_roles(*PARTICIPANT_READ_ROLES)
def get_participant(pid):
    participant = get_or_404(db.participants, pid)
    services.refresh_participant_consent(participant)  # lazy EXPIRED evaluation
    return ok_object(serialize(participant))


# ------------------------------------------------------- participant actions
@bp.post("/participants/<pid>/exit")
@require_roles("ProgramDirector")
def exit_participant(pid):
    participant = get_or_404(db.participants, pid)
    body = get_body()
    reason = opt_str(body, "reason")
    if participant["status"] != "ACTIVE":
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            f"Participant in state {participant['status']} cannot exit.",
        )
    participant["status"] = "EXITED"
    participant["exit_reason"] = reason
    touch(db.participants, participant)
    cycle = services.cycle_of_participant(participant)
    if cycle is not None:
        services.recompute_cycle_aggregates(cycle)
    return ok_object(serialize(participant))


@bp.post("/participants/<pid>/re-enroll")
@require_roles("ProgramDirector")
def reenroll_participant(pid):
    participant = get_or_404(db.participants, pid)
    get_body()
    services.refresh_participant_consent(participant)  # consent check: lazy expiry
    if participant["status"] != "EXITED":
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            f"Participant in state {participant['status']} cannot re-enroll.",
        )
    if participant["consent_status"] != "CURRENT":
        raise ApiError(
            "ERR_INVALID_STATE", 409, "Re-enrollment requires consent_status CURRENT."
        )
    participant["status"] = "ACTIVE"
    touch(db.participants, participant)
    cycle = services.cycle_of_participant(participant)
    if cycle is not None:
        services.recompute_cycle_aggregates(cycle)
    return ok_object(serialize(participant))


# ----------------------------------------------------------------- consents
@bp.post("/participants/<pid>/consents")
@require_roles("PrivacyOfficer")
def grant_consent(pid):
    participant = get_or_404(db.participants, pid)
    body = get_body()
    form_version = req_int(body, "form_version")
    scope = req_enum(body, "scope", SCOPES)
    expires_at = req_datetime(body, "expires_at")
    program = services.program_of_participant(participant)
    # Version pinning: the presented form must equal the program's current edition.
    if form_version != program["current_consent_form_version"]:
        raise ApiError(
            "ERR_STALE_CONSENT_FORM",
            422,
            "form_version does not equal the program's current consent form version.",
        )
    # A new grant supersedes any prior GRANTED record for this participant.
    for c in db.consents.values():
        if c["participant_id"] == pid and c["status"] == "GRANTED":
            c["status"] = "SUPERSEDED"
            touch(db.consents, c)
    ent = new_entity(
        db.consents,
        {
            "participant_id": pid,
            "form_version": form_version,
            "scope": scope,
            "granted_at": now_iso(),
            "expires_at": expires_at,
            "status": "GRANTED",
            "revoked_at": None,
        },
    )
    # Recompute consent_status (this also applies lazy expiry to the new record).
    services.refresh_participant_consent(participant)
    # A current consent activates an ENROLLED participant automatically.
    if participant["status"] == "ENROLLED" and participant["consent_status"] == "CURRENT":
        participant["status"] = "ACTIVE"
        touch(db.participants, participant)
    cycle = services.cycle_of_participant(participant)
    if cycle is not None:
        services.recompute_cycle_aggregates(cycle)
    return ok_object(serialize(ent), 201)


@bp.get("/participants/<pid>/consents")
@require_roles(*CONSENT_READ_ROLES)
def list_consents(pid):
    participant = get_or_404(db.participants, pid)
    services.refresh_participant_consent(participant)  # lazy EXPIRED evaluation
    items = [c for c in db.consents.values() if c["participant_id"] == pid]
    status = request.args.get("status")
    if status is not None:
        items = [c for c in items if c["status"] == status]
    data, limit, offset, total = page_of(items)
    return ok_list(data, limit, offset, total)


@bp.post("/consents/<cid>/revoke")
@require_roles("PrivacyOfficer")
def revoke_consent(cid):
    consent = get_or_404(db.consents, cid)
    get_body()
    if consent["status"] != "GRANTED":
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            f"Consent in state {consent['status']} cannot be revoked.",
        )
    consent["status"] = "REVOKED"
    consent["revoked_at"] = now_iso()
    touch(db.consents, consent)
    participant = db.participants.get(consent["participant_id"])
    if participant is not None:
        other_granted = any(
            c["participant_id"] == participant["id"]
            and c["status"] == "GRANTED"
            and c["id"] != cid
            for c in db.consents.values()
        )
        if not other_granted:
            # Withdrawal cascade (participant, observation, and cycle hops).
            services.withdraw_participant(participant)
        services.refresh_participant_consent(participant)
    return ok_object(serialize(consent))
