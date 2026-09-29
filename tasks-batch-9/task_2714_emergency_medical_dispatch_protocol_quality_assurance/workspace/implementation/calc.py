"""Calculation rules (PRD 2.6, 2.10, 3.5, 3.6, 3.7, 3.8, 3.9).

Every rounding in the system is round-half-up at a fixed number of decimal
places, and the order in which rounding is applied is part of the contract.
"""
import re
from decimal import Decimal, ROUND_HALF_UP

DETERMINANT_RE = re.compile(r"^[0-9]{1,2}-[OABCDE]-[0-9]{1,2}$")

PRIORITY_RANK = {"O": 1, "A": 2, "B": 3, "C": 4, "D": 5, "E": 6}
HOT_LEVELS = ("D", "E")
ALS_LEVELS = ("C", "D", "E")

D0 = Decimal("0")
ONE = Decimal("1")
HUNDRED = Decimal("100")

PENALTY_BASE = {
    "ACCURATE": Decimal("0.0"),
    "MINOR_MISCODE": Decimal("2.0"),
    "OVER_TRIAGE": Decimal("5.0"),
    "UNDER_TRIAGE": Decimal("10.0"),
}
TIER_MULTIPLIER = {"HIGH": Decimal("1.5"), "MID": Decimal("1.0"), "LOW": Decimal("0.5")}
HIGH_TIER_FLOOR = Decimal("90.0")
MID_TIER_FLOOR = Decimal("75.0")
SCORE_FLOOR = Decimal("0.0")

RECOGNITION_LIMIT_SEC = Decimal("90")
COMPRESSION_LIMIT_SEC = Decimal("120")
COMPRESSION_FLOOR_SEC = Decimal("30")
SOLO_WEIGHTS = (Decimal("40"), Decimal("45"), Decimal("15"))
BYSTANDER_WEIGHTS = (Decimal("55"), Decimal("30"), Decimal("15"))
INSTRUCTION_DELIVERED_POINTS = Decimal("60.0")
COMPRESSION_COACHED_POINTS = Decimal("40.0")
LATE_COMPRESSION_CAP = Decimal("50.0")
HIGH_RISK_PASS_INDEX = Decimal("75.0")
SENTINEL_INDEX_FLOOR = Decimal("50.0")

SEVERITY_RANK = {"ADVISORY": 1, "STANDARD": 2, "CRITICAL": 3}
REQUIRED_HOURS = {
    "ADVISORY": Decimal("2.0"),
    "STANDARD": Decimal("4.0"),
    "CRITICAL": Decimal("8.0"),
}
AUTO_PLAN_DUE_DAYS = 30

SECTIONS = ("case_entry", "key_questions", "pre_arrival", "final_coding")
SECTION_FOCUS = {
    "case_entry": "CASE_ENTRY",
    "key_questions": "KEY_QUESTIONS",
    "pre_arrival": "PRE_ARRIVAL_INSTRUCTIONS",
    "final_coding": "FINAL_CODING",
}


def q(value, places):
    """Round half up to a fixed number of decimal places."""
    if value is None:
        return None
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return value.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)


def q1(value):
    return q(value, 1)


def q2(value):
    return q(value, 2)


def q4(value):
    return q(value, 4)


def valid_determinant_code(code):
    return isinstance(code, str) and DETERMINANT_RE.match(code) is not None


def decode_determinant(code):
    """PRD 2.10 — the middle level letter carries all dispatch semantics."""
    level = code.split("-")[1]
    return {
        "priority_rank": PRIORITY_RANK[level],
        "response_mode": "HOT" if level in HOT_LEVELS else "COLD",
        "resource": "ALS" if level in ALS_LEVELS else "BLS",
        "level": level,
    }


def determinant_level(code):
    return code.split("-")[1]


def classify_determinant_accuracy(dispatched_code, reviewer_code):
    """PRD 3.5 — the four accuracy classes, decided in the declared order."""
    d = decode_determinant(dispatched_code)
    r = decode_determinant(reviewer_code)
    response_mode_deviation = r["response_mode"] != d["response_mode"]
    resource_deviation = r["resource"] != d["resource"]
    if reviewer_code == dispatched_code:
        accuracy = "ACCURATE"
    elif not response_mode_deviation and not resource_deviation:
        accuracy = "MINOR_MISCODE"
    elif r["priority_rank"] > d["priority_rank"]:
        accuracy = "UNDER_TRIAGE"
    else:
        accuracy = "OVER_TRIAGE"
    return {
        "reviewer_priority_rank": r["priority_rank"],
        "reviewer_response_mode": r["response_mode"],
        "reviewer_resource": r["resource"],
        "response_mode_deviation": response_mode_deviation,
        "resource_deviation": resource_deviation,
        "determinant_accuracy": accuracy,
    }


