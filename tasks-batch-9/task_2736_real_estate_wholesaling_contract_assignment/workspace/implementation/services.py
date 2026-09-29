"""Cross-aggregate domain services: lookups, ownership, derived-value
recomputation, the compliance-hold cascade and the cancellation cascade.
"""
from datetime import timedelta

import calc
from common import db, fail, now, touch

# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------
NOT_FOUND = {
    "wholesalers": "ERR_WHOLESALER_NOT_FOUND",
    "marketing_campaigns": "ERR_MARKETING_CAMPAIGN_NOT_FOUND",
    "seller_leads": "ERR_SELLER_LEAD_NOT_FOUND",
    "deal_analyses": "ERR_DEAL_ANALYSIS_NOT_FOUND",
    "purchase_contracts": "ERR_PURCHASE_CONTRACT_NOT_FOUND",
    "disclosure_acknowledgements": "ERR_DISCLOSURE_ACKNOWLEDGEMENT_NOT_FOUND",
    "earnest_money_deposits": "ERR_EARNEST_MONEY_DEPOSIT_NOT_FOUND",
    "cash_buyers": "ERR_CASH_BUYER_NOT_FOUND",
    "proof_of_funds": "ERR_PROOF_OF_FUNDS_NOT_FOUND",
    "assignment_offers": "ERR_ASSIGNMENT_OFFER_NOT_FOUND",
    "assignment_agreements": "ERR_ASSIGNMENT_AGREEMENT_NOT_FOUND",
    "title_orders": "ERR_TITLE_ORDER_NOT_FOUND",
    "compliance_reviews": "ERR_COMPLIANCE_REVIEW_NOT_FOUND",
    "dispute_cases": "ERR_DISPUTE_CASE_NOT_FOUND",
}


def collection(name):
    return getattr(db, name)


def load(name, record_id):
    """Resolve an identifier or raise that aggregate's not-found code."""
    if not isinstance(record_id, str):
        fail(NOT_FOUND[name])
    rec = collection(name).get(record_id)
    if rec is None:
        fail(NOT_FOUND[name])
    return rec


def all_of(name):
    return list(collection(name).values())


def store(name, rec):
    collection(name)[rec["id"]] = rec
    return rec


def set_fields(rec, changes):
    """Apply changes; bump version/updated_at only when something really moved."""
    changed = False
    for key, value in changes.items():
        if rec.get(key) != value:
            changed = True
        rec[key] = value
    if changed:
        touch(rec)
    return changed


# ---------------------------------------------------------------------------
# Graph navigation
# ---------------------------------------------------------------------------
def lead_of_contract(contract):
    return collection("seller_leads").get(contract["seller_lead_id"])


def wholesaler_of_lead(lead):
    return collection("wholesalers").get(lead["wholesaler_id"])


def wholesaler_of_contract(contract):
    lead = lead_of_contract(contract)
    return wholesaler_of_lead(lead) if lead else None


def wholesaler_id_of_contract(contract):
    lead = lead_of_contract(contract)
    return lead["wholesaler_id"] if lead else None


def contract_of_offer(offer):
    return collection("purchase_contracts").get(offer["purchase_contract_id"])


def buyer_of_offer(offer):
    return collection("cash_buyers").get(offer["cash_buyer_id"])


def contract_of_agreement(agreement):
    offer = collection("assignment_offers").get(agreement["assignment_offer_id"])
    return contract_of_offer(offer) if offer else None


def offers_of_contract(contract):
    return [
        o
        for o in all_of("assignment_offers")
        if o["purchase_contract_id"] == contract["id"]
    ]


def agreements_of_contract(contract):
    out = []
    for agreement in all_of("assignment_agreements"):
        offer = collection("assignment_offers").get(agreement["assignment_offer_id"])
        if offer is not None and offer["purchase_contract_id"] == contract["id"]:
            out.append(agreement)
    return out


def agreement_for_offer(offer_id):
    for agreement in all_of("assignment_agreements"):
        if agreement["assignment_offer_id"] == offer_id:
            return agreement
    return None


def deposit_of_contract(contract):
    for deposit in all_of("earnest_money_deposits"):
        if deposit["purchase_contract_id"] == contract["id"]:
            return deposit
    return None


def title_orders_of_contract(contract):
    return [
        t for t in all_of("title_orders") if t["purchase_contract_id"] == contract["id"]
    ]


