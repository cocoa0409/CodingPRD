"""Every derived quantity in the domain (PRD 2.8 and section 3)."""

from decimal import Decimal, ROUND_HALF_UP

import clockutil

TWO = Decimal("0.01")
ZERO2 = Decimal("0.00")
HUNDRED = Decimal("100")

RISK_ESCALATION_THRESHOLD = 70
RISK_PROHIBITED_THRESHOLD = 90
SHOWING_OF_INTEREST_THRESHOLD_PCT = Decimal("30.00")
TRAINING_PASS_SCORE = 80
REQUIRED_TRAINING_MODULES = ("TIPS_BOUNDARIES", "PROHIBITED_CONDUCT", "SOLICITATION_RULES")
MAX_REVISION_ROUNDS = 3
MAX_LIST_RESUBMISSIONS = 2
MAX_BALLOT_REOPENS = 2
MAX_OBSERVERS_PER_PARTY = 3
VOTER_LIST_BUSINESS_DAYS = 2
OBJECTION_WINDOW_BUSINESS_DAYS = 7
CERTIFICATION_YEAR_DAYS = 365
ELECTION_BAR_DAYS = 365
PEERLESS_PLYWOOD_HOURS = 24
POLL_SESSION_TEARDOWN_MINUTES = 30
PRESENTER_TRAVEL_BUFFER_MINUTES = 60
CURE_HOURS_MINOR_DEFECT = 48
CURE_HOURS_MATERIAL_DEFECT = 24

MEETING_CHANNELS = ("SMALL_GROUP_MEETING", "CAPTIVE_AUDIENCE_MEETING")
CHANNEL_BASE_RISK = {
    "EMAIL": 5,
    "LETTER": 5,
    "DIGITAL_POST": 10,
    "SMALL_GROUP_MEETING": 20,
    "CAPTIVE_AUDIENCE_MEETING": 30,
}

TRADITIONAL_WEIGHTS = (
    ("supervision_overlap", Decimal("0.325")),
    ("skills_overlap", Decimal("0.225")),
    ("functional_integration", Decimal("0.175")),
    ("interchange_rate", Decimal("0.125")),
    ("work_conditions_overlap", Decimal("0.100")),
    ("wage_proximity", Decimal("0.050")),
)

BANDS = {
    "TRADITIONAL": (Decimal("65"), Decimal("45")),
    "OVERWHELMING": (Decimal("80"), Decimal("60")),
    "ACCRETION": (Decimal("60"), Decimal("40")),
}

GRADE_TIERS = ("COMPLIANT", "MINOR_DEFECT", "MATERIAL_DEFECT", "GROSSLY_DEFICIENT")


def round2(value):
    """Every rounding step in the system is round-half-up to two decimals."""
    return Decimal(value).quantize(TWO, rounding=ROUND_HALF_UP)


def as_number(value):
    """Render a two-decimal Decimal as a JSON number."""
    if value is None:
        return None
    return float(value)


# ------------------------------------------------------- core wage snapshot

def core_avg_hourly_wage_cents(classifications):
    """Headcount-weighted average over the undisputed core; None when no core group exists."""
    core = [c for c in classifications
            if c["employer_position"] == "INCLUDE" and c["union_position"] == "INCLUDE"]
    total_heads = sum(c["headcount"] for c in core)
    if not core or total_heads <= 0:
        return None
    products = sum(c["headcount"] * c["avg_hourly_wage_cents"] for c in core)
    return int(Decimal(products).__truediv__(Decimal(total_heads)).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP))


def wage_proximity(class_wage_cents, core_wage_cents):
    """100.00 minus the wage gap percentage, floored at 0.00."""
    gap = round2(Decimal(abs(class_wage_cents - core_wage_cents)) * HUNDRED
                 / Decimal(core_wage_cents))
    proximity = Decimal("100.00") - gap
    if proximity < ZERO2:
        return ZERO2
    return round2(proximity)


def coi_score(classification, proximity, standard):
    """Each weighted term is rounded to two decimals before the six terms are summed."""
    values = {
        "supervision_overlap": Decimal(classification["supervision_overlap"]),
        "skills_overlap": Decimal(classification["skills_overlap"]),
        "functional_integration": Decimal(classification["functional_integration"]),
        "interchange_rate": Decimal(classification["interchange_rate"]),
        "work_conditions_overlap": Decimal(classification["work_conditions_overlap"]),
        "wage_proximity": proximity,
    }
    weighted = sum((round2(values[name] * weight) for name, weight in TRADITIONAL_WEIGHTS),
                   Decimal("0"))
    if standard == "TRADITIONAL":
        return round2(weighted)
    if standard == "OVERWHELMING":
        smallest = min(values[name] for name, _ in TRADITIONAL_WEIGHTS)
        return round2(Decimal("0.5") * weighted + Decimal("0.5") * smallest)
    return round2(Decimal("0.40") * values["functional_integration"]
                  + Decimal("0.35") * values["interchange_rate"]
                  + Decimal("0.25") * values["supervision_overlap"])


def coi_recommendation(score, standard, supervisory_authority_count):
    """Band mapping, then the Section 2(11) statutory override."""
    shared, contested = BANDS[standard]
    if score >= shared:
        recommendation = "SHARED_COMMUNITY"
    elif score >= contested:
        recommendation = "CONTESTED_COMMUNITY"
    else:
        recommendation = "DISTINCT_COMMUNITY"
    if (supervisory_authority_count or 0) >= 1:
        return "MANDATORY_EXCLUSION"
    return recommendation


# ------------------------------------------------------ showing of interest

def valid_card_count(petition_counts):
    submitted, duplicate, undated, stale, nonunit = petition_counts
    return submitted - duplicate - undated - stale - nonunit


