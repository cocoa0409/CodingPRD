"""Serialization: derived fields are refreshed on the way out."""

from core import DB, ordered, pagination, public, ok_list, window
from svc_ledger import count_committed, refresh_account
from svc_posture import sync_risk_score

ALL_ROLES = ("ProgramAdmin", "ProgramApprover", "FraudAnalyst", "AgencySupplier", "Cardholder")
ADMIN = ("ProgramAdmin",)
APPROVER = ("ProgramApprover",)
ANALYST = ("FraudAnalyst",)
CARDHOLDER = ("Cardholder",)
SUPPLIER = ("AgencySupplier",)
OPS = ("ProgramAdmin", "ProgramApprover", "FraudAnalyst")
OPS_CARD = ("ProgramAdmin", "ProgramApprover", "FraudAnalyst", "Cardholder")
AGENCY_READ = ("ProgramAdmin", "ProgramApprover", "AgencySupplier")
OFFER_READ = ("ProgramAdmin", "ProgramApprover", "AgencySupplier", "Cardholder")
FINANCE_READ = ("ProgramAdmin", "ProgramApprover")


def plain(row):
    return public(row)


def account_view(row):
    refresh_account(row)
    return public(row)


def entitlement_view(row):
    remaining = row["annual_allowance"] - row["used_count"]
    row["remaining_allowance"] = remaining if remaining > 0 else 0
    return public(row)


def case_view(row):
    sync_risk_score(row)
    return public(row)


def offer_view(row):
    row["seats_committed"] = count_committed(row["id"])
    return public(row)


def matches(row, filters):
    for field, value in filters.items():
        if value is None or value == "":
            continue
        current = row.get(field)
        if isinstance(current, bool) or isinstance(value, bool):
            if current is not value:
                return False
        elif current != value:
            return False
    return True


def listing(kind, args, filters, serialize=plain, rows=None, sort=None):
    limit, offset = pagination(args)
    source = DB[kind].values() if rows is None else rows
    selected = [r for r in source if matches(r, filters)]
    selected = sort(selected) if sort is not None else ordered(kind, selected)
    total = len(selected)
    page = [serialize(r) for r in window(selected, limit, offset)]
    return ok_list(page, limit, offset, total)