def acknowledgements_of_contract(contract):
    return [
        a
        for a in all_of("disclosure_acknowledgements")
        if a["purchase_contract_id"] == contract["id"]
    ]


def accepted_offer_of_contract(contract):
    """The offer that reached ACCEPTED (it stays relevant once CONSUMED)."""
    candidates = [
        o
        for o in offers_of_contract(contract)
        if o.get("accepted_at") is not None and o["status"] in ("ACCEPTED", "CONSUMED")
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda o: (o["accepted_at"], o["_seq"]))
    return candidates[-1]


# ---------------------------------------------------------------------------
# Derived values: buyer capital (PRD §2.11, §3.6)
# ---------------------------------------------------------------------------
def recompute_buyer(buyer):
    verified = 0
    for proof in all_of("proof_of_funds"):
        if proof["cash_buyer_id"] != buyer["id"]:
            continue
        if proof["verification_status"] != "VERIFIED":
            continue
        if proof.get("expires_at") is None or proof["expires_at"] <= now():
            continue
        amount = proof.get("verified_funds_cents")
        if amount is not None and amount > verified:
            verified = amount
    live = [
        o
        for o in all_of("assignment_offers")
        if o["cash_buyer_id"] == buyer["id"] and o["status"] in calc.LIVE_OFFER_STATUSES
    ]
    committed = sum(int(o["buyer_deposit_cents"]) for o in live)
    available = verified - committed
    if verified == 0:
        tier = "SUSPENDED"
    elif available >= calc.PRIORITY_TIER_MIN_AVAILABLE_CENTS:
        tier = "PRIORITY"
    else:
        tier = "STANDARD"
    return set_fields(
        buyer,
        {
            "verified_funds_cents": verified,
            "committed_deposit_cents": committed,
            "available_funds_cents": available,
            "active_offer_count": len(live),
            "buyer_tier": tier,
        },
    )


def recompute_all_buyers():
    for buyer in all_of("cash_buyers"):
        recompute_buyer(buyer)


def recompute_buyers(buyer_ids):
    for buyer_id in set(buyer_ids):
        buyer = collection("cash_buyers").get(buyer_id)
        if buyer is not None:
            recompute_buyer(buyer)


# ---------------------------------------------------------------------------
# Derived values: wholesaler compliance posture (PRD §2.9)
# ---------------------------------------------------------------------------
def executed_assignment_count(wholesaler):
    total = 0
    for agreement in all_of("assignment_agreements"):
        if agreement["settlement_status"] not in ("PENDING_SETTLEMENT", "SETTLED"):
            continue
        contract = contract_of_agreement(agreement)
        if contract is None:
            continue
        if wholesaler_id_of_contract(contract) == wholesaler["id"]:
            total += 1
    return total


def recompute_wholesaler(wholesaler):
    adverse = len(
        [
            r
            for r in all_of("compliance_reviews")
            if r["wholesaler_id"] == wholesaler["id"]
            and r["status"] == "ADJUDICATED_ADVERSE"
        ]
    )
    hold = adverse >= calc.COMPLIANCE_HOLD_THRESHOLD
    return set_fields(
        wholesaler,
        {
            "adverse_finding_count": adverse,
            "compliance_hold": hold,
            "executed_assignment_count": executed_assignment_count(wholesaler),
        },
    )


def recompute_executed_count(wholesaler):
    if wholesaler is None:
        return False
    return set_fields(
        wholesaler, {"executed_assignment_count": executed_assignment_count(wholesaler)}
    )


def leads_of_wholesaler(wholesaler_id):
    return [
        lead for lead in all_of("seller_leads") if lead["wholesaler_id"] == wholesaler_id
    ]


def campaigns_of_wholesaler(wholesaler_id):
    return [
        c
        for c in all_of("marketing_campaigns")
        if c["wholesaler_id"] == wholesaler_id
    ]


def lead_blocked_value(lead):
    wholesaler = wholesaler_of_lead(lead)
    if wholesaler is not None and wholesaler.get("compliance_hold"):
        return True
    campaign_id = lead.get("marketing_campaign_id")
    if campaign_id:
        campaign = collection("marketing_campaigns").get(campaign_id)
        if campaign is not None and campaign["status"] == "SUSPENDED":
            return True
    return False


def recompute_lead_blocked(lead):
    return set_fields(lead, {"lead_gen_blocked": lead_blocked_value(lead)})


