"""Restaurant lifecycle and menu item management."""

import state


def new_restaurant(name, address, lat, lng, commission_rate_override):
    now = state.now()
    rid = state.gen_id()
    rec = {
        "id": rid,
        "name": name,
        "address": address,
        "lat": lat,
        "lng": lng,
        "commission_rate_override": commission_rate_override,
        "status": "PENDING_APPROVAL",
        "pending_settlement_cents": 0,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    state.STORE.restaurants[rid] = rec
    return rec


def bump(rec):
    rec["updated_at"] = state.now()
    rec["version"] = rec["version"] + 1


def is_name_taken_among_active(name, except_id=None):
    cur = state.STORE.restaurant_names_active.get(name)
    if cur is None:
        return False
    return cur != except_id


def claim_name(name, rid):
    state.STORE.restaurant_names_active[name] = rid


def release_name(name, rid):
    cur = state.STORE.restaurant_names_active.get(name)
    if cur == rid:
        del state.STORE.restaurant_names_active[name]


# Menu items

def new_menu_item(restaurant_id, name, price_cents, is_listed=True):
    now = state.now()
    mid = state.gen_id()
    rec = {
        "id": mid,
        "restaurant_id": restaurant_id,
        "name": name,
        "price_cents": price_cents,
        "is_listed": is_listed,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    state.STORE.menu_items[mid] = rec
    return rec
