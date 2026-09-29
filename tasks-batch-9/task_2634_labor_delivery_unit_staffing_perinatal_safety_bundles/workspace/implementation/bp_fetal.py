"""Fetal monitoring assessments and the escalation chain (PRD 3.7): 5 endpoints."""

from flask import Blueprint

import calc
import clock
import common
import const
import rev
import store
from fields import q_enum, q_str, s_bool, s_dt, s_enum, s_int, s_str
from pipeline import begin, fail, need, run_checks, same_unit
from store import S

bp = Blueprint("fetal", __name__)

READ_ROLES = ["ChargeNurse", "BedsideNurse", "ObstetricianAttending",
              "PerinatalSafetyOfficer"]


@bp.post("/fetal-monitoring-assessments")
def create_assessment():
    ctx = begin(
        roles=["BedsideNurse", "ChargeNurse", "ObstetricianAttending"],
        body_refs=[("encounter_id", "encounter"), ("interpreted_by_staff_id", "staff")],
        specs=[s_str("encounter_id", required=True),
               s_str("interpreted_by_staff_id", required=True),
               s_enum("category", const.CATEGORIES, required=True),
               s_int("baseline_rate_bpm", required=True, min=50, max=220),
               s_enum("variability", const.VARIABILITY, required=True),
               s_bool("recurrent_decelerations", default=False),
               s_dt("assessed_at")],
        scope=lambda c: same_unit(c, c.r["encounter"]["unit_id"], [c.r["staff"]]),
    )
    enc = ctx.r["encounter"]
    staff = ctx.r["staff"]
    assessed_at = ctx.v["assessed_at"] or clock.now()

    def phase():
        need(enc["labor_phase"] not in const.TERMINAL_PHASES,
             "ERR_ENCOUNTER_PHASE_TERMINAL")

    def credential():
        need(staff["employment_status"] == "ACTIVE"
             and staff["credential_expires_at"] > clock.now(),
             "ERR_STAFF_CREDENTIAL_EXPIRED")

    def cert():
        need(staff["fetal_monitoring_cert_level"] in ("BASIC", "ADVANCED"),
             "ERR_MONITORING_CERT_INSUFFICIENT")

    def performer():
        need(calc.on_the_case(staff["id"], enc), "ERR_PERFORMER_NOT_ON_CASE")

    def stamp():
        if not ctx.v.has("assessed_at"):
            return
        need(enc["admitted_at"] <= assessed_at <= clock.now(),
             "ERR_ASSESSMENT_TIMESTAMP_OUT_OF_RANGE")

    run_checks([(8.01, phase), (11.1, credential), (11.2, cert), (12, performer),
                (14.1, stamp)])

    predecessor = calc.latest_assessment(enc["id"])
    category = ctx.v["category"]
    assessment = store.new_record({
        "encounter_id": enc["id"],
        "interpreted_by_staff_id": staff["id"],
        "supersedes_assessment_id": predecessor["id"] if predecessor else None,
        "assessed_at": assessed_at,
        "category": category,
        "baseline_rate_bpm": ctx.v["baseline_rate_bpm"],
        "variability": ctx.v["variability"],
        "recurrent_decelerations": ctx.v["recurrent_decelerations"],
        "escalation_status": ("NOT_REQUIRED" if category == "CATEGORY_I"
                             else "ESCALATION_DUE"),
        "escalation_tier_high_water": 0,
        "escalation_due_at": None,
        "next_tier_due_at": None,
        "reassessment_due_at": None,
    })
    if category != "CATEGORY_I":
        assessment["escalation_due_at"] = calc.escalation_due_from(assessment,
                                                                  assessed_at)
    S.assessments[assessment["id"]] = assessment
    calc.settle_predecessor(predecessor, assessment)
    calc.rederive_encounter(enc)
    return common.created("assessments", assessment)


@bp.get("/fetal-monitoring-assessments")
def list_assessments():
    begin(roles=READ_ROLES)
    encounter_id = q_str("encounter_id")
    interpreter = q_str("interpreted_by_staff_id")
    supersedes = q_str("supersedes_assessment_id")
    category = q_enum("category", const.CATEGORIES)
    status = q_enum("escalation_status", const.ESCALATION_STATUSES)
    found = [a for a in S.assessments.values()
             if common.match(a, "encounter_id", encounter_id)
             and common.match(a, "interpreted_by_staff_id", interpreter)
             and common.match(a, "supersedes_assessment_id", supersedes)
             and common.match(a, "category", category)
             and common.match(a, "escalation_status", status)]
    return common.listing("assessments", found,
                          [("assessed_at", "asc"), ("created_at", "asc")])


@bp.get("/fetal-monitoring-assessments/<assessment_id>")
def read_assessment(assessment_id):
    ctx = begin(roles=READ_ROLES, path=[("assessment", assessment_id)])
    return common.single("assessments", ctx.p["assessment"])


