"""Probabilistic and deterministic identity match scoring (PRD 3.3)."""
from decimal import Decimal

from services.precision import ZERO, ONE, dec, rhu4

SCORE_FIELDS = (
    "family_name",
    "given_name",
    "birth_date",
    "ssn_last4",
    "postal_code",
    "phone_digits",
)

# Only these four admit partial credit; birth_date and ssn_last4 are exact-only.
FUZZY_FIELDS = ("family_name", "given_name", "postal_code", "phone_digits")

DIGIT_FIELDS = ("ssn_last4", "phone_digits")

BIRTH_DATE_VETO_CAP = Decimal("0.6000")
STRONG_IDENTIFIER_FLOOR = Decimal("0.8000")

DETERMINISTIC = "DETERMINISTIC"
PROBABILISTIC = "PROBABILISTIC"


def normalize(field, value):
    if value is None:
        return None
    text = value if isinstance(value, str) else str(value)
    if field in DIGIT_FIELDS:
        return "".join(ch for ch in text if ch.isdigit())
    return text.strip().lower()


def field_agreement(field, left_value, right_value, partial_credit_factor):
    left = normalize(field, left_value)
    right = normalize(field, right_value)
    if left is None or right is None:
        return ZERO
    if left == right:
        return ONE
    if field in FUZZY_FIELDS and left[:3] == right[:3]:
        return partial_credit_factor
    return ZERO


def agreement_map(config, left, right):
    pcf = dec(config["partial_credit_factor"])
    return {
        field: field_agreement(field, left.get(field), right.get(field), pcf)
        for field in SCORE_FIELDS
    }


def probabilistic_score(config, agreements):
    raw = ZERO
    for field in SCORE_FIELDS:
        raw = raw + dec(config["weight_" + field]) * agreements[field]
    score = rhu4(raw)
    # Order matters: the birth-date veto cap applies before the strong floor.
    if agreements["birth_date"] == ZERO:
        if score > BIRTH_DATE_VETO_CAP:
            score = BIRTH_DATE_VETO_CAP
    if agreements["ssn_last4"] == ONE and agreements["family_name"] == ONE:
        if score < STRONG_IDENTIFIER_FLOOR:
            score = STRONG_IDENTIFIER_FLOOR
    return rhu4(score)


def deterministic_score(agreements):
    ssn_and_dob = agreements["ssn_last4"] == ONE and agreements["birth_date"] == ONE
    quad = (
        agreements["family_name"] == ONE
        and agreements["given_name"] == ONE
        and agreements["birth_date"] == ONE
        and agreements["postal_code"] == ONE
    )
    return Decimal("1.0000") if (ssn_and_dob or quad) else Decimal("0.0000")


def score_pair(config, left, right):
    """Returns (score Decimal, score_variant, agreement map of Decimals)."""
    agreements = agreement_map(config, left, right)
    if config["score_variant_mode"] == "DETERMINISTIC_FIRST":
        return deterministic_score(agreements), DETERMINISTIC, agreements
    return probabilistic_score(config, agreements), PROBABILISTIC, agreements


def agreement_output(agreements):
    from services.precision import out

    return {field: out(rhu4(agreements[field])) for field in SCORE_FIELDS}
