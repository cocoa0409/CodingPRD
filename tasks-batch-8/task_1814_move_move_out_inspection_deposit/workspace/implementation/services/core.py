"""Core shared services: record lifecycle, ledger recompute, occupancy,
statement projections, and settlement evaluation.

Aggregates are recomputed from the source collections on every mutation so
the deposit-ledger invariant of PRD §2.7 holds by construction.
"""
from db import db
from util import new_id, now_ts

# Monotonic insertion counter — stable tie-break for created_at sorting.
_SEQ = {"n": 0}


def new_record(collection, fields):
    global _SEQ
    rec = dict(fields)
    rec["id"] = new_id()
    ts = now_ts()
    rec["created_at"] = ts
    rec["updated_at"] = ts
    rec["version"] = 1
    _SEQ["n"] += 1
    rec["_seq"] = _SEQ["n"]
    db[collection][rec["id"]] = rec
    return rec


def touch(rec):
    """Every mutation refreshes updated_at and increments version (PRD §2.4)."""
    rec["updated_at"] = now_ts()
    rec["version"] = rec.get("version", 1) + 1


def public(rec):
    if rec is None:
        return None
    return {k: v for k, v in rec.items() if not k.startswith("_")}


# ---------------------------------------------------------------------------
# Reference chains
# ---------------------------------------------------------------------------

def tenancy_of(rec):
    return db["tenancies"].get(rec["tenancy_id"])


def unit_for_tenancy(tenancy):
    return db["units"].get(tenancy["unit_id"])


def property_for_tenancy(tenancy):
    unit = unit_for_tenancy(tenancy)
    return db["properties"].get(unit["property_id"]) if unit else None


def jurisdiction_for_tenancy(tenancy):
    prop = property_for_tenancy(tenancy)
    return db["jurisdiction_profiles"].get(prop["jurisdiction_profile_id"]) if prop else None


# ---------------------------------------------------------------------------
# Unit occupancy derivation (calculation: unit_occupancy_derivation)
# ---------------------------------------------------------------------------

def recompute_unit_occupancy(unit_id):
    """Derived from non-terminal tenancies; touch the unit only on change."""
    unit = db["units"].get(unit_id)
    if unit is None:
        return
    live = [
        t for t in db["tenancies"].values()
        if t["unit_id"] == unit_id and t["status"] not in ("SETTLED", "ESCHEATED")
    ]
    if any(t["status"] == "OCCUPIED" for t in live):
        new_status = "OCCUPIED"
    elif any(t["status"] in ("NOTICE_GIVEN", "PENDING_MOVE_IN") for t in live):
        new_status = "RESERVED"
    else:
        new_status = "AVAILABLE"
    if unit["occupancy_status"] != new_status:
        unit["occupancy_status"] = new_status
        touch(unit)


# ---------------------------------------------------------------------------
# Statement helpers
# ---------------------------------------------------------------------------

def current_statement(tenancy_id):
    """The tenancy's current statement: latest statement_seq. The latest is
    never SUPERSEDED (supersession only happens when a newer one is created)."""
    stmts = [s for s in db["statements"].values() if s["tenancy_id"] == tenancy_id]
    if not stmts:
        return None
    return max(stmts, key=lambda s: s["statement_seq"])


def active_dispute_for(statement_id):
    """A dispute in OPEN, MANAGER_COUNTERED, or ESCALATED_SMALL_CLAIMS."""
    for d in db["disputes"].values():
        if d["statement_id"] == statement_id and d["status"] in (
            "OPEN", "MANAGER_COUNTERED", "ESCALATED_SMALL_CLAIMS",
        ):
            return d
    return None


def refresh_draft_statement_projection(tenancy):
    """Cascade link: while DRAFT, a statement's projections shadow the
    tenancy's live pending figures (PRD §3.4/§3.5)."""
    draft = next(
        (s for s in db["statements"].values()
         if s["tenancy_id"] == tenancy["id"] and s["status"] == "DRAFT"),
        None,
    )
    if draft is None:
        return
    new_proj_ded = tenancy["pending_deductions_cents"]
    new_proj_ref = (
        tenancy["deposit_cents"]
        + tenancy["interest_accrued_cents"]
        - new_proj_ded
    )
    if (draft["projected_deductions_cents"] != new_proj_ded
            or draft["projected_refund_cents"] != new_proj_ref):
        draft["projected_deductions_cents"] = new_proj_ded
        draft["projected_refund_cents"] = new_proj_ref
        touch(draft)


