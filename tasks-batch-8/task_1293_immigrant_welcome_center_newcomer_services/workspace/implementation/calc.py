"""Calculation rules: acuity, benefits tiering, fee subsidy, funder allocation.

All money is integer cents; divisions floor unless a rule pins round-half-up.
"""
from decimal import Decimal, ROUND_HALF_UP
from datetime import timedelta

import db
from util import date_as_dt

# ---------------------------------------------------------------------------
# acuity_index
# ---------------------------------------------------------------------------

ACUITY_WEIGHTS = {
    "housing": Decimal("0.30"),
    "employment": Decimal("0.25"),
    "education": Decimal("0.15"),
    "language": Decimal("0.20"),
    "health": Decimal("0.10"),
}
VERIFIED_MULTIPLIER = Decimal("1.25")
HOUSEHOLD_BONUS_MIN = 5
RECENT_ARRIVAL_DAYS = 90


def _acuity_base(assessment):
    base = Decimal(0)
    for domain, w in ACUITY_WEIGHTS.items():
        base += w * (Decimal(assessment[f"{domain}_score"]) / Decimal(4))
    return base


def acuity_rapid(assessment):
    """Rapid variant: round_half_up(base * 100, 1dp); no multiplier/bonuses."""
    v = (_acuity_base(assessment) * 100).quantize(Decimal("0.1"),
                                                  rounding=ROUND_HALF_UP)
    return v


def acuity_comprehensive(assessment, client):
    """Comprehensive variant (VERIFIED only): *1.25 capped at 1, round,
    then +10 household / +5 recent-arrival bonuses, clamped to [0, 100]."""
    base = _acuity_base(assessment)
    scaled = min(Decimal("1.0"), base * VERIFIED_MULTIPLIER)
    v = (scaled * 100).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    if client.get("household_size", 1) >= HOUSEHOLD_BONUS_MIN:
        v += Decimal(10)
    arrival = client.get("arrival_date")
    if arrival:
        arr = date_as_dt(arrival)
        if db.now() - arr <= timedelta(days=RECENT_ARRIVAL_DAYS):
            v += Decimal(5)
    if v < 0:
        v = Decimal(0)
    if v > 100:
        v = Decimal(100)
    return v


def recompute_acuity_submit(assessment):
    """On submit: refresh the case's acuity_rapid (rapid variant)."""
    case = db.get("cases", assessment["case_id"])
    if case is None:
        return
    new_val = acuity_rapid(assessment)
    if case.get("acuity_rapid") != new_val:
        case["acuity_rapid"] = new_val
        db.touch(case)


def recompute_acuity_verify(assessment):
    """On verify: refresh both acuity_rapid and acuity_verified."""
    case = db.get("cases", assessment["case_id"])
    if case is None:
        return
    client = db.get("clients", case["client_id"])
    rapid = acuity_rapid(assessment)
    comp = acuity_comprehensive(assessment, client or {})
    changed = False
    if case.get("acuity_rapid") != rapid:
        case["acuity_rapid"] = rapid
        changed = True
    if case.get("acuity_verified") != comp:
        case["acuity_verified"] = comp
        changed = True
    if changed:
        db.touch(case)


# ---------------------------------------------------------------------------
# benefits_tiering
# ---------------------------------------------------------------------------

FPL_ANNUAL_CENTS = {1: 1506000, 2: 2044000, 3: 2582000, 4: 3120000,
                    5: 3658000, 6: 4196000, 7: 4734000, 8: 5272000}
TIER_A_PCT, TIER_B_PCT, TIER_C_PCT = 138, 200, 300
DOC_GATED = {"CASH_ASSIST"}
TIER_PROGRAMS = {
    "TIER_A": ["SNAP", "MEDICAID", "CASH_ASSIST", "ESL_SUBSIDY"],
    "TIER_B": ["SNAP", "ESL_SUBSIDY"],
    "TIER_C": ["ESL_SUBSIDY"],
    "TIER_D": [],
}


def run_tiering(income_cents, household_size, variant):
    """Return (income_ratio Decimal 4dp, tier, eligible_programs list).

    Tier boundaries are inclusive at the upper edge and compared in integer
    cents against floored FPL multiples — never via the rounded ratio.
    """
    fpl = FPL_ANNUAL_CENTS[min(household_size, 8)]
    ratio = (Decimal(income_cents) / Decimal(fpl)).quantize(
        Decimal("0.0001"), rounding=ROUND_HALF_UP)
    a = (fpl * TIER_A_PCT) // 100
    b = (fpl * TIER_B_PCT) // 100
    c = (fpl * TIER_C_PCT) // 100
    if income_cents <= a:
        tier = "TIER_A"
    elif income_cents <= b:
        tier = "TIER_B"
    elif income_cents <= c:
        tier = "TIER_C"
    else:
        tier = "TIER_D"
    programs = list(TIER_PROGRAMS[tier])
    if variant == "SELF_REPORTED":
        programs = [p for p in programs if p not in DOC_GATED]
    return ratio, tier, programs


# ---------------------------------------------------------------------------
# enrollment_fee_subsidy (pinned evaluation order)
# ---------------------------------------------------------------------------

