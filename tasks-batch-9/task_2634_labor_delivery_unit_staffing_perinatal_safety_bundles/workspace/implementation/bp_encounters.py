"""Labor encounters (PRD 3.4): 8 endpoints."""

from flask import Blueprint

import calc
import clock
import common
import const
import envelope
import rev
import store
import views
from fields import (q_bool, q_enum, q_int, q_str, s_bool, s_enum, s_int, s_str)
from pipeline import begin, need, run_checks, same_unit
from store import S

bp = Blueprint("encounters", __name__)

ALL = const.ALL_ROLES
FLOOR_STATES = ("RATIO_COVERED", "ONE_TO_ONE_COVERED")


@bp.post("/labor-encounters")
def create_encounter():
    ctx = begin(
        roles=["ChargeNurse", "PatientAccessCoordinator"],
        body_refs=[("unit_id", "unit")],
        specs=[s_str("unit_id", required=True),
               s_str("patient_record_code", required=True, min_len=1, max_len=60),
               s_int("parity", required=True, min=0),
               s_int("gestational_age_weeks", required=True, min=20, max=44),
               s_bool("prior_cesarean", default=False),
               s_int("fetus_count", min=1, default=1),
               s_enum("presentation", const.PRESENTATIONS, default="VERTEX")],
    )
    unit = ctx.r["unit"]

    def posture():
        need(unit["staffing_posture"] != "DIVERT", "ERR_UNIT_POSTURE_BLOCKS_OPERATION")

    def unique_code():
        for other in calc.encounters_of_unit(unit["id"]):
            if (other["labor_phase"] not in const.TERMINAL_PHASES
                    and other["patient_record_code"] == ctx.v["patient_record_code"]):
                need(False, "ERR_DUPLICATE_PATIENT_RECORD_CODE")

    run_checks([(8.02, posture), (13.1, unique_code)])
    enc = store.new_record({
        "unit_id": unit["id"],
        "patient_record_code": ctx.v["patient_record_code"],
        "source_booking_id": None,
        "bed_id": None,
        "admitted_at": clock.now(),
        "parity": ctx.v["parity"],
        "gestational_age_weeks": ctx.v["gestational_age_weeks"],
        "prior_cesarean": ctx.v["prior_cesarean"],
        "fetus_count": ctx.v["fetus_count"],
        "presentation": ctx.v["presentation"],
        "is_ntsv": (ctx.v["parity"] == 0 and ctx.v["prior_cesarean"] is False
                    and ctx.v["gestational_age_weeks"] >= 37
                    and ctx.v["fetus_count"] == 1
                    and ctx.v["presentation"] == "VERTEX"),
        "labor_phase": "ANTEPARTUM",
        "staffing_state": "UNASSIGNED",
        "acuity_tier": "TIER_I",
        "one_to_one_required": False,
        "required_coverage_units": 0.0,
        "assigned_coverage_units": 0.0,
        "magnesium_infusion_active": False,
        "delivery_mode": None,
        "episiotomy_performed": False,
        "delivery_recorded_at": None,
        "review_required": False,
    })
    S.encounters[enc["id"]] = enc
    calc.rederive_encounter(enc, bump_self=False)
    return common.created("encounters", enc)


@bp.get("/labor-encounters")
def list_encounters():
    begin(roles=ALL)
    unit_id = q_str("unit_id")
    bed_id = q_str("bed_id")
    booking_id = q_str("source_booking_id")
    code = q_str("patient_record_code")
    phase = q_enum("labor_phase", const.PHASES)
    state = q_enum("staffing_state", const.STAFFING_STATES)
    tier = q_enum("acuity_tier", const.TIERS)
    ntsv = q_bool("is_ntsv")
    found = [e for e in S.encounters.values()
             if common.match(e, "unit_id", unit_id)
             and common.match(e, "bed_id", bed_id)
             and common.match(e, "source_booking_id", booking_id)
             and common.match(e, "patient_record_code", code)
             and common.match(e, "labor_phase", phase)
             and common.match(e, "staffing_state", state)
             and common.match(e, "acuity_tier", tier)
             and common.match(e, "is_ntsv", ntsv)]
    return common.listing("encounters", found,
                          [("admitted_at", "asc"), ("created_at", "asc")])


