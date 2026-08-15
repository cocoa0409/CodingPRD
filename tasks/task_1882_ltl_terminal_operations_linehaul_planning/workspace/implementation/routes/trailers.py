"""Outbound trailer and manifest entry endpoints (PRD sections 2.6, 2.7, 3.5)."""
from decimal import Decimal

from flask import Blueprint, request

import db
from errors import (err_destination_mismatch, err_door_kind_mismatch,
                    err_invalid_request, err_invalid_state, err_osd_hold,
                    err_stale_trailer_version, err_terminal_closed,
                    err_trailer_not_loadable, err_trailer_over_capacity)
from middleware import require_roles
from response import success, success_list
from routes.common import (active_entries_for_trailer, as_int, body_json,
                           get_path, new_record, paginate,
                           recompute_trailer_ledger, resolve_fk, ser_entry,
                           ser_trailer, touch)
from services.calculations import (MIN_UTILIZATION_PCT, shipment_cube_cuft)

bp = Blueprint("trailers", __name__)

_READ_ROLES = ("TerminalAdmin", "Dispatcher", "DockSupervisor")


def _occ_check(body, trailer):
    """Priority 6: expected_trailer_version must equal the trailer version.
    A missing or non-integer expectation never matches."""
    expected = body.get("expected_trailer_version")
    if (not isinstance(expected, int)) or isinstance(expected, bool) \
            or expected != trailer["version"]:
        raise err_stale_trailer_version()


# --- OutboundTrailer -------------------------------------------------------------

@bp.route("/ltl/trailers", methods=["POST"])
@require_roles("DockSupervisor")
def create_trailer():
    body = body_json()
    terminal = resolve_fk("terminals", body.get("terminal_id"), "terminal_id")
    dest = resolve_fk("terminals", body.get("destination_terminal_id"), "destination_terminal_id")
    door = resolve_fk("dock_doors", body.get("outbound_door_id"), "outbound_door_id")
    # Priority 10: door-kind agreement.
    if door["door_kind"] != "OUTBOUND":
        raise err_door_kind_mismatch("An outbound trailer must be spotted at an OUTBOUND door")
    # Priority 16: closed-terminal guard.
    if terminal["status"] == "CLOSED":
        raise err_terminal_closed("Cannot spot a trailer at a CLOSED terminal")
    # Priority 20: capacity ranges.
    max_weight = as_int(body, "max_weight_lbs", minimum=1)
    max_cube = as_int(body, "max_cube_cuft", minimum=1)
    rec = new_record({
        "terminal_id": terminal["id"],
        "destination_terminal_id": dest["id"],
        "outbound_door_id": door["id"],
        "max_weight_lbs": max_weight, "max_cube_cuft": max_cube,
        "loaded_weight_lbs": 0, "loaded_cube_cuft": 0,
        "utilization_pct": Decimal("0.0"),
        "posture": "LOADING",
    })
    db.store["trailers"][rec["id"]] = rec
    return success(ser_trailer(rec), 201)


@bp.route("/ltl/trailers", methods=["GET"])
@require_roles(*_READ_ROLES)
def list_trailers():
    items = list(db.store["trailers"].values())
    for param in ("terminal_id", "destination_terminal_id", "outbound_door_id", "posture"):
        value = request.args.get(param)
        if value is not None:
            items = [t for t in items if t.get(param) == value]
    page, total, limit, offset = paginate(items)
    return success_list([ser_trailer(t) for t in page], total, limit, offset)


@bp.route("/ltl/trailers/<trailerId>", methods=["GET"])
@require_roles(*_READ_ROLES)
def get_trailer(trailerId):
    return success(ser_trailer(get_path("trailers", trailerId)))


@bp.route("/ltl/trailers/<trailerId>/mark-ready", methods=["POST"])
@require_roles("DockSupervisor")
def mark_ready(trailerId):
    trailer = get_path("trailers", trailerId)
    if trailer["posture"] != "LOADING":
        raise err_invalid_state("Only a LOADING trailer can be marked ready")
    # Priority 19: loadability gate.
    if not active_entries_for_trailer(trailer["id"]) \
            or trailer["utilization_pct"] < MIN_UTILIZATION_PCT:
        raise err_trailer_not_loadable()
    trailer["posture"] = "READY"
    touch(trailer)
    return success(ser_trailer(trailer))


@bp.route("/ltl/trailers/<trailerId>/seal", methods=["POST"])
@require_roles("DockSupervisor")
def seal_trailer(trailerId):
    trailer = get_path("trailers", trailerId)
    if trailer["posture"] != "READY":
        raise err_invalid_state("Only a READY trailer can be sealed")
    _occ_check(body_json(), trailer)
    trailer["posture"] = "SEALED"
    touch(trailer)
    return success(ser_trailer(trailer))


@bp.route("/ltl/trailers/<trailerId>/reopen", methods=["POST"])
@require_roles("DockSupervisor")
def reopen_trailer(trailerId):
    trailer = get_path("trailers", trailerId)
    if trailer["posture"] not in ("READY", "SEALED"):
        raise err_invalid_state("Only a READY or SEALED trailer can be reopened")
    if trailer["posture"] == "SEALED" and any(
            l["trailer_id"] == trailer["id"] and l["status"] == "EN_ROUTE"
            for l in db.store["linehaul_legs"].values()):
        raise err_invalid_state(
            "A SEALED trailer with an EN_ROUTE leg cannot be reopened")
    trailer["posture"] = "LOADING"
    touch(trailer)
    return success(ser_trailer(trailer))


