"""Fund waterfall allocation + reporting (calcs: fund_waterfall_allocation,
funding_report_aggregation). Fund counters are recomputed from allocation rows
so they can never drift."""

import db
from db import CLOCK


def recompute_fund_counters(fund):
    pledged = disbursed = released = 0
    for a in db.fund_allocations.values():
        if a["funding_source_id"] != fund["id"]:
            continue
        if a["status"] == "PLEDGED":
            pledged += a["amount_cents"]
        elif a["status"] == "DISBURSED":
            disbursed += a["amount_cents"]
        elif a["status"] == "RELEASED":
            released += a["amount_cents"]
    fund["pledged_cents"] = pledged
    fund["disbursed_cents"] = disbursed
    fund["released_cents"] = released
    fund["available_cents"] = fund["appropriated_cents"] - pledged - disbursed


def account_has_completed_referral(account_id):
    return any(r["account_id"] == account_id and r["status"] == "COMPLETED"
               for r in db.referrals.values())


def eligible_funds(account, enrollment):
    """OPEN + fiscal year == clock calendar year + tier eligible +
    referral constraint; ranked by priority_rank ASC, created_at ASC."""
    year = CLOCK.now().year
    tier = enrollment["tier"]
    has_referral = account_has_completed_referral(account["id"])
    out = []
    for f in db.funding_sources.values():
        if f["status"] != "OPEN":
            continue
        if f["fiscal_year"] != year:
            continue
        if tier not in f["eligible_tiers"]:
            continue
        if f["requires_completed_referral"] and not has_referral:
            continue
        out.append(f)
    out.sort(key=lambda f: (f["priority_rank"], f["created_at"], f["_seq"]))
    return out


def run_waterfall(account, enrollment, amount_cents):
    """Greedy all-or-nothing fill. Caller has already verified enrollment and
    pool sufficiency. Returns list of created allocation rows."""
    ordered = eligible_funds(account, enrollment)
    batch_id = db.new_id()
    created = []
    still_needed = amount_cents
    for f in ordered:
        if still_needed <= 0:
            break
        take = min(f["available_cents"], still_needed)
        if take <= 0:
            continue
        alloc = {
            "id": db.new_id(),
            "funding_source_id": f["id"],
            "account_id": account["id"],
            "enrollment_id": enrollment["id"],
            "amount_cents": take,
            "status": "PLEDGED",
            "batch_id": batch_id,
            "allocation_sequence": len(created) + 1,
        }
        db.stamp_common(alloc)
        db.fund_allocations[alloc["id"]] = alloc
        created.append(alloc)
        still_needed -= take
        recompute_fund_counters(f)
        db.touch(f)
    return created


def report_for(fund):
    count = sum(1 for a in db.fund_allocations.values()
                if a["funding_source_id"] == fund["id"])
    return {
        "funding_source_id": fund["id"],
        "appropriated_cents": fund["appropriated_cents"],
        "pledged_cents": fund["pledged_cents"],
        "disbursed_cents": fund["disbursed_cents"],
        "released_cents": fund["released_cents"],
        "available_cents": fund["available_cents"],
        "allocation_count": count,
    }
