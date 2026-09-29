"""Consent policy and match threshold governance endpoints (PRD 3.3)."""
from decimal import Decimal

from flask import Blueprint, request

from db import commit, create, db, parse_iso, snapshot, touch
from errors import ApiError
from middleware import HIE_ADMIN, PRIVACY_OFFICER, authenticate
from response import entity, entity_created, paginate, pagination
from services import repo
from services.matching import SCORE_FIELDS
from services.precision import dec, out
from validate import (
    body,
    before,
    opt_bool,
    opt_dt,
    opt_enum_list,
    req_dt,
    req_enum,
    req_num,
    req_str,
)

bp = Blueprint("governance", __name__)

SENSITIVE_CATEGORIES = (
    "BEHAVIORAL_HEALTH",
    "SUD",
    "HIV",
    "REPRODUCTIVE",
    "GENETIC",
)
POLICY_MODELS = ("OPT_IN", "OPT_OUT")
SCORE_VARIANT_MODES = ("DETERMINISTIC_FIRST", "PROBABILISTIC_ONLY")
WEIGHT_SUM_TOLERANCE = Decimal("0.0001")


def _overlaps(start_a, end_a, start_b, end_b):
    """Half-open interval overlap; a null upper bound means open-ended."""
    if end_a is not None and end_a <= start_b:
        return False
    if end_b is not None and end_b <= start_a:
        return False
    return True


def _assert_no_overlap(effective_from, effective_until, statuses, skip_id=None):
    for policy in repo.all_rows("consent_policies"):
        if policy["status"] not in statuses:
            continue
        if skip_id is not None and policy["id"] == skip_id:
            continue
        other_from = parse_iso(policy["effective_from"])
        other_until = (
            parse_iso(policy["effective_until"]) if policy["effective_until"] else None
        )
        if _overlaps(effective_from, effective_until, other_from, other_until):
            raise ApiError("ERR_CONSENT_POLICY_INTERVAL_OVERLAP")


@bp.route("/hie/consent-policies", methods=["POST"])
def draft_policy():
    actor = authenticate((PRIVACY_OFFICER,))
    payload = body()
    policy_version = req_str(payload, "policy_version")
    model = req_enum(payload, "model", POLICY_MODELS)
    segmented = opt_enum_list(
        payload, "sensitive_categories_segmented", SENSITIVE_CATEGORIES, []
    )
    default_share = opt_bool(payload, "default_share_for_treatment", True)
    from_raw, from_dt = req_dt(payload, "effective_from")
    until_raw, until_dt = opt_dt(payload, "effective_until")
    before(from_dt, until_dt, "effective_until must be strictly after effective_from.")

    _assert_no_overlap(from_dt, until_dt, ("DRAFT", "ACTIVE"))

    row = create(
        db.consent_policies,
        "ConsentPolicy",
        {
            "policy_version": policy_version,
            "model": model,
            "sensitive_categories_segmented": list(segmented),
            "default_share_for_treatment": default_share,
            "effective_from": from_raw,
            "effective_until": until_raw,
            "status": "DRAFT",
            "activated_by_user_id": None,
            "directive_count": 0,
        },
    )
    return entity_created(row)


