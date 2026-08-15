"""Refrigeration systems: registration, status machine, gauge readings, and
the floating head pressure computed call (PRD 3.1, 3.4).

Every handler runs the pipeline in order: step 0 payload value validation
(400) -> step 2 entity-backed identity (403) -> step 3 existence (404) ->
state/safety/temporal/conflict/cross-facility/fiscal as declared.
"""
from decimal import Decimal

from flask import Blueprint

import calc
import envelope
from errors import ApiError
from guards import (
    ALL_ROLES,
    apply_filters,
    bad_request,
    body_row,
    endpoint,
    operator_employee,
    opt_bool,
    opt_number,
    paginate,
    pagination,
    path_row,
    req_number,
    req_string,
)
from serialize import system_out
from store import db, sorted_rows, touch
from util import ZERO

bp = Blueprint("systems", __name__)

CREATE_SCHEMA = (
    frozenset(
        [
            "facility_id",
            "name",
            "design_charge_lbs",
            "condenser_approach_f",
            "min_head_psig",
            "max_head_psig",
            "float_head_enabled",
        ]
    ),
    frozenset(["facility_id", "name", "design_charge_lbs"]),
)
STATUS_SCHEMA = (frozenset(["to_status"]), frozenset(["to_status"]))
GAUGE_SCHEMA = (frozenset(["reading_lbs"]), frozenset(["reading_lbs"]))
HEAD_SCHEMA = (
    frozenset(["wet_bulb_f", "condenser_load_pct"]),
    frozenset(["wet_bulb_f", "condenser_load_pct"]),
)

STATUS_VALUES = ("IN_SERVICE", "OUT_OF_SERVICE", "DECOMMISSIONED")

# Declared moves of the status machine (SCAFFOLD 1.2).
_TRANSITIONS = {
    ("IN_SERVICE", "OUT_OF_SERVICE"),
    ("OUT_OF_SERVICE", "IN_SERVICE"),
    ("OUT_OF_SERVICE", "DECOMMISSIONED"),
}


@bp.post("/psm/refrigeration-systems")
@endpoint(["FacilityAdmin"], schema=CREATE_SCHEMA)
def create_system(ctx):
    # step 0 -- payload values
    name = req_string(ctx.body, "name")
    design = req_number(ctx.body, "design_charge_lbs")
    approach = opt_number(ctx.body, "condenser_approach_f", Decimal("15.0"))
    min_head = opt_number(ctx.body, "min_head_psig", Decimal("150.0"))
    max_head = opt_number(ctx.body, "max_head_psig", Decimal("185.0"))
    float_enabled = opt_bool(ctx.body, "float_head_enabled", True)
    # step 3 -- existence
    facility = body_row(ctx.body, "facilities", "facility_id")
    row = db.create(
        "systems",
        {
            "facility_id": facility["id"],
            "name": name,
            "design_charge_lbs": design,
            "condenser_approach_f": approach,
            "min_head_psig": min_head,
            "max_head_psig": max_head,
            "float_head_enabled": float_enabled,
            "last_gauge_reading_lbs": None,
            "last_gauge_reading_at": None,
            "status": "IN_SERVICE",
        },
    )
    return envelope.created(system_out(row))


@bp.get("/psm/refrigeration-systems/<system_id>")
@endpoint(ALL_ROLES)
def get_system(ctx, system_id):
    return envelope.ok(system_out(path_row("systems", system_id)))


@bp.get("/psm/refrigeration-systems")
@endpoint(ALL_ROLES)
def list_systems(ctx):
    limit, offset = pagination(ctx)
    rows = sorted_rows(db.systems.values())
    rows = apply_filters(
        rows,
        ctx,
        [
            ("facility_id", "facility_id", None),
            ("status", "status", STATUS_VALUES),
        ],
    )
    total = len(rows)
    return envelope.listing(
        [system_out(r) for r in paginate(rows, limit, offset)], limit, offset, total
    )


@bp.post("/psm/refrigeration-systems/<system_id>/status")
@endpoint(["FacilityAdmin"], schema=STATUS_SCHEMA)
def set_status(ctx, system_id):
    # step 0 -- to_status membership in the declared target-state set
    raw = ctx.body["to_status"]
    if not isinstance(raw, str) or raw not in STATUS_VALUES:
        bad_request("Field 'to_status' carries a value outside its declared member set.")
    # step 3 -- existence
    system = path_row("systems", system_id)
    # step 5 -- source-state validity
    if (system["status"], raw) not in _TRANSITIONS:
        raise ApiError("ERR_INVALID_STATE")
    # step 10 -- decommission solvency: net book charge must be exactly zero
    if raw == "DECOMMISSIONED" and calc.system_book_total(system["id"]) != ZERO:
        raise ApiError("ERR_SYSTEM_NOT_EMPTY")
    system["status"] = raw
    touch(system)
    return envelope.ok(system_out(system))


@bp.post("/psm/refrigeration-systems/<system_id>/gauge-readings")
@endpoint(["Operator"], schema=GAUGE_SCHEMA)
def gauge_reading(ctx, system_id):
    reading = req_number(ctx.body, "reading_lbs")
    # step 2 -- entity-backed Operator identity
    operator_employee(ctx)
    # step 3
    system = path_row("systems", system_id)
    system["last_gauge_reading_lbs"] = reading
    system["last_gauge_reading_at"] = db.now()
    touch(system)
    return envelope.ok(system_out(system))


@bp.post("/psm/refrigeration-systems/<system_id>/head-pressure-target")
@endpoint(["Operator", "MaintenanceLead"], schema=HEAD_SCHEMA)
def head_pressure(ctx, system_id):
    wet_bulb = req_number(ctx.body, "wet_bulb_f")
    load = req_number(ctx.body, "condenser_load_pct")
    operator_employee(ctx)
    system = path_row("systems", system_id)
    result = calc.head_pressure_target(system, wet_bulb, load)
    return envelope.ok(
        {
            "system_id": system["id"],
            "effective_approach_f": result["effective_approach_f"],
            "condensing_temp_f": result["condensing_temp_f"],
            "raw_psig": result["raw_psig"],
            "target_psig": result["target_psig"],
            "variant": result["variant"],
        }
    )
