"""Property endpoints and property-scoped reverse-reachability lists."""

from flask import Blueprint, g, request

import errors
from db import db, new_id, now_ts
from middleware import require_roles
from response import success, list_success
from serializers import (
    serialize_property, serialize_elevation_certificate, serialize_policy,
)
from helpers import (
    get_body, require_str, require_enum, require_number, opt_bool,
    parse_pagination, paginate, sort_by_created,
)

bp = Blueprint("properties", __name__)

FLOOD_ZONES = {"VE", "AE", "X"}
OCCUPANCIES = {"PRIMARY_RESIDENCE", "NON_PRIMARY"}


@bp.route("/properties", methods=["POST"])
@require_roles("PolicyHolder", "Underwriter")
def create_property():
    body = get_body()
    community_id = require_str(body, "community_id")
    owner_id = require_str(body, "owner_id")
    address = require_str(body, "address")
    flood_zone = require_enum(body, "flood_zone", FLOOD_ZONES)
    occupancy = require_enum(body, "occupancy", OCCUPANCIES)
    base_flood_elevation_ft = require_number(body, "base_flood_elevation_ft")
    has_active_mortgage = opt_bool(body, "has_active_mortgage", False)

    # Existence: community_id FK must resolve (priority 3).
    if db.communities.get(community_id) is None:
        raise errors.not_found("Community not found")

    # Ownership (priority 4): a PolicyHolder may only register a property they own.
    if g.user_role == "PolicyHolder" and owner_id != g.user_id:
        raise errors.not_resource_owner("owner_id must equal the acting PolicyHolder")

    is_sfha = flood_zone in ("VE", "AE")

    ts = now_ts()
    pid = new_id()
    record = {
        "id": pid,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "community_id": community_id,
        "owner_id": owner_id,
        "address": address,
        "flood_zone": flood_zone,
        "is_sfha": is_sfha,
        "occupancy": occupancy,
        "base_flood_elevation_ft": base_flood_elevation_ft,
        "has_active_mortgage": has_active_mortgage,
        "loss_history_count": 0,
        "is_repetitive_loss": False,
        "compliance_status": "NOT_REQUIRED",
        "active_policy_id": None,
    }
    db.properties[pid] = record
    return success(serialize_property(record), status=201)


@bp.route("/properties/<pid>", methods=["GET"])
@require_roles("PolicyHolder", "Underwriter", "Adjuster", "FemaAdmin")
def get_property(pid):
    record = db.properties.get(pid)
    if record is None:
        raise errors.not_found("Property not found")
    if g.user_role == "PolicyHolder" and record["owner_id"] != g.user_id:
        raise errors.not_resource_owner("Not the owner of this property")
    return success(serialize_property(record), status=200)


@bp.route("/properties", methods=["GET"])
@require_roles("PolicyHolder", "Underwriter", "Adjuster", "FemaAdmin")
def list_properties():
    limit, offset = parse_pagination()
    owner_id = request.args.get("owner_id")
    community_id = request.args.get("community_id")

    items = list(db.properties.values())
    if owner_id is not None:
        items = [p for p in items if p["owner_id"] == owner_id]
    if community_id is not None:
        items = [p for p in items if p["community_id"] == community_id]

    # Holder-scoped read: PolicyHolder only sees properties they own.
    if g.user_role == "PolicyHolder":
        items = [p for p in items if p["owner_id"] == g.user_id]

    items = sort_by_created(items)
    page, total = paginate(items, limit, offset)
    return list_success([serialize_property(p) for p in page], limit, offset, total)


@bp.route("/properties/<pid>/elevation-certificates", methods=["GET"])
@require_roles("PolicyHolder", "Underwriter", "Adjuster", "FemaAdmin")
def list_property_certificates(pid):
    prop = db.properties.get(pid)
    if prop is None:
        raise errors.not_found("Property not found")
    if g.user_role == "PolicyHolder" and prop["owner_id"] != g.user_id:
        raise errors.not_resource_owner("Not the owner of this property")
    limit, offset = parse_pagination()
    items = [e for e in db.elevation_certificates.values() if e["property_id"] == pid]
    items = sort_by_created(items)
    page, total = paginate(items, limit, offset)
    return list_success([serialize_elevation_certificate(e) for e in page], limit, offset, total)


@bp.route("/properties/<pid>/policies", methods=["GET"])
@require_roles("PolicyHolder", "Underwriter", "Adjuster", "FemaAdmin")
def list_property_policies(pid):
    prop = db.properties.get(pid)
    if prop is None:
        raise errors.not_found("Property not found")
    if g.user_role == "PolicyHolder" and prop["owner_id"] != g.user_id:
        raise errors.not_resource_owner("Not the owner of this property")
    limit, offset = parse_pagination()
    items = [p for p in db.policies.values() if p["property_id"] == pid]
    items = sort_by_created(items)
    page, total = paginate(items, limit, offset)
    return list_success([serialize_policy(p) for p in page], limit, offset, total)
