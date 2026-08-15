"""RuleSet endpoints."""

from flask import Blueprint, request

import db
import errors
import middleware
import response
from services import domain

bp = Blueprint("rule_sets", __name__)

VALID_SCOPES = {"GLOBAL", "DEBIT_CARD", "CREDIT_CARD"}
REQUIRED_CHANNEL_KEYS = {"CHIP", "CONTACTLESS", "CNP", "ATM"}


def _validate_ruleset_fields(body, partial: bool = False):
    """Validate ruleset payload. Returns dict of validated fields."""
    out = {}
    if not partial or "scope" in body:
        scope = body.get("scope")
        if scope not in VALID_SCOPES:
            raise errors.err_invalid_request("scope must be GLOBAL, DEBIT_CARD, or CREDIT_CARD")
        out["scope"] = scope

    def _int_field(name, required=not partial):
        if name in body:
            v = body[name]
            if not isinstance(v, int) or isinstance(v, bool):
                raise errors.err_invalid_request(f"{name} must be an integer")
            out[name] = v
        elif required:
            raise errors.err_invalid_request(f"{name} is required")

    _int_field("base_score")
    _int_field("review_threshold")
    _int_field("decline_threshold")
    _int_field("cross_border_weight")
    _int_field("watch_weight")
    _int_field("compromised_weight")

    if "high_risk_multiplier" in body:
        v = body["high_risk_multiplier"]
        if not isinstance(v, (int, float)) or isinstance(v, bool):
            raise errors.err_invalid_request("high_risk_multiplier must be a number")
        out["high_risk_multiplier"] = v
    elif not partial:
        raise errors.err_invalid_request("high_risk_multiplier is required")

    if "amount_tiers" in body or not partial:
        tiers = body.get("amount_tiers")
        if not isinstance(tiers, list):
            raise errors.err_invalid_request("amount_tiers must be an array")
        seen = set()
        for t in tiers:
            if not isinstance(t, dict):
                raise errors.err_invalid_request("amount_tiers entries must be objects")
            m = t.get("min_amount_cents")
            p = t.get("points")
            if not isinstance(m, int) or isinstance(m, bool) or not isinstance(p, int) or isinstance(p, bool):
                raise errors.err_invalid_request("amount_tiers entries require integer min_amount_cents and points")
            if m in seen:
                raise errors.err_invalid_request("amount_tiers must not repeat a min_amount_cents value")
            seen.add(m)
        out["amount_tiers"] = tiers

    if "channel_weights" in body or not partial:
        cw = body.get("channel_weights")
        if not isinstance(cw, dict):
            raise errors.err_invalid_request("channel_weights must be an object")
        if set(cw.keys()) != REQUIRED_CHANNEL_KEYS:
            raise errors.err_invalid_request("channel_weights must contain CHIP, CONTACTLESS, CNP, ATM")
        for k, v in cw.items():
            if not isinstance(v, int) or isinstance(v, bool):
                raise errors.err_invalid_request("channel_weights values must be integers")
        out["channel_weights"] = cw

    if "high_risk_countries" in body:
        hrc = body["high_risk_countries"]
        if not isinstance(hrc, list) or not all(isinstance(x, str) for x in hrc):
            raise errors.err_invalid_request("high_risk_countries must be an array of strings")
        out["high_risk_countries"] = hrc
    elif not partial:
        out["high_risk_countries"] = []

    # threshold order (when both are present after merging)
    rt = out.get("review_threshold")
    dt = out.get("decline_threshold")
    if rt is not None and dt is not None and rt >= dt:
        raise errors.err_threshold_order_invalid()

    return out


@bp.route("/fraudops/rule-sets", methods=["POST"])
def create_ruleset():
    user_id, _ = middleware.require_role("FraudAnalyst", "FraudOpsManager")
    body = request.get_json(silent=True) or {}
    fields = _validate_ruleset_fields(body, partial=False)
    rec = middleware.stamp_new(
        {
            "scope": fields["scope"],
            "base_score": fields["base_score"],
            "review_threshold": fields["review_threshold"],
            "decline_threshold": fields["decline_threshold"],
            "amount_tiers": fields["amount_tiers"],
            "channel_weights": fields["channel_weights"],
            "cross_border_weight": fields["cross_border_weight"],
            "high_risk_multiplier": fields["high_risk_multiplier"],
            "watch_weight": fields["watch_weight"],
            "compromised_weight": fields["compromised_weight"],
            "high_risk_countries": fields["high_risk_countries"],
            "ruleset_status": "DRAFT",
            "created_by_user_id": user_id,
            "activated_by_user_id": None,
        }
    )
    db.rule_sets[rec["id"]] = rec
    return response.success(domain.ser_ruleset(rec), status_code=201)


@bp.route("/fraudops/rule-sets", methods=["GET"])
def list_rulesets():
    middleware.require_role("FraudAnalyst", "FraudOpsManager")
    args = request.args
    scope = args.get("scope")
    status = args.get("ruleset_status")
    items = sorted(db.rule_sets.values(), key=lambda r: (r["created_at"], r["id"]))
    if scope:
        items = [r for r in items if r["scope"] == scope]
    if status:
        items = [r for r in items if r["ruleset_status"] == status]
    limit, offset = domain.parse_pagination_args(args)
    sliced, pg = domain.paginate(items, limit, offset)
    return response.success([domain.ser_ruleset(r) for r in sliced], pagination=pg)


@bp.route("/fraudops/rule-sets/<rid>", methods=["GET"])
def get_ruleset(rid):
    middleware.require_role("FraudAnalyst", "FraudOpsManager")
    r = db.rule_sets.get(rid)
    if not r:
        raise errors.err_not_found("RuleSet not found")
    return response.success(domain.ser_ruleset(r))


