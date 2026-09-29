"""Care assignments (PRD 3.3): 4 endpoints."""

from flask import Blueprint

import calc
import clock
import common
import const
import rev
import store
from fields import q_enum, q_str, s_enum, s_int, s_str
from pipeline import begin, need, run_checks, same_unit
from store import S

bp = Blueprint("care", __name__)

READ_ROLES = ["ChargeNurse", "BedsideNurse", "ObstetricianAttending",
              "PerinatalSafetyOfficer"]


@bp.post("/care-assignments")
def create_care():
    ctx = begin(
        roles=["ChargeNurse"],
        body_refs=[("encounter_id", "encounter"), ("shift_assignment_id", "shift")],
        specs=[s_str("encounter_id", required=True),
               s_str("shift_assignment_id", required=True),
               s_enum("coverage_mode", const.COVERAGE_MODES, required=True),
               s_int("expected_encounter_version", required=True)],
        occ=("expected_encounter_version", "ERR_STALE_ENCOUNTER_VERSION",
             lambda c: c.r.get("encounter")),
        scope=lambda c: same_unit(c, c.r["encounter"]["unit_id"], [c.r["shift"]]),
    )
    enc = ctx.r["encounter"]
    shift = ctx.r["shift"]
    staff = S.staff.get(shift["staff_id"])
    mode = ctx.v["coverage_mode"]

    def phase():
        need(enc["labor_phase"] not in const.TERMINAL_PHASES,
             "ERR_ENCOUNTER_PHASE_TERMINAL")

    def shift_active():
        instant = clock.now()
        need(shift["status"] == "ACTIVE"
             and shift["shift_start_utc"] <= instant < shift["shift_end_utc"],
             "ERR_SHIFT_NOT_ACTIVE")

    def credential():
        need(staff is not None and staff["employment_status"] == "ACTIVE"
             and staff.get("credential_expires_at") is not None
             and staff["credential_expires_at"] > clock.now(),
             "ERR_STAFF_CREDENTIAL_EXPIRED")

    def competency():
        if mode == "RATIO_SHARED":
            need(enc.get("one_to_one_required") is not True,
                 "ERR_ONE_TO_ONE_COVERAGE_REQUIRED")
            return
        need(shift["role_slot"] in ("BEDSIDE", "ONE_TO_ONE_FLOAT"),
             "ERR_ROLE_SLOT_NOT_ELIGIBLE")
        for row in calc.rows("care", staff_id=staff["id"], status="ACTIVE"):
            need(row["encounter_id"] == enc["id"], "ERR_STAFF_NOT_EXCLUSIVELY_AVAILABLE")
        cert = staff["fetal_monitoring_cert_level"]
        need(cert in ("BASIC", "ADVANCED"), "ERR_MONITORING_CERT_INSUFFICIENT")
        if enc["acuity_tier"] == "TIER_IV":
            need(cert == "ADVANCED", "ERR_MONITORING_CERT_INSUFFICIENT")

    def capacity():
        debit = calc.care_debit(mode, shift, enc)
        credit = 0.0
        if mode == "ONE_TO_ONE":
            # the rows this handoff displaces are credited back on the same ledger
            for row in calc.active_care_on_encounter(enc["id"]):
                if row["shift_assignment_id"] == shift["id"]:
                    credit += row["acuity_units_consumed"] or 0.0
        projected = clock.one_dp((shift.get("assigned_acuity_load_units") or 0.0)
                                 - credit + debit)
        need(projected <= (shift.get("capacity_units_effective") or 0.0),
             "ERR_STAFF_ACUITY_CAPACITY_EXCEEDED")

    run_checks([(8.01, phase), (8.08, shift_active), (11.1, credential),
                (11.2, competency), (15, capacity)])

    instant = clock.now()
    row = store.new_record({
        "encounter_id": enc["id"],
        "shift_assignment_id": shift["id"],
        "staff_id": shift["staff_id"],
        "coverage_mode": mode,
        "acuity_units_consumed": 0.0,
        "status": "ACTIVE",
        "released_at": None,
        "superseded_by_assignment_id": None,
    })
    if mode == "ONE_TO_ONE":
        for prior in calc.sort_rows(calc.active_care_on_encounter(enc["id"]),
                                    [("created_at", "asc")]):
            prior_shift = S.shifts.get(prior["shift_assignment_id"])
            calc.move_load(prior_shift, credit=prior["acuity_units_consumed"] or 0.0)
            if prior["coverage_mode"] == "ONE_TO_ONE":
                prior["status"] = "SUPERSEDED"
                prior["superseded_by_assignment_id"] = row["id"]
            else:
                prior["status"] = "RELEASED"
            prior["released_at"] = instant
            rev.touch(prior)
    debit = calc.care_debit(mode, shift, enc)
    row["acuity_units_consumed"] = debit
    S.care[row["id"]] = row
    calc.move_load(shift, debit=debit)
    calc.recompute_assigned(enc)
    forced = "ONE_TO_ONE_COVERED" if mode == "ONE_TO_ONE" else None
    calc.rederive_encounter(enc, forced_state=forced)
    calc.recompute_staff_capacity(staff)
    return common.created("care", row)


@bp.get("/care-assignments")
def list_care():
    begin(roles=READ_ROLES)
    encounter_id = q_str("encounter_id")
    shift_id = q_str("shift_assignment_id")
    staff_id = q_str("staff_id")
    mode = q_enum("coverage_mode", const.COVERAGE_MODES)
    status = q_enum("status", const.CARE_STATUSES)
    superseded = q_str("superseded_by_assignment_id")
    found = [r for r in S.care.values()
             if common.match(r, "encounter_id", encounter_id)
             and common.match(r, "shift_assignment_id", shift_id)
             and common.match(r, "staff_id", staff_id)
             and common.match(r, "coverage_mode", mode)
             and common.match(r, "status", status)
             and common.match(r, "superseded_by_assignment_id", superseded)]
    return common.listing("care", found, [("created_at", "asc")])


@bp.get("/care-assignments/<assignment_id>")
def read_care(assignment_id):
    ctx = begin(roles=READ_ROLES, path=[("care", assignment_id)])
    return common.single("care", ctx.p["care"])


@bp.post("/care-assignments/<assignment_id>/release")
def release_care(assignment_id):
    ctx = begin(roles=["ChargeNurse"], path=[("care", assignment_id)])
    row = ctx.p["care"]

    def declared():
        need(row["status"] == "ACTIVE", "ERR_INVALID_STATE_TRANSITION")

    run_checks([(8, declared)])
    shift = S.shifts.get(row["shift_assignment_id"])
    calc.move_load(shift, credit=row["acuity_units_consumed"] or 0.0)
    row["status"] = "RELEASED"
    row["released_at"] = clock.now()
    rev.touch(row)
    enc = S.encounters.get(row["encounter_id"])
    if enc is not None:
        calc.recompute_assigned(enc)
        forced = None
        if not calc.active_care_on_encounter(enc["id"]):
            if enc["labor_phase"] in ("POSTPARTUM_RECOVERY", "DISCHARGED",
                                      "TRANSFERRED_OUT"):
                forced = "RELEASED"
            else:
                forced = "COVERAGE_BREACH"
        calc.rederive_encounter(enc, forced_state=forced)
    calc.recompute_staff_capacity(S.staff.get(row["staff_id"]))
    return common.single("care", row)
