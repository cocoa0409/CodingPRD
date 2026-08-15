"""RelaySetting endpoints."""
from flask import Blueprint, request

import db
from middleware import get_actor, require_roles, ALL_ROLES
from response import success_object, success_list
from errors import (
    err_validation, err_not_found, err_state_transition, err_segregation_of_duties,
    err_certification_required, err_asset_decommissioned, err_asset_not_in_service,
    err_relay_coordination_violation, err_stale_version,
)
from services.common import (
    body, require_string, require_number, optional_number, parse_pagination,
    paginate, get_asset, get_relay_setting,
)
from services.calculations import check_certification_gate

bp = Blueprint("relay_settings", __name__)


def relay_setting_view(rs):
    return {
        "id": rs["id"],
        "asset_id": rs["asset_id"],
        "setting_group": rs["setting_group"],
        "pickup_a": rs["pickup_a"],
        "time_dial": rs["time_dial"],
        "curve": rs["curve"],
        "status": rs["status"],
        "author_technician_id": rs["author_technician_id"],
        "verified_by_technician_id": rs.get("verified_by_technician_id"),
        "supersedes_setting_id": rs.get("supersedes_setting_id"),
        "rejection_note": rs.get("rejection_note"),
        "created_at": rs["created_at"],
        "updated_at": rs["updated_at"],
        "version": rs["version"],
    }


@bp.post("/relay-settings")
def create_relay_setting():
    actor = get_actor()
    require_roles(actor, ["Technician"])
    payload = body()
    asset_id = require_string(payload, "asset_id")
    setting_group = require_string(payload, "setting_group")
    pickup_a = require_number(payload, "pickup_a")
    time_dial = require_number(payload, "time_dial")
    curve = require_string(payload, "curve")

    # FK: asset must exist and be RELAY class
    asset = get_asset(asset_id)
    if asset["asset_class"] != "RELAY":
        raise err_validation("asset_id must reference an asset of class RELAY")

    # Decommissioned asset guard
    if asset["status"] == "DECOMMISSIONED":
        raise err_asset_decommissioned()

    ent = {
        "id": db.new_id(),
        "asset_id": asset_id,
        "setting_group": setting_group,
        "pickup_a": pickup_a,
        "time_dial": time_dial,
        "curve": curve,
        "status": "DRAFT",
        "author_technician_id": actor.user_id,
        "verified_by_technician_id": None,
        "supersedes_setting_id": None,
        "rejection_note": None,
    }
    db.stamp_new(ent)
    db.relay_settings[ent["id"]] = ent
    return success_object(relay_setting_view(ent), status=201)


@bp.get("/relay-settings")
def list_relay_settings():
    actor = get_actor()
    require_roles(actor, ALL_ROLES)
    limit, offset = parse_pagination()
    items = list(db.relay_settings.values())
    asset_id = request.args.get("asset_id")
    if asset_id:
        items = [r for r in items if r["asset_id"] == asset_id]
    author_technician_id = request.args.get("author_technician_id")
    if author_technician_id:
        items = [r for r in items if r["author_technician_id"] == author_technician_id]
    verified_by_technician_id = request.args.get("verified_by_technician_id")
    if verified_by_technician_id:
        items = [r for r in items if r.get("verified_by_technician_id") == verified_by_technician_id]
    supersedes_setting_id = request.args.get("supersedes_setting_id")
    if supersedes_setting_id:
        items = [r for r in items if r.get("supersedes_setting_id") == supersedes_setting_id]
    status = request.args.get("status")
    if status:
        items = [r for r in items if r["status"] == status]
    setting_group = request.args.get("setting_group")
    if setting_group:
        items = [r for r in items if r["setting_group"] == setting_group]
    page, total = paginate(items, limit, offset)
    return success_list([relay_setting_view(r) for r in page], limit, offset, total)


@bp.get("/relay-settings/<id>")
def get_relay_setting_route(id):
    actor = get_actor()
    require_roles(actor, ALL_ROLES)
    rs = get_relay_setting(id)
    return success_object(relay_setting_view(rs))


