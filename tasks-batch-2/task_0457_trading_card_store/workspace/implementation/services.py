"""Cross-cutting domain services: lookups, ledger, balance reconciliation.

PRD §2.8: store credit is the single settlement instrument. Every movement of
credit appends one row to the append-only ledger; the balance is always the
running sum of that customer's rows in creation order. Appending a row
recomputes store_credit_balance_cents and advances the customer's updated_at and
version.

PRD §3.1: lifetime_spend_cents = sum of negated delta_cents over EVENT_CHARGE +
PREORDER_FULFILL rows only. loyalty_tier re-derived whenever lifetime spend
changes.
"""

import calculations as calc
import common
import db
from errors import err


# ----------------------------------------------------------------------------
# Existence lookups (PRD §2.4: ERR_NOT_FOUND when a referenced resource is
# absent). Path identifiers are validated left to right by callers.
# ----------------------------------------------------------------------------

def find_or_404(store, entity_id):
    ent = store.get(entity_id)
    if ent is None:
        raise err("ERR_NOT_FOUND", "Resource not found")
    return ent


def get_customer(cid):
    return find_or_404(db.customers, cid)


def get_inventory_item(iid):
    return find_or_404(db.inventory_items, iid)


# ----------------------------------------------------------------------------
# Ledger + balance reconciliation
# ----------------------------------------------------------------------------

# reasons that count toward lifetime spend (PRD §3.1).
SPEND_REASONS = {"EVENT_CHARGE", "PREORDER_FULFILL"}


def append_ledger(customer, delta_cents, reason, source_entity_id=None):
    """Append a ledger row (id + created_at only — PRD §2.5) and recompute the
    owning customer's balance / lifetime spend / tier (PRD §2.8, §3.1)."""
    row = {
        "id": db.new_id(),
        "created_at": db.now_iso(),
        "customer_id": customer["id"],
        "delta_cents": delta_cents,
        "reason": reason,
        "source_entity_id": source_entity_id,
        "_seq": db.next_seq(),
    }
    db.ledger_rows[row["id"]] = row
    recompute_customer(customer)
    return row


def recompute_customer(customer):
    """Recompute store_credit_balance_cents, lifetime_spend_cents, loyalty_tier
    from the customer's ledger rows in creation order, then touch the customer
    (this recomputation is itself a mutation — PRD §2.5)."""
    rows = [r for r in db.ledger_rows.values() if r["customer_id"] == customer["id"]]
    rows.sort(key=lambda r: r["_seq"])
    balance = sum(r["delta_cents"] for r in rows)
    spend = sum(-r["delta_cents"] for r in rows if r["reason"] in SPEND_REASONS)
    customer["store_credit_balance_cents"] = balance
    customer["lifetime_spend_cents"] = spend
    customer["loyalty_tier"] = calc.loyalty_tier(spend)
    common.touch(customer)
