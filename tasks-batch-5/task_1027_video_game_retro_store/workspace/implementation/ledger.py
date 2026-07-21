"""Store-credit ledger (PRD 2.8). The append-only StoreCreditEntry rows are the
single source of truth for a member's balance; the balance is recomputed from
the full ledger after every write."""
import store


def add_entry(member_id, amount_cents, reason, related_ref):
    entry = store.make_ledger_entry({
        "member_id": member_id,
        "amount_cents": amount_cents,
        "reason": reason,
        "related_ref": related_ref,
    })
    store.store_credit_entries[entry["id"]] = entry
    return entry


def recompute_balance(member):
    total = sum(
        e["amount_cents"]
        for e in store.store_credit_entries.values()
        if e["member_id"] == member["id"]
    )
    member["store_credit_balance_cents"] = total
    store.touch(member)
    return total
