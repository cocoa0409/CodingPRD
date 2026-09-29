"""Every calculation rule of the PRD, with the pinned rounding / evaluation orders."""
from datetime import timedelta
from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP

import clock
import db

# --- constants -------------------------------------------------------------
AUTHORIZED_DAYS_PER_MONTH = 22
ABSENCE_ALLOWANCE_DAYS_PER_LINE = 3
ADVANCE_PCT = 80

OPEN_FINDING_PENALTY = Decimal("4.0")
QUALITY_WEIGHTS = [Decimal("0.5"), Decimal("0.3"), Decimal("0.2")]
ANCHOR_WINDOW_DAYS = 180
TIER_1_FLOOR = Decimal("85")
TIER_2_FLOOR = Decimal("70")

TIER_100_PCT = Decimal("0.12")
TIER_50_PCT = Decimal("0.08")
TIER_15_PCT = Decimal("0.05")
INSURANCE_ADMIN_FEE_PCT = Decimal("0.03")

MIN_BILLABLE_HOURS = 4
CDA_PREMIUM_PCT = Decimal("0.10")
CHILD_DEV_TEACHER_PREMIUM_PCT = Decimal("0.18")
FEE_TIER_30000_PCT = Decimal("0.06")
FEE_TIER_15000_PCT = Decimal("0.08")
FEE_TIER_BASE_PCT = Decimal("0.10")

FOOD_RATES = {
    "TIER_I": {"breakfast": 187, "lunch": 348, "snack": 100},
    "TIER_II": {"breakfast": 67, "lunch": 210, "snack": 27},
}
SUBSIDY_SHARE_TIER_I_FLOOR = Decimal("0.5000")

TARGET_MARGIN_PCT = Decimal("0.15")
TUITION_ROUNDING_CENTS = 500
SUSTAINABLE_FLOOR = Decimal("0.1500")
THIN_FLOOR = Decimal("0.0500")

BUFFER_MINUTES = 30
CREDENTIAL_RANK = {"NONE": 0, "CDA": 1, "CHILD_DEV_TEACHER": 2}


# --- numeric helpers -------------------------------------------------------

def dec(value):
    return Decimal(str(value))


def round_half_up(value, places=0):
    quantum = Decimal(1).scaleb(-places)
    return Decimal(value).quantize(quantum, rounding=ROUND_HALF_UP)


def cents(value):
    return int(round_half_up(value, 0))


def ceil_int(value):
    return int(Decimal(value).to_integral_value(rounding=ROUND_CEILING))


# --- subsidy claim amount --------------------------------------------------

def _ordered_lines(claim):
    """Line ordering is Enrollment.created_at ASC — never by identifier."""
    def key(index_line):
        index, line = index_line
        enrollment = db.enrollments.get(line.get("enrollment_id"))
        return (enrollment["_seq"] if enrollment else 0, index)

    return [line for _, line in sorted(enumerate(claim["lines"]), key=key)]


def provisional_amount(claim, contract):
    """Variant PROVISIONAL_ADVANCE: absence days at the FULL rate, joint 22-day cap."""
    total = 0
    for line in _ordered_lines(claim):
        payable_days = min(
            int(line.get("attended_days", 0)) + int(line.get("absent_days", 0)),
            AUTHORIZED_DAYS_PER_MONTH,
        )
        total += payable_days * contract["daily_rate_cents"]
    return total


def final_amount(claim, contract):
    """Variant FINAL_RECONCILED: capped/discounted absences, per-line rounding."""
    rate = contract["daily_rate_cents"]
    absence_rate_pct = dec(contract["absence_rate_pct"])
    total = 0
    for line in _ordered_lines(claim):
        attended_component = min(int(line.get("attended_days", 0)), AUTHORIZED_DAYS_PER_MONTH) * rate
        enrollment = db.enrollments.get(line.get("enrollment_id"))
        if enrollment is not None and enrollment["status"] in ("WITHDRAWN", "TRANSFERRED"):
            absent_component = 0
        else:
            paid_absent_days = min(int(line.get("absent_days", 0)), ABSENCE_ALLOWANCE_DAYS_PER_LINE)
            absent_component = cents(dec(paid_absent_days) * dec(rate) * absence_rate_pct / dec(100))
        total += attended_component + absent_component
    return total


