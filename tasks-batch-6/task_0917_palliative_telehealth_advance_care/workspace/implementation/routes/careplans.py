"""Care plans, symptom assessments and after-hours escalations (PRD 3.5, 3.6)."""

from flask import Blueprint

import calc
import cascades
import config
from envelope import created, listing, ok
from errors import ERR_STALE_CARE_PLAN_VERSION, ERR_VALIDATION, api_error
from ladder import (
    apply_filters, auth, field, fk, freeze_gate, occ, pagination, paginate,
    path_row, query_filters, raw_body, state, touch, validate,
)
from store import ordered, store

bp = Blueprint("careplans", __name__)


# ---------------------------------------------------------------- care plans
@bp.post("/palliative/care-plans")
def create_care_plan():
    auth([config.ROLE_NURSE, config.ROLE_SOCIAL, config.ROLE_ADMIN])
    body = raw_body()
    data = validate(body, [
        field("patient_id", "string", required=True),
        field("plan_title", "string", required=True),
        field("problem_list", "array", required=True, item_kind="string"),
    ])
    patient = fk(store.patients, data["patient_id"])
    freeze_gate(patient)
    row = store.new_row({
        "patient_id": patient["id"],
        "plan_title": data["plan_title"],
        "problem_list": list(data["problem_list"]),
        "revision_number": 0,
        "closed_reason": None,
        "status": "DRAFT",
    })
    store.care_plans[row["id"]] = row
    return created(row)


@bp.post("/palliative/care-plans/<cid>/activate")
def activate_care_plan(cid):
    auth([config.ROLE_NURSE, config.ROLE_ADMIN])
    plan = path_row(store.care_plans, cid)
    body = raw_body()
    validate(body, [field("activation_note", "string")])
    patient = store.patients.get(plan["patient_id"])
    freeze_gate(patient)
    state(plan["status"] in ("DRAFT", "UNDER_REVISION"))
    if plan["status"] == "DRAFT":
        state(patient is not None
              and patient["program_status"] in ("ACTIVE", "HOSPICE_ELECTED"))
        plan["status"] = "ACTIVE"
    else:
        plan["status"] = "ACTIVE"
        plan["revision_number"] += 1
    touch(plan)
    return ok(plan)


@bp.post("/palliative/care-plans/<cid>/revisions")
def revise_care_plan(cid):
    auth([config.ROLE_NURSE, config.ROLE_ADMIN])
    plan = path_row(store.care_plans, cid)
    body = raw_body()
    data = validate(body, [
        field("expected_care_plan_version", "integer", required=True),
        field("revised_problem_list", "array", required=True, item_kind="string"),
    ])
    freeze_gate(store.patients.get(plan["patient_id"]))
    state(plan["status"] == "ACTIVE")
    occ(data["expected_care_plan_version"], plan["version"], ERR_STALE_CARE_PLAN_VERSION)
    plan["status"] = "UNDER_REVISION"
    plan["problem_list"] = list(data["revised_problem_list"])
    touch(plan)
    return ok(plan)


@bp.get("/palliative/care-plans/<cid>")
def read_care_plan(cid):
    auth([config.ROLE_NURSE, config.ROLE_SOCIAL, config.ROLE_PHYSICIAN, config.ROLE_ADMIN])
    return ok(path_row(store.care_plans, cid))


@bp.get("/palliative/care-plans")
def list_care_plans():
    auth([config.ROLE_NURSE, config.ROLE_SOCIAL, config.ROLE_PHYSICIAN, config.ROLE_ADMIN])
    limit, offset = pagination()
    rows = apply_filters(ordered(store.care_plans.values()),
                         query_filters(["patient_id", "status"]))
    page, total = paginate(rows, limit, offset)
    return listing(page, limit, offset, total)