@bp.route("/hie/consent-policies/<policy_id>/activation", methods=["POST"])
def activate_policy(policy_id):
    actor = authenticate((PRIVACY_OFFICER,))
    body()
    policy = repo.must("consent_policies", policy_id)
    if policy["status"] == "SUPERSEDED":
        raise ApiError("ERR_TERMINAL_STATE")
    if policy["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    from_dt = parse_iso(policy["effective_from"])
    until_dt = parse_iso(policy["effective_until"]) if policy["effective_until"] else None
    _assert_no_overlap(from_dt, until_dt, ("ACTIVE",), skip_id=policy["id"])

    policy["status"] = "ACTIVE"
    policy["activated_by_user_id"] = actor.user_id
    touch(policy)

    for other in repo.where("consent_policies", status="ACTIVE"):
        if other["id"] == policy["id"]:
            continue
        if not other["effective_until"]:
            continue
        other_until = parse_iso(other["effective_until"])
        if other_until is not None and other_until <= from_dt:
            snap = snapshot(other)
            other["status"] = "SUPERSEDED"
            commit(other, snap)
    return entity(policy)


@bp.route("/hie/consent-policies/<policy_id>", methods=["GET"])
def read_policy(policy_id):
    authenticate((PRIVACY_OFFICER, HIE_ADMIN))
    return entity(repo.must("consent_policies", policy_id))


@bp.route("/hie/consent-policies", methods=["GET"])
def list_policies():
    authenticate((PRIVACY_OFFICER, HIE_ADMIN))
    limit, offset = pagination()
    rows = repo.all_rows("consent_policies")
    status = request.args.get("status")
    model = request.args.get("model")
    if status:
        rows = [r for r in rows if r["status"] == status]
    if model:
        rows = [r for r in rows if r["model"] == model]
    return paginate(rows, limit, offset)


@bp.route("/hie/match-threshold-configs", methods=["POST"])
def draft_config():
    actor = authenticate((PRIVACY_OFFICER,))
    payload = body()
    label = req_str(payload, "config_label")
    auto_link = req_num(payload, "auto_link_threshold", minimum=0, maximum=1)
    review_lower = req_num(payload, "review_lower_bound", minimum=0, maximum=1)
    mode = req_enum(payload, "score_variant_mode", SCORE_VARIANT_MODES)
    weights = {}
    for field in SCORE_FIELDS:
        weights["weight_" + field] = req_num(
            payload, "weight_" + field, minimum=0, maximum=1
        )
    partial = req_num(payload, "partial_credit_factor", minimum=0, maximum=1)

    total = sum((dec(weights["weight_" + f]) for f in SCORE_FIELDS), Decimal(0))
    if abs(total - Decimal(1)) > WEIGHT_SUM_TOLERANCE:
        raise ApiError("ERR_THRESHOLD_CONFIG_INVALID")
    if not dec(auto_link) > dec(review_lower):
        raise ApiError("ERR_THRESHOLD_CONFIG_INVALID")
    if not (Decimal(0) < dec(partial) < Decimal(1)):
        raise ApiError("ERR_THRESHOLD_CONFIG_INVALID")

    fields = {
        "config_label": label,
        "auto_link_threshold": out(dec(auto_link)),
        "review_lower_bound": out(dec(review_lower)),
        "score_variant_mode": mode,
        "partial_credit_factor": out(dec(partial)),
        "status": "DRAFT",
        "tuned_by_user_id": actor.user_id,
        "activated_by_user_id": None,
        "scored_link_count": 0,
    }
    for field in SCORE_FIELDS:
        key = "weight_" + field
        fields[key] = out(dec(weights[key]))
    row = create(db.threshold_configs, "MatchThresholdConfig", fields)
    return entity_created(row)


@bp.route("/hie/match-threshold-configs/<config_id>/activation", methods=["POST"])
def activate_config(config_id):
    actor = authenticate((PRIVACY_OFFICER,))
    body()
    config = repo.must("threshold_configs", config_id)
    if config["status"] == "RETIRED":
        raise ApiError("ERR_TERMINAL_STATE")
    if config["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    config["status"] = "ACTIVE"
    config["activated_by_user_id"] = actor.user_id
    touch(config)

    for other in repo.where("threshold_configs", status="ACTIVE"):
        if other["id"] == config["id"]:
            continue
        snap = snapshot(other)
        other["status"] = "RETIRED"
        commit(other, snap)
    return entity(config)


@bp.route("/hie/match-threshold-configs/<config_id>", methods=["GET"])
def read_config(config_id):
    authenticate((PRIVACY_OFFICER, HIE_ADMIN))
    return entity(repo.must("threshold_configs", config_id))


@bp.route("/hie/match-threshold-configs", methods=["GET"])
def list_configs():
    authenticate((PRIVACY_OFFICER, HIE_ADMIN))
    limit, offset = pagination()
    rows = repo.all_rows("threshold_configs")
    status = request.args.get("status")
    mode = request.args.get("score_variant_mode")
    if status:
        rows = [r for r in rows if r["status"] == status]
    if mode:
        rows = [r for r in rows if r["score_variant_mode"] == mode]
    return paginate(rows, limit, offset)
