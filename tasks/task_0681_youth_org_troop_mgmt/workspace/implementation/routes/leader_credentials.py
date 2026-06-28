"""Leader credentials: background check + training (PRD §3.4)."""
from datetime import datetime, timezone, timedelta

from flask import Blueprint, request

from db import db
from clock import clock
from errors import (
    err,
    ERR_INVALID_STATE,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_MEMBER_NOT_REGISTERED,
    ERR_INVALID_REQUEST,
)
from middleware import authenticate, require_roles, BOTH_ROLES, REGISTRAR_ONLY, LEADER_ONLY
from response import object_response, array_response
from serializers import serialize_leader_credential
from util import new_id, iso_now
from routes import helpers as h
from services import recompute

bp = Blueprint("leader_credentials", __name__)

# Training validity window (SCAFFOLD TRAINING_VALID_DAYS; not gated, set-only).
TRAINING_VALID_DAYS = 365


def _bump_owning_troop(member):
    troop = db.troops.get(member["troop_id"])
    if troop is not None:
        recompute.recompute_troop_counts(troop, bump=True)


@bp.post("/members/<member_id>/leader-credentials")
def open_credential(member_id):
    _, role = authenticate()
    require_roles(role, LEADER_ONLY)
    member = h.get_or_404(db.members, member_id)
    body = h.get_json_body()
    requested_by_user_id = h.require_string(body, "requested_by_user_id")

    # Only an ADULT can become a leader (PRD §3.4) -> ERR_MEMBER_NOT_REGISTERED.
    if member["member_type"] != "ADULT":
        raise err(ERR_MEMBER_NOT_REGISTERED, "leader credential requires an ADULT member")

    now = iso_now(datetime.now(timezone.utc))
    cred = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "member_id": member["id"],
        "requested_by_user_id": requested_by_user_id,
        "bgcheck_status": "NOT_STARTED",
        "training_status": "UNTRAINED",
        "training_expires_at": None,
        "_seq": db.next_seq(),
    }
    db.leader_credentials[cred["id"]] = cred
    return object_response(serialize_leader_credential(cred), status=201)


@bp.get("/leader-credentials/<cred_id>")
def get_credential(cred_id):
    _, role = authenticate()
    require_roles(role, BOTH_ROLES)
    cred = h.get_or_404(db.leader_credentials, cred_id)
    return object_response(serialize_leader_credential(cred))


@bp.get("/leader-credentials")
def list_credentials():
    _, role = authenticate()
    require_roles(role, BOTH_ROLES)
    member_id = request.args.get("member_id")
    limit, offset = h.parse_pagination()
    rows = [
        c for c in db.leader_credentials.values()
        if member_id is None or c["member_id"] == member_id
    ]
    rows = h.sort_by_creation(rows)
    page, total = h.paginate(rows, limit, offset)
    return array_response(
        [serialize_leader_credential(c) for c in page], limit, offset, total
    )


@bp.post("/leader-credentials/<cred_id>/start-bgcheck")
def start_bgcheck(cred_id):
    _, role = authenticate()
    require_roles(role, REGISTRAR_ONLY)
    cred = h.get_or_404(db.leader_credentials, cred_id)
    if cred["bgcheck_status"] != "NOT_STARTED":
        raise err(ERR_INVALID_STATE, "start-bgcheck only from NOT_STARTED")
    cred["bgcheck_status"] = "PENDING"
    h.touch_and_bump(cred)
    return object_response(serialize_leader_credential(cred))


@bp.post("/leader-credentials/<cred_id>/resolve-bgcheck")
def resolve_bgcheck(cred_id):
    user_id, role = authenticate()
    require_roles(role, REGISTRAR_ONLY)
    cred = h.get_or_404(db.leader_credentials, cred_id)
    body = h.get_json_body()

    # State precondition first (PRD §3.9: state before segregation of duties).
    if cred["bgcheck_status"] != "PENDING":
        raise err(ERR_INVALID_STATE, "resolve-bgcheck only from PENDING")

    # Segregation of duties: resolver != requested_by_user_id (PRD §3.4).
    if user_id == cred["requested_by_user_id"]:
        raise err(ERR_SEGREGATION_OF_DUTIES, "resolver must differ from requester")

    outcome = h.require_enum(body, "outcome", {"CLEAR", "FLAG"})
    cred["bgcheck_status"] = "CLEARED" if outcome == "CLEAR" else "FLAGGED"
    h.touch_and_bump(cred)

    member = db.members.get(cred["member_id"])
    if member is not None:
        _bump_owning_troop(member)
    return object_response(serialize_leader_credential(cred))


@bp.post("/leader-credentials/<cred_id>/complete-training")
def complete_training(cred_id):
    _, role = authenticate()
    require_roles(role, REGISTRAR_ONLY)
    cred = h.get_or_404(db.leader_credentials, cred_id)
    if cred["training_status"] != "UNTRAINED":
        raise err(ERR_INVALID_STATE, "complete-training only from UNTRAINED")
    cred["training_status"] = "TRAINED"
    expires = clock.now() + timedelta(days=TRAINING_VALID_DAYS)
    cred["training_expires_at"] = iso_now(expires)
    h.touch_and_bump(cred)

    member = db.members.get(cred["member_id"])
    if member is not None:
        _bump_owning_troop(member)
    return object_response(serialize_leader_credential(cred))
