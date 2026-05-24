"""In-memory data store. Resets to empty on every fresh process start."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone


def new_id() -> str:
    """UUID without a type prefix per PRD §2.4."""
    return str(uuid.uuid4())


def now_iso() -> str:
    """ISO 8601 UTC timestamp with three fractional digits."""
    now = datetime.now(timezone.utc)
    ms = now.microsecond // 1000
    return now.strftime("%Y-%m-%dT%H:%M:%S") + f".{ms:03d}Z"


# Entity stores keyed by id
borrowers: dict = {}
loans: dict = {}
repayment_plans: dict = {}
payments: dict = {}
servicing_events: dict = {}
employment_certifications: dict = {}
pslf_trackers: dict = {}
discharge_applications: dict = {}
delinquency_records: dict = {}

# Per-Loan tracking: ordered list of monthly due dates that have been generated
# This drives the delinquency clock-advance logic.
# Keyed by loan_id -> list of ISO date strings
loan_due_dates: dict = {}

# System clock — ISO 8601 date string (YYYY-MM-DD). Defaults to today.
# A simulation date drives all time-gated behaviors.
_clock_state = {"date": datetime.now(timezone.utc).strftime("%Y-%m-%d")}


def get_clock_date() -> str:
    return _clock_state["date"]


def set_clock_date(iso_date: str) -> None:
    _clock_state["date"] = iso_date


def reset_all() -> None:
    """Test helper: wipe every store. Not called at startup."""
    borrowers.clear()
    loans.clear()
    repayment_plans.clear()
    payments.clear()
    servicing_events.clear()
    employment_certifications.clear()
    pslf_trackers.clear()
    discharge_applications.clear()
    delinquency_records.clear()
    loan_due_dates.clear()
    _clock_state["date"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")
