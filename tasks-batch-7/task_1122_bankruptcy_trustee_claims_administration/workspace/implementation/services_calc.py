"""Calculation services (SCAFFOLD Table 3 / PRD §3).

- trustee_commission_326: four-tier §326(a)-style commission, integer division
  per tier (floor each tier, then sum).
- waterfall_allocation: distribution cascade across priority classes with
  per-class pro-rata splits, floor per claim, remainder-to-last claim
  (order pinned by claim_number ASC).
- final report totals.
"""
import uuid
from datetime import timedelta

import db
from errors import ApiError, ERR_NO_FUNDS_TO_DISTRIBUTE
from logical_clock import CLOCK
from services_common import new_entity

CLASS_ORDER = ["SECURED", "PRIORITY_TAX", "PRIORITY_WAGE", "PRIORITY_CONSUMER", "GENERAL_UNSECURED"]

# §326(a) tier caps in cents
T1_CAP = 500_000        # first $5,000
T2_CAP = 4_500_000      # next $45,000
T3_CAP = 95_000_000     # next $950,000
T3_CUM = 5_000_000      # cumulative basis at start of tier 3
T4_CUM = 100_000_000    # cumulative basis at start of tier 4 ($1,000,000)


def commission_326(basis_cents: int) -> int:
    """§326(a)-style tiered commission; each tier floored by integer division
    before summation (order pinned)."""
    b = basis_cents
    tier1 = min(b, T1_CAP) * 25 // 100
    tier2 = min(max(b - T1_CAP, 0), T2_CAP) * 10 // 100
    tier3 = min(max(b - T3_CUM, 0), T3_CAP) * 5 // 100
    tier4 = max(b - T4_CUM, 0) * 3 // 100
    return tier1 + tier2 + tier3 + tier4


def disbursed_basis(case_id: str) -> int:
    """DISBURSED basis: POSTED dividends + PAID non-trustee fee approved amounts."""
    total = 0
    for div in db.dividends.values():
        plan = db.plans.get(div["plan_id"])
        if plan and plan["case_id"] == case_id and div["status"] == "POSTED":
            total += div["amount_cents"]
    for fee in db.fees.values():
        if (fee["case_id"] == case_id and fee["status"] == "PAID"
                and fee["applicant_role"] != "TRUSTEE"):
            total += fee["approved_amount_cents"] or 0
    return total


def proposed_basis(case_id: str) -> int:
    """PROPOSED basis: allocated cents across the case's CONFIRMED plan."""
    total = 0
    for plan in db.plans.values():
        if plan["case_id"] == case_id and plan["status"] == "CONFIRMED":
            for alloc in db.allocations.values():
                if alloc["plan_id"] == plan["id"]:
                    total += alloc["allocated_cents"]
    return total


def approved_unpaid_fees(case_id: str) -> int:
    total = 0
    for fee in db.fees.values():
        if fee["case_id"] == case_id and fee["status"] == "APPROVED":
            total += fee["approved_amount_cents"] or 0
    return total


def objected_reserve_by_class(case_id: str):
    reserve = {c: 0 for c in CLASS_ORDER}
    for cl in db.claims.values():
        if cl["case_id"] == case_id and cl["status"] == "OBJECTED":
            reserve[cl["priority_class"]] += cl["filed_amount_cents"]
    return reserve


def distributable_pool(case) -> int:
    """estate cash - objected reserve - approved-but-unpaid fees (current state)."""
    reserve = objected_reserve_by_class(case["id"])
    pool = case["estate_cash_on_hand_cents"] - sum(reserve.values()) - approved_unpaid_fees(case["id"])
    return pool


def register_claim_number(claim):
    """Insert into the case register ordered by (received_at, creditor.created_at,
    claim.created_at, insertion seq) and renumber sequentially from 1."""
    case_claims = [c for c in db.claims.values() if c["case_id"] == claim["case_id"]]

    def key(c):
        cred = db.creditors.get(c["creditor_id"])
        cred_created = cred["created_at"] if cred else c["created_at"]
        return (c["received_at"], cred_created, c["created_at"], c["_seq"])

    case_claims.sort(key=key)
    for i, c in enumerate(case_claims, 1):
        c["claim_number"] = i


