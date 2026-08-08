"""Computed fields, business calculations, and serializers.

All monetary math uses Decimal; the only fractional-cent cases are the
contingency fee and the pro-rata share (PRD §2.5).
"""
from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR

from db import store, fmt_dt

# ---- Constants (from SCAFFOLD calculations / PRD §3) ----
RISK_THRESHOLD = 50
CONFIRMED_FLAG_WEIGHT = 40
OPEN_FLAG_WEIGHT = 25
UNVERIFIED_WEIGHT = 20
REJECTED_CLAIM_WEIGHT = 15

FEE_MIN_CENTS = 500
FEE_MAX_CENTS = 25000
VERIFIED_FEE_DISCOUNT = Decimal("0.10")

PROGRAM_WINDOW_BUFFER_DAYS = 30


def round_half_up(value):
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Cross-entity lookups
# ---------------------------------------------------------------------------
def program_payouts(program_id):
    out = []
    for p in store.payouts.values():
        cl = store.claims.get(p["claim_id"])
        if cl and cl["program_id"] == program_id:
            out.append(p)
    return out


def consumer_claims(consumer_id):
    return [c for c in store.claims.values() if c["consumer_id"] == consumer_id]


def claim_flags(claim_id):
    return [f for f in store.fraud_flags.values() if f["claim_id"] == claim_id]


def consumer_flags(consumer_id):
    ids = {c["id"] for c in consumer_claims(consumer_id)}
    return [f for f in store.fraud_flags.values() if f["claim_id"] in ids]


# ---------------------------------------------------------------------------
# Computed fields
# ---------------------------------------------------------------------------
def fund_remaining(program):
    if program["status"] == "DRAFT":
        return None
    committed = sum(
        p["gross_amount_cents"]
        for p in program_payouts(program["id"])
        if p["status"] in ("INITIATED", "CLEARED", "FAILED")
    )
    return program["fund_total_cents"] - committed


def document_count(claim_id):
    return sum(1 for d in store.documents.values() if d["claim_id"] == claim_id)


def verified_document_count(claim_id):
    return sum(
        1 for d in store.documents.values()
        if d["claim_id"] == claim_id and d["status"] == "VERIFIED"
    )


def claim_fraud_status(claim_id):
    flags = claim_flags(claim_id)
    if any(f["status"] == "CONFIRMED" for f in flags):
        return "CONFIRMED"
    if any(f["status"] == "OPEN" for f in flags):
        return "FLAGGED"
    return "CLEAR"


def total_recovered(consumer_id):
    total = 0
    for c in consumer_claims(consumer_id):
        for p in store.payouts.values():
            if p["claim_id"] == c["id"] and p["status"] == "CLEARED":
                total += p["net_amount_cents"]
    return total


def risk_scores(consumer):
    flags = consumer_flags(consumer["id"])
    confirmed = sum(1 for f in flags if f["status"] == "CONFIRMED")
    openf = sum(1 for f in flags if f["status"] == "OPEN")
    rejected = sum(1 for c in consumer_claims(consumer["id"]) if c["status"] == "REJECTED")
    unverified = 0 if consumer["identity_status"] == "VERIFIED" else 1
    base = (confirmed * CONFIRMED_FLAG_WEIGHT
            + unverified * UNVERIFIED_WEIGHT
            + rejected * REJECTED_CLAIM_WEIGHT)
    optimistic = min(100, base)
    pessimistic = min(100, base + openf * OPEN_FLAG_WEIGHT)
    return optimistic, pessimistic


# ---------------------------------------------------------------------------
# Monetary calculations
# ---------------------------------------------------------------------------
def provisional_payout(claim, program):
    return min(claim["claimed_amount_cents"],
               program["advertised_amount_cents"],
               program["per_claim_cap_cents"])


def contingency_fee(gross, consumer_verified):
    """PRD §3.9 — rate tier -> raw round -> clamp -> gross cap -> loyalty discount."""
    if gross < 10000:
        rate = Decimal("0.15")
    elif gross < 50000:
        rate = Decimal("0.20")
    else:
        rate = Decimal("0.25")
    raw = round_half_up(Decimal(gross) * rate)
    clamped = min(max(raw, FEE_MIN_CENTS), FEE_MAX_CENTS)
    clamped = min(clamped, gross)
    if consumer_verified:
        return round_half_up(Decimal(clamped) * (Decimal("1") - VERIFIED_FEE_DISCOUNT))
    return clamped


def eligibility(claim, program):
    min_purchase_met = claim["claimed_amount_cents"] >= program["eligibility_min_purchase_cents"]
    if not program["requires_proof"]:
        documents_sufficient = True
    else:
        documents_sufficient = verified_document_count(claim["id"]) >= program["min_documents"]
    eligible = min_purchase_met and documents_sufficient
    reasons = []
    if not min_purchase_met:
        reasons.append("MIN_PURCHASE_NOT_MET")
    if not documents_sufficient:
        reasons.append("INSUFFICIENT_VERIFIED_DOCUMENTS")
    return min_purchase_met, documents_sufficient, eligible, reasons


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------
def ser_program(p):
    return {
        "id": p["id"],
        "created_at": fmt_dt(p["created_at"]),
        "updated_at": fmt_dt(p["updated_at"]),
        "version": p["version"],
        "name": p["name"],
        "settlement_case_id": p["settlement_case_id"],
        "category": p["category"],
        "distribution_method": p["distribution_method"],
        "fund_total_cents": p["fund_total_cents"],
        "fund_remaining_cents": fund_remaining(p),
        "advertised_amount_cents": p["advertised_amount_cents"],
        "per_claim_cap_cents": p["per_claim_cap_cents"],
        "eligibility_min_purchase_cents": p["eligibility_min_purchase_cents"],
        "requires_proof": p["requires_proof"],
        "min_documents": p["min_documents"],
        "claim_window_open_at": fmt_dt(p["claim_window_open_at"]),
        "claim_window_close_at": fmt_dt(p["claim_window_close_at"]),
        "status": p["status"],
    }


