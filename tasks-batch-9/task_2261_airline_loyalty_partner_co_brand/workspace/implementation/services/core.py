"""Shared row plumbing: creation, versioning, serialisation, derived counters
and the cascade helpers used by more than one route module."""

import calendar
from datetime import date, datetime, timedelta, timezone

from flask import g

import calc
from db import new_id, store
from errors import fail
from response import iso_ms

# --------------------------------------------------------------------------
# Clock
# --------------------------------------------------------------------------


def now():
    """The logical clock -- the sole source of 'now' for business decisions."""
    return store.clock


def today():
    return store.clock.date()


def at_midnight(d):
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)


def pdate(text):
    return date(int(text[0:4]), int(text[5:7]), int(text[8:10]))


def dstr(d):
    return "%04d-%02d-%02d" % (d.year, d.month, d.day)


# --------------------------------------------------------------------------
# Row lifecycle
# --------------------------------------------------------------------------


def base_row(versioned=True):
    """A brand-new row's common fields.  `created_at`/`updated_at` are wall
    clock stamps; `_seq` gives a stable total order for 'created_at ASC'."""
    stamp = datetime.now(timezone.utc)
    row = {"id": new_id()}
    row["_created"] = stamp
    row["_seq"] = store.next_seq()
    if versioned:
        row["_versioned"] = True
    return row


def finish_row(row):
    """Append the common trailing fields in their canonical order."""
    row["created_at"] = iso_ms(row["_created"])
    if row.get("_versioned"):
        row["updated_at"] = row["created_at"]
        row["version"] = 1
    return row


def touch(row):
    """Refresh updated_at and increment version -- at most once per request."""
    if not row.get("_versioned"):
        return row
    seen = getattr(g, "_touched", None)
    if seen is None:
        seen = set()
        g._touched = seen
    key = id(row)
    if key in seen:
        return row
    seen.add(key)
    row["version"] = row.get("version", 1) + 1
    row["updated_at"] = iso_ms(datetime.now(timezone.utc))
    return row


def dump(row):
    """Public JSON view: drop internal keys, render datetimes."""
    out = {}
    for key, value in row.items():
        if key.startswith("_"):
            continue
        if isinstance(value, datetime):
            out[key] = iso_ms(value)
        else:
            out[key] = value
    return out


def dump_all(rows):
    return [dump(r) for r in rows]


# --------------------------------------------------------------------------
# Lookup / listing
# --------------------------------------------------------------------------


def find(table, row_id, error_id):
    if not isinstance(row_id, str):
        fail(error_id, "not found")
    row = table.get(row_id)
    if row is None:
        fail(error_id, "not found")
    return row


def fk(table, body, field, error_id, required=False):
    """Resolve a body-supplied foreign key (ladder rung 6)."""
    if field not in body or body[field] is None:
        if required:
            fail("ERR_INVALID_REQUEST", "%s is required" % field)
        return None
    return find(table, body[field], error_id)


def ordered(table):
    return sorted(table.values(), key=lambda r: r["_seq"])


def paginate(rows, limit, offset):
    total = len(rows)
    return rows[offset:offset + limit], total


# --------------------------------------------------------------------------
# Scope checks (ladder rungs 3 and 4)
# --------------------------------------------------------------------------


def member_scope(caller, member_id):
    if caller.is_member and member_id != caller.user_id:
        fail("ERR_MEMBER_SCOPE_VIOLATION", "members may act only on their own records")


def issuer_scope(caller, issuer_id):
    if caller.is_issuer_rep and issuer_id != caller.user_id:
        fail("ERR_ISSUER_SCOPE_VIOLATION", "issuer may act only on its own agreements")


# --------------------------------------------------------------------------
# Programme / period helpers
# --------------------------------------------------------------------------


def program_of(row):
    return store.programs[row["program_id"]]


def program_of_member(member):
    return store.programs[member["program_id"]]


def require_not_locked(program):
    if program["revenue_recognition_state"] == "LOCKED":
        fail("ERR_PERIOD_LOCKED", "the accounting period is locked")


def require_member_normal(member):
    if member["security_state"] != "NORMAL":
        fail("ERR_MEMBER_FROZEN", "the member account is not in NORMAL security state")


def next_period(period):
    year = int(period[0:4])
    month = int(period[5:7])
    month += 1
    if month == 13:
        month = 1
        year += 1
    return "%04d-%02d" % (year, month)


