"""Identity routes (PRD §3.2, §3.5, §3.6).

Covers identity create/get/list, direct grants (OCC-guarded, JIT windows),
disable (cascade revoke), enable (no resurrection), deprovision, and the
nested grant/audit-event listings.
"""
from flask import Blueprint, request

import db
import errors
from errors import err
from middleware import require_role, get_json_body
from response import object_response, array_response
from services.common import (
    serialize, require_string, optional_bool, require_int,
    parse_pagination, paginate, filter_enum_param, filter_bool_param,
    optional_string, parse_iso8601,
)
from services import domain

bp = Blueprint("identities", __name__)

READ_ROLES = {"AccessManager", "AccessApprover", "CampaignAdmin", "Certifier"}
IDENTITY_STATUS = {"ACTIVE", "DISABLED", "DEPROVISIONED"}
GRANT_LIFECYCLE = {"PROVISIONING", "ACTIVE", "REVOKED"}
GRANT_REVIEW = {"NOT_DUE", "UNDER_REVIEW", "CERTIFIED", "FLAGGED"}
EVENT_TYPES = {
    "GRANT_ACTIVATED", "GRANT_REVOKED", "REQUEST_APPROVED", "REQUEST_REJECTED",
    "IDENTITY_DISABLED", "ITEM_CERTIFIED", "ORPHAN_DETECTED",
}


def _new_identity(display_name, email, is_human):
    common = db.new_common()
    record = {
        "id": common["id"],
        "created_at": common["created_at"],
        "updated_at": common["updated_at"],
        "version": common["version"],
        "_seq": common["_seq"],
        "display_name": display_name,
        "email": email,
        "is_human": is_human,
        "status": "ACTIVE",
        "active_grant_count": 0,
        "privileged_entitlement_count": 0,
        "effective_risk_score": 0,
        "projected_risk_score": 0,
        "is_orphan": False,
    }
    record["is_orphan"] = domain.compute_is_orphan(record)
    return record


@bp.route("/identities", methods=["POST"])
def create_identity():
    require_role({"AccessManager"})
    body = get_json_body()
    display_name = require_string(body, "display_name")
    email = require_string(body, "email")
    is_human = optional_bool(body, "is_human", True)
    with db.LOCK:
        record = _new_identity(display_name, email, is_human)
        db.identities[record["id"]] = record
        return object_response(serialize(record), 201)


@bp.route("/identities/<id>", methods=["GET"])
def get_identity_route(id):
    require_role(READ_ROLES)
    with db.LOCK:
        record = db.identities.get(id)
        if record is None:
            raise err(errors.ERR_NOT_FOUND, "Identity not found")
        return object_response(serialize(record), 200)


@bp.route("/identities", methods=["GET"])
def list_identities():
    require_role(READ_ROLES)
    status = filter_enum_param(request.args, "status", IDENTITY_STATUS)
    is_orphan = filter_bool_param(request.args, "is_orphan")
    is_human = filter_bool_param(request.args, "is_human")
    limit, offset = parse_pagination(request.args)
    with db.LOCK:
        records = list(db.identities.values())
        if status is not None:
            records = [r for r in records if r["status"] == status]
        if is_orphan is not None:
            records = [r for r in records if r["is_orphan"] == is_orphan]
        if is_human is not None:
            records = [r for r in records if r["is_human"] == is_human]
        items, total = paginate(records, limit, offset)
        return array_response(items, limit, offset, total, 200)


@bp.route("/identities/<id>/grants", methods=["POST"])
def direct_grant(id):
    user_id, _ = require_role({"AccessManager"})
    body = get_json_body()
    with db.LOCK:
        identity = db.identities.get(id)
        if identity is None:
            raise err(errors.ERR_NOT_FOUND, "Identity not found")

        # Body fields / FK existence.
        entitlement_id = require_string(body, "entitlement_id")
        expected_version = require_int(body, "expected_identity_version")
        ent = db.entitlements.get(entitlement_id)
        if ent is None:
            raise err(errors.ERR_NOT_FOUND, "Entitlement not found")

        is_jit = optional_bool(body, "is_just_in_time", False)
        eff_from_raw = optional_string(body, "effective_from")
        eff_until_raw = optional_string(body, "effective_until")

        eff_from = None
        eff_until = None
        if eff_from_raw is not None:
            eff_from = parse_iso8601(eff_from_raw, "effective_from")
        if eff_until_raw is not None:
            eff_until = parse_iso8601(eff_until_raw, "effective_until")
        if is_jit:
            if eff_from is None or eff_until is None:
                raise err(errors.ERR_VALIDATION,
                          "JIT grant requires effective_from and effective_until")
            if not (eff_until > eff_from):
                raise err(errors.ERR_VALIDATION,
                          "effective_until must be strictly after effective_from")

        # State gate: identity must be ACTIVE to receive a grant.
        if identity["status"] != "ACTIVE":
            raise err(errors.ERR_IDENTITY_NOT_ACTIVE, "Identity is not ACTIVE")

        # Archived entitlement may not be granted.
        if ent["status"] != "ACTIVE":
            raise err(errors.ERR_ENTITLEMENT_ARCHIVED, "Entitlement is not ACTIVE")

        # JIT window overlap on (identity, entitlement) — half-open intervals.
        if is_jit:
            for g in db.grants.values():
                if (g["identity_id"] == id
                        and g["entitlement_id"] == entitlement_id
                        and g.get("is_just_in_time")
                        and g.get("effective_from") is not None
                        and g.get("effective_until") is not None):
                    g_from = parse_iso8601(g["effective_from"], "effective_from")
                    g_until = parse_iso8601(g["effective_until"], "effective_until")
                    # Overlap iff start < other_end AND other_start < end.
                    if eff_from < g_until and g_from < eff_until:
                        raise err(errors.ERR_JIT_WINDOW_OVERLAP,
                                  "JIT window overlaps an existing grant")

        # OCC: expected_identity_version must match current version.
        if expected_version != identity["version"]:
            raise err(errors.ERR_STALE_VERSION,
                      "expected_identity_version does not match current version")

        risk_before = identity["effective_risk_score"]
        grant = domain.create_and_activate_grant(
            identity=identity,
            entitlement_id=entitlement_id,
            source_request_id=None,
            is_just_in_time=is_jit,
            effective_from=eff_from_raw,
            effective_until=eff_until_raw,
            actor_user_id=user_id,
            touch_identity=False,
        )
        domain.apply_high_risk_flag(identity, risk_before, [grant])
        # The direct-grant operation bumps the identity version exactly once
        # (PRD §3.2 / §2.8 OCC supersede). The activation recompute above ran
        # without its own version bump (touch_identity=False) so this is the
        # single increment for the whole operation.
        db.touch(identity)
        return object_response(serialize(grant), 201)


