"""The partitioned agency SLA clock (PRD 3.10, Invariant 3)."""
import clock
import store
from calendar_util import business_minutes_between
from services import lookup


def open_segment(order):
    for row in lookup.sla_segments_of(order):
        if row["ended_at"] is None:
            return row
    return None


def append_segment(order, segment_kind, cause, started_at=None, ended_at=None,
                   business_minutes=None):
    row = {
        "order_id": order["id"],
        "segment_kind": segment_kind,
        "cause": cause,
        "started_at": started_at if started_at is not None else clock.now(),
        "ended_at": ended_at,
        "business_minutes": business_minutes,
    }
    store.insert("sla_segments", row)
    return row


def close_open_segment(order):
    row = open_segment(order)
    if row is None:
        return None
    instant = clock.now()
    consulate = lookup.consulate_of(order)
    row["ended_at"] = instant
    row["business_minutes"] = business_minutes_between(row["started_at"], instant, consulate)
    return row


def _end_instant(order):
    return order["decided_at"] if order["decided_at"] is not None else clock.now()


def running_minutes(order):
    """The contractual clock-stop figure. PAUSED segments contribute zero."""
    if order["submitted_at"] is None:
        return 0
    consulate = lookup.consulate_of(order)
    end = _end_instant(order)
    total = 0
    for row in lookup.sla_segments_of(order):
        if row["segment_kind"] != "RUNNING":
            continue
        if row["ended_at"] is not None:
            total += row["business_minutes"] or 0
        else:
            total += business_minutes_between(row["started_at"], end, consulate)
    return total


def paused_minutes(order):
    if order["submitted_at"] is None:
        return 0
    consulate = lookup.consulate_of(order)
    end = _end_instant(order)
    total = 0
    for row in lookup.sla_segments_of(order):
        if row["segment_kind"] != "PAUSED":
            continue
        if row["ended_at"] is not None:
            total += row["business_minutes"] or 0
        else:
            total += business_minutes_between(row["started_at"], end, consulate)
    return total


def gross_minutes(order):
    if order["submitted_at"] is None:
        return 0
    consulate = lookup.consulate_of(order)
    return business_minutes_between(order["submitted_at"], _end_instant(order), consulate)
