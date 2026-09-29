"""The logical clock, towers, transport circuits and spectrum licences."""
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
from util import format_date, format_ts

bp = Blueprint("plant", __name__)

TOWER_STATUSES = ("PLANNED", "ACTIVE", "MAINTENANCE", "DECOMMISSIONED")
CIRCUIT_STATES = ("ORDERED", "INSTALLED", "ACCEPTED", "DEGRADED", "CANCELLED")
BANDS = ("CBRS_3_5GHZ", "EBS_2_5GHZ", "LTE_700MHZ")

CIRCUIT_TRANSITIONS = {
    ("ORDERED", "INSTALLED"),
    ("INSTALLED", "ACCEPTED"),
    ("ACCEPTED", "DEGRADED"),
    ("DEGRADED", "ACCEPTED"),
    ("ORDERED", "CANCELLED"),
    ("INSTALLED", "CANCELLED"),
}


# ---------------------------------------------------------------------------
# logical clock
# ---------------------------------------------------------------------------
@bp.post("/_clock/set_current_utc")
def set_clock():
    mw.require(*mw.OPERATOR_ROLES)
    payload = mw.body()
    moment = mw.v_ts(payload, "to_iso8601", required=True)
    db.set_clock(moment)
    return response.object_response({"current_utc": format_ts(db.now())})


# ---------------------------------------------------------------------------
# towers
# ---------------------------------------------------------------------------
@bp.post("/towers")
def create_tower():
    mw.require(mw.ROLE_NETWORK_ENGINEER)
    payload = mw.body()
    site_code = mw.v_str(payload, "site_code", min_len=4, max_len=32)
    latitude = mw.v_num(payload, "latitude", minimum="-90.0", maximum="90.0", places=4)
    longitude = mw.v_num(payload, "longitude", minimum="-180.0", maximum="180.0", places=4)
    ground = mw.v_num(payload, "ground_elevation_m", minimum="0.0", maximum="4500.0", places=1)
    agl = mw.v_num(payload, "antenna_agl_m", minimum="6.0", maximum="120.0", places=1)
    landowner = mw.v_str(payload, "lease_landowner_name")
    base_rent = mw.v_int(payload, "lease_monthly_base_rent_cents", minimum=0)
    escalator = mw.v_num(payload, "lease_escalator_pct", minimum="0.0", maximum="0.15", places=4)
    start_date = mw.v_date(payload, "lease_start_date")
    term_months = mw.v_int(payload, "lease_term_months", minimum=12, maximum=240,
                           multiple_of=12)

    for tower in db.towers.values():
        if tower["site_code"] == site_code:
            raise ApiError("ERR_DUPLICATE_SITE_CODE")

    tower = db.base_record(
        site_code=site_code,
        latitude=latitude,
        longitude=longitude,
        ground_elevation_m=ground,
        antenna_agl_m=agl,
        status="PLANNED",
        lease_landowner_name=landowner,
        lease_monthly_base_rent_cents=base_rent,
        lease_escalator_pct=escalator,
        lease_start_date=start_date,
        lease_term_months=term_months,
    )
    db.towers[tower["id"]] = tower
    return response.created(domain.tower_view(tower))


@bp.get("/towers/<tower_id>")
def read_tower(tower_id):
    mw.require(*mw.OPERATOR_ROLES)
    tower = resolve.tower(tower_id)
    return response.object_response(domain.tower_view(tower))


@bp.get("/towers/<tower_id>/lease-schedule")
def read_lease_schedule(tower_id):
    mw.require(mw.ROLE_NETWORK_ENGINEER, mw.ROLE_BILLING_ADMIN, mw.ROLE_FINANCE_APPROVER)
    tower = resolve.tower(tower_id)
    schedule = calc.lease_schedule(tower, db.now())
    return response.object_response({
        "tower_id": tower["id"],
        "years_elapsed": schedule["years_elapsed"],
        "current_monthly_rent_cents": schedule["current_monthly_rent_cents"],
        "next_anniversary_date": format_date(schedule["next_anniversary_date"]),
        "total_committed_cents": schedule["total_committed_cents"],
    })


