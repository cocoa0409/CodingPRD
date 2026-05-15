"""Calculation rules — SCAFFOLD §1.3 / PRD §3.4, §3.5, §3.7."""
import hashlib
import math
from decimal import Decimal, ROUND_HALF_UP


# Constants
OFFER_RESPONSE_HOURS = 168          # 7 days
WITHDRAW_GRACE_DAYS = 14
MAX_CHOICES_PER_STUDENT = 5
POVERTY_BOOST_PER_DECILE = Decimal("0.10")
CHOICE_RANK_DECAY = Decimal("0.85")


PRIORITY_BASE_WEIGHT = {
    "SIBLING_IN_DISTRICT": Decimal("4.0"),
    "IN_DISTRICT_DISADVANTAGED": Decimal("3.0"),
    "IN_DISTRICT_STANDARD": Decimal("2.0"),
    "INTER_DISTRICT_DISADVANTAGED": Decimal("1.5"),
    "INTER_DISTRICT_STANDARD": Decimal("1.0"),
}


PRIORITY_RANK = {
    "SIBLING_IN_DISTRICT": 1,
    "IN_DISTRICT_DISADVANTAGED": 2,
    "IN_DISTRICT_STANDARD": 3,
    "INTER_DISTRICT_DISADVANTAGED": 4,
    "INTER_DISTRICT_STANDARD": 5,
}


def _round_half_up(value: Decimal, places: int) -> Decimal:
    quant = Decimal(1).scaleb(-places)  # 10^-places
    return value.quantize(quant, rounding=ROUND_HALF_UP)


def classify_priority_category(family: dict, program: dict, school: dict, district: dict,
                               anchor_district_id) -> str:
    """priority_category_classifier — SCAFFOLD §1.3."""
    crosses_district = school["district_id"] != family["residency_district_id"]
    family_score = Decimal(str(family["poverty_index_score"]))
    threshold = Decimal(str(district["poverty_index_threshold"]))
    is_disadvantaged = family_score >= threshold
    has_sibling_anchor = (
        family.get("head_household_application_id") is not None
        and anchor_district_id is not None
        and anchor_district_id == school["district_id"]
    )
    if has_sibling_anchor and not crosses_district:
        return "SIBLING_IN_DISTRICT"
    if not crosses_district and is_disadvantaged:
        return "IN_DISTRICT_DISADVANTAGED"
    if not crosses_district:
        return "IN_DISTRICT_STANDARD"
    if crosses_district and is_disadvantaged:
        return "INTER_DISTRICT_DISADVANTAGED"
    return "INTER_DISTRICT_STANDARD"


def compute_lottery_weight(priority_category: str, family: dict, district: dict,
                           choice_rank: int) -> float:
    """lottery_weight — SCAFFOLD §1.3.

    Implements the integer-scaled poverty multiplier, the choice-rank decay,
    and ROUND_HALF_UP to 4 decimal places.
    """
    base = PRIORITY_BASE_WEIGHT[priority_category]

    poverty_score = Decimal(str(family["poverty_index_score"]))
    threshold = Decimal(str(district["poverty_index_threshold"]))

    pi_int = int((poverty_score * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    thr_int = int((threshold * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))

    if pi_int > thr_int:
        deciles = (pi_int - thr_int) // 10
        multiplier = Decimal("1.0") + POVERTY_BOOST_PER_DECILE * Decimal(deciles)
    else:
        multiplier = Decimal("1.0")

    decay = CHOICE_RANK_DECAY ** (int(choice_rank) - 1)
    raw = base * multiplier * decay
    rounded = _round_half_up(raw, 4)
    # Return as float for JSON; Decimal serialization isn't standard JSON.
    return float(rounded)


def deterministic_uniform(seed: str, application_id: str) -> float:
    """Deterministic uniform draw in (0, 1] from SHA-256 of `seed:application_id`.

    Re-draw if exact 0 — extends the input until a non-zero value is produced.
    """
    salt = ""
    while True:
        material = f"{seed}:{application_id}{salt}"
        digest = hashlib.sha256(material.encode("utf-8")).digest()
        first8 = int.from_bytes(digest[:8], "big", signed=False)
        # uniform in [0, 1). Convert to (0, 1] semantics required by spec.
        u = first8 / (2 ** 64)
        if u > 0:
            return u
        # Vanishingly unlikely; salt and redraw to satisfy the (0, 1] constraint.
        salt += "_redraw"


def compute_lottery_score(lottery_weight: float, seed: str, application_id: str) -> float:
    """lottery_score = round(lottery_weight * -ln(rng_a), 6) with ROUND_HALF_UP."""
    u = deterministic_uniform(seed, application_id)
    raw = Decimal(str(lottery_weight)) * Decimal(str(-math.log(u)))
    return float(_round_half_up(raw, 6))
