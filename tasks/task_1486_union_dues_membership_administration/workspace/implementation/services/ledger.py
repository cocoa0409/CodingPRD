"""Append-only ledger postings, the payment_waterfall replay (scaffold
calculations[1]), derived member balances, and the auto-cure cascade.

Waterfall:
  Buckets in strict allocation order:
    1. REINSTATEMENT_FEE entries (oldest first, by created_at ASC)
    2. DuesAssessments ordered by period ASC, then created_at ASC
  Replay the member's full LedgerEntry stream in created_at ASC order
  (ties broken by insertion order, which is non-decreasing created_at):
  each credit (-amount) fills the earliest open bucket until exhausted;
  each charge (+amount) opens/increases its own bucket. VOID_REVERSAL entries
  carry their sign, so they negate their originals naturally in the replay.
  paid_cents(assessment) = credit applied to that bucket capped at assessed.
  ledger_balance = sum(signed amounts); arrears = max(0, bal);
  credit_balance = max(0, -bal).
"""
import db
import utils


def post_entry(member_id, entry_type, amount_cents, period, memo="",
               assessment_id=None, remittance_id=None):
    ts = db.fmt_ts(db.now())
    entry = {
        "id": utils.new_id(),
        "member_id": member_id,
        "entry_type": entry_type,
        "amount_cents": amount_cents,
        "period": period,
        "memo": memo,
        "created_at": ts,
        "_seq": db.store.next_seq(),
        "_assessment_id": assessment_id,
        "_remittance_id": remittance_id,
    }
    db.store.ledger_entries[entry["id"]] = entry
    return entry


def member_entries(member_id):
    entries = [e for e in db.store.ledger_entries.values()
               if e["member_id"] == member_id]
    entries.sort(key=lambda e: e["_seq"])
    return entries


def member_assessments(member_id):
    rows = [a for a in db.store.assessments.values()
            if a["member_id"] == member_id]
    rows.sort(key=lambda a: (a["period"], a["_seq"]))
    return rows


def waterfall(member_id):
    """Replay the member's ledger. Returns (arrears_cents, credit_balance_cents,
    paid_by_assessment, remaining_by_assessment)."""
    entries = member_entries(member_id)
    assessments = member_assessments(member_id)

    # Bucket order: REINSTATEMENT_FEE entries first (oldest first), then
    # assessments by period ASC, created_at ASC.
    fee_buckets = []
    for e in entries:
        if e["entry_type"] == "REINSTATEMENT_FEE" and e["amount_cents"] > 0:
            fee_buckets.append({"key": e["id"], "capacity": e["amount_cents"],
                                "allocated": 0})
    assess_buckets = {}
    for a in assessments:
        assess_buckets[a["id"]] = {"key": a["id"], "capacity": 0,
                                   "allocated": 0}
    for e in entries:
        if e["amount_cents"] > 0 and e["entry_type"] in (
                "ASSESSMENT_CHARGE", "SUPPLEMENTAL_CHARGE"):
            b = assess_buckets.get(e.get("_assessment_id"))
            if b is not None:
                b["capacity"] += e["amount_cents"]
    ordered = fee_buckets + [assess_buckets[a["id"]] for a in assessments]

    balance = 0
    for e in entries:
        amount = e["amount_cents"]
        balance += amount
        if amount < 0:
            remaining = -amount
            for b in ordered:
                open_amt = b["capacity"] - b["allocated"]
                if open_amt <= 0:
                    continue
                take = min(open_amt, remaining)
                b["allocated"] += take
                remaining -= take
                if remaining == 0:
                    break

    paid = {}
    remaining_map = {}
    for a in assessments:
        b = assess_buckets[a["id"]]
        paid[a["id"]] = min(b["allocated"], a["assessed_cents"])
        remaining_map[a["id"]] = b["capacity"] - b["allocated"]
    arrears = balance if balance > 0 else 0
    credit = -balance if balance < 0 else 0
    return arrears, credit, paid, remaining_map


def balances(member_id):
    arrears, credit, _, _ = waterfall(member_id)
    return arrears, credit


def paid_cents(assessment):
    _, _, paid, _ = waterfall(assessment["member_id"])
    return paid.get(assessment["id"], 0)


def auto_cure(member, remittance=None):
    """DELINQUENT -> ACTIVE cascade when arrears fall below the local's
    threshold after a credit posting: SENT notices -> CURED, DRAFT notices
    deleted; the posting remittance records the member in
    auto_cured_member_ids. Returns True when a cure fired."""
    if member["status"] != "DELINQUENT":
        return False
    local = db.store.locals[member["local_id"]]
    arrears, _ = balances(member["id"])
    if arrears >= local["delinquency_threshold_cents"]:
        return False
    member["status"] = "ACTIVE"
    for n in list(db.store.notices.values()):
        if n["member_id"] != member["id"]:
            continue
        if n["status"] == "SENT":
            n["status"] = "CURED"
            db.touch(n)
        elif n["status"] == "DRAFT":
            del db.store.notices[n["id"]]
    if remittance is not None:
        if member["id"] not in remittance["auto_cured_member_ids"]:
            remittance["auto_cured_member_ids"].append(member["id"])
    return True
