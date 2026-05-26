"""Business-logic services: helpers shared across route modules.

Includes: account re-aggregation, StateTaxIncentive aggregation, Form1099Q
aggregation, cadence-interval advancement.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from dateutil.relativedelta import relativedelta

from db import store, stamp_update


# ---------------------------------------------------------------------------
# Cadence intervals
# ---------------------------------------------------------------------------

def advance_by_cadence(when: datetime, cadence: str) -> datetime:
    """ScheduledContribution cadence: WEEKLY = +7 days, MONTHLY = +1 calendar
    month, QUARTERLY = +3 calendar months."""
    if cadence == "WEEKLY":
        return when + timedelta(days=7)
    if cadence == "MONTHLY":
        return when + relativedelta(months=+1)
    if cadence == "QUARTERLY":
        return when + relativedelta(months=+3)
    raise ValueError(f"unknown cadence: {cadence!r}")


# ---------------------------------------------------------------------------
# Account ledger re-aggregation
# ---------------------------------------------------------------------------

def recompute_account_ledger(account: Dict, *, bump_version: bool, now: datetime) -> None:
    """Recompute account_balance/total_basis/total_earnings from primary
    sources (POSTED Contributions and DISBURSED Withdrawals).

    PRD §3.4: balance := sum(POSTED contributions) - sum(DISBURSED withdrawals);
              basis   := sum(POSTED contributions) - sum(DISBURSED basis portions).
    """
    account_id = account["id"]
    posted_total = sum(
        c["amount_cents"]
        for c in store.contributions.values()
        if c["account_id"] == account_id and c["status"] == "POSTED"
    )
    disbursed_total = sum(
        w["amount_cents"]
        for w in store.withdrawals.values()
        if w["account_id"] == account_id and w["status"] == "DISBURSED"
    )
    disbursed_basis = sum(
        (w.get("basis_portion_cents") or 0)
        for w in store.withdrawals.values()
        if w["account_id"] == account_id and w["status"] == "DISBURSED"
    )
    # Market earnings (synthetic) — tracked outside primary contribution data.
    market_credit = account.get("_market_credit_cents", 0)

    account["account_balance_cents"] = posted_total - disbursed_total + market_credit
    account["total_basis_cents"] = posted_total - disbursed_basis
    account["total_earnings_cents"] = account["account_balance_cents"] - account["total_basis_cents"]
    if bump_version:
        stamp_update(account, now)


# ---------------------------------------------------------------------------
# StateTaxIncentive re-aggregation (DRAFT rows only)
# ---------------------------------------------------------------------------

def recompute_state_tax_incentives(donor_id: str, tax_year: int) -> None:
    """Re-aggregate contributions_eligible_cents for any matching
    StateTaxIncentive(donor_id, tax_year). Re-aggregation is always live —
    even after the row has advanced past DRAFT — but match_cents is NOT
    retroactively reapplied (the match is locked when the row entered
    CALCULATED, per PRD §3.8 last paragraph).
    """
    donor_account_ids = {
        a["id"] for a in store.accounts.values() if a["donor_id"] == donor_id
    }
    eligible_total = sum(
        c["amount_cents"]
        for c in store.contributions.values()
        if c["status"] == "POSTED"
        and c.get("tax_year") == tax_year
        and c["account_id"] in donor_account_ids
    )
    for sti in store.state_tax_incentives.values():
        if sti["donor_id"] == donor_id and sti["tax_year"] == tax_year:
            sti["contributions_eligible_cents"] = eligible_total


# ---------------------------------------------------------------------------
# Form 1099-Q aggregate refresh (DRAFT only)
# ---------------------------------------------------------------------------

def refresh_form_1099q_aggregates(form: Dict) -> None:
    """Recompute aggregates for a DRAFT (or newly-spawned, pre-REISSUED) form
    from current DISBURSED Withdrawal data.

    Sets gross_distribution / earnings / basis / penalty cents and
    recipient_kind (ACCOUNT_OWNER if any NON_QUALIFIED DISBURSED row exists
    for that (account_id, tax_year), else BENEFICIARY).
    """
    account_id = form["account_id"]
    tax_year = form["tax_year"]
    matching = [
        w
        for w in store.withdrawals.values()
        if w["account_id"] == account_id
        and w["status"] == "DISBURSED"
        and w.get("tax_year") == tax_year
    ]
    form["gross_distribution_cents"] = sum(w["amount_cents"] for w in matching)
    form["earnings_cents"] = sum(w.get("earnings_portion_cents", 0) for w in matching)
    form["basis_cents"] = sum(w.get("basis_portion_cents", 0) for w in matching)
    form["penalty_cents"] = sum(w.get("penalty_cents", 0) for w in matching)
    has_non_qualified = any(w.get("expense_class") == "NON_QUALIFIED" for w in matching)
    form["recipient_kind"] = "ACCOUNT_OWNER" if has_non_qualified else "BENEFICIARY"


def refresh_matching_draft_forms_on_disburse(account_id: str, tax_year: int) -> None:
    """After a withdrawal disburses, every DRAFT Form1099Q matching the same
    (account_id, tax_year) has its aggregate fields refreshed (PRD §3.5 last
    paragraph)."""
    from db import iso_ms  # avoid circular
    for form in store.forms_1099q.values():
        if (
            form["status"] == "DRAFT"
            and form["account_id"] == account_id
            and form["tax_year"] == tax_year
        ):
            refresh_form_1099q_aggregates(form)
            form["updated_at"] = iso_ms(store.clock_utc)


# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------

def get_account_owner_donor_id(account_id: str) -> Optional[str]:
    a = store.accounts.get(account_id)
    return a["donor_id"] if a else None
