"""Fine accrual: provisional and final readings."""
from clock import now, parse_iso, days_between_ceil
from services.money import DAILY_RATE_BY_CATEGORY, FINE_CAP_BY_CATEGORY


def _effective_due(loan: dict):
    if loan.get("is_recalled") and loan.get("recall_due_at"):
        return parse_iso(loan["recall_due_at"])
    return parse_iso(loan["due_at"])


def compute_provisional_fine(loan: dict, book_title: dict) -> int:
    """Live computation against current clock now()."""
    if loan["status"] not in {"BORROWED", "RENEWED", "RECALL_PENDING"}:
        return 0
    cat = book_title["subject_category"]
    daily = DAILY_RATE_BY_CATEGORY[cat]
    cap = FINE_CAP_BY_CATEGORY[cat]
    effective_due = _effective_due(loan)
    n = now()
    if n <= effective_due:
        return 0
    days = days_between_ceil(n, effective_due)
    raw = days * daily
    return min(raw, cap)


def compute_final_fine_amount(loan: dict, book_title: dict, returned_at):
    """Returns (days_overdue, accrued_cents, daily_rate, cap) — accrued_cents is 0 if not late."""
    cat = book_title["subject_category"]
    daily = DAILY_RATE_BY_CATEGORY[cat]
    cap = FINE_CAP_BY_CATEGORY[cat]
    effective_due = _effective_due(loan)
    if returned_at <= effective_due:
        return 0, 0, daily, cap
    days = days_between_ceil(returned_at, effective_due)
    if days <= 0:
        return 0, 0, daily, cap
    raw = days * daily
    return days, min(raw, cap), daily, cap
