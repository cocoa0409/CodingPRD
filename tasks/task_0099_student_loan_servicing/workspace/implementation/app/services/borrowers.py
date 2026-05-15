"""Borrower service: aggregates and snapshot helpers."""
from __future__ import annotations

from typing import Any

from ..store import get_store


TERMINAL_LOAN_STATUSES = {"PAID_OFF", "DISCHARGED"}


def loans_for_borrower(borrower_id: str) -> list[dict[str, Any]]:
    return [l for l in get_store().loans.values() if l.get("borrower_id") == borrower_id]


def non_terminal_loans(borrower_id: str) -> list[dict[str, Any]]:
    return [l for l in loans_for_borrower(borrower_id) if l["status"] not in TERMINAL_LOAN_STATUSES]


def recompute_aggregates(borrower: dict[str, Any]) -> None:
    """Refresh aggregate_principal_balance_cents and aggregate_interest_balance_cents."""
    loans = non_terminal_loans(borrower["id"])
    borrower["aggregate_principal_balance_cents"] = sum(
        int(l.get("principal_balance_cents", 0)) for l in loans
    )
    borrower["aggregate_interest_balance_cents"] = sum(
        int(l.get("accrued_interest_cents", 0)) for l in loans
    )


def borrower_view(borrower: dict[str, Any]) -> dict[str, Any]:
    """Return a fresh dict for response: recompute aggregates first."""
    recompute_aggregates(borrower)
    return dict(borrower)
