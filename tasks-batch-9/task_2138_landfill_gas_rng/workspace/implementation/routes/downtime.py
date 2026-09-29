"""DowntimeEvent endpoints."""

from decimal import Decimal

from flask import Blueprint

import derived
import store
from auth import authenticate, require_role
from common import minutes_between, r2
from envelope import object_response, paginate, pagination
from errors import fail
from helpers import arg, filter_equal, must_find
from serializers import downtime_out
from validation import Field, parse_body, validate

bp = Blueprint("downtime", __name__)

ZERO = Decimal("0")

DOWNTIME_FIELDS = [
    Field("plant_id", "string", required=True),
    Field("start_at", "datetime", required=True),
    Field(
        "cause",
        "enum",
        required=True,
        values=(
            "PLANNED_MAINTENANCE",
            "COMPRESSOR_TRIP",
            "OFF_SPEC_TRIP",
            "WELLFIELD_SHORTFALL",
            "PIPELINE_CURTAILMENT",
        ),
    ),
    Field("disposition", "enum", required=True, values=("FLARED", "VENTED", "BYPASS")),
]


@bp.post("/downtime-events")
def create_downtime():
    caller = authenticate()
    require_role(caller, ["ProjectAdmin", "PlantOperator"])
    body = parse_body()
    data = validate(body, DOWNTIME_FIELDS)

    plant = must_find("plant", data["plant_id"])

    row = store.new_row(
        plant_id=plant["id"],
        start_at=data["start_at"],
        end_at=None,
        cause=data["cause"],
        disposition=data["disposition"],
        status="OPEN",
        flared_mmbtu=r2(ZERO),
        vented_mmbtu=r2(ZERO),
        duration_minutes=r2(ZERO),
        auto_generated=False,
    )
    store.downtime_events[row["id"]] = row
    return object_response(downtime_out(row), 201)


@bp.get("/downtime-events/<event_id>")
def read_downtime(event_id):
    caller = authenticate()
    require_role(caller, ["ProjectAdmin", "PlantOperator", "ComplianceOfficer"])
    row = must_find("downtime", event_id)
    return object_response(downtime_out(row))


@bp.get("/downtime-events")
def list_downtime():
    caller = authenticate()
    require_role(caller, ["ProjectAdmin", "PlantOperator", "ComplianceOfficer"])
    limit, offset = pagination()
    rows = store.ordered(store.downtime_events.values())
    rows = filter_equal(rows, "plant_id", arg("plant_id"))
    rows = filter_equal(rows, "status", arg("status"))
    rows = filter_equal(rows, "cause", arg("cause"))
    return paginate(rows, limit, offset, downtime_out)


CLOSE_FIELDS = [
    Field("end_at", "datetime", required=True),
    Field("flared_mmbtu", "number", default=ZERO),
    Field("vented_mmbtu", "number", default=ZERO),
]


@bp.post("/downtime-events/<event_id>/close")
def close_downtime(event_id):
    caller = authenticate()
    require_role(caller, ["ProjectAdmin", "PlantOperator"])
    event = must_find("downtime", event_id)
    body = parse_body()
    data = validate(body, CLOSE_FIELDS)

    # Priority 57 - interval direction.
    if data["end_at"] <= event["start_at"]:
        fail("ERR_INTERVAL_INVALID", "end_at must be strictly after start_at.")

    # Priority 80 - the record must still be open.
    if event["status"] == "CLOSED":
        fail("ERR_DOWNTIME_ALREADY_CLOSED", "This downtime record is already closed.")

    flared = data["flared_mmbtu"]
    vented = data["vented_mmbtu"]
    duration = r2(minutes_between(event["start_at"], data["end_at"]))

    derived.apply_changes(
        event,
        {
            "status": "CLOSED",
            "end_at": data["end_at"],
            "flared_mmbtu": r2(flared),
            "vented_mmbtu": r2(vented),
            "duration_minutes": duration,
        },
    )

    plant = store.plants.get(event["plant_id"])
    if plant is not None:
        site = derived.site_of_plant(plant)
        if site is not None:
            derived.move_energy(site, produced=flared + vented, flared=flared, vented=vented)
        derived.recompute_plant_availability(plant)

    return object_response(downtime_out(event))