def run_waterfall(case, plan):
    """Compute PlanClassAllocation rows and COMPUTED Dividend rows for a plan
    being confirmed. Runs against current case state (PRD §3.6: the waterfall
    is computed at confirm, not at proposal)."""
    pool = distributable_pool(case)
    if pool <= 0:
        raise ApiError(ERR_NO_FUNDS_TO_DISTRIBUTE, 409, "Distributable pool is not positive.")

    # Per-class shares: (claim, share_amount). Secured claims cap at the securing
    # asset's realized proceeds; the deficiency spills into GENERAL_UNSECURED.
    shares = {c: [] for c in CLASS_ORDER}
    allowed = [c for c in db.claims.values()
               if c["case_id"] == case["id"] and c["status"] == "ALLOWED"]
    allowed.sort(key=lambda c: (c["claim_number"], c["_seq"]))
    for cl in allowed:
        amount = cl["allowed_amount_cents"]
        if cl["priority_class"] == "SECURED":
            asset = db.assets.get(cl["secured_by_asset_id"]) if cl["secured_by_asset_id"] else None
            cap = asset["realized_proceeds_cents"] if asset else 0
            secured_share = min(amount, cap)
            deficiency = amount - secured_share
            if secured_share > 0:
                shares["SECURED"].append((cl, secured_share))
            if deficiency > 0:
                shares["GENERAL_UNSECURED"].append((cl, deficiency))
        else:
            if amount > 0:
                shares[cl["priority_class"]].append((cl, amount))

    remaining = pool
    for cls in CLASS_ORDER:
        class_shares = shares[cls]
        need = sum(amount for _, amount in class_shares)
        grant = min(need, remaining)
        remaining -= grant
        if grant <= 0:
            continue
        alloc = new_entity({
            "plan_id": plan["id"],
            "case_id": case["id"],
            "priority_class": cls,
            "allocated_cents": grant,
            "paid_total_cents": 0,
        })
        db.allocations[alloc["id"]] = alloc
        running = 0
        last_index = len(class_shares) - 1
        for i, (cl, amount) in enumerate(class_shares):
            if grant == need:
                div_amount = amount
            elif i < last_index:
                div_amount = amount * grant // need
            else:
                div_amount = grant - running  # remainder-to-last rule
            running += div_amount
            div = new_entity({
                "plan_id": plan["id"],
                "claim_id": cl["id"],
                "amount_cents": div_amount,
                "status": "COMPUTED",
                "_allocation_id": alloc["id"],
            })
            db.dividends[div["id"]] = div


def maybe_enter_final_report(case):
    """When the case's last active plan is FULLY_DISTRIBUTED (no other plan in
    PROPOSED/CONFIRMED/EXECUTING), the case moves DISTRIBUTION -> FINAL_REPORT
    and a DRAFT FinalReport is created with computed totals (PRD §3.8)."""
    if case["status"] != "DISTRIBUTION":
        return
    for plan in db.plans.values():
        if plan["case_id"] == case["id"] and plan["status"] in ("PROPOSED", "CONFIRMED", "EXECUTING"):
            return
    plans = [p for p in db.plans.values() if p["case_id"] == case["id"]]
    if not plans or not any(p["status"] == "FULLY_DISTRIBUTED" for p in plans):
        return
    if any(r["case_id"] == case["id"] for r in db.reports.values()):
        return
    case["status"] = "FINAL_REPORT"

    receipts = 0
    for sale in db.sales.values():
        if sale["case_id"] == case["id"] and sale["proceeds_status"] == "POSTED":
            receipts += sale["net_proceeds_cents"]
    for dep in db.deposits.values():
        if dep["case_id"] == case["id"] and dep["status"] == "POSTED":
            receipts += dep["amount_cents"]
    dividends_total = 0
    for div in db.dividends.values():
        plan = db.plans.get(div["plan_id"])
        if plan and plan["case_id"] == case["id"] and div["status"] == "POSTED":
            dividends_total += div["amount_cents"]
    fees_total = 0
    for fee in db.fees.values():
        if fee["case_id"] == case["id"] and fee["status"] == "PAID":
            fees_total += fee["approved_amount_cents"] or 0

    report = {
        "id": str(uuid.uuid4()),
        "case_id": case["id"],
        "total_receipts_cents": receipts,
        "total_dividends_cents": dividends_total,
        "total_fees_cents": fees_total,
        "unclaimed_funds_cents": receipts - dividends_total - fees_total,
        "status": "DRAFT",
        "created_at": CLOCK.now(),
        "_seq": db.next_seq(),
    }
    db.reports[report["id"]] = report


def add_days(dt, days):
    return dt + timedelta(days=days)