@bp.post("/towers/<tower_id>/status-changes")
def change_tower_status(tower_id):
    mw.require(mw.ROLE_NETWORK_ENGINEER)
    payload = mw.body()
    to_status = mw.v_enum(payload, "to_status", TOWER_STATUSES)
    mw.v_str(payload, "reason", required=False)
    tower = resolve.tower(tower_id)

    current = tower["status"]
    allowed = {
        ("PLANNED", "ACTIVE"),
        ("ACTIVE", "MAINTENANCE"),
        ("MAINTENANCE", "ACTIVE"),
        ("ACTIVE", "DECOMMISSIONED"),
        ("MAINTENANCE", "DECOMMISSIONED"),
    }
    if (current, to_status) not in allowed:
        raise ApiError("ERR_INVALID_TOWER_STATE")

    if to_status == "ACTIVE":
        if domain.tower_backhaul_accepted_mbps(tower["id"]) == 0:
            raise ApiError("ERR_BACKHAUL_NOT_ACCEPTED")
    if to_status == "DECOMMISSIONED":
        for subscriber in db.subscribers.values():
            sector = db.sectors.get(subscriber["sector_id"])
            if sector is None or sector["tower_id"] != tower["id"]:
                continue
            if subscriber["service_status"] in ("PENDING_INSTALL", "ACTIVE", "SUSPENDED"):
                raise ApiError("ERR_TOWER_HAS_ACTIVE_SUBSCRIBERS")

    tracker = flows.SectorTracker()
    tracker.watch_tower(tower["id"])
    tower["status"] = to_status
    if to_status == "DECOMMISSIONED":
        flows.cascade_tower_decommissioned(tower, tracker)
    db.touch(tower)
    tracker.settle()
    return response.object_response(domain.tower_view(tower))


@bp.get("/towers/<tower_id>/backhaul-circuits")
def list_tower_circuits(tower_id):
    mw.require(mw.ROLE_NETWORK_ENGINEER, mw.ROLE_CAPACITY_PLANNER, mw.ROLE_BILLING_ADMIN)
    limit, offset = mw.pagination()
    tower = resolve.tower(tower_id)
    records = [c for c in db.backhaul_circuits.values() if c["tower_id"] == tower["id"]]
    records = mw.apply_filters(db.ordered(records), mw.filters("state"))
    page, total = mw.paginate(records, limit, offset)
    return response.list_response([domain.circuit_view(c) for c in page], limit, offset, total)


@bp.get("/towers/<tower_id>/outage-events")
def list_tower_outages(tower_id):
    mw.require(mw.ROLE_NETWORK_ENGINEER, mw.ROLE_CAPACITY_PLANNER, mw.ROLE_BILLING_ADMIN,
               mw.ROLE_FINANCE_APPROVER)
    limit, offset = mw.pagination()
    tower = resolve.tower(tower_id)
    records = [o for o in db.outage_events.values() if o["tower_id"] == tower["id"]]
    records = mw.apply_filters(db.ordered(records), mw.filters("status", "cause"))
    page, total = mw.paginate(records, limit, offset)
    return response.list_response([domain.outage_view(o) for o in page], limit, offset, total)


# ---------------------------------------------------------------------------
# backhaul circuits
# ---------------------------------------------------------------------------
@bp.post("/backhaul-circuits")
def create_circuit():
    mw.require(mw.ROLE_NETWORK_ENGINEER)
    payload = mw.body()
    tower_id = mw.v_ref(payload, "tower_id")
    carrier_name = mw.v_str(payload, "carrier_name")
    circuit_ref = mw.v_str(payload, "circuit_ref")
    committed = mw.v_int(payload, "committed_mbps", minimum=1)
    monthly_cost = mw.v_int(payload, "monthly_cost_cents", minimum=0)

    tower = resolve.tower(tower_id)
    for circuit in db.backhaul_circuits.values():
        if circuit["circuit_ref"] == circuit_ref:
            raise ApiError("ERR_DUPLICATE_CIRCUIT_REF")

    circuit = db.base_record(
        tower_id=tower["id"],
        carrier_name=carrier_name,
        circuit_ref=circuit_ref,
        committed_mbps=committed,
        monthly_cost_cents=monthly_cost,
        state="ORDERED",
        measured_mbps=None,
        accepted_at=None,
        degraded_since=None,
    )
    db.backhaul_circuits[circuit["id"]] = circuit
    return response.created(domain.circuit_view(circuit))


