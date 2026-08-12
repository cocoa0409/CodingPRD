"""Derived-field computations and recomputes.

These recompute:
- TrustAccount.balance_cents from ledger entries
- Client.total_funds_cents / countable_resources_cents / medicaid_at_risk
- SuretyBond.funds_under_management_cents / utilization_bps
"""

from db import store


def account_balance(account_id):
    total = 0
    for entry_id in store.ledger_order:
        e = store.ledger_entries[entry_id]
        if e["account_id"] == account_id:
            total += e["amount_cents"]
    return total


def recompute_account_balance(account_id):
    acct = store.accounts.get(account_id)
    if not acct:
        return
    acct["balance_cents"] = account_balance(account_id)


def recompute_client_rollups(client_id):
    c = store.clients.get(client_id)
    if not c:
        return
    total = 0
    countable = 0
    for acct in store.accounts.values():
        if acct["client_id"] != client_id:
            continue
        if acct["status"] not in ("OPEN", "FROZEN"):
            continue
        bal = acct.get("balance_cents", 0)
        total += bal
        if acct["account_type"] in ("OPERATING", "RESTRICTED"):
            countable += bal
    c["total_funds_cents"] = total
    c["countable_resources_cents"] = countable
    limit = c.get("medicaid_resource_limit_cents") or 200000
    c["medicaid_at_risk"] = bool(c.get("medicaid_enrolled")) and (countable > limit)


def recompute_bond_rollups():
    fum = 0
    for acct in store.accounts.values():
        if acct["status"] in ("OPEN", "FROZEN"):
            fum += acct.get("balance_cents", 0)
    for bond in store.bonds.values():
        bond["funds_under_management_cents"] = fum
        cov = bond["coverage_amount_cents"]
        bond["utilization_bps"] = (fum * 10000) // cov if cov else 0


def recompute_all_for_client(client_id):
    """Recompute all accounts of client + client rollups + bond rollups."""
    for acct in store.accounts.values():
        if acct["client_id"] == client_id:
            recompute_account_balance(acct["id"])
    recompute_client_rollups(client_id)
    recompute_bond_rollups()


def append_ledger(account_id, entry_type, amount_cents, reference_id, created_at):
    """Append a ledger entry; balance_after_cents = running balance after."""
    from util import new_id
    eid = new_id()
    new_balance = account_balance(account_id) + amount_cents
    entry = {
        "id": eid,
        "account_id": account_id,
        "entry_type": entry_type,
        "amount_cents": amount_cents,
        "reference_id": reference_id,
        "balance_after_cents": new_balance,
        "created_at": created_at,
    }
    store.ledger_entries[eid] = entry
    store.ledger_order.append(eid)
    recompute_account_balance(account_id)
    return entry
