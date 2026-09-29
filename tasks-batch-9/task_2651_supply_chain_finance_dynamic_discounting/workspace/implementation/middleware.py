"""Authentication, role authorisation, resource lookups and scope checks.

PRD 2.1 pins the two headers (X-User-ID, X-User-Role) and the five roles.
PRD 2.7 pins the precedence: authentication (1) -> role authorisation (2) ->
request shape (3) -> path existence (4) -> resource scope (5) -> body FK
existence (6) -> business rules.
"""

from flask import request

from db import db
from errors import ApiError

BUYER_ADMIN = "BuyerAdmin"
BUYER_TREASURY = "BuyerTreasury"
SUPPLIER = "Supplier"
FUNDER = "Funder"
PLATFORM_OPS = "PlatformOps"

ROLES = (BUYER_ADMIN, BUYER_TREASURY, SUPPLIER, FUNDER, PLATFORM_OPS)
BUYER_ROLES = (BUYER_ADMIN, BUYER_TREASURY)


class Ctx(object):
    __slots__ = ("role", "uid")

    def __init__(self, role, uid):
        self.role = role
        self.uid = uid

    @property
    def is_ops(self):
        return self.role == PLATFORM_OPS

    @property
    def is_buyer(self):
        return self.role in BUYER_ROLES


def authenticate(allowed_roles):
    """Check 1 then check 2."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if uid is None or role is None:
        raise ApiError("ERR_UNAUTHENTICATED")
    uid = uid.strip()
    role = role.strip()
    if not uid or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    ctx = Ctx(role, uid)
    if allowed_roles is not None and role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED")
    return ctx


# --------------------------------------------------------------------------
# lookups (checks 4 and 6 share these identifiers)
# --------------------------------------------------------------------------

def _find(table, key, error_id):
    if not isinstance(key, str):
        raise ApiError(error_id)
    row = table.get(key)
    if row is None:
        raise ApiError(error_id)
    return row


def get_buyer(bid):
    return _find(db.buyers, bid, "ERR_BUYER_NOT_FOUND")


def get_program(pid):
    return _find(db.programs, pid, "ERR_PROGRAM_NOT_FOUND")


def get_session(sid):
    return _find(db.sessions, sid, "ERR_SESSION_NOT_FOUND")


def get_supplier(sid):
    return _find(db.suppliers, sid, "ERR_SUPPLIER_NOT_FOUND")


def get_bank_account(bid):
    return _find(db.bank_accounts, bid, "ERR_BANK_ACCOUNT_NOT_FOUND")


def get_invoice(iid):
    return _find(db.invoices, iid, "ERR_INVOICE_NOT_FOUND")


def get_dispute(did):
    return _find(db.disputes, did, "ERR_DISPUTE_NOT_FOUND")


def get_offer(oid):
    return _find(db.offers, oid, "ERR_OFFER_NOT_FOUND")


def get_funder(fid):
    return _find(db.funders, fid, "ERR_FUNDER_NOT_FOUND")


def get_payment(pid):
    return _find(db.payments, pid, "ERR_EARLY_PAYMENT_NOT_FOUND")


# --------------------------------------------------------------------------
# scope (check 5) -- only ever evaluated once the identifier has resolved
# --------------------------------------------------------------------------

def _deny():
    raise ApiError("ERR_FORBIDDEN_RESOURCE_SCOPE")


def scope_buyer(ctx, buyer_id):
    if ctx.is_buyer and ctx.uid != buyer_id:
        _deny()


def scope_supplier(ctx, supplier_id):
    if ctx.role == SUPPLIER and ctx.uid != supplier_id:
        _deny()


def scope_funder(ctx, funder_id):
    if ctx.role == FUNDER and ctx.uid != funder_id:
        _deny()


def program_of(row_program_id):
    return db.programs.get(row_program_id)


def buyer_id_of_program(program):
    return program["buyer_id"] if program else None


def scope_program(ctx, program):
    scope_buyer(ctx, program["buyer_id"])


def scope_session(ctx, session):
    program = db.programs.get(session["program_id"])
    if program is not None:
        scope_buyer(ctx, program["buyer_id"])


def scope_file(ctx, file_row):
    program = db.programs.get(file_row["program_id"])
    if program is not None:
        scope_buyer(ctx, program["buyer_id"])


def scope_invoice(ctx, invoice):
    scope_supplier(ctx, invoice["supplier_id"])
    program = db.programs.get(invoice["program_id"])
    if program is not None:
        scope_buyer(ctx, program["buyer_id"])


def scope_dispute(ctx, dispute):
    invoice = db.invoices.get(dispute["invoice_id"])
    if invoice is not None:
        scope_invoice(ctx, invoice)


def scope_offer(ctx, offer):
    scope_supplier(ctx, offer["supplier_id"])
    invoice = db.invoices.get(offer["invoice_id"])
    if invoice is not None:
        program = db.programs.get(invoice["program_id"])
        if program is not None:
            scope_buyer(ctx, program["buyer_id"])


def scope_payment(ctx, payment):
    if payment.get("funder_id"):
        scope_funder(ctx, payment["funder_id"])
    elif ctx.role == FUNDER:
        _deny()
    invoice = db.invoices.get(payment["invoice_id"])
    if invoice is not None:
        scope_invoice(ctx, invoice)
