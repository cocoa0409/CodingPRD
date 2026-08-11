"""Business logic: mutations, cascades, allocation sweeps, calculations.

Every mutation bumps the resource's version and refreshes updated_at,
including cascade-driven ones.  The wallet invariant is maintained by
recomputing the balance from the ledger after every append.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from store import DB, clock, clock_date, new_id, next_seq
from timestamps import calendar_months, iso3, now_iso, whole_days

SUSPENSION_THRESHOLD_CENTS = 5000
HOLD_WINDOW_HOURS = 72
SANITIZATION_VALIDITY_DAYS = 30
SANITIZATION_MIN_HOURS = 24
LATE_FEE_PER_DAY_CENTS = 150
MAX_DISPUTE_ROUNDS = 2
MAX_PAUSE_DAYS_PER_365 = 60
MIN_BUYOUT_FLOOR_CENTS = 499
MIN_NET_CHARGE_CENTS = 100
GRADE_DEPRECIATION = {"NEW": Decimal("1.0"), "GOOD": Decimal("0.85"),
                      "FAIR": Decimal("0.70"), "WORN": Decimal("0.55")}
RENTAL_CREDIT_PCT_PER_MONTH = Decimal("0.04")
RENTAL_CREDIT_CAP_PCT = Decimal("0.30")
DAMAGE_RATE = {"MINOR": Decimal("0.15"), "MODERATE": Decimal("0.35"), "SEVERE": Decimal("0.75")}
GRADE_ORDER = {"NEW": 0, "GOOD": 1, "FAIR": 2, "WORN": 3}
OPEN_BOX_STATES = {"PLANNED", "SHIPPED", "DELIVERED", "RETURNING", "RECEIVED", "INSPECTED"}


def touch(obj):
    obj["updated_at"] = now_iso()
    obj["version"] += 1


def base_fields():
    return {
        "id": new_id(),
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "version": 1,
        "_seq": next_seq(),
    }


def by_seq(items):
    return sorted(items, key=lambda o: o["_seq"])


def round_half_up(d):
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Wallet ledger + suspension
# ---------------------------------------------------------------------------

def wallet_of(member_id):
    return sum(e["amount_cents"] for e in DB.ledger.values() if e["member_id"] == member_id)


def ledger_append(member_id, amount_cents, reason, note=""):
    entry = {
        "id": new_id(),
        "created_at": now_iso(),
        "_seq": next_seq(),
        "member_id": member_id,
        "amount_cents": amount_cents,
        "reason": reason,
        "note": note or "",
    }
    DB.ledger[entry["id"]] = entry
    _recompute_member_status(member_id)
    return entry


def _recompute_member_status(member_id):
    m = DB.members.get(member_id)
    if not m or m["status"] == "CLOSED":
        return
    w = wallet_of(member_id)
    if m["status"] == "ACTIVE" and w < -SUSPENSION_THRESHOLD_CENTS:
        m["status"] = "SUSPENDED"
        touch(m)
    elif m["status"] == "SUSPENDED" and w >= -SUSPENSION_THRESHOLD_CENTS:
        m["status"] = "ACTIVE"
        touch(m)


# ---------------------------------------------------------------------------
# Lookups / gates
# ---------------------------------------------------------------------------

def active_subscription(member_id):
    for s in DB.subscriptions.values():
        if s["member_id"] == member_id and s["status"] == "ACTIVE":
            return s
    return None


def plan_of(sub):
    return DB.plans.get(sub["plan_id"])


def sanitization_valid(copy):
    if copy["condition_grade"] == "NEW" and copy["last_sanitized_at"] is None:
        return True
    if copy["last_sanitized_at"] is not None:
        return (clock() - copy["last_sanitized_at"]) <= timedelta(days=SANITIZATION_VALIDITY_DAYS)
    return False


def age_gate_passes(member_id, catalog_item):
    today = clock_date()
    for c in DB.children.values():
        if c["member_id"] != member_id:
            continue
        months = calendar_months(c["birthdate"], today)
        if catalog_item["min_age_months"] <= months <= catalog_item["max_age_months"]:
            return True
    return False


def held_count(member_id):
    return sum(
        1 for e in DB.wishlist_entries.values()
        if e["member_id"] == member_id and e["status"] == "HELD"
    )


def member_of_box(box):
    sub = DB.subscriptions.get(box["subscription_id"])
    return sub["member_id"] if sub else None


# ---------------------------------------------------------------------------
# Wishlist allocation sweep
# ---------------------------------------------------------------------------

def _eligible(entry, copy):
    if entry["status"] != "WAITING":
        return False
    if entry["catalog_item_id"] != copy["catalog_item_id"]:
        return False
    sub = active_subscription(entry["member_id"])
    if sub is None:
        return False
    plan = plan_of(sub)
    if plan is None:
        return False
    if held_count(entry["member_id"]) >= plan["max_holds"]:
        return False
    cat = DB.catalog_items.get(copy["catalog_item_id"])
    if cat is None or not age_gate_passes(entry["member_id"], cat):
        return False
    return True


def promote_for_copy(copy):
    """Targeted sweep for one AVAILABLE copy.  Returns the promoted entry or None."""
    if copy["status"] != "AVAILABLE" or not sanitization_valid(copy):
        return None
    candidates = [e for e in DB.wishlist_entries.values() if _eligible(e, copy)]
    if not candidates:
        return None
    candidates.sort(key=lambda e: (e["rank"], e["_seq"]))
    winner = candidates[0]
    winner["status"] = "HELD"
    winner["held_copy_id"] = copy["id"]
    winner["hold_expires_at"] = clock() + timedelta(hours=HOLD_WINDOW_HOURS)
    touch(winner)
    copy["status"] = "RESERVED"
    copy["reserved_member_id"] = winner["member_id"]
    touch(copy)
    return winner


def global_sweep():
    """Promote against every AVAILABLE sanitization-valid copy, created_at ASC."""
    promoted = []
    for copy in by_seq(DB.copies.values()):
        if copy["status"] != "AVAILABLE":
            continue
        winner = promote_for_copy(copy)
        if winner is not None:
            promoted.append(winner)
    return promoted


def release_reserved_copy(copy):
    """RESERVED -> AVAILABLE, clear reservation, fire the targeted sweep.

    Returns the promoted entry when the sweep re-promoted someone.
    """
    copy["status"] = "AVAILABLE"
    copy["reserved_member_id"] = None
    touch(copy)
    return promote_for_copy(copy)


def copy_backs_box_slot(copy_id):
    for it in DB.box_items.values():
        if it["toy_copy_id"] == copy_id and it["loan_status"] == "PENDING_RETURN":
            box = DB.boxes.get(it["rotation_box_id"])
            if box and box["status"] in OPEN_BOX_STATES:
                return True
    return False


def cancel_wishlist_entry(entry, released):
    """WAITING/HELD -> CANCELLED; a HELD entry releases its copy + sweep.

    `released` collects promoted entries from the resulting targeted sweep.
    """
    was_held = entry["status"] == "HELD"
    held_copy_id = entry["held_copy_id"]
    entry["status"] = "CANCELLED"
    entry["held_copy_id"] = None
    touch(entry)
    if was_held and held_copy_id:
        copy = DB.copies.get(held_copy_id)
        if (
            copy is not None
            and copy["status"] == "RESERVED"
            and copy["reserved_member_id"] == entry["member_id"]
            and not copy_backs_box_slot(copy["id"])
        ):
            winner = release_reserved_copy(copy)
            if winner is not None and released is not None:
                released.append(winner)


# ---------------------------------------------------------------------------
# Box / subscription cascades
# ---------------------------------------------------------------------------

def cancel_planned_box(box, released):
    """PLANNED -> CANCELLED; items cancel; reserved copies release + sweep."""
    if box["status"] != "PLANNED":
        return
    box["status"] = "CANCELLED"
    touch(box)
    for it in DB.box_items.values():
        if it["rotation_box_id"] == box["id"] and it["loan_status"] == "PENDING_RETURN":
            it["loan_status"] = "CANCELLED"
            touch(it)
            copy = DB.copies.get(it["toy_copy_id"])
            if copy is not None and copy["status"] == "RESERVED":
                winner = release_reserved_copy(copy)
                if winner is not None and released is not None:
                    released.append(winner)


def cancel_member_wishlist(member_id, released):
    for e in by_seq(DB.wishlist_entries.values()):
        if e["member_id"] == member_id and e["status"] in ("WAITING", "HELD"):
            cancel_wishlist_entry(e, released)


def create_fee(subscription_id, box_item_id, rotation_box_id, fee_type, amount_cents):
    fee = base_fields()
    fee.update({
        "subscription_id": subscription_id,
        "box_item_id": box_item_id,
        "rotation_box_id": rotation_box_id,
        "fee_type": fee_type,
        "amount_cents": amount_cents,
        "status": "INVOICED",
        "dispute_rounds": 0,
    })
    DB.fees[fee["id"]] = fee
    sub = DB.subscriptions.get(subscription_id)
    if sub is not None:
        ledger_append(sub["member_id"], -amount_cents, "FEE_CHARGE")
    return fee


def advance_item_resolution(box_item_id):
    """Item resolution -> RESOLVED once every fee on it is terminal."""
    if box_item_id is None:
        return
    item = DB.box_items.get(box_item_id)
    if item is None:
        return
    fees = [f for f in DB.fees.values() if f["box_item_id"] == box_item_id]
    if fees and all(f["status"] in ("PAID", "WAIVED") for f in fees):
        if item["resolution_status"] != "RESOLVED":
            item["resolution_status"] = "RESOLVED"
            touch(item)


# ---------------------------------------------------------------------------
# Calculations
# ---------------------------------------------------------------------------

def late_fee_cents(box, eval_dt):
    """FINALIZED/projected late fee: whole days late * 150, capped."""
    if box["due_date"] is None:
        return 0
    days_late = max(0, whole_days(box["due_date"], eval_dt))
    raw = days_late * LATE_FEE_PER_DAY_CENTS
    cap = 0
    for it in DB.box_items.values():
        if it["rotation_box_id"] != box["id"]:
            continue
        if it["loan_status"] not in ("PENDING_RETURN", "RETURNED"):
            continue
        copy = DB.copies.get(it["toy_copy_id"])
        if not copy:
            continue
        cat = DB.catalog_items.get(copy["catalog_item_id"])
        if cat:
            cap += cat["replacement_value_cents"]
    return min(raw, cap)


def buyout_price_cents(box, copy, cat):
    snap = box["plan_snapshot"]
    retail = Decimal(cat["retail_value_cents"])
    gross = retail * (Decimal("1") - Decimal(str(snap["buyout_discount_pct"])))
    depreciation = GRADE_DEPRECIATION[copy["condition_grade"]]
    months_rented = calendar_months(box["delivered_at_dt"].date(), clock_date())
    credit_raw = min(
        Decimal(months_rented) * RENTAL_CREDIT_PCT_PER_MONTH * retail,
        RENTAL_CREDIT_CAP_PCT * retail,
    )
    price = round_half_up(gross * depreciation) - round_half_up(credit_raw)
    return max(price, MIN_BUYOUT_FLOOR_CENTS)


def inspection_components(cat, damage_severity, missing_piece_count):
    repl = cat["replacement_value_cents"]
    damage = 0
    if damage_severity != "NONE":
        damage = round_half_up(Decimal(repl) * DAMAGE_RATE[damage_severity])
    missing = 0
    if missing_piece_count > 0:
        missing = round_half_up(
            Decimal(repl) * Decimal(missing_piece_count) / Decimal(cat["piece_count"])
        )
    if damage + missing > repl:
        missing = repl - damage
    return damage, missing
