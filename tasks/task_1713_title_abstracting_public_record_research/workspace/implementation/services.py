"""Business logic: fee ledger, liability cap, SLA clock, scope window,
chain-of-title derivation, computed read-time fields, and the order
search-completion guard."""

from datetime import date, timedelta

import db
from util import rhu, parse_date, dt_of_stored

# --- Fee / SLA constants (scaffold section 1.3) ---
BASE_FEE_CENTS = 40000
PER_DOCUMENT_FEE_CENTS = 2500
PER_PAGE_FEE_CENTS = 125
ESTIMATED_DOCUMENT_COUNT = 8
RUSH_PREMIUM_PCT_NUM = 25   # 0.25
RUSH_PREMIUM_PCT_DEN = 100
LATE_CREDIT_PCT_NUM = 10    # 0.10
LATE_CREDIT_PCT_DEN = 100
LIABILITY_MULT = {"STANDARD": 3, "EXTENDED": 5}
ABSOLUTE_CAP_CENTS = 200000
SLA_HOURS = {"STANDARD": 72, "RUSH": 24}

TERMINAL_ORDER_STATES = ("DELIVERED", "CANCELLED")

ACTIVE_REPORT_STATES = ("DRAFT", "SUBMITTED", "UNDER_REVIEW", "REVISION_REQUIRED", "APPROVED")


# ---------------------------------------------------------------------------
# Collections helpers
# ---------------------------------------------------------------------------

def assignments_of_order(order_id):
    return [a for a in db.all_of("assignments") if a["order_id"] == order_id]


def documents_of_order(order_id):
    return [d for d in db.all_of("documents") if d["order_id"] == order_id]


def documents_of_assignment(assignment_id):
    return [d for d in db.all_of("documents") if d["assignment_id"] == assignment_id]


def checks_of_order(order_id):
    return [c for c in db.all_of("checks") if c["order_id"] == order_id]


def reports_of_order(order_id):
    return [r for r in db.all_of("reports") if r["order_id"] == order_id]


def curatives_of_order(order_id):
    return [c for c in db.all_of("curatives") if c["order_id"] == order_id]


def retrievals_of_order(order_id):
    return [r for r in db.all_of("retrievals") if r["order_id"] == order_id]


# ---------------------------------------------------------------------------
# Scope window (calculation document_scope)
# ---------------------------------------------------------------------------

def compute_scope_start(effective_date_str, search_period_years):
    """effective_date minus search_period_years calendar years (same
    month-day; Feb 29 clamps to Feb 28)."""
    eff = parse_date(effective_date_str, "effective_date")
    try:
        start = eff.replace(year=eff.year - int(search_period_years))
    except ValueError:
        start = eff.replace(year=eff.year - int(search_period_years), day=28)
    return start.isoformat()


def compute_in_scope(order, recording_date_str):
    """Both bounds inclusive: scope_start_date <= recording_date <= effective_date."""
    rec = parse_date(recording_date_str, "recording_date")
    start = date.fromisoformat(order["scope_start_date"])
    end = date.fromisoformat(order["effective_date"])
    return start <= rec <= end


# ---------------------------------------------------------------------------
# Chain of title (calculation chain_break_detection)
# ---------------------------------------------------------------------------

def compute_chain_break(instrument_type, grantor_name, prior_document):
    if instrument_type != "DEED" or prior_document is None:
        return False
    return grantor_name.strip() != prior_document["grantee_name"].strip()


# ---------------------------------------------------------------------------
# Fee ledger (calculations order_fee_provisional / order_fee_actualization /
# liability_cap)
# ---------------------------------------------------------------------------

def compute_provisional(sla_tier):
    """Creation-time quote: base + estimated retrieval allowance, plus the
    rush premium on that subtotal when RUSH."""
    subtotal = BASE_FEE_CENTS + ESTIMATED_DOCUMENT_COUNT * PER_DOCUMENT_FEE_CENTS
    premium = rhu(subtotal * RUSH_PREMIUM_PCT_NUM, RUSH_PREMIUM_PCT_DEN) if sla_tier == "RUSH" else 0
    return subtotal + premium


