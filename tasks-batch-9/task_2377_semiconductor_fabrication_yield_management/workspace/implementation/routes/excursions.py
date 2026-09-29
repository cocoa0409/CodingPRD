"""Excursion containment and disposition."""
from flask import Blueprint, g

import calc
from auth import require
from db import db, need, ordered, touch
from errors import fail
from response import ok
from routes.common import matches, paged
from services import cascades
from validate import body, q_enum, q_str, v_enum, v_str

bp = Blueprint("excursions", __name__)

SOURCE_TYPES = ("SPC", "DIE_SORT", "PARTICLE")
EXCURSION_STATUSES = ("OPEN", "CONTAINED", "DISPOSITIONED")
SCOPES = ("SPC_CHART", "CHAMBER", "EQUIPMENT")
DISPOSITIONS = ("CONTINUE", "REWORK", "SCRAP")
READERS = ("QualityManager", "YieldEngineer", "ProcessEngineer", "EquipmentEngineer",
           "FabPlanner")


@bp.get("/fab/excursions")
@require(*READERS)
def list_excursions():
    filters = {
        "spc_chart_id": q_str("spc_chart_id"),
        "die_sort_run_id": q_str("die_sort_run_id"),
        "chamber_id": q_str("chamber_id"),
        "lot_id": q_str("lot_id"),
        "source_type": q_enum("source_type", SOURCE_TYPES),
        "status": q_enum("status", EXCURSION_STATUSES),
    }
    return paged([e for e in db.excursions.values() if matches(e, filters)])


@bp.get("/fab/excursions/<excursion_id>")
@require(*READERS)
def read_excursion(excursion_id):
    return ok(need(db.excursions, excursion_id, "ERR_EXCURSION_NOT_FOUND"))


@bp.post("/fab/excursions/<excursion_id>/contain")
@require("QualityManager")
def contain(excursion_id):
    data = body()
    scope = v_enum(data, "containment_scope", SCOPES)
    chamber_id = v_str(data, "chamber_id", required=False, default=None)
    if scope in ("CHAMBER", "EQUIPMENT") and chamber_id is None:
        fail("ERR_VALIDATION", "chamber_id is required for %s containment" % scope)

    excursion = need(db.excursions, excursion_id, "ERR_EXCURSION_NOT_FOUND")
    chamber = None
    if chamber_id is not None:
        chamber = need(db.chambers, chamber_id, "ERR_CHAMBER_NOT_FOUND")

    if excursion["status"] != "OPEN":
        fail("ERR_EXCURSION_INVALID_STATE", "Excursion is %s, not OPEN" % excursion["status"])
    if excursion["source_type"] not in ("SPC", "DIE_SORT"):
        fail("ERR_EXCURSION_INVALID_STATE",
             "PARTICLE excursions are contained automatically at creation")

    cascades.finalize_severity(excursion)
    excursion["containment_scope"] = scope
    excursion["contained_by_user_id"] = g.user_id
    excursion["status"] = "CONTAINED"
    touch(excursion)

    cascades.apply_containment(excursion, scope, chamber)
    return ok(excursion)


@bp.post("/fab/excursions/<excursion_id>/disposition")
@require("QualityManager", "YieldEngineer")
def disposition(excursion_id):
    data = body()
    value = v_enum(data, "disposition", DISPOSITIONS)
    v_str(data, "root_cause_note")

    excursion = need(db.excursions, excursion_id, "ERR_EXCURSION_NOT_FOUND")
    if excursion["contained_by_user_id"] is not None \
            and g.user_id == excursion["contained_by_user_id"]:
        fail("ERR_SOD_SELF_DISPOSITION",
             "The containing engineer may not disposition their own containment")
    if excursion["status"] != "CONTAINED":
        fail("ERR_EXCURSION_INVALID_STATE",
             "Excursion is %s, not CONTAINED" % excursion["status"])

    excursion["disposition"] = value
    excursion["dispositioned_by_user_id"] = g.user_id
    excursion["status"] = "DISPOSITIONED"
    touch(excursion)

    # Any chart this excursion's containment suspended returns to MONITORING.
    if excursion["containment_scope"] == "SPC_CHART" and excursion["spc_chart_id"]:
        chart = db.spc_charts.get(excursion["spc_chart_id"])
        if chart is not None and chart["status"] == "SUSPENDED":
            chart["status"] = "MONITORING"
            chart["consecutive_same_side_count"] = 0
            chart["last_side"] = "NONE"
            touch(chart)

    if value == "CONTINUE":
        for lot in ordered(db.lots.values()):
            if lot["hold_excursion_id"] == excursion["id"] and lot["hold_state"] != "NONE":
                cascades.release_hold(lot)
    elif value == "SCRAP":
        affected = calc.affected_lot_ids(excursion, "FINAL")
        for lot in ordered(db.lots.values()):
            if lot["id"] not in affected:
                continue
            if lot["flow_state"] not in ("RELEASED", "IN_PROCESS", "AT_SORT"):
                continue
            was_in_process = lot["flow_state"] == "IN_PROCESS"
            lot["flow_state"] = "SCRAPPED"
            lot["hold_state"] = "NONE"
            lot["hold_excursion_id"] = None
            touch(lot)
            if was_in_process:
                for run in ordered(db.step_runs.values()):
                    if run["lot_id"] == lot["id"] and run["status"] == "OPEN":
                        cascades.abort_run(run)
    return ok(excursion)
