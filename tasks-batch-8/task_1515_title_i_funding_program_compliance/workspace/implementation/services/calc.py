"""Calculation rules (scaffold Table 3 / PRD section 3).

All arithmetic is exact integer math with round-half-up (ties away from zero)
applied exactly where each rule states it.
"""

from datetime import date

MUST_SERVE_BP = 7500
ELIGIBLE_BP = 3500
SCHOOLWIDE_BP = 4000

PE_THRESHOLD_CENTS = 50000000      # $500,000.00 — strictly greater than
HOMELESS_FLOOR_CENTS = 500000      # $5,000.00
PE_SCHOOL_SHARE_NUM = 90           # 0.90
PE_SCHOOL_SHARE_DEN = 100

CARRYOVER_LIMIT_BP = 1500

TIER_MUST_SERVE_WEIGHT = 150
TIER_SCHOOLWIDE_WEIGHT = 125
TIER_TARGETED_WEIGHT = 100
TIER_ELECTED_WEIGHT = 125


def rhu(numer, denom):
    """round_half_up(numer / denom) to an integer, exact integer math.
    Ties go away from zero (Decimal ROUND_HALF_UP semantics). denom > 0."""
    if numer >= 0:
        return (2 * numer + denom) // (2 * denom)
    return -((2 * (-numer) + denom) // (2 * denom))


# --- school_ranking ----------------------------------------------------------
def poverty_pct_bp(low_income, total):
    return rhu(low_income * 10000, total)


def eligibility_flag(pct_bp):
    if pct_bp >= MUST_SERVE_BP:
        return "MUST_SERVE"
    if pct_bp >= ELIGIBLE_BP:
        return "ELIGIBLE"
    return "BELOW_THRESHOLD"


def program_model(pct_bp):
    return "SCHOOLWIDE" if pct_bp >= SCHOOLWIDE_BP else "TARGETED_ASSISTANCE"


def compute_ranking(entries, schools_by_id):
    """Return {school_id: {poverty_pct_bp, rank_position, eligibility_flag,
    program_model}} computed over one snapshot's entries.

    Rank order: poverty_pct_bp DESC, low_income_student_count DESC,
    School.created_at ASC. UUID ids are never used as a tie-break.
    """
    figures = {}
    rows = []
    for e in entries:
        pct = poverty_pct_bp(e["low_income_student_count"], e["total_student_count"])
        school = schools_by_id[e["school_id"]]
        rows.append((e["school_id"], pct, e["low_income_student_count"], school["created_at"]))
    rows.sort(key=lambda r: (-r[1], -r[2], r[3]))
    for idx, (school_id, pct, li, _created) in enumerate(rows):
        figures[school_id] = {
            "poverty_pct_bp": pct,
            "rank_position": idx + 1,
            "eligibility_flag": eligibility_flag(pct),
            "program_model": program_model(pct),
        }
    return figures


# --- set_aside_minimums ------------------------------------------------------
def non_equitable_minimums(grant):
    """PARENT_ENGAGEMENT / HOMELESS_SERVICES / PROFESSIONAL_DEVELOPMENT floors."""
    total = grant["total_allocation_cents"]
    net = grant["net_allocable_cents"]
    pe = rhu(total, 100) if total > PE_THRESHOLD_CENTS else 0            # 1% of total
    homeless = max(HOMELESS_FLOOR_CENTS, rhu(net, 200))                  # max(floor, 0.5% of net)
    pd = rhu(net, 20)                                                    # 5% of net
    return {
        "PARENT_ENGAGEMENT": pe,
        "HOMELESS_SERVICES": homeless,
        "PROFESSIONAL_DEVELOPMENT": pd,
    }


# --- equitable_services_share ------------------------------------------------
def equitable_minimum(grant, li_private, li_public_served):
    """Pinned evaluation order: the share is computed on P (net of the three
    non-equitable set-asides), not on net_allocable_cents and not on the
    post-share school pool. Returns (equitable_min_cents, school_pool_cents)."""
    mins = non_equitable_minimums(grant)
    base = (
        grant["net_allocable_cents"]
        - mins["PARENT_ENGAGEMENT"]
        - mins["HOMELESS_SERVICES"]
        - mins["PROFESSIONAL_DEVELOPMENT"]
    )
    if li_private == 0:
        return 0, base
    eq = rhu(base * li_private, li_public_served + li_private)
    return eq, base - eq


def private_low_income_count(grant, consultations, private_schools):
    """Dual-variant private-school low-income count."""
    if grant["equitable_count_method"] == "CONSULTATION_AGREED":
        return sum(
            c["agreed_low_income_count"] or 0
            for c in consultations
            if c["grant_id"] == grant["id"] and c["status"] == "AFFIRMATION_SIGNED"
        )
    # VERIFIED_COUNT: all verified private schools, consultation status irrelevant
    return sum(
        p["low_income_resident_count"] for p in private_schools if p["nonprofit_verified"]
    )


# --- school_allocation_waterfall ---------------------------------------------
def weight_for(allocation):
    pct = allocation["poverty_pct_bp"]
    if pct >= MUST_SERVE_BP:
        return TIER_MUST_SERVE_WEIGHT
    if pct >= SCHOOLWIDE_BP:
        return TIER_SCHOOLWIDE_WEIGHT
    if pct >= ELIGIBLE_BP:
        return TIER_TARGETED_WEIGHT
    return TIER_ELECTED_WEIGHT  # serve_elected below threshold: the 125% rule


def run_waterfall(served, school_pool_cents):
    """Fill per_pupil_cents / allocation_amount_cents on each served allocation.

    Rounding order is pinned: per-school round_half_up first, then a one-cent-at-
    a-time remainder reconciliation cycling rank_position ASC (shortfall) or
    DESC (overshoot).
    """
    if not served:
        return
    sum_raw = sum(weight_for(a) * a["low_income_student_count"] for a in served)
    for a in served:
        if sum_raw > 0:
            a["per_pupil_cents"] = rhu(
                school_pool_cents * weight_for(a), sum_raw
            )
        else:
            a["per_pupil_cents"] = 0
        a["allocation_amount_cents"] = a["per_pupil_cents"] * a["low_income_student_count"]
    remainder = school_pool_cents - sum(a["allocation_amount_cents"] for a in served)
    ranked = sorted(served, key=lambda a: a["rank_position"])
    if remainder > 0:
        i = 0
        while remainder > 0:
            ranked[i % len(ranked)]["allocation_amount_cents"] += 1
            remainder -= 1
            i += 1
    elif remainder < 0:
        ranked.reverse()
        i = 0
        while remainder < 0:
            ranked[i % len(ranked)]["allocation_amount_cents"] -= 1
            remainder += 1
            i += 1


# --- pe_school_distribution_minimum ------------------------------------------
def pe_school_distributed_minimum(reserved_cents):
    return rhu(PE_SCHOOL_SHARE_NUM * reserved_cents, PE_SCHOOL_SHARE_DEN)


# --- carryover_computation -----------------------------------------------------
def provisional_carryover(grant):
    """PROVISIONAL variant: pending charges count as encumbered at face value."""
    cents = (
        grant["net_allocable_cents"] - grant["liquidated_cents"] - grant["pending_cents"]
    )
    pct_bp = rhu(cents * 10000, grant["total_allocation_cents"])
    return cents, pct_bp


def final_carryover(grant):
    """FINAL variant: only ALLOWED expenditures subtract."""
    cents = grant["net_allocable_cents"] - grant["liquidated_cents"]
    pct_bp = rhu(cents * 10000, grant["total_allocation_cents"])
    return cents, pct_bp


# --- funds period ---------------------------------------------------------------
def funds_period(fiscal_year):
    """[July 1 of fiscal_year-1, June 30 of fiscal_year], inclusive."""
    return date(fiscal_year - 1, 7, 1), date(fiscal_year, 6, 30)


# --- monitoring_clearance -------------------------------------------------------
NON_TERMINAL_FINDING_STATUSES = {"OPEN", "ESCALATED", "CAP_SUBMITTED", "CAP_RETURNED"}


def monitoring_clearance(grant_id, visits, findings):
    visit_ids = {v["id"] for v in visits if v["grant_id"] == grant_id}
    grant_findings = [f for f in findings if f["visit_id"] in visit_ids]
    if any(f["status"] in NON_TERMINAL_FINDING_STATUSES for f in grant_findings):
        return "FINDINGS_OPEN"
    if any(v["status"] == "CLOSED" for v in visits if v["grant_id"] == grant_id):
        return "CLEARED"
    return "NOT_MONITORED"
