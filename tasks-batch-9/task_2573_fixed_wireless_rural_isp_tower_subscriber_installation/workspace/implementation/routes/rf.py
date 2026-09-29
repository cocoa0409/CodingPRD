"""Sectors and interference coordination."""
from decimal import Decimal

from flask import Blueprint, g

import calc
import db
import domain
import flows
import middleware as mw
import resolve
import response
from errors import ApiError
from util import dec, q1

bp = Blueprint("rf", __name__)

SECTOR_STATUSES = ("PLANNED", "ACTIVE", "DISABLED")
COORDINATION_DECISIONS = ("ACCEPT", "REJECT", "REQUEST_REVISION", "WITHDRAW")


def _sector_eirp(sector):
    return q1(dec(sector["tx_power_dbm"]) + dec(sector["antenna_gain_dbi"]))


def _check_channel_inside(license_record, lower, upper):
    lic_lower, lic_upper = domain.license_edges(license_record)
    if dec(lower) < lic_lower or dec(upper) > lic_upper:
        raise ApiError("ERR_CHANNEL_OUTSIDE_LICENSE")


# ---------------------------------------------------------------------------
# sectors
# ---------------------------------------------------------------------------
@bp.post("/sectors")
def create_sector():
    mw.require(mw.ROLE_NETWORK_ENGINEER)
    payload = mw.body()
    tower_id = mw.v_ref(payload, "tower_id")
    license_id = mw.v_ref(payload, "spectrum_license_id")
    azimuth = mw.v_num(payload, "azimuth_deg", minimum="0.0", maximum="359.9", places=1)
    beamwidth = mw.v_num(payload, "beamwidth_deg", minimum="15.0", maximum="180.0", places=1)
    center = mw.v_num(payload, "channel_center_mhz", minimum="600.0", maximum="6000.0", places=1)
    width = mw.v_num(payload, "channel_width_mhz", minimum="5.0", maximum="100.0", places=1)
    tx_power = mw.v_num(payload, "tx_power_dbm", minimum="0.0", maximum="40.0", places=1)
    gain = mw.v_num(payload, "antenna_gain_dbi", minimum="0.0", maximum="30.0", places=1)
    capacity = mw.v_int(payload, "capacity_mbps", minimum=1)
    max_ratio = mw.v_num(payload, "max_oversubscription_ratio", required=False,
                         default=calc.DEFAULT_MAX_OVERSUBSCRIPTION_RATIO,
                         minimum="1.0", maximum="20.0", places=1)

    tower = resolve.tower(tower_id)
    license_record = resolve.license_(license_id)

    eirp = q1(tx_power + gain)
    if eirp > dec(license_record["max_eirp_dbm"]):
        raise ApiError("ERR_EIRP_EXCEEDS_LICENSE")
    lower, upper = calc.channel_edges(center, width)
    _check_channel_inside(license_record, lower, upper)

    sector = db.base_record(
        tower_id=tower["id"],
        spectrum_license_id=license_record["id"],
        azimuth_deg=azimuth,
        beamwidth_deg=beamwidth,
        channel_center_mhz=center,
        channel_width_mhz=width,
        tx_power_dbm=tx_power,
        antenna_gain_dbi=gain,
        capacity_mbps=capacity,
        max_oversubscription_ratio=dec(max_ratio),
        status="PLANNED",
        capacity_policy_note=None,
    )
    db.sectors[sector["id"]] = sector
    return response.created(domain.sector_view(sector))


@bp.get("/sectors/<sector_id>")
def read_sector(sector_id):
    mw.require(*mw.OPERATOR_ROLES)
    sector = resolve.sector(sector_id)
    return response.object_response(domain.sector_view(sector))


@bp.get("/sectors")
def list_sectors():
    mw.require(mw.ROLE_NETWORK_ENGINEER, mw.ROLE_CAPACITY_PLANNER, mw.ROLE_SALES_AGENT)
    limit, offset = mw.pagination()
    spec = mw.filters("tower_id", "spectrum_license_id", "capacity_posture", "status")
    posture = spec.pop("capacity_posture", None)
    records = mw.apply_filters(db.ordered(list(db.sectors.values())), spec)
    if posture is not None:
        records = [s for s in records
                   if domain.sector_ledger(s)["capacity_posture"] == posture]
    page, total = mw.paginate(records, limit, offset)
    return response.list_response([domain.sector_view(s) for s in page], limit, offset, total)


