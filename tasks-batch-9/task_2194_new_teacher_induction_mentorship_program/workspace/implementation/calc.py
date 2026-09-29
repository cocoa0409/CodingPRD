"""Deterministic calculations (PRD 2.10, 2.11, 3.4, 3.6, 3.7, 3.8, 3.9)."""

from datetime import timedelta
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP

# ------------------------------------------------------------------ enumerations

SUBJECTS = ("MATH", "SCIENCE", "ELA", "SOCIAL_STUDIES", "SPED", "WORLD_LANGUAGE", "CTE")
REGIONS = ("NORTH", "SOUTH", "EAST", "WEST")
CONTACT_TYPES = ("ONE_ON_ONE", "CO_PLANNING", "MODEL_LESSON", "DEBRIEF")
GROWTH_CODES = ("PLANNING", "INSTRUCTION", "ENVIRONMENT", "ASSESSMENT", "EQUITY")
RUBRIC_KEYS = ("planning", "instruction", "environment", "assessment")
LICENSE_STAGES = ("PRELIMINARY", "PROVISIONAL", "CLEAR")
TRAINING_MODULES = ("FOUNDATIONS", "OBSERVATION_PROTOCOL", "EQUITY", "RECERT_REFRESH")
ATTENDANCE_STATUSES = ("PRESENT", "LATE", "ABSENT", "EXCUSED")
RETENTION_OUTCOMES = ("RETAINED_SAME_SITE", "RETAINED_DISTRICT", "LEFT_DISTRICT",
                      "LEFT_PROFESSION", "UNKNOWN")

CONTACT_WEIGHTS = {
    "ONE_ON_ONE": Decimal("1.0"),
    "CO_PLANNING": Decimal("1.0"),
    "MODEL_LESSON": Decimal("1.25"),
    "DEBRIEF": Decimal("0.75"),
}

TIER_RATES = {"EXACT": 4200, "ADJACENT": 3600, "CROSS": 2800}

DAILY_CREDIT_CAP = 180
LATE_PENALTY_MINUTES = 10
SEMINAR_CREDIT_THRESHOLD = Decimal("0.75")
READINESS_GATE = Decimal("85.00")
CONTACT_TARGET_MINUTES = Decimal("600")
OBSERVATION_TARGET_CYCLES = Decimal("2")
MILESTONE_EVIDENCE_TARGET = Decimal("3")
INITIAL_TRAINING_HOURS = Decimal("18.00")
RECERT_TRAINING_HOURS = Decimal("6.00")
INITIAL_MODULES = ("FOUNDATIONS", "OBSERVATION_PROTOCOL", "EQUITY")
RECERT_MODULES = ("RECERT_REFRESH",)
CERTIFICATION_TERM_DAYS = 365
OBSERVATION_BUFFER_MINUTES = 30
WEEKLY_SEMINAR_CAP_MINUTES = 240
WINDOW_MIN_MINUTES = 30
WINDOW_MAX_MINUTES = 240

ADJACENCY = {
    "MATH": ("SCIENCE", "CTE"),
    "SCIENCE": ("MATH", "CTE"),
    "ELA": ("SOCIAL_STUDIES", "WORLD_LANGUAGE"),
    "SOCIAL_STUDIES": ("ELA", "WORLD_LANGUAGE"),
    "SPED": ("ELA", "MATH"),
    "WORLD_LANGUAGE": ("ELA", "SOCIAL_STUDIES"),
    "CTE": ("MATH", "SCIENCE"),
}


# ------------------------------------------------------------------- rounding