# -------------------------------------------------------- symptom assessments
@bp.post("/palliative/symptom-assessments")
def create_symptom_assessment():
    auth([config.ROLE_NURSE, config.ROLE_CAREGIVER, config.ROLE_ADMIN])
    body = raw_body()
    items = ["item_pain", "item_dyspnea", "item_nausea", "item_anxiety", "item_fatigue"]
    specs = [
        field("patient_id", "string", required=True),
        field("care_plan_id", "string", required=True),
        field("reporter_type", "enum", required=True, enum=config.REPORTER_TYPES),
    ]
    for name in items:
        specs.append(field(name, "integer", required=True,
                           lo=config.SYMPTOM_ITEM_MIN, hi=config.SYMPTOM_ITEM_MAX))
    data = validate(body, specs)
    patient = fk(store.patients, data["patient_id"])
    plan = fk(store.care_plans, data["care_plan_id"])
    freeze_gate(patient)

    distress = calc.symptom_distress_score(
        data["reporter_type"], data["item_pain"], data["item_dyspnea"],
        data["item_nausea"], data["item_anxiety"], data["item_fatigue"])
    tier = calc.severity_tier(distress)
    row = store.new_row({
        "patient_id": patient["id"],
        "care_plan_id": plan["id"],
        "reporter_type": data["reporter_type"],
        "item_pain": data["item_pain"],
        "item_dyspnea": data["item_dyspnea"],
        "item_nausea": data["item_nausea"],
        "item_anxiety": data["item_anxiety"],
        "item_fatigue": data["item_fatigue"],
        "distress_score": distress,
        "severity_tier": tier,
        "response_due_at": None,
        "triage_status": "OPEN",
        "escalation_status": "NONE",
        "resolution_reason": None,
    })
    row["response_due_at"] = calc.response_due_at(row["created_at"], tier)
    store.symptom_assessments[row["id"]] = row
    cascades.recompute_open_symptom_count(patient)
    return created(row)


@bp.post("/palliative/symptom-assessments/<sid>/triage-update")
def triage_update(sid):
    auth([config.ROLE_NURSE, config.ROLE_ADMIN])
    row = path_row(store.symptom_assessments, sid)
    body = raw_body()
    data = validate(body, [
        field("action", "enum", required=True, enum=config.TRIAGE_ACTIONS),
        field("triage_note", "string"),
    ])
    patient = store.patients.get(row["patient_id"])
    freeze_gate(patient)
    if data["action"] == "ACKNOWLEDGE":
        state(row["triage_status"] == "OPEN")
        row["triage_status"] = "ACKNOWLEDGED"
        touch(row)
    else:
        state(row["triage_status"] == "ACKNOWLEDGED")
        row["triage_status"] = "RESOLVED"
        row["resolution_reason"] = ("ESCALATION_DISPOSITIONED"
                                    if row["escalation_status"] == "DISPOSITIONED"
                                    else "SYMPTOM_CONTROLLED")
        touch(row)
        for esc in store.escalations.values():
            if esc["symptom_assessment_id"] == row["id"] and esc["status"] == "DISPOSITIONED":
                esc["status"] = "CLOSED"
                touch(esc)
        if patient is not None:
            cascades.recompute_open_symptom_count(patient)
    return ok(row)


@bp.get("/palliative/symptom-assessments/<sid>")
def read_symptom_assessment(sid):
    auth([config.ROLE_NURSE, config.ROLE_ONCALL, config.ROLE_PHYSICIAN,
          config.ROLE_CAREGIVER, config.ROLE_ADMIN])
    return ok(path_row(store.symptom_assessments, sid))


@bp.get("/palliative/symptom-assessments")
def list_symptom_assessments():
    auth([config.ROLE_NURSE, config.ROLE_ONCALL, config.ROLE_PHYSICIAN,
          config.ROLE_CAREGIVER, config.ROLE_ADMIN])
    limit, offset = pagination()
    rows = apply_filters(ordered(store.symptom_assessments.values()),
                         query_filters(["patient_id", "care_plan_id", "triage_status"]))
    page, total = paginate(rows, limit, offset)
    return listing(page, limit, offset, total)


