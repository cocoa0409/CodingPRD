"""Entity existence lookups that raise the correct not-found ApiError."""
from common import ApiError
from store import STORE


def _get(coll, _id, err):
    ent = coll.get(_id)
    if ent is None:
        raise ApiError(err, 404, f"{err.replace('ERR_', '').replace('_NOT_FOUND', '').title()} not found.")
    return ent


def holder(_id):
    return _get(STORE.holders, _id, "ERR_HOLDER_NOT_FOUND")


def property_type(_id):
    return _get(STORE.property_types, _id, "ERR_PROPERTY_TYPE_NOT_FOUND")


def state_account(_id):
    return _get(STORE.state_accounts, _id, "ERR_STATE_ACCOUNT_NOT_FOUND")


def owner(_id):
    return _get(STORE.owners, _id, "ERR_OWNER_NOT_FOUND")


def recovery_firm(_id):
    return _get(STORE.recovery_firms, _id, "ERR_FIRM_NOT_FOUND")


def prop(_id):
    return _get(STORE.properties, _id, "ERR_PROPERTY_NOT_FOUND")


def notice(_id):
    return _get(STORE.notices, _id, "ERR_NOTICE_NOT_FOUND")


def report(_id):
    return _get(STORE.reports, _id, "ERR_REPORT_NOT_FOUND")


def claim(_id):
    return _get(STORE.claims, _id, "ERR_CLAIM_NOT_FOUND")


def evidence(_id):
    return _get(STORE.evidence, _id, "ERR_EVIDENCE_NOT_FOUND")


def audit_case(_id):
    return _get(STORE.audit_cases, _id, "ERR_AUDIT_NOT_FOUND")


def ledger_entry(_id):
    return _get(STORE.ledger, _id, "ERR_LEDGER_NOT_FOUND")


def find_state_account_by_code(code):
    for acc in STORE.state_accounts.values():
        if acc.get("state_code") == code:
            return acc
    return None
