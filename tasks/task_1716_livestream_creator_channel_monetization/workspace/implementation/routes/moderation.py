"""Moderator staff lifecycle and progressive viewer discipline (§3.5)."""

from datetime import timedelta

from flask import Blueprint, request

import db
import domain
from core import (ApiError, auth, body, err_invalid_request, err_invalid_state,
                  err_not_found, err_ownership, ok_obj, paginate, pagination,
                  req_enum, req_int, req_str, require_role)

bp = Blueprint("moderation", __name__)

SCOPES = ("TIMEOUT", "BAN")
ACTION_KINDS = ("TIMEOUT", "BAN")
MOD_READ_ROLES = ("PlatformAdmin", "Creator", "Moderator")
ACTION_READ_ROLES = ("PlatformAdmin", "Creator", "Moderator", "AppealsOfficer")
BAN_MIN_PRIOR_TIMEOUTS = 2


# ---------------------------------------------------------------------------
# Moderators
# ---------------------------------------------------------------------------
@bp.post("/api/channels/<channel_id>/moderators")
def invite_moderator(channel_id):
    uid, role = auth()
    b = body()
    moderator_handle = req_str(b, "moderator_handle")
    scopes = b.get("scopes")
    if not isinstance(scopes, list) or any(s not in SCOPES for s in scopes):
        raise err_invalid_request("Field 'scopes' must be a subset of [TIMEOUT, BAN]")
    require_role(role, ("Creator",))
    if domain.get_channel(channel_id) is None:
        raise err_not_found("Channel not found")
    if uid != channel_id:
        raise err_ownership()
    m = db.new_entity(
        channel_id=channel_id,
        moderator_handle=moderator_handle,
        scopes=list(scopes),
        moderator_status="INVITED",
    )
    db.store.moderators[m["id"]] = m
    return ok_obj(domain.moderator_json(m), status=201)


@bp.get("/api/moderators/<moderator_id>")
def get_moderator(moderator_id):
    uid, role = auth()
    require_role(role, MOD_READ_ROLES)
    m = db.store.moderators.get(moderator_id)
    if m is None:
        raise err_not_found("Moderator not found")
    return ok_obj(domain.moderator_json(m))


@bp.get("/api/channels/<channel_id>/moderators")
def list_moderators(channel_id):
    uid, role = auth()
    limit, offset = pagination()
    require_role(role, MOD_READ_ROLES)
    if domain.get_channel(channel_id) is None:
        raise err_not_found("Channel not found")
    mods = [m for m in db.store.moderators.values() if m["channel_id"] == channel_id]
    status = request.args.get("moderator_status")
    if status is not None:
        mods = [m for m in mods if m["moderator_status"] == status]
    return paginate(mods, limit, offset, domain.moderator_json)


@bp.post("/api/moderators/<moderator_id>/transition")
def transition_moderator(moderator_id):
    uid, role = auth()
    b = body()
    action = req_enum(b, "action", ("ACCEPT", "SUSPEND", "REINSTATE", "REMOVE"))
    if action == "ACCEPT":
        require_role(role, ("Moderator",))
    else:
        require_role(role, ("Creator",))
    m = db.store.moderators.get(moderator_id)
    if m is None:
        raise err_not_found("Moderator not found")
    # Identity: ACCEPT is self-service (X-User-ID == this Moderator.id);
    # the others are owner operations on the moderator's channel.
    if action == "ACCEPT":
        if uid != m["id"]:
            raise err_ownership("A moderator can only accept their own invite")
    else:
        if uid != m["channel_id"]:
            raise err_ownership()

    if action == "ACCEPT":
        if m["moderator_status"] != "INVITED":
            raise err_invalid_state("Only an INVITED moderator can accept")
        m["moderator_status"] = "ACTIVE"
    elif action == "SUSPEND":
        if m["moderator_status"] != "ACTIVE":
            raise err_invalid_state("Only an ACTIVE moderator can be suspended")
        m["moderator_status"] = "SUSPENDED"
    elif action == "REINSTATE":
        if m["moderator_status"] != "SUSPENDED":
            raise err_invalid_state("Only a SUSPENDED moderator can be reinstated")
        m["moderator_status"] = "ACTIVE"
    else:  # REMOVE
        if m["moderator_status"] not in ("ACTIVE", "SUSPENDED"):
            raise err_invalid_state("Only an ACTIVE or SUSPENDED moderator can be removed")
        m["moderator_status"] = "REMOVED"  # existing actions are NOT auto-reversed

    db.touch(m)
    return ok_obj(domain.moderator_json(m))


