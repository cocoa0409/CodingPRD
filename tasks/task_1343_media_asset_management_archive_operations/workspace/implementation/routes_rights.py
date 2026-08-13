"""RightsGrant, LegalHold and RetentionPolicy routes."""
from flask import Blueprint, request

import cascades
from auth import ALL_ROLES, require_roles
from db import STORE, new_id, now, stamp
from envelope import ok, paginate
from errors import raise_err
from serializers import grant_out, hold_out, policy_out
from validate import (
    GRANT_TYPES, MEDIA_TYPES, RESTRICTION_FLAGS, TERRITORIES,
    body, opt_bool, opt_enum_list, req_dt, req_enum, req_int, req_str,
)

bp = Blueprint("rights", __name__, url_prefix="/archive")


def _get_asset(aid):
    rec = STORE.assets.get(aid)
    if rec is None:
        raise_err("ERR_ASSET_NOT_FOUND", "Asset not found")
    return rec


def _get_grant(gid):
    rec = STORE.grants.get(gid)
    if rec is None:
        raise_err("ERR_GRANT_NOT_FOUND", "Rights grant not found")
    return rec


def _get_hold(hid):
    rec = STORE.holds.get(hid)
    if rec is None:
        raise_err("ERR_HOLD_NOT_FOUND", "Legal hold not found")
    return rec


# --- RightsGrant ---------------------------------------------------------------
@bp.post("/rights-grants")
def create_grant():
    require_roles("RightsManager")
    j = body()
    asset_id = req_str(j, "asset_id")
    _get_asset(asset_id)
    grant_type = req_enum(j, "grant_type", GRANT_TYPES)
    territory = req_enum(j, "territory", TERRITORIES)
    exclusive = opt_bool(j, "exclusive", False)
    window_start = req_dt(j, "window_start")
    window_end = req_dt(j, "window_end")
    restriction_flags = opt_enum_list(j, "restriction_flags", RESTRICTION_FLAGS, [])
    # Window well-formedness
    if not (window_start < window_end):
        raise_err("ERR_INVALID_REQUEST", "window_start must be strictly before window_end")
    # Temporal: window must reach into the future
    if window_end <= now():
        raise_err("ERR_RIGHTS_WINDOW_PAST", "window_end must be after the current time")
    # Exclusive non-overlap (half-open; adjacency allowed)
    if exclusive:
        for g in STORE.grants.values():
            if (
                g["asset_id"] == asset_id
                and g["status"] == "ACTIVE"
                and g["exclusive"]
                and g["grant_type"] == grant_type
                and g["territory"] == territory
                and window_start < g["window_end"]
                and g["window_start"] < window_end
            ):
                raise_err(
                    "ERR_EXCLUSIVE_GRANT_OVERLAP",
                    "Exclusive grant window overlaps an existing ACTIVE exclusive grant",
                )
    rec = {
        "id": new_id(),
        "asset_id": asset_id,
        "grant_type": grant_type,
        "territory": territory,
        "exclusive": exclusive,
        "window_start": window_start,
        "window_end": window_end,
        "restriction_flags": restriction_flags,
        "status": "ACTIVE",
    }
    stamp(rec)
    STORE.grants[rec["id"]] = rec
    return ok(grant_out(rec), 201)


@bp.get("/rights-grants")
def list_grants():
    require_roles(*ALL_ROLES)
    recs = list(STORE.grants.values())
    for param, field in (
        ("asset_id", "asset_id"),
        ("status", "status"),
        ("grant_type", "grant_type"),
    ):
        v = request.args.get(param)
        if v is not None:
            recs = [r for r in recs if r[field] == v]
    return paginate(recs, grant_out)


@bp.get("/rights-grants/<gid>")
def get_grant(gid):
    require_roles(*ALL_ROLES)
    return ok(grant_out(_get_grant(gid)))


@bp.post("/rights-grants/<gid>/revoke")
def revoke_grant(gid):
    require_roles("RightsManager")
    rec = _get_grant(gid)
    if rec["status"] != "ACTIVE":
        raise_err("ERR_GRANT_ALREADY_REVOKED", "Grant is already REVOKED")
    rec["status"] = "REVOKED"
    rec["updated_at"] = now()
    rec["version"] += 1
    return ok(grant_out(rec))


# --- LegalHold -------------------------------------------------------------------
@bp.post("/legal-holds")
def create_hold():
    uid, _ = require_roles("LegalCounsel")
    j = body()
    asset_id = req_str(j, "asset_id")
    asset = _get_asset(asset_id)
    matter_reference = req_str(j, "matter_reference")
    reason = req_str(j, "reason")
    rec = {
        "id": new_id(),
        "asset_id": asset_id,
        "matter_reference": matter_reference,
        "reason": reason,
        "placed_by_user_id": uid,
        "status": "ACTIVE",
        "released_by_user_id": None,
        "released_at": None,
    }
    stamp(rec)
    STORE.holds[rec["id"]] = rec
    cascades.legal_hold_place_cascade(asset)
    return ok(hold_out(rec), 201)


@bp.get("/legal-holds")
def list_holds():
    require_roles(*ALL_ROLES)
    recs = list(STORE.holds.values())
    for param, field in (("asset_id", "asset_id"), ("status", "status")):
        v = request.args.get(param)
        if v is not None:
            recs = [r for r in recs if r[field] == v]
    return paginate(recs, hold_out)


@bp.get("/legal-holds/<hid>")
def get_hold(hid):
    require_roles(*ALL_ROLES)
    return ok(hold_out(_get_hold(hid)))


@bp.post("/legal-holds/<hid>/release")
def release_hold(hid):
    uid, _ = require_roles("LegalCounsel")
    rec = _get_hold(hid)
    if rec["status"] != "ACTIVE":
        raise_err("ERR_HOLD_ALREADY_RELEASED", "Hold is already RELEASED")
    if uid == rec["placed_by_user_id"]:
        raise_err("ERR_SOD_HOLD_SELF_RELEASE", "Releaser must differ from the placer")
    rec["status"] = "RELEASED"
    rec["released_by_user_id"] = uid
    rec["released_at"] = now()
    rec["updated_at"] = now()
    rec["version"] += 1
    asset = STORE.assets.get(rec["asset_id"])
    if asset is not None:
        cascades.legal_hold_release_cascade(asset)
    return ok(hold_out(rec))


# --- RetentionPolicy ---------------------------------------------------------------
@bp.post("/retention-policies")
def create_policy():
    require_roles("SystemAdmin")
    j = body()
    media_type = req_enum(j, "media_type", MEDIA_TYPES)
    min_retention_years = req_int(j, "min_retention_years")
    requires_legal_review = opt_bool(j, "requires_legal_review", False)
    for p in STORE.policies.values():
        if p["media_type"] == media_type:
            raise_err(
                "ERR_DUPLICATE_MEDIA_TYPE_POLICY",
                "A retention policy already exists for this media_type",
            )
    rec = {
        "id": new_id(),
        "media_type": media_type,
        "min_retention_years": min_retention_years,
        "requires_legal_review": requires_legal_review,
    }
    stamp(rec)
    STORE.policies[rec["id"]] = rec
    return ok(policy_out(rec), 201)


@bp.get("/retention-policies")
def list_policies():
    require_roles(*ALL_ROLES)
    recs = list(STORE.policies.values())
    v = request.args.get("media_type")
    if v is not None:
        recs = [r for r in recs if r["media_type"] == v]
    return paginate(recs, policy_out)
