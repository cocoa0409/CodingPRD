"""Calculation rules — SCAFFOLD §1.3 + PRD §2.7-§2.9, §3.11.

Includes:
  * priority_date_currency      — Visa Bulletin lookup → priority_date_status
  * rfe_response_deadline       — RFE.deadline_at and Case.rfe_deadline
  * mint_receipt_number         — 13-character USCIS-style receipt number
  * case_completeness_score     — 0..100 weighted score (live + snapshot)
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from db import store
from utils import (
    day_of_fiscal_year,
    fiscal_year_start,
    parse_iso_date,
    round_half_up,
)


# ────────────────────────────────────────────────────────────────────────────
# priority_date_currency (PRD §2.9; SCAFFOLD calculations.priority_date_currency)
# ────────────────────────────────────────────────────────────────────────────


def _latest_bulletin_month() -> str | None:
    """Latest bulletin_month across all rows (lexical max on YYYY-MM)."""
    months = {row["bulletin_month"] for row in store.visa_bulletins.values()}
    return max(months) if months else None


def _select_bulletin_row(chart_type: str, month: str, category: str, country: str):
    """Return the best-matching VisaBulletin row.

    Selection (PRD §2.9):
      - chart_type matches
      - bulletin_month matches the supplied month
      - preference_category matches
      - country is either the beneficiary's country_of_chargeability or 'ROW'
      - country-specific row wins over ROW row when both exist
      - among multiple matching rows (theoretically duplicates), pick the one
        with the latest published_at.
    """
    matches = []
    for row in store.visa_bulletins.values():
        if row["chart_type"] != chart_type:
            continue
        if row["bulletin_month"] != month:
            continue
        if row["preference_category"] != category:
            continue
        if row["country"] != country and row["country"] != "ROW":
            continue
        matches.append(row)
    if not matches:
        return None
    # Sort: country-specific rows first (False sorts before True, so use a
    # custom key that puts the country-specific row first).
    matches.sort(
        key=lambda r: (0 if r["country"] == country else 1, -r["published_at"].timestamp()),
    )
    return matches[0]


def compute_priority_date_status(case: dict) -> str:
    """Compute the case's priority_date_status against the latest VisaBulletin.

    The function reads the configured `chart_in_effect`, picks the latest
    published bulletin month, then selects the row matching the beneficiary's
    (preference_category, country_of_chargeability) with ROW fallback. It does
    NOT do retrogression detection — callers should compare against the prior
    stored value and substitute RETROGRESSED when applicable.

    A case for which priority-date currency does not apply (case_type in
    {I-130, I-765, I-131}, or beneficiary.preference_category == IR) always
    returns NOT_APPLICABLE.
    """
    config = store.case_type_configs_by_type.get(case["case_type"])
    if config is None or not config.get("requires_priority_date_current"):
        return "NOT_APPLICABLE"

    # Look up beneficiary to read preference_category + country_of_chargeability.
    beneficiary = store.beneficiaries.get(case.get("beneficiary_id"))
    if beneficiary is None:
        return "NOT_APPLICABLE"
    if beneficiary["preference_category"] == "IR":
        return "NOT_APPLICABLE"

    # Need priority_date set to evaluate currency against a real date.
    pd_str = case.get("priority_date")
    if pd_str is None:
        return "NOT_CURRENT"

    month = _latest_bulletin_month()
    if month is None:
        return "NOT_CURRENT"

    row = _select_bulletin_row(
        chart_type=store.chart_in_effect,
        month=month,
        category=beneficiary["preference_category"],
        country=beneficiary["country_of_chargeability"],
    )
    if row is None:
        return "NOT_CURRENT"

    cutoff = row["cutoff_date"]
    if cutoff == "CURRENT":
        return "CURRENT"
    if cutoff == "UNAVAILABLE":
        return "NOT_CURRENT"

    # Real date — strict less-than (PRD §2.9).
    cutoff_date = parse_iso_date(cutoff)
    case_pd = parse_iso_date(pd_str)
    if cutoff_date is None or case_pd is None:
        return "NOT_CURRENT"
    return "CURRENT" if case_pd < cutoff_date else "NOT_CURRENT"


def recompute_with_retrogression(case: dict) -> str:
    """Compute new status and substitute RETROGRESSED if previous was CURRENT.

    PRD §2.9: 'if the previous status was CURRENT and the newly computed
    status is NOT_CURRENT, the status is recorded as RETROGRESSED'.
    """
    previous = case.get("priority_date_status", "NOT_APPLICABLE")
    new_status = compute_priority_date_status(case)
    if previous == "CURRENT" and new_status == "NOT_CURRENT":
        return "RETROGRESSED"
    return new_status


# ────────────────────────────────────────────────────────────────────────────
# rfe_response_deadline (SCAFFOLD calculations.rfe_response_deadline)
# ────────────────────────────────────────────────────────────────────────────


def rfe_response_deadline(issued_at: datetime, window_days: int) -> datetime:
    """RFE.deadline_at = issued_at + window_days * 86400 seconds."""
    return issued_at + timedelta(seconds=window_days * 86400)


# ────────────────────────────────────────────────────────────────────────────
# mint_receipt_number (PRD §2.7; SCAFFOLD calculations.mint_receipt_number)
# ────────────────────────────────────────────────────────────────────────────


def mint_receipt_number(receipt_prefix: str, now: datetime) -> str:
    """Mint a 13-character USCIS-style Receipt Number.

    Algorithm (pinned order):
      p     := receipt_prefix              (3 letters)
      yr2   := now.year mod 100            (2 digits, zero-padded)
      doy3  := day-of-fiscal-year (1..366) (3 digits, zero-padded)
      seq5  := monotonic per-(prefix, fy)  (5 digits, zero-padded)

    The function MUST be called under store.lock so the sequence is
    advanced atomically.

    Raises ApiError(ERR_RECEIPT_NUMBER_COLLISION) if the resulting number
    is already in use (extremely defensive — sequence is unique per
    (prefix, fy) so collisions should be impossible inside the lock).
    """
    from errors import err_receipt_number_collision

    fy = fiscal_year_start(now)
    key = (receipt_prefix, fy)
    next_seq = store.receipt_sequences.get(key, 0) + 1

    # Try sequences until we find an unused receipt_number. In normal
    # operation the first attempt succeeds; we loop only as belt-and-braces
    # protection against any out-of-band reservation.
    for _ in range(10):
        yr2 = f"{now.year % 100:02d}"
        doy3 = f"{day_of_fiscal_year(now):03d}"
        seq5 = f"{next_seq:05d}"
        candidate = f"{receipt_prefix}{yr2}{doy3}{seq5}"
        if candidate not in store.receipt_numbers:
            store.receipt_sequences[key] = next_seq
            store.receipt_numbers.add(candidate)
            return candidate
        next_seq += 1
    raise err_receipt_number_collision()


# ────────────────────────────────────────────────────────────────────────────
# case_completeness_score (PRD §2.8, §3.11; SCAFFOLD calculations.case_completeness_score)
# ────────────────────────────────────────────────────────────────────────────


_STATUS_RAW = {
    "DRAFT": "0.00",
    "FILED": "0.10",
    "BIOMETRICS_SCHEDULED": "0.20",
    "BIOMETRICS_COMPLETED": "0.40",
    "RFE_ISSUED": "0.30",
    "RFE_RESPONDED": "0.50",
    "INTERVIEW_SCHEDULED": "0.70",
    "READY_FOR_DECISION": "0.90",
    "APPROVED": "1.00",
    "DENIED": "1.00",
    "WITHDRAWN": "1.00",
}


def case_completeness_score(case: dict) -> int:
    """Compute the case's 0..100 weighted completeness score.

    Per-factor weights:
      status      0.40
      biometrics  0.20
      rfe         0.10
      interview   0.15
      priority    0.15

    Rounding order (PRD §2.8):
      1. round each weighted product to 2 dp half-up
      2. sum the 5 rounded products
      3. multiply by 100, round half-up to integer
      4. clamp to [0, 100]
    """
    case_id = case["id"]

    f_status = Decimal(_STATUS_RAW.get(case["status"], "0.00"))

    biometrics_rows = [b for b in store.biometrics.values() if b["case_id"] == case_id]
    f_biometrics = Decimal("1.00") if any(b["status"] == "COMPLETED" for b in biometrics_rows) else Decimal("0.00")

    rfe_rows = [r for r in store.rfes.values() if r["case_id"] == case_id]
    config = store.case_type_configs_by_type.get(case["case_type"])
    requires_pd = bool(config and config.get("requires_priority_date_current"))
    has_outstanding_rfe = any(r["status"] == "OUTSTANDING" for r in rfe_rows)
    if (not requires_pd) or (not has_outstanding_rfe):
        f_rfe = Decimal("1.00")
    else:
        f_rfe = Decimal("0.00")

    interview_rows = [i for i in store.interviews.values() if i["case_id"] == case_id]
    if any(i["status"] == "COMPLETED" for i in interview_rows):
        f_interview = Decimal("1.00")
    elif any(i["status"] == "SCHEDULED" for i in interview_rows):
        f_interview = Decimal("0.50")
    else:
        f_interview = Decimal("0.00")

    pds = case.get("priority_date_status", "NOT_APPLICABLE")
    if pds in ("CURRENT", "NOT_APPLICABLE"):
        f_priority = Decimal("1.00")
    elif pds == "NOT_CURRENT":
        f_priority = Decimal("0.50")
    else:  # RETROGRESSED or anything unexpected
        f_priority = Decimal("0.00")

    # Pinned per-factor rounding (2 dp half-up).
    s_status = round_half_up(f_status * Decimal("0.40"), 2)
    s_biometrics = round_half_up(f_biometrics * Decimal("0.20"), 2)
    s_rfe = round_half_up(f_rfe * Decimal("0.10"), 2)
    s_interview = round_half_up(f_interview * Decimal("0.15"), 2)
    s_priority = round_half_up(f_priority * Decimal("0.15"), 2)

    total = (s_status + s_biometrics + s_rfe + s_interview + s_priority) * Decimal("100")
    final = int(round_half_up(total, 0))
    return max(0, min(100, final))
