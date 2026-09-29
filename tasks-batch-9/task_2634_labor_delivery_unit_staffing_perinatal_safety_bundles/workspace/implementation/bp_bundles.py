"""Safety bundle activations and checklist items (PRD 3.6): 13 endpoints."""

from flask import Blueprint

import calc
import clock
import common
import const
import envelope
import rev
import store
import views
from fields import q_enum, q_int, q_str, s_dt, s_enum, s_int, s_str
from pipeline import begin, fail, need, run_checks, same_unit
from store import S

bp = Blueprint("bundles", __name__)

READ_ROLES = ["ChargeNurse", "BedsideNurse", "ObstetricianAttending",
              "PerinatalSafetyOfficer"]


def _mint_items(activation):
    for seq, code, gate, minutes in const.CHECKLIST_TEMPLATE[activation["bundle_type"]]:
        item = store.new_record({
            "activation_id": activation["id"],
            "step_code": code,
            "step_sequence": seq,
            "stage_gate": gate,
            "required_within_minutes": minutes,
            "due_at_activation_anchored": clock.plus_minutes(
                activation["activated_at"],
                calc.cumulative_minutes(activation["bundle_type"], seq)),
            "due_at_sequence_anchored": (clock.plus_minutes(
                activation["activated_at"], minutes) if seq == 1 else None),
            "status": "PENDING",
            "completed_at": None,
            "performed_by_staff_id": None,
            "minutes_from_activation": None,
        })
        S.items[item["id"]] = item


@bp.post("/bundle-activations")
def create_activation():
    ctx = begin(
        roles=["ObstetricianAttending", "BedsideNurse"],
        body_refs=[("encounter_id", "encounter")],
        specs=[s_str("encounter_id", required=True),
               s_enum("bundle_type", const.BUNDLE_TYPES, required=True),
               s_enum("activation_trigger", const.ACTIVATION_TRIGGERS, required=True),
               s_int("quantitative_blood_loss_ml", min=0),
               s_int("systolic_mmhg", min=60, max=300),
               s_int("diastolic_mmhg", min=30, max=200)],
    )
    enc = ctx.r["encounter"]
    unit = S.units.get(enc["unit_id"])
    bundle = ctx.v["bundle_type"]
    trigger = ctx.v["activation_trigger"]
    qbl = ctx.v["quantitative_blood_loss_ml"]
    systolic = ctx.v["systolic_mmhg"]
    diastolic = ctx.v["diastolic_mmhg"]
    if bundle == "SEVERE_HYPERTENSION" and qbl is not None:
        fail("ERR_INVALID_FIELD_VALUE", "quantitative_blood_loss_ml must be null.")
    if bundle == "OBSTETRIC_HEMORRHAGE" and (systolic is not None
                                             or diastolic is not None):
        fail("ERR_INVALID_FIELD_VALUE", "Blood pressure figures must be null.")
    if trigger == "QBL_THRESHOLD" and qbl is None:
        fail("ERR_INVALID_FIELD_VALUE", "quantitative_blood_loss_ml is required.")
    if trigger == "BP_THRESHOLD" and systolic is None and diastolic is None:
        fail("ERR_INVALID_FIELD_VALUE", "A blood pressure figure is required.")

    def phase():
        need(enc["labor_phase"] not in const.TERMINAL_PHASES,
             "ERR_ENCOUNTER_PHASE_TERMINAL")

    def single():
        for other in calc.live_activations(enc["id"]):
            need(other["bundle_type"] != bundle, "ERR_BUNDLE_ALREADY_ACTIVE")

    def criteria():
        if trigger == "QBL_THRESHOLD":
            need(qbl >= 1000, "ERR_ACTIVATION_CRITERIA_NOT_MET")
        elif trigger == "BP_THRESHOLD":
            need((systolic is not None and systolic >= 160)
                 or (diastolic is not None and diastolic >= 110),
                 "ERR_ACTIVATION_CRITERIA_NOT_MET")

    run_checks([(8.01, phase), (8.06, single), (11.5, criteria)])
    activation = store.new_record({
        "encounter_id": enc["id"],
        "unit_id": enc["unit_id"],
        "bundle_type": bundle,
        "activation_trigger": trigger,
        "quantitative_blood_loss_ml": qbl,
        "systolic_mmhg": systolic,
        "diastolic_mmhg": diastolic,
        "activated_at": clock.now(),
        "status": "ACTIVATED",
        "highest_stage_reached": 0,
        "on_time_step_count": 0,
        "late_step_count": 0,
        "missed_step_count": 0,
        "timeliness_score": None,
        "sequence_adjusted_score": None,
        "rescind_reason": None,
        "_stage2_qbl": None,
    })
    S.activations[activation["id"]] = activation
    _mint_items(activation)
    calc.rederive_encounter(enc)
    if unit["staffing_posture"] in ("INDUCTION_FROZEN", "DIVERT"):
        calc.cascade_bump(unit, ("CAPACITY_HELD",))
        calc.rederive_unit(unit)
    return common.created("activations", activation)


