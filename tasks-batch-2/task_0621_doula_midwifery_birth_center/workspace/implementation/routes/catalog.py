"""Logical clock, Client, CarePackage, SupplyKit, Provider, Room routes."""
from flask import Blueprint, request

from db import db
from common import (stamp_new, touch, public, paginate, get_body,
                    require_string, require_int, require_enum, require_datetime)
from errors import err, ERR_DUPLICATE_RESOURCE
from middleware import require_auth, require_role, ALL_ROLES
from response import object_response, array_response
import lookup
from common import parse_dt

bp = Blueprint("catalog", __name__)


# ---------------------------------------------------------------------------
# Logical clock (§2.9)
# ---------------------------------------------------------------------------
@bp.route("/birth-center/_clock/set_current_utc", methods=["POST"])
def set_clock():
    _, role = require_auth()
    require_role(role, ["CenterAdmin"])
    body = get_body()
    iso = require_datetime(body, "to_iso8601")
    db.logical_clock = parse_dt(iso, "to_iso8601")
    return object_response({"now": iso}, 200)


# ---------------------------------------------------------------------------
# Client (§3.1)
# ---------------------------------------------------------------------------
@bp.route("/birth-center/clients", methods=["POST"])
def create_client():
    _, role = require_auth()
    require_role(role, ["IntakeCoordinator"])
    body = get_body()
    full_name = require_string(body, "full_name")
    date_of_birth = require_datetime(body, "date_of_birth")
    parity = require_int(body, "parity", minimum=0)
    insurance_payer = require_string(body, "insurance_payer", required=False, default="")
    policy_number = require_string(body, "policy_number", required=False, default="")
    rec = {
        "full_name": full_name,
        "date_of_birth": date_of_birth,
        "parity": parity,
        "insurance_payer": insurance_payer,
        "policy_number": policy_number,
        "status": "ACTIVE",
    }
    stamp_new(rec)
    db.clients[rec["id"]] = rec
    return object_response(public(rec), 201)


@bp.route("/birth-center/clients/<cid>", methods=["GET"])
def get_client(cid):
    _, role = require_auth()
    require_role(role, ALL_ROLES)
    rec = lookup.get_client(cid)
    return object_response(public(rec), 200)


@bp.route("/birth-center/clients", methods=["GET"])
def list_clients():
    _, role = require_auth()
    require_role(role, ALL_ROLES)
    status = request.args.get("status")
    records = [r for r in db.clients.values()
               if status is None or r["status"] == status]
    items, limit, offset, total = paginate(records)
    return array_response(items, limit, offset, total, 200)


@bp.route("/birth-center/clients/<cid>/archive", methods=["POST"])
def archive_client(cid):
    _, role = require_auth()
    require_role(role, ["IntakeCoordinator"])
    rec = lookup.get_client(cid)
    rec["status"] = "ARCHIVED"
    touch(rec)
    return object_response(public(rec), 200)


# ---------------------------------------------------------------------------
# CarePackage (§3.1) — immutable config; id == code; no version/updated_at.
# ---------------------------------------------------------------------------
@bp.route("/birth-center/care-packages", methods=["POST"])
def create_package():
    _, role = require_auth()
    require_role(role, ["CenterAdmin"])
    body = get_body()
    code = require_string(body, "code")
    package_type = require_enum(body, "package_type", {"BIRTH", "POSTPARTUM", "COMBINED"})
    global_fee_cents = require_int(body, "global_fee_cents", minimum=0)
    prenatal_visits_included = require_int(body, "prenatal_visits_included", minimum=0)
    postpartum_visits_included = require_int(body, "postpartum_visits_included", minimum=0)
    kit_sku = require_string(body, "kit_sku")
    # Uniqueness (priority 5) after well-formedness (priority 4).
    if code in db.care_packages:
        raise err(ERR_DUPLICATE_RESOURCE, "CarePackage code already exists")
    from common import iso_now
    from datetime import datetime, timezone
    rec = {
        "code": code,
        "package_type": package_type,
        "global_fee_cents": global_fee_cents,
        "prenatal_visits_included": prenatal_visits_included,
        "postpartum_visits_included": postpartum_visits_included,
        "kit_sku": kit_sku,
    }
    # CarePackage carries only id and created_at (no updated_at, no version).
    now = iso_now(datetime.now(timezone.utc))
    rec["id"] = code  # id == code for lookup
    rec["created_at"] = now
    rec["_seq"] = db.next_seq()
    db.care_packages[code] = rec
    return object_response(public(rec), 201)


@bp.route("/birth-center/care-packages/<code>", methods=["GET"])
def get_package(code):
    _, role = require_auth()
    require_role(role, ALL_ROLES)
    rec = lookup.get_care_package(code)
    return object_response(public(rec), 200)


