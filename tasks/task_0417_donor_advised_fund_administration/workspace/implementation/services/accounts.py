"""DonorAccount derived-balance recomputation and ledger posting.

PRD 2.7: invested_value_cents, committed_grants_cents, grantable_balance_cents are
DERIVED and must be recomputed whenever any input changes, in the same operation.
"""
from db import db, audit_create_fields
from services import calc

GRANT_COMMITTED_STATES = {"SUBMITTED", "APPROVED", "SCHEDULED"}


def active_allocations(account_id):
    """ACTIVE PoolAllocations for an account, in created_at-ascending order."""
    allocs = [a for a in db.allocations.values()
              if a["donor_account_id"] == account_id and a["status"] == "ACTIVE"]
    allocs.sort(key=lambda a: a["_seq"])
    return allocs


def compute_invested_value(account_id):
    """Sum over ACTIVE allocations of round_half_up(units_micro/1e6 * nav) (PRD 2.7/3.4)."""
    total = 0
    for a in active_allocations(account_id):
        pool = db.pools[a["investment_pool_id"]]
        total += calc.allocation_value_cents(a["units_micro"], pool["nav_per_unit_cents"])
    return total


def compute_committed_grants(account_id):
    """Sum of amount_cents over grants in {SUBMITTED, APPROVED, SCHEDULED} (PRD 2.7)."""
    total = 0
    for g in db.grants.values():
        if g["donor_account_id"] == account_id and g["status"] in GRANT_COMMITTED_STATES:
            total += g["amount_cents"]
    return total


def recompute_account(account):
    """Recompute the three derived figures from current inputs (PRD 2.7).

    grantable (SETTLED) = cash + invested - committed - admin_fee_accrued.
    """
    account_id = account["id"]
    account["invested_value_cents"] = compute_invested_value(account_id)
    account["committed_grants_cents"] = compute_committed_grants(account_id)
    account["grantable_balance_cents"] = (
        account["cash_balance_cents"]
        + account["invested_value_cents"]
        - account["committed_grants_cents"]
        - account["admin_fee_accrued_cents"]
    )


def current_quarter_index(account):
    sponsor = db.sponsors[account["sponsor_id"]]
    return sponsor["current_quarter_index"]


def post_ledger(account, entry_type, signed_amount_cents, ref_entity, ref_id):
    """Append a LedgerEntry (PRD 2.7). Append-only audit record: id + created_at only."""
    entry = audit_create_fields()
    entry.update({
        "donor_account_id": account["id"],
        "entry_type": entry_type,
        "signed_amount_cents": signed_amount_cents,
        "ref_entity": ref_entity,
        "ref_id": ref_id,
        "quarter_index": current_quarter_index(account),
    })
    db.ledger_entries[entry["id"]] = entry
    return entry
