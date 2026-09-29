"""The eight declared calculations (SCAFFOLD 1.3 / PRD 3).

All money is integer cents; every rounding step is ROUND_HALF_UP on Decimal and
never a float. The two pinned rounding orders (per-item damage cap before
summation, per-line admin retention before summation) are honoured literally.
"""

import datetime
from decimal import Decimal, ROUND_HALF_UP

import db
from constants import (
    ADMIN_RETENTION_BPS,
    BRIDGE_PCT_BPS,
    BUCKET_OF_CATEGORY,
    BUCKET_ORDER,
    CATEGORY_CAP_CENTS,
    CRITICAL_TRADE_WEIGHT,
    DISABILITY_POINTS,
    DOB_COUNTED_DOCUMENTATION_STATUSES,
    DOB_FLAG_THRESHOLD_CENTS,
    ELDER_AGE_THRESHOLD,
    ELDER_POINTS,
    ELIGIBLE_PURPOSES_BY_RESTRICTION,
    HOUSEHOLD_POINT_CAP,
    HOUSEHOLD_POINT_PER_EXTRA_MEMBER,
    INCOME_POINTS,
    NORMAL_TRADE_WEIGHT,
    RESTRICTION_SPECIFICITY,
    SCORE_CEILING,
    TIER_A_CEILING_CENTS,
    TIER_B_CEILING_CENTS,
    UNINSURED_POINTS,
    VOLUNTEER_HOURS_PER_DAY,
)


# ---------------------------------------------------------------------------
# Rounding
# ---------------------------------------------------------------------------
def round_half_up(numerator, denominator):
    """round_half_up(numerator / denominator) on exact integers."""
    value = Decimal(numerator) / Decimal(denominator)
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def retention_for(net_cents):
    return round_half_up(net_cents * ADMIN_RETENTION_BPS, 10000)


def to_date(raw):
    if raw is None:
        return None
    return datetime.date.fromisoformat(str(raw)[:10])


# ---------------------------------------------------------------------------
# 1. survivor_priority_score
# ---------------------------------------------------------------------------
def survivor_priority_score(survivor):
    score = INCOME_POINTS[survivor["income_band"]]
    score += min(
        HOUSEHOLD_POINT_CAP,
        HOUSEHOLD_POINT_PER_EXTRA_MEMBER * max(0, survivor["household_size"] - 1),
    )
    if survivor["has_member_with_disability"]:
        score += DISABILITY_POINTS
    if survivor["head_of_household_age"] >= ELDER_AGE_THRESHOLD:
        score += ELDER_POINTS
    if survivor["is_uninsured"]:
        score += UNINSURED_POINTS
    return min(SCORE_CEILING, score)


# ---------------------------------------------------------------------------
# 2. verified_damage_total
# ---------------------------------------------------------------------------
def capped_item_cents(item):
    cost = item.get("verified_cost_cents") or 0
    return min(cost, CATEGORY_CAP_CENTS[item["category"]])


def case_damage_items(case_id):
    return [d for d in db.damage_items.values() if d["case_id"] == case_id]


def verified_damage_total(case_id):
    return sum(
        capped_item_cents(d)
        for d in case_damage_items(case_id)
        if d["verification_status"] == "VERIFIED"
    )


# ---------------------------------------------------------------------------
# 3. unmet_need_determination
# ---------------------------------------------------------------------------
def bucket_needs(case):
    need = {bucket: 0 for bucket in BUCKET_ORDER}
    for item in case_damage_items(case["id"]):
        if item["verification_status"] != "VERIFIED":
            continue
        need[BUCKET_OF_CATEGORY[item["category"]]] += capped_item_cents(item)
    need["TEMPORARY_HOUSING"] = case["temporary_housing_need_cents"]
    return need


def bucket_offsets(case_id):
    offset = {bucket: 0 for bucket in BUCKET_ORDER}
    for record in db.assistance_records.values():
        if record["case_id"] != case_id:
            continue
        if record["documentation_status"] != "DOCUMENTED":
            continue
        offset[record["purpose_code"]] += record["awarded_cents"]
    return offset


