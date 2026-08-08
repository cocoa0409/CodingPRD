"""Therapy plans, their phase ladder, and the revision / suspension cycles."""

from datetime import timedelta

from flask import Blueprint, request

import calc
import cascades
import config
import lookup
import serialize
from auth import authenticate
from envelope import created, ok, paginate, pagination
from errors import ApiError
from store import base_row, db, latest, now, now_iso, ordered, parse_instant, touch
from validate import filter_enum, json_body

bp = Blueprint("plans", __name__)
P = config.API_PREFIX


@bp.post(P + "/therapy-plans")
def create_plan():
    authenticate([config.ROLE_OPTOMETRIST])
    b = json_body()
    patient_id = b.str_req("patient_id")
    source_assessment_id = b.str_req("source_assessment_id")
    b.enum_shape_req("discharge_criteria_mode")
    per_week = b.int_req("prescribed_home_sessions_per_week")
    mode = b.enum_req("discharge_criteria_mode", config.DISCHARGE_CRITERIA_MODES)

    lookup.patient_or_404(patient_id)                                      # rung 5
    source = lookup.assessment_or_404(source_assessment_id)                # rung 7
    lookup.gate_for_patient_id(patient_id)                                 # rung 12
    if source["status"] != "SIGNED" or source["assessment_type"] != "EVALUATION":  # rung 14
        raise ApiError("ERR_INVALID_STATE",
                       "A plan may only be authored from a SIGNED EVALUATION battery.")

    npc = calc.latest_metric(source["id"], "NPC")
    amp = calc.latest_metric(source["id"], "ACCOMMODATIVE_AMPLITUDE")
    verg = calc.latest_metric(source["id"], "VERGENCE_BASE_OUT")
    acu = calc.latest_metric(source["id"], "VISUAL_ACUITY")
    ciss = calc.latest_metric(source["id"], "SYMPTOM_SURVEY")

    row = base_row()
    row.update({
        "patient_id": patient_id,
        "source_assessment_id": source_assessment_id,
        "authorization_id": None,
        "status": "DRAFT",
        "progress_state": "ON_TRACK",
        "discharge_criteria_mode": mode,
        "current_phase_index": 1,
        "prescribed_home_sessions_per_week": per_week,
        "previous_prescribed_home_sessions_per_week": None,
        "prescription_changed_at": None,
        "cumulative_therapy_minutes": 0.0,
        "home_compliance_pct": 0.0,
        "revision_count": 0,
        "consecutive_low_delta_count": 0,
        "suspension_reason": None,
        "discharge_ready": False,
        "baseline_npc_break_cm": npc["npc_break_cm"] if npc else None,
        "baseline_amplitude_d": amp["amplitude_d"] if amp else None,
        "baseline_vergence_bo_break_pd": verg["vergence_bo_break_pd"] if verg else None,
        "baseline_acuity_logmar": acu["acuity_logmar"] if acu else None,
        "baseline_ciss_score": ciss["ciss_score"] if ciss else None,
    })
    db.plans[row["id"]] = row
    return created(serialize.plan(row))


@bp.get(P + "/therapy-plans/<id>")
def get_plan(id):
    authenticate(config.READ_ROLES)
    return ok(serialize.plan(lookup.plan_or_404(id)))


@bp.get(P + "/therapy-plans")
def list_plans():
    authenticate(config.READ_ROLES)
    limit, offset = pagination(request.args)
    status = filter_enum(request.args, "status", config.PLAN_STATUSES)
    progress_state = filter_enum(request.args, "progress_state", config.PROGRESS_STATES)
    patient_id = request.args.get("patient_id")
    source_assessment_id = request.args.get("source_assessment_id")
    authorization_id = request.args.get("authorization_id")

    def match(row):
        if patient_id and row["patient_id"] != patient_id:
            return False
        if source_assessment_id and row["source_assessment_id"] != source_assessment_id:
            return False
        if authorization_id and row["authorization_id"] != authorization_id:
            return False
        if status and row["status"] != status:
            return False
        if progress_state and row["progress_state"] != progress_state:
            return False
        return True

    return paginate(ordered(db.plans, match), limit, offset, serialize.plan)


def _phase_at(plan_id, sequence_index):
    for phase in db.phases.values():
        if phase["plan_id"] == plan_id and phase["sequence_index"] == sequence_index:
            return phase
    return None


