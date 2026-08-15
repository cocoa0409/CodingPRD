"""Insurance policy and spoilage claim endpoints (PRD 3.8)."""
from decimal import Decimal

from flask import Blueprint

import db
from errors import ApiError
from middleware import ALL_ROLES, require_roles
from response import ok, ok_list
from services import core
from util import (as_dt, as_enum, as_int, as_str, body, paginate_sorted,
                  present, query_enum, query_str, required, resolve_body_fk,
                  resolve_path)

bp = Blueprint("insurance", __name__)


@bp.route("/grain/policies", methods=["POST"])
def create_policy():
    require_roles("FarmOwner")
    data = body()
    crop = as_enum(required(data, "crop"), "crop", core.CROPS)
    limit = as_int(required(data, "coverage_limit_cents"), "coverage_limit_cents")
    if limit <= 0:
        raise ApiError("ERR_VALIDATION", 400, "coverage_limit_cents must be > 0")
    deductible = as_int(required(data, "deductible_cents"), "deductible_cents")
    if deductible < 0:
        raise ApiError("ERR_VALIDATION", 400, "deductible_cents must be >= 0")
    clause = as_enum(required(data, "valuation_clause"), "valuation_clause",
                     core.VALUATION_CLAUSES)
    start = as_dt(required(data, "period_start"), "period_start")
    end = as_dt(required(data, "period_end"), "period_end")
    if end <= start:
        raise ApiError("ERR_VALIDATION", 400,
                       "period_end must be strictly after period_start")

    rec = core.new_common()
    rec.update({
        "crop": crop,
        "coverage_limit_cents": limit,
        "deductible_cents": deductible,
        "valuation_clause": clause,
        "period_start": start,
        "period_end": end,
        "remaining_coverage_cents": limit,
        "status": "ACTIVE",
    })
    db.policies[rec["id"]] = rec
    return ok(core.policy_view(rec), 201)


@bp.route("/grain/claims", methods=["POST"])
def create_claim():
    require_roles("SiteManager")
    data = body()
    # existence (4): body FKs left to right: policy_id, spoilage_alert_id
    policy = resolve_body_fk(db.policies, data, "policy_id", "policy")
    alert = resolve_body_fk(db.alerts, data, "spoilage_alert_id", "spoilage alert")
    # shape (6)
    as_str(required(data, "policy_id"), "policy_id")
    as_str(required(data, "spoilage_alert_id"), "spoilage_alert_id")
    # temporal (23): alert.closed_at within the policy period, both inclusive.
    # An OPEN alert has no closed_at; the period check cannot bind and the
    # CONFIRMED_LOSS requirement (27) reports it instead.
    if alert["closed_at"] is not None:
        if not (policy["period_start"] <= alert["closed_at"] <= policy["period_end"]):
            raise ApiError("ERR_LOSS_OUTSIDE_PERIOD", 409,
                           "alert closed_at is outside the policy coverage period")
    # crop consistency (25): policy crop vs the crop of the bin that raised it
    bin_rec = db.bins.get(alert["bin_id"])
    if bin_rec is not None and policy["crop"] != bin_rec["crop"]:
        raise ApiError("ERR_CROP_MIX", 409,
                       "policy crop must equal the alert bin's crop")
    # referential (27)
    if alert["status"] != "CONFIRMED_LOSS":
        raise ApiError("ERR_ALERT_LOSS_NOT_CONFIRMED", 409,
                       "referenced alert is not CONFIRMED_LOSS")
    # referential (28)
    if policy["status"] != "ACTIVE":
        raise ApiError("ERR_POLICY_NOT_ACTIVE", 409, "policy is not ACTIVE")

    rec = core.new_common()
    rec.update({
        "policy_id": policy["id"],
        "spoilage_alert_id": alert["id"],
        "loss_bu": alert["loss_bu"],
        "unit_value_cents": None,
        "gross_indemnity_cents": None,
        "indemnity_cents": None,
        "status": "SUBMITTED",
    })
    db.claims[rec["id"]] = rec
    return ok(core.claim_view(rec), 201)


