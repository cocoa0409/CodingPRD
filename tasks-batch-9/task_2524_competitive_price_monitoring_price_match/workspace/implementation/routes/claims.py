"""Price match claim endpoints (PRD 3.8, 3.9)."""
from datetime import timedelta

from flask import Blueprint, request

import clock
import db
from errors import err
from middleware import (ALL_ROLES, COMPLIANCE_OFFICER, STORE_ASSOCIATE,
                        STORE_MANAGER, body, endpoint, enforce_store_scope)
from response import object_response
from routes.common import (FK_COMPETITOR, FK_POLICY, FK_PRODUCT, FK_STORE,
                           filtered, list_page, path_lookup, resolve_fks)
from services import calc, cascades, ledger, serialize
from util import as_dt, as_enum, as_int, as_str, dec, get_required, round_half_up

bp = Blueprint("claims", __name__)

CLAIM_DECISIONS = ("VERIFIED", "REJECTED", "NEEDS_EVIDENCE")


@bp.post("/claims")
@endpoint([STORE_ASSOCIATE, STORE_MANAGER])
def create_claim(user_id, role):
    payload = body()
    fks = resolve_fks(payload, [FK_POLICY, FK_PRODUCT, FK_COMPETITOR, FK_STORE])

    policy = fks["policy_id"]
    if policy is None:
        get_required(payload, "policy_id")
    product = fks["product_id"]
    if product is None:
        get_required(payload, "product_id")
    competitor = fks["competitor_id"]
    if competitor is None:
        get_required(payload, "competitor_id")
    store = fks["store_id"]
    if store is None:
        get_required(payload, "store_id")
    claimed_price_cents = as_int(get_required(payload, "claimed_price_cents"),
                                 "claimed_price_cents", gt=0)
    claimed_observed_at = as_dt(get_required(payload, "claimed_observed_at"),
                                "claimed_observed_at")
    competitor_evidence_ref = None
    if payload.get("competitor_evidence_ref") is not None:
        competitor_evidence_ref = as_str(payload["competitor_evidence_ref"],
                                        "competitor_evidence_ref", min_len=1)

    enforce_store_scope(user_id, role, store["id"])

    if claimed_price_cents < product["map_floor_cents"]:
        raise err("ERR_MAP_FLOOR_VIOLATION",
                  "claimed_price_cents sits below the product's map_floor_cents.")

    _require_competitor_eligible(competitor, policy)

    if product["category_code"] in policy["excluded_category_codes"]:
        raise err("ERR_CATEGORY_EXCLUDED",
                  "The product's category is excluded from the programme.")

    market_ids = {store["market_id"], product["market_id"],
                  competitor["market_id"], policy["market_id"]}
    if len(market_ids) != 1:
        raise err("ERR_MARKET_MISMATCH",
                  "The store, product, competitor and policy span several markets.")

    instant = clock.now()
    if claimed_observed_at > instant:
        raise err("ERR_OBSERVATION_IN_FUTURE",
                  "claimed_observed_at is later than the current logical instant.")
    if instant - claimed_observed_at > timedelta(hours=policy["claim_window_hours"]):
        raise err("ERR_CLAIM_WINDOW_EXPIRED",
                  "The sighting is older than the policy's claim_window_hours.")

    figures = calc.price_match_honored_price(claimed_price_cents, product, store)

    if product["own_price_cents"] <= figures["honored_price_cents"]:
        raise err("ERR_CLAIM_NO_SAVINGS", "The claim yields no discount.")
    cap_cents = round_half_up(dec(product["own_price_cents"])
                              * dec(policy["max_match_discount_pct"]))
    if figures["discount_cents"] > cap_cents:
        raise err("ERR_MATCH_DISCOUNT_CAP_EXCEEDED",
                  "discount_cents %d exceeds the policy cap of %d cents."
                  % (figures["discount_cents"], cap_cents))

    link = calc.confirmed_link_for_pair(product["id"], competitor["id"])

    record = db.new_record()
    record.update({
        "policy_id": policy["id"],
        "product_id": product["id"],
        "competitor_id": competitor["id"],
        "store_id": store["id"],
        "verification_link_id": link["id"] if link is not None else None,
        "claimed_price_cents": claimed_price_cents,
        "claimed_observed_at": claimed_observed_at,
        "competitor_evidence_ref": competitor_evidence_ref,
        "evidence_round": 0,
        "status": "SUBMITTED",
        "rejection_reason": None,
        "reversal_reason": None,
    })
    record.update(figures)
    db.claims[record["id"]] = record
    return object_response(serialize.claim(record), 201)


