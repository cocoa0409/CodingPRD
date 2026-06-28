"""Replenishment lifecycle: dispatch / confirm-load / recall (PRD §3.4-§3.7).

Dispatch precondition ladder (priority order — lowest number wins):
  6  ERR_INVALID_STATE         (order not SCHEDULED)         [checked in route]
  13 ERR_ROUTE_PAUSED
  14 ERR_AMOUNT_NOT_DENOMINATED
  15 ERR_ROUTE_WINDOW_CONFLICT
  16 ERR_ATM_SERVICE_LOCKOUT
  17 ERR_VAULT_INSUFFICIENT
  20 ERR_STALE_VERSION

Vault.version is bumped on dispatch and on recall-of-DISPATCHED (the only two
operations that mutate balance/in_transit). confirm-load and close-out do NOT
bump version.
"""
from datetime import timedelta

from constants import ATM_BUFFER_SECONDS
from errors import err
from util import parse_iso
import services.atm as atm_svc
import services.vault as vault_svc

COMMITTED = ("DISPATCHED", "LOADED")


def _half_open_overlap(a_start, a_end, b_start, b_end):
    """Two half-open intervals [a_start,a_end), [b_start,b_end) overlap iff
    a_start < b_end AND b_start < a_end. Touching endpoints do NOT overlap."""
    return a_start < b_end and b_start < a_end


def _closed_buffered_overlap(a_start, a_end, b_start, b_end):
    """ATM lockout: closed intervals expanded by 30 min each side. Adjacency
    (touching) collides; only a gap strictly greater than 30 min is allowed.

    Expand b by the buffer and test closed-interval intersection:
    intersect iff a_start <= b_end+buf AND b_start-buf <= a_end."""
    buf = timedelta(seconds=ATM_BUFFER_SECONDS)
    return a_start <= (b_end + buf) and (b_start - buf) <= a_end


def check_window_conflict(store, order, atm, route):
    a_start = parse_iso(order["service_window_start"])
    a_end = parse_iso(order["service_window_end"])
    for other in store.replenishment_orders.values():
        if other["id"] == order["id"]:
            continue
        if other["status"] not in COMMITTED:
            continue
        if other["route_id"] != order["route_id"]:
            continue
        b_start = parse_iso(other["service_window_start"])
        b_end = parse_iso(other["service_window_end"])
        if _half_open_overlap(a_start, a_end, b_start, b_end):
            raise err("ERR_ROUTE_WINDOW_CONFLICT",
                      "Service window overlaps a committed order on the same route.")


def check_atm_lockout(store, order, atm):
    a_start = parse_iso(order["service_window_start"])
    a_end = parse_iso(order["service_window_end"])
    for other in store.replenishment_orders.values():
        if other["id"] == order["id"]:
            continue
        if other["status"] not in COMMITTED:
            continue
        if other["atm_id"] != order["atm_id"]:
            continue
        b_start = parse_iso(other["service_window_start"])
        b_end = parse_iso(other["service_window_end"])
        if _closed_buffered_overlap(a_start, a_end, b_start, b_end):
            raise err("ERR_ATM_SERVICE_LOCKOUT",
                      "Target ATM has another committed order within the service buffer.")


