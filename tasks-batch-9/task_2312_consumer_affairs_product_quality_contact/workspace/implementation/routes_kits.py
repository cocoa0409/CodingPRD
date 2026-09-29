"""Sample-retrieval kits and their append-only chain of custody."""

from flask import Blueprint

import calc
import serializers as ser
import services as svc
from common import (
    ROLE_CARE_AGENT,
    ROLE_CARE_SUPERVISOR,
    ROLE_QUALITY_LEAD,
    authorize,
    base_record,
    check_required,
    err,
    get_body,
    must_get,
    now,
    pagination,
    paginated,
    q_str,
    sort_records,
    store,
    success,
    touch,
    v_datetime,
    v_enum,
    v_int,
    v_string,
)

bp = Blueprint("kits", __name__)

EVENT_TYPES = ("KIT_ISSUED", "CONSUMER_SEALED", "CARRIER_PICKUP", "LAB_RECEIVED", "LAB_OPENED")
OPEN_KIT_STATES = ("REQUESTED", "SHIPPED", "IN_TRANSIT_INBOUND", "RECEIVED")
APPENDABLE_STATES = ("SHIPPED", "IN_TRANSIT_INBOUND", "RECEIVED")


def _advance_parent_complaint(kit):
    """Kit acceptance, cancellation and expiry all release AWAITING_SAMPLE."""
    complaint = store.complaints.get(kit["complaint_id"])
    if complaint is not None and complaint["handling_status"] == "AWAITING_SAMPLE":
        complaint["handling_status"] = "IN_RESOLUTION"
        touch(complaint)


@bp.post("/sample-kits")
def create_kit():
    authorize([ROLE_CARE_AGENT, ROLE_CARE_SUPERVISOR])
    body = get_body()
    if "complaint_id" in body and body["complaint_id"] is not None:
        must_get("complaints", body["complaint_id"])
    check_required(body, ["complaint_id", "kit_code", "seal_id_issued"])
    complaint_id = v_string(body, "complaint_id", 1)
    kit_code = v_string(body, "kit_code", 1)
    seal_id_issued = v_string(body, "seal_id_issued", 1)

    for existing in store.sample_kits.values():
        if existing["kit_code"] == kit_code:
            raise err("ERR_DUPLICATE_CODE", "kit_code already exists")

    complaint = store.complaints[complaint_id]
    if complaint["handling_status"] != "TRIAGED":
        raise err(
            "ERR_COMPLAINT_STATE_INVALID", "a sample kit may only be requested for a TRIAGED complaint"
        )

    rec = base_record()
    rec.update(
        {
            "complaint_id": complaint_id,
            "consumer_id": complaint["consumer_id"],
            "kit_code": kit_code,
            "seal_id_issued": seal_id_issued,
            "status": "REQUESTED",
            "shipped_at": None,
            "expected_return_by": None,
            "occupied_from": None,
            "occupied_until": None,
            "received_at": None,
            "seal_id_returned": None,
            "transit_hours": None,
            "chain_integrity_status": "PENDING",
            "disposition": "PENDING",
            "custody_event_count": 0,
        }
    )
    store.sample_kits[rec["id"]] = rec

    complaint["handling_status"] = "AWAITING_SAMPLE"
    touch(complaint)
    ser.sync_consumer(store.consumers.get(rec["consumer_id"]))
    return success(ser.sample_kit(rec), 201)


@bp.get("/sample-kits")
def list_kits():
    authorize([ROLE_CARE_AGENT, ROLE_CARE_SUPERVISOR, ROLE_QUALITY_LEAD])
    limit, offset = pagination()
    filters = {
        "complaint_id": q_str("complaint_id"),
        "consumer_id": q_str("consumer_id"),
        "status": q_str("status"),
        "chain_integrity_status": q_str("chain_integrity_status"),
    }
    items = []
    for rec in sort_records(list(store.sample_kits.values())):
        if any(value is not None and rec.get(key) != value for key, value in filters.items()):
            continue
        items.append(ser.sample_kit(rec))
    return paginated(items, limit, offset)