@bp.post(P + "/therapy-plans/<id>/activate")
def activate_plan(id):
    authenticate([config.ROLE_OPTOMETRIST])
    b = json_body()
    authorization_id = b.str_req("authorization_id")
    plan = lookup.plan_or_404(id)                                          # rung 8
    auth_row = lookup.authorization_or_404(authorization_id)               # rung 11
    lookup.gate_for_plan(plan)                                             # rung 12

    if plan["status"] not in ("DRAFT", "UNDER_REVISION"):                  # rung 14
        raise ApiError("ERR_INVALID_STATE", "Only a DRAFT or UNDER_REVISION plan may be activated.")
    if auth_row["patient_id"] != plan["patient_id"]:
        raise ApiError("ERR_INVALID_STATE", "The authorization belongs to a different patient.")
    if auth_row["status"] not in ("ACTIVE", "EXHAUSTED"):
        raise ApiError("ERR_INVALID_STATE", "The authorization is not ACTIVE or EXHAUSTED.")

    if plan["status"] == "DRAFT":
        first = _phase_at(plan["id"], 1)
        if first is None:
            raise ApiError("ERR_INVALID_STATE", "The plan has no phase with sequence_index 1.")
        plan["status"] = "ACTIVE"
        plan["authorization_id"] = authorization_id
        plan["current_phase_index"] = 1
        touch(plan)
        first["status"] = "IN_PROGRESS"
        first["started_at"] = now_iso()
        touch(first)
    else:
        plan["status"] = "ACTIVE"
        plan["authorization_id"] = authorization_id
        if plan["progress_state"] == "REVISION_PENDING":
            plan["progress_state"] = "ON_TRACK"
        touch(plan)
    return ok(serialize.plan(plan))


@bp.post(P + "/therapy-plans/<id>/advance-phase")
def advance_phase(id):
    authenticate([config.ROLE_OPTOMETRIST, config.ROLE_VISION_THERAPIST])
    json_body()
    plan = lookup.plan_or_404(id)                                          # rung 8
    lookup.gate_for_plan(plan)                                             # rung 12
    if plan["status"] != "ACTIVE":                                         # rung 15
        raise ApiError("ERR_PLAN_NOT_ACTIVE")

    current = cascades.in_progress_phase(plan["id"])
    if current is None:
        raise ApiError("ERR_INVALID_STATE", "No phase on this plan is IN_PROGRESS.")
    nxt = _phase_at(plan["id"], current["sequence_index"] + 1)

    if nxt is not None and nxt["sequence_index"] >= config.PHASE_REASSESS_FROM_INDEX:  # rung 24
        cutoff = now() - timedelta(days=config.REASSESS_WINDOW_DAYS)
        fresh = False
        for a in db.assessments.values():
            if (a["plan_id"] == plan["id"] and a["assessment_type"] == "REASSESSMENT"
                    and a["status"] == "SIGNED"):
                signed_at = parse_instant(a.get("signed_at"))
                if signed_at is not None and signed_at >= cutoff:
                    fresh = True
                    break
        if not fresh:
            raise ApiError("ERR_REASSESSMENT_REQUIRED")

    if current["activities_mastered_count"] < current["required_mastery_count"]:        # rung 25
        raise ApiError("ERR_MASTERY_NOT_MET")

    compliance = calc.compute_home_compliance(plan)                                     # rung 26
    if calc.D(compliance) < calc.D(config.PHASE_ADVANCE_COMPLIANCE_PCT):
        raise ApiError("ERR_COMPLIANCE_BELOW_THRESHOLD")

    plan["home_compliance_pct"] = compliance
    current["status"] = "MASTERED"
    current["mastered_at"] = now_iso()
    touch(current)

    if nxt is not None:
        nxt["status"] = "IN_PROGRESS"
        nxt["started_at"] = now_iso()
        touch(nxt)
        plan["current_phase_index"] = nxt["sequence_index"]
    else:
        plan["status"] = "COMPLETED"
        plan["progress_state"] = "DISCHARGE_PENDING"
    touch(plan)
    return ok(serialize.plan(plan))


@bp.post(P + "/therapy-plans/<id>/revise")
def revise_plan(id):
    authenticate([config.ROLE_OPTOMETRIST])
    b = json_body()
    expected_version = b.int_req("expected_plan_version")
    b.str_opt("revision_reason")
    new_per_week = b.int_opt("prescribed_home_sessions_per_week")
    plan = lookup.plan_or_404(id)                                          # rung 8
    lookup.gate_for_plan(plan)                                             # rung 12
    if expected_version != plan["version"]:                                # rung 13
        raise ApiError("ERR_STALE_VERSION")
    if plan["status"] not in ("ACTIVE", "SUSPENDED"):                      # rung 14
        raise ApiError("ERR_INVALID_STATE", "Only an ACTIVE or SUSPENDED plan may be revised.")

    plan["status"] = "UNDER_REVISION"
    plan["revision_count"] += 1
    if new_per_week is not None:
        plan["previous_prescribed_home_sessions_per_week"] = plan["prescribed_home_sessions_per_week"]
        plan["prescribed_home_sessions_per_week"] = new_per_week
        plan["prescription_changed_at"] = now_iso()
    touch(plan)
    return ok(serialize.plan(plan))


