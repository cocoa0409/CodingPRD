"""All calculation rules from SCAFFOLD 1.3 / PRD 3.

Every monetary amount is integer cents; every rounding step is round_half_up.
"""

from decimal import Decimal

import db
from db import ONE4, ONE6, ZERO4, ZERO6, rhu, rhu_int
from services import queries as q


# =========================================================== budget roll-up
def capitalization_budget_rollup(ctx, production):
    ctx.watch(production)
    lines = q.budget_lines_of(production["id"])
    production["budget_total_cents"] = sum(
        line["amount_cents"] for line in lines
        if line["commitment_status"] in ("PLANNED", "COMMITTED", "SPENT"))
    production["budget_committed_cents"] = sum(
        line["amount_cents"] for line in lines
        if line["commitment_status"] in ("COMMITTED", "SPENT"))


# ==================================================== offering document rollup
def refresh_offering_document(ctx, document):
    ctx.watch(document)
    subs = q.subs_of_doc(document["id"])
    document["submitted_units_total"] = sum(
        s["units"] for s in subs if s["status"] == "SUBMITTED")
    accepted = [s for s in subs if s["status"] == "ACCEPTED"]
    document["accepted_units_total"] = sum(s["units"] for s in accepted)
    document["accepted_amount_cents"] = sum(s["amount_cents"] for s in accepted)
    document["accepted_investor_count"] = len(
        {s["investor_id"] for s in accepted})


# ============================================== investor ownership allocation
def investor_ownership_allocation(ctx, production):
    """SCAFFOLD investor_ownership_allocation steps 2-4 / PRD 3.4."""
    accounts = q.accounts_of(production["id"])
    subs = q.subs_of_production(production["id"])
    for account in accounts:
        ctx.watch(account)
        mine = [s for s in subs
                if s["investor_id"] == account["investor_id"]
                and s["status"] == "ACCEPTED"]
        account["units_total"] = sum(s["units"] for s in mine)
        account["contributed_cents"] = sum(s["amount_cents"] for s in mine)

    ordered = sorted(accounts, key=lambda a: (-a["units_total"], a["_seq"]))
    total_units = sum(a["units_total"] for a in accounts)
    if not ordered:
        refresh_recoupment_credits(ctx, production)
        return
    if total_units == 0:
        for account in accounts:
            account["ownership_pct"] = ZERO6
    else:
        running = Decimal(0)
        for account in ordered:
            share = rhu(db.div(account["units_total"], total_units), 6)
            account["ownership_pct"] = share
            running += share
        residue = ONE6 - running
        ordered[0]["ownership_pct"] = (ordered[0]["ownership_pct"]
                                       + residue).quantize(ONE6)
    refresh_recoupment_credits(ctx, production)


def refresh_recoupment_credits(ctx, production):
    """Step 4: recoupment credit snapshot on every capital account."""
    for account in q.accounts_of(production["id"]):
        ctx.watch(account)
        account["recoupment_credited_cents"] = rhu_int(
            Decimal(production["recouped_amount_cents"])
            * account["ownership_pct"])


# ======================================================= production capital
def recompute_production_capital(ctx, production):
    ctx.watch(production)
    subs = q.subs_of_production(production["id"])
    production["capital_raised_cents"] = sum(
        s["amount_cents"] for s in subs if s["status"] == "ACCEPTED")
    production["escrow_balance_cents"] = (production["capital_raised_cents"]
                                         - production["released_capital_cents"])
    production["active_investor_count"] = len(
        [a for a in q.accounts_of(production["id"]) if a["units_total"] > 0])


# ================================================== royalty pool share pct
def royalty_pool_share_pct(ctx, production):
    """SCAFFOLD royalty_pool_share_pct / PRD 3.6."""
    ctx.watch(production)
    participants = q.participants_of(production["id"])
    total_points = sum(p["pool_points"] for p in participants
                       if p["status"] == "ACTIVE")
    production["total_pool_points"] = total_points

    eligible = q.eligible_participants(production["id"])
    for participant in participants:
        ctx.watch(participant)
        participant["pool_share_pct"] = ZERO4

    if total_points == 0 or not eligible:
        return

    running = Decimal(0)
    for participant in eligible:
        share = rhu(db.div(participant["pool_points"], total_points), 4)
        participant["pool_share_pct"] = share
        running += share
    residue = ONE4 - running
    eligible[0]["pool_share_pct"] = (eligible[0]["pool_share_pct"]
                                     + residue).quantize(ONE4)


def refresh_participant_cumulative(ctx, participant):
    ctx.watch(participant)
    participant["cumulative_royalty_cents"] = sum(
        a["allocated_cents"] for a in q.allocations_of_participant(
            participant["id"]) if a["status"] == "ALLOCATED")