def advance_amount(provisional_cents):
    """Truncated downward — the only place the system does not round half up."""
    return (provisional_cents * ADVANCE_PCT) // 100


# --- provider quality score ------------------------------------------------

def completed_visits(provider_id):
    return [
        v for v in db.visits.values()
        if v["provider_id"] == provider_id and v["status"] == "COMPLETED"
    ]


def coaching_weighted_score(provider_id):
    visits = completed_visits(provider_id)
    visits.sort(key=lambda v: (clock.date_of(v["visit_conducted_on"]), v["_seq"]), reverse=True)
    picked = visits[:3]
    if not picked:
        return None
    used = QUALITY_WEIGHTS[:len(picked)]
    numerator = sum(w * dec(v["observation_score"]) for w, v in zip(used, picked))
    return round_half_up(numerator / sum(used), 2)


def compliance_anchored_score(provider_id):
    today = clock.today()
    low = clock.plus_days(today, -ANCHOR_WINDOW_DAYS)
    window = []
    for visit in completed_visits(provider_id):
        conducted = clock.date_of(visit["visit_conducted_on"])
        if conducted is not None and low <= conducted <= today:
            window.append(visit)
    if not window:
        return None
    total = sum(dec(v["observation_score"]) for v in window)
    return round_half_up(total / dec(len(window)), 2)


def quality_tail(score, open_finding_count):
    """Shared tail of both variants: open-finding penalty, clamp, tier banding."""
    penalised = round_half_up(score - OPEN_FINDING_PENALTY * dec(open_finding_count), 2)
    penalised = max(Decimal("0.00"), min(Decimal("100.00"), penalised))
    if penalised >= TIER_1_FLOOR:
        tier = "TIER_1"
    elif penalised >= TIER_2_FLOOR:
        tier = "TIER_2"
    else:
        tier = "TIER_3"
    return float(penalised), tier


# --- group purchase order --------------------------------------------------

def group_purchase_total(order):
    total_quantity = sum(int(line["quantity"]) for line in order["lines"])
    if total_quantity >= 100:
        discount = TIER_100_PCT
    elif total_quantity >= 50:
        discount = TIER_50_PCT
    elif total_quantity >= 15:
        discount = TIER_15_PCT
    else:
        discount = Decimal("0.00")

    subtotal = 0
    for line in order["lines"]:  # request-body order, which is the persisted order
        gross = dec(line["unit_price_cents"]) * dec(line["quantity"])
        subtotal += cents(gross * (Decimal(1) - discount))  # per-line rounding

    fee = cents(dec(subtotal) * INSURANCE_ADMIN_FEE_PCT) if order["category"] == "INSURANCE" else 0
    return {
        "total_quantity": total_quantity,
        "discount_pct": float(discount),
        "subtotal_cents": subtotal,
        "insurance_admin_fee_cents": fee,
        "total_cents": subtotal + fee,
    }


# --- substitute assignment cost -------------------------------------------