@bp.get("/labor-encounters/<encounter_id>")
def read_encounter(encounter_id):
    ctx = begin(roles=ALL, path=[("encounter", encounter_id)])
    return common.single("encounters", ctx.p["encounter"])


@bp.get("/labor-encounters/<encounter_id>/coverage-summary")
def coverage_summary(encounter_id):
    ctx = begin(roles=["ChargeNurse", "BedsideNurse", "ObstetricianAttending",
                       "PerinatalSafetyOfficer", "PatientAccessCoordinator"],
                path=[("encounter", encounter_id)])
    enc = ctx.p["encounter"]
    tier, reason, one_to_one, required = calc.derive_requirements(enc)
    active = calc.sort_rows(calc.active_care_on_encounter(enc["id"]),
                            [("created_at", "asc")])
    latest = calc.latest_assessment(enc["id"])
    data = {
        "encounter_id": enc["id"],
        "labor_phase": enc["labor_phase"],
        "staffing_state": enc["staffing_state"],
        "acuity_tier": tier,
        "acuity_tier_reason": reason,
        "one_to_one_required": one_to_one,
        "required_coverage_units": required,
        "assigned_coverage_units": enc["assigned_coverage_units"],
        "deficit_units": clock.one_dp(max(0.0, required
                                          - (enc["assigned_coverage_units"] or 0.0))),
        "magnesium_infusion_active": enc["magnesium_infusion_active"],
        "review_required": enc["review_required"],
        "active_assignments": [
            {"care_assignment_id": row["id"],
             "shift_assignment_id": row["shift_assignment_id"],
             "staff_id": row["staff_id"],
             "coverage_mode": row["coverage_mode"],
             "acuity_units_consumed": row["acuity_units_consumed"]}
            for row in active],
        "latest_assessment_id": latest["id"] if latest else None,
        "latest_assessment_category": latest["category"] if latest else None,
        "latest_assessment_escalation_status": (latest["escalation_status"]
                                                if latest else None),
        "support_person_allowance": calc.support_allowance(enc),
        "support_persons_checked_in": calc.checked_in_count(enc["id"]),
    }
    return envelope.obj(data)


@bp.post("/labor-encounters/<encounter_id>/assign-bed")
def assign_bed(encounter_id):
    ctx = begin(roles=["ChargeNurse"], path=[("encounter", encounter_id)],
                body_refs=[("bed_id", "bed")],
                specs=[s_str("bed_id", required=True)],
                scope=lambda c: same_unit(c, c.p["encounter"]["unit_id"], [c.r["bed"]]))
    enc = ctx.p["encounter"]
    bed = ctx.r["bed"]

    def already():
        need(enc.get("bed_id") is None, "ERR_ENCOUNTER_ALREADY_IN_BED")

    def eligible():
        need(bed["bed_type"] == "LDR" and bed["status"] == "AVAILABLE",
             "ERR_BED_TYPE_NOT_ELIGIBLE")

    run_checks([(8.07, already), (13.3, eligible)])
    bed["status"] = "OCCUPIED"
    bed["current_encounter_id"] = enc["id"]
    rev.touch(bed)
    enc["bed_id"] = bed["id"]
    rev.touch(enc)
    calc.rederive_encounter(enc)
    return common.single("encounters", enc)


LADDER = {"ANTEPARTUM": "LATENT", "LATENT": "ACTIVE_FIRST_STAGE",
          "ACTIVE_FIRST_STAGE": "SECOND_STAGE", "SECOND_STAGE": "THIRD_STAGE_DELIVERED",
          "THIRD_STAGE_DELIVERED": "POSTPARTUM_RECOVERY"}
