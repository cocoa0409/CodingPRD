"""Rule packs, fraud rules and risk models (PRD 3.2 / 3.3 / 3.9)."""

from flask import Blueprint, g

import calc
import services as svc
import validators as v
from db import db, touch
from errors import ApiError
from middleware import roles
from response import created, ok, serialize
from routes._common import paged

bp = Blueprint("policy", __name__, url_prefix="/fraud")

PACK_READERS = ("PolicyEngineer", "ReviewLead", "RiskAnalyst", "PlatformAdmin")
MODEL_READERS = ("PolicyEngineer", "ReviewLead", "PlatformAdmin")


# =============================================================== RulePack
@bp.route("/rule-packs", methods=["POST"])
@roles("PolicyEngineer")
def create_rule_pack():
    payload = v.body()
    version_label = v.as_str(payload, "version_label")
    blend_mode = v.as_enum(payload, "blend_mode", calc.BLEND_MODES)
    rule_weight = v.as_decimal(payload, "rule_weight", minimum=0, maximum=1)
    model_weight = v.as_decimal(payload, "model_weight", minimum=0, maximum=1)
    review_floor_score = v.as_decimal(
        payload, "review_floor_score", minimum=0, maximum=200
    )
    decline_floor_score = v.as_decimal(
        payload, "decline_floor_score", minimum=0, maximum=200
    )
    effective_from = v.as_datetime(payload, "effective_from")
    effective_until = v.as_datetime(payload, "effective_until")

    # priority 70, then 84, then 85 (PRD 3.2)
    if effective_until <= effective_from:
        raise ApiError("ERR_INVALID_WINDOW")
    if calc.rh(rule_weight + model_weight, 2) != calc.dec("1.00"):
        raise ApiError("ERR_WEIGHTS_NOT_NORMALIZED")
    if review_floor_score >= decline_floor_score:
        raise ApiError("ERR_INVALID_SCORE_BANDS")

    row = svc.new_row(
        version_label=version_label,
        blend_mode=blend_mode,
        rule_weight=rule_weight,
        model_weight=model_weight,
        review_floor_score=review_floor_score,
        decline_floor_score=decline_floor_score,
        effective_from=effective_from,
        effective_until=effective_until,
        status="DRAFT",
        created_by_user_id=g.user_id,
        activated_by_user_id=None,
        activated_at=None,
        retired_at=None,
        rule_count=0,
    )
    db.rule_packs[row["id"]] = row
    return created(serialize(row))


@bp.route("/rule-packs", methods=["GET"])
@roles(*PACK_READERS)
def list_rule_packs():
    return paged(
        list(db.rule_packs.values()),
        [
            ("status", v.query_enum("status", calc.RULE_PACK_STATUSES)),
            ("blend_mode", v.query_enum("blend_mode", calc.BLEND_MODES)),
        ],
    )


@bp.route("/rule-packs/<pid>", methods=["GET"])
@roles(*PACK_READERS)
def read_rule_pack(pid):
    return ok(serialize(v.lookup(db.rule_packs, pid, "ERR_RULE_PACK_NOT_FOUND")))


@bp.route("/rule-packs/<pid>/activate", methods=["POST"])
@roles("PolicyEngineer")
def activate_rule_pack(pid):
    pack = v.lookup(db.rule_packs, pid, "ERR_RULE_PACK_NOT_FOUND")
    # PRD 3.2: 46 -> 56 -> 75 -> 78 -> 84 -> 85
    if pack["status"] != "DRAFT":
        raise ApiError("ERR_RULE_PACK_NOT_DRAFT")
    if g.user_id is not None and g.user_id == pack["created_by_user_id"]:
        raise ApiError("ERR_ACTIVATION_SEGREGATION_VIOLATION")
    if svc.rule_pack_window_collision(pack):
        raise ApiError("ERR_RULE_PACK_WINDOW_OVERLAP")
    if pack["rule_count"] == 0:
        raise ApiError("ERR_RULE_PACK_EMPTY")
    if calc.rh(pack["rule_weight"] + pack["model_weight"], 2) != calc.dec("1.00"):
        raise ApiError("ERR_WEIGHTS_NOT_NORMALIZED")
    if pack["review_floor_score"] >= pack["decline_floor_score"]:
        raise ApiError("ERR_INVALID_SCORE_BANDS")

    svc.activate_rule_pack(pack, g.user_id)
    return ok(serialize(pack))


@bp.route("/rule-packs/<pid>/performance", methods=["GET"])
@roles("PolicyEngineer", "ReviewLead")
def rule_pack_performance(pid):
    pack = v.lookup(db.rule_packs, pid, "ERR_RULE_PACK_NOT_FOUND")
    cohort = v.query_enum("cohort", calc.COHORTS) or "DECISION_COHORT"
    return ok(svc.performance_report(pack["id"], cohort))


