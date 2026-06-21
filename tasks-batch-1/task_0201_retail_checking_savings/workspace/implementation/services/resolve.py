"""Resource resolution with specialized not-found errors (PRD §2.8)."""
from db import db
import errors
from errors import ApiError


def get_customer(customer_id, specialized=False):
    c = db.customers.get(customer_id)
    if c is None:
        eid = errors.ERR_CUSTOMER_NOT_FOUND if specialized else errors.ERR_NOT_FOUND
        raise ApiError(eid, 404, "Customer not found")
    return c


def get_application(app_id):
    a = db.applications.get(app_id)
    if a is None:
        raise ApiError(errors.ERR_NOT_FOUND, 404, "Application not found")
    return a


def get_account(account_id, specialized=False):
    a = db.accounts.get(account_id)
    if a is None:
        eid = errors.ERR_ACCOUNT_NOT_FOUND if specialized else errors.ERR_NOT_FOUND
        raise ApiError(eid, 404, "Account not found")
    return a


def get_owner(owner_id):
    o = db.account_owners.get(owner_id)
    if o is None:
        raise ApiError(errors.ERR_NOT_FOUND, 404, "Account owner not found")
    return o


def get_transaction(txn_id):
    t = db.transactions.get(txn_id)
    if t is None:
        raise ApiError(errors.ERR_NOT_FOUND, 404, "Transaction not found")
    return t


def get_fee_assessment(fee_id):
    f = db.fee_assessments.get(fee_id)
    if f is None:
        raise ApiError(errors.ERR_NOT_FOUND, 404, "Fee assessment not found")
    return f


def get_ach_origination(orig_id):
    o = db.ach_originations.get(orig_id)
    if o is None:
        raise ApiError(errors.ERR_NOT_FOUND, 404, "ACH origination not found")
    return o


def get_ach_leg(leg_id):
    l = db.ach_legs.get(leg_id)
    if l is None:
        raise ApiError(errors.ERR_NOT_FOUND, 404, "ACH leg not found")
    return l


def get_apy_tier_by_code(code, product_type):
    """Resolve an ApyTier by code whose product_type matches (PRD §3.3, §2.8)."""
    for t in db.apy_tiers.values():
        if t["code"] == code and t["product_type"] == product_type:
            return t
    return None


def active_owners(account_id):
    return [o for o in db.account_owners.values()
            if o["account_id"] == account_id and o["is_active"]]


def is_active_owner(account_id, customer_id):
    return any(o["customer_id"] == customer_id for o in active_owners(account_id))


def require_account_owner(account, user_id):
    """AccountHolder ownership gate (PRD §2.1, §2.10 priority 4)."""
    if not is_active_owner(account["id"], user_id):
        raise ApiError(errors.ERR_NOT_ACCOUNT_OWNER, 403,
                       "Acting principal is not an active owner of this account")


def primary_owner(account_id):
    """The active PRIMARY owner of an account (for escheat jurisdiction)."""
    for o in active_owners(account_id):
        if o["ownership_role"] == "PRIMARY":
            return o
    return None
