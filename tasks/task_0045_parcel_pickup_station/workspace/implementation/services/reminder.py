"""Reminder + sweep logic."""
from datetime import timedelta
from clock import now
from db import store, GLOBAL_LOCK
from services.common import stamp_create, bump, write_audit


ESCALATION_HOURS = 24
LONG_STAY_HOURS = 168


def emit_reminder(parcel_id: str, tier: str, channel: str, triggered_by: str) -> dict:
    row = stamp_create({
        "parcel_id": parcel_id,
        "tier": tier,
        "channel": channel,
        "sent_at": now(),
        "triggered_by": triggered_by,
    }, common_fields=False)
    store.reminders[row["id"]] = row
    return row


def has_reminder(parcel_id: str, tier: str) -> bool:
    for r in store.reminders.values():
        if r["parcel_id"] == parcel_id and r["tier"] == tier:
            return True
    return False


def list_reminders_for_parcel(parcel_id: str):
    return [r for r in store.reminders.values() if r["parcel_id"] == parcel_id]


def run_sweep(station_id_filter=None, actor_role="PlatformAdmin", actor_id="system"):
    """Walk every non-terminal parcel and apply tier rules in sequence."""
    from services.pricing import storage_fee_at
    emissions = []
    overtimed = []
    awaiting = []
    with GLOBAL_LOCK:
        t = now()

        # Snapshot parcel ids for stable iteration
        parcel_ids = list(store.parcels.keys())

        # Pass 1: SHELVED -> OVERTIME when t >= free_storage_deadline
        for pid in parcel_ids:
            p = store.parcels.get(pid)
            if p is None:
                continue
            if station_id_filter and p["station_id"] != station_id_filter:
                continue
            if p["status"] != "SHELVED":
                continue
            if p["free_storage_deadline"] is None or t < p["free_storage_deadline"]:
                continue
            if has_reminder(pid, "T2_FOLLOWUP"):
                continue
            r = emit_reminder(pid, "T2_FOLLOWUP", "SMS", "OVERTIME_SWEEP")
            emissions.append(r)
            # Transition to OVERTIME, recompute provisional storage fee
            from_state = p["status"]
            p["status"] = "OVERTIME"
            if not p.get("storage_fee_locked"):
                p["storage_fee_total"] = storage_fee_at(
                    p["free_storage_deadline"], t, p["size_class"])
            bump(p)
            write_audit("Parcel", pid, "OVERTIME_FLAGGED", actor_role, actor_id,
                        from_state=from_state, to_state="OVERTIME", payload={})
            overtimed.append(pid)

        # Pass 2: OVERTIME -> escalate T3 when t >= free_storage_deadline + 24h
        for pid in parcel_ids:
            p = store.parcels.get(pid)
            if p is None:
                continue
            if station_id_filter and p["station_id"] != station_id_filter:
                continue
            if p["status"] != "OVERTIME":
                continue
            if p["free_storage_deadline"] is None:
                continue
            if t < p["free_storage_deadline"] + timedelta(hours=ESCALATION_HOURS):
                continue
            if has_reminder(pid, "T3_ESCALATION"):
                continue
            r = emit_reminder(pid, "T3_ESCALATION", "IM", "OVERTIME_SWEEP")
            emissions.append(r)
            # Provisional fee recompute
            if not p.get("storage_fee_locked"):
                p["storage_fee_total"] = storage_fee_at(
                    p["free_storage_deadline"], t, p["size_class"])
                bump(p)

        # Pass 3: OVERTIME -> AWAITING_RETURN when t >= shelved_at + LONG_STAY_HOURS
        for pid in parcel_ids:
            p = store.parcels.get(pid)
            if p is None:
                continue
            if station_id_filter and p["station_id"] != station_id_filter:
                continue
            if p["status"] != "OVERTIME":
                continue
            if p.get("shelved_at") is None:
                continue
            if t < p["shelved_at"] + timedelta(hours=LONG_STAY_HOURS):
                continue
            from_state = p["status"]
            p["status"] = "AWAITING_RETURN"
            p["long_stay_flagged_at"] = t
            if not p.get("storage_fee_locked"):
                p["storage_fee_total"] = storage_fee_at(
                    p["free_storage_deadline"], t, p["size_class"])
            bump(p)
            if not has_reminder(pid, "T4_RETURN_CONFIRM"):
                r = emit_reminder(pid, "T4_RETURN_CONFIRM", "IM", "LONG_STAY_SWEEP")
                emissions.append(r)
            write_audit("Parcel", pid, "LONG_STAY_FLAGGED", actor_role, actor_id,
                        from_state=from_state, to_state="AWAITING_RETURN", payload={})
            awaiting.append(pid)

        return {
            "reminders_emitted": [r["id"] for r in emissions],
            "parcels_to_overtime": overtimed,
            "parcels_to_awaiting_return": awaiting,
        }
