"""GasWell, WellTuningReading and manual well status endpoints."""

from decimal import Decimal

from flask import Blueprint

import calc
import derived
import store
from auth import authenticate, deny_role, require_role
from common import r2
from envelope import object_response, paginate, pagination
from errors import fail
from helpers import arg, filter_equal, must_find
from serializers import reading_out, well_out
from validation import Field, parse_body, peek_body, validate

bp = Blueprint("wells", __name__)

ZERO = Decimal("0")

WELL_FIELDS = [
    Field("site_id", "string", required=True),
    Field("well_code", "string", required=True, max_len=20),
    Field("target_flow_scfm", "number", required=True, gt=0),
]


@bp.post("/wells")
def create_well():
    caller = authenticate()
    require_role(caller, ["ProjectAdmin", "WellfieldTechnician"])
    body = parse_body()
    data = validate(body, WELL_FIELDS)

    site = must_find("site", data["site_id"])

    for well in store.wells.values():
        if (
            well["site_id"] == site["id"]
            and well["well_code"] == data["well_code"]
            and well["operating_state"] != "DECOMMISSIONED"
        ):
            fail(
                "ERR_WELL_CODE_DUPLICATE",
                "well_code is already used by a live well of this site.",
            )

    row = store.new_row(
        site_id=site["id"],
        well_code=data["well_code"],
        target_flow_scfm=data["target_flow_scfm"],
        operating_state="ONLINE",
        current_flow_scfm=r2(ZERO),
        last_reading_flow_scfm=r2(ZERO),
        wellhead_vacuum_inhg=r2(ZERO),
        last_quality_class="NONE",
        last_reading_at=None,
        consecutive_good_readings=0,
        lockout_work_order_id=None,
    )
    store.wells[row["id"]] = row
    derived.recompute_site_flow(site)
    return object_response(well_out(row), 201)


@bp.get("/wells/<well_id>")
def read_well(well_id):
    caller = authenticate()
    require_role(
        caller, ["ProjectAdmin", "WellfieldTechnician", "PlantOperator", "ComplianceOfficer"]
    )
    row = must_find("well", well_id)
    return object_response(well_out(row))


@bp.get("/wells")
def list_wells():
    caller = authenticate()
    require_role(
        caller, ["ProjectAdmin", "WellfieldTechnician", "PlantOperator", "ComplianceOfficer"]
    )
    limit, offset = pagination()
    rows = store.ordered(store.wells.values())
    rows = filter_equal(rows, "site_id", arg("site_id"))
    rows = filter_equal(rows, "operating_state", arg("operating_state"))
    return paginate(rows, limit, offset, well_out)


READING_FIELDS = [
    Field("taken_at", "datetime", required=True),
    Field("methane_pct", "number", required=True, gte=0, lte=100),
    Field("oxygen_pct", "number", required=True, gte=0, lte=25),
    Field("nitrogen_pct", "number", required=True, gte=0, lte=100),
    Field("temperature_f", "number", required=True, gte=0, lte=250),
    Field("flow_scfm", "number", required=True, gte=0),
    Field("vacuum_inhg", "number", required=True, gte=0),
]


@bp.post("/wells/<well_id>/readings")
def create_reading(well_id):
    caller = authenticate()
    require_role(caller, ["WellfieldTechnician"])
    well = must_find("well", well_id)
    body = parse_body()
    data = validate(body, READING_FIELDS)

    # Priority 55 - gas composition coherence.
    if data["methane_pct"] + data["oxygen_pct"] + data["nitrogen_pct"] > Decimal("100"):
        fail(
            "ERR_GAS_COMPOSITION_INVALID",
            "methane_pct + oxygen_pct + nitrogen_pct may not exceed 100.",
        )

    # Priority 80 - well state.
    if well["operating_state"] == "DECOMMISSIONED":
        fail("ERR_WELL_DECOMMISSIONED", "The well has been decommissioned.")
    if well["operating_state"] == "MAINTENANCE_LOCKOUT":
        fail("ERR_WELL_IN_LOCKOUT", "The well is locked out for maintenance.")

    # Priority 85 - reading chronology.
    if well["last_reading_at"] is not None and data["taken_at"] <= well["last_reading_at"]:
        fail(
            "ERR_READING_OUT_OF_ORDER",
            "taken_at must be strictly after the well's last reading.",
        )

    index = calc.air_intrusion_index(
        data["methane_pct"], data["oxygen_pct"], data["nitrogen_pct"], data["temperature_f"]
    )
    quality = calc.quality_class(
        data["methane_pct"], data["oxygen_pct"], data["temperature_f"], index
    )

    state = well["operating_state"]
    changes = {
        "last_quality_class": quality,
        "last_reading_at": data["taken_at"],
        "last_reading_flow_scfm": data["flow_scfm"],
        "wellhead_vacuum_inhg": data["vacuum_inhg"],
    }

    if quality == "ALARM":
        if state in ("ONLINE", "THROTTLED"):
            changes["operating_state"] = "ISOLATED"
        changes["current_flow_scfm"] = r2(ZERO)
        changes["consecutive_good_readings"] = 0
    elif quality == "WATCH":
        if state == "ISOLATED":
            changes["current_flow_scfm"] = r2(ZERO)
        else:
            changes["operating_state"] = "THROTTLED"
            changes["current_flow_scfm"] = calc.throttled_flow(
                data["flow_scfm"], well["target_flow_scfm"]
            )
        changes["consecutive_good_readings"] = 0
    else:  # GOOD
        if state == "ISOLATED":
            changes["current_flow_scfm"] = r2(ZERO)
        elif state == "THROTTLED":
            changes["current_flow_scfm"] = calc.throttled_flow(
                data["flow_scfm"], well["target_flow_scfm"]
            )
        else:
            changes["current_flow_scfm"] = r2(data["flow_scfm"])
        changes["consecutive_good_readings"] = well["consecutive_good_readings"] + 1

    derived.apply_changes(well, changes)

    reading = store.new_event_row(
        well_id=well["id"],
        taken_at=data["taken_at"],
        methane_pct=data["methane_pct"],
        oxygen_pct=data["oxygen_pct"],
        nitrogen_pct=data["nitrogen_pct"],
        temperature_f=data["temperature_f"],
        flow_scfm=data["flow_scfm"],
        vacuum_inhg=data["vacuum_inhg"],
        air_intrusion_index=index,
        quality_class=quality,
        resulting_well_state=well["operating_state"],
        recorded_by_user_id=caller.user_id,
    )
    store.readings[reading["id"]] = reading

    site = store.sites.get(well["site_id"])
    if site is not None:
        derived.recompute_site_flow(site)
        derived.propagate_shortfall(site)

    return object_response(reading_out(reading), 201)


