"""Playlist timeline, inventory, variance, backtiming and settlement calculations."""
from fractions import Fraction

import store
import timeutil
from calc import round_half_up
from constants import (AIR_TOLERANCE_SECONDS, BACKTIME_TOLERANCE_CAP_SECONDS,
                       HOUR_SECONDS, MAX_COMMERCIAL_SECONDS_PER_HOUR,
                       MAX_FILLER_SECONDS, TRIMMABLE_KINDS)
from errors import fail


# --- timeline --------------------------------------------------------------

def timeline_items(playlist):
    return [i for i in store.items_of(playlist["id"])
            if i["playout_status"] not in ("SKIPPED", "PREEMPTED")]


def check_timeline(playlist):
    """Half-open interval adjacency walk (PRD 3.5). First anomaly in sequence order wins."""
    rows = timeline_items(playlist)
    if not rows:
        fail("ERR_PLAYLIST_NO_PROGRAM_CONTENT", "The playlist has no content on the timeline.")
    first = rows[0]
    if timeutil.sec(first["scheduled_start_utc"]) != timeutil.sec(playlist["schedule_start_utc"]):
        fail("ERR_SCHEDULE_GAP_DETECTED", "The first element does not start at the playlist start.")
    for earlier, later in zip(rows, rows[1:]):
        end = timeutil.sec(earlier["scheduled_start_utc"]) + \
            _delta(int(earlier["scheduled_duration_seconds"]))
        start = timeutil.sec(later["scheduled_start_utc"])
        if start > end:
            fail("ERR_SCHEDULE_GAP_DETECTED", "A hole exists in the playlist timeline.")
        if start < end:
            fail("ERR_SCHEDULE_OVERLAP_DETECTED", "Two elements collide on the playlist timeline.")
    return rows


def _delta(seconds):
    from datetime import timedelta
    return timedelta(seconds=seconds)


# --- commercial inventory --------------------------------------------------

def commercial_by_hour(playlist):
    out = {}
    start = timeutil.sec(playlist["schedule_start_utc"])
    for item in store.items_of(playlist["id"]):
        if item["element_kind"] != "COMMERCIAL":
            continue
        if item["playout_status"] in ("SKIPPED", "PREEMPTED"):
            continue
        offset = int((timeutil.sec(item["scheduled_start_utc"]) - start).total_seconds())
        index = offset // HOUR_SECONDS
        key = str(index)
        out[key] = out.get(key, 0) + int(item["scheduled_duration_seconds"])
    return out


def check_inventory(playlist):
    for hour, seconds in commercial_by_hour(playlist).items():
        if seconds > MAX_COMMERCIAL_SECONDS_PER_HOUR:
            fail("ERR_COMMERCIAL_INVENTORY_EXCEEDED",
                 "Hour %s carries %d seconds of commercial inventory." % (hour, seconds))


# --- variance figures ------------------------------------------------------

def projected_variance(playlist):
    total = 0
    for item in store.items_of(playlist["id"]):
        if item["playout_status"] in ("SKIPPED", "PREEMPTED"):
            continue
        total += int(item["scheduled_duration_seconds"])
    return total - int(playlist["window_duration_seconds"])


def asrun_variance(playlist):
    total = 0
    for item in store.items_of(playlist["id"]):
        status = item["playout_status"]
        if status in ("PLAYED", "TRUNCATED"):
            total += int(item.get("measured_duration_seconds") or 0)
        elif status in ("SKIPPED", "PREEMPTED"):
            total += 0
        else:
            total += int(item["scheduled_duration_seconds"])
    return total - int(playlist["window_duration_seconds"])


def recompute_playlist(playlist, bump=False):
    rows = store.items_of(playlist["id"])
    playlist["item_count"] = len(rows)
    playlist["blocked_item_count"] = len([i for i in rows if i["clearance_status"] == "BLOCKED"])
    playlist["scheduled_total_seconds"] = sum(
        int(i["scheduled_duration_seconds"]) for i in rows
        if i["playout_status"] not in ("SKIPPED", "PREEMPTED"))
    playlist["commercial_seconds_by_hour"] = commercial_by_hour(playlist)
    playlist["projected_end_variance_seconds"] = projected_variance(playlist)
    playlist["asrun_end_variance_seconds"] = asrun_variance(playlist)
    if bump:
        store.bump(playlist)
    return playlist


# --- spot settlement -------------------------------------------------------

def per_spot_rate(order):
    return Fraction(int(order["rate_cents_total"]), int(order["ordered_spots"]))


def full_spot_credit(order):
    return round_half_up(Fraction(per_spot_rate(order)))


