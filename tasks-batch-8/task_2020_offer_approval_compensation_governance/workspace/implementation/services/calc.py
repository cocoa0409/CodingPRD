"""Calculation rules: band classification, offer cost views, peer equity,
concession authority, clawback quotes, clearance posture, chain construction."""

from decimal import Decimal, ROUND_HALF_UP

import db

# Constants from the scaffold calculations table
ABOVE_BAND_TOLERANCE_PCT = Decimal("0.10")
HARD_CAP_PCT = Decimal("1.25")
BENEFITS_LOAD_PCT = Decimal("0.30")
EQUITY_VEST_YEARS = 4
MIN_PEER_SNAPSHOTS = 3
SIGNON_REVIEW_THRESHOLD_CENTS = 1000000
TIER2_TOTAL_CASH_CENTS = 30000000
SIGNON_HARD_CAP_CENTS = 2500000
CONCESSION_CAPS = {
    "Recruiter": Decimal("0.05"),
    "HiringManager": Decimal("0.10"),
    "VPPeople": Decimal("1.00"),
}

SEVERITY = {"IN_BAND": 1, "BELOW_MIN": 2, "ABOVE_BAND": 2, "EXCEPTION": 3}

COMMITTED_STATUSES = {
    "PENDING_APPROVAL", "APPROVED", "LETTER_GENERATED", "EXTENDED",
    "COUNTERED", "ACCEPTED", "HIRED",
}

# Statuses blocking candidate archive (live statuses)
CANDIDATE_LIVE_STATUSES = {
    "DRAFT", "RETURNED", "PENDING_APPROVAL", "APPROVED", "LETTER_GENERATED",
    "EXTENDED", "COUNTERED", "ACCEPTED", "HIRED",
}

# Statuses auto-withdrawn by the requisition cascade
REQ_CASCADE_STATUSES = {
    "DRAFT", "RETURNED", "PENDING_APPROVAL", "APPROVED", "LETTER_GENERATED",
    "EXTENDED", "COUNTERED",
}


def rhu(value, places=0):
    """Round half up to given decimal places; returns Decimal."""
    q = Decimal(1).scaleb(-places)
    return Decimal(value).quantize(q, rounding=ROUND_HALF_UP)


def rhu_int(value):
    return int(rhu(value, 0))


def classify_band(base_cents, req):
    """PRD 3.2/3.3: unrounded product comparisons."""
    if base_cents < req["salary_min_cents"]:
        return "BELOW_MIN"
    if base_cents <= req["salary_max_cents"]:
        return "IN_BAND"
    threshold = Decimal(req["salary_max_cents"]) * (1 + ABOVE_BAND_TOLERANCE_PCT)
    if Decimal(base_cents) <= threshold:
        return "ABOVE_BAND"
    return "EXCEPTION"


def exceeds_hard_cap(base_cents, req):
    cap = Decimal(req["salary_max_cents"]) * HARD_CAP_PCT
    return Decimal(base_cents) > cap


def perk_totals(offer_id):
    sign_on = 0
    relocation = 0
    for p in db.perks.values():
        if p["offer_id"] == offer_id and p["status"] != "VOIDED":
            if p["kind"] == "SIGN_ON":
                sign_on += p["amount_cents"]
            else:
                relocation += p["amount_cents"]
    return sign_on, relocation


def compute_costs(offer):
    """offer_cost calculation: pinned order bonus -> benefits -> equity -> perk sums."""
    base = offer["base_cents"]
    bonus = rhu_int(Decimal(base) * Decimal(str(offer["bonus_target_pct"])))
    benefits = rhu_int(Decimal(base + bonus) * BENEFITS_LOAD_PCT)
    equity_annual = rhu_int(
        Decimal(offer["equity_shares"] * offer["equity_fmv_cents"]) / Decimal(EQUITY_VEST_YEARS)
    )
    sign_on, relocation = perk_totals(offer["id"])
    cash_only = base + bonus + sign_on + relocation
    fully_loaded = cash_only + equity_annual + benefits
    offer["bonus_target_cents"] = bonus
    offer["total_cash_cents"] = cash_only
    offer["cash_only_annual_cost_cents"] = cash_only
    offer["fully_loaded_annual_cost_cents"] = fully_loaded


