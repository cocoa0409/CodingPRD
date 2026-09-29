"""Numeric primitives, the governing-policy selector and every calculation.

All money is integer cents; every derived cent amount and every computed
percentage or hour figure is rounded half up (PRD 2.7).
"""

from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from store import clock_date, db, seq_of

# ------------------------------------------------------------------ primitives
_TWO = Decimal("0.01")
_ONE = Decimal("1")


def dec(value):
    if isinstance(value, Decimal):
        return value
    if value is None:
        return Decimal(0)
    return Decimal(str(value))


def rhu_cents(value):
    """Round half up to a whole cent, returned as an int."""
    return int(dec(value).quantize(_ONE, rounding=ROUND_HALF_UP))


def rhu2(value):
    """Round half up to two decimal places, returned as a float."""
    return float(dec(value).quantize(_TWO, rounding=ROUND_HALF_UP))


def pct_of_cents(pct, base_cents):
    """pct percent of base_cents, rounded half up to whole cents."""
    return rhu_cents(dec(pct) / Decimal(100) * dec(base_cents))


def ratio_pct(numerator, denominator):
    """100 * numerator / denominator to two decimals; 0.00 when denominator is 0."""
    if not denominator:
        return 0.00
    return rhu2(Decimal(100) * dec(numerator) / dec(denominator))


