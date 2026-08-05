"""Referral traffic in and out of the practice."""

from datetime import timedelta

from flask import Blueprint, request

import cascades
import config
import lookup
import serialize
from auth import authenticate
from envelope import created, ok, paginate, pagination
from errors import ApiError
from store import db, iso3, now, now_iso, ordered, parse_instant, touch
from validate import filter_enum, json_body

bp = Blueprint("referrals", __name__)
P = config.API_PREFIX


@bp.post(P + "/referrals")
def create_referral():
    authenticate([config.ROLE_FRONT_DESK, config.ROLE_OPTOMETRIST])
    b = json_body()
    patient_id = b.str_req("patient_id")
    b.enum_shape_req("direction")
    b.enum_shape_req("urgency")
    referring = b.str_req("referring_provider_name")
    target = b.str_req("target_provider_name")
    reason = b.str_req("reason")
    plan_id = b.str_opt("plan_id")
    triggering_assessment_id = b.str_opt("triggering_assessment_id")
    direction = b.enum_req("direction", config.DIRECTIONS)
    urgency = b.enum_req("urgency", config.URGENCIES)

    lookup.patient_or_404(patient_id)                                      # rung 5
    if triggering_assessment_id:
        lookup.assessment_or_404(triggering_assessment_id)                 # rung 7
    if plan_id:
        lookup.plan_or_404(plan_id)                                        # rung 8
    lookup.gate_for_patient_id(patient_id)                                 # rung 12

    row = cascades.create_referral_row(
        patient_id=patient_id,
        direction=direction,
        urgency=urgency,
        referring_provider_name=referring,
        target_provider_name=target,
        reason=reason,
        plan_id=plan_id,
        triggering_assessment_id=triggering_assessment_id,
    )
    return created(serialize.referral(row))


@bp.get(P + "/referrals/<id>")
def get_referral(id):
    authenticate(config.READ_ROLES)
    return ok(serialize.referral(lookup.referral_or_404(id)))


@bp.get(P + "/referrals")
def list_referrals():
    authenticate(config.READ_ROLES)
    limit, offset = pagination(request.args)
    direction = filter_enum(request.args, "direction", config.DIRECTIONS)
    urgency = filter_enum(request.args, "urgency", config.URGENCIES)
    status = filter_enum(request.args, "status", config.REFERRAL_STATUSES)
    patient_id = request.args.get("patient_id")
    plan_id = request.args.get("plan_id")
    triggering = request.args.get("triggering_assessment_id")

    def match(row):
        if patient_id and row["patient_id"] != patient_id:
            return False
        if plan_id and row["plan_id"] != plan_id:
            return False
        if triggering and row["triggering_assessment_id"] != triggering:
            return False
        if direction and row["direction"] != direction:
            return False
        if urgency and row["urgency"] != urgency:
            return False
        if status and row["status"] != status:
            return False
        return True

    return paginate(ordered(db.referrals, match), limit, offset, serialize.referral)


@bp.post(P + "/referrals/<id>/respond")
def respond_referral(id):
    authenticate([config.ROLE_FRONT_DESK, config.ROLE_OPTOMETRIST])
    b = json_body()
    b.enum_shape_req("response_outcome")                                   # rung 3
    decline_reason = b.str_opt("decline_reason")
    outcome = b.enum_req("response_outcome", config.RESPONSE_OUTCOMES)     # rung 4
    referral = lookup.referral_or_404(id)                                  # rung 11
    # OUTSIDE the clinical write gate (PRD §2.8).
    if referral["status"] != "SENT":                                       # rung 14
        raise ApiError("ERR_INVALID_STATE", "Only a SENT referral may be responded to.")

    responded_at = now_iso()
    referral["status"] = outcome
    referral["response_outcome"] = outcome
    referral["responded_at"] = responded_at
    if outcome == "DECLINED":
        referral["decline_reason"] = decline_reason
    due = parse_instant(referral.get("sla_due_at"))
    referral["sla_breached"] = bool(due is not None and now() > due)
    touch(referral)
    return ok(serialize.referral(referral))


@bp.post(P + "/referrals/<id>/re-refer")
def re_refer(id):
    authenticate([config.ROLE_FRONT_DESK, config.ROLE_OPTOMETRIST])
    b = json_body()
    target = b.str_req("target_provider_name")
    referral = lookup.referral_or_404(id)                                  # rung 11
    lookup.gate_for_patient_id(referral["patient_id"])                     # rung 12
    if referral["status"] != "DECLINED":                                   # rung 14
        raise ApiError("ERR_INVALID_STATE", "Only a DECLINED referral may be re-referred.")

    if referral["attempt_count"] >= config.MAX_REFERRAL_ATTEMPTS:          # rung 33
        # MUTATE-THEN-REJECT: the ABANDONED write commits, then the call fails.
        referral["status"] = "ABANDONED"
        touch(referral)
        raise ApiError("ERR_REFERRAL_ATTEMPT_LIMIT")

    hours = (config.URGENT_REFERRAL_SLA_HOURS if referral["urgency"] == "URGENT"
             else config.ROUTINE_REFERRAL_SLA_HOURS)
    referral["attempt_count"] += 1
    referral["target_provider_name"] = target
    referral["responded_at"] = None
    referral["response_outcome"] = None
    referral["decline_reason"] = None
    referral["status"] = "SENT"
    referral["sla_due_at"] = iso3(now() + timedelta(hours=hours))
    referral["sla_breached"] = False
    touch(referral)
    return ok(serialize.referral(referral))
