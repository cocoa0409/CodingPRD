"""Calculation rules per SCAFFOLD §1.3."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import List, Optional

from .clock import (
    format_datetime_ms,
    format_date,
    get_clock,
    parse_iso_date,
)


# ---------------------------------------------------------------------------
# compute_section2_deadline
# ---------------------------------------------------------------------------

def compute_section2_deadline(start_date_iso: str) -> str:
    """3 federal working days strictly after start_date, ending 23:59:59.999 UTC."""
    clock = get_clock()
    d0 = parse_iso_date(start_date_iso)
    deadline_date = clock.add_federal_working_days(d0, 3)
    dt = datetime(
        deadline_date.year, deadline_date.month, deadline_date.day,
        23, 59, 59, 999_000, tzinfo=timezone.utc,
    )
    return format_datetime_ms(dt)


# ---------------------------------------------------------------------------
# compute_reverification_due
# ---------------------------------------------------------------------------

# Documents whose category contributes to reverification.
_REVERIFY_CATEGORIES = {"LIST_A", "LIST_C"}


def compute_reverification_due(
    employee: dict,
    docs_on_form: List[dict],
    *,
    stem_extended: bool = False,
) -> Optional[str]:
    """Return the earliest reverification-driving expiration date as ISO YYYY-MM-DD,
    or None when there are no candidates.

    `stem_extended` — when True and the LIST_A doc is an EAD I-766 and visa is
    F1_OPT_STEM, the EAD expiry is shifted forward by 180 calendar days.
    """
    candidates: List[date] = []

    # 1) Employee.work_authorization_expiry (only for ALIEN_AUTHORIZED).
    if employee.get("citizenship_status") == "ALIEN_AUTHORIZED":
        wae = employee.get("work_authorization_expiry")
        if wae:
            candidates.append(parse_iso_date(wae))

    # 2) Documents in LIST_A / LIST_C with non-null expiration_date.
    for doc in docs_on_form:
        if doc is None:
            continue
        if doc.get("category") not in _REVERIFY_CATEGORIES:
            continue
        exp = doc.get("expiration_date")
        if not exp:
            continue
        d = parse_iso_date(exp)
        # OPT EAD STEM extension auto-180 — handled per-doc below.
        if (
            stem_extended
            and doc.get("category") == "LIST_A"
            and doc.get("document_title") == "EAD I-766"
            and employee.get("visa_class") == "F1_OPT_STEM"
        ):
            d = d + timedelta(days=180)
        candidates.append(d)

    if not candidates:
        return None
    return format_date(min(candidates))


# ---------------------------------------------------------------------------
# compute_reverification_deadline
# ---------------------------------------------------------------------------

def compute_reverification_deadline(
    *, reason: str, base_reverification_due: Optional[str], rehire_start_date: Optional[str]
) -> Optional[str]:
    if reason == "WORK_AUTH_EXPIRY":
        if not base_reverification_due:
            return None
        d = parse_iso_date(base_reverification_due)
    elif reason == "OPT_TO_OPT_STEM_EXTENSION":
        if not base_reverification_due:
            return None
        d = parse_iso_date(base_reverification_due) + timedelta(days=180)
    elif reason == "REHIRE_WITHIN_3_YEARS":
        if not rehire_start_date:
            return None
        clock = get_clock()
        d0 = parse_iso_date(rehire_start_date)
        d = clock.add_federal_working_days(d0, 3)
    else:
        return None

    dt = datetime(d.year, d.month, d.day, 23, 59, 59, 999_000, tzinfo=timezone.utc)
    return format_datetime_ms(dt)


# ---------------------------------------------------------------------------
# compute_tnc_contest_deadline
# ---------------------------------------------------------------------------

def compute_tnc_contest_deadline(tnc_opened_at_dt: datetime) -> str:
    """10 federal working days strictly after tnc_opened_at, ending 23:59:59.999 UTC."""
    clock = get_clock()
    d0 = tnc_opened_at_dt.date()
    deadline_date = clock.add_federal_working_days(d0, 10)
    dt = datetime(
        deadline_date.year, deadline_date.month, deadline_date.day,
        23, 59, 59, 999_000, tzinfo=timezone.utc,
    )
    return format_datetime_ms(dt)