ADVANCE_TARGETS = ("LATENT", "ACTIVE_FIRST_STAGE", "SECOND_STAGE",
                   "THIRD_STAGE_DELIVERED", "POSTPARTUM_RECOVERY")


def _release_bed_to_turnover(enc, unit):
    bed = S.beds.get(enc.get("bed_id") or "")
    if bed is None:
        enc["bed_id"] = None
        return
    if bed["status"] == "OCCUPIED":
        bed["status"] = "TURNOVER"
        bed["turnover_clear_at"] = clock.plus_minutes(
            clock.now(), unit.get("turnover_buffer_minutes") or 0)
    bed["current_encounter_id"] = None
    rev.touch(bed)
    enc["bed_id"] = None
    rev.touch(enc)


def _fresh_within(enc, minutes):
    latest = calc.latest_assessment(enc["id"])
    if latest is None:
        return False, None
    elapsed = clock.whole_minutes_between(latest["assessed_at"], clock.now())
    return (0 <= elapsed <= minutes), latest


@bp.post("/labor-encounters/<encounter_id>/advance-phase")
def advance_phase(encounter_id):
    ctx = begin(roles=["ChargeNurse", "ObstetricianAttending"],
                path=[("encounter", encounter_id)],
                specs=[s_enum("target_phase", ADVANCE_TARGETS, required=True),
                       s_enum("delivery_mode", const.DELIVERY_MODES),
                       s_bool("episiotomy_performed", default=False)])
    enc = ctx.p["encounter"]
    unit = S.units.get(enc["unit_id"])
    target = ctx.v["target_phase"]
    mode = ctx.v["delivery_mode"]
    episiotomy = ctx.v["episiotomy_performed"]
    checks = []

    def declared():
        need(LADDER.get(enc["labor_phase"]) == target, "ERR_INVALID_STATE_TRANSITION")

    checks.append((8, declared))

    if target == "LATENT":
        def posture():
            need(unit["staffing_posture"] != "DIVERT",
                 "ERR_UNIT_POSTURE_BLOCKS_OPERATION")

        def coverage():
            need(enc["staffing_state"] in FLOOR_STATES,
                 "ERR_ENCOUNTER_COVERAGE_INSUFFICIENT")

        def in_bed():
            bed = S.beds.get(enc.get("bed_id") or "")
            need(bed is not None and bed["status"] == "OCCUPIED"
                 and bed["bed_type"] == "LDR", "ERR_ENCOUNTER_BED_NOT_ASSIGNED")

        checks += [(8.02, posture), (8.03, coverage), (13.3, in_bed)]

    if target == "ACTIVE_FIRST_STAGE":
        def coverage():
            need(enc["staffing_state"] in FLOOR_STATES,
                 "ERR_ENCOUNTER_COVERAGE_INSUFFICIENT")

        def fresh():
            ok, latest = _fresh_within(enc, 30)
            need(ok, "ERR_FETAL_ASSESSMENT_STALE")
            need(latest["escalation_status"] not in const.ESCALATION_UNRESOLVED,
                 "ERR_FETAL_ESCALATION_UNRESOLVED")

        checks += [(8.03, coverage), (11.3, fresh)]

    if target == "SECOND_STAGE":
        def coverage():
            need(enc["staffing_state"] == "ONE_TO_ONE_COVERED",
                 "ERR_ONE_TO_ONE_COVERAGE_REQUIRED")

        def fetal():
            ok, latest = _fresh_within(enc, 15)
            need(ok, "ERR_FETAL_ASSESSMENT_STALE")
            if latest["category"] == "CATEGORY_III":
                covered = any(c["status"] in ("DECISION_DECLARED", "TEAM_MOBILIZED")
                              for c in calc.rows("cesareans", encounter_id=enc["id"]))
                need(covered, "ERR_FETAL_CATEGORY_BLOCKS_PHASE")

        def readiness():
            need(unit["cesarean_readiness_state"] != "NOT_READY",
                 "ERR_CESAREAN_READINESS_NOT_MET")

        checks += [(8.03, coverage), (11.3, fetal), (11.4, readiness)]

    if target == "THIRD_STAGE_DELIVERED":
        def mode_required():
            need(mode is not None, "ERR_DELIVERY_MODE_REQUIRED")

        def coherent():
            if mode in const.CESAREAN_MODES:
                done = any(c["status"] in ("DELIVERED", "REVIEW_PENDING", "CLOSED")
                           for c in calc.rows("cesareans", encounter_id=enc["id"]))
                need(done, "ERR_CESAREAN_EVENT_NOT_DELIVERED")
            need(not (enc["prior_cesarean"] is True and mode == "CESAREAN_PRIMARY"),
                 "ERR_DELIVERY_MODE_CONFLICTS_HISTORY")
            need(not (episiotomy is True and mode not in const.VAGINAL_MODES),
                 "ERR_EPISIOTOMY_MODE_CONFLICT")

        checks += [(9, mode_required), (11.7, coherent)]

    if target == "POSTPARTUM_RECOVERY":
        def escalations():
            for row in calc.rows("assessments", encounter_id=enc["id"]):
                need(row["escalation_status"] in ("NOT_REQUIRED", "RESOLVED",
                                                  "TIMED_OUT_BREACH"),
                     "ERR_FETAL_ESCALATION_UNRESOLVED")

        def cesarean():
            for row in calc.rows("cesareans", encounter_id=enc["id"]):
                need(row["status"] not in const.CESAREAN_IN_THEATRE,
                     "ERR_CESAREAN_EVENT_IN_PROGRESS")

        checks += [(11.3, escalations), (11.35, cesarean)]

    run_checks(checks)

    enc["labor_phase"] = target
    rev.touch(enc)
    if target == "THIRD_STAGE_DELIVERED":
        enc["delivery_mode"] = mode
        enc["episiotomy_performed"] = episiotomy
        enc["delivery_recorded_at"] = clock.now()
    if target == "POSTPARTUM_RECOVERY":
        _release_bed_to_turnover(enc, unit)
    calc.rederive_encounter(enc)
    if target == "SECOND_STAGE" and unit["staffing_posture"] in ("INDUCTION_FROZEN",
                                                                "DIVERT"):
        calc.cascade_bump(unit, ("CAPACITY_HELD",), const.PRIORITY_CLASSES)
        calc.rederive_unit(unit)
    if target == "THIRD_STAGE_DELIVERED":
        calc.recompute_draft_snapshots(unit["id"], enc["delivery_recorded_at"])
    return common.single("encounters", enc)