@bp.get("/sample-kits/<record_id>")
def get_kit(record_id):
    authorize([ROLE_CARE_AGENT, ROLE_CARE_SUPERVISOR, ROLE_QUALITY_LEAD])
    rec = must_get("sample_kits", record_id)
    return success(ser.sample_kit(rec))


@bp.post("/sample-kits/<record_id>/ship")
def ship_kit(record_id):
    authorize([ROLE_CARE_AGENT, ROLE_CARE_SUPERVISOR])
    rec = must_get("sample_kits", record_id)
    body = get_body()
    v_string(body, "carrier_note", 0)

    if rec["status"] != "REQUESTED":
        raise err("ERR_SAMPLE_KIT_STATE_INVALID", "only a REQUESTED kit may be shipped")

    shipped_at = now()
    for other in sort_records(list(store.sample_kits.values())):
        if other["id"] == rec["id"] or other["consumer_id"] != rec["consumer_id"]:
            continue
        if other["status"] not in OPEN_KIT_STATES:
            continue
        start = other.get("occupied_from")
        end = other.get("occupied_until")
        if start is None or end is None:
            continue
        if start <= shipped_at <= end:
            raise err(
                "ERR_KIT_INTERVAL_CONFLICT",
                "the consumer already holds a kit occupying this instant",
            )

    consumer = store.consumers.get(rec["consumer_id"])
    if consumer is None or not consumer.get("postal_code"):
        raise err("ERR_CONSUMER_ADDRESS_MISSING", "the consumer has no postal_code on file")

    window = calc.kit_retention_window(shipped_at)
    rec["status"] = "SHIPPED"
    rec["shipped_at"] = window["shipped_at"]
    rec["expected_return_by"] = window["expected_return_by"]
    rec["occupied_from"] = window["occupied_from"]
    rec["occupied_until"] = window["occupied_until"]

    svc.append_custody_event(
        rec, "KIT_ISSUED", shipped_at, "SYSTEM", rec["seal_id_issued"], None
    )
    rec["custody_event_count"] = 1
    status, transit_hours = calc.custody_projection(rec)
    rec["chain_integrity_status"] = status
    if transit_hours is not None:
        rec["transit_hours"] = transit_hours
    touch(rec)
    return success(ser.sample_kit(rec))


@bp.post("/sample-kits/<record_id>/receive")
def receive_kit(record_id):
    authorize([ROLE_QUALITY_LEAD])
    rec = must_get("sample_kits", record_id)
    get_body()

    if rec["status"] != "IN_TRANSIT_INBOUND":
        raise err(
            "ERR_SAMPLE_KIT_STATE_INVALID", "only an IN_TRANSIT_INBOUND kit may be received"
        )
    lab_received = None
    for event in calc.kit_events(rec["id"]):
        if event["event_type"] == "LAB_RECEIVED":
            lab_received = event
            break
    if lab_received is None:
        raise err(
            "ERR_SAMPLE_KIT_STATE_INVALID", "no LAB_RECEIVED custody event has been appended"
        )

    rec["status"] = "RECEIVED"
    rec["received_at"] = now()
    rec["seal_id_returned"] = lab_received.get("seal_id_observed")
    status, transit_hours = calc.custody_projection(rec)
    rec["chain_integrity_status"] = status
    if transit_hours is not None:
        rec["transit_hours"] = transit_hours
    touch(rec)
    return success(ser.sample_kit(rec))


@bp.post("/sample-kits/<record_id>/lab-accept")
def lab_accept_kit(record_id):
    authorize([ROLE_QUALITY_LEAD])
    rec = must_get("sample_kits", record_id)
    body = get_body()
    v_string(body, "lab_note", 0)

    if rec["status"] != "RECEIVED":
        raise err("ERR_SAMPLE_KIT_STATE_INVALID", "only a RECEIVED kit may be accepted")
    if rec["custody_event_count"] != len(calc.REQUIRED_SEQUENCE):
        raise err(
            "ERR_SAMPLE_KIT_STATE_INVALID", "the custody chain is not complete at five events"
        )

    status, transit_hours = calc.custody_projection(rec)
    rec["chain_integrity_status"] = status
    if transit_hours is not None:
        rec["transit_hours"] = transit_hours
    rec["status"] = "LAB_ACCEPTED"
    rec["disposition"] = "USABLE" if status == "INTACT" else "UNUSABLE"
    touch(rec)

    _advance_parent_complaint(rec)
    ser.sync_consumer(store.consumers.get(rec["consumer_id"]))
    return success(ser.sample_kit(rec))


