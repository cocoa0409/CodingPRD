"""Monitoring kits, their components and the chain of custody (PRD 3.5)."""

from flask import Blueprint

import derived
import envelope
import errors
import ladder
import serializers
import store
from domain import kits as kit_service
from errors import fail
from routes.common import apply_filter, endpoint
from store import DB

bp = Blueprint("device_kits", __name__)

COMPONENT_TYPES = ("TABLET", "BP_CUFF", "PULSE_OX", "SCALE", "THERMOMETER", "GATEWAY")
RECONCILE_OUTCOMES = ("RETURNED", "WRITTEN_OFF")
KIT_READ_ROLES = ["ProgramAdmin", "AdmittingPhysician", "FieldNurse"]


@endpoint(bp, "/device-kits", ["POST"], ["ProgramAdmin"])
def create_kit(caller):
    body = ladder.json_body()
    # rung 4a
    ladder.require_fields(body, ["asset_tag"])
    # rung 4c
    ladder.check_non_empty_string(body, "asset_tag")
    ladder.check_unique("kits", "asset_tag", body["asset_tag"])
    row = store.make_row("kits", {
        "asset_tag": body["asset_tag"],
        "assigned_episode_id": None,
        "status": "AVAILABLE",
        "refurb_cycle_count": 0,
        "deployed_at": None,
    })
    return envelope.ObjResult(row, serializers.device_kit, 201)


@endpoint(bp, "/device-kits/<kit_id>", ["GET"], KIT_READ_ROLES)
def get_kit(caller, kit_id):
    row = ladder.path_row("kits", kit_id)
    return envelope.ObjResult(row, serializers.device_kit, 200)


@endpoint(bp, "/episodes/<episode_id>/device-kits", ["GET"], KIT_READ_ROLES)
def list_episode_kits(caller, episode_id):
    # rung 3
    ladder.path_row("episodes", episode_id)
    limit, offset = ladder.pagination_params()
    rows = [k for k in DB.kits.values() if k["assigned_episode_id"] == episode_id]
    return envelope.ListResult(store.ordered(rows), serializers.device_kit, limit, offset)


@endpoint(bp, "/device-kits/<kit_id>/deploy", ["POST"], ["FieldNurse"])
def deploy_kit(caller, kit_id):
    # rung 3
    kit = ladder.path_row("kits", kit_id)
    body = ladder.json_body()
    # rung 4a
    ladder.require_fields(body, ["episode_id", "expected_kit_version"])
    # rung 4c
    supplied_version = ladder.expected_version(body, "expected_kit_version")
    # rung 5
    episode = ladder.body_episode(body)
    # rung 6
    ladder.check_occ(kit, supplied_version)
    # rung 8
    ladder.require_episode_active(episode)
    # rung 14b
    if kit["status"] != "AVAILABLE":
        fail(errors.ERR_KIT_UNAVAILABLE)
    if derived.episode_deployed_kit(episode["id"]) is not None:
        fail(errors.ERR_KIT_UNAVAILABLE)

    kit_service.deploy(kit, episode)
    return envelope.ObjResult(kit, serializers.device_kit, 200)


@endpoint(bp, "/device-kit-census", ["GET"], ["ProgramAdmin"])
def get_kit_census(caller):
    return envelope.RawResult(derived.kit_census(), 200)


@endpoint(bp, "/device-kits/<kit_id>/components", ["POST"], ["ProgramAdmin"])
def create_component(caller, kit_id):
    # rung 3
    kit = ladder.path_row("kits", kit_id)
    body = ladder.json_body()
    # rung 4a
    ladder.require_fields(body, ["component_type", "serial_number", "replacement_cost_usd"])
    # rung 4b
    ladder.check_enum(body, "component_type", COMPONENT_TYPES)
    # rung 4c
    ladder.check_non_empty_string(body, "serial_number")
    ladder.check_number_min(body, "replacement_cost_usd", 0)
    ladder.check_unique("components", "serial_number", body["serial_number"])

    row = store.make_row("components", {
        "kit_id": kit["id"],
        "component_type": body["component_type"],
        "serial_number": body["serial_number"],
        "replacement_cost_usd": body["replacement_cost_usd"],
        "reconciliation_status": "IN_STOCK",
        "reconciled_by_user_id": None,
    })
    return envelope.ObjResult(row, serializers.device_component, 201)


@endpoint(bp, "/device-kits/<kit_id>/components", ["GET"], KIT_READ_ROLES)
def list_components(caller, kit_id):
    # rung 3
    ladder.path_row("kits", kit_id)
    limit, offset = ladder.pagination_params()
    rows = [c for c in DB.components.values() if c["kit_id"] == kit_id]
    rows = apply_filter(rows, "reconciliation_status")
    return envelope.ListResult(store.ordered(rows), serializers.device_component, limit, offset)


@endpoint(bp, "/device-components/<component_id>/reconcile", ["POST"], ["FieldNurse"])
def reconcile_component(caller, component_id):
    # rung 3
    component = ladder.path_row("components", component_id)
    body = ladder.json_body()
    # rung 4a
    ladder.require_fields(body, ["outcome"])
    # rung 4b
    ladder.check_enum(body, "outcome", RECONCILE_OUTCOMES)
    # rung 7
    ladder.require_state(component["reconciliation_status"] == "PENDING_RECONCILIATION")
    kit_service.reconcile_component(component, body["outcome"], caller.user_id)
    return envelope.ObjResult(component, serializers.device_component, 200)
