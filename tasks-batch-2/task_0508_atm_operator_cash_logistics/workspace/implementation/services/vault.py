"""Vault cash-position derivation + conservation invariant (PRD §2.7, §1.3).

in_transit_cents = sum(order_amount_cents for DISPATCHED orders on this vault)
in_machine_cents = sum(order_amount_cents for LOADED orders on this vault)
balance_cents    = provisioned_cents - in_transit_cents - in_machine_cents

PRD §2.7: "the sum of the vault's on-hand `balance_cents`, its `in_transit_cents`,
and its `in_machine_cents` equals `provisioned_cents`" — at all times, conserved
forever, with every dispatch/load/recall/close-out adjusting two buckets in equal
and opposite amounts. There is no fourth "reconciled out" subtraction from balance:
at close-out the LOADED order leaves the in_machine bucket (it is no longer "loaded
but not yet reconciled out"), and by the §2.7 formula that cash returns to on-hand
balance, conserving the total. SETTLED orders therefore contribute to none of the
three buckets, exactly like RECALLED orders, so balance = provisioned - in_transit
- in_machine alone.

These are computed from the live replenishment-order set rather than stored, so
the ledger can never drift. dispatch/recall additionally bump Vault.version (the
OCC token) — see services.replenishment.
"""


def position(store, vault):
    in_transit = 0
    in_machine = 0
    vid = vault["id"]
    for order in store.replenishment_orders.values():
        if order.get("vault_id") != vid:
            continue
        status = order["status"]
        if status == "DISPATCHED":
            in_transit += order["order_amount_cents"]
        elif status == "LOADED":
            in_machine += order["order_amount_cents"]
    balance = vault["provisioned_cents"] - in_transit - in_machine
    return {
        "balance_cents": balance,
        "in_transit_cents": in_transit,
        "in_machine_cents": in_machine,
    }


def balance(store, vault):
    return position(store, vault)["balance_cents"]
