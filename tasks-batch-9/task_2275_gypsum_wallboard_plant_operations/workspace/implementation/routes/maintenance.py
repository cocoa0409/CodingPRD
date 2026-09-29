"""Maintenance outages, deferral and the seasonality gate (PRD 3.9)."""

from decimal import Decimal

from flask import Blueprint

import calc
import validate as v
from db import base_entity, bump, db, ordered
from errors import fail
from middleware import ANY, acting_user_id, guard
from response import entity_response
from routes.common import list_collection, require_outage, require_ref
from services.cascade import cancel_run
from services.plant import settle_plant
from util import D, ZERO3, rhu

bp = Blueprint("maintenance", __name__)

OUTAGE_TYPES = ("PLANNED", "EMERGENCY")


def _line_of(outage):
    return db.board_lines[outage["line_id"]]


def _plant_of(outage):
    return db.plants[_line_of(outage)["plant_id"]]


def _intersects_closed(outage, run):
    """Closed-interval intersection between an outage window and a run window."""
    return (
        run["_window_start"] <= outage["_window_end"]
        and run["_window_end"] >= outage["_window_start"]
    )


def _at_risk_runs(outage):
    return [
        run
        for run in ordered(db.production_runs)
        if run["line_id"] == outage["line_id"]
        and run["status"] in ("SCHEDULED", "RUNNING")
        and _intersects_closed(outage, run)
    ]


def _derive(outage, plant):
    outage["seasonality_index"] = calc.seasonality_index_of(outage["_window_start"])
    outage["planned_downtime_hours"] = calc.planned_downtime_hours(
        outage["_window_start"], outage["_window_end"]
    )
    total = Decimal(0)
    for run in _at_risk_runs(outage):
        if run["effective_planned_msf"] is not None:
            total += D(run["effective_planned_msf"])
    at_risk = rhu(total, 3)
    outage["at_risk_msf"] = at_risk
    outage["opportunity_cost_usd"] = rhu(
        at_risk * D(plant["contribution_margin_per_msf"]), 2
    )


@bp.post("/plant-ops/maintenance-outages")
@guard(("MaintenancePlanner",))
def propose_outage():
    body = v.body_of()
    line_id = v.text(body, "line_id", min_len=1)
    outage_type = v.enum(body, "outage_type", OUTAGE_TYPES)
    start_raw, start = v.instant(body, "window_start")
    end_raw, end = v.instant(body, "window_end")
    scope_note = v.text(body, "scope_note", required=False)

    line = require_ref(db.board_lines, line_id, "board line")

    if end <= start:
        fail("ERR_INVALID_WINDOW", "window_end must be strictly after window_start")

    outage = base_entity()
    outage.update(
        {
            "line_id": line["id"],
            "outage_type": outage_type,
            "window_start": start_raw,
            "window_end": end_raw,
            "_window_start": start,
            "_window_end": end,
            "scope_note": scope_note,
            "proposed_by_user_id": acting_user_id(),
            "approved_by_user_id": None,
            "deferral_count": 0,
            "deferred_reason": None,
            "close_note": None,
            "seasonality_index": None,
            "planned_downtime_hours": None,
            "at_risk_msf": ZERO3,
            "opportunity_cost_usd": None,
            "status": "PROPOSED",
        }
    )
    _derive(outage, db.plants[line["plant_id"]])
    db.maintenance_outages[outage["id"]] = outage
    return entity_response(outage, 201)


@bp.get("/plant-ops/maintenance-outages")
@guard(ANY)
def list_outages():
    return list_collection(db.maintenance_outages, ("line_id", "status", "outage_type"))


@bp.get("/plant-ops/maintenance-outages/<outage_id>")
@guard(ANY)
def read_outage(outage_id):
    return entity_response(require_outage(outage_id))


