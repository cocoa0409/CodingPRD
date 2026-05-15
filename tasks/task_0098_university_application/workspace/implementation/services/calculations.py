"""Pure-function calculation rules.

All money is integer cents.
All scores use Decimal with ROUND_HALF_UP at two decimal places.
"""
from __future__ import annotations  # noqa

import re
from decimal import ROUND_HALF_UP, Decimal

# Quantizers
TWO = Decimal("0.01")
ZERO = Decimal("0")
ONE = Decimal("1")

# Financial aid constants
FEDERAL_LOAN_CAP_CENTS = 550000
FEDERAL_WS_CAP_CENTS = 250000
INSTITUTIONAL_GRANT_PCT = Decimal("0.70")
INSTITUTIONAL_LOAN_CAP_CENTS = 350000

# Essay customization constants
DRAFT_LENGTH_DIVISOR = Decimal("500.0")
FINAL_LENGTH_DIVISOR = Decimal("650.0")
MIN_SUBMIT_SCORE = Decimal("0.30")

# Waitlist rank constants
GPA_WEIGHT = Decimal("40.00")
ESSAY_WEIGHT = Decimal("30.00")
TENURE_DAY_VALUE = Decimal("0.50")
TENURE_DAY_CAP = 30
INTEREST_PER_PROGRAM = Decimal("5.00")
INTEREST_PROGRAM_CAP = 3

# Yield management
MELT_RATE_CONSTANT = Decimal("0.15")
MAX_BATCH_PER_SWEEP = 50


def round_half_up_dec(value: Decimal, places: int = 2) -> Decimal:
    quant = Decimal("1").scaleb(-places)
    return value.quantize(quant, rounding=ROUND_HALF_UP)


def round_half_up_int(value: Decimal) -> int:
    return int(value.to_integral_value(rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Financial aid
# ---------------------------------------------------------------------------
def compute_financial_aid(aid_method: str, cost_of_attendance_cents: int, applicant: dict) -> dict:
    """Return dict with grant_cents, loan_cents, work_study_cents, total_award_cents."""
    coa = int(cost_of_attendance_cents)

    if aid_method == "FEDERAL_METHODOLOGY":
        efc = int(applicant.get("fafsa_efc_cents") or 0)
        need = max(0, coa - efc)
        loan = min(need, FEDERAL_LOAN_CAP_CENTS)
        ws_input = max(0, need - loan)
        work_study = min(ws_input, FEDERAL_WS_CAP_CENTS)
        grant = max(0, need - loan - work_study)
    elif aid_method == "INSTITUTIONAL_METHODOLOGY":
        efc = int(applicant.get("css_profile_efc_cents") or 0)
        need = max(0, coa - efc)
        # grant_pct of need, round half-up to cents
        grant_dec = Decimal(need) * INSTITUTIONAL_GRANT_PCT
        grant = int(grant_dec.to_integral_value(rounding=ROUND_HALF_UP))
        loan_input = max(0, need - grant)
        loan = min(loan_input, INSTITUTIONAL_LOAN_CAP_CENTS)
        work_study = max(0, need - grant - loan)
    else:
        raise ValueError(f"unknown aid_method: {aid_method}")

    total = grant + loan + work_study
    return {
        "grant_cents": grant,
        "loan_cents": loan,
        "work_study_cents": work_study,
        "total_award_cents": total,
    }


# ---------------------------------------------------------------------------
# Essay customization score
# ---------------------------------------------------------------------------
def whitespace_tokens(text: str) -> list[str]:
    if not text:
        return []
    return text.split()


def _whole_word_count(haystack: str, needle: str) -> int:
    if not haystack or not needle:
        return 0
    # Case-insensitive whole-word matches. Use \b boundary around an escaped needle.
    pattern = r"\b" + re.escape(needle) + r"\b"
    return len(re.findall(pattern, haystack, flags=re.IGNORECASE))


def _university_prefix_code(university_id: str) -> str:
    """Derive an id-prefix for prompt_code matching. We adopt the first 8 chars of the UUID."""
    return (university_id or "")[:8]


def _prompt_match(prompt_code: str, university_id: str) -> Decimal:
    if not prompt_code:
        return ZERO
    prefix = _university_prefix_code(university_id)
    if not prefix:
        return ZERO
    return ONE if prompt_code.lower().startswith(prefix.lower()) else ZERO


def compute_customization_score(
    body: str,
    prompt_code: str,
    university_name: str,
    program_name: str,
    university_id: str,
    variant: str,  # "draft" | "final"
) -> Decimal:
    tokens = whitespace_tokens(body)
    token_count = Decimal(len(tokens))
    mentions_uni = Decimal(_whole_word_count(body, university_name))
    mentions_prog = Decimal(_whole_word_count(body, program_name))
    prompt_match = _prompt_match(prompt_code, university_id)

    if variant == "draft":
        divisor = DRAFT_LENGTH_DIVISOR
        w_len = Decimal("0.40")
        w_uni = Decimal("0.20")
        w_prog = Decimal("0.20")
        w_prompt = Decimal("0.20")
    else:  # final
        divisor = FINAL_LENGTH_DIVISOR
        w_len = Decimal("0.35")
        w_uni = Decimal("0.175")
        w_prog = Decimal("0.175")
        w_prompt = Decimal("0.30")

    length_factor = min(ONE, token_count / divisor) if divisor != 0 else ZERO
    uni_factor = min(ONE, mentions_uni / Decimal("2.0"))
    prog_factor = min(ONE, mentions_prog / Decimal("2.0"))

    raw = (
        w_len * length_factor
        + w_uni * uni_factor
        + w_prog * prog_factor
        + w_prompt * prompt_match
    )
    return round_half_up_dec(raw, 2)


# ---------------------------------------------------------------------------
# Waitlist rank score — per-component round, then sum, then final round.
# ---------------------------------------------------------------------------
def compute_rank_score(
    high_school_gpa: Decimal | float | str,
    customization_score: Decimal | float | str,
    days_on_waitlist: int,
    demonstrated_interest: int,
) -> Decimal:
    gpa = Decimal(str(high_school_gpa))
    cs = Decimal(str(customization_score))
    days = Decimal(min(int(days_on_waitlist), TENURE_DAY_CAP))
    interest = Decimal(min(int(demonstrated_interest), INTEREST_PROGRAM_CAP))

    gpa_component = round_half_up_dec((gpa / Decimal("4.00")) * GPA_WEIGHT, 2)
    essay_component = round_half_up_dec(cs * ESSAY_WEIGHT, 2)
    tenure_component = round_half_up_dec(days * TENURE_DAY_VALUE, 2)
    interest_component = round_half_up_dec(interest * INTEREST_PER_PROGRAM, 2)

    total = gpa_component + essay_component + tenure_component + interest_component
    return round_half_up_dec(total, 2)


# ---------------------------------------------------------------------------
# Yield batch sizing
# ---------------------------------------------------------------------------
def compute_yield_batch_size(target: int, enrolled: int, admitted_open: int) -> int:
    gap = max(0, int(target) - int(enrolled))
    expected_melt = round_half_up_int(Decimal(int(admitted_open)) * MELT_RATE_CONSTANT)
    raw_batch = max(0, gap - expected_melt)
    capacity_cap = int(admitted_open)
    return min(raw_batch, capacity_cap, MAX_BATCH_PER_SWEEP)
