"""StorageLocation provisioning and StoragePlacement lifecycle (§3.7):
staging with SOC-band fire-code gating, store, pick and manual release,
including the two watt-hour ledgers of §2.8."""

from decimal import Decimal

from flask import Blueprint, request

import db
import clock
from domain import (
    new_row, touch, sorted_rows, get_program, get_location, get_placement,
    require_program_open, raise_if_pack_under_recall, ser_location,
    ser_placement, soc_band_plain, release_placement, FIRE_ZONES, SOC_BANDS,
)
from errors import (
    err_pack_not_found, err_location_not_found, err_cross_program,
    err_pack_not_ready_to_store, err_pack_already_stored,
    err_soc_band_not_accepted, err_location_capacity, err_program_capacity,
    err_placement_not_staged, err_invalid_request,
)
from middleware import require_roles
from response import success_object, success_created, success_list
from util import get_body, req_field, as_str, as_int, as_enum, as_enum_list, round_half_up

bp = Blueprint("storage", __name__)


# ---------------------------------------------------------------------------
# StorageLocation
# ---------------------------------------------------------------------------

@bp.route("/integration-programs/<programId>/storage-locations", methods=["POST"])
@require_roles("LogisticsCoordinator")
def create_location(actor, programId):
    program = get_program(programId)
    body = get_body(required=True)
    location_code = as_str(req_field(body, "location_code"), "location_code")
    fire_zone = as_enum(req_field(body, "fire_zone"), "fire_zone", FIRE_ZONES)
    capacity_wh = as_int(req_field(body, "capacity_wh"), "capacity_wh")
    if capacity_wh <= 0:
        raise err_invalid_request("capacity_wh must be > 0")
    accepts = as_enum_list(
        req_field(body, "accepts_soc_band"), "accepts_soc_band", SOC_BANDS
    )
    require_program_open(program)

    row = new_row()
    row.update(
        program_id=program["id"],
        location_code=location_code,
        fire_zone=fire_zone,
        capacity_wh=capacity_wh,
        wh_occupied=Decimal("0"),
        accepts_soc_band=accepts,
    )
    db.locations[row["id"]] = row
    return success_created(ser_location(row))


@bp.route("/integration-programs/<programId>/storage-locations", methods=["GET"])
@require_roles()
def list_locations(actor, programId):
    get_program(programId)
    rows = sorted_rows(
        [r for r in db.locations.values() if r["program_id"] == programId]
    )
    return success_list(rows, ser_location)


@bp.route("/integration-programs/<programId>/storage-locations/<locationId>", methods=["GET"])
@require_roles()
def get_one_location(actor, programId, locationId):
    get_program(programId)
    return success_object(ser_location(get_location(programId, locationId)))


# ---------------------------------------------------------------------------
# StoragePlacement
# ---------------------------------------------------------------------------

@bp.route("/integration-programs/<programId>/storage-placements", methods=["POST"])
@require_roles("LogisticsCoordinator")
def create_placement(actor, programId):
    program = get_program(programId)
    body = get_body(required=True)
    location_id = as_str(req_field(body, "storage_location_id"), "storage_location_id")
    pack_id = as_str(req_field(body, "battery_pack_id"), "battery_pack_id")

    pack = db.packs.get(pack_id)
    if pack is None:
        raise err_pack_not_found()
    location = db.locations.get(location_id)
    if location is None:
        raise err_location_not_found()
    require_program_open(program)
    # priority 5: state preconditions on the pack's two axes
    if pack["assembly_status"] != "READY_TO_STORE":
        raise err_pack_not_ready_to_store()
    if pack["logistics_status"] != "NOT_STORED":
        raise err_pack_already_stored()
    # the pack's soc_band is re-evaluated as part of the staging act (§3.7)
    pack["soc_band"] = soc_band_plain(pack["soc_percent"])
    # priority 7: fire-zone SOC-band acceptance
    if pack["soc_band"] not in location["accepts_soc_band"]:
        raise err_soc_band_not_accepted()
    # priority 12: cross-program referential integrity
    if pack["program_id"] != program["id"] or location["program_id"] != program["id"]:
        raise err_cross_program()
    # priority 16/17: slot headroom, then program capacity
    energy = pack["pack_energy_wh"]
    if Decimal(location["capacity_wh"]) - location["wh_occupied"] < energy:
        raise err_location_capacity()
    if Decimal(program["storage_capacity_wh"]) - program["wh_committed"] < energy:
        raise err_program_capacity()

    row = new_row()
    row.update(
        storage_location_id=location["id"],
        battery_pack_id=pack["id"],
        program_id=program["id"],
        staged_at_utc=clock.now(),
        stored_at_utc=None,
        released_at_utc=None,
        status="STAGED",
    )
    db.placements[row["id"]] = row

    location["wh_occupied"] = round_half_up(location["wh_occupied"] + energy, 2)
    touch(location)
    program["wh_committed"] = round_half_up(program["wh_committed"] + energy, 2)
    touch(program)
    pack["storage_location_id"] = location["id"]
    pack["logistics_status"] = "STAGED"
    touch(pack)
    return success_created(ser_placement(row))


@bp.route("/integration-programs/<programId>/storage-placements", methods=["GET"])
@require_roles()
def list_placements(actor, programId):
    get_program(programId)
    rows = [r for r in db.placements.values() if r["program_id"] == programId]
    for f in ("storage_location_id", "battery_pack_id"):
        v = request.args.get(f)
        if v is not None:
            rows = [r for r in rows if r.get(f) == v]
    return success_list(sorted_rows(rows), ser_placement)


@bp.route("/integration-programs/<programId>/storage-placements/<placementId>", methods=["GET"])
@require_roles()
def get_one_placement(actor, programId, placementId):
    get_program(programId)
    return success_object(ser_placement(get_placement(programId, placementId)))


@bp.route("/integration-programs/<programId>/storage-placements/<placementId>/store", methods=["POST"])
@require_roles("LogisticsCoordinator")
def store_placement(actor, programId, placementId):
    program = get_program(programId)
    placement = get_placement(programId, placementId)
    get_body()
    require_program_open(program)
    if placement["status"] != "STAGED":
        raise err_placement_not_staged()

    placement["status"] = "STORED"
    placement["stored_at_utc"] = clock.now()
    touch(placement)
    pack = db.packs[placement["battery_pack_id"]]
    pack["logistics_status"] = "STORED"
    touch(pack)
    return success_object(ser_placement(placement))


@bp.route("/integration-programs/<programId>/storage-placements/<placementId>/release", methods=["POST"])
@require_roles("LogisticsCoordinator")
def release_placement_manual(actor, programId, placementId):
    program = get_program(programId)
    placement = get_placement(programId, placementId)
    get_body()
    require_program_open(program)
    if placement["status"] not in ("STAGED", "STORED"):
        raise err_placement_not_staged()
    pack = db.packs[placement["battery_pack_id"]]
    # priority 20: recall capture blocks manual release
    raise_if_pack_under_recall(pack)

    from domain import release_placement as _do_release  # local alias: route name shadows
    _do_release(placement, pack)
    pack["logistics_status"] = "NOT_STORED"
    touch(pack)
    return success_object(ser_placement(placement))