@bp.route("/identities/<id>/disable", methods=["POST"])
def disable_identity(id):
    user_id, _ = require_role({"AccessManager"})
    body = get_json_body()
    with db.LOCK:
        identity = db.identities.get(id)
        if identity is None:
            raise err(errors.ERR_NOT_FOUND, "Identity not found")
        expected_version = require_int(body, "expected_identity_version")
        if identity["status"] != "ACTIVE":
            raise err(errors.ERR_INVALID_STATE, "Identity is not ACTIVE")
        if expected_version != identity["version"]:
            raise err(errors.ERR_STALE_VERSION,
                      "expected_identity_version does not match current version")

        # CASCADE: revoke every ACTIVE grant of this identity.
        active = [g for g in db.grants.values()
                  if g["identity_id"] == id and g["lifecycle_status"] == "ACTIVE"]
        active.sort(key=lambda g: g.get("_seq", 0))
        for g in active:
            domain.revoke_grant(g, identity, "system")

        identity["status"] = "DISABLED"
        db.touch(identity)
        domain.append_audit(id, "IDENTITY_DISABLED", user_id,
                            "Identity %s disabled" % id)
        return object_response(serialize(identity), 200)


@bp.route("/identities/<id>/enable", methods=["POST"])
def enable_identity(id):
    require_role({"AccessManager"})
    body = get_json_body()
    with db.LOCK:
        identity = db.identities.get(id)
        if identity is None:
            raise err(errors.ERR_NOT_FOUND, "Identity not found")
        expected_version = require_int(body, "expected_identity_version")
        if identity["status"] != "DISABLED":
            raise err(errors.ERR_INVALID_STATE, "Identity is not DISABLED")
        if expected_version != identity["version"]:
            raise err(errors.ERR_STALE_VERSION,
                      "expected_identity_version does not match current version")
        identity["status"] = "ACTIVE"
        # No grant resurrection; recompute counters/orphan from current (empty)
        # active-grant state.
        domain.recompute_identity_counters(identity, touch_record=False)
        db.touch(identity)
        return object_response(serialize(identity), 200)


@bp.route("/identities/<id>/deprovision", methods=["POST"])
def deprovision_identity(id):
    require_role({"AccessManager"})
    with db.LOCK:
        identity = db.identities.get(id)
        if identity is None:
            raise err(errors.ERR_NOT_FOUND, "Identity not found")
        if identity["status"] != "DISABLED":
            raise err(errors.ERR_INVALID_STATE, "Identity is not DISABLED")
        if identity["active_grant_count"] != 0:
            raise err(errors.ERR_IDENTITY_HAS_ACTIVE_GRANTS,
                      "Identity still has active grants")
        identity["status"] = "DEPROVISIONED"
        domain.recompute_identity_counters(identity, touch_record=False)
        db.touch(identity)
        return object_response(serialize(identity), 200)


@bp.route("/identities/<id>/grants", methods=["GET"])
def list_identity_grants(id):
    require_role(READ_ROLES)
    lifecycle = filter_enum_param(request.args, "lifecycle_status", GRANT_LIFECYCLE)
    review = filter_enum_param(request.args, "review_status", GRANT_REVIEW)
    limit, offset = parse_pagination(request.args)
    with db.LOCK:
        if db.identities.get(id) is None:
            raise err(errors.ERR_NOT_FOUND, "Identity not found")
        records = [g for g in db.grants.values() if g["identity_id"] == id]
        if lifecycle is not None:
            records = [g for g in records if g["lifecycle_status"] == lifecycle]
        if review is not None:
            records = [g for g in records if g["review_status"] == review]
        items, total = paginate(records, limit, offset)
        return array_response(items, limit, offset, total, 200)


@bp.route("/identities/<id>/audit-events", methods=["GET"])
def list_identity_audit_events(id):
    require_role(READ_ROLES)
    event_type = filter_enum_param(request.args, "event_type", EVENT_TYPES)
    limit, offset = parse_pagination(request.args)
    with db.LOCK:
        if db.identities.get(id) is None:
            raise err(errors.ERR_NOT_FOUND, "Identity not found")
        records = [a for a in db.audit_events.values()
                   if a["subject_identity_id"] == id]
        if event_type is not None:
            records = [a for a in records if a["event_type"] == event_type]
        items, total = paginate(records, limit, offset)
        return array_response(items, limit, offset, total, 200)