def superseded_by_makegood():
    """Ids of elements whose credited spot a makegood placement has already replaced.

    A makegood is the compensating action for one credited spot, so the element it
    replaces leaves the ledger entirely: the count of linked elements is unchanged by
    the placement and the spot-count identity survives the round trip.
    """
    return set(i["replaces_item_id"] for i in store.items.values()
               if i.get("is_makegood") and i.get("replaces_item_id"))


def linked_items(order):
    dropped = superseded_by_makegood()
    rows = [i for i in store.items.values()
            if i.get("spot_order_id") == order["id"] and i["id"] not in dropped]
    rows.sort(key=lambda i: (timeutil.sec(i["scheduled_start_utc"]) if i.get("scheduled_start_utc") else timeutil.sec("1970-01-01T00:00:00Z"),
                             int(i["sequence_number"]), i["_seq"]))
    return rows


def classify(item, order):
    unit = int(order["unit_duration_seconds"])
    status = item["playout_status"]
    measured = item.get("measured_duration_seconds")
    measured = int(measured) if measured is not None else 0
    if status == "PLAYED":
        if measured >= unit - AIR_TOLERANCE_SECONDS:
            return "AIRED_FULL"
        return "SHORT_AIR"
    if status == "TRUNCATED":
        return "SHORT_AIR"
    if status in ("SKIPPED", "PREEMPTED"):
        return "NOT_AIRED"
    return "PENDING"


def raw_credit(item, order, bucket):
    rate = per_spot_rate(order)
    unit = int(order["unit_duration_seconds"])
    if bucket == "AIRED_FULL" or bucket == "PENDING":
        return Fraction(0)
    if bucket == "NOT_AIRED":
        return rate
    measured = item.get("measured_duration_seconds")
    measured = int(measured) if measured is not None else 0
    shortfall = unit - measured
    if shortfall < 0:
        shortfall = 0
    return rate * Fraction(shortfall, unit)


def short_air_credit(item, order):
    return round_half_up(raw_credit(item, order, "SHORT_AIR"))


def settle(order, basis="PRELIMINARY", playlist_id=None):
    """Compute the settlement figures for one order (PRD 3.9). Never persists."""
    rows = linked_items(order)
    aired = shorts = credited = pending = 0
    credit_total = 0
    playlist_credit = 0
    details = []
    for item in rows:
        bucket = classify(item, order)
        credit = 0
        if bucket == "AIRED_FULL":
            aired += 1
        elif bucket == "SHORT_AIR":
            shorts += 1
            credit = round_half_up(raw_credit(item, order, bucket))
        elif bucket == "NOT_AIRED":
            credited += 1
            credit = round_half_up(raw_credit(item, order, bucket))
        else:
            pending += 1
        credit_total += credit
        if playlist_id is not None and item["playlist_id"] == playlist_id:
            playlist_credit += credit
        details.append({
            "playlist_item_id": item["id"],
            "playlist_id": item["playlist_id"],
            "sequence_number": int(item["sequence_number"]),
            "scheduled_start_utc": item.get("scheduled_start_utc"),
            "classification": bucket,
            "credit_cents": credit,
        })
    unplaced = max(0, int(order["ordered_spots"]) - len(rows))
    # The unplaced spots are credited in full on the final basis, but they stay
    # counted in unplaced_spots rather than moving into credited_spots: PRD 2.11
    # requires ordered_spots to equal the sum of the five counters, and PRD 3.9
    # restates it as "the four settled counters plus unplaced_spots account for
    # the whole ordered_spots". Only the money moves.
    credited_final = credited
    if basis == "FINAL" and unplaced:
        per_spot = full_spot_credit(order)
        credit_total += unplaced * per_spot
        playlist_credit += unplaced * per_spot if playlist_id is not None else 0
    return {
        "spot_order_id": order["id"],
        "order_reference": order["order_reference"],
        "basis": basis,
        "aired_spots": aired,
        "short_aired_spots": shorts,
        "credited_spots": credited_final,
        "scheduled_spots": pending,
        "unplaced_spots": unplaced,
        "credit_accrued_cents": credit_total,
        "playlist_credit_cents": playlist_credit,
        "elements": details,
    }


def refresh_order_status(order):
    ordered = int(order["ordered_spots"])
    credited = int(order["credited_spots"])
    shorts = int(order["short_aired_spots"])
    if credited + shorts == 0:
        order["status"] = "OPEN"
    elif order["status"] in ("FULLY_AIRED", "CLOSED_WITH_CREDIT"):
        pass
    else:
        order["status"] = "PARTIALLY_CREDITED"
    return order