def section_percentage(earned, possible):
    """PRD 3.5 — 2 dp; an inapplicable section (possible == 0) scores 100.00."""
    if possible == 0:
        return q2(HUNDRED)
    return q2(HUNDRED * Decimal(earned) / Decimal(possible))


def provisional_composite(pcts):
    """Unweighted mean of the four already-rounded section percentages, 1 dp."""
    total = pcts["case_entry_pct"] + pcts["key_questions_pct"] + pcts["pre_arrival_pct"] + pcts["final_coding_pct"]
    return q1(total / Decimal(4))


def weighted_composite(sheet, version):
    """Accreditation-weighted composite from the pinned version's weights, 1 dp."""
    total = (
        sheet["case_entry_pct"] * version["case_entry_weight"]
        + sheet["key_questions_pct"] * version["key_questions_weight"]
        + sheet["pre_arrival_pct"] * version["pre_arrival_weight"]
        + sheet["final_coding_pct"] * version["final_coding_weight"]
    )
    return q1(total)


def determinant_penalty(pre_penalty, accuracy):
    """PRD 3.7 — the tier is chosen from the pre-penalty score, never after."""
    base = PENALTY_BASE[accuracy]
    if pre_penalty >= HIGH_TIER_FLOOR:
        tier = "HIGH"
    elif pre_penalty >= MID_TIER_FLOOR:
        tier = "MID"
    else:
        tier = "LOW"
    penalty = q1(base * TIER_MULTIPLIER[tier])
    final = q1(max(SCORE_FLOOR, pre_penalty - penalty))
    return penalty, final


def dacpr_index(observations, bystander_cpr_in_progress):
    """PRD 3.6 — weighted resuscitation performance index on a 0..100 scale."""
    if not observations["cardiac_arrest_recognized"]:
        return {
            "compression_compliant": False,
            "dacpr_index": q1(Decimal("0.0")),
            "dacpr_pass": False,
        }
    recognition_time = Decimal(observations["recognition_time_sec"])
    compression_time = Decimal(observations["time_to_first_compression_sec"])

    recognition_sub = (
        HUNDRED * max(D0, RECOGNITION_LIMIT_SEC - recognition_time) / RECOGNITION_LIMIT_SEC
    )
    compression_compliant = compression_time <= COMPRESSION_LIMIT_SEC
    span = COMPRESSION_LIMIT_SEC - COMPRESSION_FLOOR_SEC
    remaining = min(span, max(D0, COMPRESSION_LIMIT_SEC - compression_time))
    compression_sub = HUNDRED * remaining / span

    instruction_sub = D0
    if observations["dacpr_instructions_delivered"]:
        instruction_sub += INSTRUCTION_DELIVERED_POINTS
    if observations["compressions_coached"]:
        instruction_sub += COMPRESSION_COACHED_POINTS

    weights = BYSTANDER_WEIGHTS if bystander_cpr_in_progress else SOLO_WEIGHTS
    raw = (
        recognition_sub * weights[0]
        + compression_sub * weights[1]
        + instruction_sub * weights[2]
    ) / HUNDRED
    index = q1(raw)
    if not compression_compliant:
        index = min(index, LATE_COMPRESSION_CAP)
    return {
        "compression_compliant": bool(compression_compliant),
        "dacpr_index": index,
        "dacpr_pass": bool(index >= HIGH_RISK_PASS_INDEX),
    }


def weakest_section_focus(sheet):
    """PRD 3.8 — lowest section percentage, ties broken by the fixed order."""
    best_key = None
    best_value = None
    for section in SECTIONS:
        value = sheet[section + "_pct"]
        if best_value is None or value < best_value:
            best_value = value
            best_key = section
    return SECTION_FOCUS[best_key]


def posture_for(compliance_pct, program):
    if compliance_pct is None:
        return "UNRATED"
    if compliance_pct >= program["target_compliance_pct"]:
        return "GOOD"
    if compliance_pct >= program["watch_floor_pct"]:
        return "WATCH"
    return "PROBATION"


def systematic_indices(pool_size, requested_count, wanted):
    """PRD 3.4 — deterministic systematic stride, then head top-up."""
    stride = max(1, pool_size // requested_count)
    indices = []
    position = 0
    while position < pool_size:
        indices.append(position)
        position += stride
    chosen = indices[:wanted]
    if len(chosen) < wanted:
        taken = set(chosen)
        for index in range(pool_size):
            if len(chosen) >= wanted:
                break
            if index not in taken:
                chosen.append(index)
                taken.add(index)
    return sorted(chosen)
