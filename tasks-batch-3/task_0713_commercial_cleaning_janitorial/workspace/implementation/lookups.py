"""Path / FK resolution helpers (PRD §2.5 left-to-right existence)."""
from db import db
from errors import err


def get_account(account_id):
    rec = db.get("Account", account_id)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Account not found")
    return rec


def get_child(kind, rid, parent_field=None, parent_id=None, label=None):
    rec = db.get(kind, rid)
    if rec is None:
        raise err("ERR_NOT_FOUND", "%s not found" % (label or kind))
    if parent_field is not None and rec.get(parent_field) != parent_id:
        raise err("ERR_NOT_FOUND", "%s not found under parent" % (label or kind))
    return rec


def get_fk(kind, rid, label=None):
    """Resolve a foreign-key id from a request body; 404 if missing (PRD §2.5)."""
    if rid is None:
        raise err("ERR_INVALID_REQUEST", "Missing required field id")
    rec = db.get(kind, rid)
    if rec is None:
        raise err("ERR_NOT_FOUND", "%s not found" % (label or kind))
    return rec


# --- nested chain resolvers (validate left to right) ---
def acct_rfp(account_id, rfp_id):
    get_account(account_id)
    rfp = get_child("RfpOpportunity", rfp_id, "account_id", account_id, "RFP")
    return rfp


def acct_contract(account_id, contract_id):
    get_account(account_id)
    return get_child("CleaningContract", contract_id, "account_id", account_id, "Contract")
