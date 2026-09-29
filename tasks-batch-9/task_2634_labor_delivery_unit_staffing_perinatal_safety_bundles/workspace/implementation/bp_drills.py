"""Cesarean readiness drills (PRD 3.8): 9 endpoints."""

from flask import Blueprint

import calc
import clock
import common
import const
import rev
import store
from fields import q_enum, q_str, s_array, s_dt, s_enum, s_str
from pipeline import begin, fail, need, run_checks, same_unit
from store import S

bp = Blueprint("drills", __name__)

READ_ROLES = ["ChargeNurse", "ObstetricianAttending", "AnesthesiaLead",
              "PerinatalSafetyOfficer"]


def _filtered(records):
    status = q_enum("status", const.DRILL_STATUSES)
    drill_type = q_enum("drill_type", const.DRILL_TYPES)
    participant = q_str("participant_staff_id")
    documenter = q_str("documented_by_staff_id")
    return [d for d in records
            if common.match(d, "status", status)
            and common.match(d, "drill_type", drill_type)
            and common.match(d, "documented_by_staff_id", documenter)
            and (participant is None
                 or participant in (d.get("participant_staff_ids") or []))]


@bp.post("/obstetric-units/<unit_id>/cesarean-readiness-drills")
def schedule_drill(unit_id):
    ctx = begin(
        roles=["ChargeNurse", "AnesthesiaLead"],
        path=[("unit", unit_id)],
        specs=[s_enum("drill_type", const.DRILL_TYPES, required=True),
               s_dt("scheduled_for_utc", required=True),
               s_array("participant_staff_ids", required=True, min_len=2, max_len=20)],
    )
    unit = ctx.p["unit"]
    participants = []
    for staff_id in ctx.v["participant_staff_ids"]:      # priority 4, payload order
        member = S.staff.get(staff_id)
        if member is None:
            fail("ERR_STAFF_NOT_FOUND")
        participants.append(member)
    same_unit(ctx, unit["id"], participants)             # priority 7

    def credential():
        for member in participants:
            need(member["employment_status"] == "ACTIVE"
                 and member["credential_expires_at"] > clock.now(),
                 "ERR_STAFF_CREDENTIAL_EXPIRED")

    def stamp():
        need(ctx.v["scheduled_for_utc"] >= clock.now(),
             "ERR_DRILL_TIMESTAMP_OUT_OF_RANGE")

    run_checks([(11.1, credential), (14.1, stamp)])

    drill = store.new_record({
        "unit_id": unit["id"],
        "drill_type": ctx.v["drill_type"],
        "scheduled_for_utc": ctx.v["scheduled_for_utc"],
        "participant_staff_ids": list(ctx.v["participant_staff_ids"]),
        "decision_at": None,
        "incision_at": None,
        "measured_d2i_minutes": None,
        "status": "SCHEDULED",
        "validated_at": None,
        "validated_by_user_id": None,
        "documented_by_staff_id": None,
        "expires_at": None,
        "invalidation_reason": None,
        "revision_count": 0,
    })
    S.drills[drill["id"]] = drill
    # An unvalidated drill grants no currency, so readiness is untouched here.
    rev.touch(unit)
    return common.created("drills", drill)


@bp.get("/obstetric-units/<unit_id>/cesarean-readiness-drills")
def list_unit_drills(unit_id):
    ctx = begin(roles=READ_ROLES, path=[("unit", unit_id)])
    found = _filtered(calc.rows("drills", unit_id=ctx.p["unit"]["id"]))
    return common.listing("drills", found,
                          [("scheduled_for_utc", "desc"), ("created_at", "desc")])


@bp.get("/cesarean-readiness-drills")
def list_drills():
    begin(roles=READ_ROLES)
    unit_id = q_str("unit_id")
    found = _filtered([d for d in S.drills.values()
                       if common.match(d, "unit_id", unit_id)])
    return common.listing("drills", found,
                          [("scheduled_for_utc", "asc"), ("created_at", "asc")])


@bp.get("/cesarean-readiness-drills/<drill_id>")
def read_drill(drill_id):
    ctx = begin(roles=READ_ROLES, path=[("drill", drill_id)])
    return common.single("drills", ctx.p["drill"])