# ============================================ wrap settlement (steps 1 - 3)
def derive_wrap_provisional(wrap, theatre, operating_budget):
    """wrap_settlement steps 1-3, applied at create and at amend."""
    performances = wrap["performances"]
    wrap["capacity_gross_cents"] = (theatre["seat_count"]
                                    * theatre["top_ticket_price_cents"]
                                    * performances)
    wrap["paid_capacity_pct"] = rhu(
        db.div(wrap["paid_attendance"],
               theatre["seat_count"] * performances), 4)
    wrap["variable_cost_cents"] = rhu_int(
        Decimal(wrap["gross_receipts_cents"])
        * operating_budget["variable_cost_pct"])
    wrap["adjusted_gross_cents"] = (wrap["gross_receipts_cents"]
                                    - wrap["variable_cost_cents"])
    wrap["royalty_base_cents"] = max(
        0, wrap["adjusted_gross_cents"] - wrap["running_expenses_cents"])


# ============================================ wrap settlement (steps 4 - 5)
def settle_wrap(wrap, production, theatre, operating_budget):
    """wrap_settlement, all five steps, at certification."""
    derive_wrap_provisional(wrap, theatre, operating_budget)

    eligible = q.eligible_participants(production["id"])
    pool_floor_cents = sum(p["min_guarantee_cents"] for p in eligible)

    basis = production["royalty_basis"]
    wrap["royalty_basis_applied"] = basis

    if basis == "FIXED_GROSS":
        wrap["royalty_pool_cents"] = sum(
            rhu_int(Decimal(wrap["adjusted_gross_cents"])
                    * p["fixed_gross_pct"])
            for p in eligible)
        wrap["deferred_royalty_added_cents"] = 0
    else:
        pool_pct = (production["post_recoupment_pool_pct"]
                    if production["recoupment_status"] == "RECOUPED"
                    else production["pre_recoupment_pool_pct"])
        base = wrap["royalty_base_cents"]
        if base <= 0:
            wrap["royalty_pool_cents"] = 0
            wrap["deferred_royalty_added_cents"] = pool_floor_cents
        else:
            raw = rhu_int(Decimal(base) * pool_pct)
            wrap["royalty_pool_cents"] = min(max(raw, pool_floor_cents), base)
            wrap["deferred_royalty_added_cents"] = 0

    wrap["weekly_operating_profit_cents"] = (wrap["royalty_base_cents"]
                                             - wrap["royalty_pool_cents"])


# =============================================================== pool split
def royalty_pool_split(ctx, wrap, production):
    """SCAFFOLD royalty_pool_split / PRD 3.7."""
    eligible = q.eligible_participants(production["id"])
    total_points = sum(p["pool_points"] for p in eligible)
    if wrap["royalty_pool_cents"] == 0 or total_points == 0 or not eligible:
        return []

    shares = {}
    if wrap["royalty_basis_applied"] == "FIXED_GROSS":
        for participant in eligible:
            shares[participant["id"]] = rhu_int(
                Decimal(wrap["adjusted_gross_cents"])
                * participant["fixed_gross_pct"])
        basis = "FIXED_GROSS"
    else:
        running = 0
        for participant in eligible:
            amount = rhu_int(
                Decimal(wrap["royalty_pool_cents"])
                * Decimal(participant["pool_points"]) / Decimal(total_points))
            shares[participant["id"]] = amount
            running += amount
        residue = wrap["royalty_pool_cents"] - running
        shares[eligible[0]["id"]] += residue
        basis = "POOL"

    created = []
    for participant in eligible:
        row = db.insert("royalty_allocations", {
            "wrap_id": wrap["id"],
            "royalty_participant_id": participant["id"],
            "basis": basis,
            "points_at_allocation": (0 if basis == "FIXED_GROSS"
                                     else participant["pool_points"]),
            "allocated_cents": shares[participant["id"]],
            "status": "ALLOCATED",
        })
        ctx.created(row)
        created.append(row)
    return created


# ======================================================= recoupment progress
def cash_basis(production):
    wrap_profit = sum(w["weekly_operating_profit_cents"]
                      for w in q.wraps_of(production["id"])
                      if w["status"] == "CERTIFIED")
    sub_rights = sum(s["investor_share_cents"]
                     for s in q.income_of(production["id"])
                     if s["status"] == "ALLOCATED")
    reserve_rel = sum(c["reserve_released_cents"]
                      for c in q.notices_of(production["id"])
                      if c["status"] == "SETTLED")
    return wrap_profit + sub_rights + reserve_rel


def subsidiary_rights_receivable(production):
    return sum(rhu_int(Decimal(s["gross_income_cents"])
                       * production["subsidiary_rights_investor_share_pct"])
               for s in q.income_of(production["id"])
               if s["status"] == "RECORDED")


def recoupment_progress(ctx, production):
    """CASH_BASIS variant: authoritative, persisted, may flip
    recoupment_status (SCAFFOLD recoupment_progress / PRD 3.8)."""
    ctx.watch(production)
    target = production["capitalization_target_cents"]
    recouped = cash_basis(production)
    production["recouped_amount_cents"] = recouped
    production["recoupment_pct"] = rhu(db.div(recouped, target), 4)
    production["recoupment_status"] = (
        "RECOUPED" if recouped >= target else "UNRECOUPED")
    production["distributed_total_cents"] = sum(
        d["total_amount_cents"] for d in q.distributions_of(production["id"])
        if d["status"] in ("DECLARED", "PAID"))
    production["distributable_cash_cents"] = max(
        0, recouped - production["distributed_total_cents"])

    # cascade onto every capital account: basis + credit snapshot
    basis = ("NET_PROFIT" if production["recoupment_status"] == "RECOUPED"
             else "RECOUPMENT_RETURN")
    for account in q.accounts_of(production["id"]):
        ctx.watch(account)
        account["basis"] = basis
    refresh_recoupment_credits(ctx, production)


