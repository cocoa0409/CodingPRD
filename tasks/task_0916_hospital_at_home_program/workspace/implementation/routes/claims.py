"""Claim construction and payer settlement (PRD 3.9)."""

from flask import Blueprint

import calc
import derived
import envelope
import errors
import ladder
import serializers
import store
from errors import fail
from routes.common import apply_filter, endpoint
from store import DB

bp = Blueprint("claims", __name__)

OUTCOMES = ("PAID", "DENIED", "CLOSED")
CLAIM_LIST_ROLES = ["ProgramAdmin", "AdmittingPhysician", "BillingAnalyst"]


@endpoint(bp, "/billing-claims", ["POST"], ["BillingAnalyst"])
def build_claim(caller):
    body = ladder.json_body()
    # rung 4a
    ladder.require_fields(body, ["episode_id", "expected_episode_version"])
    # rung 4c
    supplied_version = ladder.expected_version(body, "expected_episode_version")
    # rung 5
    episode = ladder.body_episode(body)
    # rung 6
    ladder.check_occ(episode, supplied_version)
    # rung 16
    billable = derived.episode_billable_day_count(episode["id"])
    if billable < calc.MIN_BILLABLE_DAYS_FOR_CLAIM:
        fail(errors.ERR_NO_BILLABLE_DAYS)

    reimbursement = derived.episode_reimbursement_amount(episode)
    meal_credit = derived.episode_meal_credit_total(episode["id"])
    gross, rate, withhold, net = calc.claim_money(reimbursement, meal_credit)

    claim = store.make_row("claims", {
        "episode_id": episode["id"],
        "billed_day_count": billable,
        "gross_amount_usd": gross,
        "withhold_rate": rate,
        "withhold_amount_usd": withhold,
        "net_payable_usd": net,
        "paid_amount_usd": calc.ZERO,
        "status": "BUILT",
        "appeal_count": 0,
        "denial_reason": None,
    })
    # Building a claim advances the EPISODE's version by 1.
    store.touch(episode)
    return envelope.ObjResult(claim, serializers.billing_claim, 201)


@endpoint(bp, "/episodes/<episode_id>/billing-claims", ["GET"], CLAIM_LIST_ROLES)
def list_claims(caller, episode_id):
    # rung 3
    ladder.path_row("episodes", episode_id)
    limit, offset = ladder.pagination_params()
    rows = [c for c in DB.claims.values() if c["episode_id"] == episode_id]
    rows = apply_filter(rows, "status")
    return envelope.ListResult(store.ordered(rows), serializers.billing_claim, limit, offset)


@endpoint(bp, "/billing-claims/<claim_id>/submit", ["POST"], ["BillingAnalyst"])
def submit_claim(caller, claim_id):
    # rung 3
    claim = ladder.path_row("claims", claim_id)
    # rung 7
    ladder.require_state(claim["status"] == "BUILT")
    episode = DB.episodes.get(claim["episode_id"])
    ladder.require_state(episode is not None and episode["status"] == "DISCHARGED")
    claim["status"] = "SUBMITTED"
    store.touch(claim)
    return envelope.ObjResult(claim, serializers.billing_claim, 200)


@endpoint(bp, "/billing-claims/<claim_id>/record-outcome", ["POST"], ["BillingAnalyst"])
def record_outcome(caller, claim_id):
    # rung 3
    claim = ladder.path_row("claims", claim_id)
    body = ladder.json_body()
    # rung 4a
    ladder.require_fields(body, ["outcome"])
    # rung 4b
    ladder.check_enum(body, "outcome", OUTCOMES)
    outcome = body["outcome"]
    # rung 4a (conditional): denial_reason is required when the outcome is DENIED
    if outcome == "DENIED":
        ladder.require_fields(body, ["denial_reason"])
    # rung 7
    if outcome in ("PAID", "DENIED"):
        ladder.require_state(claim["status"] in ("SUBMITTED", "APPEALED"))
    else:
        ladder.require_state(claim["status"] in ("PAID", "DENIED"))

    if outcome == "PAID":
        from_appeal = claim["status"] == "APPEALED"
        claim["status"] = "PAID"
        if from_appeal:
            claim["paid_amount_usd"] = calc.appeal_recovery(claim["net_payable_usd"])
        else:
            claim["paid_amount_usd"] = calc.money(claim["net_payable_usd"])
    elif outcome == "DENIED":
        claim["status"] = "DENIED"
        claim["denial_reason"] = body["denial_reason"]
        claim["paid_amount_usd"] = calc.ZERO
    else:
        claim["status"] = "CLOSED"
    store.touch(claim)
    return envelope.ObjResult(claim, serializers.billing_claim, 200)


@endpoint(bp, "/billing-claims/<claim_id>/appeal", ["POST"], ["BillingAnalyst"])
def appeal_claim(caller, claim_id):
    # rung 3
    claim = ladder.path_row("claims", claim_id)
    # rung 7 -- the cap is deliberately enforced below the state check
    ladder.require_state(claim["status"] == "DENIED")
    # rung 14d
    if claim["appeal_count"] >= calc.MAX_APPEAL_ATTEMPTS:
        fail(errors.ERR_APPEAL_LIMIT_EXCEEDED)
    claim["status"] = "APPEALED"
    claim["appeal_count"] = claim["appeal_count"] + 1
    store.touch(claim)
    return envelope.ObjResult(claim, serializers.billing_claim, 200)
