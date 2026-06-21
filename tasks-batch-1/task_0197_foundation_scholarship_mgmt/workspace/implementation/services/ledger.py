"""Fund-ledger recomputation and member-count recomputation (PRD §2.7, §3)."""

import db


def recompute_fund(fund):
    """Fully recompute the fund's derived monetary fields from authoritative
    award/disbursement state. committed_cents first, then available_cents."""
    committed = 0
    for aw in db.awards.values():
        if aw["fund_id"] == fund["id"] and aw["status"] in (
                "COMMITTED", "ACTIVE", "RENEWAL_PENDING"):
            committed += aw["provisional_award_cents"]
    disbursed = 0
    for dis in db.disbursements.values():
        if dis["fund_id"] == fund["id"] and dis["status"] == "SETTLED":
            disbursed += dis["amount_cents"]
    fund["committed_cents"] = committed
    fund["disbursed_cents"] = disbursed
    fund["available_cents"] = fund["endowment_cents"] - committed


def committed_total(fund):
    committed = 0
    for aw in db.awards.values():
        if aw["fund_id"] == fund["id"] and aw["status"] in (
                "COMMITTED", "ACTIVE", "RENEWAL_PENDING"):
            committed += aw["provisional_award_cents"]
    return committed


def available_cents(fund):
    return fund["endowment_cents"] - committed_total(fund)


def recompute_member_count(member):
    """active_assignment_count = number of this member's ASSIGNED assignments."""
    count = 0
    for asg in db.committee_assignments.values():
        if asg["committee_member_id"] == member["id"] and asg["status"] == "ASSIGNED":
            count += 1
    member["active_assignment_count"] = count
