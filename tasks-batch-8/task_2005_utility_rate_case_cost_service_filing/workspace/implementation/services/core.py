"""Core shared services: record lifecycle, recomputation helpers, cascades.

Entity created_at/updated_at are stamped from the logical clock (PRD 2.6);
version starts at 1 and increments on every mutation (PRD 2.4).
"""
from db import db, next_seq
from util import CLOCK


def new_record(collection, fields):
    rec = dict(fields)
    rec["id"] = __import__("util").new_id()
    ts = CLOCK.now_iso()
    rec["created_at"] = ts
    rec["updated_at"] = ts
    rec["version"] = 1
    rec["_seq"] = next_seq()
    db[collection][rec["id"]] = rec
    return rec


def touch(rec):
    rec["updated_at"] = CLOCK.now_iso()
    rec["version"] = rec.get("version", 1) + 1


def public(rec):
    if rec is None:
        return None
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def sort_rows(rows):
    """Global list ordering: created_at ASC; cascade rows keep generation order
    via the insertion sequence (UUID id is never a sort key)."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


# ---------------------------------------------------------------------------
# TestYearEntry adjusted amount (calculations.adjusted_test_year_amount)
# ---------------------------------------------------------------------------

ADJ_COUNTING_STATUSES = ("PROPOSED", "VERIFIED", "DISPUTED", "ACCEPTED")


def recompute_entry_adjusted(entry, bump=True):
    delta = sum(
        a["amount_cents"]
        for a in db["adjustments"].values()
        if a["test_year_entry_id"] == entry["id"] and a["status"] in ADJ_COUNTING_STATUSES
    )
    new_val = entry["booked_amount_cents"] + delta
    if entry["adjusted_amount_cents"] != new_val:
        entry["adjusted_amount_cents"] = new_val
        if bump:
            touch(entry)


# ---------------------------------------------------------------------------
# SettlementProposal signature counters (VOID rows excluded from both)
# ---------------------------------------------------------------------------

def recompute_proposal_counts(proposal, bump=True):
    sigs = [
        s for s in db["settlement_signatories"].values()
        if s["settlement_proposal_id"] == proposal["id"]
    ]
    proposal["signature_count"] = sum(1 for s in sigs if s["status"] == "SIGNED")
    proposal["required_signature_count"] = sum(1 for s in sigs if s["status"] != "VOID")
    if bump:
        touch(proposal)


def proposals_of_case(case_id):
    return [p for p in db["settlement_proposals"].values() if p["rate_case_id"] == case_id]


def classes_of_case(case_id):
    return [c for c in db["customer_classes"].values() if c["rate_case_id"] == case_id]


def get_case(case_id):
    return db["rate_cases"].get(case_id)
