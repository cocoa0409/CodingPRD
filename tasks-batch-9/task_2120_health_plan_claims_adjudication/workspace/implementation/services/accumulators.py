"""Benefit accumulators: the ledger of year-to-date benefit consumption."""

from store import db


def find(member_id, plan_year):
    for acc in db.values("benefit_accumulators"):
        if acc["member_id"] == member_id and acc["plan_year"] == plan_year:
            return acc
    return None


def create(member_id, plan_year):
    return db.insert(
        "benefit_accumulators",
        {
            "member_id": member_id,
            "plan_year": plan_year,
            "deductible_applied_cents": 0,
            "oop_applied_cents": 0,
            "remitted_claim_count": 0,
        },
    )


def get_or_create(member_id, plan_year):
    return find(member_id, plan_year) or create(member_id, plan_year)


def snapshot(member_id, plan_year):
    """The pass-start reading of the accumulator; a missing row reads as zero."""
    acc = find(member_id, plan_year)
    if acc is None:
        return {"deductible_applied_cents": 0, "oop_applied_cents": 0}
    return {
        "deductible_applied_cents": acc["deductible_applied_cents"],
        "oop_applied_cents": acc["oop_applied_cents"],
    }