# ----------------------------------------------------------------- date helpers
def whole_years(start, end):
    """Days between two dates divided by 365, fraction discarded."""
    if start is None or end is None:
        return 0
    return int((end - start).days // 365)


def add_years(d, years):
    """Advance a calendar date by whole years, clamping 29 February."""
    if d is None:
        return None
    year = d.year + int(years)
    try:
        return date(year, d.month, d.day)
    except ValueError:
        return date(year, d.month, 28)


def parse_iso_date(text):
    if not text:
        return None
    try:
        return date(int(text[0:4]), int(text[5:7]), int(text[8:10]))
    except (ValueError, IndexError, TypeError):
        return None


# ------------------------------------------------------- governing policy (2.6)
def governing_policy():
    """ACTIVE rows ranked effective_from DESC then created_at DESC; ids never rank."""
    eligible = [p for p in db.policies.values() if p["status"] == "ACTIVE"]
    if not eligible:
        return None
    eligible.sort(key=lambda p: (str(p.get("_effective_sort") or p["effective_from"]),
                                 str(p["created_at"]), seq_of(p)),
                  reverse=True)
    return eligible[0]


def require_policy():
    from errors import fail
    policy = governing_policy()
    if policy is None:
        fail("ERR_NO_ACTIVE_POLICY", "No ACTIVE governance policy is in force.")
    return policy


# --------------------------------------------------------------- row selectors
def sorted_rows(rows, key=None, reverse=False):
    """Stable ordering with the insertion sequence as the final tiebreak."""
    if key is None:
        ordered = sorted(rows, key=lambda r: (str(r["created_at"]), seq_of(r)), reverse=reverse)
    else:
        ordered = sorted(rows, key=lambda r: (key(r), seq_of(r)), reverse=reverse)
    return ordered


# ------------------------------------------------------- outside-board topology
def public_company_ids(directorship_rows):
    """The ACTIVE seats of a subject whose company is public."""
    ids = set()
    for row in directorship_rows:
        if row["status"] != "ACTIVE":
            continue
        company = db.external_companies.get(row["external_company_id"])
        if company is not None and company["is_public"]:
            ids.add(company["id"])
    return ids


def candidate_directorships(candidate_id):
    return [d for d in db.directorships.values() if d.get("candidate_id") == candidate_id]


def director_directorships(director_id):
    return [d for d in db.directorships.values() if d.get("director_id") == director_id]


def candidate_board_set(candidate_id):
    return public_company_ids(candidate_directorships(candidate_id))


def director_board_set(director_id):
    return public_company_ids(director_directorships(director_id))


INTERLOCK_POPULATION_STATUS = ("ONBOARDING", "SEATED", "RETIREMENT_NOTICED")


def interlock_population(exclude_director_id=None):
    rows = [d for d in db.directors.values()
            if d["service_status"] in INTERLOCK_POPULATION_STATUS]
    if exclude_director_id is not None:
        rows = [d for d in rows if d["id"] != exclude_director_id]
    return rows


def interlock_evaluation(board_set, exclude_director_id=None):
    """Largest per-director intersection, plus whether any shared seat is a competitor."""
    largest = 0
    competitor_shared = False
    for director in interlock_population(exclude_director_id):
        shared = board_set & director_board_set(director["id"])
        if len(shared) > largest:
            largest = len(shared)
        for company_id in shared:
            company = db.external_companies.get(company_id)
            if company is not None and company["is_competitor"]:
                competitor_shared = True
    return largest, competitor_shared


def overboarding_limit(policy, is_sitting_ceo):
    if is_sitting_ceo:
        return policy["max_public_boards_sitting_ceo"]
    return policy["max_public_boards_default"]


# ------------------------------------------------------------- readiness (3.4)
CHANNEL_POINTS = {
    "SEARCH_FIRM": Decimal("20.00"),
    "NETWORK_REFERRAL": Decimal("15.00"),
    "SHAREHOLDER_PROPOSAL": Decimal("10.00"),
    "UNIVERSAL_PROXY_NOMINATION": Decimal("5.00"),
}


def candidate_readiness_score(candidate):
    interview = dec(rhu2(Decimal("8.0") * dec(candidate["interview_score_avg"])))
    if interview > Decimal("40.00"):
        interview = Decimal("40.00")
    independence = Decimal("30.00") if candidate["independence_result"] == "INDEPENDENT" \
        else Decimal("0.00")
    channel = CHANNEL_POINTS.get(candidate["source_channel"], Decimal("0.00"))
    capacity = Decimal("10.00") - Decimal("2.5") * dec(candidate["external_public_board_count"])
    if capacity < Decimal("0.00"):
        capacity = Decimal("0.00")
    total = interview + independence + channel + capacity
    if total > Decimal("100.00"):
        total = Decimal("100.00")
    if candidate["adverse_reference_found"]:
        total = total - Decimal("15.00")
    return rhu2(total)


# ------------------------------------------------- independence screening (3.3)
FACTOR_ORDER = (
    "PAYMENT_MATERIALITY", "RECENT_EMPLOYMENT", "FAMILY_EMPLOYMENT",
    "AUDITOR_AFFILIATION", "CHARITABLE_MATERIALITY",
)


def screen_factor_results(screen, policy):
    today = clock_date()
    floor = policy["bright_line_payment_floor_cents"]
    revenue_leg = pct_of_cents(policy["bright_line_revenue_pct"],
                               screen["recipient_gross_revenue_cents"])
    threshold = floor if floor > revenue_leg else revenue_leg
    payment_fail = screen["payments_to_company_cents"] > threshold

    ended_on = parse_iso_date(screen["prior_employment_end_on"])

    def employment_fail(lookback_years):
        if ended_on is None:
            return False
        return (today - ended_on).days < int(lookback_years) * 365

    bright_employment = employment_fail(policy["bright_line_lookback_years"])
    enhanced_employment = employment_fail(policy["enhanced_lookback_years"])
    family_fail = bool(screen["family_member_employed"])
    auditor_fail = bool(screen["auditor_affiliation"])
    charitable_threshold = pct_of_cents(policy["enhanced_charitable_pct"],
                                        screen["company_gross_revenue_cents"])
    charitable_fail = screen["charitable_contributions_cents"] >= charitable_threshold

    bright_line_fail_count = sum(
        1 for flag in (payment_fail, bright_employment, family_fail, auditor_fail) if flag)
    qualitative_fail_count = sum(
        1 for flag in (payment_fail, enhanced_employment, family_fail, auditor_fail,
                       charitable_fail) if flag)
    return {
        "payment_fail": payment_fail,
        "bright_employment": bright_employment,
        "enhanced_employment": enhanced_employment,
        "family_fail": family_fail,
        "auditor_fail": auditor_fail,
        "charitable_fail": charitable_fail,
        "bright_line_fail_count": bright_line_fail_count,
        "qualitative_fail_count": qualitative_fail_count,
    }


def disqualifying_factor(results, standard):
    if standard == "ENHANCED":
        flags = (
            ("PAYMENT_MATERIALITY", results["payment_fail"]),
            ("RECENT_EMPLOYMENT", results["enhanced_employment"]),
            ("FAMILY_EMPLOYMENT", results["family_fail"]),
            ("AUDITOR_AFFILIATION", results["auditor_fail"]),
            ("CHARITABLE_MATERIALITY", results["charitable_fail"]),
        )
    else:
        flags = (
            ("PAYMENT_MATERIALITY", results["payment_fail"]),
            ("RECENT_EMPLOYMENT", results["bright_employment"]),
            ("FAMILY_EMPLOYMENT", results["family_fail"]),
            ("AUDITOR_AFFILIATION", results["auditor_fail"]),
        )
    for code, failed in flags:
        if failed:
            return code
    return None


def deciding_fail_count(screen):
    if screen["standard_applied"] == "ENHANCED":
        return screen["qualitative_fail_count"]
    return screen["bright_line_fail_count"]


# ------------------------------------------------------- skills matrix (3.1)
GAP_POPULATION_STATUS = ("SEATED", "ONBOARDING")


def rating_row(director_id, skill_category_id):
    for row in db.skill_ratings.values():
        if row["director_id"] == director_id and row["skill_category_id"] == skill_category_id:
            return row
    return None


def effective_rating(row):
    if row is None:
        return 0
    if row["validation_status"] == "VALIDATED" and row["validated_rating"] is not None:
        return row["validated_rating"]
    return row["self_rating"]


def _variant_rating(row, variant):
    if row is None:
        return 0
    if variant == "VALIDATED_ONLY":
        if row["validation_status"] == "VALIDATED" and row["validated_rating"] is not None:
            return row["validated_rating"]
        return 0
    return row["self_rating"]


def gap_analysis(variant):
    from vocab import CRITICALITY_RANK
    population = [d for d in db.directors.values()
                  if d["service_status"] in GAP_POPULATION_STATUS]
    categories = sorted(db.skill_categories.values(), key=lambda c: c["code"])
    rows = []
    running = Decimal("0.00")
    for category in categories:
        covered = 0
        for director in population:
            row = rating_row(director["id"], category["id"])
            if _variant_rating(row, variant) >= 3:
                covered += 1
        gap = category["required_min_directors"] - covered
        if gap < 0:
            gap = 0
        multiplier = Decimal("1.5") if category["risk_oversight"] else Decimal("1.0")
        weighted = rhu2(Decimal(gap) * dec(category["strategic_weight"]) * multiplier)
        running = running + dec(weighted)
        if gap >= 2:
            severity = "CRITICAL_GAP"
        elif gap == 1:
            severity = "MINOR_GAP"
        else:
            severity = "COVERED"
        rows.append({
            "skill_category_id": category["id"],
            "code": category["code"],
            "criticality": category["criticality"],
            "required_min_directors": category["required_min_directors"],
            "covered_director_count": covered,
            "gap": gap,
            "weighted_gap": weighted,
            "severity": severity,
        })
    priority = None
    if rows:
        ranked = sorted(rows, key=lambda r: (-dec(r["weighted_gap"]),
                                            CRITICALITY_RANK.get(r["criticality"], 9),
                                            r["code"]))
        priority = ranked[0]["code"]
    return {
        "variant": variant,
        "seated_director_count": len(population),
        "category_count": len(categories),
        "board_gap_index": rhu2(running),
        "priority_category_code": priority,
        "categories": rows,
    }


# ------------------------------------------------------ compensation award (3.9)
def excess_offset_pct(pre_offset_total_cents):
    """Tier keyed on the pre-offset total and never on the net total."""
    if pre_offset_total_cents <= 30000000:
        return 0.0
    if pre_offset_total_cents <= 40000000:
        return 2.5
    return 5.0


def award_waterfall(policy, director, service_start_on, service_end_on, share_price_cents,
                    shares_held):
    service_days = (service_end_on - service_start_on).days + 1
    member_seats = 0
    chair_seats = 0
    for row in db.assignments.values():
        if row["director_id"] != director["id"] or row["status"] != "ACTIVE":
            continue
        if row["seat_role"] == "CHAIR":
            chair_seats += 1
        elif row["seat_role"] == "MEMBER":
            member_seats += 1
    retainer = rhu_cents(dec(policy["annual_cash_retainer_cents"]) * Decimal(service_days)
                         / Decimal(365))
    committee_fees = (member_seats * policy["committee_member_fee_cents"]
                      + chair_seats * policy["committee_chair_premium_cents"])
    equity = policy["equity_grant_value_cents"]
    pre_offset = retainer + committee_fees + equity
    offset_pct = excess_offset_pct(pre_offset)
    offset_cents = pct_of_cents(offset_pct, pre_offset)
    total = pre_offset - offset_cents
    requirement = rhu_cents(dec(policy["ownership_multiple"]) * Decimal(retainer + committee_fees))
    actual = shares_held * share_price_cents
    return {
        "service_days": service_days,
        "committee_member_seat_count": member_seats,
        "committee_chair_seat_count": chair_seats,
        "prorated_cash_retainer_cents": retainer,
        "committee_fees_cents": committee_fees,
        "equity_value_cents": equity,
        "pre_offset_total_cents": pre_offset,
        "excess_offset_pct": offset_pct,
        "excess_offset_cents": offset_cents,
        "total_cents": total,
        "ownership_requirement_cents": requirement,
        "ownership_actual_cents": actual,
        "ownership_compliant": actual >= requirement,
    }


def governing_award(director_id):
    """FINALIZED awards ranked cycle_year, finalized_at then created_at descending."""
    rows = [a for a in db.comp_awards.values()
            if a["director_id"] == director_id and a["status"] == "FINALIZED"]
    if not rows:
        return None
    rows.sort(key=lambda a: (a["cycle_year"], str(a["finalized_at"] or ""),
                             str(a["created_at"]), seq_of(a)), reverse=True)
    return rows[0]