def _item_filters(records):
    status = q_enum("status", const.ITEM_STATUSES)
    gate = q_int("stage_gate")
    code = q_enum("step_code", const.STEP_CODES)
    staff_id = q_str("performed_by_staff_id")
    if gate is not None and gate not in (1, 2, 3):
        fail("ERR_INVALID_FIELD_VALUE", "stage_gate must be 1..3.")
    return [i for i in records
            if common.match(i, "status", status)
            and common.match(i, "stage_gate", gate)
            and common.match(i, "step_code", code)
            and common.match(i, "performed_by_staff_id", staff_id)]


@bp.get("/bundle-activations")
def list_activations():
    begin(roles=READ_ROLES)
    encounter_id = q_str("encounter_id")
    unit_id = q_str("unit_id")
    bundle = q_enum("bundle_type", const.BUNDLE_TYPES)
    status = q_enum("status", const.ACTIVATION_STATUSES)
    found = [a for a in S.activations.values()
             if common.match(a, "encounter_id", encounter_id)
             and common.match(a, "unit_id", unit_id)
             and common.match(a, "bundle_type", bundle)
             and common.match(a, "status", status)]
    return common.listing("activations", found,
                          [("activated_at", "asc"), ("created_at", "asc")])


@bp.get("/bundle-activations/<activation_id>")
def read_activation(activation_id):
    ctx = begin(roles=READ_ROLES, path=[("activation", activation_id)])
    return common.single("activations", ctx.p["activation"])


@bp.get("/bundle-activations/<activation_id>/checklist-items")
def list_activation_items(activation_id):
    ctx = begin(roles=READ_ROLES, path=[("activation", activation_id)])
    found = _item_filters(calc.rows("items", activation_id=ctx.p["activation"]["id"]))
    return common.listing("items", found, [("step_sequence", "asc")])


@bp.get("/bundle-activations/<activation_id>/checklist-items/<item_id>")
def read_activation_item(activation_id, item_id):
    ctx = begin(roles=READ_ROLES,
                path=[("activation", activation_id),
                      ("item", item_id, "activation", "activation_id")])
    return common.single("items", ctx.p["item"])


@bp.get("/bundle-checklist-items")
def list_items():
    begin(roles=READ_ROLES)
    activation_id = q_str("activation_id")
    found = _item_filters([i for i in S.items.values()
                           if common.match(i, "activation_id", activation_id)])
    return common.listing("items", found,
                          [("step_sequence", "asc"), ("created_at", "asc")])


@bp.get("/bundle-checklist-items/<item_id>")
def read_item(item_id):
    ctx = begin(roles=READ_ROLES, path=[("item", item_id)])
    return common.single("items", ctx.p["item"])


@bp.get("/bundle-activations/<activation_id>/timeliness-report")
def timeliness_report(activation_id):
    ctx = begin(roles=["ChargeNurse", "ObstetricianAttending",
                       "PerinatalSafetyOfficer"],
                path=[("activation", activation_id)])
    activation = ctx.p["activation"]
    items = calc.items_of(activation["id"])
    applicable = [i for i in items if i["status"] != "NOT_APPLICABLE"]
    _auth, _at, _al, _am, auth_flags = calc.score_run(activation,
                                                      "due_at_activation_anchored")
    _adv, _st, _sl, _sm, seq_flags = calc.score_run(activation,
                                                    "due_at_sequence_anchored")
    data = {
        "activation_id": activation["id"],
        "bundle_type": activation["bundle_type"],
        "status": activation["status"],
        "highest_stage_reached": activation["highest_stage_reached"],
        "activated_at": clock.fmt_dt(activation["activated_at"]),
        "applicable_item_count": len(applicable),
        "on_time_step_count": activation["on_time_step_count"],
        "late_step_count": activation["late_step_count"],
        "missed_step_count": activation["missed_step_count"],
        "timeliness_score": activation["timeliness_score"],
        "sequence_adjusted_score": activation["sequence_adjusted_score"],
        "items": [
            {"checklist_item_id": item["id"],
             "step_code": item["step_code"],
             "step_sequence": item["step_sequence"],
             "stage_gate": item["stage_gate"],
             "status": item["status"],
             "completed_at": clock.fmt_dt(item["completed_at"]),
             "minutes_from_activation": item["minutes_from_activation"],
             "due_at_activation_anchored": clock.fmt_dt(
                 item["due_at_activation_anchored"]),
             "due_at_sequence_anchored": clock.fmt_dt(
                 item["due_at_sequence_anchored"]),
             "on_time_activation_anchored": auth_flags.get(item["id"]),
             "on_time_sequence_anchored": seq_flags.get(item["id"])}
            for item in items],
    }
    return envelope.obj(data)