@bp.route("/grain/claims/<cid>", methods=["GET"])
def get_claim(cid):
    require_roles(*ALL_ROLES)
    return ok(core.claim_view(resolve_path(db.claims, cid, "claim")))


@bp.route("/grain/claims", methods=["GET"])
def list_claims():
    require_roles(*ALL_ROLES)
    f_policy = query_str("policy_id")
    f_alert = query_str("spoilage_alert_id")
    f_status = query_enum("status", core.CLAIM_STATUSES)
    items = list(db.claims.values())
    if f_policy is not None:
        items = [c for c in items if c["policy_id"] == f_policy]
    if f_alert is not None:
        items = [c for c in items if c["spoilage_alert_id"] == f_alert]
    if f_status is not None:
        items = [c for c in items if c["status"] == f_status]
    page, total, limit, offset = paginate_sorted(items)
    return ok_list([core.claim_view(c) for c in page], total, limit, offset)


@bp.route("/grain/claims/<cid>/approve", methods=["POST"])
def approve_claim(cid):
    require_roles("FarmOwner")
    # existence (4)
    claim = resolve_path(db.claims, cid, "claim")
    policy = db.policies.get(claim["policy_id"])
    data = body()

    # Determine whether spot pricing applies: always under a SPOT clause, and
    # under CONTRACT_AVG when the valuation pool is empty — PRD 3.8: "when the
    # pool is empty the clause falls back to SPOT behavior and the spot price
    # input is then required". The pool is well-defined here because claim
    # creation guaranteed a CONFIRMED_LOSS alert (closed_at is set).
    pool = None
    if policy is not None and policy["valuation_clause"] == "CONTRACT_AVG":
        alert = db.alerts[claim["spoilage_alert_id"]]
        pool = [c for c in db.contracts.values()
                if c["crop"] == policy["crop"]
                and c["status"] in ("OPEN", "DELIVERING")
                and c["window_start"] <= alert["closed_at"] <= c["window_end"]]
    use_spot = (policy is not None and policy["valuation_clause"] == "SPOT") \
        or (pool is not None and not pool)

    # shape (6): conditional spot price — required when spot pricing applies,
    # forbidden under CONTRACT_AVG with a non-empty pool — precedes the state
    # check.
    spot = None
    if use_spot:
        if not present(data, "spot_price_cents_per_bu"):
            raise ApiError("ERR_VALIDATION", 400,
                           "spot_price_cents_per_bu is required for SPOT policies")
        spot = as_int(data["spot_price_cents_per_bu"], "spot_price_cents_per_bu")
    else:
        if present(data, "spot_price_cents_per_bu"):
            raise ApiError("ERR_VALIDATION", 400,
                           "spot_price_cents_per_bu is forbidden for CONTRACT_AVG policies")
    # state (12)
    if claim["status"] != "SUBMITTED":
        raise ApiError("ERR_CLAIM_NOT_SUBMITTED", 409, "claim is not SUBMITTED")

    # indemnity valuation per the policy's clause
    if use_spot:
        unit_value = Decimal(spot)
    else:
        weighted = sum(Decimal(c["contract_unit_price_cents"]) * c["contracted_bu"]
                       for c in pool)
        total_bu = sum(c["contracted_bu"] for c in pool)
        unit_value = core.q2(weighted / total_bu)

    gross = core.q0(claim["loss_bu"] * unit_value)
    # the coverage cap binds BEFORE the deductible is subtracted
    indemnity = max(0, min(gross, policy["remaining_coverage_cents"])
                    - policy["deductible_cents"])

    claim["unit_value_cents"] = unit_value
    claim["gross_indemnity_cents"] = gross
    claim["indemnity_cents"] = indemnity
    claim["status"] = "APPROVED"
    core.touch(claim)

    policy["remaining_coverage_cents"] -= indemnity
    core.touch(policy)
    return ok(core.claim_view(claim))