@bp.post("/claims/<claim_id>/verify")
@endpoint([STORE_MANAGER, COMPLIANCE_OFFICER])
def verify_claim(user_id, role, claim_id):
    claim = path_lookup("claims", claim_id, "ERR_CLAIM_NOT_FOUND")
    payload = body()
    evidence_ref = None
    if payload.get("competitor_evidence_ref") is not None:
        evidence_ref = as_str(payload["competitor_evidence_ref"],
                              "competitor_evidence_ref", min_len=1)

    enforce_store_scope(user_id, role, claim["store_id"])

    current = claim["status"]
    if current == "SUBMITTED":
        policy = db.policies.get(claim["policy_id"])
        if policy is None or policy["status"] != "ACTIVE":
            raise err("ERR_INVALID_STATE",
                      "The governing policy must be ACTIVE to start verification.")
        if evidence_ref is not None:
            claim["competitor_evidence_ref"] = evidence_ref
        claim["status"] = "VERIFYING"
        db.touch(claim)
    elif current == "NEEDS_EVIDENCE":
        if evidence_ref is None:
            raise err("ERR_INVALID_REQUEST",
                      "competitor_evidence_ref is required to restart verification.")
        if claim["evidence_round"] >= calc.MAX_CLAIM_EVIDENCE_ROUNDS:
            raise err("ERR_MAX_EVIDENCE_ROUNDS",
                      "The claim has exhausted its evidence rounds.")
        claim["competitor_evidence_ref"] = evidence_ref
        claim["evidence_round"] = claim["evidence_round"] + 1
        claim["status"] = "VERIFYING"
        db.touch(claim)
    else:
        raise err("ERR_INVALID_STATE",
                  "A claim in %s cannot enter verification." % current)

    return object_response(serialize.claim(claim))


@bp.post("/claims/<claim_id>/decide")
@endpoint([STORE_MANAGER, COMPLIANCE_OFFICER])
def decide_claim(user_id, role, claim_id):
    claim = path_lookup("claims", claim_id, "ERR_CLAIM_NOT_FOUND")
    payload = body()
    decision_raw = as_str(get_required(payload, "decision"), "decision", min_len=1)
    reason = None
    if payload.get("reason") is not None:
        reason = as_str(payload["reason"], "reason", min_len=1)
    decision = as_enum(decision_raw, "decision", CLAIM_DECISIONS)

    enforce_store_scope(user_id, role, claim["store_id"])

    if claim["status"] != "VERIFYING":
        raise err("ERR_INVALID_STATE",
                  "Only a VERIFYING claim may be decided.")

    if decision == "VERIFIED":
        competitor = db.competitors.get(claim["competitor_id"])
        policy = db.policies.get(claim["policy_id"])
        _require_competitor_eligible(competitor, policy)
        if claim["verification_link_id"] is None:
            raise err("ERR_NO_CONFIRMED_MATCH",
                      "The claim carries no CONFIRMED match to verify against.")
        claim["status"] = "VERIFIED"
    elif decision == "REJECTED":
        claim["status"] = "REJECTED"
        claim["rejection_reason"] = reason
    else:
        if claim["evidence_round"] >= calc.MAX_CLAIM_EVIDENCE_ROUNDS:
            raise err("ERR_MAX_EVIDENCE_ROUNDS",
                      "The claim has exhausted its evidence rounds.")
        claim["status"] = "NEEDS_EVIDENCE"
    db.touch(claim)
    return object_response(serialize.claim(claim))


@bp.post("/claims/<claim_id>/honor")
@endpoint([STORE_ASSOCIATE, STORE_MANAGER])
def honor_claim(user_id, role, claim_id):
    claim = path_lookup("claims", claim_id, "ERR_CLAIM_NOT_FOUND")
    enforce_store_scope(user_id, role, claim["store_id"])

    if claim["status"] != "VERIFIED":
        raise err("ERR_INVALID_STATE", "Only a VERIFIED claim may be honoured.")

    store = db.stores.get(claim["store_id"])
    product = db.products.get(claim["product_id"])
    policy = db.policies.get(claim["policy_id"])
    market = db.markets.get(store["market_id"]) if store else None
    if market is not None and market["pricing_posture"] == "FROZEN":
        raise err("ERR_MARKET_POSTURE_BLOCKED",
                  "The market's pricing_posture is FROZEN.")

    if claim["required_approval_tier"] == "MANAGER" and role != STORE_MANAGER:
        raise err("ERR_OVERRIDE_AUTHORITY_EXCEEDED",
                  "A MANAGER-tier claim must be honoured by a StoreManager.")

    used = ledger.override_budget_used_cents(store)
    if policy is not None and used + claim["discount_cents"] > policy["daily_override_budget_cents"]:
        raise err("ERR_OVERRIDE_BUDGET_EXCEEDED",
                  "The store's daily override budget cannot absorb this discount.")

    claim["status"] = "HONORED"
    db.touch(claim)
    _append_override_log(claim, "DEBIT", role, user_id)
    _synthesize_price_match_order(claim, product, user_id)
    return object_response(serialize.claim(claim))