@bp.post("/relay-settings/<id>/submit")
def submit_relay_setting(id):
    actor = get_actor()
    require_roles(actor, ["Technician"])
    rs = get_relay_setting(id)
    if rs["status"] not in ("DRAFT", "REJECTED"):
        raise err_state_transition("Setting is not DRAFT or REJECTED")
    # Only the author submits
    if actor.user_id != rs["author_technician_id"]:
        raise err_segregation_of_duties("Only the author may submit")
    rs["status"] = "SUBMITTED"
    db.touch(rs)
    return success_object(relay_setting_view(rs))


@bp.post("/relay-settings/<id>/verify")
def verify_relay_setting(id):
    actor = get_actor()
    require_roles(actor, ["Technician"])
    rs = get_relay_setting(id)
    if rs["status"] != "SUBMITTED":
        raise err_state_transition("Setting is not SUBMITTED")
    # Certification gate: NETA_LEVEL_4
    if not check_certification_gate(actor.user_id, "NETA_LEVEL_4"):
        raise err_certification_required()
    # Segregation of duties
    if actor.user_id == rs["author_technician_id"]:
        raise err_segregation_of_duties("Verifier must differ from author")
    rs["status"] = "VERIFIED"
    rs["verified_by_technician_id"] = actor.user_id
    db.touch(rs)
    return success_object(relay_setting_view(rs))


@bp.post("/relay-settings/<id>/reject")
def reject_relay_setting(id):
    actor = get_actor()
    require_roles(actor, ["Technician"])
    rs = get_relay_setting(id)
    payload = body()
    rejection_note = payload.get("rejection_note")

    if rs["status"] != "SUBMITTED":
        raise err_state_transition("Setting is not SUBMITTED")
    # Certification gate: NETA_LEVEL_4
    if not check_certification_gate(actor.user_id, "NETA_LEVEL_4"):
        raise err_certification_required()
    # Segregation of duties
    if actor.user_id == rs["author_technician_id"]:
        raise err_segregation_of_duties("Reviewer must differ from author")
    # rejection_note required
    if not rejection_note:
        raise err_validation("rejection_note is required")

    rs["status"] = "REJECTED"
    rs["rejection_note"] = rejection_note
    db.touch(rs)
    return success_object(relay_setting_view(rs))


@bp.post("/relay-settings/<id>/activate")
def activate_relay_setting(id):
    actor = get_actor()
    require_roles(actor, ["Technician"])
    rs = get_relay_setting(id)
    payload = body()
    expected_asset_version = payload.get("expected_asset_version")

    if rs["status"] != "VERIFIED":
        raise err_state_transition("Setting is not VERIFIED")

    # Certification gate: NETA_LEVEL_4
    if not check_certification_gate(actor.user_id, "NETA_LEVEL_4"):
        raise err_certification_required()

    # Asset must be IN_SERVICE
    asset = db.assets.get(rs["asset_id"])
    if asset is None:
        raise err_not_found("asset not found")
    if asset["status"] != "IN_SERVICE":
        raise err_asset_not_in_service()

    # OCC check
    if expected_asset_version is not None:
        if expected_asset_version != asset["version"]:
            raise err_stale_version()

    # Coordination margin check
    upstream_asset_id = asset.get("upstream_asset_id")
    if upstream_asset_id is not None:
        # Find upstream asset's ACTIVE setting in the same setting_group
        for other in db.relay_settings.values():
            if (other["asset_id"] == upstream_asset_id
                    and other["setting_group"] == rs["setting_group"]
                    and other["status"] == "ACTIVE"):
                if other["pickup_a"] < 1.3 * rs["pickup_a"]:
                    raise err_relay_coordination_violation()
                break

    # Find previous ACTIVE setting of the same (asset_id, setting_group)
    previous_active = None
    for other in db.relay_settings.values():
        if (other["asset_id"] == rs["asset_id"]
                and other["setting_group"] == rs["setting_group"]
                and other["status"] == "ACTIVE"
                and other["id"] != rs["id"]):
            previous_active = other
            break

    # Supersede previous
    if previous_active:
        previous_active["status"] = "SUPERSEDED"
        db.touch(previous_active)
        rs["supersedes_setting_id"] = previous_active["id"]
    else:
        rs["supersedes_setting_id"] = None

    rs["status"] = "ACTIVE"
    db.touch(rs)

    # Increment asset version (active-setting pointer changed)
    db.touch(asset)

    return success_object(relay_setting_view(rs))
