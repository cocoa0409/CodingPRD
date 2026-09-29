"""Obstetric units and their computed reads (PRD 3.1, 3.3, 3.8): 7 endpoints.

POST /obstetric-units, GET /obstetric-units, GET+PATCH /obstetric-units/{unitId},
GET .../capacity-summary, GET .../coverage-report, GET .../readiness-report
"""

from flask import Blueprint

import calc
import clock
import common
import const
import envelope
import rev
import store
from fields import pagination, q_enum, q_date, s_int, s_str
from pipeline import begin, fail, run_checks
from store import S, sort_rows

bp = Blueprint("units", __name__)

READ_ROLES = const.ALL_ROLES


@bp.post("/obstetric-units")
def create_unit():
    ctx = begin(
        roles=["PerinatalSafetyOfficer"],
        specs=[s_str("unit_name", required=True, min_len=1, max_len=120),
               s_int("licensed_ldr_beds", required=True, min=1),
               s_int("licensed_or_rooms", required=True, min=1),
               s_int("max_daily_induction_bed_minutes", min=0,
                     default=const.DEFAULT_INDUCTION_BED_MINUTES)],
    )
    name = ctx.v["unit_name"]

    def unique_name():
        for other in S.units.values():
            if other["unit_name"] == name:
                fail("ERR_DUPLICATE_UNIT_NAME")

    run_checks([(13.1, unique_name)])
    unit = store.new_record({
        "unit_name": name,
        "licensed_ldr_beds": ctx.v["licensed_ldr_beds"],
        "licensed_or_rooms": ctx.v["licensed_or_rooms"],
        "max_daily_induction_bed_minutes": ctx.v["max_daily_induction_bed_minutes"],
        "staffing_posture": "OPEN",
        "coverage_deficit_units": 0.0,
        "cesarean_readiness_state": "NOT_READY",
        "escalation_breach_count": 0,
        "bundle_breach_count": 0,
        "turnover_buffer_minutes": const.TURNOVER_BUFFER_OPEN,
        "committed_bed_minutes_by_day": {},
        "held_bed_minutes_by_day": {},
        "last_capacity_sweep_at": None,
        "readiness_reason": "NO_CURRENT_DRILL",
        "current_drill_id": None,
        "current_drill_expires_at": None,
        "mean_d2i_minutes": None,
        "_posture_reason": "NONE",
    })
    S.units[unit["id"]] = unit
    return common.created("units", unit)


@bp.get("/obstetric-units")
def list_units():
    begin(roles=READ_ROLES)
    posture = q_enum("staffing_posture", const.POSTURES)
    readiness = q_enum("cesarean_readiness_state", const.READINESS)
    found = [u for u in S.units.values()
             if common.match(u, "staffing_posture", posture)
             and common.match(u, "cesarean_readiness_state", readiness)]
    return common.listing("units", found, [("created_at", "asc")])


@bp.get("/obstetric-units/<unit_id>")
def read_unit(unit_id):
    ctx = begin(roles=READ_ROLES, path=[("unit", unit_id)])
    return common.single("units", ctx.p["unit"])


@bp.patch("/obstetric-units/<unit_id>")
def patch_unit(unit_id):
    ctx = begin(
        roles=["PerinatalSafetyOfficer"],
        path=[("unit", unit_id)],
        specs=[s_int("max_daily_induction_bed_minutes", required=True, min=0)],
    )
    unit = ctx.p["unit"]
    # The budget never moves the posture by itself.
    unit["max_daily_induction_bed_minutes"] = ctx.v["max_daily_induction_bed_minutes"]
    rev.touch(unit)
    return common.single("units", unit)


@bp.get("/obstetric-units/<unit_id>/capacity-summary")
def capacity_summary(unit_id):
    ctx = begin(roles=["ChargeNurse", "PatientAccessCoordinator",
                       "ObstetricianAttending", "PerinatalSafetyOfficer"],
                path=[("unit", unit_id)])
    unit = ctx.p["unit"]
    day = q_date("day")
    key = day.isoformat() if day is not None else clock.day_of(clock.now())
    committed = (unit.get("committed_bed_minutes_by_day") or {}).get(key) or 0
    held = (unit.get("held_bed_minutes_by_day") or {}).get(key) or 0
    beds = calc.rows("beds", unit_id=unit["id"])
    ldr = [b for b in beds if b["bed_type"] == "LDR"]

    def count(status):
        return len([b for b in ldr if b["status"] == status])

    return envelope.obj({
        "unit_id": unit["id"],
        "day": key,
        "committed_bed_minutes": committed,
        "held_bed_minutes": held,
        "day_load_minutes": committed + held,
        "max_daily_induction_bed_minutes": unit["max_daily_induction_bed_minutes"],
        "remaining_bed_minutes": unit["max_daily_induction_bed_minutes"] - (committed + held),
        "turnover_buffer_minutes": unit["turnover_buffer_minutes"],
        "staffing_posture": unit["staffing_posture"],
        "available_ldr_beds": count("AVAILABLE"),
        "held_ldr_beds": count("HELD"),
        "occupied_ldr_beds": count("OCCUPIED"),
        "turnover_ldr_beds": count("TURNOVER"),
        "last_capacity_sweep_at": clock.fmt_dt(unit.get("last_capacity_sweep_at")),
    })


@bp.get("/obstetric-units/<unit_id>/coverage-report")
def coverage_report(unit_id):
    ctx = begin(roles=["ChargeNurse", "BedsideNurse", "ObstetricianAttending",
                       "PerinatalSafetyOfficer"],
                path=[("unit", unit_id)])
    unit = ctx.p["unit"]
    limit, offset = pagination()
    deficit, posture, reason = calc.posture_view(unit)
    live = sort_rows(calc.live_encounters(unit["id"]), [("created_at", "asc")])
    window, total, has_more = store.paginate(live, limit, offset)
    data = {
        "unit_id": unit["id"],
        "coverage_deficit_units": deficit,
        "staffing_posture": posture,
        "posture_reason": reason,
        "escalation_breach_count": unit.get("escalation_breach_count") or 0,
        "bundle_breach_count": unit.get("bundle_breach_count") or 0,
        "encounters": [{
            "encounter_id": e["id"],
            "patient_record_code": e["patient_record_code"],
            "labor_phase": e["labor_phase"],
            "staffing_state": e["staffing_state"],
            "acuity_tier": e["acuity_tier"],
            "one_to_one_required": e["one_to_one_required"],
            "required_coverage_units": e["required_coverage_units"],
            "assigned_coverage_units": e["assigned_coverage_units"],
            "deficit_units": calc.encounter_deficit(e),
        } for e in window],
    }
    return envelope.obj_paged(data, limit, offset, total, has_more)


@bp.get("/obstetric-units/<unit_id>/readiness-report")
def readiness_report(unit_id):
    ctx = begin(roles=["ChargeNurse", "ObstetricianAttending", "AnesthesiaLead",
                       "PerinatalSafetyOfficer"],
                path=[("unit", unit_id)])
    view = calc.readiness_view(ctx.p["unit"])
    view["current_drill_expires_at"] = clock.fmt_dt(view["current_drill_expires_at"])
    return envelope.obj(view)
