"""Derived-field computation and entity serialization (PRD 2.10)."""
import db
from services import calc

# Non-terminal proposal states (count toward JobPosting.proposal_count).
PROPOSAL_LIVE = {"SUBMITTED", "COUNTERED"}
# Non-terminal milestone states (open_milestone_count).
MILESTONE_TERMINAL = {"RELEASED", "REFUNDED", "CANCELLED"}
# Non-terminal dispute states (open_dispute_count).
DISPUTE_TERMINAL = {"RESOLVED", "WITHDRAWN"}


# --------------------------------------------------------------------------
# Milestone escrow derivations (PRD 2.9)
# --------------------------------------------------------------------------
def milestone_escrow(milestone_id):
    funded = 0
    released = 0
    refunded = 0
    for txn in db.escrow_transactions.values():
        if txn["milestone_id"] != milestone_id:
            continue
        if txn["txn_type"] == "FUND":
            if txn["status"] == "HELD":
                funded += txn["amount_cents"]
        elif txn["txn_type"] == "RELEASE":
            if txn["status"] == "SETTLED":
                released += txn["amount_cents"]
        elif txn["txn_type"] == "REFUND":
            if txn["status"] == "SETTLED":
                refunded += txn["amount_cents"]
    return funded, released, refunded


def milestone_funded_cents(milestone_id):
    funded, _, _ = milestone_escrow(milestone_id)
    return funded


# --------------------------------------------------------------------------
# Freelancer derivations (PRD 3.1)
# --------------------------------------------------------------------------
def freelancer_completed_count(freelancer_id):
    return sum(
        1 for c in db.contracts.values()
        if c["freelancer_id"] == freelancer_id and c["status"] == "COMPLETED"
    )


def freelancer_dispute_loss_count(freelancer_id):
    """Disputes resolved CLIENT_FAVOR or SPLIT against this freelancer."""
    count = 0
    for d in db.disputes.values():
        if d["status"] != "RESOLVED":
            continue
        if d["resolution"] not in ("CLIENT_FAVOR", "SPLIT"):
            continue
        contract = db.contracts.get(d["contract_id"])
        if contract and contract["freelancer_id"] == freelancer_id:
            count += 1
    return count


def freelancer_client_avg_rating(freelancer_id):
    ratings = [
        r["rating"] for r in db.reviews.values()
        if r["freelancer_id"] == freelancer_id and r["author_role"] == "CLIENT"
    ]
    if not ratings:
        return 0.0, False
    return sum(ratings) / len(ratings), True


def recompute_freelancer_reputation(freelancer):
    """Recompute and store reputation_score and fee_tier on a freelancer."""
    fid = freelancer["id"]
    completed = freelancer_completed_count(fid)
    losses = freelancer_dispute_loss_count(fid)
    avg, has = freelancer_client_avg_rating(fid)
    freelancer["reputation_score"] = calc.reputation_score(completed, losses, avg, has)
    freelancer["fee_tier"] = calc.fee_tier(freelancer["lifetime_earnings_cents"])
    db.touch(freelancer)


def freelancer_lifetime_gross_billed(freelancer_id):
    total = 0
    for p in db.payouts.values():
        if p["freelancer_id"] == freelancer_id:
            total += p["gross_cents"]
    return total


# --------------------------------------------------------------------------
# Client derivations (PRD 2.9)
# --------------------------------------------------------------------------
def client_escrow_held(client_id):
    held = 0
    for c in db.contracts.values():
        if c["client_id"] != client_id:
            continue
        for m in db.milestones.values():
            if m["contract_id"] == c["id"]:
                held += milestone_funded_cents(m["id"])
    return held


# --------------------------------------------------------------------------
# Contract derivations
# --------------------------------------------------------------------------
def contract_open_milestone_count(contract_id):
    return sum(
        1 for m in db.milestones.values()
        if m["contract_id"] == contract_id and m["status"] not in MILESTONE_TERMINAL
    )


def contract_open_dispute_count(contract_id):
    return sum(
        1 for d in db.disputes.values()
        if d["contract_id"] == contract_id and d["status"] not in DISPUTE_TERMINAL
    )


# --------------------------------------------------------------------------
# Serializers
# --------------------------------------------------------------------------
def _strip(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def client_view(c):
    out = _strip(c)
    held = client_escrow_held(c["id"])
    out["escrow_held_cents"] = held
    out["lifetime_funded_cents"] = c["lifetime_funded_cents"]
    return out


def freelancer_view(f):
    out = _strip(f)
    out["lifetime_gross_billed_cents"] = freelancer_lifetime_gross_billed(f["id"])
    out["completed_contract_count"] = freelancer_completed_count(f["id"])
    out["dispute_loss_count"] = freelancer_dispute_loss_count(f["id"])
    return out


def job_posting_view(j):
    out = _strip(j)
    out["proposal_count"] = sum(
        1 for p in db.proposals.values()
        if p["job_posting_id"] == j["id"] and p["status"] in PROPOSAL_LIVE
    )
    return out


def proposal_view(p):
    return _strip(p)


def contract_view(c):
    out = _strip(c)
    total_released = 0
    total_refunded = 0
    for m in db.milestones.values():
        if m["contract_id"] != c["id"]:
            continue
        _, rel, ref = milestone_escrow(m["id"])
        total_released += rel
        total_refunded += ref
    out["total_released_cents"] = total_released
    out["total_refunded_cents"] = total_refunded
    out["open_milestone_count"] = contract_open_milestone_count(c["id"])
    out["open_dispute_count"] = contract_open_dispute_count(c["id"])
    return out


def milestone_view(m):
    out = _strip(m)
    funded, released, refunded = milestone_escrow(m["id"])
    out["funded_cents"] = funded
    out["released_gross_cents"] = released
    out["refunded_cents"] = refunded
    return out


def timelog_view(t):
    return _strip(t)


def escrow_view(e):
    return _strip(e)


def dispute_view(d):
    return _strip(d)


def payout_view(p):
    return _strip(p)


def review_view(r):
    return _strip(r)


def tax_record_view(t):
    return _strip(t)