@bp.post("/sectors/<sector_id>/activation")
def activate_sector(sector_id):
    mw.require(mw.ROLE_NETWORK_ENGINEER)
    mw.body()
    sector = resolve.sector(sector_id)
    if sector["status"] != "PLANNED":
        raise ApiError("ERR_INVALID_SECTOR_STATE")
    tower = db.towers.get(sector["tower_id"])
    if tower is None or tower["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_TOWER_STATE")
    license_record = db.spectrum_licenses.get(sector["spectrum_license_id"])
    if license_record is None or domain.license_status(license_record) != "ACTIVE":
        raise ApiError("ERR_LICENSE_NOT_EFFECTIVE")

    tracker = flows.SectorTracker()
    tracker.watch(sector)
    sector["status"] = "ACTIVE"
    tracker.mark(sector)
    tracker.settle()
    return response.object_response(domain.sector_view(sector))


@bp.post("/sectors/<sector_id>/capacity-policy")
def change_capacity_policy(sector_id):
    mw.require(mw.ROLE_CAPACITY_PLANNER)
    payload = mw.body()
    max_ratio = mw.v_num(payload, "max_oversubscription_ratio",
                         minimum="1.0", maximum="20.0", places=1)
    justification = mw.v_str(payload, "justification")
    sector = resolve.sector(sector_id)
    if sector["status"] == "DISABLED":
        raise ApiError("ERR_INVALID_SECTOR_STATE")

    tracker = flows.SectorTracker()
    tracker.watch(sector)
    sector["max_oversubscription_ratio"] = dec(max_ratio)
    sector["capacity_policy_note"] = justification
    tracker.mark(sector)
    flows.promote_deferred(sector, tracker)
    tracker.settle()
    return response.object_response(domain.sector_view(sector))


@bp.get("/sectors/<sector_id>/interference-coordinations")
def list_sector_coordinations(sector_id):
    mw.require(mw.ROLE_NETWORK_ENGINEER, mw.ROLE_CAPACITY_PLANNER)
    limit, offset = mw.pagination()
    sector = resolve.sector(sector_id)
    records = [c for c in db.interference_coordinations.values()
               if c["requesting_sector_id"] == sector["id"]]
    records = mw.apply_filters(db.ordered(records), mw.filters("status"))
    page, total = mw.paginate(records, limit, offset)
    return response.list_response([domain.coordination_view(c) for c in page],
                                  limit, offset, total)


# ---------------------------------------------------------------------------
# interference coordination
# ---------------------------------------------------------------------------
def _spectrum_checks(requesting, neighbor, center, width, eirp, guard,
                     check_effective):
    license_record = db.spectrum_licenses.get(requesting["spectrum_license_id"])
    if license_record is None:
        raise ApiError("ERR_LICENSE_NOT_FOUND")
    if dec(eirp) > dec(license_record["max_eirp_dbm"]):
        raise ApiError("ERR_EIRP_EXCEEDS_LICENSE")
    lower, upper = calc.channel_edges(center, width)
    _check_channel_inside(license_record, lower, upper)
    if check_effective and domain.license_status(license_record) != "ACTIVE":
        raise ApiError("ERR_LICENSE_NOT_EFFECTIVE")
    neighbor_lower, neighbor_upper = domain.sector_edges(neighbor)
    if not calc.guard_band_clear(requesting["azimuth_deg"], neighbor["azimuth_deg"],
                                 lower, upper, guard, neighbor_lower, neighbor_upper):
        raise ApiError("ERR_CHANNEL_OVERLAP_GUARD_BAND")


@bp.post("/interference-coordinations")
def create_coordination():
    mw.require(mw.ROLE_NETWORK_ENGINEER)
    payload = mw.body()
    requesting_id = mw.v_ref(payload, "requesting_sector_id")
    neighbor_id = mw.v_ref(payload, "neighbor_sector_id")
    center = mw.v_num(payload, "proposed_channel_center_mhz")
    width = mw.v_num(payload, "proposed_channel_width_mhz")
    eirp = mw.v_num(payload, "proposed_eirp_dbm")
    guard = mw.v_num(payload, "guard_band_mhz", minimum="0.0", maximum="20.0", places=1)
    effective_from = mw.v_ts(payload, "effective_from")

    requesting = resolve.sector(requesting_id)
    neighbor = resolve.sector(neighbor_id)

    _spectrum_checks(requesting, neighbor, center, width, eirp, guard, True)
    if requesting["tower_id"] == neighbor["tower_id"]:
        raise ApiError("ERR_SAME_TOWER_COORDINATION")

    record = db.base_record(
        requesting_sector_id=requesting["id"],
        neighbor_sector_id=neighbor["id"],
        proposed_channel_center_mhz=center,
        proposed_channel_width_mhz=width,
        proposed_eirp_dbm=eirp,
        guard_band_mhz=guard,
        effective_from=effective_from,
        round_number=1,
        status="REQUESTED",
        decision_note=None,
        decided_by_user_id=None,
        last_response_at=None,
    )
    db.interference_coordinations[record["id"]] = record
    return response.created(domain.coordination_view(record))