def recoupment_report(production):
    """Both variants side by side; a pure read that persists nothing."""
    target = production["capitalization_target_cents"]
    cash = cash_basis(production)
    receivable = subsidiary_rights_receivable(production)
    accrual = cash - production["deferred_royalty_cents"] + receivable
    distributed = sum(d["total_amount_cents"]
                      for d in q.distributions_of(production["id"])
                      if d["status"] in ("DECLARED", "PAID"))
    return {
        "production_id": production["id"],
        "capitalization_target_cents": target,
        "cash_basis_recouped_cents": cash,
        "cash_basis_recoupment_pct": float(rhu(db.div(cash, target), 4)),
        "accrual_basis_recouped_cents": accrual,
        "accrual_basis_recoupment_pct": float(rhu(db.div(accrual, target), 4)),
        "deferred_royalty_cents": production["deferred_royalty_cents"],
        "subsidiary_rights_receivable_cents": receivable,
        "recoupment_status": ("RECOUPED" if cash >= target else "UNRECOUPED"),
        "distributable_cash_cents": max(0, cash - distributed),
    }


# =================================================== subsidiary rights share
def subsidiary_rights_investor_share(income, production):
    return rhu_int(Decimal(income["gross_income_cents"])
                   * production["subsidiary_rights_investor_share_pct"])


# ==================================================== distribution allocation
def distribution_allocation(production, total_amount_cents):
    """SCAFFOLD distribution_allocation / PRD 3.9.  Returns the frozen
    breakdown or None when there is no payee set."""
    accounts = [a for a in q.accounts_of(production["id"])
                if a["units_total"] > 0]
    if not accounts:
        return None
    ordered = sorted(accounts, key=lambda a: (-a["units_total"], a["_seq"]))
    shares = {}
    running = 0
    for account in ordered:
        amount = rhu_int(Decimal(total_amount_cents) * account["ownership_pct"])
        shares[account["id"]] = amount
        running += amount
    shares[ordered[0]["id"]] += total_amount_cents - running
    return [{"investor_account_id": a["id"],
             "investor_id": a["investor_id"],
             "amount_cents": shares[a["id"]]} for a in ordered]


# =================================================== closing reserve settlement
def closing_reserve_settlement(production, closing_costs_cents):
    balance = sum(line["amount_cents"]
                  for line in q.budget_lines_of(production["id"])
                  if line["component"] == "RESERVE"
                  and line["commitment_status"] == "COMMITTED")
    return {
        "reserve_balance_at_settlement_cents": balance,
        "reserve_released_cents": max(0, balance - closing_costs_cents),
        "closing_cost_shortfall_cents": max(0, closing_costs_cents - balance),
    }


# ========================================================= break-even analysis
BREAK_EVEN_WALK_LIMIT = 100


def break_even_analysis(production, operating_budget, theatre):
    v = operating_budget["variable_cost_pct"]
    eligible = q.eligible_participants(production["id"])
    floor_cents = sum(p["min_guarantee_cents"] for p in eligible)
    target = (operating_budget["weekly_fixed_running_cost_cents"]
              + floor_cents + 1)

    gross = db.ceil_div(target, Decimal(1) - v)
    steps = 0
    while (gross > 0
           and (gross - 1) - rhu_int(Decimal(gross - 1) * v) >= target
           and steps < BREAK_EVEN_WALK_LIMIT):
        gross -= 1
        steps += 1
    steps = 0
    while (gross - rhu_int(Decimal(gross) * v) < target
           and steps < BREAK_EVEN_WALK_LIMIT):
        gross += 1
        steps += 1

    capacity = (theatre["seat_count"] * theatre["top_ticket_price_cents"]
                * operating_budget["performances_per_week"])
    pct = rhu(db.div(gross, capacity), 4)

    certified = [w for w in q.wraps_of(production["id"])
                 if w["status"] == "CERTIFIED"]
    certified.sort(key=lambda w: (w["week_ending_date"], w["_seq"]),
                   reverse=True)
    weeks = None
    if certified and certified[0]["weekly_operating_profit_cents"] > 0:
        remaining = max(0, production["capitalization_target_cents"]
                        - production["recouped_amount_cents"])
        weeks = db.ceil_div(
            remaining, certified[0]["weekly_operating_profit_cents"])

    return {
        "production_id": production["id"],
        "operating_budget_id": operating_budget["id"],
        "royalty_min_guarantee_floor_cents": floor_cents,
        "target_adjusted_gross_cents": target,
        "break_even_gross_cents": gross,
        "capacity_gross_projection_cents": capacity,
        "break_even_paid_capacity_pct": float(pct),
        "weeks_to_recoup_at_last_certified_run_rate": weeks,
    }
