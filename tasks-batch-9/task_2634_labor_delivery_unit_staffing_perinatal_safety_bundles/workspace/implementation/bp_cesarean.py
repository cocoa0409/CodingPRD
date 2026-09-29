"""Emergency cesarean events (PRD 3.8): 8 endpoints."""

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

bp = Blueprint("cesarean", __name__)

READ_ROLES = ["ChargeNurse", "ObstetricianAttending", "AnesthesiaLead",
              "PerinatalSafetyOfficer"]


@bp.post("/emergency-cesareans")
def declare_event():
    ctx = begin(
        roles=["ObstetricianAttending"],
        body_refs=[("encounter_id", "encounter"),
                   ("triggering_assessment_id", "assessment"),
                   ("triggering_activation_id", "activation")],
        specs=[s_str("encounter_id", required=True),
               s_enum("urgency_class", const.URGENCY_CLASSES, required=True),
               s_str("triggering_assessment_id"),
               s_str("triggering_activation_id")],
    )
    enc = ctx.r["encounter"]
    assessment = ctx.r.get("assessment")
    activation = ctx.r.get("activation")
    # Priority 7: both triggering references must belong to this very encounter.
    for ref in (assessment, activation):
        if ref is not None and ref["encounter_id"] != enc["id"]:
            fail("ERR_CROSS_UNIT_REFERENCE")

    def phase():
        need(enc["labor_phase"] not in const.TERMINAL_PHASES,
             "ERR_ENCOUNTER_PHASE_TERMINAL")

    def single():
        need(not calc.live_cesareans(enc["id"]), "ERR_CESAREAN_EVENT_IN_PROGRESS")

    run_checks([(8.01, phase), (8.011, single)])

    event = store.new_record({
        "encounter_id": enc["id"],
        "or_bed_id": None,
        "triggering_assessment_id": assessment["id"] if assessment else None,
        "triggering_activation_id": activation["id"] if activation else None,
        "urgency_class": ctx.v["urgency_class"],
        "decision_at": clock.now(),
        "incision_at": None,
        "delivery_at": None,
        "decision_to_incision_minutes": None,
        "met_target": None,
        "mobilized_staff_ids": [],
        "status": "DECISION_DECLARED",
    })
    S.cesareans[event["id"]] = event
    calc.rederive_encounter(enc)
    return common.created("cesareans", event)


@bp.get("/emergency-cesareans")
def list_events():
    begin(roles=READ_ROLES)
    encounter_id = q_str("encounter_id")
    unit_id = q_str("unit_id")
    or_bed_id = q_str("or_bed_id")
    assessment_id = q_str("triggering_assessment_id")
    activation_id = q_str("triggering_activation_id")
    status = q_enum("status", const.CESAREAN_STATUSES)
    urgency = q_enum("urgency_class", const.URGENCY_CLASSES)

    def unit_ok(event):
        if unit_id is None:
            return True
        enc = S.encounters.get(event["encounter_id"])
        return enc is not None and enc["unit_id"] == unit_id

    found = [e for e in S.cesareans.values()
             if common.match(e, "encounter_id", encounter_id)
             and common.match(e, "or_bed_id", or_bed_id)
             and common.match(e, "triggering_assessment_id", assessment_id)
             and common.match(e, "triggering_activation_id", activation_id)
             and common.match(e, "status", status)
             and common.match(e, "urgency_class", urgency)
             and unit_ok(e)]
    return common.listing("cesareans", found,
                          [("decision_at", "desc"), ("created_at", "desc")])


@bp.get("/emergency-cesareans/<event_id>")
def read_event(event_id):
    ctx = begin(roles=READ_ROLES, path=[("cesarean", event_id)])
    return common.single("cesareans", ctx.p["cesarean"])


