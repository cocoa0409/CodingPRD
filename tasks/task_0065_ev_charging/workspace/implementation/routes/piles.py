"""Pile endpoints."""

import math

from flask import Blueprint, g, request

import db
from clock import now_iso
from errors import raise_error
from middleware import require_roles
from response import paginated, success
from services import queue_service
from validators import (
    SEMVER_RE,
    check_version,
    get_pagination,
    paginate_list,
    parse_json_body,
    require_enum,
    require_number,
    require_str,
)


bp = Blueprint("piles", __name__)

VALID_CONNECTOR_TYPES = {"GBT_DC", "GBT_AC", "CCS2", "CHADEMO"}
VALID_OPERATIONAL_STATES = {"IDLE", "IN_USE", "FAULT", "OFFLINE"}


@bp.post("/stations/<station_id>/piles")
@require_roles({"StationOwner"})
def add_pile(station_id: str):
    station = db.stations.get(station_id)
    if station is None:
        raise_error("ERR_NOT_FOUND", "station not found")
    if station["station_owner_id"] != g.user_id:
        raise_error("ERR_FORBIDDEN", "you do not own this station")

    body = parse_json_body()
    model_code = require_str(body, "model_code", 1, 64)
    rated_power_kw = require_number(
        body, "rated_power_kw", min_value=None, max_value=360.0, max_frac_digits=1
    )
    if not (rated_power_kw > 0):
        raise_error("ERR_VALIDATION", "rated_power_kw must be > 0")
    connector_type = require_enum(body, "connector_type", VALID_CONNECTOR_TYPES)
    firmware_version = require_str(body, "firmware_version", 1, 64)
    if not SEMVER_RE.match(firmware_version):
        raise_error("ERR_VALIDATION", "firmware_version must match MAJOR.MINOR.PATCH")

    record = {
        "station_id": station_id,
        "model_code": model_code,
        "rated_power_kw": rated_power_kw,
        "connector_type": connector_type,
        "firmware_version": firmware_version,
        "lifecycle_state": "OFF_SHELF",
        "operational_state": None,
        "last_heartbeat_at": None,
    }
    db.with_common_fields(record)
    db.piles[record["id"]] = record
    return success(db.public(record), status=201)


@bp.post("/piles/<pile_id>/shelve")
@require_roles({"StationOwner"})
def shelve_pile(pile_id: str):
    pile = db.piles.get(pile_id)
    if pile is None:
        raise_error("ERR_NOT_FOUND", "pile not found")
    body = parse_json_body()
    check_version(body, pile)

    station = db.stations.get(pile["station_id"])
    if station is None or station["station_owner_id"] != g.user_id:
        raise_error("ERR_FORBIDDEN", "you do not own this station")

    if pile["lifecycle_state"] != "OFF_SHELF":
        raise_error("ERR_INVALID_STATE", "pile not in OFF_SHELF state")
    if not SEMVER_RE.match(pile["firmware_version"]):
        raise_error("ERR_INVALID_STATE", "firmware version invalid")
    if station["status"] != "ACTIVE":
        raise_error("ERR_INVALID_STATE", "station is not ACTIVE")

    pile["lifecycle_state"] = "ON_SHELF"
    pile["operational_state"] = "IDLE"
    db.bump(pile)

    # Newly-idle pile: promote any waiting queue entry at the station.
    queue_service.promote_if_possible(station["id"])
    return success(db.public(pile))


@bp.post("/piles/<pile_id>/off-shelve")
@require_roles({"StationOwner"})
def off_shelve_pile(pile_id: str):
    pile = db.piles.get(pile_id)
    if pile is None:
        raise_error("ERR_NOT_FOUND", "pile not found")
    body = parse_json_body()
    check_version(body, pile)

    station = db.stations.get(pile["station_id"])
    if station is None or station["station_owner_id"] != g.user_id:
        raise_error("ERR_FORBIDDEN", "you do not own this station")

    if pile["lifecycle_state"] != "ON_SHELF":
        raise_error("ERR_INVALID_STATE", "pile not in ON_SHELF state")

    # Dependents check.
    for sess in db.sessions.values():
        if sess["pile_id"] == pile_id and sess["status"] in {
            "PENDING_AUTH", "CHARGING", "SETTLING"
        }:
            raise_error("ERR_PILE_HAS_DEPENDENTS", "pile has active session")
    for res in db.reservations.values():
        if res["pile_id"] == pile_id and res["status"] == "HELD":
            raise_error("ERR_PILE_HAS_DEPENDENTS", "pile has held reservation")

    pile["lifecycle_state"] = "OFF_SHELF"
    pile["operational_state"] = None
    db.bump(pile)
    return success(db.public(pile))


@bp.post("/piles/<pile_id>/decommission")
@require_roles({"PlatformOperator"})
def decommission_pile(pile_id: str):
    pile = db.piles.get(pile_id)
    if pile is None:
        raise_error("ERR_NOT_FOUND", "pile not found")
    body = parse_json_body()
    check_version(body, pile)

    if pile["lifecycle_state"] != "OFF_SHELF":
        raise_error("ERR_INVALID_STATE", "pile must be OFF_SHELF to decommission")

    pile["lifecycle_state"] = "DECOMMISSIONED"
    pile["operational_state"] = None
    db.bump(pile)
    return success(db.public(pile))