def unmet_need_determination(case, variant):
    need = bucket_needs(case)
    offset = bucket_offsets(case["id"])
    if variant == "PURPOSE_MATCHED":
        unmet = sum(max(0, need[b] - offset[b]) for b in BUCKET_ORDER)
    else:
        unmet = max(
            0,
            sum(need[b] for b in BUCKET_ORDER) - sum(offset[b] for b in BUCKET_ORDER),
        )
    damage_total = (
        need["STRUCTURE_REPAIR"]
        + need["CONTENTS_REPLACEMENT"]
        + need["ACCESSIBILITY_MOD"]
    )
    return {
        "bucket_need_cents": {b: need[b] for b in BUCKET_ORDER},
        "bucket_offset_cents": {b: offset[b] for b in BUCKET_ORDER},
        "unmet_need_total_cents": unmet,
        "verified_damage_total_cents": damage_total,
        "total_documented_assistance_cents": sum(offset[b] for b in BUCKET_ORDER),
    }


# ---------------------------------------------------------------------------
# 4. dob_exposure_check
# ---------------------------------------------------------------------------
def sibling_cases(survivor_id):
    rows = [
        c
        for c in db.recovery_cases.values()
        if c["survivor_id"] == survivor_id and c["case_status"] != "INACTIVE"
    ]
    return db.sorted_records(rows)


def dob_exposure_check(case, purpose_code, requested_cents, exclude_disbursement_id=None):
    siblings = sibling_cases(case["survivor_id"])
    sibling_ids = [c["id"] for c in siblings]

    dob_pool = 0
    for record in db.assistance_records.values():
        if record["case_id"] not in sibling_ids:
            continue
        if record["purpose_code"] != purpose_code:
            continue
        if record["documentation_status"] not in DOB_COUNTED_DOCUMENTATION_STATUSES:
            continue
        if record["is_excluded_from_dob"]:
            continue
        dob_pool += record["awarded_cents"]

    prior_disbursed = 0
    for row in db.disbursements.values():
        if row["case_id"] not in sibling_ids:
            continue
        if row["purpose_code"] != purpose_code:
            continue
        if row["status"] not in ("APPROVED", "PAID"):
            continue
        if exclude_disbursement_id is not None and row["id"] == exclude_disbursement_id:
            continue
        prior_disbursed += row["requested_cents"]

    bucket_need = bucket_needs(case)[purpose_code]
    exposure = max(
        0, dob_pool + prior_disbursed + requested_cents - bucket_need
    )
    return {
        "sibling_case_ids": sibling_ids,
        "dob_pool_cents": dob_pool,
        "prior_disbursed_cents": prior_disbursed,
        "bucket_need_cents": bucket_need,
        "dob_exposure_cents": exposure,
        "cleared": exposure <= DOB_FLAG_THRESHOLD_CENTS,
    }


# ---------------------------------------------------------------------------
# 5. restricted_fund_waterfall
# ---------------------------------------------------------------------------
def eligible_purpose_codes(restriction_code):
    return list(ELIGIBLE_PURPOSES_BY_RESTRICTION[restriction_code])


def restriction_specificity(restriction_code):
    return RESTRICTION_SPECIFICITY[restriction_code]


def source_unexpired(source):
    if not source.get("expires_on"):
        return True
    return to_date(source["expires_on"]) >= db.clock_date()


def open_unexpired_sources():
    return [
        s
        for s in db.sorted_records(list(db.funding_sources.values()))
        if s["status"] == "OPEN" and source_unexpired(s)
    ]


def waterfall_candidates(purpose_code):
    eligible = [
        s
        for s in db.sorted_records(list(db.funding_sources.values()))
        if s["status"] == "OPEN"
        and purpose_code in s["eligible_purpose_codes"]
        and source_unexpired(s)
        and s["available_cents"] > 0
    ]

    def sort_key(source):
        expires = source.get("expires_on")
        return (
            -source["restriction_specificity"],
            0 if expires else 1,
            expires or "",
            source["created_at"],
            source["_seq"],
        )

    return sorted(eligible, key=sort_key)


