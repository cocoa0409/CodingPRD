"""As-run writing, spot credit movements and the four named cascades (PRD 2.12)."""
import calc
import plcalc
import store
import timeutil
from errors import fail


# --- as-run log ------------------------------------------------------------

def append_asrun(playlist, item, event_kind, event_utc, measured=0,
                 source="SYSTEM", recorded_by=None):
    entry = store.base(versioned=False)
    entry.update({
        "playlist_id": playlist["id"] if playlist else (item["playlist_id"] if item else None),
        "playlist_item_id": item["id"] if item else None,
        "sequence_number": int(item["sequence_number"]) if item else None,
        "house_number": item.get("house_number") if item else None,
        "element_kind": item.get("element_kind") if item else None,
        "event_kind": event_kind,
        "event_utc": event_utc,
        "measured_duration_seconds": int(measured or 0),
        "source": source,
        "recorded_by_user_id": recorded_by,
    })
    return store.add(store.asrun, entry)


# --- spot credit movements -------------------------------------------------

def _order_of(item):
    if not item.get("spot_order_id"):
        return None
    return store.spot_orders.get(item["spot_order_id"])


def credit_not_aired(item):
    """Move one spot from scheduled_spots to credited_spots with the full per-spot credit."""
    order = _order_of(item)
    if order is None:
        return None
    order["scheduled_spots"] = max(0, int(order["scheduled_spots"]) - 1)
    order["credited_spots"] = int(order["credited_spots"]) + 1
    credit = plcalc.full_spot_credit(order)
    order["credit_accrued_cents"] = int(order["credit_accrued_cents"]) + credit
    plcalc.recompute_unplaced(order)
    plcalc.refresh_order_status(order)
    store.bump(order)
    return order


def credit_short_air(item):
    order = _order_of(item)
    if order is None:
        return None
    order["scheduled_spots"] = max(0, int(order["scheduled_spots"]) - 1)
    order["short_aired_spots"] = int(order["short_aired_spots"]) + 1
    credit = plcalc.short_air_credit(item, order)
    order["credit_accrued_cents"] = int(order["credit_accrued_cents"]) + credit
    plcalc.recompute_unplaced(order)
    plcalc.refresh_order_status(order)
    store.bump(order)
    return order


def credit_end_event(item):
    order = _order_of(item)
    if order is None:
        return None
    bucket = plcalc.classify(item, order)
    order["scheduled_spots"] = max(0, int(order["scheduled_spots"]) - 1)
    if bucket == "AIRED_FULL":
        order["aired_spots"] = int(order["aired_spots"]) + 1
    else:
        order["short_aired_spots"] = int(order["short_aired_spots"]) + 1
        order["credit_accrued_cents"] = int(order["credit_accrued_cents"]) + \
            plcalc.short_air_credit(item, order)
    plcalc.recompute_unplaced(order)
    plcalc.refresh_order_status(order)
    store.bump(order)
    return order


def preemption_allowed(item, force):
    order = _order_of(item)
    if order is None:
        return True
    if order["priority_class"] in ("PREEMPTIBLE", "REMNANT"):
        return True
    return bool(force)


def guard_preemption(items, force):
    for item in items:
        if not preemption_allowed(item, force):
            fail("ERR_ORDER_NOT_PREEMPTIBLE",
                 "A GUARANTEED spot may only be preempted with force_preempt_guaranteed.")


# --- item level transitions ------------------------------------------------

def truncate_item(item, at_utc, source="SYSTEM", recorded_by=None, measured=None):
    playlist = store.playlists.get(item["playlist_id"])
    if measured is None:
        started = item.get("actual_start_utc")
        measured = timeutil.delta_seconds(started, at_utc) if started else 0
        if measured < 0:
            measured = 0
    item["playout_status"] = "TRUNCATED"
    item["measured_duration_seconds"] = int(measured)
    store.bump(item)
    append_asrun(playlist, item, "TRUNCATION", at_utc, measured=int(measured),
                 source=source, recorded_by=recorded_by)
    credit_short_air(item)
    return item


