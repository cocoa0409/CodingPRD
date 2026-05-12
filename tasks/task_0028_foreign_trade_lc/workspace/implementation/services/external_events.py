"""External event ingestion (idempotent on (source_system, idempotency_key))."""

import db
from errors import raise_error, ERR_INVALID_REQUEST, ERR_NOT_FOUND


VALID_SOURCES = {"BANKING", "CUSTOMS", "LOGISTICS", "SWIFT"}
VALID_EVENT_TYPES = {
    "BANK_PAYMENT_CONFIRMED", "CUSTOMS_DECLARATION_FILED", "SHIPMENT_DEPARTED",
    "SHIPMENT_DELIVERED", "SWIFT_ACK", "SWIFT_NAK",
}


def ingest(payload):
    if not isinstance(payload, dict):
        raise_error(ERR_INVALID_REQUEST, "JSON body required")

    src = payload.get("source_system")
    if src not in VALID_SOURCES:
        raise_error(ERR_INVALID_REQUEST, "source_system invalid")
    et = payload.get("event_type")
    if et not in VALID_EVENT_TYPES:
        raise_error(ERR_INVALID_REQUEST, "event_type invalid")
    lc_id = payload.get("lc_id")
    if not isinstance(lc_id, str) or not lc_id:
        raise_error(ERR_INVALID_REQUEST, "lc_id required")
    if db.get_by_id("letters_of_credit", lc_id) is None:
        raise_error(ERR_NOT_FOUND, "lc not found")
    idem = payload.get("idempotency_key")
    if not isinstance(idem, str) or not idem:
        raise_error(ERR_INVALID_REQUEST, "idempotency_key required")

    # Idempotent replay
    existing = db.find_one("external_events", source_system=src, idempotency_key=idem)
    if existing is not None:
        return existing, True

    pres_id = payload.get("presentation_id")
    if pres_id is not None and db.get_by_id("presentations", pres_id) is None:
        raise_error(ERR_NOT_FOUND, "presentation not found")

    body = payload.get("payload") or {}
    if not isinstance(body, dict):
        raise_error(ERR_INVALID_REQUEST, "payload must be object")

    event = db.insert("external_events", {
        "source_system": src,
        "event_type": et,
        "lc_id": lc_id,
        "presentation_id": pres_id,
        "idempotency_key": idem,
        "payload": body,
        "processed_at": db.now_iso(),
        "applied_side_effects": [],
    }, with_version=False)
    return event, False


def get_event(event_id):
    e = db.get_by_id("external_events", event_id)
    if e is None:
        raise_error(ERR_NOT_FOUND, "event not found")
    return e
