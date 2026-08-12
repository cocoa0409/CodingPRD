"""Business logic: calculations (SCAFFOLD §1.3), ledger postings, and cascades.

All money is integer cents; all rounding is round-half-up via Decimal.
"""

from decimal import Decimal, ROUND_HALF_UP

from db import iso, new_id, next_seq, now, store, today, touch
from errors import ERR_EXIT_INSOLVENT, raise_err

# --- constants (SCAFFOLD §1.3) ---
TIER1_CAP_CENTS = 10_000_000        # first $100,000 cumulative received at 8%
TIER2_CAP_CENTS = 50_000_000        # next $400,000 at 6%; 4% beyond
MIN_FEE_CENTS = 50                  # comprehensive per-donation minimum
GRANT_FLAT_RATE = Decimal("0.03")   # pre-approved-grant flat fee
PLEDGE_CREDIT_FACTOR = Decimal("0.8")
MISSION_SCORE_THRESHOLD = Decimal("70.00")
HIGH_VALUE_THRESHOLD_CENTS = 1_000_000
CONTRACTOR_REPORT_THRESHOLD_CENTS = 60_000
RESERVE_PER_OPEN_FINDING_CENTS = 250_000
EXIT_FEE_RATE = Decimal("0.02")
MIN_EXIT_FEE_CENTS = 50_000
ANNUAL_PLATFORM_FEE_CENTS = 25_000

SEVERITY_WEIGHT = {"CRITICAL": 40, "HIGH": 20, "MEDIUM": 8, "LOW": 3}
FINDING_WEIGHT = 5
RESTRICTED_BAND = 25
SEVERE_BAND = 50

OPEN_INCIDENT_STATES = ("REPORTED", "TRIAGED", "MITIGATING")
FINDING_REVIEW_STATES = ("FINDINGS_ISSUED", "ESCALATED")
IN_FLIGHT_DISBURSEMENT_STATES = ("SUBMITTED", "PENDING_SPONSOR", "APPROVED_FOR_PAYMENT")


