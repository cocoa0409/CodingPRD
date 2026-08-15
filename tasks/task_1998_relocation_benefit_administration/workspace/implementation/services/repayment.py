"""Repayment schedule logic per scaffold `repayment_schedule` and PRD §3.8."""

from decimal import Decimal, ROUND_HALF_UP

from util import whole_months_between, add_months


def compute_months_remaining(termination_date, authorized_at, repayment_window_months):
    """whole calendar months between termination_date and authorized_at + window."""
    required_service_end = add_months(authorized_at, repayment_window_months)
    return whole_months_between(termination_date, required_service_end)


def compute_schedule(total_paid_cents, months_remaining, repayment_window_months):
    """Return (total_owed_cents, installments_count, installment_cents, final_installment_cents)."""
    total_owed = int(
        (Decimal(int(total_paid_cents)) * Decimal(months_remaining)
         / Decimal(repayment_window_months)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    )
    installments_count = repayment_window_months
    installment_cents = total_owed // installments_count  # floor
    final_installment_cents = total_owed - (installments_count - 1) * installment_cents
    return total_owed, installments_count, installment_cents, final_installment_cents


def arrears_threshold(agreement, clock_now):
    """min(months_elapsed, installments_count - 1) * installment_cents."""
    if agreement.get("signed_at") is None:
        return 0
    months_elapsed = whole_months_between(agreement["signed_at"], clock_now)
    cap = max(0, agreement["installments_count"] - 1)
    months_capped = min(months_elapsed, cap)
    return months_capped * agreement["installment_cents"]