@bp.get("/wells/<well_id>/readings")
def list_readings(well_id):
    caller = authenticate()
    require_role(caller, ["ProjectAdmin", "WellfieldTechnician", "ComplianceOfficer"])
    well = must_find("well", well_id)
    limit, offset = pagination()
    rows = [r for r in store.readings.values() if r["well_id"] == well["id"]]
    rows = filter_equal(rows, "quality_class", arg("quality_class"))
    rows.sort(key=lambda r: (r["taken_at"], r["_seq"]), reverse=True)
    return paginate(rows, limit, offset, reading_out)


WELL_STATUS_FIELDS = [
    Field(
        "to_state",
        "enum",
        required=True,
        values=("ONLINE", "THROTTLED", "ISOLATED", "MAINTENANCE_LOCKOUT", "DECOMMISSIONED"),
    ),
    Field("reason", "string", max_len=500),
]

MANUAL_WELL_TRANSITIONS = {
    ("ISOLATED", "THROTTLED"),
    ("THROTTLED", "ONLINE"),
    ("ONLINE", "DECOMMISSIONED"),
    ("THROTTLED", "DECOMMISSIONED"),
    ("ISOLATED", "DECOMMISSIONED"),
}


@bp.post("/wells/<well_id>/status")
def well_status(well_id):
    caller = authenticate()
    require_role(caller, ["ProjectAdmin", "WellfieldTechnician"])

    # Narrower-than-endpoint authority: retiring a well is a ProjectAdmin act.
    requested = peek_body().get("to_state")
    if caller.role == "WellfieldTechnician" and requested == "DECOMMISSIONED":
        deny_role("Only a ProjectAdmin may decommission a well.")

    well = must_find("well", well_id)
    body = parse_body()
    data = validate(body, WELL_STATUS_FIELDS)
    target = data["to_state"]
    current = well["operating_state"]

    # Priority 80 - state legality.
    if current == "DECOMMISSIONED":
        fail("ERR_WELL_DECOMMISSIONED", "The well has been decommissioned.")
    if (current, target) not in MANUAL_WELL_TRANSITIONS:
        fail("ERR_INVALID_TRANSITION", "%s -> %s is not a declared transition." % (current, target))

    # Priority 90 - recovery evidence.
    if target == "THROTTLED":
        if well["last_quality_class"] != "GOOD" or well["consecutive_good_readings"] < 2:
            fail(
                "ERR_WELL_NOT_RECOVERED",
                "Returning to THROTTLED requires two consecutive GOOD readings.",
            )
    elif target == "ONLINE":
        if well["last_quality_class"] != "GOOD" or well["consecutive_good_readings"] < 3:
            fail(
                "ERR_WELL_NOT_RECOVERED",
                "Returning to ONLINE requires three consecutive GOOD readings.",
            )

    changes = {"operating_state": target}
    if target == "THROTTLED":
        changes["current_flow_scfm"] = calc.throttled_flow(
            well["last_reading_flow_scfm"], well["target_flow_scfm"]
        )
    elif target == "ONLINE":
        changes["current_flow_scfm"] = r2(well["last_reading_flow_scfm"])
    elif target == "DECOMMISSIONED":
        changes["current_flow_scfm"] = r2(ZERO)

    derived.apply_changes(well, changes)

    site = store.sites.get(well["site_id"])
    if site is not None:
        derived.recompute_site_flow(site)
        if target in ("THROTTLED", "ONLINE"):
            derived.propagate_recovery(site)

    return object_response(well_out(well))
