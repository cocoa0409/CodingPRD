"""All derived quantities (PRD §2.9, §3.2, §3.4, §3.5, §3.7, §3.8, §3.9).

Round half up is the system's only rounding mode.
"""

from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

import store
from errors import fail
from validation import (DOMAIN_CODES, as_date, as_dt, add_months, day_count,
                        days_of_month, month_first_day, SUBSCALE_CODES)

ZERO = Decimal("0")

MIN_LEVEL_BY_ROLE = {"DIRECTOR": 4, "LEAD_TEACHER": 3, "ASSISTANT": 1}

OBSERVATION_FRACTIONS = [
    (Decimal("6.00"), Decimal("1.00")),
    (Decimal("5.00"), Decimal("0.80")),
    (Decimal("4.00"), Decimal("0.60")),
    (Decimal("3.00"), Decimal("0.40")),
]
CREDENTIAL_FRACTIONS = [
    (Decimal("95.00"), Decimal("1.00")),
    (Decimal("85.00"), Decimal("0.80")),
    (Decimal("70.00"), Decimal("0.60")),
    (Decimal("55.00"), Decimal("0.40")),
]
POINTS_TIER_THRESHOLDS = [
    (Decimal("85.00"), 5),
    (Decimal("70.00"), 4),
    (Decimal("55.00"), 3),
    (Decimal("40.00"), 2),
]
BLOCK_TIER_CEILING = {0: 1, 1: 2, 2: 4, 3: 5}
TIER_COMPLIANCE_FLOOR = {
    1: Decimal("0.00"),
    2: Decimal("60.00"),
    3: Decimal("80.00"),
    4: Decimal("90.00"),
    5: Decimal("95.00"),
}
TIER_MULTIPLIER = {
    1: Decimal("1.00"),
    2: Decimal("1.05"),
    3: Decimal("1.15"),
    4: Decimal("1.30"),
    5: Decimal("1.50"),
}
REGION_FACTOR = {
    "URBAN": Decimal("1.00"),
    "RURAL": Decimal("1.08"),
    "FRONTIER": Decimal("1.15"),
}
BASE_DAILY_RATE_CENTS = {
    "INFANT": 4500,
    "TODDLER": 3800,
    "PRESCHOOL": 3200,
}
CATEGORY_SHARE = {
    "EQUIPMENT": Decimal("0.40"),
    "PROF_DEV": Decimal("0.30"),
    "FACILITY": Decimal("0.25"),
    "ADMIN": Decimal("0.10"),
}
CATEGORY_MATCH_RATE = {
    "EQUIPMENT": Decimal("0.90"),
    "PROF_DEV": Decimal("1.00"),
    "FACILITY": Decimal("0.75"),
    "ADMIN": Decimal("0.50"),
}
TIER_HOURS_CEILING = {
    1: Decimal("40.0"),
    2: Decimal("32.0"),
    3: Decimal("24.0"),
    4: Decimal("16.0"),
    5: Decimal("8.0"),
}
TIER_SPEND_CEILING_CENTS = {
    1: 900000,
    2: 750000,
    3: 600000,
    4: 400000,
    5: 250000,
}
STATE_BASE_FUNDING_BALANCE_CENTS = 500000
RELIABILITY_THRESHOLD = Decimal("83.33")
ANCHOR_AGREEMENT_THRESHOLD = Decimal("85.00")


def dec(value):
    if isinstance(value, Decimal):
        return value
    if value is None:
        return None
    return Decimal(str(value))


def rhu(value, places):
    quant = Decimal(1).scaleb(-places)
    return dec(value).quantize(quant, rounding=ROUND_HALF_UP)