@bp.post("/emergency-cesareans/<event_id>/mobilize-team")
def mobilize_team(event_id):
    ctx = begin(
        roles=["ObstetricianAttending"],
        path=[("cesarean", event_id)],
        body_refs=[("or_bed_id", "bed")],
        specs=[s_str("or_bed_id", required=True),
               s_array("staff_ids", required=True, min_len=3, max_len=12)],
    )
    event = ctx.p["cesarean"]
    enc = S.encounters.get(event["encounter_id"])
    unit = S.units.get(enc["unit_id"]) if enc is not None else None
    bed = ctx.r["bed"]
    staff_ids = ctx.v["staff_ids"]
    team = []
    for staff_id in staff_ids:                       # priority 4, payload order
        member = S.staff.get(staff_id)
        if member is None:
            fail("ERR_STAFF_NOT_FOUND")
        team.append(member)
    same_unit(ctx, enc["unit_id"], [bed] + team)     # priority 7

    def declared():
        need(event["status"] == "DECISION_DECLARED", "ERR_INVALID_STATE_TRANSITION")

    def phase():
        need(enc["labor_phase"] not in const.TERMINAL_PHASES,
             "ERR_ENCOUNTER_PHASE_TERMINAL")

    def bed_type():
        need(bed["bed_type"] == "OR", "ERR_BED_TYPE_NOT_ELIGIBLE")

    def bed_free():
        need(bed["status"] == "AVAILABLE", "ERR_OR_BED_UNAVAILABLE")

    def credential():
        for member in team:
            need(member["employment_status"] == "ACTIVE"
                 and member["credential_expires_at"] > clock.now(),
                 "ERR_STAFF_CREDENTIAL_EXPIRED")

    def complete():
        # The three required roles must each hold an ACTIVE roster entry on the
        # unit; a member off the roster simply does not satisfy its role.
        def rostered(member):
            return any(s["staff_id"] == member["id"]
                       for s in calc.active_shifts_of_unit(enc["unit_id"]))

        have_anesthesia = any(m["staff_role"] == "ANESTHESIOLOGIST" and rostered(m)
                              for m in team)
        have_tech = any(m["staff_role"] == "SURGICAL_TECH"
                        and m["or_circulating_qualified"] is True and rostered(m)
                        for m in team)
        have_neonatal = any(m["staff_role"] == "NEONATAL_RESUSCITATOR" and rostered(m)
                            for m in team)
        need(have_anesthesia and have_tech and have_neonatal,
             "ERR_CESAREAN_TEAM_INCOMPLETE")

    def readiness():
        if event["urgency_class"] == "CATEGORY_1_CRASH":
            return                                   # a crash section is never refused
        need(unit.get("cesarean_readiness_state") != "NOT_READY",
             "ERR_CESAREAN_READINESS_NOT_MET")

    run_checks([(8, declared), (8.01, phase), (8.07, bed_type), (8.071, bed_free),
                (11.1, credential), (11.4, complete),
                (11.41, readiness)])

    event["status"] = "TEAM_MOBILIZED"
    event["or_bed_id"] = bed["id"]
    event["mobilized_staff_ids"] = list(staff_ids)
    rev.touch(event)
    bed["status"] = "OCCUPIED"
    rev.touch(bed)
    for row in calc.rows("passes", encounter_id=enc["id"], status="CHECKED_IN"):
        if (row["credential_type"] == "DOULA_CERTIFIED"
                and row.get("or_credentialed") is True):
            continue                                 # the one pass allowed in theatre
        row["status"] = "CHECKED_OUT"
        row["checked_out_at"] = clock.now()
        rev.touch(row)
    calc.rederive_encounter(enc)
    return common.single("cesareans", event)


@bp.post("/emergency-cesareans/<event_id>/record-incision")
def record_incision(event_id):
    ctx = begin(roles=["ObstetricianAttending"], path=[("cesarean", event_id)],
                specs=[s_dt("incision_at", required=True)])
    event = ctx.p["cesarean"]
    enc = S.encounters.get(event["encounter_id"])
    unit = S.units.get(enc["unit_id"]) if enc is not None else None
    incision_at = ctx.v["incision_at"]

    def declared():
        need(event["status"] == "TEAM_MOBILIZED", "ERR_INVALID_STATE_TRANSITION")

    def stamp():
        need(event["decision_at"] < incision_at <= clock.now(),
             "ERR_CESAREAN_TIMESTAMP_OUT_OF_RANGE")

    run_checks([(8, declared), (14.1, stamp)])

    minutes = clock.whole_minutes_between(event["decision_at"], incision_at)
    event["status"] = "INCISION_RECORDED"
    event["incision_at"] = incision_at
    event["decision_to_incision_minutes"] = minutes
    event["met_target"] = minutes <= const.D2I_TARGET_MINUTES[event["urgency_class"]]
    rev.touch(event)
    before = unit.get("cesarean_readiness_state") if unit is not None else None
    calc.rederive_unit(unit)
    if (unit is not None and before != "NOT_READY"
            and unit.get("cesarean_readiness_state") == "NOT_READY"):
        calc.cascade_bump(unit, ("CONFIRMED",), ("ELECTIVE_39_WEEK",))
        calc.rederive_unit(unit)
    return common.single("cesareans", event)