# ============================================================== FraudRule
@bp.route("/rule-packs/<pid>/rules", methods=["POST"])
@roles("PolicyEngineer")
def create_fraud_rule(pid):
    # priority 12: the parent pack in the path resolves first
    pack = v.lookup(db.rule_packs, pid, "ERR_RULE_PACK_NOT_FOUND")
    payload = v.body()
    code = v.as_enum(payload, "code", calc.RULE_CODES)
    signal_family = v.as_enum(payload, "signal_family", calc.RULE_SIGNAL_FAMILIES)
    points = v.as_int(payload, "points", minimum=0, maximum=100)
    evaluation_order = v.as_int(payload, "evaluation_order", minimum=1)
    hard_decline = v.as_bool(payload, "hard_decline", required=False, default=False)

    if pack["status"] != "DRAFT":
        raise ApiError("ERR_RULE_PACK_NOT_DRAFT")
    if calc.RULE_CODE_FAMILY[code] != signal_family:
        raise ApiError("ERR_RULE_FAMILY_MISMATCH")
    for other in db.fraud_rules.values():
        if other["rule_pack_id"] == pack["id"] and other["code"] == code:
            raise ApiError("ERR_DUPLICATE_RULE_CODE")

    row = svc.new_immutable_row(
        rule_pack_id=pack["id"],
        code=code,
        signal_family=signal_family,
        points=points,
        hard_decline=hard_decline,
        evaluation_order=evaluation_order,
    )
    db.fraud_rules[row["id"]] = row
    pack["rule_count"] += 1
    touch(pack)
    return created(serialize(row))


@bp.route("/rule-packs/<pid>/rules", methods=["GET"])
@roles(*PACK_READERS)
def list_fraud_rules(pid):
    pack = v.lookup(db.rule_packs, pid, "ERR_RULE_PACK_NOT_FOUND")
    rows = [r for r in db.fraud_rules.values() if r["rule_pack_id"] == pack["id"]]
    return paged(
        rows,
        [("signal_family", v.query_enum("signal_family", calc.RULE_SIGNAL_FAMILIES))],
        order="rules",
    )


@bp.route("/rules/<rid>", methods=["GET"])
@roles(*PACK_READERS)
def read_fraud_rule(rid):
    return ok(serialize(v.lookup(db.fraud_rules, rid, "ERR_RULE_NOT_FOUND")))


# ============================================================== RiskModel
@bp.route("/risk-models", methods=["POST"])
@roles("PolicyEngineer")
def create_risk_model():
    payload = v.body()
    model_version_label = v.as_str(payload, "model_version_label")
    calibration_intercept = v.as_decimal(
        payload, "calibration_intercept", minimum=-1, maximum=1
    )
    calibration_slope = v.as_decimal(
        payload, "calibration_slope", exclusive_minimum=0, maximum=4
    )
    cutoff = v.as_datetime(
        payload, "trained_on_chargeback_cutoff_at", required=False, default=None
    )
    # priority 73
    if cutoff is not None and cutoff > db.now():
        raise ApiError("ERR_TRAINING_CUTOFF_IN_FUTURE")

    row = svc.new_row(
        model_version_label=model_version_label,
        calibration_intercept=calibration_intercept,
        calibration_slope=calibration_slope,
        trained_on_chargeback_cutoff_at=cutoff,
        status="DRAFT",
        training_segment_counts=None,
        promoted_at=None,
        retired_at=None,
        scored_assessment_count=0,
    )
    db.risk_models[row["id"]] = row
    return created(serialize(row))


@bp.route("/risk-models", methods=["GET"])
@roles(*MODEL_READERS)
def list_risk_models():
    return paged(
        list(db.risk_models.values()),
        [("status", v.query_enum("status", calc.MODEL_STATUSES))],
    )


@bp.route("/risk-models/<mid>", methods=["GET"])
@roles(*MODEL_READERS)
def read_risk_model(mid):
    return ok(serialize(v.lookup(db.risk_models, mid, "ERR_RISK_MODEL_NOT_FOUND")))


@bp.route("/risk-models/<mid>/lifecycle", methods=["POST"])
@roles("PolicyEngineer")
def risk_model_lifecycle(mid):
    model = v.lookup(db.risk_models, mid, "ERR_RISK_MODEL_NOT_FOUND")
    payload = v.body()
    action = v.as_enum(payload, "action", calc.MODEL_ACTIONS)
    status = model["status"]
    cutoff = model["trained_on_chargeback_cutoff_at"]

    if action == "START_TRAINING":
        # priority 45 then priority 83
        if status != "DRAFT" or cutoff is None:
            raise ApiError("ERR_MODEL_TRANSITION_INVALID")
        counts = svc.training_segment_counts(cutoff)
        for segment in calc.REQUIRED_TRAINING_SEGMENTS:
            if counts[segment] < calc.MIN_SAMPLES_PER_SEGMENT:
                raise ApiError("ERR_TRAINING_SEGMENT_UNDERFILLED")
        model["status"] = "TRAINING"
        model["training_segment_counts"] = counts
    elif action == "PUBLISH_SHADOW":
        if status == "DRAFT" and cutoff is None:
            model["status"] = "SHADOW"
        elif status == "TRAINING":
            model["status"] = "SHADOW"
        else:
            raise ApiError("ERR_MODEL_TRANSITION_INVALID")
    elif action == "REJECT":
        if status != "SHADOW":
            raise ApiError("ERR_MODEL_TRANSITION_INVALID")
        model["status"] = "DRAFT"
        model["training_segment_counts"] = None
    elif action == "PROMOTE":
        if status != "SHADOW":
            raise ApiError("ERR_MODEL_TRANSITION_INVALID")
        svc.promote_model(model)
        return ok(serialize(model))
    else:  # RETIRE
        if status != "ACTIVE":
            raise ApiError("ERR_MODEL_TRANSITION_INVALID")
        model["status"] = "RETIRED"
        model["retired_at"] = db.now()

    touch(model)
    return ok(serialize(model))
