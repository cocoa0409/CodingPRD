"""Billing dimension and clock-driven transitions (SCAFFOLD §1.2 billing machine,
PRD §3.12, §3.13).
"""
from datetime import timedelta

import db
import clock
from util import parse_dt, to_midnight
from services.common import touch


def reevaluate_billing_on_settlement(account):
    """PAST_DUE/IN_COLLECTIONS -> CURRENT when no OPEN/PAST_DUE invoice remains.

    Returns True if billing_status changed (caller bumps account version).
    """
    has_open = any(
        inv["account_id"] == account["id"] and inv["status"] in ("OPEN", "PAST_DUE")
        for inv in db.invoices.values()
    )
    if not has_open and account["billing_status"] in ("PAST_DUE", "IN_COLLECTIONS"):
        account["billing_status"] = "CURRENT"
        return True
    return False


def advance_clock_transitions():
    """Evaluate the billing machine on every account at the new clock instant.

    - CURRENT -> PAST_DUE: an OPEN invoice's due_date strictly before clock date;
      that invoice's status becomes PAST_DUE.
    - PAST_DUE -> IN_COLLECTIONS: a PAST_DUE invoice with clock_date - due_date
      strictly more than 60 days.
    Every billing-dimension transition increments the account's version.
    Returns the number of accounts that advanced (changed billing_status).
    """
    today = clock.today_date()
    advanced = 0

    for account in db.service_accounts.values():
        changed = False

        # First, flip any OPEN invoices that have passed their due_date to PAST_DUE.
        flipped_any = False
        for inv in db.invoices.values():
            if inv["account_id"] != account["id"]:
                continue
            if inv["status"] == "OPEN":
                due = to_midnight(parse_dt(inv["due_date"]))
                if due < today:
                    inv["status"] = "PAST_DUE"
                    touch(inv)
                    flipped_any = True

        # CURRENT -> PAST_DUE
        if account["billing_status"] == "CURRENT" and flipped_any:
            account["billing_status"] = "PAST_DUE"
            changed = True

        # PAST_DUE -> IN_COLLECTIONS (a PAST_DUE invoice older than 60 days)
        if account["billing_status"] == "PAST_DUE":
            for inv in db.invoices.values():
                if inv["account_id"] != account["id"]:
                    continue
                if inv["status"] == "PAST_DUE":
                    due = to_midnight(parse_dt(inv["due_date"]))
                    if (today - due) > timedelta(days=60):
                        account["billing_status"] = "IN_COLLECTIONS"
                        changed = True
                        break

        if changed:
            touch(account)
            advanced += 1

    return advanced