@bp.post("/labor-encounters/<encounter_id>/discharge")
def discharge(encounter_id):
    ctx = begin(roles=["ChargeNurse"], path=[("encounter", encounter_id)])
    enc = ctx.p["encounter"]
    unit = S.units.get(enc["unit_id"])

    def declared():
        need(enc["labor_phase"] == "POSTPARTUM_RECOVERY", "ERR_INVALID_STATE_TRANSITION")

    def blockers():
        for review in calc.rows("reviews", encounter_id=enc["id"]):
            need(review["status"] == "CLOSED", "ERR_NEWBORN_REVIEW_OPEN")
        for activation in calc.rows("activations", encounter_id=enc["id"]):
            need(activation["status"] in ("CLOSED", "RESCINDED"), "ERR_BUNDLE_NOT_CLOSED")
        for row in calc.rows("passes", encounter_id=enc["id"]):
            need(row["status"] not in const.PASS_PRESENT, "ERR_SUPPORT_PASS_STILL_PRESENT")
        need(enc["staffing_state"] == "RELEASED", "ERR_CARE_ASSIGNMENT_STILL_ACTIVE")

    run_checks([(8, declared), (8.04, blockers)])
    enc["labor_phase"] = "DISCHARGED"
    enc["staffing_state"] = "RELEASED"
    enc["required_coverage_units"] = 0.0
    rev.touch(enc)
    if enc.get("bed_id"):
        _release_bed_to_turnover(enc, unit)
    calc.rederive_encounter(enc, forced_state="RELEASED")
    return common.single("encounters", enc)