def restricted_fund_waterfall(purpose_code, requested_cents):
    """Returns (lines, net_cents, admin_retained_cents, gross_cents) or None
    when the eligible pool cannot cover the request."""
    remaining_net = requested_cents
    lines = []
    for source in waterfall_candidates(purpose_code):
        if remaining_net == 0:
            break
        available = source["available_cents"]
        if source["admin_retention_allowed"]:
            net_cap = (available * 10000) // (10000 + ADMIN_RETENTION_BPS)
            while net_cap > 0 and net_cap + retention_for(net_cap) > available:
                net_cap -= 1
        else:
            net_cap = available
        net_line = min(remaining_net, net_cap)
        if net_line == 0:
            continue
        retention_line = (
            retention_for(net_line) if source["admin_retention_allowed"] else 0
        )
        lines.append(
            {
                "funding_source_id": source["id"],
                "net_cents": net_line,
                "retention_cents": retention_line,
                "gross_cents": net_line + retention_line,
            }
        )
        remaining_net -= net_line

    if remaining_net > 0:
        return None

    net_cents = sum(line["net_cents"] for line in lines)
    admin_retained_cents = sum(line["retention_cents"] for line in lines)
    return lines, net_cents, admin_retained_cents, net_cents + admin_retained_cents


# ---------------------------------------------------------------------------
# 6. table_award_assembly
# ---------------------------------------------------------------------------
def presentation_pledged_sum(presentation_id, statuses):
    return sum(
        c["pledged_cents"]
        for c in db.commitments.values()
        if c["presentation_id"] == presentation_id and c["status"] in statuses
    )


def bridge_tier_for(unmet):
    if unmet < TIER_A_CEILING_CENTS:
        return "TIER_A"
    if unmet < TIER_B_CEILING_CENTS:
        return "TIER_B"
    return "TIER_C"


def unrestricted_bridge_pool():
    return sum(
        s["available_cents"]
        for s in db.funding_sources.values()
        if s["restriction_code"] == "UNRESTRICTED"
        and s["status"] == "OPEN"
        and source_unexpired(s)
    )


def table_award_assembly(presentation):
    assessment = db.assessments[presentation["assessment_id"]]
    unmet = assessment["unmet_need_total_cents"]
    tier = bridge_tier_for(unmet)
    pledged_total = presentation_pledged_sum(presentation["id"], ("PLEDGED",))
    gap = max(0, unmet - pledged_total)
    bridge_cap = round_half_up(unmet * BRIDGE_PCT_BPS[tier], 10000)
    bridge_pool = unrestricted_bridge_pool()
    bridge_authorized = min(gap, bridge_cap, bridge_pool)
    awarded = pledged_total + bridge_authorized
    return {
        "unmet": unmet,
        "bridge_tier": tier,
        "pledged_total_cents": pledged_total,
        "bridge_authorized_cents": bridge_authorized,
        "awarded_cents": awarded,
        "shortfall_cents": max(0, unmet - awarded),
    }


# ---------------------------------------------------------------------------
# 7. volunteer_skill_fit_score
# ---------------------------------------------------------------------------
def day_count(arrival, departure):
    return (departure - arrival).days + 1


def volunteer_skill_fit_score(project, group, arrival, departure, variant):
    days = day_count(arrival, departure)
    required = project["required_trade_hours"] or {}
    critical = project.get("critical_trades") or []
    profile = group["skill_profile"] or {}

    numerator = 0
    denominator = 0
    for trade, hours in required.items():
        weight = CRITICAL_TRADE_WEIGHT if trade in critical else NORMAL_TRADE_WEIGHT
        if variant == "COVERAGE_WEIGHTED":
            capacity = profile.get(trade, 0) * VOLUNTEER_HOURS_PER_DAY * days
            numerator += weight * min(hours, capacity)
            denominator += weight * hours
        else:
            numerator += weight * (1 if profile.get(trade, 0) >= 1 else 0)
            denominator += weight

    if denominator == 0:
        score_bps = 10000
    else:
        score_bps = round_half_up(10000 * numerator, denominator)
    return {
        "day_count": days,
        "numerator": numerator,
        "denominator": denominator,
        "score_bps": score_bps,
    }
