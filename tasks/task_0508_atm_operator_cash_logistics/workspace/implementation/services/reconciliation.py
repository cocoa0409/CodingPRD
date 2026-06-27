"""Cash count (open) + close-out reconciliation (PRD §3.6, SCAFFOLD §1.3).

Open cash-count (LOADED/LOW -> RECONCILING):
  expected_remaining_cents = loaded_cents - dispensed_cents_since_load
  variance_cents = counted_cents - expected_remaining_cents
  outcome = BALANCED if abs(variance) <= tolerance
            else OVER (variance > 0) / SHORT (variance < 0)
  Each cassette's balance_status is set to the outcome.

Close-out (RECONCILING -> EMPTY) cascade:
  cassette.loaded_cents := loaded_cents - dispensed_cents ; cassette.dispensed_cents := 0
  ATM.cash_status := EMPTY
  the ATM's LOADED ReplenishmentOrder -> SETTLED ; vault in_machine drops (derived)
"""
import services.atm as atm_svc


def open_count(store, atm, counted_cents, tolerance_cents):
    expected = atm_svc.loaded_cents(store, atm) - atm["dispensed_cents_since_load"]
    variance = counted_cents - expected
    if abs(variance) <= tolerance_cents:
        outcome = "BALANCED"
    elif variance > 0:
        outcome = "OVER"
    else:
        outcome = "SHORT"

    count = {
        "atm_id": atm["id"],
        "counted_cents": counted_cents,
        "expected_remaining_cents": expected,
        "variance_cents": variance,
        "outcome": outcome,
        "tolerance_cents": tolerance_cents,
    }
    store.stamp_new(count)
    store.cash_counts[count["id"]] = count

    # ATM moves to RECONCILING; set each cassette's balance_status to outcome.
    atm["cash_status"] = "RECONCILING"
    store.touch(atm)
    for c in atm_svc.cassettes_for(store, atm["id"]):
        c["balance_status"] = outcome
        store.touch(c)
    return count


def close_out(store, atm, count):
    # Reduce each cassette's loaded_cents to its expected remaining; reset dispensed.
    for c in atm_svc.cassettes_for(store, atm["id"]):
        c["loaded_cents"] = c["loaded_cents"] - c["dispensed_cents"]
        c["dispensed_cents"] = 0
        store.touch(c)

    atm["cash_status"] = "EMPTY"
    atm["dispensed_cents_since_load"] = 0
    store.touch(atm)

    # Cascade: the ATM's currently LOADED order -> SETTLED (frees vault in_machine,
    # which is derived from order status).
    for order in store.replenishment_orders.values():
        if order["atm_id"] == atm["id"] and order["status"] == "LOADED":
            order["status"] = "SETTLED"
            store.touch(order)
            vault = store.vaults.get(order.get("vault_id"))
            if vault is not None:
                store.touch(vault)
            break

    store.touch(count)
    return count