# ---------------------------------------------------------------- escalations
@bp.post("/palliative/escalations")
def create_escalation():
    auth([config.ROLE_ONCALL, config.ROLE_NURSE, config.ROLE_ADMIN])
    body = raw_body()
    data = validate(body, [
        field("patient_id", "string", required=True),
        field("symptom_assessment_id", "string", required=True),
        field("contact_summary", "string", required=True),
    ])
    patient = fk(store.patients, data["patient_id"])
    assessment = fk(store.symptom_assessments, data["symptom_assessment_id"])
    freeze_gate(patient)
    state(assessment["escalation_status"] == "NONE"
          and assessment["triage_status"] in ("OPEN", "ACKNOWLEDGED"))

    now = store.now()
    row = store.new_row({
        "patient_id": patient["id"],
        "symptom_assessment_id": assessment["id"],
        "tier": config.ESCALATION_TIER_MIN,
        "tier_notified_at": now,
        "ack_due_at": calc.ack_due_at(now, config.ESCALATION_TIER_MIN),
        "acknowledged_at": None,
        "acknowledged_by_user_id": None,
        "disposition": None,
        "status": "TIER_NOTIFIED",
    })
    store.escalations[row["id"]] = row
    assessment["escalation_status"] = "ESCALATED"
    touch(assessment)
    return created(row)


@bp.post("/palliative/escalations/<eid>/promote")
def promote_escalation(eid):
    auth([config.ROLE_ONCALL, config.ROLE_ADMIN])
    row = path_row(store.escalations, eid)
    body = raw_body()
    validate(body, [field("promotion_note", "string")])
    freeze_gate(store.patients.get(row["patient_id"]))
    state(row["status"] == "TIER_NOTIFIED")
    state(row["tier"] < config.ESCALATION_TIER_MAX)
    state(store.now() >= row["ack_due_at"])
    row["tier"] += 1
    row["tier_notified_at"] = store.now()
    row["ack_due_at"] = calc.ack_due_at(row["tier_notified_at"], row["tier"])
    touch(row)
    return ok(row)


@bp.post("/palliative/escalations/<eid>/response")
def respond_escalation(eid):
    ctx = auth([config.ROLE_ONCALL, config.ROLE_ADMIN])
    row = path_row(store.escalations, eid)
    body = raw_body()
    data = validate(body, [
        field("response_type", "enum", required=True, enum=config.ESCALATION_RESPONSE_TYPES),
        field("disposition", "enum", enum=config.CLIENT_DISPOSITIONS),
    ])
    if data["response_type"] == "DISPOSITION" and data["disposition"] is None:
        raise api_error(ERR_VALIDATION, "disposition is required for a DISPOSITION response.")
    freeze_gate(store.patients.get(row["patient_id"]))

    if data["response_type"] == "ACKNOWLEDGE":
        state(row["status"] == "TIER_NOTIFIED")
        row["status"] = "ACKNOWLEDGED"
        row["acknowledged_at"] = store.now()
        row["acknowledged_by_user_id"] = ctx.user_id
        touch(row)
    else:
        state(row["status"] == "ACKNOWLEDGED")
        row["status"] = "DISPOSITIONED"
        row["disposition"] = data["disposition"]
        touch(row)
        assessment = store.symptom_assessments.get(row["symptom_assessment_id"])
        if assessment is not None and assessment["escalation_status"] == "ESCALATED":
            assessment["escalation_status"] = "DISPOSITIONED"
            touch(assessment)
    return ok(row)


@bp.get("/palliative/escalations/<eid>")
def read_escalation(eid):
    auth([config.ROLE_ONCALL, config.ROLE_NURSE, config.ROLE_PHYSICIAN, config.ROLE_ADMIN])
    return ok(path_row(store.escalations, eid))


@bp.get("/palliative/escalations")
def list_escalations():
    auth([config.ROLE_ONCALL, config.ROLE_NURSE, config.ROLE_PHYSICIAN, config.ROLE_ADMIN])
    limit, offset = pagination()
    rows = apply_filters(ordered(store.escalations.values()),
                         query_filters(["patient_id", "symptom_assessment_id", "status"]))
    page, total = paginate(rows, limit, offset)
    return listing(page, limit, offset, total)