def assignment_cost(assignment, substitute):
    start = clock.parse_instant(assignment["start_at"])
    end = clock.parse_instant(assignment["end_at"])
    duration_minutes = int((end - start).total_seconds() // 60)
    billable_hours = max(MIN_BILLABLE_HOURS, ceil_int(dec(duration_minutes) / dec(60)))
    base = billable_hours * substitute["hourly_rate_cents"]

    level = substitute["credential_level"]
    if level == "CDA":
        premium_pct = CDA_PREMIUM_PCT
    elif level == "CHILD_DEV_TEACHER":
        premium_pct = CHILD_DEV_TEACHER_PREMIUM_PCT
    else:
        premium_pct = Decimal("0.00")
    premium = cents(dec(base) * premium_pct)
    pre_fee_subtotal = base + premium

    # Evaluation order is pinned: the fee tier keys on pre_fee_subtotal_cents.
    if pre_fee_subtotal >= 30000:
        fee_pct = FEE_TIER_30000_PCT
    elif pre_fee_subtotal >= 15000:
        fee_pct = FEE_TIER_15000_PCT
    else:
        fee_pct = FEE_TIER_BASE_PCT
    fee = cents(dec(pre_fee_subtotal) * fee_pct)
    return {
        "billable_hours": billable_hours,
        "pre_fee_subtotal_cents": pre_fee_subtotal,
        "network_admin_fee_cents": fee,
        "total_cost_cents": pre_fee_subtotal + fee,
    }


# --- food program reimbursement -------------------------------------------

def meal_line_amount(line, tier):
    rates = FOOD_RATES[tier]
    return (
        int(line.get("breakfasts", 0)) * rates["breakfast"]
        + int(line.get("lunches", 0)) * rates["lunch"]
        + int(line.get("snacks", 0)) * rates["snack"]
    )


def food_program_tiering(provider, meal_lines):
    enrolled = [
        e for e in db.enrollments.values()
        if e["provider_id"] == provider["id"] and e["status"] == "ENROLLED"
    ]
    if not enrolled:
        share = Decimal("0.0000")
    else:
        certified = len([e for e in enrolled if e["subsidy_certified"]])
        share = round_half_up(dec(certified) / dec(len(enrolled)), 4)
    if provider["county_tier"] == "HIGH_NEED" or share >= SUBSIDY_SHARE_TIER_I_FLOOR:
        tier = "TIER_I"
    else:
        tier = "TIER_II"
    claimed = sum(meal_line_amount(line, tier) for line in meal_lines)
    return {
        "subsidy_enrollment_share": float(share),
        "tier_applied": tier,
        "claimed_amount_cents": claimed,
    }


# --- remittance allocation waterfall --------------------------------------

def allocation_candidates(contract_id):
    rows = [
        c for c in db.claims.values()
        if c["contract_id"] == contract_id
        and c["status"] == "RECONCILED"
        and c["paid_cents"] < c["final_amount_cents"]
    ]
    rows.sort(key=lambda c: (c["period_month"], c["_seq"]))
    return rows


# --- substitute selection --------------------------------------------------

def _overlaps(assignment, other):
    """(start - 30min) < other.end AND (end + 30min) > other.start."""
    start = clock.parse_instant(assignment["start_at"])
    end = clock.parse_instant(assignment["end_at"])
    other_start = clock.parse_instant(other["start_at"])
    other_end = clock.parse_instant(other["end_at"])
    buffer_delta = timedelta(minutes=BUFFER_MINUTES)
    return (start - buffer_delta) < other_end and (end + buffer_delta) > other_start


def has_interval_conflict(assignment, substitute_id):
    for other in db.assignments.values():
        if other["id"] == assignment["id"]:
            continue
        if other.get("substitute_id") != substitute_id:
            continue
        if other["staffing_status"] not in ("OFFERED", "CONFIRMED", "COMPLETED"):
            continue
        if _overlaps(assignment, other):
            return True
    return False


def clearance_ok(substitute, assignment):
    expiry = clock.parse_instant(substitute["clearance_expires_on"])
    end = clock.parse_instant(assignment["end_at"])
    return expiry is not None and expiry >= end


def eligible(substitute, assignment, provider, ignore_clearance=False, ignore_conflict=False):
    if substitute["pool_status"] != "AVAILABLE":
        return False
    if not ignore_clearance and not clearance_ok(substitute, assignment):
        return False
    if CREDENTIAL_RANK[substitute["credential_level"]] < CREDENTIAL_RANK[assignment["min_credential_level"]]:
        return False
    if provider["county_tier"] not in substitute["service_county_tiers"]:
        return False
    if substitute["id"] in assignment["declined_substitute_ids"]:
        return False
    if not ignore_conflict and has_interval_conflict(assignment, substitute["id"]):
        return False
    return True


def select_substitute(assignment, provider):
    """Deterministic single-row pick: cheapest, then fewest completed, then oldest."""
    candidates = [s for s in db.substitutes.values() if eligible(s, assignment, provider)]
    if not candidates:
        return None
    candidates.sort(key=lambda s: (s["hourly_rate_cents"], s["assignment_count_completed"], s["_seq"]))
    return candidates[0]


# --- provider revenue projection ------------------------------------------

def revenue_model(provider):
    provider_id = provider["id"]
    month = clock.clock_month()

    contracts = [
        c for c in db.contracts.values()
        if c["provider_id"] == provider_id and c["status"] in ("ACTIVE", "SUSPENDED_FOR_QUALITY")
    ]
    contracts.sort(key=lambda c: c["_seq"])
    contract = contracts[0] if contracts else None

    held_enrollment_ids = set()
    if contract is not None:
        for claim in db.claims.values():
            if (
                claim["contract_id"] == contract["id"]
                and claim["status"] == "HELD"
                and claim["period_month"] == month
            ):
                for line in claim["lines"]:
                    held_enrollment_ids.add(line.get("enrollment_id"))

    subsidy_enrollments = [
        e for e in db.enrollments.values()
        if e["provider_id"] == provider_id
        and e["status"] == "ENROLLED"
        and e["subsidy_certified"]
        and e["slot_committed"]
        and e["id"] not in held_enrollment_ids
    ]
    private_enrollments = [
        e for e in db.enrollments.values()
        if e["provider_id"] == provider_id
        and e["status"] == "ENROLLED"
        and not e["subsidy_certified"]
    ]

    daily_rate = contract["daily_rate_cents"] if contract is not None else 0
    subsidy_component = len(subsidy_enrollments) * daily_rate * AUTHORIZED_DAYS_PER_MONTH
    private_component = sum(e["private_monthly_tuition_cents"] for e in private_enrollments)

    approved = [
        f for f in db.food_claims.values()
        if f["provider_id"] == provider_id
        and f["status"] in ("APPROVED", "APPROVED_WITH_DISALLOWANCE")
    ]
    approved.sort(key=lambda f: (f["period_month"], f["_seq"]), reverse=True)
    food_component = approved[0]["reimbursed_amount_cents"] if approved else 0

    monthly_revenue = subsidy_component + private_component + food_component

    network_fee = cents(dec(monthly_revenue) * dec(provider["network_fee_pct"]) / dec(100))
    substitute_cost = 0
    for assignment in db.assignments.values():
        if assignment["provider_id"] != provider_id:
            continue
        if assignment["billing_status"] not in ("ACCRUED", "INVOICED"):
            continue
        if clock.month_of(assignment["start_at"]) != month:
            continue
        substitute_cost += assignment["total_cost_cents"]
    monthly_cost = provider["fixed_monthly_cost_cents"] + network_fee + substitute_cost

    if len(subsidy_enrollments) + len(private_enrollments) == 0:
        margin_pct = Decimal("0.0000")
        sustainability = "INSUFFICIENT_DATA"
        recommended = None
    else:
        if monthly_revenue == 0:
            margin_pct = Decimal("0.0000")
        else:
            margin_pct = round_half_up(
                (dec(monthly_revenue) - dec(monthly_cost)) / dec(monthly_revenue), 4
            )
        if monthly_revenue != 0 and margin_pct >= SUSTAINABLE_FLOOR:
            sustainability = "SUSTAINABLE"
        elif monthly_revenue != 0 and margin_pct >= THIN_FLOOR:
            sustainability = "THIN"
        else:
            sustainability = "AT_RISK"
        if not private_enrollments:
            recommended = None
        else:
            denominator = Decimal(1) - TARGET_MARGIN_PCT - dec(provider["network_fee_pct"]) / dec(100)
            needed_total = ceil_int(
                (dec(provider["fixed_monthly_cost_cents"]) + dec(substitute_cost)) / denominator
            )
            needed_private = max(0, needed_total - subsidy_component - food_component)
            per_child = dec(needed_private) / dec(len(private_enrollments))
            recommended = ceil_int(per_child / dec(TUITION_ROUNDING_CENTS)) * TUITION_ROUNDING_CENTS

    return {
        "monthly_revenue_cents": monthly_revenue,
        "subsidy_component_cents": subsidy_component,
        "private_component_cents": private_component,
        "food_component_cents": food_component,
        "monthly_cost_cents": monthly_cost,
        "network_fee_cents": network_fee,
        "substitute_cost_cents": substitute_cost,
        "margin_pct": float(margin_pct),
        "sustainability": sustainability,
        "recommended_private_tuition_cents": recommended,
    }
