"""Producer churn surveillance (PRD §3.8, SCAFFOLD §1.3 producer_churn_metrics).

Re-evaluated after every producer case event and every logical-clock set.
Window: half-open (now-365d, now] — event exactly 365 days old is EXCLUDED,
event at exactly now is INCLUDED.
"""
from datetime import timedelta

import db
from services.calculations import (
    CHURN_FLAG_MIN_COMPLETED_12M,
    RESCISSION_FLAG_BPS,
)


def _bump_producer(p: dict, now_iso: str):
    p["version"] += 1
    p["updated_at"] = now_iso


def _append_event(producer_id: str, case_id, event_type: str, event_at: str):
    evt = {
        "id": db.new_id(),
        "producer_id": producer_id,
        "case_id": case_id,
        "event_type": event_type,
        "event_at": event_at,
        "created_at": event_at,
    }
    db.activity_events.append(evt)
    return evt


def append_event(producer_id: str, case_id, event_type: str):
    return _append_event(producer_id, case_id, event_type, db.now_formatted())


def recompute_counters(p: dict, now_dt=None):
    """Recompute the producer's rolling 12m counters and rate variants.

    Does NOT bump the version by itself; callers decide when the producer
    record mutates (flag transitions bump; mere counter recomputation does
    not — counters are exposed as computed fields derived from the event log).
    """
    if now_dt is None:
        now_dt = db.parse_iso(db.now_iso())
    window_start = now_dt - timedelta(days=365)
    submitted = 0
    completed = 0
    rescinded = 0
    for e in db.activity_events:
        if e["producer_id"] != p["id"]:
            continue
        evt_dt = db.parse_iso(e["event_at"])
        # Half-open: event_at > now - 365d AND event_at <= now
        if not (evt_dt > window_start and evt_dt <= now_dt):
            continue
        et = e["event_type"]
        if et == "CASE_SUBMITTED":
            submitted += 1
        elif et == "EXCHANGE_COMPLETED":
            completed += 1
        elif et == "EXCHANGE_RESCINDED":
            rescinded += 1
    p["submitted_case_count_12m"] = submitted
    p["completed_exchange_count_12m"] = completed
    p["rescinded_exchange_count_12m"] = rescinded
    p["rescission_rate_completed_bps"] = (
        0 if completed == 0 else (10000 * rescinded) // completed
    )
    p["rescission_rate_submitted_bps"] = (
        0 if submitted == 0 else (10000 * rescinded) // submitted
    )


def evaluate_producer(p: dict):
    """Run the churn evaluation for a single producer.

    Stamps last_churn_eval_at, sets/clears FLAGGED per thresholds, and
    appends PRODUCER_FLAGGED / PRODUCER_UNFLAGGED events on transitions.
    """
    now_iso = db.now_iso()
    now_dt = db.parse_iso(now_iso)
    recompute_counters(p, now_dt)
    p["last_churn_eval_at"] = db.fmt_iso(now_dt)

    threshold_met = (
        p["completed_exchange_count_12m"] >= CHURN_FLAG_MIN_COMPLETED_12M
        and p["rescission_rate_completed_bps"] >= RESCISSION_FLAG_BPS
    )
    if p["status"] == "ACTIVE" and threshold_met:
        p["status"] = "FLAGGED"
        _append_event(p["id"], None, "PRODUCER_FLAGGED", p["last_churn_eval_at"])
        _bump_producer(p, p["last_churn_eval_at"])
    elif p["status"] == "FLAGGED" and not threshold_met:
        p["status"] = "ACTIVE"
        _append_event(p["id"], None, "PRODUCER_UNFLAGGED", p["last_churn_eval_at"])
        _bump_producer(p, p["last_churn_eval_at"])


def evaluate_all_producers():
    for p in list(db.producers.values()):
        evaluate_producer(p)