@bp.post("/bundle-activations/<activation_id>/checklist-items/<item_id>/complete")
def complete_item(activation_id, item_id):
    ctx = begin(
        roles=["BedsideNurse", "ChargeNurse", "ObstetricianAttending"],
        path=[("activation", activation_id),
              ("item", item_id, "activation", "activation_id")],
        body_refs=[("performed_by_staff_id", "staff")],
        specs=[s_dt("completed_at", required=True),
               s_str("performed_by_staff_id", required=True)],
        scope=lambda c: same_unit(c, c.p["activation"]["unit_id"], [c.r["staff"]]),
    )
    activation = ctx.p["activation"]
    item = ctx.p["item"]
    staff = ctx.r["staff"]
    enc = S.encounters.get(activation["encounter_id"])
    completed_at = ctx.v["completed_at"]

    def declared():
        need(item["status"] == "PENDING", "ERR_INVALID_STATE_TRANSITION")

    def phase():
        need(enc["labor_phase"] not in const.TERMINAL_PHASES,
             "ERR_ENCOUNTER_PHASE_TERMINAL")

    def gate():
        if item["stage_gate"] == 1 and activation["status"] == "ACTIVATED":
            return
        need(activation["highest_stage_reached"] >= item["stage_gate"],
             "ERR_CHECKLIST_STAGE_NOT_REACHED")

    def performer():
        need(calc.on_the_case(staff["id"], enc), "ERR_PERFORMER_NOT_ON_CASE")

    def stamp():
        need(activation["activated_at"] <= completed_at <= clock.now(),
             "ERR_CHECKLIST_TIMESTAMP_OUT_OF_RANGE")

    run_checks([(8, declared), (8.01, phase), (8.05, gate), (12, performer),
                (14.1, stamp)])

    on_time = completed_at <= item["due_at_activation_anchored"]
    item["status"] = "COMPLETED" if on_time else "LATE_COMPLETED"
    item["completed_at"] = completed_at
    item["performed_by_staff_id"] = staff["id"]
    item["minutes_from_activation"] = clock.whole_minutes_between(
        activation["activated_at"], completed_at)
    rev.touch(item)
    if on_time:
        activation["on_time_step_count"] += 1
    else:
        activation["late_step_count"] += 1
    if item["stage_gate"] == 1 and activation["status"] == "ACTIVATED":
        activation["status"] = "STAGE_1_IN_PROGRESS"
        activation["highest_stage_reached"] = max(
            1, activation["highest_stage_reached"])
    rev.touch(activation)
    calc.recompute_sequence_due(activation, item["step_sequence"] + 1)
    if (item["step_code"] == "MAGNESIUM_LOADED"
            and activation["bundle_type"] == "SEVERE_HYPERTENSION"):
        enc["magnesium_infusion_active"] = True
        rev.touch(enc)
    calc.rederive_encounter(enc)
    return common.single("items", item)