def dispatch(store, order, atm, route, vault, expected_vault_version):
    # 13 ERR_ROUTE_PAUSED
    if route["status"] != "ACTIVE":
        raise err("ERR_ROUTE_PAUSED", "Route is paused; dispatch is rejected.")
    # 14 ERR_AMOUNT_NOT_DENOMINATED
    note = atm["note_denomination_cents"]
    if note <= 0 or order["order_amount_cents"] % note != 0:
        raise err("ERR_AMOUNT_NOT_DENOMINATED",
                  "order_amount_cents must be a multiple of note_denomination_cents.")
    # 15 ERR_ROUTE_WINDOW_CONFLICT
    check_window_conflict(store, order, atm, route)
    # 16 ERR_ATM_SERVICE_LOCKOUT
    check_atm_lockout(store, order, atm)
    # 17 ERR_VAULT_INSUFFICIENT
    if vault_svc.balance(store, vault) < order["order_amount_cents"]:
        raise err("ERR_VAULT_INSUFFICIENT", "Vault balance is insufficient for this order.")
    # 20 ERR_STALE_VERSION (OCC)
    if expected_vault_version != vault["version"]:
        raise err("ERR_STALE_VERSION", "expected_vault_version does not match the vault version.")

    # Commit. Resolve vault_id, advance order, advance ATM cash.
    # Vault balance/in_transit are DERIVED from order status, so flipping the
    # order to DISPATCHED is what actually moves the cash; the vault row's only
    # stored mutation is the version bump performed by store.touch.
    order["vault_id"] = vault["id"]
    order["expected_vault_version"] = expected_vault_version
    order["status"] = "DISPATCHED"
    store.touch(order)

    # ATM cash dimension: EMPTY/LOW -> AWAITING_LOAD (remember prior for recall).
    if atm["cash_status"] in ("EMPTY", "LOW"):
        atm["_awaiting_prev_cash_status"] = atm["cash_status"]
        atm["cash_status"] = "AWAITING_LOAD"
        store.touch(atm)

    # Bump the vault version exactly once (store.touch increments version).
    store.touch(vault)
    return order


def confirm_load(store, order, atm, allocations):
    # cash leaves in_transit, enters in_machine (both derived from order status).
    order["status"] = "LOADED"
    store.touch(order)

    # Distribute loaded_cents across cassettes.
    cassettes = atm_svc.cassettes_for(store, atm["id"])
    _distribute(store, cassettes, order["order_amount_cents"], allocations)

    # Reset ATM running figures, anchor chronological forecast, advance cash.
    atm["dispensed_cents_since_load"] = 0
    atm["last_confirm_load_at"] = store.clock_now_iso()
    atm["cash_status"] = "LOADED"
    atm.pop("_awaiting_prev_cash_status", None)
    store.touch(atm)
    return order


def _distribute(store, cassettes, total, allocations):
    """Apply loaded_cents to cassettes.

    If `allocations` (a list of {position, loaded_cents} or {cassette_id,...})
    is supplied, honor it. Otherwise put the full order amount on the
    smallest-position cassette (or spread evenly is not specified — the PRD only
    requires ATM.loaded_cents == sum(cassette.loaded_cents) == order amount).
    """
    if allocations:
        by_key = {}
        for c in cassettes:
            by_key[c["position"]] = c
            by_key[c["id"]] = c
        for alloc in allocations:
            key = alloc.get("position") or alloc.get("cassette_id")
            amount = alloc.get("loaded_cents", 0)
            c = by_key.get(key)
            if c is not None:
                c["loaded_cents"] = amount
                c["dispensed_cents"] = 0
                c["balance_status"] = "BALANCED"
                store.touch(c)
        return

    # Default: full amount onto the first cassette; reset the rest.
    for idx, c in enumerate(cassettes):
        c["loaded_cents"] = total if idx == 0 else 0
        c["dispensed_cents"] = 0
        c["balance_status"] = "BALANCED"
        store.touch(c)


def recall(store, order, atm, vault):
    prior_status = order["status"]
    order["status"] = "RECALLED"
    store.touch(order)

    if prior_status == "DISPATCHED" and vault is not None:
        # Compensation: balance/in_transit are derived from order status (now
        # RECALLED, so excluded), so the only stored change is the version bump.
        store.touch(vault)

    # Revert ATM cash_status from AWAITING_LOAD to its prior value if this order
    # drove it there.
    if atm is not None and atm["cash_status"] == "AWAITING_LOAD":
        prev = atm.get("_awaiting_prev_cash_status")
        atm["cash_status"] = prev if prev in ("EMPTY", "LOW") else "EMPTY"
        atm.pop("_awaiting_prev_cash_status", None)
        store.touch(atm)
    return order