def compute_equity_metrics(offer, req):
    """peer_equity_position calculation."""
    peers = [
        s for s in db.snapshots.values()
        if s["role_level"] == req["role_level"] and s["geo_tier"] == req["geo_tier"]
    ]
    n = len(peers)
    if n < MIN_PEER_SNAPSHOTS:
        offer["equity_compa_ratio"] = None
        offer["equity_percentile"] = None
        offer["equity_compa_risk_flag"] = False
        offer["equity_percentile_risk_flag"] = False
        return
    mean = rhu_int(Decimal(sum(p["base_cents"] for p in peers)) / Decimal(n))
    ratio = float(rhu(Decimal(offer["base_cents"]) / Decimal(mean), 4))
    count_lt = sum(1 for p in peers if p["base_cents"] < offer["base_cents"])
    count_eq = sum(1 for p in peers if p["base_cents"] == offer["base_cents"])
    percentile = rhu_int(
        (Decimal(count_lt) + Decimal("0.5") * Decimal(count_eq)) / Decimal(n) * 100
    )
    offer["equity_compa_ratio"] = ratio
    offer["equity_percentile"] = percentile
    offer["equity_compa_risk_flag"] = ratio < 0.85 or ratio > 1.15
    offer["equity_percentile_risk_flag"] = percentile < 10 or percentile >= 90


def recompute_offer_analytics(offer, req):
    offer["band"] = classify_band(offer["base_cents"], req)
    compute_costs(offer)
    compute_equity_metrics(offer, req)


def matching_peer_count(req):
    return sum(
        1 for s in db.snapshots.values()
        if s["role_level"] == req["role_level"] and s["geo_tier"] == req["geo_tier"]
    )


def recompute_committed_budget(req):
    total = sum(
        o["fully_loaded_annual_cost_cents"]
        for o in db.offers.values()
        if o["requisition_id"] == req["id"] and o["status"] in COMMITTED_STATUSES
    )
    if total != req["committed_budget_cents"]:
        req["committed_budget_cents"] = total
        touch(req)


def recompute_headcount(req):
    """Returns True when the requisition auto-closed (caller fires cascade)."""
    filled = sum(
        1 for o in db.offers.values()
        if o["requisition_id"] == req["id"] and o["status"] == "HIRED"
    )
    req["headcount_filled"] = filled
    if req["status"] == "OPEN" and filled == req["headcount_authorized"]:
        req["status"] = "CLOSED"
        req["close_reason"] = "FILLED"
        touch(req)
        return True
    touch(req)
    return False


def concession_pct(proposed_base, original_base):
    return float(rhu(
        (Decimal(proposed_base) - Decimal(original_base)) / Decimal(original_base), 4
    ))


def max_allowed_base(role, original_base):
    cap = CONCESSION_CAPS[role]
    return original_base + rhu_int(Decimal(original_base) * cap)


def clawback_quote(perk, months_worked):
    amount = perk["amount_cents"]
    months = perk["clawback_months"]
    if perk["clawback_variant"] == "FULL_CLIFF":
        repayment = amount if months_worked < months else 0
    else:  # PRORATED_MONTHLY
        if months_worked >= months:
            repayment = 0
        elif months_worked == 0:
            repayment = amount
        else:
            installment = rhu_int(Decimal(amount) / Decimal(months))
            repayment = installment * (months - months_worked)
    remaining = max(0, months - months_worked)
    return repayment, remaining


def clearance_posture(offer_id):
    checks = [c for c in db.clearance_checks.values() if c["offer_id"] == offer_id]
    if any(c["status"] == "FAILED" for c in checks):
        return "FAILED"
    if not checks:
        return "NOT_STARTED"
    if all(c["status"] in ("CLEARED", "WAIVED") for c in checks):
        return "CLEARED"
    return "PENDING"


def build_approval_chain(offer):
    """approval_chain_construction. Returns ordered list of role names."""
    chain = ["HiringManager"]
    rows = [
        p for p in db.policies.values()
        if p["status"] == "ACTIVE"
        and SEVERITY[offer["band"]] >= SEVERITY[p["min_band_severity"]]
    ]
    rows.sort(key=lambda p: (p["chain_position"], p["created_at"]))
    for row in rows:
        if row["required_role"] not in chain:
            chain.append(row["required_role"])
    sign_on, _ = perk_totals(offer["id"])
    need_comp = (
        sign_on > SIGNON_REVIEW_THRESHOLD_CENTS
        or offer["equity_compa_risk_flag"]
        or offer["equity_percentile_risk_flag"]
    )
    if need_comp and "CompAnalyst" not in chain:
        chain.append("CompAnalyst")
    if offer["total_cash_cents"] >= TIER2_TOTAL_CASH_CENTS and "VPPeople" not in chain:
        chain.append("VPPeople")
    return chain


def touch(entity):
    entity["updated_at"] = db.now_ms()
    entity["version"] = entity.get("version", 1) + 1


def touch_no_version(entity):
    """Refresh updated_at without bumping version.

    PRD 2.8: any change to a resource's recorded properties refreshes
    updated_at, but Offer.version only advances on terms revision and
    negotiation-round creation/acceptance."""
    entity["updated_at"] = db.now_ms()