def preempt_item(item, at_utc, source="SYSTEM", recorded_by=None):
    playlist = store.playlists.get(item["playlist_id"])
    item["playout_status"] = "PREEMPTED"
    store.bump(item)
    append_asrun(playlist, item, "PREEMPTION", at_utc, measured=0,
                 source=source, recorded_by=recorded_by)
    credit_not_aired(item)
    return item


def skip_item(item, at_utc, source="SYSTEM", recorded_by=None):
    playlist = store.playlists.get(item["playlist_id"])
    item["playout_status"] = "SKIPPED"
    store.bump(item)
    append_asrun(playlist, item, "SKIP", at_utc, measured=0,
                 source=source, recorded_by=recorded_by)
    credit_not_aired(item)
    return item


# --- clearance axis --------------------------------------------------------

def block_clearance(item):
    if item["clearance_status"] == "BLOCKED":
        return False
    item["clearance_status"] = "BLOCKED"
    store.bump(item)
    playlist = store.playlists.get(item["playlist_id"])
    if playlist is not None:
        playlist["blocked_item_count"] = len(
            [i for i in store.items_of(playlist["id"]) if i["clearance_status"] == "BLOCKED"])
        if playlist["status"] in ("VALIDATED", "ARMED"):
            playlist["status"] = "IMPORTED"
            playlist["armed_at_utc"] = None
        store.bump(playlist)
    return True


def clear_clearance(item):
    if item["clearance_status"] == "CLEARED":
        return False
    item["clearance_status"] = "CLEARED"
    store.bump(item)
    playlist = store.playlists.get(item["playlist_id"])
    if playlist is not None:
        playlist["blocked_item_count"] = len(
            [i for i in store.items_of(playlist["id"]) if i["clearance_status"] == "BLOCKED"])
        store.bump(playlist)
    return True


def asset_block_cascade(asset, accrue_credit):
    """Cascade B (retraction) and B-prime (expiry): block unaired elements."""
    for item in store.items_for_asset(asset["id"]):
        if item["playout_status"] not in ("SCHEDULED", "CUED"):
            continue
        if block_clearance(item) and accrue_credit:
            credit_not_aired(item)


def asset_clear_cascade(asset, respect_captions=True):
    for item in store.items_for_asset(asset["id"]):
        if item["playout_status"] not in ("SCHEDULED", "CUED"):
            continue
        if respect_captions and asset.get("captions_required") and not asset.get("caption_present") \
                and asset["status"] != "QC_WAIVED":
            continue
        clear_clearance(item)


# --- Cascade A: transmitter power -----------------------------------------

def transmitter_cascade(tx, at_utc, off_air):
    """Recompute the bit pool for every child multiplex and settle the consequences."""
    for mux in store.multiplexes_of(tx["id"]):
        calc.run_waterfall(mux)
        store.bump(mux)
        calc.refresh_encoder_peak(mux)
    for channel in store.channels_of_transmitter(tx["id"]):
        if off_air:
            channel["air_status"] = "DARK"
            calc.recompute_posture(channel, bump=False)
            store.bump(channel)
            _sweep_off_programme(channel, at_utc)
            abandon_windows(channel)
        else:
            was_on_air = channel["air_status"] == "ON_AIR"
            calc.recompute_posture(channel, bump=True)
            if channel["posture"] == "SUSPENDED" and was_on_air:
                # Cascade A hop four takes the newly suspended channel off
                # programme, and hops five and six follow: PRD 2.12 runs the
                # cascade through "channel posture and air status, then playlist
                # items, then spot-order credit", PRD 3.6 names "hop five of the
                # transmitter cascade" as a source of both truncation and
                # preemption, and PRD 3.1's restoration hop puts such a channel
                # back "from BARS_AND_TONE to ON_AIR" -- which is where the
                # suspension must therefore have left it.
                channel["air_status"] = "BARS_AND_TONE"
                store.bump(channel)
                _sweep_off_programme(channel, at_utc)
                abandon_windows(channel)
            elif channel["posture"] != "SUSPENDED" and channel["air_status"] == "BARS_AND_TONE":
                playlist = store.on_air_playlist(channel["id"])
                if playlist is not None:
                    channel["air_status"] = "ON_AIR"
                    store.bump(channel)