def ser_consumer(c):
    opt, pess = risk_scores(c)
    return {
        "id": c["id"],
        "created_at": fmt_dt(c["created_at"]),
        "updated_at": fmt_dt(c["updated_at"]),
        "version": c["version"],
        "email": c["email"],
        "full_name": c["full_name"],
        "identity_status": c["identity_status"],
        "total_recovered_cents": total_recovered(c["id"]),
        "optimistic_risk_score": opt,
        "pessimistic_risk_score": pess,
    }


def ser_match(m):
    return {
        "id": m["id"],
        "created_at": fmt_dt(m["created_at"]),
        "updated_at": fmt_dt(m["updated_at"]),
        "version": m["version"],
        "consumer_id": m["consumer_id"],
        "program_id": m["program_id"],
        "match_score": m["match_score"],
        "status": m["status"],
    }


def ser_claim(c):
    return {
        "id": c["id"],
        "created_at": fmt_dt(c["created_at"]),
        "updated_at": fmt_dt(c["updated_at"]),
        "version": c["version"],
        "consumer_id": c["consumer_id"],
        "program_id": c["program_id"],
        "benefit_period_start": fmt_dt(c["benefit_period_start"]),
        "benefit_period_end": fmt_dt(c["benefit_period_end"]),
        "claimed_amount_cents": c["claimed_amount_cents"],
        "provisional_payout_cents": c["provisional_payout_cents"],
        "final_payout_cents": c["final_payout_cents"],
        "contingency_fee_cents": c["contingency_fee_cents"],
        "net_payout_cents": c["net_payout_cents"],
        "eligibility_status": c["eligibility_status"],
        "fraud_status": claim_fraud_status(c["id"]),
        "document_count": document_count(c["id"]),
        "needs_info_count": c["needs_info_count"],
        "submitted_at": fmt_dt(c["submitted_at"]),
        "status": c["status"],
    }


def ser_document(d):
    return {
        "id": d["id"],
        "created_at": fmt_dt(d["created_at"]),
        "updated_at": fmt_dt(d["updated_at"]),
        "version": d["version"],
        "claim_id": d["claim_id"],
        "doc_type": d["doc_type"],
        "file_ref": d["file_ref"],
        "status": d["status"],
        "rejection_reason": d["rejection_reason"],
    }


def ser_payout(p):
    return {
        "id": p["id"],
        "created_at": fmt_dt(p["created_at"]),
        "updated_at": fmt_dt(p["updated_at"]),
        "version": p["version"],
        "claim_id": p["claim_id"],
        "gross_amount_cents": p["gross_amount_cents"],
        "fee_amount_cents": p["fee_amount_cents"],
        "net_amount_cents": p["net_amount_cents"],
        "attempt_count": p["attempt_count"],
        "status": p["status"],
    }


def ser_fraud_flag(f):
    return {
        "id": f["id"],
        "created_at": fmt_dt(f["created_at"]),
        "updated_at": fmt_dt(f["updated_at"]),
        "version": f["version"],
        "claim_id": f["claim_id"],
        "raised_by_user_id": f["raised_by_user_id"],
        "reason": f["reason"],
        "status": f["status"],
        "cleared_by_user_id": f["cleared_by_user_id"],
        "resolution_note": f["resolution_note"],
    }


def ser_fund_transaction(t):
    return {
        "id": t["id"],
        "created_at": fmt_dt(t["created_at"]),
        "program_id": t["program_id"],
        "related_claim_id": t["related_claim_id"],
        "type": t["type"],
        "amount_cents": t["amount_cents"],
        "reason": t["reason"],
        "balance_after_cents": t["balance_after_cents"],
    }


def ser_notification(n):
    return {
        "id": n["id"],
        "created_at": fmt_dt(n["created_at"]),
        "consumer_id": n["consumer_id"],
        "related_claim_id": n["related_claim_id"],
        "channel": n["channel"],
        "event_type": n["event_type"],
        "body": n["body"],
        "read": n["read"],
    }


def ser_assessment(a):
    return {
        "id": a["id"],
        "created_at": fmt_dt(a["created_at"]),
        "updated_at": fmt_dt(a["updated_at"]),
        "version": a["version"],
        "claim_id": a["claim_id"],
        "assessed_by_user_id": a["assessed_by_user_id"],
        "eligible": a["eligible"],
        "min_purchase_met": a["min_purchase_met"],
        "documents_sufficient": a["documents_sufficient"],
        "reasons": a["reasons"],
        "assessed_at": fmt_dt(a["assessed_at"]),
    }


def floor_share(claimed, total_claimed, pool):
    raw = Decimal(claimed) * Decimal(pool) / Decimal(total_claimed)
    return int(raw.to_integral_value(rounding=ROUND_FLOOR))