def compute_initial_accrued(sla_tier):
    """Running ledger at creation: base fee only, plus rush premium on the
    base alone when RUSH (the estimated allowance is quote-only)."""
    premium = rhu(BASE_FEE_CENTS * RUSH_PREMIUM_PCT_NUM, RUSH_PREMIUM_PCT_DEN) if sla_tier == "RUSH" else 0
    return BASE_FEE_CENTS + premium


def compute_liability_cap(liability_tier, fee_basis):
    return min(LIABILITY_MULT[liability_tier] * fee_basis, ABSOLUTE_CAP_CENTS)


def recompute_order_fees(order):
    """order_fee_actualization + liability_cap. The rush premium is computed
    exactly once on the whole subtotal (base + full retrieval sum); per-line
    premium rounding is a forbidden variant."""
    retrieval_sum = sum(
        r["fee_cents"] or 0
        for r in retrievals_of_order(order["id"])
        if r["status"] in ("FEE_POSTED", "INVOICED")
    )
    subtotal = BASE_FEE_CENTS + retrieval_sum
    premium = rhu(subtotal * RUSH_PREMIUM_PCT_NUM, RUSH_PREMIUM_PCT_DEN) if order["sla_tier"] == "RUSH" else 0
    order["accrued_fees_cents"] = subtotal + premium
    fee_basis = order["final_fee_cents"] if order["final_fee_cents"] is not None else order["accrued_fees_cents"]
    order["liability_cap_cents"] = compute_liability_cap(order["liability_tier"], fee_basis)


def compute_due_at(received_at_dt, sla_tier):
    return received_at_dt + timedelta(hours=SLA_HOURS[sla_tier])


# ---------------------------------------------------------------------------
# Read-time computed fields
# ---------------------------------------------------------------------------

def order_legal_hold(order_id):
    return any(c["status"] == "MISMATCH" for c in checks_of_order(order_id))


def order_open_curative_count(order_id):
    return sum(1 for c in curatives_of_order(order_id) if c["status"] == "OPEN")


def order_is_overdue(order):
    if order["status"] in TERMINAL_ORDER_STATES:
        return False
    return db.now() > dt_of_stored(order["due_at"])


def assignment_document_count(assignment_id):
    return sum(1 for d in documents_of_assignment(assignment_id) if d["status"] != "VOID")


def assignment_verified_count(assignment_id):
    return sum(1 for d in documents_of_assignment(assignment_id) if d["status"] == "VERIFIED")


# ---------------------------------------------------------------------------
# Serializers (stored fields + read-time computed fields)
# ---------------------------------------------------------------------------

def order_view(order):
    out = db.public(order)
    out["is_overdue"] = order_is_overdue(order)
    out["open_curative_count"] = order_open_curative_count(order["id"])
    out["legal_hold"] = order_legal_hold(order["id"])
    return out


def assignment_view(assignment):
    out = db.public(assignment)
    out["document_count"] = assignment_document_count(assignment["id"])
    out["verified_count"] = assignment_verified_count(assignment["id"])
    return out


def document_view(document):
    out = db.public(document)
    order = db.get("orders", document["order_id"])
    out["in_scope"] = compute_in_scope(order, document["recording_date"]) if order else False
    return out


def check_view(check):
    return db.public(check)


def report_view(report):
    return db.public(report)


def curative_view(curative):
    return db.public(curative)


def retrieval_view(retrieval):
    return db.public(retrieval)


# ---------------------------------------------------------------------------
# Order search-completion guard (SEARCH_IN_PROGRESS -> SEARCH_COMPLETE)
# ---------------------------------------------------------------------------

def reevaluate_search_completion(order):
    """Re-evaluated after every assignment acceptance and after every
    legal-hold clear. Advances the order and bumps its version when the
    guard passes."""
    if order["status"] != "SEARCH_IN_PROGRESS":
        return
    live = [a for a in assignments_of_order(order["id"]) if a["status"] != "CANCELLED"]
    if not live:
        return
    if not all(a["status"] == "ACCEPTED" for a in live):
        return
    if order_legal_hold(order["id"]):
        return
    order["status"] = "SEARCH_COMPLETE"
    db.touch(order)


# ---------------------------------------------------------------------------
# Shared guards
# ---------------------------------------------------------------------------

def order_of(entity):
    return db.get("orders", entity["order_id"])