@bp.post("/bundle-activations/<activation_id>/escalate-stage")
def escalate_stage(activation_id):
    ctx = begin(roles=["ObstetricianAttending"], path=[("activation", activation_id)],
                specs=[s_int("target_stage", required=True, min=2, max=3),
                       s_int("quantitative_blood_loss_ml", min=0),
                       s_int("systolic_mmhg", min=60, max=300),
                       s_int("diastolic_mmhg", min=30, max=200)])
    activation = ctx.p["activation"]
    unit = S.units.get(activation["unit_id"])
    enc = S.encounters.get(activation["encounter_id"])
    target = ctx.v["target_stage"]
    qbl = ctx.v["quantitative_blood_loss_ml"]
    systolic = ctx.v["systolic_mmhg"]
    diastolic = ctx.v["diastolic_mmhg"]
    hemorrhage = activation["bundle_type"] == "OBSTETRIC_HEMORRHAGE"
    if hemorrhage and qbl is None:
        fail("ERR_INVALID_FIELD_VALUE", "quantitative_blood_loss_ml is required.")
    if not hemorrhage and target == 2 and systolic is None and diastolic is None:
        fail("ERR_INVALID_FIELD_VALUE", "A severe-range reading is required.")

    def declared():
        expected = "STAGE_1_IN_PROGRESS" if target == 2 else "STAGE_2_ESCALATED"
        need(activation["status"] == expected, "ERR_INVALID_STATE_TRANSITION")

    def gates():
        limit = 1 if target == 2 else 2
        for item in calc.items_of(activation["id"]):
            if item["stage_gate"] <= limit:
                need(item["status"] in const.ITEM_TERMINAL
                     or item["status"] == "NOT_APPLICABLE",
                     "ERR_CHECKLIST_STAGE_INCOMPLETE")

    def standby():
        if target == 3:
            need(calc.or_standby_staffed(unit["id"]), "ERR_OR_STANDBY_NOT_STAFFED")

    def criteria():
        if hemorrhage:
            floor = 1500 if target == 2 else 2500
            need(qbl >= floor, "ERR_BUNDLE_STAGE_CRITERIA_NOT_MET")
        else:
            need(target == 2, "ERR_BUNDLE_STAGE_CRITERIA_NOT_MET")
            need((systolic is not None and systolic >= 160)
                 or (diastolic is not None and diastolic >= 110),
                 "ERR_BUNDLE_STAGE_CRITERIA_NOT_MET")

    run_checks([(8, declared), (8.05, gates), (11.4, standby), (11.5, criteria)])

    activation["status"] = ("STAGE_2_ESCALATED" if target == 2
                            else "STAGE_3_MASSIVE_TRANSFUSION")
    activation["highest_stage_reached"] = max(activation["highest_stage_reached"],
                                             target)
    if qbl is not None:
        activation["quantitative_blood_loss_ml"] = qbl
    if systolic is not None:
        activation["systolic_mmhg"] = systolic
    if diastolic is not None:
        activation["diastolic_mmhg"] = diastolic
    if target == 2:
        activation["_stage2_qbl"] = qbl
    rev.touch(activation)

    if target == 3:
        event = store.new_record({
            "encounter_id": enc["id"],
            "or_bed_id": None,
            "triggering_assessment_id": None,
            "triggering_activation_id": activation["id"],
            "urgency_class": "CATEGORY_1_CRASH",
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
    if unit["staffing_posture"] in ("INDUCTION_FROZEN", "DIVERT"):
        calc.cascade_bump(unit, ("CAPACITY_HELD", "CONFIRMED"))
        calc.rederive_unit(unit)
    return common.single("activations", activation)


def _void_pending(activation, gate_above=None):
    """PENDING items become NOT_APPLICABLE; `gate_above` limits the void to the
    gates the run never reached."""
    for item in calc.items_of(activation["id"]):
        if item["status"] != "PENDING":
            continue
        if gate_above is not None and item["stage_gate"] <= gate_above:
            continue
        item["status"] = "NOT_APPLICABLE"
        rev.touch(item)


@bp.post("/bundle-activations/<activation_id>/resolve")
def resolve_activation(activation_id):
    ctx = begin(roles=["ObstetricianAttending"], path=[("activation", activation_id)],
                specs=[s_int("quantitative_blood_loss_ml", min=0)])
    activation = ctx.p["activation"]
    enc = S.encounters.get(activation["encounter_id"])
    unit = S.units.get(activation["unit_id"])
    qbl = ctx.v["quantitative_blood_loss_ml"]
    hemorrhage = activation["bundle_type"] == "OBSTETRIC_HEMORRHAGE"
    if hemorrhage and qbl is None:
        fail("ERR_INVALID_FIELD_VALUE", "quantitative_blood_loss_ml is required.")
    if not hemorrhage and qbl is not None:
        fail("ERR_INVALID_FIELD_VALUE",
             "quantitative_blood_loss_ml must be null for a hypertension bundle.")
    stage3 = activation["status"] == "STAGE_3_MASSIVE_TRANSFUSION"

    def declared():
        need(activation["status"] in ("STAGE_2_ESCALATED",
                                      "STAGE_3_MASSIVE_TRANSFUSION"),
             "ERR_INVALID_STATE_TRANSITION")

    def gates():
        limit = 3 if stage3 else 2
        for item in calc.items_of(activation["id"]):
            if item["stage_gate"] <= limit:
                need(item["status"] in const.ITEM_TERMINAL
                     or item["status"] == "NOT_APPLICABLE",
                     "ERR_CHECKLIST_STAGE_INCOMPLETE")

    def theatre():
        if not stage3:
            return
        for event in calc.rows("cesareans", triggering_activation_id=activation["id"]):
            need(event["status"] not in const.CESAREAN_IN_THEATRE,
                 "ERR_CESAREAN_EVENT_IN_PROGRESS")

    def controlled():
        if not hemorrhage:
            return
        stage2 = activation.get("_stage2_qbl")
        if stage2 is not None:
            need(qbl <= stage2, "ERR_BUNDLE_NOT_CONTROLLED")

    run_checks([(8, declared), (8.05, gates), (8.052, theatre),
                (11.5, controlled)])

    if qbl is not None:
        activation["quantitative_blood_loss_ml"] = qbl
    activation["status"] = "CONTROLLED"
    _void_pending(activation, gate_above=activation["highest_stage_reached"])
    auth, advisory, on_time, late, missed = calc.timeliness_scores(activation)
    activation["timeliness_score"] = auth
    activation["sequence_adjusted_score"] = advisory
    activation["on_time_step_count"] = on_time
    activation["late_step_count"] = late
    activation["missed_step_count"] = missed
    if missed >= 1 or late >= 2 or activation["highest_stage_reached"] >= 2:
        activation["status"] = "DEBRIEF_PENDING"
    rev.touch(activation)
    if missed >= 1 and unit is not None:
        # Only the missed-step condition is a unit-level bundle breach.
        unit["bundle_breach_count"] = (unit.get("bundle_breach_count") or 0) + 1
        rev.touch(unit)
    calc.rederive_encounter(enc)
    return common.single("activations", activation)


@bp.post("/bundle-activations/<activation_id>/close-debrief")
def close_debrief(activation_id):
    ctx = begin(roles=["PerinatalSafetyOfficer"],
                path=[("activation", activation_id)],
                specs=[s_str("debrief_notes")])
    activation = ctx.p["activation"]
    enc = S.encounters.get(activation["encounter_id"])
    notes = ctx.v["debrief_notes"]

    def declared():
        need(activation["status"] in ("CONTROLLED", "DEBRIEF_PENDING"),
             "ERR_INVALID_STATE_TRANSITION")

    def context_fields():
        if activation["status"] != "DEBRIEF_PENDING":
            return
        need(notes is not None and 40 <= len(notes) <= 2000,
             "ERR_DEBRIEF_NOTES_REQUIRED")

    def duties():
        for item in calc.items_of(activation["id"]):
            need(item.get("performed_by_staff_id") != ctx.user_id,
                 "ERR_SEGREGATION_OF_DUTIES_VIOLATION")

    def scored():
        need(activation.get("timeliness_score") is not None,
             "ERR_BUNDLE_SCORE_NOT_COMPUTED")

    run_checks([(8, declared), (9, context_fields), (10, duties), (11.5, scored)])

    activation["status"] = "CLOSED"
    _void_pending(activation)
    rev.touch(activation)
    calc.rederive_encounter(enc)
    return common.single("activations", activation)


@bp.post("/bundle-activations/<activation_id>/rescind")
def rescind_activation(activation_id):
    ctx = begin(roles=["ObstetricianAttending"],
                path=[("activation", activation_id)],
                specs=[s_str("rescind_reason"),
                       s_int("expected_activation_version", required=True)],
                occ=("expected_activation_version", "ERR_STALE_ACTIVATION_VERSION",
                     lambda c: c.p["activation"]))
    activation = ctx.p["activation"]
    enc = S.encounters.get(activation["encounter_id"])
    reason = ctx.v["rescind_reason"]

    def declared():
        need(activation["status"] in ("ACTIVATED", "STAGE_1_IN_PROGRESS"),
             "ERR_INVALID_STATE_TRANSITION")

    def stage_block():
        need(activation["highest_stage_reached"] <= 1,
             "ERR_BUNDLE_STAGE_BLOCKS_RESCIND")

    def context_fields():
        need(reason is not None and 10 <= len(reason) <= 500,
             "ERR_RESCIND_REASON_REQUIRED")

    run_checks([(8, declared), (8.10, stage_block), (9, context_fields)])

    activation["status"] = "RESCINDED"
    activation["rescind_reason"] = reason
    for item in calc.items_of(activation["id"]):
        if item["status"] != "NOT_APPLICABLE":
            item["status"] = "NOT_APPLICABLE"
            rev.touch(item)
    activation["on_time_step_count"] = 0
    activation["late_step_count"] = 0
    activation["missed_step_count"] = 0
    activation["timeliness_score"] = None
    activation["sequence_adjusted_score"] = None
    rev.touch(activation)
    if enc is not None and enc.get("magnesium_infusion_active"):
        enc["magnesium_infusion_active"] = False
        rev.touch(enc)
    # Re-pricing credits the bundle price back and debits the pre-activation one,
    # so every conservation sum returns to its exact prior value.
    calc.rederive_encounter(enc)
    return common.single("activations", activation)