@bp.post("/cesarean-readiness-drills/<drill_id>/start")
def start_drill(drill_id):
    ctx = begin(roles=["ChargeNurse"], path=[("drill", drill_id)])
    drill = ctx.p["drill"]
    unit = S.units.get(drill["unit_id"])

    def declared():
        need(drill["status"] == "SCHEDULED", "ERR_INVALID_STATE_TRANSITION")

    def posture():
        need((unit or {}).get("staffing_posture") != "DIVERT",
             "ERR_UNIT_POSTURE_BLOCKS_OPERATION")

    def due():
        need(clock.now() >= drill["scheduled_for_utc"], "ERR_DRILL_NOT_DUE")

    run_checks([(8, declared), (8.02, posture), (14.2, due)])

    drill["status"] = "IN_PROGRESS"
    rev.touch(drill)
    return common.single("drills", drill)


@bp.post("/cesarean-readiness-drills/<drill_id>/document")
def document_drill(drill_id):
    ctx = begin(
        roles=["ChargeNurse", "AnesthesiaLead"],
        path=[("drill", drill_id)],
        body_refs=[("documented_by_staff_id", "staff")],
        specs=[s_dt("decision_at", required=True),
               s_dt("incision_at", required=True),
               s_str("documented_by_staff_id", required=True)],
        scope=lambda c: same_unit(c, c.p["drill"]["unit_id"], [c.r["staff"]]),
    )
    drill = ctx.p["drill"]
    documenter = ctx.r["staff"]
    decision_at = ctx.v["decision_at"]
    incision_at = ctx.v["incision_at"]
    participants = [S.staff.get(i) for i in (drill.get("participant_staff_ids") or [])]

    def declared():
        need(drill["status"] in ("IN_PROGRESS", "INVALIDATED"),
             "ERR_INVALID_STATE_TRANSITION")

    def revisions():
        if drill["status"] != "INVALIDATED":
            return
        need((drill.get("revision_count") or 0) < const.DRILL_REVISION_LIMIT,
             "ERR_DRILL_REVISION_LIMIT_REACHED")

    def credential():
        need(documenter["employment_status"] == "ACTIVE"
             and documenter["credential_expires_at"] > clock.now(),
             "ERR_STAFF_CREDENTIAL_EXPIRED")

    def roster():
        have_ob = any(m is not None and m["staff_role"] == "OB_ATTENDING"
                      for m in participants)
        have_anesthesia = any(m is not None and m["staff_role"] == "ANESTHESIOLOGIST"
                              for m in participants)
        need(have_ob and have_anesthesia, "ERR_DRILL_PARTICIPANTS_INSUFFICIENT")

    def performer():
        need(documenter["id"] in (drill.get("participant_staff_ids") or []),
             "ERR_PERFORMER_NOT_ON_CASE")

    def stamp():
        need(decision_at < incision_at <= clock.now(),
             "ERR_DRILL_TIMESTAMP_OUT_OF_RANGE")

    run_checks([(8, declared), (8.10, revisions), (11.1, credential),
                (11.4, roster), (12, performer), (14.1, stamp)])

    if drill["status"] == "INVALIDATED":
        drill["revision_count"] = (drill.get("revision_count") or 0) + 1
    drill["status"] = "DOCUMENTED"
    drill["decision_at"] = decision_at
    drill["incision_at"] = incision_at
    drill["measured_d2i_minutes"] = clock.whole_minutes_between(decision_at,
                                                               incision_at)
    drill["documented_by_staff_id"] = documenter["id"]
    rev.touch(drill)
    # Documentation alone grants no currency, so readiness is untouched.
    return common.single("drills", drill)


