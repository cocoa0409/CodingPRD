"""The logical clock and its five-sweep ops-run checkpoint (PRD 2.4)."""
import auth
import calc
import cascades
import plcalc
import store
import timeutil
from constants import (DELIVERY_GRACE_SECONDS, FAULT_AUTO_CLEAR_SECONDS,
                       NOTIFY_WINDOW_SECONDS, OUTAGE_NOTIFY_AFTER_SECONDS)


def refresh_pending_count(tx):
    tx["notification_pending_count"] = len(
        [n for n in store.notifications_of(tx["id"]) if n["status"] in ("PENDING", "OVERDUE")])
    return tx


def create_notification(tx, kind, triggering_utc, due_utc,
                        observed_power_pct=None, outage_seconds=None):
    rec = store.base()
    rec.update({
        "transmitter_id": tx["id"],
        "kind": kind,
        "triggering_utc": triggering_utc,
        "due_utc": due_utc,
        "filed_utc": None,
        "filed_reference": None,
        "narrative": None,
        "observed_power_pct": observed_power_pct,
        "outage_seconds": outage_seconds,
        "status": "PENDING",
    })
    store.add(store.notifications, rec)
    refresh_pending_count(tx)
    return rec


def run_checkpoint(now):
    """Five sweeps in the pinned order; an earlier sweep's rows are visible to later ones."""
    # Sweep 1: outage filing obligations for transmitters still off air.
    for tx in store.rows(store.transmitters):
        if tx["operational_state"] != "OFF_AIR" or not tx.get("outage_started_utc"):
            continue
        elapsed = timeutil.delta_seconds(tx["outage_started_utc"], now)
        if elapsed < OUTAGE_NOTIFY_AFTER_SECONDS:
            continue
        existing = [n for n in store.notifications_of(tx["id"])
                    if n["kind"] == "OUTAGE"
                    and timeutil.sec(n["triggering_utc"]) == timeutil.sec(tx["outage_started_utc"])]
        if existing:
            continue
        create_notification(tx, "OUTAGE", tx["outage_started_utc"],
                            timeutil.plus(now, NOTIFY_WINDOW_SECONDS),
                            outage_seconds=elapsed)
        store.bump(tx)

    # Sweep 2: pending notifications whose due instant now lies in the past.
    for notification in store.rows(store.notifications):
        if notification["status"] != "PENDING":
            continue
        if timeutil.sec(notification["due_utc"]) < timeutil.sec(now):
            notification["status"] = "OVERDUE"
            store.bump(notification)
            tx = store.transmitters.get(notification["transmitter_id"])
            if tx is not None:
                refresh_pending_count(tx)

    # Sweep 3: expected assets whose delivery grace window has elapsed.
    for asset in store.rows(store.assets):
        if asset["status"] != "EXPECTED":
            continue
        limit = timeutil.plus(asset["delivery_deadline_utc"], DELIVERY_GRACE_SECONDS)
        if timeutil.sec(now) > timeutil.sec(limit):
            asset["status"] = "EXPIRED"
            store.bump(asset)
            cascades.asset_block_cascade(asset, accrue_credit=False)

    # Sweep 4: minor faults that were never acknowledged and have aged out.
    for fault in store.rows(store.faults):
        if fault["state"] != "DETECTED" or fault.get("acknowledged_by_user_id"):
            continue
        if fault["severity"] != "MINOR":
            continue
        if timeutil.delta_seconds(fault["detected_utc"], now) < FAULT_AUTO_CLEAR_SECONDS:
            continue
        fault["state"] = "AUTO_CLEARED"
        fault["cleared_utc"] = now
        fault["duration_seconds"] = timeutil.delta_seconds(fault["detected_utc"], now)
        store.bump(fault)
        if fault.get("channel_id"):
            channel = store.channels.get(fault["channel_id"])
            if channel is not None:
                calc.recompute_posture(channel, bump=True)

    # Sweep 5: re-derive every operator's certification state.
    for operator in store.rows(store.operators):
        state = auth.certification_state(operator)
        if operator.get("certification_state") != state:
            operator["certification_state"] = state
            store.bump(operator)

    # Posture is recomputed on every advance of the logical clock.
    for channel in store.rows(store.channels):
        calc.recompute_posture(channel, bump=True)
    for playlist in store.rows(store.playlists):
        plcalc.recompute_playlist(playlist, bump=False)