def trailing_window(period):
    """The 24 calendar months ending on the last day of `period`, inclusive."""
    year = int(period[0:4])
    month = int(period[5:7])
    end = date(year, month, calendar.monthrange(year, month)[1])
    total = year * 12 + (month - 1) - (calc.BREAKAGE_TRAILING_MONTHS - 1)
    start = date(total // 12, total % 12 + 1, 1)
    return start, end


# --------------------------------------------------------------------------
# Derived counters
# --------------------------------------------------------------------------


def recompute_window(window):
    """Refresh the three derived posture fields; returns True when any moved."""
    load = calc.load_factor_bps(
        window["authorized_seats"], window["seats_held"], window["seats_confirmed"])
    demand = calc.demand_multiplier_bps(load)
    state = calc.capacity_control_state(load)
    changed = (window["load_factor_bps"] != load
               or window["demand_multiplier_bps"] != demand
               or window["capacity_control_state"] != state)
    window["load_factor_bps"] = load
    window["demand_multiplier_bps"] = demand
    window["capacity_control_state"] = state
    return changed


def release_seats(booking):
    """Give a HELD booking's seats back to its window and re-posture it."""
    window = store.windows.get(booking["window_id"])
    if window is None:
        return None
    window["seats_held"] -= booking["seats"]
    if booking["fare_class"] == "SAVER":
        window["saver_seats_consumed"] -= booking["seats"]
    recompute_window(window)
    touch(window)
    return window


def recompute_issuer_aggregate(issuer):
    total = 0
    for agreement in store.agreements.values():
        if agreement["issuer_id"] == issuer["id"] and agreement["status"] in ("RATIFIED", "ACTIVE"):
            total += agreement["committed_volume_miles"]
    if issuer["aggregate_committed_miles"] != total:
        issuer["aggregate_committed_miles"] = total
        touch(issuer)
    return total


def program_add_outstanding(program, delta):
    if delta == 0:
        return
    program["outstanding_miles"] += delta
    touch(program)


def program_add_deferred(program, delta_cents):
    if delta_cents == 0:
        return
    program["deferred_revenue_cents"] += delta_cents
    touch(program)


# --------------------------------------------------------------------------
# Mile ledger inserts
# --------------------------------------------------------------------------


def insert_transaction(member, program, txn_type, total_miles, activity_date,
                       award_booking_id=None, reverses_transaction_id=None,
                       promotion_id=None, base_miles=0, qualifying_spend_cents=0,
                       segments=0, tier_bonus_miles=0, promo_multiplier_bps=10000,
                       stacking_mode_applied=None, bonus_miles=0,
                       qualifying_miles_credited=0):
    """Append an immutable ledger row.  Callers own the counter movements."""
    row = base_row(versioned=False)
    row["member_id"] = member["id"]
    row["promotion_id"] = promotion_id
    row["award_booking_id"] = award_booking_id
    row["reverses_transaction_id"] = reverses_transaction_id
    row["txn_type"] = txn_type
    row["base_miles"] = base_miles
    row["qualifying_spend_cents"] = qualifying_spend_cents
    row["segments"] = segments
    row["activity_date"] = activity_date
    row["elite_tier_at_earn"] = member["elite_tier"]
    row["tier_bonus_miles"] = tier_bonus_miles
    row["promo_multiplier_bps"] = promo_multiplier_bps
    row["stacking_mode_applied"] = stacking_mode_applied
    row["bonus_miles"] = bonus_miles
    row["total_miles"] = total_miles
    row["qualifying_miles_credited"] = qualifying_miles_credited
    row["posted_period"] = program["current_period"]
    finish_row(row)
    store.transactions[row["id"]] = row
    return row


def member_transactions(member_id):
    return [t for t in ordered(store.transactions) if t["member_id"] == member_id]


# --------------------------------------------------------------------------
# Fraud / security cascade shared by case creation and substantiation
# --------------------------------------------------------------------------


def cancel_held_bookings(member):
    """Every HELD booking of the member is cancelled and its seats released."""
    count = 0
    for booking in ordered(store.bookings):
        if booking["member_id"] == member["id"] and booking["status"] == "HELD":
            booking["status"] = "CANCELLED"
            touch(booking)
            release_seats(booking)
            count += 1
    return count


def revert_tier_after_lapse(member):
    member["elite_tier"] = member["awarded_tier_at_close"] or "BASE"


def lapse_status_match(member):
    member["status_match_state"] = "LAPSED"
    revert_tier_after_lapse(member)
    touch(member)
