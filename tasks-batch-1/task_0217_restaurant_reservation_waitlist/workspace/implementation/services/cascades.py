"""Cascade families (PRD §2.7, §3.2, §3.5, §3.8).

  * table-freeing cascade -> re-run waitlist promotion (notify next party)
  * fiscal cascade -> strike, recompute reliability, auto-block + mass-cancel
  * buyout cascade -> cancel colliding reservations + release their holds
"""
import clock
import db
from services import calc
from services.notifications import create_notification


# ---- reliability -------------------------------------------------------------

def recompute_reliability(customer):
    customer["settled_reliability_pct"] = calc.settled_reliability(
        customer["lifetime_reservations"], customer["lifetime_failures"]
    )


# ---- waitlist promotion (table-freeing cascade) ------------------------------

def _available_table_fits(restaurant_id, party_size):
    """True if some AVAILABLE table in the restaurant fits party_size."""
    return _find_available_table(restaurant_id, party_size) is not None


def _find_available_table(restaurant_id, party_size):
    # Tables belong to dining areas which belong to a restaurant.
    area_ids = {a["id"] for a in db.dining_areas.values()
                if a["restaurant_id"] == restaurant_id}
    for t in db.tables.values():
        if t["dining_area_id"] not in area_ids:
            continue
        if t["status"] != "AVAILABLE":
            continue
        if t["min_party_size"] <= party_size <= t["max_party_size"]:
            return t
    return None


def promotion_winner(restaurant_id):
    """Lowest (notify_count, joined_at) among WAITING entries whose party_size
    fits some AVAILABLE table; joined_at tie-break, never id (PRD §3.8)."""
    candidates = []
    for w in db.waitlist_entries.values():
        if w["status"] != "WAITING":
            continue
        if w["restaurant_id"] != restaurant_id:
            continue
        if not _available_table_fits(restaurant_id, w["party_size"]):
            continue
        candidates.append(w)
    if not candidates:
        return None
    candidates.sort(key=lambda w: (w["notify_count"], w["joined_at"], w["_seq"]))
    return candidates[0]


def notify_entry(entry, customer):
    """Apply WAITING -> NOTIFIED side effects (PRD §3.8)."""
    entry["status"] = "NOTIFIED"
    entry["notify_expires_at"] = clock.now() + __import__("datetime").timedelta(
        minutes=calc.NOTIFY_TTL_MINUTES)
    db.touch(entry)
    create_notification(
        subject_type="WAITLIST_ENTRY",
        subject_id=entry["id"],
        template="WAITLIST_TABLE_READY",
        to_phone=customer["phone"],
    )


def run_table_freeing_cascade(restaurant_id):
    """Promote and notify the next eligible waitlist party, if any."""
    winner = promotion_winner(restaurant_id)
    if winner is None:
        return None
    customer = db.customers.get(winner["customer_id"])
    if customer is None:
        return None
    notify_entry(winner, customer)
    return winner


# ---- fiscal cascade ----------------------------------------------------------

def accrue_failure_and_maybe_block(customer, restaurant):
    """Increment strikes + lifetime_failures, recompute reliability, and
    auto-block at the threshold (PRD §3.5)."""
    customer["no_show_strikes"] += 1
    customer["lifetime_failures"] += 1
    recompute_reliability(customer)
    db.touch(customer)
    if customer["no_show_strikes"] >= restaurant["no_show_strike_block_threshold"]:
        block_customer(customer, restaurant)


def block_customer(customer, restaurant):
    """Set BLOCKED and mass-cancel the customer's future REQUESTED/CONFIRMED
    reservations, releasing their HELD holds (PRD §3.2)."""
    if customer["status"] == "BLOCKED":
        return
    customer["status"] = "BLOCKED"
    db.touch(customer)
    now = clock.now()
    for res in list(db.reservations.values()):
        if res["customer_id"] != customer["id"]:
            continue
        if res["status"] not in ("CONFIRMED", "REQUESTED"):
            continue
        if res["reservation_start"] is None or res["reservation_start"] <= now:
            continue
        # block-cancel is treated as early -> fee 0
        res["cancellation_fee_cents"] = 0
        res["status"] = "CANCELLED"
        db.touch(res)
        _release_held_hold(res["id"])
        _free_table_after_cancel(res)


def _release_held_hold(reservation_id):
    for hold in db.deposit_holds.values():
        if hold["reservation_id"] == reservation_id and hold["status"] == "HELD":
            hold["captured_cents"] = 0
            hold["status"] = "RELEASED"
            db.touch(hold)


def _free_table_after_cancel(res):
    """Free the future slot and run the table-freeing cascade unless the table
    is currently SEATED (PRD §3.6)."""
    table = db.tables.get(res["table_id"]) if res["table_id"] else None
    if table is not None and table["status"] == "SEATED":
        return
    run_table_freeing_cascade(res["restaurant_id"])


# ---- buyout cascade ----------------------------------------------------------

def run_buyout_cascade(event):
    """Cancel CONFIRMED/REQUESTED reservations whose window intersects the
    buyout window on this dining area, releasing their HELD holds (PRD §3.4)."""
    area_id = event["dining_area_id"]
    table_ids = {t["id"] for t in db.tables.values()
                 if t["dining_area_id"] == area_id}
    for res in list(db.reservations.values()):
        if res["table_id"] not in table_ids:
            continue
        if res["status"] not in ("CONFIRMED", "REQUESTED"):
            continue
        if res["reservation_start"] is None or res["release_at"] is None:
            continue
        # reservation window half-open [start, release); buyout window closed
        # [event_start, event_end].
        if res["reservation_start"] <= event["event_end"] and event["event_start"] < res["release_at"]:
            res["status"] = "CANCELLED"
            db.touch(res)
            _release_held_hold(res["id"])
