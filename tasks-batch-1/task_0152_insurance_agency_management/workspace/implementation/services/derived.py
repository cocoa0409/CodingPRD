"""Derived / computed field helpers (read-time computation).

License.status, Account.active_policy_count, TrustAccount.balance_cents, and
the OPEN CommissionStatement live figures are all computed against current state
rather than stored as authoritative mutable fields.
"""
import clock
from db import store
from util import parse_dt


def license_status(lic):
    """Computed validity at server-now (PRD §3.2).

    ACTIVE when effective_date <= now < expiration_date;
    EXPIRED when now >= expiration_date;
    PENDING when now < effective_date.
    """
    now = clock.now()
    eff = parse_dt(lic["effective_date"], "effective_date")
    exp = parse_dt(lic["expiration_date"], "expiration_date")
    if now < eff:
        return "PENDING"
    if now >= exp:
        return "EXPIRED"
    return "ACTIVE"


def active_policy_count(account_id):
    """Count of policies under the account whose status IN {ACTIVE, PENDING_RENEWAL}."""
    n = 0
    for p in store.policies.values():
        if p["account_id"] == account_id and p["status"] in ("ACTIVE", "PENDING_RENEWAL"):
            n += 1
    return n


def trust_balance(trust_account_id):
    """Sum of amount_cents of every ledger entry posted to the account."""
    total = 0
    for e in store.trust_ledger_entries.values():
        if e["trust_account_id"] == trust_account_id:
            total += e["amount_cents"]
    return total


def has_active_license(producer_id, state_code, line_of_business=None):
    """True if the producer holds a license whose computed status is ACTIVE
    matching state_code (and line_of_business when given)."""
    for lic in store.licenses.values():
        if lic["producer_id"] != producer_id:
            continue
        if lic["state_code"] != state_code:
            continue
        if line_of_business is not None and lic["line_of_business"] != line_of_business:
            continue
        if license_status(lic) == "ACTIVE":
            return True
    return False


def has_active_appointment(producer_id, carrier_id, state_code):
    """True if an ACTIVE appointment exists for (producer, carrier, state)."""
    for appt in store.appointments.values():
        if (
            appt["producer_id"] == producer_id
            and appt["carrier_id"] == carrier_id
            and appt["state_code"] == state_code
            and appt["status"] == "ACTIVE"
        ):
            return True
    return False
