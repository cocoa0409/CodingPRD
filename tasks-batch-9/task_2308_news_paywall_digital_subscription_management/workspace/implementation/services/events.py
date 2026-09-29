"""ReaderEvent creation (append-only: no updated_at, no version)."""
import config
from clock import clock, format_datetime
from db import db, new_entity
from response import mark_created


def create_event(
    reader,
    event_type,
    article_id=None,
    applied_rule_id=None,
    decision=None,
    meter_index=None,
    effective_allowance=None,
    occurred_dt=None,
):
    occurred = occurred_dt or clock.now()
    event = new_entity(common_fields=False)
    event.update(
        {
            "reader_id": reader["id"],
            "article_id": article_id,
            "applied_rule_id": applied_rule_id,
            "event_type": event_type,
            "decision": decision,
            "meter_index": meter_index,
            "effective_allowance": effective_allowance,
            "weight": config.EVENT_WEIGHTS.get(event_type, 0),
            "occurred_at": format_datetime(occurred),
            "_occurred_dt": occurred,
        }
    )
    db.reader_events[event["id"]] = event
    mark_created(event)
    return event
