"""PackageSeries credit balance recomputation and status transitions.

package_credit_balance (SCAFFOLD §1.3 / PRD 3.4):
  reserved_credits  = count(appts of series with clinical_status IN {SCHEDULED, CHECKED_IN})
  consumed_credits  = count(appts of series with clinical_status == COMPLETED)
  provisional_remaining_credits = total_credits - reserved_credits - consumed_credits
  finalized_remaining_credits   = total_credits - consumed_credits

The series status tracks the provisional balance (ACTIVE <-> EXHAUSTED).
"""

from common import touch
from db import db


def recompute_balances(series):
    """Recompute both credit balances from the live appointment set. Returns the
    provisional balance prior to recompute so callers can detect threshold
    crossings if needed."""
    sid = series["id"]
    reserved = 0
    consumed = 0
    for appt in db.appointments.values():
        if appt.get("package_series_id") != sid:
            continue
        cs = appt["clinical_status"]
        if cs in ("SCHEDULED", "CHECKED_IN"):
            reserved += 1
        elif cs == "COMPLETED":
            consumed += 1
    series["reserved_credits"] = reserved
    series["consumed_credits"] = consumed
    series["provisional_remaining_credits"] = series["total_credits"] - reserved - consumed
    series["finalized_remaining_credits"] = series["total_credits"] - consumed


def reconcile_series(series):
    """Recompute balances, then re-evaluate the ACTIVE<->EXHAUSTED auto-transition.
    Always bumps the series version + updated_at (this is invoked as part of a
    mutation to the series — booking/complete/no-show/cancel)."""
    recompute_balances(series)
    status = series["status"]
    prov = series["provisional_remaining_credits"]
    if status == "ACTIVE" and prov == 0:
        series["status"] = "EXHAUSTED"
    elif status == "EXHAUSTED" and prov > 0:
        series["status"] = "ACTIVE"
    touch(series)