@bp.post("/plant-ops/maintenance-outages/<outage_id>/approve")
@guard(("PlantManager",))
def approve_outage(outage_id):
    outage = require_outage(outage_id)
    v.body_of()

    line = _line_of(outage)
    plant = _plant_of(outage)

    if outage["status"] != "PROPOSED":
        fail("ERR_INVALID_STATE", "only a PROPOSED outage may be approved")
    if line["status"] != "AVAILABLE":
        fail("ERR_LINE_NOT_AVAILABLE", "the line is %s" % line["status"])
    if acting_user_id() == outage["proposed_by_user_id"]:
        fail(
            "ERR_SEGREGATION_OF_DUTIES",
            "the proposer of an outage may not approve it",
        )

    for other in ordered(db.maintenance_outages):
        if other["id"] == outage["id"] or other["line_id"] != outage["line_id"]:
            continue
        if other["status"] not in ("APPROVED", "IN_PROGRESS"):
            continue
        if (
            outage["_window_start"] <= other["_window_end"]
            and other["_window_start"] <= outage["_window_end"]
        ):
            fail(
                "ERR_OUTAGE_WINDOW_CONFLICT",
                "another approved outage on this line intersects this window",
            )

    _derive(outage, plant)
    if not calc.outage_gate_allowed(outage):
        fail(
            "ERR_SEASONALITY_WINDOW_UNFAVORABLE",
            "seasonality index %s exceeds the planned-outage ceiling"
            % outage["seasonality_index"],
        )

    outage["approved_by_user_id"] = acting_user_id()
    outage["status"] = "APPROVED"
    bump(outage)

    # hop 1 -> 2
    line["status"] = "MAINTENANCE_SCHEDULED"
    bump(line)

    # hop 2 -> 3 and 3 -> 4
    for run in ordered(db.production_runs):
        if run["line_id"] != outage["line_id"]:
            continue
        if run["status"] not in ("DRAFT", "SCHEDULED"):
            continue
        if not _intersects_closed(outage, run):
            continue
        cancel_run(run, plant, "OUTAGE_APPROVED:" + outage["id"])

    return entity_response(outage)


@bp.post("/plant-ops/maintenance-outages/<outage_id>/defer")
@guard(("MaintenancePlanner",))
def defer_outage(outage_id):
    outage = require_outage(outage_id)
    body = v.body_of()
    deferred_reason = v.text(body, "deferred_reason", required=False)

    if outage["status"] != "PROPOSED":
        fail("ERR_INVALID_STATE", "only a PROPOSED outage may be deferred")
    if int(outage["deferral_count"]) >= calc.MAX_DEFERRALS:
        fail("ERR_MAX_DEFERRALS_REACHED", "this outage has already been deferred twice")

    outage["deferral_count"] = int(outage["deferral_count"]) + 1
    outage["deferred_reason"] = deferred_reason
    outage["status"] = "DEFERRED"
    bump(outage)
    return entity_response(outage)


@bp.post("/plant-ops/maintenance-outages/<outage_id>/repropose")
@guard(("MaintenancePlanner",))
def repropose_outage(outage_id):
    outage = require_outage(outage_id)
    body = v.body_of()
    start_raw, start = v.instant(body, "window_start")
    end_raw, end = v.instant(body, "window_end")
    scope_note = v.text(body, "scope_note", required=False)

    if outage["status"] != "DEFERRED":
        fail("ERR_INVALID_STATE", "only a DEFERRED outage may be re-proposed")
    if end <= start:
        fail("ERR_INVALID_WINDOW", "window_end must be strictly after window_start")

    outage["window_start"] = start_raw
    outage["window_end"] = end_raw
    outage["_window_start"] = start
    outage["_window_end"] = end
    if scope_note is not None:
        outage["scope_note"] = scope_note
    _derive(outage, _plant_of(outage))
    outage["status"] = "PROPOSED"
    bump(outage)
    return entity_response(outage)


@bp.post("/plant-ops/maintenance-outages/<outage_id>/start")
@guard(("MaintenancePlanner",))
def start_outage(outage_id):
    outage = require_outage(outage_id)
    v.body_of()

    line = _line_of(outage)
    plant = _plant_of(outage)

    if outage["status"] != "APPROVED":
        fail("ERR_INVALID_STATE", "only an APPROVED outage may be started")
    for run in db.production_runs.values():
        if run["line_id"] == outage["line_id"] and run["status"] == "RUNNING":
            fail("ERR_RUN_ACTIVE_ON_LINE", "a production run is still RUNNING on this line")
    if db.now() < outage["_window_start"]:
        fail("ERR_OUTAGE_WINDOW_NOT_STARTED", "the logical clock has not reached window_start")

    outage["status"] = "IN_PROGRESS"
    bump(outage)

    line["status"] = "UNDER_MAINTENANCE"
    bump(line)

    if outage["outage_type"] == "EMERGENCY":
        settle_plant(plant)

    return entity_response(outage)


@bp.post("/plant-ops/maintenance-outages/<outage_id>/close")
@guard(("MaintenancePlanner",))
def close_outage(outage_id):
    outage = require_outage(outage_id)
    body = v.body_of()
    close_note = v.text(body, "close_note", required=False)

    line = _line_of(outage)
    plant = _plant_of(outage)

    if outage["status"] != "IN_PROGRESS":
        fail("ERR_INVALID_STATE", "only an IN_PROGRESS outage may be closed")

    outage["close_note"] = close_note
    outage["status"] = "CLOSED"
    bump(outage)

    line["status"] = "AVAILABLE"
    bump(line)

    settle_plant(plant)
    return entity_response(outage)
