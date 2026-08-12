"""Derived aggregates, ledger appends and the shared cascades.

The five conservation invariants of PRD section 2.12 are guaranteed by
recomputing each aggregate from its own source population rather than by
incrementing counters in place.
"""

from . import calc
from . import constants as K
from .clock import month_of_date_string
from .store import all_of, bump, db, new_row


# -- lookups --------------------------------------------------------------

def in_force_bond():
    for bond in all_of("surety_bonds"):
        if bond["status"] == "IN_FORCE":
            return bond
    return None


def period_for_month(account_id, month):
    if month is None:
        return None
    for period in all_of("reconciliation_periods"):
        if period["account_id"] == account_id and period["period_month"] == month:
            return period
    return None


def period_for_date(account_id, date_str):
    return period_for_month(account_id, month_of_date_string(date_str))


def payments_of_account(account_id):
    return [p for p in db.ordered("payments") if p["account_id"] == account_id]


def payments_of_budget_line(line_id):
    return [p for p in all_of("payments") if p["budget_category_id"] == line_id]


def entries_of_account(account_id):
    return [e for e in all_of("ledger_entries") if e["account_id"] == account_id]


def accounts_of_client(client_id):
    return [a for a in db.ordered("accounts") if a["client_id"] == client_id]


# -- account_available_balance -------------------------------------------

def recompute_account(account):
    cleared = account["opening_balance_cents"]
    for entry in entries_of_account(account["id"]):
        cleared += entry["amount_cents"]
    committed = 0
    for payment in payments_of_account(account["id"]):
        if payment["settlement_status"] in ("SCHEDULED", "IN_FLIGHT"):
            committed += payment["total_charge_cents"]
    account["cleared_balance_cents"] = cleared
    account["committed_disbursements_cents"] = committed
    account["available_balance_cents"] = (
        cleared - account["pending_holds_cents"] - committed
    )
    return account


# -- budget_variance ------------------------------------------------------

def recompute_budget(line):
    committed = 0
    settled = 0
    for payment in payments_of_budget_line(line["id"]):
        status = payment["settlement_status"]
        if status in ("SCHEDULED", "IN_FLIGHT", "SETTLED"):
            committed += payment["amount_cents"]
        if status == "SETTLED":
            settled += payment["amount_cents"]
    capacity = line["allocation_cents"] + line["override_granted_cents"]
    line["committed_cents"] = committed
    line["settled_cents"] = settled
    line["remaining_cents"] = capacity - committed
    line["variance_full_cents"] = capacity - committed
    prorated = calc.prorated_allocation_cents(
        line["allocation_cents"], line["override_granted_cents"],
        line["budget_month"], db.now.date(),
    )
    line["variance_ptd_cents"] = prorated - settled
    line["variance_direction"] = calc.variance_direction(line["variance_ptd_cents"])
    return line


# -- bond_exposure --------------------------------------------------------

def recompute_bond():
    bond = in_force_bond()
    if bond is None:
        return None
    committed = 0
    settled_this_month = 0
    current_month = db.current_month()
    for payment in all_of("payments"):
        status = payment["settlement_status"]
        if status in ("SCHEDULED", "IN_FLIGHT"):
            committed += payment["amount_cents"]
        elif status == "SETTLED":
            if month_of_date_string(payment.get("settled_on")) == current_month:
                settled_this_month += payment["amount_cents"]
    bond["exposure_committed_cents"] = committed
    bond["exposure_settled_inclusive_cents"] = committed + settled_this_month
    bond["headroom_committed_cents"] = bond["coverage_cents"] - committed
    return bond


def recompute_payment_aggregates(payment):
    """Refresh every aggregate a payment's status or amount participates in."""
    account = db.accounts.get(payment["account_id"])
    if account is not None:
        recompute_account(account)
    line = db.budget_categories.get(payment["budget_category_id"])
    if line is not None:
        recompute_budget(line)
    recompute_bond()


# -- ledger_period_assignment --------------------------------------------

