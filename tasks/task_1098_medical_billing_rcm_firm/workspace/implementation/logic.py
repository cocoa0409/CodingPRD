"""Calculations, ledger reconciliation, and derived-field recomputation."""
from decimal import Decimal, ROUND_HALF_UP

import store

# Wire claim statuses = reached the clearinghouse (§3.8).
WIRE_STATUSES = {"SUBMITTED", "ACCEPTED", "DENIED", "APPEALED", "PAID", "CLOSED"}
REALIZED_STATUSES = {"PAID", "CLOSED"}


def round_half_up_cents(amount_decimal):
    return int(Decimal(amount_decimal).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def pct_of(amount_cents, pct):
    """round_half_up(amount_cents * pct) to whole cents."""
    product = Decimal(int(amount_cents)) * Decimal(str(pct))
    return round_half_up_cents(product)


def rate4(numerator, denominator):
    """numerator/denominator rounded half-up to 4 decimals; 0 when denom <= 0."""
    if denominator is None or denominator <= 0:
        return 0.0
    q = (Decimal(int(numerator)) / Decimal(int(denominator))).quantize(
        Decimal("0.0001"), rounding=ROUND_HALF_UP)
    return float(q)


# ---------------------------------------------------------------------------
# Child lookups
# ---------------------------------------------------------------------------
def claim_lines_of(claim_id):
    return [l for l in store.claim_lines.values() if l["claim_id"] == claim_id]


def posted_postings_of(claim_id):
    return [p for p in store.payment_postings.values()
            if p["claim_id"] == claim_id and p["status"] == "POSTED"]


def all_postings_of(claim_id):
    return [p for p in store.payment_postings.values()
            if p["claim_id"] == claim_id]


def denials_of(claim_id):
    return [d for d in store.denials.values() if d["claim_id"] == claim_id]


# ---------------------------------------------------------------------------
# Provisional patient responsibility (§3.3)
# ---------------------------------------------------------------------------
def provisional_patient_responsibility(claim):
    lines = claim_lines_of(claim["id"])
    allowed = sum(l["allowed_amount_cents"] for l in lines)
    deductible_applied = min(allowed, claim["deductible_remaining_cents"])
    after_deductible = allowed - deductible_applied
    coinsurance = pct_of(after_deductible, claim["coinsurance_pct"])
    pr = min(deductible_applied + coinsurance + claim["copay_cents"], allowed)
    return pr


# ---------------------------------------------------------------------------
# Claim ledger identity (§3.6) — fixed evaluation order.
# ---------------------------------------------------------------------------
def recompute_claim_ledger(claim):
    lines = claim_lines_of(claim["id"])
    billed = sum(l["charge_amount_cents"] for l in lines)
    allowed = sum(l["allowed_amount_cents"] for l in lines)
    contractual = billed - allowed
    posted = posted_postings_of(claim["id"])
    insurance_paid = sum(p["insurance_paid_cents"] for p in posted)
    # §3.6: patient_responsibility is the provisional figure computed at scrub
    # UNTIL ANY POSTING EXISTS, after which it is the final value reported on the
    # ERA line. Unlike insurance_paid (POSTED-only, step 4), this key is "any
    # posting exists" — so a reversed posting still supplies the ERA value.
    all_postings = all_postings_of(claim["id"])
    if all_postings:
        latest = max(all_postings, key=lambda p: (p["created_at"], p["id"]))
        patient_responsibility = latest["patient_responsibility_cents"]
    else:
        patient_responsibility = claim.get("_provisional_pr", 0)
    write_off = claim["write_off_cents"]
    outstanding = billed - contractual - insurance_paid - patient_responsibility - write_off

    claim["billed_amount_cents"] = billed
    claim["allowed_amount_cents"] = allowed
    claim["contractual_adjustment_cents"] = contractual
    claim["insurance_paid_cents"] = insurance_paid
    claim["patient_responsibility_cents"] = patient_responsibility
    claim["outstanding_balance_cents"] = outstanding
    return claim


# ---------------------------------------------------------------------------
# Practice derived totals (§2.9)
# ---------------------------------------------------------------------------
def recompute_practice_totals(practice, touch_fn):
    pid = practice["id"]
    prac_claims = [c for c in store.claims.values() if c["practice_id"] == pid]
    # ar_balance = sum of outstanding across non-terminal claims (not CLOSED/VOID).
    ar = sum(c["outstanding_balance_cents"] for c in prac_claims
             if c["status"] not in ("CLOSED", "VOID"))
    collected = sum(c["insurance_paid_cents"] for c in prac_claims)
    changed = (practice["ar_balance_cents"] != ar or
               practice["collected_ytd_cents"] != collected)
    practice["ar_balance_cents"] = ar
    practice["collected_ytd_cents"] = collected
    if changed:
        touch_fn(practice, bump_version=False)


# ---------------------------------------------------------------------------
# Remittance allocation (§3.6)
# ---------------------------------------------------------------------------
def recompute_remittance_allocation(remittance):
    rid = remittance["id"]
    posted = [p for p in store.payment_postings.values()
              if p["remittance_id"] == rid and p["status"] == "POSTED"]
    allocated = sum(p["insurance_paid_cents"] for p in posted)
    remittance["allocated_amount_cents"] = allocated
    remittance["unallocated_amount_cents"] = remittance["total_amount_cents"] - allocated


# ---------------------------------------------------------------------------
# Statement aging bucket (§3.7)
# ---------------------------------------------------------------------------
def aging_bucket_for(statement):
    if statement["first_sent_date"] is None:
        return "CURRENT"
    days = store.day_diff(store.clock_now(), statement["first_sent_date"])
    if days <= 30:
        return "CURRENT"
    if days <= 60:
        return "DAYS_31_60"
    if days <= 90:
        return "DAYS_61_90"
    return "OVER_90"


# ---------------------------------------------------------------------------
# Practice billing fee (§3.8)
# ---------------------------------------------------------------------------
def practice_billing_fee(practice):
    pid = practice["id"]
    pct = practice["billing_fee_pct"]
    prac_claims = [c for c in store.claims.values() if c["practice_id"] == pid]
    charge_based = sum(pct_of(c["billed_amount_cents"], pct)
                       for c in prac_claims if c["status"] in WIRE_STATUSES)
    collection_based = sum(pct_of(c["insurance_paid_cents"], pct)
                           for c in prac_claims if c["status"] in REALIZED_STATUSES)
    return {"charge_based_fee_cents": charge_based,
            "collection_based_fee_cents": collection_based}


# ---------------------------------------------------------------------------
# Practice KPI (§3.8)
# ---------------------------------------------------------------------------
def practice_kpi(practice):
    pid = practice["id"]
    prac_claims = [c for c in store.claims.values() if c["practice_id"] == pid]
    counted = [c for c in prac_claims if c["status"] not in ("DRAFT", "VOID")]
    total_claims = len(counted)

    def ever_denied(c):
        return len(denials_of(c["id"])) > 0 or c["status"] in ("DENIED", "APPEALED")

    clean = sum(1 for c in counted if c.get("_ever_accepted") and not ever_denied(c))
    denied = sum(1 for c in counted if ever_denied(c))

    clean_rate = rate4(clean, total_claims) if total_claims > 0 else 0.0
    denial_rate = rate4(denied, total_claims) if total_claims > 0 else 0.0

    billed_total = sum(c["billed_amount_cents"] for c in prac_claims
                       if c["status"] in WIRE_STATUSES)
    contractual_total = sum(c["contractual_adjustment_cents"] for c in prac_claims
                            if c["status"] in WIRE_STATUSES)
    collected_total = sum(c["insurance_paid_cents"] for c in prac_claims)
    denom = billed_total - contractual_total
    net_rate = rate4(collected_total, denom)

    return {
        "clean_claim_rate": clean_rate,
        "denial_rate": denial_rate,
        "net_collection_rate": net_rate,
        "total_claims": total_claims,
    }
