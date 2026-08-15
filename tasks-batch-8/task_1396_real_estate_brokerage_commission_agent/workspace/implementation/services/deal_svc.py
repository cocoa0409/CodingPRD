"""Deal pipeline, settle/unsettle cascades, disbursement legs (PRD §3.5-3.8)."""

from datetime import date

import db
from errors import (
    ApiError, ERR_DEAL_INVALID_STATE, ERR_DEAL_HAS_SETTLEMENT,
    ERR_NO_PLAN_ENROLLMENT, ERR_WINDOW_CLOSED, ERR_LEGS_OUTSTANDING,
    ERR_LEG_INVALID_STATE, ERR_SEGREGATION_OF_DUTIES,
)
from services.common import new_id, stamp_new, stamp_append_only, touch
from services.ledger import post_entry
from services.trust import post_trust
from services.waterfall import run_waterfall, leg_composition
from timeutil import logical_stamp, parse_date, window_index_for


def active_settlement_for_deal(deal_id):
    for s in db.settlements.values():
        if s["deal_id"] == deal_id and s["status"] == "POSTED":
            return s
    return None


def legs_of_settlement(settlement_id):
    return [l for l in db.legs.values() if l["settlement_id"] == settlement_id]


def settle_deal(deal, user_id):
    """POST /deals/{id}/settle — the FINAL variant of the waterfall (mutating,
    atomic). Preconditions are checked by the caller (route) in guard order;
    this function runs the cascade."""
    agent = db.agents[deal["agent_id"]]

    # (a) window of the closing date (materialized lazily)
    closing = deal["_closing_date"]
    idx = window_index_for(agent["_joined_date"], closing)
    from services.anniversary import ensure_period
    window = ensure_period(agent, idx)
    if window["status"] == "CLOSED":
        raise ApiError(ERR_WINDOW_CLOSED, 409,
                       "the anniversary window containing closing_date is CLOSED")

    # (b) covering enrollment
    from services.enrollment import covering_enrollment, plan_terms
    enrollment = covering_enrollment(agent["id"], closing)
    if enrollment is None:
        raise ApiError(ERR_NO_PLAN_ENROLLMENT, 409,
                       "no PlanEnrollment covers the deal's closing_date")

    # (c) pinned plan terms; (d) accumulators read before this deal posts
    terms = plan_terms(enrollment["plan_id"], enrollment["plan_version"])
    breakdown = run_waterfall(deal, agent, terms, window)

    settlement = {
        "id": new_id(),
        "deal_id": deal["id"],
        "agent_id": agent["id"],
        "enrollment_id": enrollment["id"],
        "plan_version_used": enrollment["plan_version"],
        "window_start": window["window_start"],
        **breakdown,
        "status": "POSTED",
        "posted_by_user_id": user_id,
        "posted_at": logical_stamp(),
        "reversed_at": None,
    }
    stamp_new(settlement)
    db.settlements[settlement["id"]] = settlement

    # Disbursement legs in fixed creation order (zero-amount suppressed)
    for payee_type, payee_agent_id, payee_name, amount in leg_composition(breakdown, deal):
        leg = {
            "id": new_id(),
            "settlement_id": settlement["id"],
            "payee_type": payee_type,
            "payee_agent_id": payee_agent_id,
            "payee_name": payee_name,
            "amount_cents": amount,
            "status": "SCHEDULED",
            "authorized_by_user_id": None,
            "authorized_at": None,
            "released_by_user_id": None,
            "released_at": None,
        }
        stamp_new(leg)
        db.legs[leg["id"]] = leg

    # (f) accumulators rise only after the money steps
    window["company_dollar_accrued_cents"] += breakdown["company_dollar_cents"]
    window["royalty_accrued_cents"] += breakdown["royalty_cents"]
    touch(window)

    # Agent: settled_deal_count +1 (version bumps once for the settle cascade)
    agent["settled_deal_count"] = agent.get("settled_deal_count", 0) + 1
    touch(agent)

    # Debit ledger, pinned posting order: shortfall accrual FIRST, then recovery
    if breakdown["fee_shortfall_cents"] > 0:
        post_entry(agent, "FEE_SHORTFALL_ACCRUAL", breakdown["fee_shortfall_cents"],
                   deal_id=deal["id"], settlement_id=settlement["id"])
    if breakdown["debit_recovery_cents"] > 0:
        post_entry(agent, "DEBIT_RECOVERY", -breakdown["debit_recovery_cents"],
                   deal_id=deal["id"], settlement_id=settlement["id"])

    deal["status"] = "SETTLED"
    touch(deal)
    return settlement


