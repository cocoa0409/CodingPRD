"""Loan state machine helpers and transitions."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from ..clock import (
    add_days,
    days_between,
    first_of_month_at_or_after,
    format_iso,
    now_dt,
    now_iso_ms,
    parse_iso,
)
from ..store import bump_version, get_store


CAPITALIZE_ON_GRACE_EXIT = {"DIRECT_UNSUBSIDIZED", "DIRECT_PLUS"}


def capitalize_accrued(loan: dict[str, Any]) -> None:
    """Move accrued_interest_cents into principal_balance_cents + capitalized_interest_cents,
    then zero accrued."""
    accrued = int(loan.get("accrued_interest_cents", 0))
    if accrued <= 0:
        loan["accrued_interest_cents"] = 0
        return
    loan["principal_balance_cents"] = int(loan["principal_balance_cents"]) + accrued
    loan["capitalized_interest_cents"] = (
        int(loan.get("capitalized_interest_cents", 0)) + accrued
    )
    loan["accrued_interest_cents"] = 0


def set_due_first_of_month(loan: dict[str, Any], dt: datetime) -> None:
    loan["last_payment_due_at"] = format_iso(first_of_month_at_or_after(dt))


def set_status(loan: dict[str, Any], status: str) -> None:
    loan["status"] = status
    loan["status_entered_at"] = now_iso_ms()
    bump_version(loan)


def loan_belongs_to_borrower(loan_id: str, borrower_id: str) -> Optional[dict[str, Any]]:
    loan = get_store().loans.get(loan_id)
    if not loan:
        return None
    if loan.get("borrower_id") != borrower_id:
        return None
    return loan
