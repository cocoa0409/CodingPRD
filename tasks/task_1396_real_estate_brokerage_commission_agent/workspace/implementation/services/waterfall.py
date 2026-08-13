"""The nine-step settlement waterfall (PRD §3.6, scaffold §1.3).

Pinned evaluation order:
  gross -> cobroke -> net_office -> referral -> adjusted -> royalty (capped)
  -> after_royalty -> tier split (cap-clipped) -> agent_gross -> mentor ->
  team override -> E&O -> transaction fee -> shortfall -> debit recovery ->
  agent_net.

Per-step rounding discipline: every component is rounded HALF UP to whole
cents at its own step before any later step consumes it.
"""

from services.common import mul_pct


def run_waterfall(deal, agent, plan_terms, window):
    """Compute the full payout schedule. Pure: no mutation.

    `window` is the AnniversaryPeriod row of the closing date (its
    accumulators are read BEFORE this deal posts).
    Returns the breakdown dict (without bookkeeping fields).
    """
    gross = deal["gross_commission_cents"]
    cobroke = deal["cobroke_payout_cents"]

    # Step 1 — co-broke off the top
    net_office = gross - cobroke

    # Step 2 — referral fee, rounded half up here
    referral_fee = mul_pct(deal["referral_pct"], net_office)
    adjusted = net_office - referral_fee

    # Step 3 — franchise royalty with its annual (window) cap
    tentative_royalty = mul_pct(plan_terms["royalty_pct"], adjusted)
    royalty_cap_room = max(0, plan_terms["royalty_cap_cents"] - window["royalty_accrued_cents"])
    royalty = min(tentative_royalty, royalty_cap_room)
    royalty_capped = royalty < tentative_royalty
    after_royalty = adjusted - royalty

    # Step 4 — tiered company split with cap clip. Applicable tier: first
    # (ascending threshold) whose threshold strictly exceeds pre-deal accrued
    # company dollar.
    accrued_cd = window["company_dollar_accrued_cents"]
    tiers = plan_terms["tiers"]
    tier_index = 0
    for i, t in enumerate(tiers):
        if t["threshold_company_dollar_cents"] > accrued_cd:
            tier_index = i
            break
    else:
        tier_index = len(tiers) - 1
    tier = tiers[tier_index]
    tentative_company = mul_pct(tier["broker_split_pct"], after_royalty)
    cap_room = max(0, tier["threshold_company_dollar_cents"] - accrued_cd)
    company_dollar = min(tentative_company, cap_room)
    cap_clipped = company_dollar < tentative_company
    agent_gross = after_royalty - company_dollar

    # Step 5 — mentor split (count read BEFORE this deal posts)
    mentor_applied = (
        agent.get("mentor_agent_id") is not None
        and agent["settled_deal_count"] < plan_terms["mentor_deal_count"]
    )
    if mentor_applied:
        mentor_split = mul_pct(plan_terms["mentor_split_pct"], agent_gross)
    else:
        mentor_split = 0

    # Step 6 — team override (same base as mentor; neither reduces the other)
    team_applied = (
        agent.get("team_lead_agent_id") is not None
        and agent.get("team_override_pct", 0) > 0
    )
    if team_applied:
        team_override = mul_pct(agent["team_override_pct"], agent_gross)
    else:
        team_override = 0

    # Steps 7-8 — flat fees, clipped by what remains
    remaining = agent_gross - mentor_split - team_override
    eo_fee = min(plan_terms["eo_fee_cents"], remaining)
    remaining -= eo_fee
    transaction_fee = min(plan_terms["transaction_fee_cents"], remaining)
    remaining -= transaction_fee
    fee_shortfall = (plan_terms["eo_fee_cents"] - eo_fee) + \
                    (plan_terms["transaction_fee_cents"] - transaction_fee)

    # Step 9 — debit recovery sweeps only the PRE-EXISTING debit balance
    debit_recovery = min(remaining, agent["debit_balance_cents"])
    agent_net = remaining - debit_recovery

    return {
        "gross_commission_cents": gross,
        "cobroke_payout_cents": cobroke,
        "net_office_commission_cents": net_office,
        "referral_fee_cents": referral_fee,
        "adjusted_commission_cents": adjusted,
        "royalty_cents": royalty,
        "royalty_capped": royalty_capped,
        "after_royalty_cents": after_royalty,
        "tier_index_applied": tier_index,
        "company_dollar_cents": company_dollar,
        "cap_clipped": cap_clipped,
        "agent_gross_cents": agent_gross,
        "mentor_split_cents": mentor_split,
        "mentor_applied": mentor_applied,
        "mentor_agent_id": agent.get("mentor_agent_id") if mentor_applied else None,
        "team_override_cents": team_override,
        "team_lead_agent_id": agent.get("team_lead_agent_id") if team_applied else None,
        "eo_fee_cents": eo_fee,
        "transaction_fee_cents": transaction_fee,
        "fee_shortfall_cents": fee_shortfall,
        "debit_recovery_cents": debit_recovery,
        "agent_net_cents": agent_net,
    }


def leg_composition(breakdown, deal):
    """Disbursement legs in fixed creation order (PRD §3.6); zero-amount legs
    are never created. Conservation: created legs always sum to gross."""
    legs = []
    if breakdown["cobroke_payout_cents"] > 0:
        legs.append(("CO_BROKE", None, deal.get("cobroke_payee_name"),
                     breakdown["cobroke_payout_cents"]))
    if breakdown["referral_fee_cents"] > 0:
        legs.append(("REFERRAL", deal.get("referral_agent_id"), None,
                     breakdown["referral_fee_cents"]))
    if breakdown["royalty_cents"] > 0:
        legs.append(("ROYALTY", None, "FRANCHISE", breakdown["royalty_cents"]))
    company_amt = (breakdown["company_dollar_cents"] + breakdown["eo_fee_cents"]
                   + breakdown["transaction_fee_cents"] + breakdown["debit_recovery_cents"])
    if company_amt > 0:
        legs.append(("COMPANY", None, "COMPANY", company_amt))
    if breakdown["mentor_split_cents"] > 0:
        legs.append(("MENTOR", breakdown["mentor_agent_id"], None,
                     breakdown["mentor_split_cents"]))
    if breakdown["team_override_cents"] > 0:
        legs.append(("TEAM_LEAD", breakdown["team_lead_agent_id"], None,
                     breakdown["team_override_cents"]))
    if breakdown["agent_net_cents"] > 0:
        legs.append(("AGENT", deal["agent_id"], None, breakdown["agent_net_cents"]))
    return legs