def unsettle_deal(deal):
    """POST /deals/{id}/unsettle — full reversal cascade (atomic)."""
    settlement = active_settlement_for_deal(deal["id"])
    legs = legs_of_settlement(settlement["id"]) if settlement else []
    for leg in legs:
        if leg["status"] not in ("SCHEDULED", "VOIDED"):
            raise ApiError(ERR_LEGS_OUTSTANDING, 409,
                           "unsettle blocked: a leg is AUTHORIZED or RELEASED")

    agent = db.agents[deal["agent_id"]]

    # Settlement POSTED -> REVERSED
    settlement["status"] = "REVERSED"
    settlement["reversed_at"] = logical_stamp()
    touch(settlement)

    # Every still-SCHEDULED leg -> VOIDED
    for leg in legs:
        if leg["status"] == "SCHEDULED":
            leg["status"] = "VOIDED"
            touch(leg)

    # Exact accumulator restoration
    from services.anniversary import get_period
    window = None
    for p in db.anniversary_periods.values():
        if p["agent_id"] == agent["id"] and p["window_start"] == settlement["window_start"]:
            window = p
            break
    if window is not None:
        window["company_dollar_accrued_cents"] -= settlement["company_dollar_cents"]
        window["royalty_accrued_cents"] -= settlement["royalty_cents"]
        touch(window)

    # Debit ledger compensation
    if settlement["debit_recovery_cents"] > 0:
        post_entry(agent, "DEBIT_RECOVERY_REVERSAL", settlement["debit_recovery_cents"],
                   deal_id=deal["id"], settlement_id=settlement["id"])
    if settlement["fee_shortfall_cents"] > 0:
        post_entry(agent, "FEE_SHORTFALL_REVERSAL", -settlement["fee_shortfall_cents"],
                   deal_id=deal["id"], settlement_id=settlement["id"])

    agent["settled_deal_count"] = agent.get("settled_deal_count", 0) - 1
    touch(agent)

    deal["status"] = "CLOSED"
    touch(deal)
    return deal


def check_leg_actionable(leg, user_id, action):
    """Shared guards for authorize/release: leg state, settlement POSTED,
    deal SETTLED, segregation of duties."""
    settlement = db.settlements[leg["settlement_id"]]
    deal = db.deals[settlement["deal_id"]]

    if action == "authorize":
        if leg["status"] != "SCHEDULED":
            raise ApiError(ERR_LEG_INVALID_STATE, 409, "leg is not SCHEDULED")
    elif action == "release":
        if leg["status"] != "AUTHORIZED":
            raise ApiError(ERR_LEG_INVALID_STATE, 409, "leg is not AUTHORIZED")
    elif action == "void":
        if leg["status"] not in ("SCHEDULED", "AUTHORIZED"):
            raise ApiError(ERR_LEG_INVALID_STATE, 409, "leg cannot be voided from its state")

    if settlement["status"] != "POSTED" or deal["status"] != "SETTLED":
        raise ApiError(ERR_DEAL_INVALID_STATE, 409,
                       "the leg's settlement is not POSTED or its deal is not SETTLED")

    if action == "authorize" and user_id == settlement["posted_by_user_id"]:
        raise ApiError(ERR_SEGREGATION_OF_DUTIES, 403,
                       "the settlement poster may not authorize its legs")
    if action == "release" and user_id == leg["authorized_by_user_id"]:
        raise ApiError(ERR_SEGREGATION_OF_DUTIES, 403,
                       "the authorizer may not release the same leg")
    return settlement, deal


def release_leg(leg, user_id):
    settlement, deal = check_leg_actionable(leg, user_id, "release")
    leg["released_by_user_id"] = user_id
    leg["released_at"] = logical_stamp()
    leg["status"] = "RELEASED"
    touch(leg)
    post_trust(deal["id"], "RELEASE", -leg["amount_cents"],
               disbursement_leg_id=leg["id"])

    # Bubble-up: every leg RELEASED -> deal DISBURSED
    if all(l["status"] == "RELEASED" for l in legs_of_settlement(settlement["id"])):
        deal["status"] = "DISBURSED"
        touch(deal)
    return leg