@bp.post("/labor-encounters/<encounter_id>/transfer-out")
def transfer_out(encounter_id):
    ctx = begin(roles=["ObstetricianAttending"], path=[("encounter", encounter_id)])
    enc = ctx.p["encounter"]
    unit = S.units.get(enc["unit_id"])

    def declared():
        need(enc["labor_phase"] in ("ANTEPARTUM", "LATENT", "ACTIVE_FIRST_STAGE"),
             "ERR_INVALID_STATE_TRANSITION")

    def blockers():
        for row in calc.rows("cesareans", encounter_id=enc["id"]):
            need(row["status"] not in const.CESAREAN_OR_ACTIVE,
                 "ERR_CESAREAN_EVENT_IN_PROGRESS")
        for row in calc.rows("activations", encounter_id=enc["id"]):
            need(row["status"] not in ("STAGE_2_ESCALATED", "STAGE_3_MASSIVE_TRANSFUSION"),
                 "ERR_BUNDLE_STAGE_BLOCKS_TRANSFER")

    run_checks([(8, declared), (8.04, blockers)])
    instant = clock.now()

    for row in calc.sort_rows(calc.active_care_on_encounter(enc["id"]),
                              [("created_at", "asc")]):
        shift = S.shifts.get(row["shift_assignment_id"])
        calc.move_load(shift, credit=row["acuity_units_consumed"] or 0.0)
        row["status"] = "RELEASED"
        row["released_at"] = instant
        rev.touch(row)
        calc.recompute_staff_capacity(S.staff.get(row["staff_id"]))

    for activation in calc.sort_rows(calc.rows("activations", encounter_id=enc["id"]),
                                     [("created_at", "asc")]):
        if activation["status"] in ("ACTIVATED", "STAGE_1_IN_PROGRESS"):
            activation["status"] = "RESCINDED"
            activation["rescind_reason"] = "TRANSFER_OUT"
            rev.touch(activation)
            for item in calc.items_of(activation["id"]):
                if item["status"] == "PENDING":
                    item["status"] = "NOT_APPLICABLE"
                    rev.touch(item)

    breaches = 0
    for row in calc.sort_rows(calc.rows("assessments", encounter_id=enc["id"]),
                              [("created_at", "asc")]):
        if row["escalation_status"] == "TIMED_OUT_BREACH":
            breaches += 1
        if row["escalation_status"] not in ("NOT_REQUIRED", "RESOLVED", "TIMED_OUT_BREACH"):
            row["escalation_status"] = "RESOLVED"
            row["resolved_at"] = instant
            rev.touch(row)

    for row in calc.sort_rows(calc.rows("passes", encounter_id=enc["id"]),
                              [("created_at", "asc")]):
        if row["status"] in const.PASS_PRESENT:
            row["status"] = "REVOKED"
            row["revoked_at"] = instant
            rev.touch(row)

    if breaches:
        unit["escalation_breach_count"] = max(
            0, (unit.get("escalation_breach_count") or 0) - breaches)

    enc["labor_phase"] = "TRANSFERRED_OUT"
    enc["staffing_state"] = "RELEASED"
    enc["required_coverage_units"] = 0.0
    enc["assigned_coverage_units"] = 0.0
    rev.touch(enc)
    if enc.get("bed_id"):
        _release_bed_to_turnover(enc, unit)
    calc.rederive_encounter(enc, forced_state="RELEASED")
    return common.single("encounters", enc)
