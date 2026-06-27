"""Derived-field reconciliation (PRD 2.7, 2.11).

These compute derived fields from source rows. We keep the stored computed
fields on each record updated whenever inputs change, and also recompute on read
where the PRD describes them as always-current. The stored values are the source
of truth for serialization.
"""
from db import db
from clock import clock, parse_iso

COMMITTED_STATES = {"ACTIVE", "FULFILLED", "SETTLED"}


def recompute_brand_budget(brand):
    """committed_cents = sum(contracted_rate_cents) over brand's contracts in
    {ACTIVE, FULFILLED, SETTLED}; available = budget - committed (PRD 2.7)."""
    total = 0
    for c in db.contracts.values():
        if c["status"] in COMMITTED_STATES and _contract_brand_id(c) == brand["id"]:
            total += c["contracted_rate_cents"]
    brand["committed_cents"] = total
    brand["available_budget_cents"] = brand["budget_cents"] - total


def _contract_brand_id(contract):
    camp = db.campaigns.get(contract["campaign_id"])
    return camp["brand_id"] if camp else None


def recompute_campaign_committed(campaign):
    """campaign.committed_cents = sum over this campaign's contracts in
    {ACTIVE, FULFILLED, SETTLED} (PRD 2.7)."""
    total = 0
    for c in db.contracts.values():
        if c["campaign_id"] == campaign["id"] and c["status"] in COMMITTED_STATES:
            total += c["contracted_rate_cents"]
    campaign["committed_cents"] = total


def current_tax_year():
    return clock.now().year


def recompute_creator_ytd(creator):
    """ytd_paid_cents = sum(net_amount_cents) over creator's SETTLED payouts whose
    settlement clock-year falls in the current tax year (PRD 2.7, 3.9).

    The settlement year is recorded on the payout at settle time as
    `_settled_year`. Sum already-rounded per-payout nets (round-then-sum)."""
    year = current_tax_year()
    total = 0
    for p in db.payouts.values():
        if p["status"] != "SETTLED":
            continue
        contract = db.contracts.get(p["contract_id"])
        if not contract or contract["creator_id"] != creator["id"]:
            continue
        if p.get("_settled_year") == year:
            total += p["net_amount_cents"]
    creator["ytd_paid_cents"] = total


def recompute_discovery_status(creator):
    """NEW when no snapshot; DISCOVERABLE when latest fraud_score < 60;
    SUPPRESSED when latest fraud_score >= 60 (PRD 2.11, 3.2)."""
    snaps = [s for s in db.audience_snapshots.values()
             if s["creator_id"] == creator["id"]]
    if not snaps:
        creator["discovery_status"] = "NEW"
        return
    # Latest snapshot = most recent by capture (logical clock) then seq.
    latest = max(snaps, key=lambda s: (parse_iso(s["captured_at"]), s["_seq"]))
    if latest["fraud_score"] < 60:
        creator["discovery_status"] = "DISCOVERABLE"
    else:
        creator["discovery_status"] = "SUPPRESSED"


def recompute_brand_safety_status(creator):
    """CLEAR when no OPEN flag; FLAGGED when highest OPEN severity is LOW/MEDIUM;
    BLOCKED when >=1 OPEN HIGH flag (PRD 2.11, 3.10)."""
    open_flags = [f for f in db.brand_safety_flags.values()
                  if f["creator_id"] == creator["id"] and f["status"] == "OPEN"]
    if not open_flags:
        creator["brand_safety_status"] = "CLEAR"
        return
    if any(f["severity"] == "HIGH" for f in open_flags):
        creator["brand_safety_status"] = "BLOCKED"
    else:
        creator["brand_safety_status"] = "FLAGGED"


def latest_follower_count(creator_id):
    snaps = [s for s in db.audience_snapshots.values()
             if s["creator_id"] == creator_id]
    if not snaps:
        return None
    latest = max(snaps, key=lambda s: (parse_iso(s["captured_at"]), s["_seq"]))
    return latest["follower_count"]