@bp.get("/interference-coordinations/<coordination_id>")
def read_coordination(coordination_id):
    mw.require(mw.ROLE_NETWORK_ENGINEER, mw.ROLE_CAPACITY_PLANNER)
    record = resolve.coordination(coordination_id)
    return response.object_response(domain.coordination_view(record))


@bp.get("/interference-coordinations")
def list_coordinations():
    mw.require(mw.ROLE_NETWORK_ENGINEER, mw.ROLE_CAPACITY_PLANNER)
    limit, offset = mw.pagination()
    spec = mw.filters("requesting_sector_id", "neighbor_sector_id", "status")
    records = mw.apply_filters(db.ordered(list(db.interference_coordinations.values())), spec)
    page, total = mw.paginate(records, limit, offset)
    return response.list_response([domain.coordination_view(c) for c in page],
                                  limit, offset, total)


@bp.post("/interference-coordinations/<coordination_id>/responses")
def respond_coordination(coordination_id):
    mw.require(mw.ROLE_NETWORK_ENGINEER)
    payload = mw.body()
    decision = mw.v_enum(payload, "decision", COORDINATION_DECISIONS)
    revised_center = mw.v_num(payload, "revised_channel_center_mhz", required=False)
    revised_eirp = mw.v_num(payload, "revised_eirp_dbm", required=False)
    note = mw.v_str(payload, "note", required=False)

    record = resolve.coordination(coordination_id)
    if decision == "WITHDRAW":
        if record["status"] not in ("REQUESTED", "REVISION_REQUESTED"):
            raise ApiError("ERR_COORDINATION_NOT_OPEN")
    elif record["status"] != "REQUESTED":
        raise ApiError("ERR_COORDINATION_NOT_OPEN")

    if decision == "REQUEST_REVISION":
        if int(record["round_number"]) >= calc.COORDINATION_ROUND_LIMIT:
            raise ApiError("ERR_COORDINATION_ROUND_LIMIT")

    tracker = flows.SectorTracker()
    record["last_response_at"] = db.now()
    record["decided_by_user_id"] = g.user_id

    if decision == "ACCEPT":
        record["status"] = "ACCEPTED"
        if note is not None:
            record["decision_note"] = note
        sector = db.sectors.get(record["requesting_sector_id"])
        if sector is not None:
            tracker.watch(sector)
            sector["channel_center_mhz"] = record["proposed_channel_center_mhz"]
            sector["channel_width_mhz"] = record["proposed_channel_width_mhz"]
            sector["tx_power_dbm"] = q1(dec(record["proposed_eirp_dbm"])
                                        - dec(sector["antenna_gain_dbi"]))
            tracker.mark(sector)
    elif decision == "REJECT":
        record["status"] = "REJECTED"
        record["decision_note"] = note
    elif decision == "WITHDRAW":
        record["status"] = "WITHDRAWN"
        if note is not None:
            record["decision_note"] = note
    else:
        record["status"] = "REVISION_REQUESTED"
        parts = []
        if note is not None:
            parts.append(note)
        if revised_center is not None:
            parts.append("revised_channel_center_mhz=%s" % revised_center)
        if revised_eirp is not None:
            parts.append("revised_eirp_dbm=%s" % revised_eirp)
        record["decision_note"] = "; ".join(parts) if parts else None

    db.touch(record)
    tracker.settle()
    return response.object_response(domain.coordination_view(record))


@bp.post("/interference-coordinations/<coordination_id>/revisions")
def revise_coordination(coordination_id):
    mw.require(mw.ROLE_NETWORK_ENGINEER)
    payload = mw.body()
    center = mw.v_num(payload, "proposed_channel_center_mhz")
    width = mw.v_num(payload, "proposed_channel_width_mhz")
    eirp = mw.v_num(payload, "proposed_eirp_dbm")
    guard = mw.v_num(payload, "guard_band_mhz", minimum="0.0", maximum="20.0", places=1)

    record = resolve.coordination(coordination_id)
    if record["status"] != "REVISION_REQUESTED":
        raise ApiError("ERR_COORDINATION_NOT_OPEN")

    requesting = db.sectors.get(record["requesting_sector_id"])
    neighbor = db.sectors.get(record["neighbor_sector_id"])
    if requesting is None or neighbor is None:
        raise ApiError("ERR_SECTOR_NOT_FOUND")
    _spectrum_checks(requesting, neighbor, center, width, eirp, guard, False)

    if int(record["round_number"]) >= calc.COORDINATION_ROUND_LIMIT:
        raise ApiError("ERR_COORDINATION_ROUND_LIMIT")

    record["proposed_channel_center_mhz"] = center
    record["proposed_channel_width_mhz"] = width
    record["proposed_eirp_dbm"] = eirp
    record["guard_band_mhz"] = guard
    record["round_number"] = int(record["round_number"]) + 1
    record["status"] = "REQUESTED"
    db.touch(record)
    return response.object_response(domain.coordination_view(record))
