"""Households, Members, Manufacturers, and the logical clock."""
from flask import Blueprint

import store
import serializers as S
from common import (
    bad_request, get_body, ok, ok_list, optional_bool, optional_enum,
    paginate, require_auth, require_enum, require_household_member, require_str,
    resolve_or_404,
)
from errors import ApiError
from util import new_id, now_iso, parse_dt

bp_core = Blueprint("core", __name__)

READ_ROLES_HH = ["HouseholdOwner", "HouseholdMember", "ConciergeAgent", "ManufacturerAgent", "PlatformAdmin"]
READ_ROLES_MEMBER = ["HouseholdOwner", "HouseholdMember", "ConciergeAgent", "PlatformAdmin"]


def _new_common(kind):
    ts = now_iso()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": store.next_seq(),
    }


# ------------------------------------------------------------ households ----
@bp_core.route("/households", methods=["POST"])
def create_household():
    body = get_body()
    primary_email = require_str(body, "primary_email")
    display_name = require_str(body, "display_name")
    mode = optional_enum(body, "exposure_scoring_mode", {"WEIGHTED", "COUNT"}, "WEIGHTED")
    rec = _new_common("household")
    rec.update({
        "primary_email": primary_email,
        "display_name": display_name,
        "exposure_scoring_mode": mode,
        "recall_exposure_score": 0,
        "active_claim_count": 0,
        "status": "ACTIVE",
    })
    store.households[rec["id"]] = rec
    return ok(S.household(rec), 201)


@bp_core.route("/households/<hid>/members", methods=["POST"])
def create_member(hid):
    household = store.households.get(hid)
    if household is None:
        raise ApiError("ERR_NOT_FOUND")
    existing = [m for m in store.members.values() if m["household_id"] == hid]
    role_hdr, uid = None, None
    from flask import request
    role_hdr = request.headers.get("X-User-Role")
    uid = request.headers.get("X-User-ID")

    body = get_body()

    if not existing:
        # First member: open self-service creation of the OWNER.
        full_name = require_str(body, "full_name")
        email = require_str(body, "email")
        role = require_enum(body, "role", {"OWNER", "ADULT", "MINOR"})
        if role != "OWNER":
            raise bad_request("The first member of a household must be the OWNER.")
    else:
        # Subsequent members require an authenticated HouseholdOwner of this household.
        if not role_hdr or not uid or role_hdr not in {
            "Anonymous", "HouseholdOwner", "HouseholdMember", "ConciergeAgent",
            "ManufacturerAgent", "PlatformAdmin",
        }:
            raise ApiError("ERR_UNAUTHENTICATED")
        if role_hdr != "HouseholdOwner":
            raise ApiError("ERR_UNAUTHORIZED")
        require_household_member(uid, hid, require_owner=True)
        full_name = require_str(body, "full_name")
        email = require_str(body, "email")
        role = require_enum(body, "role", {"OWNER", "ADULT", "MINOR"})
        if role == "OWNER":
            raise bad_request("A household may have only one OWNER; add ADULT or MINOR members.")

    rec = _new_common("member")
    rec.update({
        "household_id": hid,
        "full_name": full_name,
        "email": email,
        "role": role,
        "status": "ACTIVE",
    })
    store.members[rec["id"]] = rec
    return ok(S.member(rec), 201)


@bp_core.route("/households/<hid>", methods=["GET"])
def get_household(hid):
    require_auth(READ_ROLES_HH)
    rec = resolve_or_404(store.households, hid)
    return ok(S.household(rec))


@bp_core.route("/members/<mid>", methods=["GET"])
def get_member(mid):
    require_auth(READ_ROLES_MEMBER)
    rec = resolve_or_404(store.members, mid)
    return ok(S.member(rec))


@bp_core.route("/members", methods=["GET"])
def list_members():
    require_auth(READ_ROLES_MEMBER)
    from flask import request
    hid = request.args.get("household_id")
    records = list(store.members.values())
    if hid is not None:
        records = [m for m in records if m["household_id"] == hid]
    items, pagination = paginate(records, S.member)
    return ok_list(items, pagination)


# --------------------------------------------------------- manufacturers ----
@bp_core.route("/manufacturers", methods=["POST"])
def create_manufacturer():
    require_auth(["PlatformAdmin"])
    body = get_body()
    name = require_str(body, "name")
    contact_email = require_str(body, "contact_email")
    coordination_enabled = optional_bool(body, "coordination_enabled", True)
    rma_required = optional_bool(body, "rma_required", True)
    rec = _new_common("manufacturer")
    rec.update({
        "name": name,
        "contact_email": contact_email,
        "coordination_enabled": coordination_enabled,
        "rma_required": rma_required,
    })
    store.manufacturers[rec["id"]] = rec
    return ok(S.manufacturer(rec), 201)


@bp_core.route("/manufacturers/<mid>", methods=["GET"])
def get_manufacturer(mid):
    require_auth(READ_ROLES_HH)
    rec = resolve_or_404(store.manufacturers, mid)
    return ok(S.manufacturer(rec))


# ----------------------------------------------------------------- clock ----
@bp_core.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require_auth(["PlatformAdmin"])
    body = get_body()
    to_iso = body.get("to_iso8601")
    if not isinstance(to_iso, str) or to_iso == "":
        raise bad_request("Field 'to_iso8601' is required.")
    try:
        parse_dt(to_iso)
    except (ValueError, TypeError):
        raise bad_request("Field 'to_iso8601' must be a valid ISO 8601 timestamp.")
    store.set_clock(to_iso)
    return ok({})
