"""Rider lifecycle, metrics, and bonus tier maintenance."""

import compute
import state


def new_rider(name, phone):
    now = state.now()
    rid = state.gen_id()
    rec = {
        "id": rid,
        "name": name,
        "phone": phone,
        "status": "OFFLINE",
        "on_time_rate": 1.0,
        "acceptance_rate": 1.0,
        "rating": 5.0,
        "wallet_balance_cents": 0,
        "bonus_tier": "BRONZE",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    state.STORE.riders[rid] = rec
    state.STORE.rider_phones.add(phone)
    state.STORE.rider_offer_history[rid] = []
    state.STORE.rider_delivery_history[rid] = []
    state.STORE.rider_rating_history[rid] = []
    # initial tier derived from defaults
    rec["bonus_tier"] = compute.bonus_tier(1.0, 1.0, 5.0)
    return rec


def bump(rec):
    rec["updated_at"] = state.now()
    rec["version"] = rec["version"] + 1


def record_offer_outcome(rider_id, accepted):
    """Push the latest offer outcome and trim to the last 30."""
    hist = state.STORE.rider_offer_history.setdefault(rider_id, [])
    hist.append(bool(accepted))
    if len(hist) > 30:
        del hist[0 : len(hist) - 30]


def record_delivery_outcome(rider_id, on_time, rating=None):
    hist = state.STORE.rider_delivery_history.setdefault(rider_id, [])
    hist.append(bool(on_time))
    if len(hist) > 30:
        del hist[0 : len(hist) - 30]
    if rating is not None:
        r_hist = state.STORE.rider_rating_history.setdefault(rider_id, [])
        r_hist.append(float(rating))
        if len(r_hist) > 30:
            del r_hist[0 : len(r_hist) - 30]


def recompute_acceptance_rate(rider):
    hist = state.STORE.rider_offer_history.get(rider["id"], [])
    if not hist:
        rate = 1.0
    else:
        rate = sum(1 for x in hist if x) / float(len(hist))
    rider["acceptance_rate"] = max(0.0, min(1.0, rate))


def recompute_on_time_rate(rider):
    hist = state.STORE.rider_delivery_history.get(rider["id"], [])
    if len(hist) < 10:
        rate = 1.0
    else:
        rate = sum(1 for x in hist if x) / float(len(hist))
    rider["on_time_rate"] = max(0.0, min(1.0, rate))


def recompute_rating(rider):
    hist = state.STORE.rider_rating_history.get(rider["id"], [])
    if not hist:
        return
    rider["rating"] = sum(hist) / float(len(hist))


def recompute_bonus_tier(rider):
    rider["bonus_tier"] = compute.bonus_tier(
        rider["on_time_rate"], rider["acceptance_rate"], rider["rating"]
    )


def rider_has_blocking_assignments(rider_id):
    for a in state.STORE.assignments.values():
        if a["rider_id"] == rider_id and a["status"] in (
            "OFFERED", "ACCEPTED", "PICKED_UP",
        ):
            return True
    return False