BASE_SUBSIDY_PCT = {
    "TIER_A": Decimal("0.90"),
    "TIER_B": Decimal("0.60"),
    "TIER_C": Decimal("0.30"),
    "TIER_D": Decimal("0.00"),
}
BURDEN_RATE_NUM, BURDEN_RATE_DEN = 5, 100   # 0.05
MONTHS_PER_YEAR = 12


def latest_verified_screening(case_id):
    """Latest VERIFIED-variant screening in SCREENED/EXPLAINED status."""
    cands = [s for s in db.all_of("screenings")
             if s["case_id"] == case_id
             and s.get("variant_used") == "VERIFIED"
             and s.get("status") in ("SCREENED", "EXPLAINED")]
    if not cands:
        return None
    return max(cands, key=lambda s: (s["updated_at"], s["_seq"]))


def compute_fee_subsidy(program, screening):
    """Return (subsidy_pct Decimal, subsidized_fee_cents int)."""
    pct = BASE_SUBSIDY_PCT[screening["tier"]]
    provisional = (Decimal(program["base_fee_cents"]) * (1 - pct)).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP)
    monthly = screening["documented_annual_income_cents"] // MONTHS_PER_YEAR
    burden_cap = (monthly * BURDEN_RATE_NUM) // BURDEN_RATE_DEN
    final_fee = min(int(provisional), burden_cap)
    final_fee = max(final_fee, 0)
    return pct, final_fee


# ---------------------------------------------------------------------------
# funder_cost_allocation
# ---------------------------------------------------------------------------

REFERRAL_COMPLETION_CENTS = 7500
ENROLLMENT_COMPLETION_CENTS = 12000
WORKSHOP_ATTENDANCE_CENTS = 2500


def compute_report(period_start, period_end, funding_streams):
    """Compute lines, stream_totals, total_cost_cents and client counts.

    Pinned order: per-cell round_half_up BEFORE summing; residual (possibly
    negative) lands on the greatest share_pct, tie -> lowest array index.
    """
    def in_window(dt):
        return dt is not None and period_start <= dt < period_end

    refs = [r for r in db.all_of("referrals")
            if r["status"] == "COMPLETED" and in_window(r.get("completed_at"))]
    enrs = [e for e in db.all_of("enrollments")
            if e["status"] == "COMPLETED" and in_window(e.get("completed_at"))]
    wks = [w for w in db.all_of("wk_enrollments")
           if w["status"] == "ATTENDED"
           and in_window(w.get("attended_marked_at"))]

    lines = [
        {"line_type": "REFERRAL_COMPLETION",
         "unit_cost_cents": REFERRAL_COMPLETION_CENTS,
         "quantity": len(refs),
         "line_total_cents": len(refs) * REFERRAL_COMPLETION_CENTS},
        {"line_type": "ENROLLMENT_COMPLETION",
         "unit_cost_cents": ENROLLMENT_COMPLETION_CENTS,
         "quantity": len(enrs),
         "line_total_cents": len(enrs) * ENROLLMENT_COMPLETION_CENTS},
        {"line_type": "WORKSHOP_ATTENDANCE",
         "unit_cost_cents": WORKSHOP_ATTENDANCE_CENTS,
         "quantity": len(wks),
         "line_total_cents": len(wks) * WORKSHOP_ATTENDANCE_CENTS},
    ]
    total_cost = sum(l["line_total_cents"] for l in lines)

    # per-cell rounding, then per-stream sum
    stream_sums = []
    for stream in funding_streams:
        share = Decimal(str(stream["share_pct"]))
        s = 0
        for line in lines:
            cell = (Decimal(line["line_total_cents"]) * share / 100).quantize(
                Decimal("1"), rounding=ROUND_HALF_UP)
            s += int(cell)
        stream_sums.append(s)

    residual = total_cost - sum(stream_sums)
    if funding_streams:
        top_idx = max(range(len(funding_streams)),
                      key=lambda i: (Decimal(str(
                          funding_streams[i]["share_pct"])),
                          -i))
        stream_sums[top_idx] += residual

    stream_totals = []
    for i, stream in enumerate(funding_streams):
        stream_totals.append({
            "stream_name": stream["stream_name"],
            "share_pct": stream["share_pct"],
            "total_cents": stream_sums[i],
        })

    # consent-split client counts
    client_ids = []
    for r in refs:
        case = db.get("cases", r["case_id"])
        if case:
            client_ids.append(case["client_id"])
    for e in enrs:
        case = db.get("cases", e["case_id"])
        if case:
            client_ids.append(case["client_id"])
    for w in wks:
        case = db.get("cases", w["case_id"])
        if case:
            client_ids.append(case["client_id"])
    aggregate = len(set(client_ids))
    reportable = len({cid for cid in set(client_ids)
                      if (db.get("clients", cid) or {}).get("reportable")})

    return {
        "lines": lines,
        "stream_totals": stream_totals,
        "total_cost_cents": total_cost,
        "reportable_client_count": reportable,
        "aggregate_client_count": aggregate,
    }
