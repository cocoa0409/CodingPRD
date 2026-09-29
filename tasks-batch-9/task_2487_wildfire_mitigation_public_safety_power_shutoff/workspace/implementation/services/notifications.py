"""Notification batching, routing and dispatch (C8, C9)."""

import clock
import db
from errors import ApiError
from services import calc, events


def target_customers(event):
    """Customers on the circuits of the event's CONFIRMED scope rows."""
    circuit_ids = set(s["circuit_id"] for s in events.confirmed_scopes(event))
    rows = [c for c in db.customers.values() if c["circuit_id"] in circuit_ids]
    rows.sort(
        key=lambda c: (
            calc.TIER_RANK[c["notification_tier"]],
            c["created_at"],
            c["_seq"],
        )
    )
    return rows


def allowed_languages(stage):
    if stage in calc.RESTRICTED_LANGUAGE_STAGES:
        return calc.RESTRICTED_LANGUAGES
    return calc.FULL_LANGUAGES


def resolve_channel(customer):
    forbidden = set()
    for need in customer["accessibility_needs"]:
        for channel in calc.FORBIDDEN_CHANNELS.get(need, ()):
            forbidden.add(channel)
    for channel in calc.CHANNEL_PRIORITY:
        if channel in forbidden:
            continue
        if channel in customer["notification_channels"]:
            return channel
    return None


def dispatch(batch, event):
    """Priority 13 lead-time gate, then the routing walk."""
    stamp = clock.now()
    lead = calc.floor_minutes(stamp, event["forecast_onset_at"])
    required = calc.STAGE_MIN_LEAD_MINUTES[batch["stage"]]
    if lead < required:
        raise ApiError(
            "ERR_NOTIFICATION_LEAD_TIME_SHORT",
            "Stage %s requires at least %d minutes of lead time (got %d)."
            % (batch["stage"], required, lead),
        )

    if int(event["confirmed_scope_count"]) < 1:
        raise ApiError(
            "ERR_NO_CIRCUITS_IN_SCOPE",
            "The event holds no CONFIRMED scope row.",
        )

    db.set_dt(batch, "dispatched_at", stamp)
    batch["lead_time_minutes"] = lead

    languages = allowed_languages(batch["stage"])
    delivered = 0
    unreachable = 0
    order = 0
    for customer in target_customers(event):
        order += 1
        language = customer["preferred_language"]
        if language not in languages:
            language = "EN"
        channel = resolve_channel(customer)
        accessibility_format = (
            "LARGE_PRINT" if "LARGE_PRINT" in customer["accessibility_needs"] else "STANDARD"
        )
        status = "DELIVERED" if channel is not None else "UNREACHABLE"
        if channel is None:
            unreachable += 1
        else:
            delivered += 1
        record = db.new_row(versioned=False)
        record["notification_batch_id"] = batch["id"]
        record["customer_id"] = customer["id"]
        record["attempt_order"] = order
        record["language_used"] = language
        record["channel_used"] = channel
        record["accessibility_format"] = accessibility_format
        record["delivery_status"] = status
        db.notification_records[record["id"]] = record

    batch["target_count"] = order
    batch["delivered_count"] = delivered
    batch["unreachable_count"] = unreachable
    batch["status"] = "FAILED_PARTIAL" if unreachable > 0 else "DISPATCHED"
    db.touch(batch)

    advance_notification_status(event, batch["stage"])
    db.touch(event)


def advance_notification_status(event, stage):
    current = event["notification_status"]
    if stage in ("ADVANCE_48H", "ADVANCE_24H"):
        if current == "NOT_STARTED":
            event["notification_status"] = "ADVANCE_SENT"
    elif stage == "IMMINENT_1H":
        if current == "ADVANCE_SENT":
            event["notification_status"] = "IMMINENT_SENT"
    elif stage == "ACTIVATION":
        if current == "IMMINENT_SENT":
            event["notification_status"] = "ACTIVATION_SENT"
    elif stage == "RESTORATION":
        if current == "ACTIVATION_SENT":
            event["notification_status"] = "RESTORATION_SENT"


# ------------------------------------------------------------------- the gates
def assert_advance_notification(event):
    for batch in events.batches_of(event):
        if batch["stage"] == "ADVANCE_48H" and batch["status"] in (
            "DISPATCHED",
            "FAILED_PARTIAL",
        ):
            return batch
    raise ApiError(
        "ERR_ADVANCE_NOTIFICATION_MISSING",
        "No dispatched ADVANCE_48H notification batch exists for this event.",
    )


def assert_critical_notification(event):
    circuit_ids = set(s["circuit_id"] for s in events.confirmed_scopes(event))
    critical_ids = set(
        c["id"]
        for c in db.customers.values()
        if c["circuit_id"] in circuit_ids and c["notification_tier"] in calc.CRITICAL_TIERS
    )
    for batch in events.batches_of(event):
        if batch["stage"] != "IMMINENT_1H":
            continue
        if batch["status"] not in ("DISPATCHED", "FAILED_PARTIAL"):
            continue
        delivered = set(
            r["customer_id"]
            for r in db.notification_records.values()
            if r["notification_batch_id"] == batch["id"] and r["delivery_status"] == "DELIVERED"
        )
        if critical_ids <= delivered:
            return batch
    raise ApiError(
        "ERR_CRITICAL_NOTIFICATION_INCOMPLETE",
        "No IMMINENT_1H batch delivered to every critical and medical-baseline customer.",
    )
