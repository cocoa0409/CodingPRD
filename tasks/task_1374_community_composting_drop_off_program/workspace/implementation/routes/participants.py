"""Participant and AccessGrant endpoints."""

import secrets
import string

from flask import Blueprint, request

import db
import errors
from middleware import require_roles
from response import success_object, success_list
from routes.helpers import (
    body, require_fields, require_str, require_int, require_dt_field,
    get_program_or_404, get_participant_or_404, get_grant_or_404,
    get_site_or_404, paginate, sort_created,
)
from services import credits
from services.programs import touch
from services.serializers import participant as serialize_participant
from services.serializers import grant as serialize_grant

bp = Blueprint("participants", __name__)


def _mint_token():
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(24))


def _mint_access_code(site_id):
    alphabet = string.ascii_uppercase + string.digits
    while True:
        code = "".join(secrets.choice(alphabet) for _ in range(8))
        collision = any(
            g["site_id"] == site_id and g["status"] == "ACTIVE" and g["access_code"] == code
            for g in db.grants.values()
        )
        if not collision:
            return code


# ---------------------------------------------------------------------------
# Participants
# ---------------------------------------------------------------------------

@bp.route("/programs/<program_id>/participants/register", methods=["POST"])
def register_participant(program_id):
    require_roles("Anonymous")
    program = get_program_or_404(program_id)
    data = body()
    require_fields(data, "email", "full_name", "household_size")
    email = require_str(data, "email")
    full_name = require_str(data, "full_name")
    household_size = require_int(data, "household_size")

    now = db.iso_now()
    participant = {
        "id": db.new_id(),
        "program_id": program["id"],
        "email": email,
        "full_name": full_name,
        "household_size": household_size,
        "status": "PENDING_VERIFY",
        "verification_token": _mint_token(),
        "bucket_credit_balance": 0,
        "bucket_credits_granted_total": 0,
        "bucket_credits_redeemed_total": 0,
        "bucket_credits_expired_total": 0,
        "suspension_count": 0,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.participants[participant["id"]] = participant
    return success_object(serialize_participant(participant), status=201)


@bp.route("/programs/<program_id>/participants", methods=["GET"])
def list_participants(program_id):
    require_roles("ProgramAdmin", "MunicipalAuditor")
    get_program_or_404(program_id)
    items = [p for p in db.participants.values() if p["program_id"] == program_id]
    if request.args.get("status"):
        items = [p for p in items if p["status"] == request.args["status"]]
    items = sort_created(items)
    page, limit, offset, total = paginate(items)
    return success_list([serialize_participant(p) for p in page], limit, offset, total)


@bp.route("/programs/<program_id>/participants/<participant_id>", methods=["GET"])
def get_participant(program_id, participant_id):
    user_id, role = require_roles("ProgramAdmin", "Participant", "MunicipalAuditor")
    get_program_or_404(program_id)
    participant = get_participant_or_404(participant_id, program_id)
    return success_object(serialize_participant(participant))


@bp.route("/programs/<program_id>/participants/<participant_id>/verify", methods=["POST"])
def verify_participant(program_id, participant_id):
    require_roles("Anonymous")
    get_program_or_404(program_id)
    participant = get_participant_or_404(participant_id, program_id)
    if participant["status"] != "PENDING_VERIFY":
        errors.raise_err(errors.ERR_INVALID_STATE, "Participant is not PENDING_VERIFY")
    data = body()
    require_fields(data, "verification_token")
    if data["verification_token"] != participant["verification_token"]:
        errors.raise_err(errors.ERR_INVALID_VERIFICATION_TOKEN, "Verification token mismatch")
    participant["status"] = "ACTIVE"
    participant["verification_token"] = None
    touch(participant)
    return success_object(serialize_participant(participant))


def _revoke_participant_grants(participant_id, bypass_bucket_check=True):
    for grant in db.grants.values():
        if grant["participant_id"] == participant_id and grant["status"] == "ACTIVE":
            if not bypass_bucket_check and grant.get("buckets_checked_out", 0) > 0:
                errors.raise_err(
                    errors.ERR_BUCKETS_STILL_OUT,
                    "Grant revoke blocked while buckets_checked_out > 0",
                )
            grant["status"] = "REVOKED"
            touch(grant)


@bp.route("/programs/<program_id>/participants/<participant_id>/suspend", methods=["POST"])
def suspend_participant(program_id, participant_id):
    require_roles("ProgramAdmin")
    get_program_or_404(program_id)
    participant = get_participant_or_404(participant_id, program_id)
    if participant["status"] != "ACTIVE":
        errors.raise_err(errors.ERR_INVALID_STATE, "Participant must be ACTIVE to suspend")
    participant["suspension_count"] += 1
    if participant["suspension_count"] >= 3:
        participant["status"] = "DEACTIVATED"
    else:
        participant["status"] = "SUSPENDED"
    _revoke_participant_grants(participant["id"], bypass_bucket_check=True)
    touch(participant)
    return success_object(serialize_participant(participant))


@bp.route("/programs/<program_id>/participants/<participant_id>/reinstate", methods=["POST"])
def reinstate_participant(program_id, participant_id):
    require_roles("ProgramAdmin")
    get_program_or_404(program_id)
    participant = get_participant_or_404(participant_id, program_id)
    if participant["status"] != "SUSPENDED":
        errors.raise_err(errors.ERR_INVALID_STATE, "Participant must be SUSPENDED to reinstate")
    if participant["suspension_count"] >= 3:
        errors.raise_err(
            errors.ERR_PARTICIPANT_PERMANENTLY_DEACTIVATED,
            "Reinstate blocked: suspension_count >= 3",
        )
    participant["status"] = "ACTIVE"
    touch(participant)
    return success_object(serialize_participant(participant))


@bp.route("/programs/<program_id>/participants/<participant_id>/deactivate", methods=["POST"])
def deactivate_participant(program_id, participant_id):
    require_roles("ProgramAdmin")
    get_program_or_404(program_id)
    participant = get_participant_or_404(participant_id, program_id)
    if participant["status"] not in ("ACTIVE", "SUSPENDED"):
        errors.raise_err(
            errors.ERR_INVALID_STATE,
            "Participant must be ACTIVE or SUSPENDED to deactivate",
        )
    has_pending = any(
        a["participant_id"] == participant["id"] and a["status"] == "REQUESTED"
        for a in db.allocations.values()
    )
    if has_pending:
        errors.raise_err(
            errors.ERR_PARTICIPANT_HAS_PENDING_ALLOCATIONS,
            "Deactivate blocked by REQUESTED DistributionAllocations",
        )
    _revoke_participant_grants(participant["id"], bypass_bucket_check=True)
    credits.expire_all_balance(participant["id"])
    participant["status"] = "DEACTIVATED"
    touch(participant)
    return success_object(serialize_participant(participant))


# ---------------------------------------------------------------------------
# AccessGrants
# ---------------------------------------------------------------------------

@bp.route("/programs/<program_id>/participants/<participant_id>/grants", methods=["POST"])
def create_grant(program_id, participant_id):
    require_roles("ProgramAdmin")
    get_program_or_404(program_id)
    participant = get_participant_or_404(participant_id, program_id)
    data = body()
    require_fields(data, "site_id", "bucket_quota", "expires_at")
    site = get_site_or_404(data["site_id"], program_id)
    bucket_quota = require_int(data, "bucket_quota")
    expires_at = require_dt_field(data, "expires_at")

    now = db.iso_now()
    grant = {
        "id": db.new_id(),
        "participant_id": participant["id"],
        "site_id": site["id"],
        "access_code": _mint_access_code(site["id"]),
        "bucket_quota": bucket_quota,
        "buckets_checked_out": 0,
        "status": "ACTIVE",
        "expires_at": expires_at,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.grants[grant["id"]] = grant
    return success_object(serialize_grant(grant), status=201)


@bp.route("/programs/<program_id>/participants/<participant_id>/grants", methods=["GET"])
def list_grants(program_id, participant_id):
    require_roles("ProgramAdmin", "Participant", "MunicipalAuditor")
    get_program_or_404(program_id)
    get_participant_or_404(participant_id, program_id)
    items = [g for g in db.grants.values() if g["participant_id"] == participant_id]
    if request.args.get("status"):
        items = [g for g in items if g["status"] == request.args["status"]]
    items = sort_created(items)
    page, limit, offset, total = paginate(items)
    return success_list([serialize_grant(g) for g in page], limit, offset, total)


@bp.route(
    "/programs/<program_id>/participants/<participant_id>/grants/<grant_id>/revoke",
    methods=["POST"],
)
def revoke_grant(program_id, participant_id, grant_id):
    require_roles("ProgramAdmin")
    get_program_or_404(program_id)
    get_participant_or_404(participant_id, program_id)
    grant = get_grant_or_404(grant_id, participant_id)
    if grant["status"] != "ACTIVE":
        errors.raise_err(errors.ERR_INVALID_STATE, "Grant must be ACTIVE to revoke")
    if grant.get("buckets_checked_out", 0) > 0:
        errors.raise_err(
            errors.ERR_BUCKETS_STILL_OUT,
            "Grant revoke blocked while buckets_checked_out > 0",
        )
    grant["status"] = "REVOKED"
    touch(grant)
    return success_object(serialize_grant(grant))


# --- Flat aliases ---

@bp.route("/participants", methods=["GET"])
def list_participants_flat():
    require_roles("ProgramAdmin", "MunicipalAuditor")
    items = list(db.participants.values())
    if request.args.get("program_id"):
        items = [p for p in items if p["program_id"] == request.args["program_id"]]
    if request.args.get("status"):
        items = [p for p in items if p["status"] == request.args["status"]]
    items = sort_created(items)
    page, limit, offset, total = paginate(items)
    return success_list([serialize_participant(p) for p in page], limit, offset, total)


@bp.route("/participants/<participant_id>", methods=["GET"])
def get_participant_flat(participant_id):
    require_roles("ProgramAdmin", "Participant", "MunicipalAuditor")
    participant = get_participant_or_404(participant_id)
    return success_object(serialize_participant(participant))


@bp.route("/grants", methods=["GET"])
def list_grants_flat():
    require_roles("ProgramAdmin", "Participant", "MunicipalAuditor")
    items = list(db.grants.values())
    if request.args.get("participant_id"):
        items = [g for g in items if g["participant_id"] == request.args["participant_id"]]
    if request.args.get("site_id"):
        items = [g for g in items if g["site_id"] == request.args["site_id"]]
    if request.args.get("status"):
        items = [g for g in items if g["status"] == request.args["status"]]
    items = sort_created(items)
    page, limit, offset, total = paginate(items)
    return success_list([serialize_grant(g) for g in page], limit, offset, total)


@bp.route("/grants/<grant_id>", methods=["GET"])
def get_grant_flat(grant_id):
    require_roles("ProgramAdmin", "Participant", "MunicipalAuditor")
    grant = get_grant_or_404(grant_id)
    return success_object(serialize_grant(grant))
