"""Path/foreign-key resolution and list assembly helpers."""
from db import Ctx, store
from errors import ApiError
from validation import bad

NOT_FOUND = {
    "resident": "ERR_RESIDENT_NOT_FOUND",
    "assessment": "ERR_ASSESSMENT_NOT_FOUND",
    "plan": "ERR_PLAN_NOT_FOUND",
    "program": "ERR_PROGRAM_NOT_FOUND",
    "room": "ERR_ROOM_NOT_FOUND",
    "session": "ERR_SESSION_NOT_FOUND",
    "record": "ERR_PARTICIPATION_RECORD_NOT_FOUND",
    "volunteer": "ERR_VOLUNTEER_NOT_FOUND",
    "assignment": "ERR_ASSIGNMENT_NOT_FOUND",
    "vehicle": "ERR_VEHICLE_NOT_FOUND",
    "outing": "ERR_OUTING_NOT_FOUND",
    "consent": "ERR_CONSENT_NOT_FOUND",
    "council_request": "ERR_COUNCIL_REQUEST_NOT_FOUND",
    "packet": "ERR_SURVEY_PACKET_NOT_FOUND",
}

COLLECTION = {
    "resident": "residents",
    "assessment": "assessments",
    "plan": "plans",
    "program": "programs",
    "room": "rooms",
    "session": "sessions",
    "record": "participation",
    "volunteer": "volunteers",
    "assignment": "assignments",
    "vehicle": "vehicles",
    "outing": "outings",
    "consent": "consents",
    "council_request": "council_requests",
    "packet": "packets",
}


def find(kind, identifier):
    collection = getattr(store, COLLECTION[kind])
    if not isinstance(identifier, str):
        return None
    return collection.get(identifier)


def load(kind, identifier):
    """Path identifier resolution: first failure wins."""
    entity = find(kind, identifier)
    if entity is None:
        raise ApiError(NOT_FOUND[kind])
    return entity


def resolve_fk(body, field, kind):
    """Body foreign keys resolve in declared field order, after path ids."""
    if field not in body or body[field] is None:
        return None
    entity = find(kind, body[field])
    if entity is None:
        raise ApiError(NOT_FOUND[kind])
    return entity


def ctx():
    return Ctx(store)


def paginate(rows, limit, offset):
    total = len(rows)
    return rows[offset : offset + limit], total


def sort_rows(rows, key, reverse=False):
    return sorted(rows, key=key, reverse=reverse)


def require_true(condition, error_id, message=None):
    if not condition:
        raise ApiError(error_id, message)


def new_entity(extra=None):
    from db import new_id

    entity = {
        "id": new_id(),
        "created_at": store.now_iso(),
        "updated_at": store.now_iso(),
        "version": 1,
        "_seq": store.next_seq(),
    }
    if extra:
        entity.update(extra)
    return entity


def no_body_fields(body):
    if body:
        bad("This endpoint accepts no request body fields.")