# ---------------------------------------------------------------------------
# Deposit ledger (calculation: deposit_reconciliation, PRD §2.7)
# ---------------------------------------------------------------------------

def recompute_tenancy_money(tenancy_id):
    """Recompute every money aggregate of the tenancy from source records.

    total_deductions_cents  = sum of BILLED DeductionItems
    pending_deductions_cents = sum of DRAFT DeductionItems
    refund_paid_cents       = sum of CASHED REFUND disbursements
    penalty_paid_cents      = sum of CASHED PENALTY disbursements (outside ledger)
    escheated_cents         = sum of ESCHEATED disbursements
    reserved_cents          = sum of SENT REFUND disbursements
    released_cents          = mirrors the current statement's released_cents
    balance_remaining_cents = deposit + interest - total + released
                              - refund_paid - escheated - reserved
    """
    t = db["tenancies"].get(tenancy_id)
    if t is None:
        return None
    t["total_deductions_cents"] = sum(
        d["amount_cents"] for d in db["deductions"].values()
        if d["tenancy_id"] == tenancy_id and d["status"] == "BILLED"
    )
    t["pending_deductions_cents"] = sum(
        d["amount_cents"] for d in db["deductions"].values()
        if d["tenancy_id"] == tenancy_id and d["status"] == "DRAFT"
    )
    t["refund_paid_cents"] = sum(
        x["amount_cents"] for x in db["disbursements"].values()
        if x["tenancy_id"] == tenancy_id and x["kind"] == "REFUND" and x["status"] == "CASHED"
    )
    t["penalty_paid_cents"] = sum(
        x["amount_cents"] for x in db["disbursements"].values()
        if x["tenancy_id"] == tenancy_id and x["kind"] == "PENALTY" and x["status"] == "CASHED"
    )
    t["escheated_cents"] = sum(
        x["amount_cents"] for x in db["disbursements"].values()
        if x["tenancy_id"] == tenancy_id and x["status"] == "ESCHEATED"
    )
    t["reserved_cents"] = sum(
        x["amount_cents"] for x in db["disbursements"].values()
        if x["tenancy_id"] == tenancy_id and x["kind"] == "REFUND" and x["status"] == "SENT"
    )
    cur = current_statement(tenancy_id)
    t["released_cents"] = cur["released_cents"] if cur is not None else 0
    t["balance_remaining_cents"] = (
        t["deposit_cents"]
        + t["interest_accrued_cents"]
        - t["total_deductions_cents"]
        + t["released_cents"]
        - t["refund_paid_cents"]
        - t["escheated_cents"]
        - t["reserved_cents"]
    )
    return t


def recompute_statement_refund_due(statement):
    """statement_totals post-issuance form (PRD §3.5):
    refund_due = deposit + interest - deduction_total + released."""
    tenancy = db["tenancies"].get(statement["tenancy_id"])
    statement["refund_due_cents"] = (
        tenancy["deposit_cents"]
        + statement["interest_cents"]
        - statement["deduction_total_cents"]
        + statement["released_cents"]
    )


def evaluate_settlement(statement):
    """Automatic ISSUED -> SETTLED (and tenancy VACATED -> SETTLED bubble-up)
    when refund_paid_cents >= refund_due_cents with no active dispute."""
    if statement is None or statement["status"] != "ISSUED":
        return
    if active_dispute_for(statement["id"]) is not None:
        return
    tenancy = db["tenancies"].get(statement["tenancy_id"])
    if tenancy["refund_paid_cents"] >= statement["refund_due_cents"]:
        statement["status"] = "SETTLED"
        touch(statement)
        if tenancy["status"] == "VACATED":
            tenancy["status"] = "SETTLED"
            # tenancy is touched by the caller's operation-level bump
