"""TrustAccount + ledger-entry endpoints (PRD §2.6, §3.9)."""
from flask import Blueprint, request

import serialize
from db import store, new_common, touch
from errors import (
    err,
    ERR_DUPLICATE,
    ERR_INVALID_REQUEST,
    ERR_TRUST_MINIMUM_BREACH,
)
from middleware import auth, get_json_body, lookup, check_version, paginate
from response import object_response, array_response
from services import trust
from util import require_str, require_int, require_enum, opt_int, validate_state_code

bp = Blueprint("trust_accounts", __name__)

READ_ROLES = {"AgencyAdmin", "TrustAccountant"}


@bp.post("/trust-accounts")
def create_trust_account():
    auth({"TrustAccountant"})
    body = get_json_body()
    name = require_str(body, "name")
    state_code = validate_state_code(body.get("state_code"))
    minimum = opt_int(body, "minimum_balance_cents", default=0)
    if minimum < 0:
        raise err(ERR_INVALID_REQUEST, "minimum_balance_cents must be >= 0")
    with store.lock:
        # uniqueness: one trust account per state (§2.8).
        for ta in store.trust_accounts.values():
            if ta["state_code"] == state_code:
                raise err(ERR_DUPLICATE, "trust account already exists for this state")
        rec = new_common()
        rec.update(name=name, state_code=state_code, minimum_balance_cents=minimum)
        store.trust_accounts[rec["id"]] = rec
        return object_response(serialize.trust_account(rec), 201)


@bp.get("/trust-accounts/<tid>")
def get_trust_account(tid):
    auth(READ_ROLES)
    rec = lookup(store.trust_accounts, tid)
    return object_response(serialize.trust_account(rec))


@bp.get("/trust-accounts")
def list_trust_accounts():
    auth(READ_ROLES)
    state_code = request.args.get("state_code")
    recs = [
        t for t in store.trust_accounts.values() if state_code is None or t["state_code"] == state_code
    ]
    page, limit, offset, total = paginate(recs)
    return array_response([serialize.trust_account(t) for t in page], limit, offset, total)


@bp.post("/trust-accounts/<tid>/entries")
def post_entry(tid):
    auth({"TrustAccountant"})
    body = get_json_body()
    with store.lock:
        ta = lookup(store.trust_accounts, tid)  # existence
        entry_type = require_enum(body, "entry_type", trust.ALL_ENTRY_TYPES)
        amount = require_int(body, "amount_cents")
        policy_id = body.get("policy_id")
        if policy_id is not None:
            if not isinstance(policy_id, str):
                raise err(ERR_INVALID_REQUEST, "policy_id must be a string")
            lookup(store.policies, policy_id)

        # sign must agree with type (§2.6).
        if entry_type in trust.POSITIVE_TYPES and amount <= 0:
            raise err(ERR_INVALID_REQUEST, f"{entry_type} amount_cents must be positive")
        if entry_type in trust.NEGATIVE_TYPES and amount >= 0:
            raise err(ERR_INVALID_REQUEST, f"{entry_type} amount_cents must be negative")

        # OCC on TrustAccount.version (§2.9) — before fiscal business check.
        check_version(ta, body.get("expected_trustaccount_version"), "expected_trustaccount_version")

        # fiscal: posting must not drop balance below minimum_balance_cents.
        projected = trust.balance(tid) + amount
        if projected < ta["minimum_balance_cents"]:
            raise err(ERR_TRUST_MINIMUM_BREACH, "posting would breach minimum balance")

        rec = trust.post_entry(tid, entry_type, amount, policy_id=policy_id)
        touch(ta)  # balance recomputes at read; version bumps (§3.9).
        return object_response(serialize.trust_ledger_entry(rec), 201)


@bp.get("/trust-accounts/<tid>/entries")
def list_account_entries(tid):
    auth(READ_ROLES)
    lookup(store.trust_accounts, tid)
    policy_id = request.args.get("policy_id")
    entry_type = request.args.get("entry_type")
    recs = [
        e
        for e in store.trust_ledger_entries.values()
        if e["trust_account_id"] == tid
        and (policy_id is None or e["policy_id"] == policy_id)
        and (entry_type is None or e["entry_type"] == entry_type)
    ]
    page, limit, offset, total = paginate(recs)
    return array_response([serialize.trust_ledger_entry(e) for e in page], limit, offset, total)


@bp.get("/trust-ledger-entries")
def list_entries():
    auth(READ_ROLES)
    policy_id = request.args.get("policy_id")
    trust_account_id = request.args.get("trust_account_id")
    entry_type = request.args.get("entry_type")
    recs = [
        e
        for e in store.trust_ledger_entries.values()
        if (policy_id is None or e["policy_id"] == policy_id)
        and (trust_account_id is None or e["trust_account_id"] == trust_account_id)
        and (entry_type is None or e["entry_type"] == entry_type)
    ]
    page, limit, offset, total = paginate(recs)
    return array_response([serialize.trust_ledger_entry(e) for e in page], limit, offset, total)


@bp.get("/trust-ledger-entries/<eid>")
def get_entry(eid):
    auth(READ_ROLES)
    rec = lookup(store.trust_ledger_entries, eid)
    return object_response(serialize.trust_ledger_entry(rec))
