"""The four write gates of PRD section 2.8, plus the client-active rung.

Order is normative - widest blast radius first - so callers invoke them in
ascending rung order: 6 bond, 7 authorization, 8 scope, 9 account freeze,
10 reconciliation freeze, 11 client active.
"""

from . import calc
from .aggregates import in_force_bond, period_for_date
from .clock import parse_date
from .errors import fail
from .store import db


def _covers(effective_date, expiry_date, day):
    start = parse_date(effective_date)
    end = parse_date(expiry_date)
    if start is None or end is None:
        return False
    return start <= day <= end


# -- rung 6 ---------------------------------------------------------------

def gate_bond():
    bond = in_force_bond()
    if bond is None or not _covers(bond["effective_date"], bond["expiry_date"], db.now.date()):
        fail("ERR_BOND_EXPIRED", "No surety bond is in force for the current date.")
    return bond


# -- rung 7 ---------------------------------------------------------------

def gate_authorization(auth):
    if auth is None:
        fail("ERR_AUTHORIZATION_INACTIVE", "No governing authorization instrument.")
    if auth["status"] != "ACTIVE":
        fail("ERR_AUTHORIZATION_INACTIVE", "The governing instrument is not ACTIVE.")
    if not _covers(auth["effective_date"], auth["expiry_date"], db.now.date()):
        fail("ERR_AUTHORIZATION_INACTIVE", "The governing instrument is out of its window.")
    return auth


# -- rung 8 ---------------------------------------------------------------

def gate_scope_payment(auth, payee):
    if not calc.scope_permits_payment(auth["scope_tier"], payee["payee_type"]):
        fail("ERR_SCOPE_NOT_PERMITTED", "The instrument's scope tier forbids this payment.")


def gate_scope_benefit_application(auth):
    if not calc.scope_permits_benefit_application(auth["scope_tier"]):
        fail("ERR_SCOPE_NOT_PERMITTED", "The instrument's scope tier forbids this filing.")


def gate_scope_family_recipient(auth):
    if not calc.scope_permits_family_recipient(auth["scope_tier"]):
        fail("ERR_SCOPE_NOT_PERMITTED", "The instrument's scope tier forbids enrolment.")


# -- rung 9 ---------------------------------------------------------------

def gate_account_frozen(account):
    if account is not None and account["fraud_posture"] == "FROZEN":
        fail("ERR_ACCOUNT_FROZEN", "The account is frozen for suspected fraud.")


# -- rung 10 --------------------------------------------------------------

def _refuse_if_frozen(period):
    if period is not None and period["status"] in ("CLOSED", "LOCKED"):
        fail("ERR_PERIOD_FROZEN", "The receiving reconciliation period is frozen.")


def gate_period_frozen_for_date(account, date_str):
    if account is None:
        return
    _refuse_if_frozen(period_for_date(account["id"], date_str))


def gate_period_frozen_now(account):
    gate_period_frozen_for_date(account, db.today_str())


def gate_period_frozen_row(period):
    _refuse_if_frozen(period)


# -- rung 11 --------------------------------------------------------------

def gate_client_active(client_row):
    if client_row is None or client_row["status"] != "ACTIVE":
        fail("ERR_CLIENT_NOT_ACTIVE", "The governing client is not ACTIVE.")