@bp.post("/claims/<claim_id>/reverse")
@endpoint([STORE_MANAGER, COMPLIANCE_OFFICER])
def reverse_claim(user_id, role, claim_id):
    claim = path_lookup("claims", claim_id, "ERR_CLAIM_NOT_FOUND")
    payload = body()
    reversal_reason = as_str(get_required(payload, "reversal_reason"),
                            "reversal_reason", min_len=1)

    enforce_store_scope(user_id, role, claim["store_id"])

    if claim["status"] != "HONORED":
        raise err("ERR_INVALID_STATE", "Only a HONORED claim may be reversed.")

    claim["status"] = "REVERSED"
    claim["reversal_reason"] = reversal_reason
    db.touch(claim)
    _append_override_log(claim, "CREDIT", role, user_id)

    for order in db.ordered(db.orders):
        if order.get("source_claim_id") != claim["id"]:
            continue
        if order["status"] != "APPROVED":
            continue
        order["status"] = "SUSPENDED"
        cascades.release_signage(order)
        db.touch(order)
    return object_response(serialize.claim(claim))


@bp.get("/claims/<claim_id>")
@endpoint(ALL_ROLES)
def read_claim(user_id, role, claim_id):
    claim = path_lookup("claims", claim_id, "ERR_CLAIM_NOT_FOUND")
    return object_response(serialize.claim(claim))


@bp.get("/claims")
@endpoint(ALL_ROLES)
def list_claims(user_id, role):
    rows = filtered(db.ordered(db.claims), request.args,
                    [("policy_id", "policy_id"), ("product_id", "product_id"),
                     ("competitor_id", "competitor_id"),
                     ("store_id", "store_id"),
                     ("verification_link_id", "verification_link_id"),
                     ("status", "status"),
                     ("required_approval_tier", "required_approval_tier")])
    return list_page(rows, serialize.claim)


@bp.get("/claims/<claim_id>/override-logs")
@endpoint(ALL_ROLES)
def list_override_logs(user_id, role, claim_id):
    claim = path_lookup("claims", claim_id, "ERR_CLAIM_NOT_FOUND")
    rows = [log for log in db.ordered(db.override_logs)
            if log["claim_id"] == claim["id"]]
    rows = filtered(rows, request.args, [("direction", "direction")])
    return list_page(rows, serialize.override_log)


# --------------------------------------------------------------- internals

def _require_competitor_eligible(competitor, policy):
    if competitor is None or competitor["status"] != "ACTIVE":
        raise err("ERR_COMPETITOR_NOT_ELIGIBLE",
                  "The cited competitor is not ACTIVE.")
    if not competitor["price_match_eligible"]:
        raise err("ERR_COMPETITOR_NOT_ELIGIBLE",
                  "The cited competitor is not price-match eligible.")
    if policy is not None and competitor["tier"] not in policy["eligible_competitor_tiers"]:
        raise err("ERR_COMPETITOR_NOT_ELIGIBLE",
                  "The competitor's tier is not eligible under this policy.")


def _append_override_log(claim, direction, role, user_id):
    record = db.new_record(with_common=False)
    record.update({
        "claim_id": claim["id"],
        "direction": direction,
        "approval_tier": claim["required_approval_tier"],
        "approved_by_role": role,
        "approved_by_user_id": user_id,
        "approved_discount_cents": claim["discount_cents"],
        "honored_price_cents": claim["honored_price_cents"],
    })
    db.override_logs[record["id"]] = record
    return record


def _synthesize_price_match_order(claim, product, user_id):
    """Levels 2 and 3 of the honour cascade (PRD 3.9)."""
    proposal = calc.repricing_proposal(
        product, "PRICE_MATCH",
        hand_set_price_cents=claim["honored_price_cents"])
    record = db.new_record()
    record.update({
        "product_id": claim["product_id"],
        "market_id": product["market_id"],
        "rule_id": None,
        "source_claim_id": claim["id"],
        "signage_store_id": claim["store_id"],
        "supersedes_order_id": None,
        "label_batch_id": None,
        "origin": "PRICE_MATCH",
        "requested_price_cents": None,
        "benchmark_price_cents": None,
        "effective_from": clock.now(),
        "effective_until": None,
        "status": "APPROVED",
        "signage_status": "NOT_REQUIRED",
        "authored_by_user_id": user_id,
        "decided_by_user_id": None,
    })
    record.update(proposal)
    record["proposed_price_cents"] = claim["honored_price_cents"]
    db.orders[record["id"]] = record
    db.touch(product)
    cascades.label_batch_selection(record)
    return record