def showing_basis(classifications):
    """AS_RULED only when every classification carries a final INCLUDED/EXCLUDED ruling."""
    for c in classifications:
        if c["scope_ruling"] not in ("INCLUDED", "EXCLUDED"):
            return "AS_PETITIONED"
    return "AS_RULED"


def showing_pct(valid_cards, denominator):
    return round2(Decimal(valid_cards) * HUNDRED / Decimal(denominator))


def showing_verdict(pct):
    return "SUFFICIENT" if pct >= SHOWING_OF_INTEREST_THRESHOLD_PCT else "INSUFFICIENT"


# ----------------------------------------------------------- voter eligibility

def voter_eligibility(entry, classification, petition, agreement):
    """Six ordered rules; the first matching rule wins."""
    if classification is not None and classification["scope_ruling"] == "EXCLUDED":
        return "INELIGIBLE", "OUTSIDE_UNIT"
    hire_date = clockutil.parse_date(entry.get("hire_date"))
    payroll_end = clockutil.parse_date(petition.get("payroll_period_end")) if petition else None
    if hire_date is not None and payroll_end is not None and hire_date > payroll_end:
        return "INELIGIBLE", "HIRED_AFTER_PAYROLL_PERIOD"
    termination = clockutil.parse_date(entry.get("termination_date"))
    election_date = None
    if agreement is not None:
        election_date = clockutil.parse_date(agreement.get("approved_election_date"))
    if termination is not None and election_date is not None and termination < election_date:
        return "INELIGIBLE", "TERMINATED_BEFORE_ELECTION"
    if entry.get("on_leave_type") == "PERMANENT_LAYOFF":
        return "INELIGIBLE", "PERMANENT_LAYOFF"
    if classification is not None and classification["scope_ruling"] == "PENDING":
        return "CHALLENGED", None
    return "ELIGIBLE", None


STATUTORY_CONTENT_FIELDS = ("home_address", "personal_email", "personal_phone",
                            "shift_code", "work_location")


def statutory_content(entry):
    missing = 0
    for name in STATUTORY_CONTENT_FIELDS:
        value = entry.get(name)
        if value is None or (isinstance(value, str) and value.strip() == ""):
            missing += 1
    return missing, missing == 0


# ------------------------------------------------------------ list grading

def base_grade(pct):
    if pct >= Decimal("100.00"):
        return "COMPLIANT"
    if pct >= Decimal("90.00"):
        return "MINOR_DEFECT"
    if pct >= Decimal("75.00"):
        return "MATERIAL_DEFECT"
    return "GROSSLY_DEFICIENT"


def worsen(grade):
    index = GRADE_TIERS.index(grade)
    return GRADE_TIERS[min(index + 1, len(GRADE_TIERS) - 1)]


def completeness_pct(complete_entry_count, total_entry_count):
    if total_entry_count <= 0:
        return ZERO2
    return round2(Decimal(complete_entry_count) * HUNDRED / Decimal(total_entry_count))


def cure_hours_for(grade):
    if grade == "MINOR_DEFECT":
        return CURE_HOURS_MINOR_DEFECT
    if grade == "MATERIAL_DEFECT":
        return CURE_HOURS_MATERIAL_DEFECT
    return 0


# ----------------------------------------------------------------- campaign

def risk_score(message):
    """Additive base rate plus aggravators, clamped to 100 exactly once at the end."""
    total = CHANNEL_BASE_RISK.get(message["channel"], 0)
    total += 15 * (message.get("threat_statement_count") or 0)
    if message.get("contains_interrogation"):
        total += 12
    if message.get("contains_promise_of_benefit"):
        total += 10
    if message.get("contains_surveillance_reference"):
        total += 8
    unsupported = message.get("unsupported_material_claim_count") or 0
    if unsupported > 1:
        total += 6 * (unsupported - 1)
    if message.get("audience_scope") == "UNIT_WIDE":
        total += 5
    return min(total, 100)


def in_peerless_window(instant, polls_open_at):
    """Closed at the lower edge, open at the upper: [polls_open - 24h, polls_open)."""
    if instant is None or polls_open_at is None:
        return False
    lower = clockutil.add_hours(polls_open_at, -PEERLESS_PLYWOOD_HOURS)
    return lower <= instant < polls_open_at


def peerless_plywood_violation(message, polls_open_at):
    if message["channel"] != "CAPTIVE_AUDIENCE_MEETING":
        return False
    return in_peerless_window(clockutil.parse_dt(message.get("planned_delivery_at")),
                              polls_open_at)


def presenter_interval(message):
    """The presenter reservation, padded by a 60-minute travel buffer and closed at both ends."""
    start = clockutil.parse_dt(message["planned_delivery_at"])
    duration = message.get("duration_minutes") or 60
    lower = clockutil.add_minutes(start, -PRESENTER_TRAVEL_BUFFER_MINUTES)
    upper = clockutil.add_minutes(start, duration + PRESENTER_TRAVEL_BUFFER_MINUTES)
    return lower, upper


def closed_intervals_overlap(a, b):
    return a[0] <= b[1] and b[0] <= a[1]


def session_occupancy(session):
    """Location occupancy runs from session_start_at up to but not including close + 30 minutes."""
    start = clockutil.parse_dt(session["session_start_at"])
    end = clockutil.add_minutes(clockutil.parse_dt(session["session_end_at"]),
                                POLL_SESSION_TEARDOWN_MINUTES)
    return start, end


def half_open_overlap(a, b):
    return a[0] < b[1] and b[0] < a[1]


# -------------------------------------------------------------------- tally

def majority_threshold(valid_votes_cast):
    """Halve, discard the fraction, add one."""
    return (valid_votes_cast // 2) + 1