@bp.route("/fraudops/rule-sets/<rid>", methods=["PUT"])
def update_ruleset(rid):
    middleware.require_role("FraudAnalyst", "FraudOpsManager")
    r = db.rule_sets.get(rid)
    if not r:
        raise errors.err_not_found("RuleSet not found")
    body = request.get_json(silent=True) or {}

    # OCC: expected_ruleset_version must be present and match
    expected = body.get("expected_ruleset_version")
    if expected is None:
        raise errors.err_invalid_request("expected_ruleset_version is required")
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise errors.err_invalid_request("expected_ruleset_version must be an integer")
    if expected != r["version"]:
        raise errors.err_stale_version()

    # state: only DRAFT may be tuned
    if r["ruleset_status"] != "DRAFT":
        raise errors.err_invalid_state("Only DRAFT rulesets may be tuned")

    # Validate provided fields (partial). Merge to check threshold order.
    fields = _validate_ruleset_fields(body, partial=True)
    merged_rt = fields.get("review_threshold", r["review_threshold"])
    merged_dt = fields.get("decline_threshold", r["decline_threshold"])
    if merged_rt >= merged_dt:
        raise errors.err_threshold_order_invalid()

    for k, v in fields.items():
        r[k] = v
    middleware.touch(r)
    return response.success(domain.ser_ruleset(r))


@bp.route("/fraudops/rule-sets/<rid>/activate", methods=["POST"])
def activate_ruleset(rid):
    user_id, _ = middleware.require_role("FraudOpsManager")
    r = db.rule_sets.get(rid)
    if not r:
        raise errors.err_not_found("RuleSet not found")
    if r["ruleset_status"] != "DRAFT":
        raise errors.err_invalid_state("Only DRAFT rulesets may be activated")
    if r["created_by_user_id"] == user_id:
        raise errors.err_segregation_of_duties("Activator must differ from creator")

    # supersede the currently ACTIVE ruleset with the same scope
    for other in db.rule_sets.values():
        if other["id"] != r["id"] and other["scope"] == r["scope"] and other["ruleset_status"] == "ACTIVE":
            other["ruleset_status"] = "RETIRED"
            middleware.touch(other)

    r["ruleset_status"] = "ACTIVE"
    r["activated_by_user_id"] = user_id
    middleware.touch(r)
    return response.success(domain.ser_ruleset(r))


@bp.route("/fraudops/rule-sets/<rid>/retire", methods=["POST"])
def retire_ruleset(rid):
    middleware.require_role("FraudOpsManager")
    r = db.rule_sets.get(rid)
    if not r:
        raise errors.err_not_found("RuleSet not found")
    if r["ruleset_status"] not in ("DRAFT", "ACTIVE"):
        raise errors.err_invalid_state("Only DRAFT or ACTIVE rulesets may be retired")
    r["ruleset_status"] = "RETIRED"
    middleware.touch(r)
    return response.success(domain.ser_ruleset(r))


@bp.route("/fraudops/rule-sets/<rid>/metrics", methods=["GET"])
def ruleset_metrics(rid):
    middleware.require_role("FraudAnalyst", "FraudOpsManager")
    r = db.rule_sets.get(rid)
    if not r:
        raise errors.err_not_found("RuleSet not found")

    population = [t for t in db.auth_transactions.values() if t["ruleset_id"] == rid]
    scored_count = len(population)
    approved = [t for t in population if t["decision"] == "APPROVE"]
    review = [t for t in population if t["decision"] == "REVIEW"]
    declined = [t for t in population if t["decision"] == "DECLINE"]
    confirmed_fraud = [t for t in population if t["final_disposition"] == "CONFIRMED_FRAUD"]
    confirmed_legit = [t for t in population if t["final_disposition"] == "CONFIRMED_LEGIT"]

    from decimal import Decimal, ROUND_HALF_UP

    def _rate_bp(numer, denom):
        if denom == 0:
            return 0
        return int((Decimal(10000) * Decimal(numer) / Decimal(denom)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))

    review_disposed = [t for t in review if t["final_disposition"] != "UNDISPOSED"]
    review_legit = [t for t in review if t["final_disposition"] == "CONFIRMED_LEGIT"]
    fp_review = _rate_bp(len(review_legit), len(review_disposed))

    decline_disposed = [t for t in declined if t["final_disposition"] != "UNDISPOSED"]
    decline_legit = [t for t in declined if t["final_disposition"] == "CONFIRMED_LEGIT"]
    fp_decline = _rate_bp(len(decline_legit), len(decline_disposed))

    # missed declines under current — shadow rescore each txn
    missed = 0
    for t in population:
        domain.apply_shadow(t)
        if t["decision"] != "DECLINE" and t.get("shadow_decision") == "DECLINE":
            missed += 1

    # gross confirmed loss
    pop_ids = {t["id"] for t in population}
    gross = 0
    for l in db.loss_entries.values():
        if l["loss_status"] not in ("FINALIZED", "PARTIALLY_RECOVERED", "FULLY_RECOVERED", "WRITTEN_OFF"):
            continue
        if l["final_amount_cents"] is None:
            continue
        if any(tid in pop_ids for tid in l["transaction_ids"]):
            gross += l["final_amount_cents"]

    return response.success(
        {
            "scored_count": scored_count,
            "approved_count": len(approved),
            "review_count": len(review),
            "declined_count": len(declined),
            "confirmed_fraud_count": len(confirmed_fraud),
            "confirmed_legit_count": len(confirmed_legit),
            "fp_rate_review_basis_bp": fp_review,
            "fp_rate_decline_basis_bp": fp_decline,
            "missed_declines_under_current": missed,
            "gross_confirmed_loss_cents": gross,
        }
    )