@bp.post("/fetal-monitoring-assessments/<assessment_id>/escalate")
def escalate_assessment(assessment_id):
    ctx = begin(
        roles=["BedsideNurse", "ChargeNurse", "ObstetricianAttending"],
        path=[("assessment", assessment_id)],
        body_refs=[("notified_staff_id", "staff")],
        specs=[s_int("target_tier", required=True, min=1, max=3),
               s_str("notified_staff_id")],
        scope=lambda c: same_unit(
            c, S.encounters[c.p["assessment"]["encounter_id"]]["unit_id"],
            [c.r.get("staff")]),
    )
    assessment = ctx.p["assessment"]
    enc = S.encounters.get(assessment["encounter_id"])
    unit = S.units.get(enc["unit_id"]) if enc is not None else None
    tier = ctx.v["target_tier"]
    target = ctx.r.get("staff")
    if tier in (1, 2) and target is None:
        fail("ERR_INVALID_FIELD_VALUE", "notified_staff_id is required.")
    if tier == 3 and ctx.v.has("notified_staff_id"):
        fail("ERR_INVALID_FIELD_VALUE",
             "notified_staff_id must be omitted for target_tier 3.")
    expected_from = {1: "ESCALATION_DUE", 2: "TIER_1_NOTIFIED", 3: "TIER_2_NOTIFIED"}

    def declared():
        need(assessment["escalation_status"] in expected_from.values(),
             "ERR_INVALID_STATE_TRANSITION")

    def one_tier():
        high = assessment.get("escalation_tier_high_water") or 0
        need(tier == high + 1
             and assessment["escalation_status"] == expected_from[tier],
             "ERR_ESCALATION_TIER_SKIPPED")

    def eligible():
        if tier == 3:
            return
        need(calc.escalation_target_eligible(target, tier, enc["unit_id"]),
             "ERR_ESCALATION_TARGET_INELIGIBLE")

    def category_ok():
        if tier != 3:
            return
        need(assessment["category"] == "CATEGORY_III",
             "ERR_ESCALATION_CATEGORY_INSUFFICIENT")

    def standby():
        if tier != 3:
            return
        need(calc.or_standby_staffed(enc["unit_id"]), "ERR_OR_STANDBY_NOT_STAFFED")

    def window():
        if tier != 1:
            return
        due = assessment.get("escalation_due_at")
        need(due is not None and clock.now() <= due,
             "ERR_ESCALATION_WINDOW_EXPIRED")

    run_checks([(8, declared), (8.10, one_tier), (11.2, eligible),
                (11.3, category_ok), (11.4, standby), (14.2, window)])

    instant = clock.now()
    assessment["escalation_tier_high_water"] = tier
    assessment["escalation_status"] = {1: "TIER_1_NOTIFIED", 2: "TIER_2_NOTIFIED",
                                       3: "TIER_3_ACTIVATED"}[tier]
    if tier == 3:
        assessment["next_tier_due_at"] = None
    else:
        assessment["next_tier_due_at"] = clock.plus_minutes(
            instant, const.TIER_ADVANCE_MINUTES[assessment["category"]])
    rev.touch(assessment)
    if tier == 3:
        # hop 1 of the cascade; hops 2 and 3 fall out of the re-derivation below
        calc.mint_cesarean(enc, triggering_assessment_id=assessment["id"])
    calc.rederive_encounter(enc)
    return common.single("assessments", assessment)


@bp.post("/fetal-monitoring-assessments/<assessment_id>/resolve")
def resolve_assessment(assessment_id):
    ctx = begin(roles=["ObstetricianAttending"], path=[("assessment", assessment_id)])
    assessment = ctx.p["assessment"]
    enc = S.encounters.get(assessment["encounter_id"])

    def declared():
        need(assessment["escalation_status"] in ("TIER_1_NOTIFIED", "TIER_2_NOTIFIED",
                                                "TIER_3_ACTIVATED"),
             "ERR_INVALID_STATE_TRANSITION")

    def started():
        need((assessment.get("escalation_tier_high_water") or 0) >= 1,
             "ERR_ESCALATION_NOT_STARTED")

    def theatre():
        for event in calc.rows("cesareans", triggering_assessment_id=assessment["id"]):
            need(event["status"] not in const.CESAREAN_IN_THEATRE,
                 "ERR_CESAREAN_EVENT_IN_PROGRESS")

    run_checks([(8, declared), (8.10, started), (8.102, theatre)])

    assessment["escalation_status"] = "REASSESSMENT_PENDING"
    assessment["reassessment_due_at"] = clock.plus_minutes(
        clock.now(), const.REASSESSMENT_WINDOW_MINUTES)
    assessment["next_tier_due_at"] = None
    rev.touch(assessment)
    calc.rederive_encounter(enc)
    return common.single("assessments", assessment)