def d(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def round_half_up(value, places):
    quant = Decimal(1).scaleb(-places) if places > 0 else Decimal(1)
    return d(value).quantize(quant, rounding=ROUND_HALF_UP)


def as_float(value, places):
    return float(round_half_up(value, places))


def truncate_int(value):
    return int(d(value).quantize(Decimal(1), rounding=ROUND_DOWN))


# ------------------------------------------------------- subject affinity (3.3)

def subject_tier(novice_subject, endorsements):
    endorsements = endorsements or []
    if novice_subject in endorsements:
        return "EXACT"
    for endorsement in endorsements:
        if novice_subject in ADJACENCY.get(endorsement, ()):
            return "ADJACENT"
    return "CROSS"


def tier_rank(tier):
    return {"EXACT": 0, "ADJACENT": 1, "CROSS": 2}[tier]


# ------------------------------------------------- credited contact minutes (3.4)

def weighted_minutes(minutes, contact_type):
    weight = CONTACT_WEIGHTS.get(contact_type, Decimal("1.0"))
    return truncate_int(d(minutes) * weight)


def day_room(already_credited):
    return max(0, DAILY_CREDIT_CAP - int(already_credited))


def credited_minutes(minutes, contact_type, already_credited):
    return min(weighted_minutes(minutes, contact_type), day_room(already_credited))


# ------------------------------------------------------------- stipends (3.8)

def stipend_cents(minutes_credited, tier, multiplier):
    rate = TIER_RATES.get(tier, 0)
    amount = (d(minutes_credited) / Decimal(60)) * Decimal(rate) * d(multiplier)
    return int(round_half_up(amount, 0))


# -------------------------------------------------------- readiness index (3.7)

def readiness_components(contact_minutes, documented_cycles, credited_seminars,
                         held_sessions, excused_sessions):
    denominator = max(1, int(held_sessions) - int(excused_sessions))
    contact = min(Decimal(1), d(contact_minutes) / CONTACT_TARGET_MINUTES)
    observation = min(Decimal(1), d(documented_cycles) / OBSERVATION_TARGET_CYCLES)
    seminar = min(Decimal(1), d(credited_seminars) / Decimal(denominator))
    index = round_half_up(
        Decimal(100) * (Decimal("0.45") * contact + Decimal("0.30") * observation
                        + Decimal("0.25") * seminar),
        2,
    )
    return {
        "contact_component": contact,
        "observation_component": observation,
        "seminar_component": seminar,
        "seminar_denominator": denominator,
        "held_sessions": int(held_sessions),
        "excused_sessions": int(excused_sessions),
        "index": index,
    }


# ------------------------------------------------------ seminar attendance (3.6)

def attendance_credit(attendance_status, minutes_attended, scheduled_minutes):
    penalty = LATE_PENALTY_MINUTES if attendance_status == "LATE" else 0
    effective = max(0, int(minutes_attended) - penalty)
    if not scheduled_minutes:
        ratio = Decimal("0.0000")
    else:
        ratio = round_half_up(d(effective) / d(scheduled_minutes), 4)
    credited = attendance_status in ("PRESENT", "LATE") and ratio >= SEMINAR_CREDIT_THRESHOLD
    return ratio, credited


# ------------------------------------------------------- completion score (3.9)

def completion_scores(readiness_live, attained_count, retention_outcome):
    milestone_component = min(Decimal(1), d(attained_count) / MILESTONE_EVIDENCE_TARGET)
    base = round_half_up(
        Decimal("0.60") * d(readiness_live)
        + Decimal("0.40") * Decimal(100) * milestone_component,
        2,
    )
    if base >= Decimal("90.00") and retention_outcome == "RETAINED_SAME_SITE":
        bonus = Decimal("5.00")
    elif base >= Decimal("75.00") and retention_outcome in ("RETAINED_SAME_SITE",
                                                            "RETAINED_DISTRICT"):
        bonus = Decimal("2.50")
    else:
        bonus = Decimal("0.00")
    completion = min(Decimal("100.00"), round_half_up(base + bonus, 2))
    return base, bonus, completion


# ------------------------------------------------------------- windows (2.11)

def duration_minutes(start, end):
    return int((end - start).total_seconds() // 60)


def window_ok(start, end, minimum=WINDOW_MIN_MINUTES, maximum=WINDOW_MAX_MINUTES):
    if end <= start:
        return False
    minutes = duration_minutes(start, end)
    if minimum is not None and minutes < minimum:
        return False
    if maximum is not None and minutes > maximum:
        return False
    return True


def observation_conflict(new_start, new_end, other_start, other_end):
    buffer_delta = timedelta(minutes=OBSERVATION_BUFFER_MINUTES)
    return new_start <= other_end + buffer_delta and other_start <= new_end + buffer_delta


def seminar_overlap(new_start, new_end, other_start, other_end):
    return new_start < other_end and other_start < new_end


def iso_week_bounds(moment):
    start_of_day = moment.replace(hour=0, minute=0, second=0, microsecond=0)
    monday = start_of_day - timedelta(days=start_of_day.weekday())
    return monday, monday + timedelta(days=7)
