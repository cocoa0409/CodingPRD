"""Resource existence resolution and ownership enforcement.

Existence is checked left-to-right; the first missing reference raises
ERR_NOT_FOUND (PRD 2.6, validation priority 3). Ownership checks for the two
entity-backed roles (Employer, CustodialParty) are applied on reads (PRD 2.1).
Ownership failures surface as ERR_NOT_FOUND so that callers cannot probe for the
existence of records they do not own.
"""

import errors
from db import store


def get_or_404(collection, rid):
    rec = collection.get(rid)
    if rec is None:
        raise errors.not_found()
    return rec


# --- typed getters -----------------------------------------------------------
def custodial_party(rid):
    return get_or_404(store.custodial_parties, rid)


def noncustodial_party(rid):
    return get_or_404(store.noncustodial_parties, rid)


def employer(rid):
    return get_or_404(store.employers, rid)


def support_order(rid):
    return get_or_404(store.support_orders, rid)


def iwo(rid):
    return get_or_404(store.income_withholding_orders, rid)


def remittance(rid):
    return get_or_404(store.remittances, rid)


def allocation(rid):
    return get_or_404(store.allocations, rid)


def ledger_entry(rid):
    return get_or_404(store.ledger_entries, rid)


def disbursement(rid):
    return get_or_404(store.disbursements, rid)


def modification(rid):
    return get_or_404(store.modifications, rid)


def enforcement_action(rid):
    return get_or_404(store.enforcement_actions, rid)


# --- ownership filters (entity-backed roles) ---------------------------------
def owns_employer(auth, emp):
    return auth.role != "Employer" or emp["id"] == auth.user_id


def owns_custodial_party(auth, cp):
    return auth.role != "CustodialParty" or cp["id"] == auth.user_id


def owns_order(auth, order):
    """CustodialParty may read orders that name them as payee."""
    return auth.role != "CustodialParty" or order["custodial_party_id"] == auth.user_id


def owns_iwo(auth, iwo_rec):
    return auth.role != "Employer" or iwo_rec["employer_id"] == auth.user_id


def owns_remittance(auth, rem):
    return auth.role != "Employer" or rem["employer_id"] == auth.user_id


def owns_disbursement(auth, disb):
    return auth.role != "CustodialParty" or disb["custodial_party_id"] == auth.user_id


def require(cond):
    if not cond:
        raise errors.not_found()