def recompute_campaign_leads(campaign):
    for lead in all_of("seller_leads"):
        if lead.get("marketing_campaign_id") == campaign["id"]:
            recompute_lead_blocked(lead)


def hold_cascade(wholesaler):
    """Levels 2-4 of the adverse-adjudication cascade (PRD §2.9)."""
    if not wholesaler.get("compliance_hold"):
        return
    for campaign in campaigns_of_wholesaler(wholesaler["id"]):
        if campaign["status"] == "PUBLISHED":
            campaign["status"] = "SUSPENDED"
            campaign["suspension_count"] = campaign["suspension_count"] + 1
            touch(campaign)
    for lead in leads_of_wholesaler(wholesaler["id"]):
        recompute_lead_blocked(lead)


# ---------------------------------------------------------------------------
# Double-close funding schedule (PRD §3.8)
# ---------------------------------------------------------------------------
def apply_funding_schedule(contract):
    base, fee, total = calc.double_close_funding_schedule(
        contract["purchase_price_cents"]
    )
    contract["funding_base_cents"] = base
    contract["transactional_lender_fee_cents"] = fee
    contract["total_funding_required_cents"] = total
    recompute_spread(contract)


def clear_funding_schedule(contract):
    contract["funding_base_cents"] = None
    contract["transactional_lender_fee_cents"] = None
    contract["total_funding_required_cents"] = None
    contract["double_close_spread_cents"] = None


def recompute_spread(contract):
    if contract["structure_election"] != "DOUBLE_CLOSE_ELECTED":
        return
    total = contract.get("total_funding_required_cents")
    offer = accepted_offer_of_contract(contract)
    if total is None or offer is None:
        contract["double_close_spread_cents"] = None
    else:
        contract["double_close_spread_cents"] = int(offer["buyer_price_cents"]) - int(
            total
        )


# ---------------------------------------------------------------------------
# Deadlines (PRD §2.5)
# ---------------------------------------------------------------------------
def cooling_off_end(lead):
    if lead.get("screened_at") is None:
        return None
    return lead["screened_at"] + timedelta(hours=calc.PROTECTED_COOLING_OFF_HOURS)


def inside_cooling_off(lead):
    if lead is None or lead.get("protection_tier") != "PROTECTED":
        return False
    end = cooling_off_end(lead)
    if end is None:
        return False
    return now() < end


def assignment_deadline_passed(contract):
    deadline = contract.get("assignment_deadline_at")
    if deadline is None:
        return False
    return now() >= deadline


# ---------------------------------------------------------------------------
# Interval semantics (PRD §2.12)
# ---------------------------------------------------------------------------
OCCUPYING_CONTRACT_STATUSES = ("DRAFT", "SIGNED", "PENDING_CLOSE")


def occupancy_conflict(lead_id, option_start_at, closing_window_end_at):
    """Fully closed interval, capacity one, no buffer."""
    for contract in all_of("purchase_contracts"):
        if contract["seller_lead_id"] != lead_id:
            continue
        if contract["contract_status"] not in OCCUPYING_CONTRACT_STATUSES:
            continue
        if (
            option_start_at <= contract["closing_window_end_at"]
            and closing_window_end_at >= contract["option_start_at"]
        ):
            return True
    return False


def funding_window_conflicts(wholesaler_id, start_at, buffered_end_at):
    """Half-open on the right, 48h trailing buffer, capacity from the wholesaler."""
    conflicts = 0
    for order in all_of("title_orders"):
        if order["structure"] != "DOUBLE_CLOSE":
            continue
        if order["status"] not in ("OPENED", "CLEARED_TO_FUND"):
            continue
        contract = collection("purchase_contracts").get(order["purchase_contract_id"])
        if contract is None or wholesaler_id_of_contract(contract) != wholesaler_id:
            continue
        existing_buffered_end = order.get("buffered_window_end_at") or order[
            "funding_window_end_at"
        ]
        if (
            start_at < existing_buffered_end
            and order["funding_window_start_at"] < buffered_end_at
        ):
            conflicts += 1
    return conflicts


# ---------------------------------------------------------------------------
# Lead lifecycle driven by contracts (PRD §3.3)
# ---------------------------------------------------------------------------
def lead_has_live_contract(lead_id, exclude_contract_id=None):
    for contract in all_of("purchase_contracts"):
        if contract["seller_lead_id"] != lead_id:
            continue
        if exclude_contract_id is not None and contract["id"] == exclude_contract_id:
            continue
        if contract["contract_status"] not in ("CLOSED", "CANCELLED"):
            return True
    return False


