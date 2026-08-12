"""Retention risk snapshot endpoints (PRD 3.9)."""

from flask import Blueprint, request

import domain as D
from db import store, new_point_record, bump
from errors import (
    ApiError, ERR_CASE_NOT_FOUND, ERR_SNAPSHOT_NOT_FOUND, ERR_INVALID_STATE,
)
from middleware import get_context, require_role
from response import success_object, paginate

bp = Blueprint("snapshots", __name__)


@bp.route("/onboarding/retention-snapshots", methods=["POST"])
def create_snapshot():
    _uid, role = get_context()
    require_role(role, ["OnboardingDirector"])
    body = D.get_body()
    case_id = D.req_str(body, "onboarding_case_id")
    variant = D.req_enum(body, "variant", D.SNAPSHOT_VARIANTS)
    case = store.cases.get(case_id)
    if case is None:
        raise ApiError(ERR_CASE_NOT_FOUND, 404, "OnboardingCase not found")
    if D.executed_offer_of_case(case_id) is None:
        raise ApiError(ERR_INVALID_STATE, 409,
                       "The case must have an EXECUTED offer before a snapshot")
    computed = D.compute_risk(case, variant)
    rec = new_point_record()
    rec.update({
        "onboarding_case_id": case_id,
        "variant": variant,
        "milestone_risk": computed["milestone_risk"],
        "panel_risk": computed["panel_risk"],
        "sentiment_risk": computed["sentiment_risk"],
        "schedule_risk": computed["schedule_risk"],
        "score": computed["score"],
        "risk_band": computed["risk_band"],
    })
    store.snapshots[rec["id"]] = rec
    case["latest_risk_score"] = computed["score"]
    case["latest_risk_band"] = computed["risk_band"]
    case["at_risk"] = computed["risk_band"] in ("HIGH", "CRITICAL")
    bump(case)
    return success_object(D.serialize_snapshot(rec), status=201)


@bp.route("/onboarding/retention-snapshots/<sid>", methods=["GET"])
def get_snapshot(sid):
    get_context()
    snapshot = store.snapshots.get(sid)
    if snapshot is None:
        raise ApiError(ERR_SNAPSHOT_NOT_FOUND, 404, "RetentionRiskSnapshot not found")
    return success_object(D.serialize_snapshot(snapshot))


@bp.route("/onboarding/retention-snapshots", methods=["GET"])
def list_snapshots():
    get_context()
    case_id = request.args.get("onboarding_case_id")
    variant = request.args.get("variant")
    records = sorted(store.snapshots.values(), key=lambda r: r["_seq"])
    if case_id is not None:
        records = [r for r in records if r["onboarding_case_id"] == case_id]
    if variant is not None:
        records = [r for r in records if r["variant"] == variant]
    return paginate([D.serialize_snapshot(r) for r in records], request.args)