def _sweep_off_programme(channel, at_utc):
    """Hops five and six: truncate what is playing, preempt what is booked, settle."""
    playlist = store.on_air_playlist(channel["id"])
    if playlist is None:
        return
    for item in store.items_of(playlist["id"]):
        if item["playout_status"] == "PLAYING":
            truncate_item(item, at_utc, source="SYSTEM")
    for item in store.items_of(playlist["id"]):
        if item["playout_status"] in ("SCHEDULED", "CUED"):
            preempt_item(item, at_utc, source="SYSTEM")
    plcalc.recompute_playlist(playlist, bump=True)


def abandon_windows(channel):
    """A PLANNED window is abandoned by the system when the channel goes dark or suspends."""
    for window in store.windows_of(channel["id"]):
        if window["state"] != "PLANNED":
            continue
        if channel["posture"] == "SUSPENDED" or channel["air_status"] == "DARK":
            window["state"] = "ABANDONED"
            store.bump(window)
            mux = store.multiplex_of_channel(channel)
            if mux is not None:
                calc.refresh_encoder_peak(mux)


# --- Cascade C: override cut-in -------------------------------------------

def cutin_cascade(override, channel, at_utc, force, recorded_by):
    playlist = store.on_air_playlist(channel["id"])
    truncated = 0
    preempted = 0
    if playlist is None:
        override["truncated_item_count"] = 0
        override["preempted_item_count"] = 0
        return
    expected = int(override["expected_duration_seconds"])
    window_start = timeutil.sec(at_utc)
    window_end = window_start + _seconds(expected)
    candidates = []
    for item in store.items_of(playlist["id"]):
        if item["playout_status"] not in ("SCHEDULED", "CUED"):
            continue
        start = timeutil.sec(item["scheduled_start_utc"])
        end = start + _seconds(int(item["scheduled_duration_seconds"]))
        if start >= window_start and end <= window_end:
            candidates.append(item)
    guard_preemption(candidates, force)
    for item in store.items_of(playlist["id"]):
        if item["playout_status"] == "PLAYING":
            truncate_item(item, at_utc, source="SYSTEM")
            truncated += 1
    for item in candidates:
        preempt_item(item, at_utc, source="SYSTEM")
        preempted += 1
    override["truncated_item_count"] = truncated
    override["preempted_item_count"] = preempted
    plcalc.recompute_playlist(playlist, bump=True)


def _seconds(value):
    from datetime import timedelta
    return timedelta(seconds=value)


# --- playlist close settlement --------------------------------------------

def close_settlement(playlist):
    orders = {}
    for item in store.items_of(playlist["id"]):
        if item.get("spot_order_id"):
            order = store.spot_orders.get(item["spot_order_id"])
            if order is not None:
                orders[order["id"]] = order
    total_credit = 0
    for order in orders.values():
        figures = plcalc.settle(order, basis="FINAL", playlist_id=playlist["id"])
        order["aired_spots"] = figures["aired_spots"]
        order["short_aired_spots"] = figures["short_aired_spots"]
        order["credited_spots"] = figures["credited_spots"]
        order["scheduled_spots"] = figures["scheduled_spots"]
        order["unplaced_spots"] = figures["unplaced_spots"]
        order["credit_accrued_cents"] = figures["credit_accrued_cents"]
        ordered = int(order["ordered_spots"])
        # PRD 3.9: the four settled counters plus unplaced_spots account for the
        # whole ordered_spots, and the credit test is credited plus unplaced.
        accounted = (figures["aired_spots"] + figures["short_aired_spots"]
                     + figures["credited_spots"] + figures["scheduled_spots"]
                     + figures["unplaced_spots"])
        if figures["aired_spots"] == ordered and figures["credited_spots"] == 0 \
                and figures["short_aired_spots"] == 0:
            order["status"] = "FULLY_AIRED"
            order["credit_accrued_cents"] = 0
        elif figures["scheduled_spots"] == 0 \
                and figures["credited_spots"] + figures["unplaced_spots"] > 0 \
                and accounted >= ordered:
            order["status"] = "CLOSED_WITH_CREDIT"
        elif figures["credited_spots"] + figures["short_aired_spots"] > 0:
            order["status"] = "PARTIALLY_CREDITED"
        store.bump(order)
        total_credit += figures["playlist_credit_cents"]
    playlist["reconciliation_credit_cents"] = total_credit
    return total_credit