# ---------------------------------------------------------------------------
# Cancellation cascade (PRD §3.9)
# ---------------------------------------------------------------------------
def cancellation_cascade(contract, reason):
    was_signed = contract["contract_status"] in ("SIGNED", "PENDING_CLOSE")
    contract["contract_status"] = "CANCELLED"
    contract["cancellation_reason"] = reason
    contract["cancelled_at"] = now()
    touch(contract)

    affected_buyers = []
    if was_signed:
        # Level two: lapse the live market.
        for offer in offers_of_contract(contract):
            if offer["status"] in calc.LIVE_OFFER_STATUSES:
                offer["status"] = "LAPSED"
                touch(offer)
                affected_buyers.append(offer["cash_buyer_id"])
        # Level three: terminate paperwork still pending settlement.
        for agreement in agreements_of_contract(contract):
            if agreement["settlement_status"] == "PENDING_SETTLEMENT":
                agreement["settlement_status"] = "TERMINATED_UPSTREAM"
                agreement["title_holdback_cents"] = 0
                agreement["state_transfer_surcharge_cents"] = 0
                agreement["marketing_cost_recovery_cents"] = 0
                agreement["wholesaler_net_cents"] = 0
                touch(agreement)
        # Level four: restore buyer capital.
        recompute_buyers(affected_buyers)
        recompute_executed_count(wholesaler_of_contract(contract))
        # Escrow returns to the wholesaler.
        deposit = deposit_of_contract(contract)
        if deposit is not None and deposit["status"] == "HELD":
            calc.apply_disposition(deposit, "CANCEL_REFUND")
            touch(deposit)
        # Release reserved funding windows.
        for order in title_orders_of_contract(contract):
            if order["status"] in ("OPENED", "CLEARED_TO_FUND"):
                order["status"] = "CANCELLED"
                touch(order)

    lead = lead_of_contract(contract)
    if lead is not None and lead["status"] == "UNDER_CONTRACT":
        if not lead_has_live_contract(lead["id"], exclude_contract_id=contract["id"]):
            set_fields(lead, {"status": "SCREENED"})


# ---------------------------------------------------------------------------
# Shared guards
# ---------------------------------------------------------------------------
def guard_contract_terminal(contract):
    if contract["contract_status"] in ("CLOSED", "CANCELLED"):
        fail("ERR_CONTRACT_TERMINAL", "The governing contract is already terminal.")


def guard_compliance_hold(wholesaler):
    if wholesaler is not None and wholesaler.get("compliance_hold"):
        fail(
            "ERR_WHOLESALER_COMPLIANCE_HOLD",
            "The governing wholesaler is on a compliance hold.",
        )


def guard_fee_cap(buyer_price_cents, contract, lead):
    tier = lead.get("protection_tier") if lead else None
    if calc.fee_exceeds_cap(buyer_price_cents, contract["purchase_price_cents"], tier):
        fail(
            "ERR_ASSIGNMENT_FEE_CAP_EXCEEDED",
            "The implied assignment fee exceeds the seller's protection-tier cap.",
        )


def guard_cooling_off(lead):
    if inside_cooling_off(lead):
        fail(
            "ERR_COOLING_OFF_NOT_ELAPSED",
            "The protected seller's cooling-off window has not elapsed.",
        )


def guard_assignment_deadline(contract):
    if assignment_deadline_passed(contract):
        fail(
            "ERR_ASSIGNMENT_DEADLINE_PASSED",
            "The assignment cutoff has been reached.",
        )


def verified_proofs(buyer_id):
    return [
        p
        for p in all_of("proof_of_funds")
        if p["cash_buyer_id"] == buyer_id and p["verification_status"] == "VERIFIED"
    ]


def guard_proof_of_funds(buyer):
    proofs = verified_proofs(buyer["id"])
    if not proofs:
        fail("ERR_POF_NOT_VERIFIED", "The bidding buyer has no verified proof of funds.")
    return proofs


def guard_proofs_unexpired(proofs):
    for proof in proofs:
        if proof.get("expires_at") is not None and proof["expires_at"] > now():
            return
    fail(
        "ERR_PROOF_OF_FUNDS_EXPIRED",
        "Every verified proof of funds for this buyer has expired.",
    )


def guard_owner(condition, message="The acting principal does not own the target."):
    if not condition:
        fail("ERR_NOT_RESOURCE_OWNER", message)
