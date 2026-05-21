"""Customer account creation and helpers."""

import state


def new_customer(name, phone, address, lat, lng):
    now = state.now()
    cid = state.gen_id()
    rec = {
        "id": cid,
        "name": name,
        "phone": phone,
        "address": address,
        "lat": lat,
        "lng": lng,
        "credit_balance_cents": 0,
        "trust_score": 1.0,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    state.STORE.customers[cid] = rec
    state.STORE.customer_phones.add(phone)
    return rec


def bump(rec):
    rec["updated_at"] = state.now()
    rec["version"] = rec["version"] + 1


def adjust_trust(rec, delta):
    new_val = rec["trust_score"] + delta
    new_val = max(0.0, min(1.0, new_val))
    rec["trust_score"] = new_val