@bp.patch("/piles/<pile_id>")
@require_roles({"StationOwner"})
def update_pile(pile_id: str):
    pile = db.piles.get(pile_id)
    if pile is None:
        raise_error("ERR_NOT_FOUND", "pile not found")
    body = parse_json_body()
    check_version(body, pile)

    station = db.stations.get(pile["station_id"])
    if station is None or station["station_owner_id"] != g.user_id:
        raise_error("ERR_FORBIDDEN", "you do not own this station")

    changed = False
    if "model_code" in body and body["model_code"] is not None:
        if not isinstance(body["model_code"], str) or not (1 <= len(body["model_code"]) <= 64):
            raise_error("ERR_VALIDATION", "model_code out of range")
        pile["model_code"] = body["model_code"]
        changed = True
    if "firmware_version" in body and body["firmware_version"] is not None:
        fw = body["firmware_version"]
        if not isinstance(fw, str) or not SEMVER_RE.match(fw):
            raise_error("ERR_VALIDATION", "firmware_version invalid")
        pile["firmware_version"] = fw
        changed = True
    if "rated_power_kw" in body and body["rated_power_kw"] is not None:
        val = body["rated_power_kw"]
        if not isinstance(val, (int, float)) or isinstance(val, bool):
            raise_error("ERR_VALIDATION", "rated_power_kw must be numeric")
        if not (0 < float(val) <= 360.0):
            raise_error("ERR_VALIDATION", "rated_power_kw out of range")
        # max 1 fractional digit
        from decimal import Decimal
        exp = -Decimal(str(val)).as_tuple().exponent if Decimal(str(val)).as_tuple().exponent < 0 else 0
        if exp > 1:
            raise_error("ERR_VALIDATION", "rated_power_kw too many fractional digits")
        pile["rated_power_kw"] = val
        changed = True

    if changed:
        db.bump(pile)
    return success(db.public(pile))


def _haversine_km(lat1, lon1, lat2, lon2):
    if None in (lat1, lon1, lat2, lon2):
        return 0.0
    radius_km = 6371.0
    phi1 = math.radians(float(lat1))
    phi2 = math.radians(float(lat2))
    dphi = math.radians(float(lat2) - float(lat1))
    dlam = math.radians(float(lon2) - float(lon1))
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return radius_km * c


@bp.get("/piles")
@require_roles({"PlatformOperator", "StationOwner", "EVDriver",
                "FieldTechnician", "CustomerService"})
def list_piles():
    station_id = request.args.get("station_id")
    connector_type = request.args.get("connector_type")
    operational_state = request.args.get("operational_state")
    available_for_member = request.args.get("available_for_member")
    limit, offset = get_pagination()

    items = list(db.piles.values())

    if station_id:
        items = [p for p in items if p["station_id"] == station_id]
    if connector_type:
        items = [p for p in items if p["connector_type"] == connector_type]
    if operational_state:
        items = [p for p in items if p["operational_state"] == operational_state]

    if available_for_member:
        member = db.members.get(available_for_member)
        if member is None:
            raise_error("ERR_NOT_FOUND", "member not found")

        eligible = []
        for p in items:
            station = db.stations.get(p["station_id"])
            if station is None or station["status"] != "ACTIVE":
                continue
            if p["lifecycle_state"] != "ON_SHELF":
                continue
            if p["operational_state"] != "IDLE":
                continue
            # no HELD reservation on this pile
            if any(
                r["pile_id"] == p["id"] and r["status"] == "HELD"
                for r in db.reservations.values()
            ):
                continue
            # station has zero WAITING queue entries (queue-jumping prevention)
            if queue_service.waiting_count(station["id"]) > 0:
                continue
            eligible.append(p)

        tier_rank = {"BASIC": 0, "SILVER": 1, "GOLD": 2, "PLATINUM": 3}[member["tier"]]
        # member last location not modeled — assume station location (distance=0)
        scored = []
        for p in eligible:
            station = db.stations[p["station_id"]]
            distance_km = 0.0  # member location unmodeled
            score = (
                5 * float(p["rated_power_kw"])
                + 25 * tier_rank
                - 100 * distance_km
            )
            scored.append((int(round(score)), p))
        scored.sort(key=lambda t: (-t[0], t[1]["id"]))
        items = [p for _, p in scored]
    else:
        items.sort(key=lambda r: r["_seq"])

    page, total = paginate_list(items, limit, offset)
    return paginated(db.public_list(page), limit, offset, total)


@bp.get("/piles/<pile_id>")
@require_roles({"PlatformOperator", "StationOwner", "EVDriver",
                "FieldTechnician", "CustomerService"})
def get_pile(pile_id: str):
    pile = db.piles.get(pile_id)
    if pile is None:
        raise_error("ERR_NOT_FOUND", "pile not found")
    return success(db.public(pile))
