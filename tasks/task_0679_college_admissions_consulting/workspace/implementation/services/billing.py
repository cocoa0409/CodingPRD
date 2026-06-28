"""BillingEntry append helper. BillingEntry is append-only (id + created_at only)."""
from db import store
from common import make_entity
from services.calculations import recompute_contract_balances


def append_billing_entry(contract, entry_type, source_kind, amount_cents,
                         source_id=None, minutes=0, memo="", recompute=True):
    """Append a BillingEntry to the contract. Returns the entry row.

    BillingEntry carries only id + created_at (no updated_at/version) per PRD §2.4.
    """
    entry = make_entity(has_version=False)
    entry.update({
        "contract_id": contract["id"],
        "entry_type": entry_type,
        "source_kind": source_kind,
        "source_id": source_id,
        "amount_cents": amount_cents,
        "minutes": minutes,
        "memo": memo,
    })
    store.billing_entries[entry["id"]] = entry
    if recompute:
        # Recompute the owning contract's balances. The contract is itself a
        # mutation target (timestamps/version) when balances change — but ledger
        # appends already represent a contract-level event, so we always touch.
        from common import touch
        recompute_contract_balances(contract)
        touch(contract)
    return entry


def serialize_billing_entry(e):
    return {
        "id": e["id"],
        "contract_id": e["contract_id"],
        "entry_type": e["entry_type"],
        "source_kind": e["source_kind"],
        "source_id": e["source_id"],
        "amount_cents": e["amount_cents"],
        "minutes": e["minutes"],
        "memo": e["memo"],
        "created_at": e["created_at"],
    }