def rhu_int(value):
    return int(dec(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def floor_int(value):
    return int(dec(value).to_integral_value(rounding="ROUND_FLOOR"))


def band_fraction(value, table, default):
    for threshold, fraction in table:
        if value >= threshold:
            return fraction
    return default


# ------------------------------------------------------------ credentials


def compute_credential_compliance(provider):
    clock_date = store.today()
    qualifying = ZERO
    for cred in store.DB.staff_credentials.values():
        if cred["provider_id"] != provider["id"]:
            continue
        if cred["employment_status"] != "ACTIVE":
            continue
        if cred["registry_status"] != "VERIFIED":
            continue
        expires = as_date(cred.get("expires_on"))
        if expires is None or expires < clock_date:
            continue
        if cred["credential_level"] < MIN_LEVEL_BY_ROLE[cred["role_type"]]:
            continue
        qualifying += dec(cred["fte"])
    denominator = dec(provider["active_staff_fte"])
    if denominator == 0:
        raw = ZERO
    else:
        raw = Decimal(100) * qualifying / denominator
    value = rhu(raw, 2)
    if value > Decimal("100.00"):
        value = Decimal("100.00")
    return value, qualifying, denominator


def refresh_credential_compliance(provider):
    """Recompute and persist; returns True when the stored value changed."""
    value, _, _ = compute_credential_compliance(provider)
    changed = dec(provider.get("credential_compliance_pct")) != value
    provider["credential_compliance_pct"] = value
    return changed


# ------------------------------------------------------------ observation


def current_scores(visit_id, observer_id):
    """Map subscale_code -> current row for that (visit, observer, subscale)."""
    best = {}
    for row in store.DB.observation_scores.values():
        if row["observation_visit_id"] != visit_id or row["observer_id"] != observer_id:
            continue
        code = row["subscale_code"]
        cur = best.get(code)
        if cur is None:
            best[code] = row
            continue
        if (row["attempt_no"], row["created_at"], row.get("_seq", 0)) > \
                (cur["attempt_no"], cur["created_at"], cur.get("_seq", 0)):
            best[code] = row
    return best


def has_full_set(visit_id, observer_id):
    rows = current_scores(visit_id, observer_id)
    return all(code in rows for code in SUBSCALE_CODES)


def compute_composite(visit):
    rows = current_scores(visit["id"], visit["lead_observer_id"])
    values = []
    for code in SUBSCALE_CODES:
        row = rows.get(code)
        if row is None:
            fail("ERR_OBSERVATION_SCORES_INCOMPLETE",
                 "the lead observer has no current score for %s" % code)
        values.append(dec(row["raw_score"]))
    total = ZERO
    for value in values:
        total += value
    return rhu(total / Decimal(6), 2)


def compute_reliability(visit):
    secondary = visit.get("secondary_observer_id")
    if not secondary:
        fail("ERR_OBSERVATION_SCORES_INCOMPLETE", "the visit has no secondary observer")
    lead_rows = current_scores(visit["id"], visit["lead_observer_id"])
    sec_rows = current_scores(visit["id"], secondary)
    matched = 0
    for code in SUBSCALE_CODES:
        lead = lead_rows.get(code)
        sec = sec_rows.get(code)
        if lead is None or sec is None:
            fail("ERR_OBSERVATION_SCORES_INCOMPLETE",
                 "both observers must hold a current score for %s" % code)
        if abs(dec(lead["raw_score"]) - dec(sec["raw_score"])) <= Decimal("1.0"):
            matched += 1
    return rhu(Decimal(100) * Decimal(matched) / Decimal(6), 2)


# ------------------------------------------------------------ domain points


def domains_by_code():
    return {d["domain_code"]: d for d in store.DB.standard_domains.values()}


def compute_domain_points(cycle, variant, provider, self_assessment):
    """calculations.domain_points_award — PROVISIONAL or FINAL variant."""
    domains = domains_by_code()
    if variant == "FINAL":
        credited_map = self_assessment.get("verified_points") if self_assessment else None
    else:
        credited_map = self_assessment.get("claimed_points") if self_assessment else None
    credited_map = credited_map or {}
    composite = dec(cycle.get("observation_composite"))
    compliance = dec(provider.get("credential_compliance_pct") or 0)
    points = {}
    for code, domain in domains.items():
        credited = credited_map.get(code)
        credited = 0 if credited is None else int(credited)
        max_points = int(domain["max_points"])
        if domain.get("observation_linked"):
            if composite is None:
                awarded = credited
            else:
                fraction = band_fraction(composite, OBSERVATION_FRACTIONS, Decimal("0.20"))
                awarded = rhu_int(Decimal(max_points) * fraction)
        elif code == "STAFF_QUALIFICATIONS":
            fraction = band_fraction(compliance, CREDENTIAL_FRACTIONS, Decimal("0.20"))
            cap = rhu_int(Decimal(max_points) * fraction)
            awarded = min(credited, cap)
        else:
            awarded = credited
        points[code] = int(awarded)
    return points


def compute_tier_determination(cycle, domain_points, variant):
    """calculations.rating_tier_determination — weighted total, block gates, tier."""
    domains = domains_by_code()
    composite = dec(cycle.get("observation_composite"))
    total = ZERO
    for code, domain in domains.items():
        awarded = Decimal(int(domain_points.get(code, 0)))
        max_points = Decimal(int(domain["max_points"]))
        if max_points == 0:
            continue
        total += (awarded / max_points) * dec(domain["weight"]) * Decimal(100)
    weighted_total = rhu(total, 2)
    points_tier = 1
    for threshold, tier in POINTS_TIER_THRESHOLDS:
        if weighted_total >= threshold:
            points_tier = tier
            break

    block_clearance = {}
    for level in (1, 2, 3):
        cleared = True
        for code, domain in domains.items():
            if int(domain["block_level"]) != level:
                continue
            if int(domain_points.get(code, 0)) < int(domain["block_min_points"]):
                cleared = False
                break
            if domain.get("observation_linked"):
                minimum = dec(domain.get("min_composite_for_block"))
                if composite is None:
                    # A provisional run treats a null composite as satisfying every
                    # observation-linked block minimum; a final run requires one.
                    if variant == "FINAL":
                        cleared = False
                        break
                elif minimum is not None and composite < minimum:
                    cleared = False
                    break
        block_clearance[str(level)] = "CLEARED" if cleared else "NOT_CLEARED"

    highest = 0
    for level in (1, 2, 3):
        if block_clearance[str(level)] == "CLEARED":
            highest = level
        else:
            break
    ceiling = BLOCK_TIER_CEILING[highest]
    awarded_tier = min(points_tier, ceiling)
    return {
        "weighted_total": weighted_total,
        "points_tier": points_tier,
        "block_clearance": block_clearance,
        "highest_block_cleared": highest,
        "awarded_tier": awarded_tier,
    }


# ------------------------------------------------------------ validity window


def compute_validity(award_instant, awarded_tier, inherited_effective_date=None):
    """calculations.validity_period."""
    if inherited_effective_date is not None:
        effective = as_dt(inherited_effective_date)
    else:
        award_date = award_instant.date()
        year = award_date.year + (1 if award_date.month == 12 else 0)
        month = 1 if award_date.month == 12 else award_date.month + 1
        effective = award_instant.replace(year=year, month=month, day=1, hour=0, minute=0,
                                          second=0, microsecond=0)
    validity_months = 36 if awarded_tier is not None and awarded_tier >= 4 else 24
    expires = add_months(effective, validity_months) - timedelta(days=1)
    expires = expires.replace(hour=23, minute=59, second=59, microsecond=999000)
    rerating = (expires - timedelta(days=90)).replace(hour=0, minute=0, second=0, microsecond=0)
    return {
        "effective_date": effective,
        "validity_months": validity_months,
        "expires_on": expires,
        "rerating_window_opens_on": rerating,
    }


# ------------------------------------------------------------ subsidy


COVERING_STATES = ("ACTIVE", "SUPERSEDED", "EXPIRED")


def covering_cycle(provider_id, day, admit_cycle_ids=()):
    """The rating cycle in force for one calendar day (PRD §3.7).

    ``admit_cycle_ids`` names cycles that must be treated as in force even though
    their state is not one of the three covering states. It carries the cycle a
    sustained appeal has just re-awarded: PRD §3.7 requires that "Appeal cascades
    push it up when a tier increase means past months were underpaid", so the
    third hop of the sustain cascade values the claim under the newly ordered
    tier rather than at the unrated base multiplier.
    """
    best = None
    for cycle in store.DB.rating_cycles.values():
        if cycle["provider_id"] != provider_id:
            continue
        if cycle["status"] not in COVERING_STATES and cycle["id"] not in admit_cycle_ids:
            continue
        if cycle.get("awarded_tier") is None:
            continue
        start = as_date(cycle.get("effective_date"))
        end = as_date(cycle.get("expires_on"))
        if start is None or end is None:
            continue
        if day < start or day > end:
            continue
        if best is None:
            best = cycle
            continue
        best_start = as_date(best.get("effective_date"))
        if (start, cycle["created_at"], cycle.get("_seq", 0)) > \
                (best_start, best["created_at"], best.get("_seq", 0)):
            best = cycle
    return best


def tier_for_day(provider_id, day, admit_cycle_ids=()):
    cycle = covering_cycle(provider_id, day, admit_cycle_ids)
    if cycle is None:
        return 1
    return int(cycle["awarded_tier"])


def compute_base_amount_cents(child_days):
    total = 0
    for band, rate in BASE_DAILY_RATE_CENTS.items():
        total += int(child_days.get(band, 0) or 0) * rate
    return total


def compute_tier_multiplier(provider, service_month, variant, admit_cycle_ids=()):
    if variant == "RECONCILED":
        days = days_of_month(service_month)
        total = ZERO
        for day in days:
            total += TIER_MULTIPLIER[tier_for_day(provider["id"], day, admit_cycle_ids)]
        return rhu(total / Decimal(len(days)), 4)
    first = month_first_day(service_month)
    return rhu(TIER_MULTIPLIER[tier_for_day(provider["id"], first, admit_cycle_ids)], 4)


def compute_reimbursement_cents(provider, child_days, multiplier):
    """Pinned per-band rounding: each band amount rounded first, then summed."""
    region = REGION_FACTOR[provider["region_code"]]
    total = 0
    for band, rate in BASE_DAILY_RATE_CENTS.items():
        days = Decimal(int(child_days.get(band, 0) or 0))
        amount = days * Decimal(rate) * dec(multiplier) * region
        total += rhu_int(amount)
    return total


def compute_subsidy(provider, claim, variant, admit_cycle_ids=()):
    multiplier = compute_tier_multiplier(
        provider, claim["service_month"], variant, admit_cycle_ids
    )
    reimbursement = compute_reimbursement_cents(provider, claim["child_days"], multiplier)
    return multiplier, reimbursement


# ------------------------------------------------------------ grants


def category_ceilings(grant):
    awarded = Decimal(int(grant["awarded_amount_cents"]))
    return {cat: floor_int(awarded * share) for cat, share in CATEGORY_SHARE.items()}


def run_reimbursement_waterfall(grant):
    """calculations.grant_reimbursement_waterfall — pinned per-line rounding."""
    ceilings = category_ceilings(grant)
    lines = [e for e in store.DB.grant_expenditures.values()
             if e["improvement_grant_id"] == grant["id"] and e["status"] == "APPROVED"]
    lines.sort(key=lambda e: (as_date(e["invoice_date"]), e["created_at"], e.get("_seq", 0)))
    grant_total = int(grant["reimbursed_cents"])
    cat_totals = {cat: int(grant["category_spend_cents"].get(cat, 0))
                  for cat in CATEGORY_SHARE}
    awarded = int(grant["awarded_amount_cents"])
    processed_amount = 0
    for line in lines:
        cat = line["category"]
        gross = rhu_int(Decimal(int(line["amount_cents"])) * CATEGORY_MATCH_RATE[cat])
        cat_room = ceilings[cat] - cat_totals.get(cat, 0)
        grant_room = awarded - grant_total
        reimbursable = min(gross, cat_room, grant_room)
        if reimbursable < 0:
            reimbursable = 0
        line["reimbursable_cents"] = reimbursable
        line["disallowed_cents"] = int(line["amount_cents"]) - reimbursable
        line["status"] = "REIMBURSED"
        store.touch(line)
        grant_total += reimbursable
        cat_totals[cat] = cat_totals.get(cat, 0) + reimbursable
        processed_amount += int(line["amount_cents"])
    grant["reimbursed_cents"] = grant_total
    grant["committed_cents"] = int(grant["committed_cents"]) - processed_amount
    grant["available_cents"] = awarded - int(grant["committed_cents"]) - grant_total
    grant["category_spend_cents"] = cat_totals
    return lines


def compute_recovery(grant):
    """calculations.grant_compliance_recovery."""
    deadline = as_date(grant["spend_deadline"])
    late_total = 0
    prof_dev_total = 0
    for line in store.DB.grant_expenditures.values():
        if line["improvement_grant_id"] != grant["id"] or line["status"] != "REIMBURSED":
            continue
        reimbursable = int(line["reimbursable_cents"])
        if as_date(line["invoice_date"]) > deadline:
            late_total += reimbursable
        if line["category"] == "PROF_DEV":
            prof_dev_total += reimbursable
    requirement = floor_int(Decimal(int(grant["awarded_amount_cents"])) * Decimal("0.25"))
    shortfall = requirement - prof_dev_total
    if shortfall < 0:
        shortfall = 0
    penalty = rhu_int(Decimal(shortfall) / Decimal(2))
    return late_total + penalty


# ------------------------------------------------------------ coaching


def compute_allocation_cost(allocated_hours, hourly_rate_cents):
    """calculations.coaching_allocation_cost — pinned three-step order."""
    base = rhu_int(dec(allocated_hours) * Decimal(int(hourly_rate_cents)))
    if base < 50000:
        rate = Decimal("0.12")
    elif base < 200000:
        rate = Decimal("0.09")
    else:
        rate = Decimal("0.06")
    admin_fee = rhu_int(Decimal(base) * rate)
    return base, admin_fee, base + admin_fee


def effective_tier(provider):
    tier = provider.get("current_tier")
    return int(tier) if tier else 1


def funding_balance_cents(funding_source, grant):
    if funding_source == "GRANT":
        return int(grant["available_cents"])
    return STATE_BASE_FUNDING_BALANCE_CENTS


def compute_spend_cap(provider, funding_source, grant):
    tier = effective_tier(provider)
    return min(TIER_SPEND_CEILING_CENTS[tier], funding_balance_cents(funding_source, grant))


def interval_hours(start, end):
    seconds = (end - start).total_seconds()
    return rhu(Decimal(seconds) / Decimal(3600), 1)