@bp.post("/cesarean-readiness-drills/<drill_id>/validate")
def validate_drill(drill_id):
    ctx = begin(roles=["PerinatalSafetyOfficer"], path=[("drill", drill_id)])
    drill = ctx.p["drill"]
    unit = S.units.get(drill["unit_id"])

    def declared():
        need(drill["status"] == "DOCUMENTED", "ERR_INVALID_STATE_TRANSITION")

    def duties():
        need(ctx.user_id != drill.get("documented_by_staff_id"),
             "ERR_SEGREGATION_OF_DUTIES_VIOLATION")

    def performance():
        need((drill.get("measured_d2i_minutes") or 0) <= const.DRILL_PASS_MINUTES,
             "ERR_DRILL_PERFORMANCE_FAILED")

    run_checks([(8, declared), (10, duties), (11.4, performance)])

    instant = clock.now()
    drill["status"] = "VALIDATED"
    drill["validated_at"] = instant
    drill["expires_at"] = clock.plus_days(instant, const.DRILL_CURRENCY_DAYS)
    drill["validated_by_user_id"] = ctx.user_id
    rev.touch(drill)
    for staff_id in (drill.get("participant_staff_ids") or []):
        member = S.staff.get(staff_id)
        if member is None:
            continue
        member["last_validated_drill_at"] = drill["decision_at"]
        member["drill_currency_state"] = "CURRENT"
        rev.touch(member)
        calc.recompute_staff_capacity(member)
    calc.rederive_unit(unit)
    return common.single("drills", drill)


@bp.post("/cesarean-readiness-drills/<drill_id>/invalidate")
def invalidate_drill(drill_id):
    ctx = begin(roles=["PerinatalSafetyOfficer"], path=[("drill", drill_id)],
                specs=[s_str("invalidation_reason")])
    drill = ctx.p["drill"]
    unit = S.units.get(drill["unit_id"])
    reason = ctx.v["invalidation_reason"]

    def declared():
        need(drill["status"] == "VALIDATED", "ERR_INVALID_STATE_TRANSITION")

    def context_fields():
        need(reason is not None and 10 <= len(reason) <= 500,
             "ERR_INVALIDATION_REASON_REQUIRED")

    run_checks([(8, declared), (9, context_fields)])

    drill["status"] = "INVALIDATED"
    drill["invalidation_reason"] = reason
    drill["expires_at"] = None
    rev.touch(drill)

    # hop 1: every participant re-derives its currency from the drills that remain
    for staff_id in (drill.get("participant_staff_ids") or []):
        member = S.staff.get(staff_id)
        if member is None:
            continue
        remaining = [d for d in S.drills.values()
                     if d["status"] == "VALIDATED"
                     and staff_id in (d.get("participant_staff_ids") or [])]
        if remaining:
            latest = store.sort_rows(remaining, [("decision_at", "desc"),
                                                 ("created_at", "desc")])[0]
            member["last_validated_drill_at"] = latest["decision_at"]
            member["drill_currency_state"] = "CURRENT"
        else:
            member["last_validated_drill_at"] = None
            member["drill_currency_state"] = "LAPSED"
        rev.touch(member)
        calc.recompute_staff_capacity(member)

    # hop 2: readiness re-derives, and a lost last drill lands on NOT_READY
    calc.rederive_unit(unit)
    if unit is not None and unit.get("cesarean_readiness_state") == "NOT_READY":
        # hops 3 and 4: the elective and patient-request queue is bumped and every
        # bed and frozen bed-minute reservation goes back exactly as reserved.
        calc.cascade_bump(unit, ("CAPACITY_HELD", "CONFIRMED"))
        calc.rederive_unit(unit)
    return common.single("drills", drill)


@bp.post("/cesarean-readiness-drills/<drill_id>/abandon")
def abandon_drill(drill_id):
    ctx = begin(roles=["ChargeNurse"], path=[("drill", drill_id)])
    drill = ctx.p["drill"]

    def declared():
        need(drill["status"] in ("SCHEDULED", "IN_PROGRESS", "DOCUMENTED",
                                "VALIDATED", "INVALIDATED", "ABANDONED"),
             "ERR_INVALID_STATE_TRANSITION")

    def abandonable():
        need(drill["status"] in ("SCHEDULED", "IN_PROGRESS"),
             "ERR_DRILL_NOT_ABANDONABLE")

    run_checks([(8, declared), (8.10, abandonable)])

    drill["status"] = "ABANDONED"
    rev.touch(drill)
    # An abandoned drill never granted currency, so no readiness recomputation.
    return common.single("drills", drill)