# ---------------------------------------------------------------------------
# Moderation actions
# ---------------------------------------------------------------------------
@bp.post("/api/channels/<channel_id>/moderation-actions")
def issue_moderation_action(channel_id):
    uid, role = auth()
    b = body()
    viewer_id = req_str(b, "viewer_id")
    action_kind = req_enum(b, "action_kind", ACTION_KINDS)
    reason = req_str(b, "reason")
    # Duration rules: TIMEOUT carries 1..10080 minutes; BAN must omit it.
    if action_kind == "TIMEOUT":
        duration_minutes = req_int(b, "duration_minutes", lo=1, hi=10080)
    else:
        if "duration_minutes" in b and b["duration_minutes"] is not None:
            raise err_invalid_request("duration_minutes must be omitted for BAN")
        duration_minutes = None
    require_role(role, ("Creator", "Moderator"))
    if domain.get_channel(channel_id) is None:
        raise err_not_found("Channel not found")
    viewer = db.store.viewers.get(viewer_id)
    if viewer is None or viewer["channel_id"] != channel_id:
        raise err_not_found("Viewer not found in this channel")
    if role == "Creator" and uid != channel_id:
        raise err_ownership()
    # Progressive discipline (priority 9): BAN requires >= 2 prior non-reversed
    # TIMEOUTs on this (channel, viewer) pair.
    if action_kind == "BAN" and domain.prior_timeout_count(channel_id, viewer_id) < BAN_MIN_PRIOR_TIMEOUTS:
        raise ApiError("ERR_PROGRESSIVE_DISCIPLINE", 409,
                       "BAN requires at least 2 prior non-reversed TIMEOUTs")
    # Moderator gating (priority 20): ACTIVE status, then scope match.
    moderator_id = None
    if role == "Moderator":
        mod = db.store.moderators.get(uid)
        if mod is None or mod["channel_id"] != channel_id:
            raise err_not_found("Moderator not found in this channel")
        if mod["moderator_status"] != "ACTIVE":
            raise ApiError("ERR_MODERATOR_NOT_ACTIVE", 409,
                           "Issuing moderator is not ACTIVE")
        if action_kind not in mod["scopes"]:
            raise ApiError("ERR_MODERATOR_SCOPE_MISSING", 403,
                           "Moderator lacks the scope matching action_kind")
        moderator_id = mod["id"]

    before = domain.viewer_standing(viewer)
    ts = db.now()
    a = db.new_entity(
        channel_id=channel_id,
        viewer_id=viewer_id,
        moderator_id=moderator_id,
        action_kind=action_kind,
        duration_minutes=duration_minutes,
        reason=reason,
        action_status="ACTIVE",
        issued_at=ts,
        expires_at=(ts + timedelta(minutes=duration_minutes)) if action_kind == "TIMEOUT" else None,
    )
    db.store.mod_actions[a["id"]] = a
    domain.recompute_standing_and_cascade(viewer, before)
    return ok_obj(domain.mod_action_json(a), status=201)


@bp.get("/api/moderation-actions/<moderation_action_id>")
def get_moderation_action(moderation_action_id):
    uid, role = auth()
    require_role(role, ACTION_READ_ROLES)
    a = db.store.mod_actions.get(moderation_action_id)
    if a is None:
        raise err_not_found("Moderation action not found")
    return ok_obj(domain.mod_action_json(a))


@bp.get("/api/moderation-actions")
def list_moderation_actions():
    uid, role = auth()
    limit, offset = pagination()
    require_role(role, ACTION_READ_ROLES)
    acts = list(db.store.mod_actions.values())
    for name in ("channel_id", "viewer_id", "moderator_id", "action_status"):
        v = request.args.get(name)
        if v is not None:
            acts = [a for a in acts if a[name] == v]
    return paginate(acts, limit, offset, domain.mod_action_json)


@bp.post("/api/moderation-actions/<moderation_action_id>/reverse")
def reverse_moderation_action(moderation_action_id):
    uid, role = auth()
    b = body()
    reason = b.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        raise err_invalid_request("Field 'reason' is required")
    require_role(role, ("Creator", "AppealsOfficer"))
    a = db.store.mod_actions.get(moderation_action_id)
    if a is None:
        raise err_not_found("Moderation action not found")
    if role == "Creator" and uid != a["channel_id"]:
        raise err_ownership()
    if a["action_status"] != "ACTIVE":
        raise err_invalid_state("Only an ACTIVE moderation action can be reversed")
    viewer = db.store.viewers.get(a["viewer_id"])
    before = domain.viewer_standing(viewer) if viewer is not None else None
    a["action_status"] = "REVERSED"  # actions_issued_count derives (excludes REVERSED)
    db.touch(a)
    if viewer is not None:
        domain.recompute_standing_and_cascade(viewer, before)
    return ok_obj(domain.mod_action_json(a))