@bp.post("/sample-kits/<record_id>/cancel")
def cancel_kit(record_id):
    authorize([ROLE_CARE_SUPERVISOR])
    rec = must_get("sample_kits", record_id)
    body = get_body()
    v_string(body, "reason", 0)

    if rec["status"] not in ("REQUESTED", "SHIPPED"):
        raise err(
            "ERR_SAMPLE_KIT_STATE_INVALID", "only a REQUESTED or SHIPPED kit may be cancelled"
        )
    rec["status"] = "CANCELLED"
    touch(rec)
    _advance_parent_complaint(rec)
    ser.sync_consumer(store.consumers.get(rec["consumer_id"]))
    return success(ser.sample_kit(rec))


@bp.post("/sample-kits/<record_id>/custody-events")
def append_custody_event(record_id):
    authorize([ROLE_CARE_AGENT, ROLE_CARE_SUPERVISOR, ROLE_QUALITY_LEAD])
    rec = must_get("sample_kits", record_id)
    body = get_body()
    check_required(body, ["event_type", "occurred_at", "actor_label", "expected_sample_kit_version"])
    event_type = v_enum(body, "event_type", EVENT_TYPES)
    occurred_at = v_datetime(body, "occurred_at")
    actor_label = v_string(body, "actor_label", 1)
    expected_version = v_int(body, "expected_sample_kit_version", 0)
    seal_id_observed = v_string(body, "seal_id_observed", 0)
    notes = v_string(body, "notes", 0)

    if expected_version != rec["version"]:
        raise err(
            "ERR_STALE_SAMPLE_KIT_VERSION",
            "expected_sample_kit_version does not match the kit's current version",
        )

    if rec["status"] not in APPENDABLE_STATES:
        raise err(
            "ERR_SAMPLE_KIT_STATE_INVALID", "the kit's status does not permit a custody append"
        )

    events = calc.kit_events(rec["id"])
    if events and occurred_at < events[-1]["occurred_at"]:
        raise err(
            "ERR_CUSTODY_OUT_OF_ORDER",
            "occurred_at is earlier than the previous custody event",
        )

    position = len(events)
    if position >= len(calc.REQUIRED_SEQUENCE) or event_type != calc.REQUIRED_SEQUENCE[position]:
        raise err(
            "ERR_CUSTODY_SEQUENCE_INVALID",
            "the appended event_type is not the one required at this position",
        )
    if event_type == "CARRIER_PICKUP" and (
        rec["status"] != "SHIPPED" or events[-1]["event_type"] != "CONSUMER_SEALED"
    ):
        raise err(
            "ERR_SAMPLE_KIT_STATE_INVALID",
            "CARRIER_PICKUP requires a SHIPPED kit sealed by the consumer",
        )

    event = svc.append_custody_event(
        rec, event_type, occurred_at, actor_label, seal_id_observed, notes
    )
    rec["custody_event_count"] = position + 1
    if event_type == "CARRIER_PICKUP":
        rec["status"] = "IN_TRANSIT_INBOUND"
    status, transit_hours = calc.custody_projection(rec)
    rec["chain_integrity_status"] = status
    if transit_hours is not None:
        rec["transit_hours"] = transit_hours
    touch(rec)
    return success(ser.custody_event(event), 201)


@bp.get("/sample-kits/<record_id>/custody-events")
def list_custody_events(record_id):
    authorize([ROLE_CARE_AGENT, ROLE_CARE_SUPERVISOR, ROLE_QUALITY_LEAD])
    must_get("sample_kits", record_id)
    limit, offset = pagination()
    items = [ser.custody_event(e) for e in calc.kit_events(record_id)]
    return paginated(items, limit, offset)