@bp.route("/ltl/trailers/<trailerId>/void", methods=["POST"])
@require_roles("DockSupervisor")
def void_trailer(trailerId):
    trailer = get_path("trailers", trailerId)
    if trailer["posture"] not in ("LOADING", "READY"):
        raise err_invalid_state("Only a LOADING or READY trailer can be voided")
    if active_entries_for_trailer(trailer["id"]):
        raise err_invalid_state("A trailer with ACTIVE manifest entries cannot be voided")
    trailer["posture"] = "VOIDED"
    touch(trailer)
    return success(ser_trailer(trailer))


# --- ManifestEntry ---------------------------------------------------------------

@bp.route("/ltl/trailers/<trailerId>/manifest-entries", methods=["POST"])
@require_roles("DockSupervisor")
def add_manifest_entry(trailerId):
    trailer = get_path("trailers", trailerId)
    body = body_json()
    shipment = resolve_fk("shipments", body.get("shipment_id"), "shipment_id")
    # Priority 5: state preconditions.
    if trailer["posture"] != "LOADING":
        raise err_invalid_state("Manifest add requires trailer posture LOADING")
    if shipment["handling_status"] != "ON_DOCK":
        raise err_invalid_state("Manifest add requires shipment handling_status ON_DOCK")
    if shipment["rating_status"] not in ("RATED", "RERATED"):
        raise err_invalid_state("Manifest add requires shipment rating_status RATED or RERATED")
    if any(e["shipment_id"] == shipment["id"] and e["status"] == "ACTIVE"
           for e in db.store["manifest_entries"].values()):
        raise err_invalid_state("Shipment already has an ACTIVE manifest entry")
    # Priority 6: OCC on the trailer ledger.
    _occ_check(body, trailer)
    # Priority 7: OS&D safety hold.
    if shipment["osd_hold"]:
        raise err_osd_hold()
    # Priority 8: destination alignment.
    if trailer["destination_terminal_id"] != shipment["destination_terminal_id"]:
        raise err_destination_mismatch()
    # Priority 14: capacity ceilings; strictly greater rejected, at-cap allowed.
    cube = shipment_cube_cuft(shipment["length_in"], shipment["width_in"], shipment["height_in"])
    if trailer["loaded_weight_lbs"] + shipment["chargeable_weight_lbs"] > trailer["max_weight_lbs"] \
            or trailer["loaded_cube_cuft"] + cube > trailer["max_cube_cuft"]:
        raise err_trailer_over_capacity()
    # Priority 20: remaining field validity.
    load_position = as_int(body, "load_position", minimum=1)
    entry = new_record({
        "trailer_id": trailer["id"], "shipment_id": shipment["id"],
        "load_position": load_position, "status": "ACTIVE",
    })
    db.store["manifest_entries"][entry["id"]] = entry
    shipment["handling_status"] = "MANIFESTED"
    touch(shipment)
    recompute_trailer_ledger(trailer)
    touch(trailer)
    return success(ser_entry(entry), 201)


@bp.route("/ltl/trailers/<trailerId>/manifest-entries", methods=["GET"])
@require_roles(*_READ_ROLES)
def list_trailer_entries(trailerId):
    trailer = get_path("trailers", trailerId)
    items = [e for e in db.store["manifest_entries"].values()
             if e["trailer_id"] == trailer["id"]]
    value = request.args.get("status")
    if value is not None:
        items = [e for e in items if e["status"] == value]
    page, total, limit, offset = paginate(items)
    return success_list([ser_entry(e) for e in page], total, limit, offset)


@bp.route("/ltl/manifest-entries", methods=["GET"])
@require_roles(*_READ_ROLES)
def list_entries():
    items = list(db.store["manifest_entries"].values())
    for param in ("trailer_id", "shipment_id", "status"):
        value = request.args.get(param)
        if value is not None:
            items = [e for e in items if e.get(param) == value]
    page, total, limit, offset = paginate(items)
    return success_list([ser_entry(e) for e in page], total, limit, offset)


@bp.route("/ltl/manifest-entries/<entryId>", methods=["GET"])
@require_roles(*_READ_ROLES)
def get_entry(entryId):
    return success(ser_entry(get_path("manifest_entries", entryId)))


@bp.route("/ltl/manifest-entries/<entryId>/remove", methods=["POST"])
@require_roles("DockSupervisor")
def remove_entry(entryId):
    entry = get_path("manifest_entries", entryId)
    trailer = db.store["trailers"][entry["trailer_id"]]
    if entry["status"] != "ACTIVE" or trailer["posture"] not in ("LOADING", "READY"):
        raise err_invalid_state(
            "Removal requires an ACTIVE entry on a trailer in posture LOADING or READY")
    shipment = db.store["shipments"][entry["shipment_id"]]
    entry["status"] = "REMOVED"
    touch(entry)
    shipment["handling_status"] = "ON_DOCK"
    touch(shipment)
    recompute_trailer_ledger(trailer)
    touch(trailer)
    return success(ser_entry(entry))