def rhu(value):
    """Round half up to whole cents -> int."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def r2(value):
    """Round half up to two decimals -> Decimal."""
    return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# calculations.mission_alignment_score — per-component rounding THEN sum (pinned)
# ---------------------------------------------------------------------------


def mission_score(purpose_pts, benefit_pts, capacity_pts, risk_pts):
    c1 = r2(Decimal("0.335") * Decimal(str(purpose_pts)))
    c2 = r2(Decimal("0.265") * Decimal(str(benefit_pts)))
    c3 = r2(Decimal("0.215") * Decimal(str(capacity_pts)))
    c4 = r2(Decimal("0.185") * (Decimal(100) - Decimal(str(risk_pts))))
    return c1 + c2 + c3 + c4


# ---------------------------------------------------------------------------
# calculations.admin_fee_on_receipt
# ---------------------------------------------------------------------------


def admin_fee_on_receipt(amount_cents, cum_received_before, model):
    if model == "PRE_APPROVED_GRANT":
        return rhu(Decimal(amount_cents) * GRANT_FLAT_RATE)
    remaining = amount_cents
    cum = cum_received_before
    fee = 0
    # tier 1: 8% within the fund's first 10,000,000 cumulative cents
    capacity = max(0, TIER1_CAP_CENTS - cum)
    seg = min(remaining, capacity)
    fee += rhu(Decimal(seg) * Decimal("0.08"))
    cum += seg
    remaining -= seg
    # tier 2: 6% within 10,000,000..50,000,000
    capacity = max(0, TIER2_CAP_CENTS - TIER1_CAP_CENTS - max(0, cum - TIER1_CAP_CENTS))
    seg = min(remaining, capacity)
    fee += rhu(Decimal(seg) * Decimal("0.06"))
    cum += seg
    remaining -= seg
    # tier 3: 4% beyond
    seg = remaining
    fee += rhu(Decimal(seg) * Decimal("0.04"))
    return max(MIN_FEE_CENTS, fee)


# ---------------------------------------------------------------------------
# calculations.available_spend_balance (settled + forward variants)
# ---------------------------------------------------------------------------


def available_cents(fund):
    return (
        fund["total_received_cents"]
        - fund["total_refunded_cents"]
        - fund["total_fees_charged_cents"]
        + fund["total_fees_reversed_cents"]
        - fund["total_disbursed_cents"]
        - fund["total_transferred_out_cents"]
        + fund["total_adjustments_cents"]
        - fund["committed_cents"]
        - fund["reserved_cents"]
    )


def forward_available_cents(fund):
    pledged = sum(
        d["amount_cents"]
        for d in store.donations.values()
        if d["project_id"] == fund["project_id"] and d["status"] == "PLEDGED"
    )
    credit = rhu(PLEDGE_CREDIT_FACTOR * Decimal(pledged))
    return available_cents(fund) + credit


def spendable_balance(fund, agreement):
    if agreement and agreement["spending_basis"] == "FORWARD_LOOKING":
        return forward_available_cents(fund)
    return available_cents(fund)


# ---------------------------------------------------------------------------
# calculations.risk_posture_score
# ---------------------------------------------------------------------------


def open_incident_count(project_id):
    return sum(
        1
        for i in store.incidents.values()
        if i["project_id"] == project_id and i["status"] in OPEN_INCIDENT_STATES
    )


def open_findings_total(project_id):
    return sum(
        r["open_findings_count"]
        for r in store.reviews.values()
        if r["project_id"] == project_id and r["status"] in FINDING_REVIEW_STATES
    )


def has_open_critical_incident(project_id):
    return any(
        i["project_id"] == project_id
        and i["severity"] == "CRITICAL"
        and i["status"] in OPEN_INCIDENT_STATES
        for i in store.incidents.values()
    )


def recompute_risk(project):
    score = 0
    for i in store.incidents.values():
        if i["project_id"] == project["id"] and i["status"] in OPEN_INCIDENT_STATES:
            score += SEVERITY_WEIGHT[i["severity"]]
    score += FINDING_WEIGHT * open_findings_total(project["id"])
    if score >= SEVERE_BAND:
        posture = "SEVERE"
    elif score >= RESTRICTED_BAND:
        posture = "RESTRICTED"
    else:
        posture = "NORMAL"
    if project["risk_score"] != score or project["oversight_posture"] != posture:
        project["risk_score"] = score
        project["oversight_posture"] = posture
        touch(project)


# ---------------------------------------------------------------------------
# Ledger
# ---------------------------------------------------------------------------


def post_ledger(fund_account_id, entry_type, amount_cents, memo, donation_id=None, disbursement_id=None):
    ent = {
        "id": new_id(),
        "fund_account_id": fund_account_id,
        "entry_type": entry_type,
        "amount_cents": amount_cents,
        "donation_id": donation_id,
        "disbursement_id": disbursement_id,
        "memo": memo,
        "created_at": iso(now()),
        "_seq": next_seq(),
    }
    store.ledger_entries[ent["id"]] = ent
    return ent


# ---------------------------------------------------------------------------
# Disbursement commitment lifecycle
# ---------------------------------------------------------------------------


def take_commitment(disb, fund):
    amount = disb["amount_cents"]
    fund["committed_cents"] += amount
    post_ledger(
        fund["id"], "COMMITMENT_HOLD", -amount,
        "Commitment hold for disbursement %s" % disb["id"],
        disbursement_id=disb["id"],
    )
    if disb.get("grant_tranche_id"):
        tranche = store.tranches.get(disb["grant_tranche_id"])
        if tranche:
            tranche["committed_cents"] += amount
            touch(tranche)
    touch(fund)


def release_commitment(disb, fund):
    amount = disb["amount_cents"]
    fund["committed_cents"] -= amount
    post_ledger(
        fund["id"], "COMMITMENT_RELEASE", amount,
        "Commitment release for disbursement %s" % disb["id"],
        disbursement_id=disb["id"],
    )
    if disb.get("grant_tranche_id"):
        tranche = store.tranches.get(disb["grant_tranche_id"])
        if tranche:
            tranche["committed_cents"] -= amount
            touch(tranche)
    touch(fund)


def pay_disbursement(disb, fund, exit_settled=False):
    """Convert commitment to spend (PRD §3.4 pay / §3.8 exit bucket one)."""
    amount = disb["amount_cents"]
    fund["committed_cents"] -= amount
    fund["total_disbursed_cents"] += amount
    post_ledger(
        fund["id"], "COMMITMENT_RELEASE", amount,
        "Commitment release on payment of disbursement %s" % disb["id"],
        disbursement_id=disb["id"],
    )
    post_ledger(
        fund["id"], "DISBURSEMENT_DEBIT", -amount,
        "Disbursement paid for request %s" % disb["id"],
        disbursement_id=disb["id"],
    )
    if disb.get("grant_tranche_id"):
        tranche = store.tranches.get(disb["grant_tranche_id"])
        if tranche:
            tranche["committed_cents"] -= amount
            tranche["spent_cents"] += amount
            touch(tranche)
    # calculations.contractor_ytd_accumulation (STAFF + CONTRACTOR only)
    if disb.get("payee_type") == "STAFF" and disb.get("staff_engagement_id"):
        eng = store.engagements.get(disb["staff_engagement_id"])
        if eng and eng["engagement_type"] == "CONTRACTOR":
            year = now().year
            if eng["ytd_year"] != year:
                eng["contractor_ytd_cents"] = 0
                eng["ytd_year"] = year
            eng["contractor_ytd_cents"] += amount
            eng["requires_1099"] = eng["contractor_ytd_cents"] >= CONTRACTOR_REPORT_THRESHOLD_CENTS
            touch(eng)
    if exit_settled:
        disb["exit_settled"] = True
    disb["status"] = "PAID"
    touch(disb)
    touch(fund)


# ---------------------------------------------------------------------------
# Suspension cascade (PRD §3.4/§3.6): fund freezes, in-flight requests reject
# ---------------------------------------------------------------------------


def suspend_project_cascade(project, reason):
    fund = None
    from db import fund_of_project  # local import to avoid cycles

    if project["status"] == "ACTIVE":
        project["status"] = "SUSPENDED"
        project["suspension_reason"] = reason
        touch(project)
        fund = fund_of_project(project["id"])
        if fund and fund["status"] == "ACTIVE":
            fund["status"] = "FROZEN"
            touch(fund)
    else:
        fund = fund_of_project(project["id"])
    if fund:
        for d in store.disbursements.values():
            if d["project_id"] == project["id"] and d["status"] in IN_FLIGHT_DISBURSEMENT_STATES:
                release_commitment(d, fund)
                d["status"] = "REJECTED"
                d["auto_reject_reason"] = "SUSPENSION"
                touch(d)


# ---------------------------------------------------------------------------
# Tax receipts
# ---------------------------------------------------------------------------


def issue_receipt(donation, amount_cents):
    year = now().year
    seq = store.receipt_seq.get(year, 0) + 1
    store.receipt_seq[year] = seq
    from db import stamp_new

    ent = stamp_new({
        "id": new_id(),
        "donation_id": donation["id"],
        "receipt_number": "FS-%d-%06d" % (year, seq),
        "tax_year": year,
        "amount_cents": amount_cents,
        "status": "ISSUED",
        "void_reason": None,
    })
    store.receipts[ent["id"]] = ent
    return ent


def issued_receipt_of(donation_id):
    for r in store.receipts.values():
        if r["donation_id"] == donation_id and r["status"] == "ISSUED":
            return r
    return None


# ---------------------------------------------------------------------------
# calculations.exit_settlement_waterfall — pinned evaluation order (PRD §3.8)
# ---------------------------------------------------------------------------


def exit_waterfall(project, fund):
    G = available_cents(fund) + fund["committed_cents"]
    bucket1 = sum(
        d["amount_cents"]
        for d in store.disbursements.values()
        if d["project_id"] == project["id"]
        and d["status"] in ("PENDING_SPONSOR", "APPROVED_FOR_PAYMENT")
    )
    bucket2 = RESERVE_PER_OPEN_FINDING_CENTS * open_findings_total(project["id"])
    base = G - bucket1 - bucket2
    if base < 0:
        raise_err(ERR_EXIT_INSOLVENT, "Exit settlement base is negative")
    bucket3 = max(MIN_EXIT_FEE_CENTS, rhu(Decimal(base) * EXIT_FEE_RATE))
    bucket4 = base - bucket3
    if bucket4 < 0:
        raise_err(ERR_EXIT_INSOLVENT, "Exit transfer is negative")
    return G, bucket1, bucket2, bucket3, bucket4