@bp.route("/birth-center/care-packages", methods=["GET"])
def list_packages():
    _, role = require_auth()
    require_role(role, ALL_ROLES)
    kit_sku = request.args.get("kit_sku")
    package_type = request.args.get("package_type")
    records = [r for r in db.care_packages.values()
               if (kit_sku is None or r["kit_sku"] == kit_sku)
               and (package_type is None or r["package_type"] == package_type)]
    items, limit, offset, total = paginate(records)
    return array_response(items, limit, offset, total, 200)


# ---------------------------------------------------------------------------
# SupplyKit (§3.1) — id == sku.
# ---------------------------------------------------------------------------
@bp.route("/birth-center/supply-kits", methods=["POST"])
def create_kit():
    _, role = require_auth()
    require_role(role, ["CenterAdmin"])
    body = get_body()
    sku = require_string(body, "sku")
    name = require_string(body, "name")
    on_hand_count = require_int(body, "on_hand_count", minimum=0)
    if sku in db.supply_kits:
        raise err(ERR_DUPLICATE_RESOURCE, "SupplyKit sku already exists")
    rec = {
        "sku": sku,
        "name": name,
        "on_hand_count": on_hand_count,
        "reserved_count": 0,
        "consumed_count": 0,
    }
    stamp_new(rec)
    rec["id"] = sku  # id == sku for lookup
    db.supply_kits[sku] = rec
    return object_response(public(rec), 201)


@bp.route("/birth-center/supply-kits/<sku>", methods=["GET"])
def get_kit(sku):
    _, role = require_auth()
    require_role(role, ALL_ROLES)
    rec = lookup.get_supply_kit(sku)
    return object_response(public(rec), 200)


@bp.route("/birth-center/supply-kits", methods=["GET"])
def list_kits():
    _, role = require_auth()
    require_role(role, ALL_ROLES)
    records = list(db.supply_kits.values())
    items, limit, offset, total = paginate(records)
    return array_response(items, limit, offset, total, 200)


# ---------------------------------------------------------------------------
# Provider (§3.4)
# ---------------------------------------------------------------------------
@bp.route("/birth-center/providers", methods=["POST"])
def create_provider():
    _, role = require_auth()
    require_role(role, ["CenterAdmin"])
    body = get_body()
    full_name = require_string(body, "full_name")
    role_type = require_enum(body, "role_type", {"MIDWIFE", "DOULA"})
    license_number = require_string(body, "license_number")
    max_active_episodes = require_int(body, "max_active_episodes", minimum=1)
    rec = {
        "full_name": full_name,
        "role_type": role_type,
        "license_number": license_number,
        "max_active_episodes": max_active_episodes,
        "active_assignment_count": 0,
        "status": "AVAILABLE",
    }
    stamp_new(rec)
    db.providers[rec["id"]] = rec
    return object_response(public(rec), 201)


@bp.route("/birth-center/providers/<pid>", methods=["GET"])
def get_provider(pid):
    _, role = require_auth()
    require_role(role, ALL_ROLES)
    rec = lookup.get_provider(pid)
    return object_response(public(rec), 200)


@bp.route("/birth-center/providers", methods=["GET"])
def list_providers():
    _, role = require_auth()
    require_role(role, ALL_ROLES)
    role_type = request.args.get("role_type")
    status = request.args.get("status")
    records = [r for r in db.providers.values()
               if (role_type is None or r["role_type"] == role_type)
               and (status is None or r["status"] == status)]
    items, limit, offset, total = paginate(records)
    return array_response(items, limit, offset, total, 200)


# ---------------------------------------------------------------------------
# Room (§3.5)
# ---------------------------------------------------------------------------
@bp.route("/birth-center/rooms", methods=["POST"])
def create_room():
    _, role = require_auth()
    require_role(role, ["CenterAdmin"])
    body = get_body()
    name = require_string(body, "name")
    turnover_minutes = require_int(body, "turnover_minutes", required=False, default=0, minimum=0)
    rec = {
        "name": name,
        "turnover_minutes": turnover_minutes,
        "status": "OPEN",
    }
    stamp_new(rec)
    db.rooms[rec["id"]] = rec
    return object_response(public(rec), 201)


@bp.route("/birth-center/rooms/<rid>", methods=["GET"])
def get_room(rid):
    _, role = require_auth()
    require_role(role, ALL_ROLES)
    rec = lookup.get_room(rid)
    return object_response(public(rec), 200)


@bp.route("/birth-center/rooms", methods=["GET"])
def list_rooms():
    _, role = require_auth()
    require_role(role, ALL_ROLES)
    status = request.args.get("status")
    records = [r for r in db.rooms.values()
               if status is None or r["status"] == status]
    items, limit, offset, total = paginate(records)
    return array_response(items, limit, offset, total, 200)


@bp.route("/birth-center/rooms/<rid>/close", methods=["POST"])
def close_room(rid):
    _, role = require_auth()
    require_role(role, ["CenterAdmin"])
    rec = lookup.get_room(rid)
    rec["status"] = "CLOSED"
    touch(rec)
    return object_response(public(rec), 200)
