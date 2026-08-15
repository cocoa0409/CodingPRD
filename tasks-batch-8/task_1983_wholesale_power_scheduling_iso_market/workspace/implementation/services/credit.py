"""Collateral requirement computation and credit posture evaluation (§2.8)."""
from datetime import timedelta
from decimal import Decimal

from db import store
from util import touch, new_record, rhu

REFERENCE_PRICE_CENTS_PER_MWH = 5000
OFFER_RISK_FACTOR = Decimal("0.10")
CAPACITY_RISK_CENTS_PER_MW = 50000
IG_UNSECURED_ALLOWANCE_CENTS = 100000
CURE_WINDOW_HOURS = 24


def unsecured_allowance(participant):
    return IG_UNSECURED_ALLOWANCE_CENTS if participant["credit_rating_tier"] == "INVESTMENT_GRADE" else 0


def effective_requirement(participant):
    return max(0, participant["collateral_requirement_cents"] - participant["unsecured_allowance_cents"])


def offer_risk_cents(offered_mw):
    """Half-up rounded per offer before summing."""
    return rhu(Decimal(offered_mw) * REFERENCE_PRICE_CENTS_PER_MWH * OFFER_RISK_FACTOR)


def recompute_requirement(participant):
    pid = participant["id"]
    remainders = []
    for s in store.statements.values():
        if s["market_participant_id"] != pid:
            continue
        if s["run_type"] in ("FINAL", "RESETTLEMENT") and s["status"] in ("ISSUED", "UNDER_DISPUTE"):
            remainders.append(s["net_amount_cents"] - s["paid_cents"])

    offer_risk = 0
    gen_ids = {g["id"] for g in store.generators.values() if g["market_participant_id"] == pid}
    for o in store.offers.values():
        if o["status"] == "SUBMITTED" and o["generator_asset_id"] in gen_ids:
            offer_risk += offer_risk_cents(o["offered_mw"])

    capacity_risk = Decimal(0)
    for obl in store.obligations.values():
        if obl["status"] == "AT_RISK" and obl["generator_asset_id"] in gen_ids:
            capacity_risk += Decimal(obl["obligated_mw"]) * CAPACITY_RISK_CENTS_PER_MW
    capacity_risk = rhu(capacity_risk)

    if participant["credit_rating_tier"] == "BELOW_INVESTMENT_GRADE":
        statement_part = sum(abs(r) for r in remainders)
    else:
        statement_part = max(0, sum(remainders))

    requirement = statement_part + offer_risk + capacity_risk
    if requirement != participant["collateral_requirement_cents"]:
        participant["collateral_requirement_cents"] = requirement
        touch(participant)
    return requirement


def open_margin_call(participant):
    for mc in store.margin_calls.values():
        if mc["market_participant_id"] == participant["id"] and mc["status"] == "OPEN":
            return mc
    return None


def defaulted_margin_call(participant):
    for mc in store.margin_calls.values():
        if mc["market_participant_id"] == participant["id"] and mc["status"] == "DEFAULTED":
            return mc
    return None


def evaluate_credit(participant):
    """Run the credit posture evaluation for one participant."""
    if participant["status"] == "SUSPENDED":
        # SUSPENDED participants never auto-reinstate and accrue no new calls
        # here; only an explicit POST evaluate-credit can move them back.
        return
    effective = effective_requirement(participant)
    posted = participant["posted_collateral_cents"]
    now = store.clock_now
    call = open_margin_call(participant)

    if posted >= effective:
        if call is not None:
            call["status"] = "CURED"
            touch(call)
        if participant["status"] == "MARGIN_CALL":
            participant["status"] = "ACTIVE"
            touch(participant)
    else:
        if call is None:
            call = new_record()
            call.update({
                "market_participant_id": participant["id"],
                "required_additional_cents": effective - posted,
                "due_at": now + timedelta(hours=CURE_WINDOW_HOURS),
                "status": "OPEN",
            })
            store.margin_calls[call["id"]] = call
            participant["status"] = "MARGIN_CALL"
            touch(participant)

    call = open_margin_call(participant)
    if call is not None and now > call["due_at"] and posted < effective:
        call["status"] = "DEFAULTED"
        touch(call)
        participant["status"] = "SUSPENDED"
        touch(participant)


def refresh_credit(participant):
    """Recompute the requirement, then evaluate posture."""
    recompute_requirement(participant)
    evaluate_credit(participant)