def recompute_unplaced(order):
    order["unplaced_spots"] = max(0, int(order["ordered_spots"]) - len(linked_items(order)))
    return order


# --- backtiming ------------------------------------------------------------

def plan_playlist(channel):
    """The channel's on-air playlist, else its most recently armed one."""
    on_air = store.on_air_playlist(channel["id"])
    if on_air is not None:
        return on_air
    armed = [p for p in store.playlists_of(channel["id"]) if p["status"] == "ARMED"]
    if armed:
        armed.sort(key=lambda p: (p.get("armed_at_utc") or p["created_at"], p["_seq"]))
        return armed[-1]
    return None


def tail_items(playlist, anchor_sequence_number):
    if playlist is None:
        return []
    return [i for i in store.items_of(playlist["id"])
            if int(i["sequence_number"]) >= int(anchor_sequence_number)
            and i["playout_status"] in ("SCHEDULED", "CUED")]


def tolerance_for(mode, guard_seconds, pending_tail):
    if mode == "STRICT":
        return int(guard_seconds)
    proportional = min(int(pending_tail * 2 // 100), BACKTIME_TOLERANCE_CAP_SECONDS)
    return max(int(guard_seconds), proportional)


def compute_plan(window, target_utc, now_utc, playlist=None):
    """The five-branch backtiming plan (PRD 3.7). First matching clause wins."""
    channel = store.channels.get(window["channel_id"])
    if playlist is None:
        playlist = plan_playlist(channel) if channel else None
    tail = tail_items(playlist, window["anchor_sequence_number"])
    pending_tail = sum(int(i["scheduled_duration_seconds"]) for i in tail)
    remaining = timeutil.delta_seconds(now_utc, target_utc)
    slack = remaining - pending_tail
    tolerance = tolerance_for(window["backtiming_mode"], window.get("guard_seconds", 2), pending_tail)
    plan = {
        "plan_action": None,
        "backtime_pad_seconds": 0,
        "backtime_trim_seconds": 0,
        "residual_dead_air_seconds": 0,
        "late_join_seconds": 0,
        "skipped_item_sequences": [],
        "_trims": {},
        "_tail": tail,
        "_pending_tail": pending_tail,
        "_playlist": playlist,
    }
    if remaining <= 0:
        plan["plan_action"] = "JOIN_IN_PROGRESS"
        plan["late_join_seconds"] = -remaining
        return plan
    if abs(slack) <= tolerance:
        plan["plan_action"] = "HARD_CUT"
        return plan
    if slack > tolerance:
        pad = min(slack, MAX_FILLER_SECONDS)
        plan["plan_action"] = "PAD_WITH_FILLER"
        plan["backtime_pad_seconds"] = pad
        plan["residual_dead_air_seconds"] = slack - pad
        return plan
    deficit = -slack
    allowances = []
    for item in tail:
        if item["element_kind"] in TRIMMABLE_KINDS:
            allowance = min(int(item["scheduled_duration_seconds"]) - 1,
                            int(item.get("max_trim_seconds") or 0))
            if allowance < 0:
                allowance = 0
            allowances.append((item, allowance))
    pool = sum(a for _, a in allowances)
    if pool >= deficit:
        plan["plan_action"] = "TRIM_TAIL"
        plan["backtime_trim_seconds"] = deficit
        need = deficit
        for item, allowance in allowances:
            if need <= 0:
                break
            take = min(need, allowance)
            if take:
                plan["_trims"][item["id"]] = take
                need -= take
        return plan
    plan["backtime_trim_seconds"] = pool
    for item, allowance in allowances:
        if allowance:
            plan["_trims"][item["id"]] = allowance
    need = deficit - pool
    skipped = []
    for item in tail:
        if need <= 0:
            break
        if item["element_kind"] not in TRIMMABLE_KINDS:
            continue
        taken = plan["_trims"].get(item["id"], 0)
        skipped.append(int(item["sequence_number"]))
        need -= (int(item["scheduled_duration_seconds"]) - taken)
    if need <= 0:
        plan["plan_action"] = "SKIP_ELEMENTS"
        plan["skipped_item_sequences"] = skipped
        for seq in skipped:
            for item in tail:
                if int(item["sequence_number"]) == seq and item["id"] in plan["_trims"]:
                    del plan["_trims"][item["id"]]
        return plan
    plan["plan_action"] = "HARD_CUT"
    plan["late_join_seconds"] = need
    plan["skipped_item_sequences"] = []
    plan["backtime_trim_seconds"] = pool
    return plan