def append_ledger_entry(account, entry_type, amount_cents, entry_date,
                        memo=None, source_payment_id=None,
                        retro_period_month=None, period=None):
    """Append one immutable LedgerEntry and apply its consequences."""
    if period is None:
        period = period_for_date(account["id"], entry_date)
    entry = new_row(
        "ledger_entries",
        {
            "account_id": account["id"],
            "period_id": period["id"] if period is not None else None,
            "source_payment_id": source_payment_id,
            "entry_type": entry_type,
            "amount_cents": amount_cents,
            "entry_date": entry_date,
            "retro_period_month": retro_period_month,
            "memo": memo,
        },
        versioned=False,
    )
    recompute_account(account)
    if period is not None:
        period["unreconciled_entry_count"] += 1
        # A period IN_REVIEW reverts to OPEN the moment a new entry lands.
        if period["status"] == "IN_REVIEW":
            period["status"] = "OPEN"
            bump(period)
    return entry


def adopt_entries_into_period(period):
    """Opening a period retroactively adopts that month's existing entries."""
    adopted = 0
    for entry in db.ordered("ledger_entries"):
        if entry["account_id"] != period["account_id"]:
            continue
        if month_of_date_string(entry["entry_date"]) != period["period_month"]:
            continue
        entry["period_id"] = period["id"]
        adopted += 1
    period["unreconciled_entry_count"] = adopted
    return adopted


# -- the shared payment unwinds ------------------------------------------

def cancel_payment_row(payment):
    """SCHEDULED -> CANCELLED; the exact compensating action for scheduling."""
    payment["settlement_status"] = "CANCELLED"
    bump(payment)
    recompute_payment_aggregates(payment)


def stop_payment_row(payment):
    """SCHEDULED or IN_FLIGHT -> STOPPED, charging the stop fee."""
    payment["settlement_status"] = "STOPPED"
    bump(payment)
    account = db.accounts.get(payment["account_id"])
    if account is not None:
        append_ledger_entry(
            account,
            "STOP_PAYMENT_FEE",
            -K.STOP_PAYMENT_FEE_CENTS,
            db.today_str(),
            memo="Stop payment fee",
            source_payment_id=payment["id"],
        )
    recompute_payment_aggregates(payment)


# -- the freeze sweep (PRD 3.5) ------------------------------------------

def freeze_sweep(account):
    """Hops A through D, payments visited in ascending created_at order."""
    for payment in payments_of_account(account["id"]):
        status = payment["settlement_status"]
        if status == "SCHEDULED":
            cancel_payment_row(payment)
        elif status == "IN_FLIGHT":
            stop_payment_row(payment)


# -- the revocation cascade (PRD 3.1) ------------------------------------

def revoke_authorization(auth, revocation_reason):
    """The six-part cascade, every part caused by the part above it."""
    auth["status"] = "REVOKED"
    auth["revoked_at"] = db.now
    auth["revocation_reason"] = revocation_reason

    cancelled = 0
    for payment in db.ordered("payments"):
        if payment["authorization_id"] != auth["id"]:
            continue
        if payment["settlement_status"] != "SCHEDULED":
            continue
        cancel_payment_row(payment)
        cancelled += 1

    terminated = 0
    for recipient in db.ordered("family_recipients"):
        if recipient["authorization_id"] != auth["id"]:
            continue
        if recipient["subscription_status"] not in ("PENDING", "ACTIVE", "SUSPENDED"):
            continue
        recipient["subscription_status"] = "TERMINATED"
        bump(recipient)
        terminated += 1

    withdrawn = 0
    for application in db.ordered("benefit_applications"):
        if application["authorization_id"] != auth["id"]:
            continue
        if application["status"] not in ("DRAFT", "SUBMITTED", "APPEALED"):
            continue
        application["status"] = "WITHDRAWN"
        bump(application)
        withdrawn += 1

    auth["cascaded_payments_cancelled"] = cancelled
    auth["cascaded_recipients_terminated"] = terminated
    auth["cascaded_applications_withdrawn"] = withdrawn
    bump(auth)
    return auth
