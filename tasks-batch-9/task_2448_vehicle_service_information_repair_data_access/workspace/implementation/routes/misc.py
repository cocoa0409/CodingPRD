"""The audit trail read and the logical-clock test hook."""

from flask import Blueprint

from auth import authenticate
from envelope import object_response
from store import store
from validate import body_object, check_allowed, get_dt, pagination, q_enum, q_str

from routes.common import EVENT_TYPES, SUBJECT_ENTITIES, paged

bp = Blueprint("misc", __name__)


@bp.get("/audit-events")
def list_audit_events():
    authenticate(("PlatformAdmin", "ComplianceOfficer"))
    subject_entity = q_enum("subject_entity", SUBJECT_ENTITIES)
    subject_id = q_str("subject_id")
    actor_user_id = q_str("actor_user_id")
    event_type = q_enum("event_type", EVENT_TYPES)
    limit, offset = pagination()

    rows = [
        row
        for row in store.audit_events.values()
        if (subject_entity is None or row["subject_entity"] == subject_entity)
        and (subject_id is None or row["subject_id"] == subject_id)
        and (actor_user_id is None or row["actor_user_id"] == actor_user_id)
        and (event_type is None or row["event_type"] == event_type)
    ]
    # PRD 2.3: occurred_at ASC with created_at ASC as the tie-breaker.
    rows.sort(key=lambda row: (row["occurred_at"], row["created_at"], row["_seq"]))
    return paged("audit_event", rows, limit, offset, presorted=True)


@bp.post("/_clock/set_current_utc")
def set_clock():
    authenticate(("PlatformAdmin",))
    body = body_object()
    check_allowed(body, ("to_iso8601",))
    raw, parsed = get_dt(body, "to_iso8601")
    store.set_clock(raw, parsed)
    return object_response({"current_utc": raw})
