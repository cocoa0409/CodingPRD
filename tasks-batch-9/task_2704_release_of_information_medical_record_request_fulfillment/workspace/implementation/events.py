"""The append-only compliance trail (PRD 2.9)."""

import store

SYSTEM_ACTOR = "system"


def append_event(request_id, event_type, actor_user_id, days_late=0,
                 penalty_delta_cents=0, detail=""):
    event = store.common_fields(full=False)
    event["request_id"] = request_id
    event["event_type"] = event_type
    event["days_late"] = days_late
    event["penalty_delta_cents"] = penalty_delta_cents
    event["actor_user_id"] = actor_user_id
    event["occurred_at"] = store.fmt(store.now())
    event["detail"] = detail
    store.compliance_events[event["id"]] = event
    return event


def events_of(request_id):
    rows = [e for e in store.compliance_events.values() if e["request_id"] == request_id]
    return sorted(rows, key=lambda e: (e["occurred_at"], e["_seq"]))