@bp.post(P + "/therapy-plans/<id>/suspend")
def suspend_plan(id):
    authenticate([config.ROLE_OPTOMETRIST])
    b = json_body()
    b.enum_shape_req("suspension_reason")                                  # rung 3
    reason = b.enum_req("suspension_reason", config.SUSPENSION_REASONS)    # rung 4
    plan = lookup.plan_or_404(id)                                          # rung 8
    lookup.gate_for_plan(plan)                                             # rung 12
    if plan["status"] != "ACTIVE":                                         # rung 14
        raise ApiError("ERR_INVALID_STATE", "Only an ACTIVE plan may be suspended.")

    cascades.suspend_plan(plan, reason)
    return ok(serialize.plan(plan))


@bp.post(P + "/therapy-plans/<id>/resume")
def resume_plan(id):
    authenticate([config.ROLE_OPTOMETRIST])
    json_body()
    plan = lookup.plan_or_404(id)                                          # rung 8
    lookup.gate_for_plan(plan)                                             # rung 12
    if plan["status"] != "SUSPENDED":                                      # rung 14
        raise ApiError("ERR_INVALID_STATE", "Only a SUSPENDED plan may be resumed.")
    if plan["suspension_reason"] == "RED_FLAG_REFERRAL":
        for referral in db.referrals.values():
            if (referral["plan_id"] == plan["id"] and referral["direction"] == "OUTBOUND"
                    and referral["urgency"] == "URGENT"
                    and referral["status"] not in ("ACCEPTED", "ABANDONED")):
                raise ApiError("ERR_INVALID_STATE",
                               "An urgent outbound referral on this plan is still open.")

    plan["status"] = "ACTIVE"
    plan["suspension_reason"] = None
    touch(plan)
    return ok(serialize.plan(plan))


# ---------------------------------------------------------------- phases ---
@bp.post(P + "/therapy-plans/<id>/phases")
def create_phase(id):
    authenticate([config.ROLE_OPTOMETRIST])
    b = json_body()
    sequence_index = b.int_req("sequence_index")
    name = b.str_req("name")
    required_mastery_count = b.int_req("required_mastery_count")
    plan = lookup.plan_or_404(id)                                          # rung 8
    lookup.gate_for_plan(plan)                                             # rung 12

    row = base_row()
    row.update({
        "plan_id": plan["id"],
        "sequence_index": sequence_index,
        "name": name,
        "required_mastery_count": required_mastery_count,
        "activities_mastered_count": 0,
        "status": "LOCKED",
        "started_at": None,
        "mastered_at": None,
    })
    db.phases[row["id"]] = row
    return created(serialize.phase(row))


@bp.get(P + "/therapy-plans/<id>/phases")
def list_phases(id):
    authenticate(config.READ_ROLES)
    limit, offset = pagination(request.args)
    status = filter_enum(request.args, "status", config.PHASE_STATUSES)
    lookup.plan_or_404(id)

    rows = [p for p in db.phases.values()
            if p["plan_id"] == id and (not status or p["status"] == status)]
    # The one list in the service that is NOT sorted by created_at.
    rows.sort(key=lambda p: (p["sequence_index"], p["created_at"], p["_seq"]))
    return paginate(rows, limit, offset, serialize.phase)


@bp.post(P + "/phases/<id>/mastery")
def record_mastery(id):
    authenticate([config.ROLE_OPTOMETRIST, config.ROLE_VISION_THERAPIST,
                  config.ROLE_THERAPY_ASSISTANT])
    b = json_body()
    delta = b.int_req("mastered_delta", non_negative=True)
    phase = lookup.phase_or_404(id)                                        # rung 11
    plan = db.plans.get(phase["plan_id"])
    if plan is not None:
        lookup.gate_for_plan(plan)                                         # rung 12
    if plan is None or plan["status"] != "ACTIVE":                         # rung 15
        raise ApiError("ERR_PLAN_NOT_ACTIVE")

    phase["activities_mastered_count"] += delta
    touch(phase)
    return ok(serialize.phase(phase))
