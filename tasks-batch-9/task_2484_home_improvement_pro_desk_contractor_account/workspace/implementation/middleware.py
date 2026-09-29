"""Identity, role authorization and account scoping (PRD 2.1, 2.8, rungs 1/2/7)."""
from flask import request

import db
from errors import ApiError

ROLES = (
    "PlatformAdmin",
    "ContractorAdmin",
    "ProDeskAssociate",
    "CreditManager",
    "StoreOperations",
    "TaxComplianceOfficer",
)


def auth(*allowed_roles):
    """Rung 1 (ERR_UNAUTHENTICATED) then rung 2 (ERR_FORBIDDEN_ROLE)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401)
    if allowed_roles and role not in allowed_roles:
        raise ApiError("ERR_FORBIDDEN_ROLE", 403)
    return user_id, role


def check_scope(role, user_id, account_id):
    """Rung 7: a ContractorAdmin's X-User-ID is the id of its own ProAccount."""
    if role == "ContractorAdmin" and account_id is not None and user_id != account_id:
        raise ApiError("ERR_ACCOUNT_SCOPE_VIOLATION", 403)


# --- owning-account resolution (PRD 2.1: the check reaches through one hop) ---

def account_of_quote(quote):
    return quote["pro_account_id"]


def account_of_order(order):
    return order["pro_account_id"]


def account_of_quote_line(line):
    quote = db.get("job_quotes", line["job_quote_id"])
    return quote["pro_account_id"] if quote else None


def account_of_order_line(line):
    order = db.get("pro_orders", line["pro_order_id"])
    return order["pro_account_id"] if order else None


def account_of_via_order(rec):
    order = db.get("pro_orders", rec["pro_order_id"])
    return order["pro_account_id"] if order else None


def scope_list(role, user_id, records, resolver):
    """Contractor list reads only see their own account's records."""
    if role != "ContractorAdmin":
        return records
    return [r for r in records if resolver(r) == user_id]
