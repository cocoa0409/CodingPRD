"""ATM derived-field computation and lookups.

loaded_cents               = sum(cassette.loaded_cents) for the ATM's cassettes
dispensed_cents_since_load = stored on the ATM, reset at confirm-load, bumped
                             per withdrawal (PRD §3.6).
"""


def cassettes_for(store, atm_id):
    """All cassettes for an ATM, ordered by physical position C1<C2<C3<C4."""
    cs = [c for c in store.cassettes.values() if c["atm_id"] == atm_id]
    cs.sort(key=lambda c: c["position"])
    return cs


def loaded_cents(store, atm):
    total = 0
    for c in store.cassettes.values():
        if c["atm_id"] == atm["id"]:
            total += c["loaded_cents"]
    return total


def derived(store, atm):
    return {
        "loaded_cents": loaded_cents(store, atm),
        "dispensed_cents_since_load": atm["dispensed_cents_since_load"],
    }


def remaining_cents(store, atm):
    """loaded_cents - dispensed_cents_since_load (PRD §3.6 low watermark / recon)."""
    return loaded_cents(store, atm) - atm["dispensed_cents_since_load"]