@bp.get("/backhaul-circuits/<circuit_id>")
def read_circuit(circuit_id):
    mw.require(mw.ROLE_NETWORK_ENGINEER, mw.ROLE_CAPACITY_PLANNER, mw.ROLE_BILLING_ADMIN)
    circuit = resolve.circuit(circuit_id)
    return response.object_response(domain.circuit_view(circuit))


@bp.post("/backhaul-circuits/<circuit_id>/state-changes")
def change_circuit_state(circuit_id):
    mw.require(mw.ROLE_NETWORK_ENGINEER)
    payload = mw.body()
    to_state = mw.v_enum(payload, "to_state", CIRCUIT_STATES)
    measured = mw.v_num(payload, "measured_mbps", required=False, minimum="0")
    mw.v_str(payload, "note", required=False)
    if to_state == "ACCEPTED" and measured is None:
        raise ApiError("ERR_VALIDATION", "Field 'measured_mbps' is required on an acceptance.")

    circuit = resolve.circuit(circuit_id)
    if (circuit["state"], to_state) not in CIRCUIT_TRANSITIONS:
        raise ApiError("ERR_INVALID_CIRCUIT_STATE")

    tower = db.towers.get(circuit["tower_id"])
    tracker = flows.SectorTracker()
    if tower is not None:
        tracker.watch_tower(tower["id"])

    previous = circuit["state"]
    circuit["state"] = to_state
    if to_state == "ACCEPTED":
        circuit["measured_mbps"] = measured
        circuit["degraded_since"] = None
        if previous == "INSTALLED":
            circuit["accepted_at"] = db.now()
    elif to_state == "DEGRADED":
        circuit["degraded_since"] = db.now()
        if measured is not None:
            circuit["measured_mbps"] = measured
    db.touch(circuit)

    if to_state == "DEGRADED" and tower is not None:
        flows.cascade_circuit_degraded(tower, tracker)
    tracker.settle()
    return response.object_response(domain.circuit_view(circuit))


# ---------------------------------------------------------------------------
# spectrum licences
# ---------------------------------------------------------------------------
@bp.post("/spectrum-licenses")
def create_license():
    mw.require(mw.ROLE_NETWORK_ENGINEER)
    payload = mw.body()
    license_ref = mw.v_str(payload, "license_ref")
    band = mw.v_enum(payload, "band", BANDS)
    center = mw.v_num(payload, "channel_center_mhz", minimum="600.0", maximum="6000.0", places=1)
    width = mw.v_num(payload, "channel_width_mhz", minimum="5.0", maximum="200.0", places=1)
    max_eirp = mw.v_num(payload, "max_eirp_dbm", minimum="20.0", maximum="65.0", places=1)
    area_code = mw.v_str(payload, "license_area_code")
    effective_from = mw.v_ts(payload, "effective_from")
    effective_to = mw.v_ts(payload, "effective_to")
    if effective_to <= effective_from:
        raise ApiError("ERR_VALIDATION",
                       "Field 'effective_to' must be strictly later than 'effective_from'.")

    for record in db.spectrum_licenses.values():
        if record["license_ref"] == license_ref:
            raise ApiError("ERR_DUPLICATE_LICENSE_REF")

    record = db.base_record(
        license_ref=license_ref,
        band=band,
        channel_center_mhz=center,
        channel_width_mhz=width,
        max_eirp_dbm=max_eirp,
        license_area_code=area_code,
        effective_from=effective_from,
        effective_to=effective_to,
    )
    db.spectrum_licenses[record["id"]] = record
    return response.created(domain.license_view(record))


@bp.get("/spectrum-licenses/<license_id>")
def read_license(license_id):
    mw.require(mw.ROLE_NETWORK_ENGINEER, mw.ROLE_CAPACITY_PLANNER)
    record = resolve.license_(license_id)
    return response.object_response(domain.license_view(record))