def _bed_to_turnover(bed, unit):
    if bed is None:
        return
    bed["status"] = "TURNOVER"
    bed["current_encounter_id"] = None
    bed["turnover_clear_at"] = clock.plus_minutes(
        clock.now(), (unit or {}).get("turnover_buffer_minutes") or 0)
    rev.touch(bed)


@bp.post("/emergency-cesareans/<event_id>/record-delivery")
def record_delivery(event_id):
    ctx = begin(roles=["ObstetricianAttending"], path=[("cesarean", event_id)],
                specs=[s_dt("delivery_at", required=True)])
    event = ctx.p["cesarean"]
    enc = S.encounters.get(event["encounter_id"])
    unit = S.units.get(enc["unit_id"]) if enc is not None else None
    delivery_at = ctx.v["delivery_at"]

    def declared():
        need(event["status"] == "INCISION_RECORDED", "ERR_INVALID_STATE_TRANSITION")

    def stamp():
        need(event["incision_at"] <= delivery_at <= clock.now(),
             "ERR_CESAREAN_TIMESTAMP_OUT_OF_RANGE")

    run_checks([(8, declared), (14.1, stamp)])

    event["status"] = "DELIVERED"
    event["delivery_at"] = delivery_at
    enc["delivery_mode"] = ("CESAREAN_REPEAT" if enc.get("prior_cesarean") is True
                            else "CESAREAN_PRIMARY")
    enc["delivery_recorded_at"] = delivery_at
    rev.touch(enc)
    _bed_to_turnover(S.beds.get(event.get("or_bed_id") or ""), unit)
    calc.recompute_draft_snapshots(enc["unit_id"], delivery_at)
    # The system edge out of DELIVERED runs at the end of this very request.
    if event["met_target"] is False or event["urgency_class"] == "CATEGORY_1_CRASH":
        event["status"] = "REVIEW_PENDING"
    else:
        event["status"] = "CLOSED"
    rev.touch(event)
    calc.rederive_encounter(enc)
    return common.single("cesareans", event)


@bp.post("/emergency-cesareans/<event_id>/close")
def close_event(event_id):
    ctx = begin(roles=["PerinatalSafetyOfficer"], path=[("cesarean", event_id)])
    event = ctx.p["cesarean"]
    enc = S.encounters.get(event["encounter_id"])

    def declared():
        need(event["status"] in ("DELIVERED", "REVIEW_PENDING"),
             "ERR_INVALID_STATE_TRANSITION")

    def review_closed():
        if event["status"] != "REVIEW_PENDING":
            return
        closed = [r for r in calc.rows("reviews", encounter_id=enc["id"])
                  if r["status"] == "CLOSED"]
        need(bool(closed), "ERR_NEWBORN_REVIEW_OPEN")

    def duties():
        need(ctx.user_id not in (event.get("mobilized_staff_ids") or []),
             "ERR_SEGREGATION_OF_DUTIES_VIOLATION")

    run_checks([(8, declared), (8.09, review_closed), (10, duties)])

    event["status"] = "CLOSED"
    rev.touch(event)
    calc.rederive_encounter(enc)
    return common.single("cesareans", event)


@bp.post("/emergency-cesareans/<event_id>/abort-to-vaginal")
def abort_event(event_id):
    ctx = begin(roles=["ObstetricianAttending"], path=[("cesarean", event_id)])
    event = ctx.p["cesarean"]
    enc = S.encounters.get(event["encounter_id"])
    unit = S.units.get(enc["unit_id"]) if enc is not None else None

    def declared():
        need(event["status"] in ("DECISION_DECLARED", "TEAM_MOBILIZED"),
             "ERR_INVALID_STATE_TRANSITION")

    def not_incised():
        need(event.get("incision_at") is None, "ERR_CESAREAN_ALREADY_INCISED")

    def category():
        latest = calc.latest_assessment(enc["id"])
        if latest is None:
            return
        need(latest["category"] in ("CATEGORY_I", "CATEGORY_II"),
             "ERR_FETAL_CATEGORY_BLOCKS_ABORT")

    run_checks([(8, declared), (8.10, not_incised), (11.3, category)])

    event["status"] = "ABORTED_TO_VAGINAL"
    bed = S.beds.get(event.get("or_bed_id") or "")
    if bed is not None:
        _bed_to_turnover(bed, unit)
        event["or_bed_id"] = None
    rev.touch(event)
    # delivery_mode is deliberately untouched so the later advance-phase can set it.
    calc.rederive_encounter(enc)
    return common.single("cesareans", event)
