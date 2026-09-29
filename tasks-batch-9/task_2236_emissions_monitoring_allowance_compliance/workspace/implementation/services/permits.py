"""Permit limit evaluation and excess emission events (PRD 3.8)."""

from db import base_record, db, touch
from lookup import events_of_limit
from services import calc
from util import D


def evaluate_limit(limit, anchor_raw, anchor_dt):
    """Re-derive the rolling window for *limit* anchored at *anchor_dt*.

    Returns the raised ExcessEmissionEvent when the evaluation exceeds, else
    ``None``. Withdrawn events are handled inline.
    """
    hours = calc.window_hours(
        limit["unit_id"], limit["averaging_basis"], anchor_dt, limit.get("_effective_from")
    )
    limit["window_sample_count"] = len(hours)
    limit["window_evaluated_utc"] = anchor_raw
    limit["_window_evaluated"] = anchor_dt

    if not calc.sufficient_samples(limit["averaging_basis"], len(hours)):
        limit["evaluation_status"] = "INSUFFICIENT_DATA"
        limit["current_rolling_value"] = None
    else:
        value = calc.rolling_value(hours, limit["pollutant"], limit["limit_units"])
        if value is None:
            limit["evaluation_status"] = "INSUFFICIENT_DATA"
            limit["current_rolling_value"] = None
        else:
            limit["current_rolling_value"] = value
            if D(value) > D(limit["limit_value"]):
                limit["evaluation_status"] = "EXCEEDED"
            else:
                limit["evaluation_status"] = "IN_COMPLIANCE"
    touch(limit)

    if limit["evaluation_status"] == "EXCEEDED":
        return raise_excess_event(limit, anchor_raw, anchor_dt)
    withdraw_detected_events(limit)
    return None


def raise_excess_event(limit, detected_raw, detected_dt):
    magnitude, _pct, penalty = calc.exceedance_figures(
        limit["current_rolling_value"], limit["limit_value"]
    )
    event = base_record()
    event.update(
        {
            "permit_limit_id": limit["id"],
            "unit_id": limit["unit_id"],
            "detected_utc": detected_raw,
            "observed_value": limit["current_rolling_value"],
            "limit_value_snapshot": limit["limit_value"],
            "exceedance_magnitude": magnitude,
            "penalty_allowance_debit_tons": penalty,
            "status": "DETECTED",
            "narrative": None,
            "corrective_action": None,
            "disposition_reason": None,
            "return_count": 0,
            "_detected": detected_dt,
        }
    )
    db.excess_events[event["id"]] = event
    return event


def withdraw_detected_events(limit):
    """A limit that leaves EXCEEDED withdraws every event still at DETECTED."""
    withdrawn = []
    for event in events_of_limit(limit["id"]):
        if event["status"] == "DETECTED":
            event["status"] = "WITHDRAWN"
            touch(event)
            withdrawn.append(event)
    return withdrawn


def reevaluate_unit_limits(unit_id):
    """Link four of the out-of-control cascade: every already-evaluated limit of
    the unit is re-run at its own stored ``window_evaluated_utc``.
    """
    limits = [
        p for p in db.permit_limits.values()
        if p["unit_id"] == unit_id and p["evaluation_status"] != "NOT_EVALUATED"
    ]
    limits.sort(key=lambda p: (p["created_at"], p["_seq"]))
    for limit in limits:
        anchor_dt = limit.get("_window_evaluated")
        anchor_raw = limit.get("window_evaluated_utc")
        if anchor_dt is None:
            continue
        evaluate_limit(limit, anchor_raw, anchor_dt)
