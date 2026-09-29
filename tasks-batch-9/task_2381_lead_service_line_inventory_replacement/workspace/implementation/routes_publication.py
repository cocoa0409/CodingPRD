"""Inventory publications and the customer-notification chase."""

from datetime import timedelta

from flask import Blueprint, g

import logic
import lookup
from core import (
    body_json, by_created_at, db, endpoint, fail, field, filter_arg,
    filter_bool, iso_ms, new_row, paginate, parse_date, parse_datetime,
    read_pagination, respond_list, respond_object, touch, validate_body,
)

bp = Blueprint("publication", __name__)

BASES = ("RECORDS", "FIELD_VERIFIED")
CHANNELS = ("MAIL", "EMAIL", "DOOR_HANGER")
RETURN_REASONS = ("ADDRESS_INVALID", "REFUSED", "VACANT")
NOTIFIABLE = ("LEAD", "GRR", "UNKNOWN")

PUB_READ_ROLES = ["ProgramAdministrator", "InventoryAnalyst", "ComplianceOfficer",
                  "CustomerRepresentative"]


# --------------------------------------------------------- InventoryPublication
@bp.post("/lsl/inventory-publications")
@endpoint(["InventoryAnalyst"])
def draft_publication():
    data = validate_body(body_json(), [
        field("water_system_id", "string", required=True),
        field("basis", "string", required=True, enum=BASES),
        field("reporting_period_label", "string", required=True, nonempty=True),
        field("expected_water_system_version", "integer", required=True),
    ])
    ws = lookup.water_system(data["water_system_id"])
    if data["expected_water_system_version"] != ws["version"]:
        fail("ERR_STALE_WATER_SYSTEM_VERSION",
             "expected_water_system_version %s does not match the live version %s."
             % (data["expected_water_system_version"], ws["version"]))
    if logic.program_posture(ws) == "FROZEN":
        fail("ERR_PROGRAM_POSTURE_FROZEN",
             "The program posture is FROZEN; an inventory publication may not be "
             "drafted.")

    # A new draft supersedes and discards any prior DRAFT of this water system.
    for stale in [p for p in db.publications.values()
                  if p["water_system_id"] == ws["id"] and p["state"] == "DRAFT"]:
        del db.publications[stale["id"]]

    pub = new_row()
    pub.update({
        "water_system_id": ws["id"],
        "basis": data["basis"],
        "reporting_period_label": data["reporting_period_label"],
        "drafted_by_user_id": g.user_id,
        "certified_by_user_id": None,
        "state": "DRAFT",
        "pinned_lead_count": None,
        "pinned_grr_count": None,
        "pinned_unknown_count": None,
        "pinned_non_lead_count": None,
        "notifiable_line_count": None,
        "published_at": None,
        "notification_due_at": None,
        "supersede_reason": None,
    })
    db.publications[pub["id"]] = pub
    touch(ws)
    return respond_object(logic.serialize_publication(pub), 201)


@bp.get("/lsl/inventory-publications")
@endpoint(PUB_READ_ROLES)
def list_publications():
    limit, offset = read_pagination()
    rows = by_created_at(list(db.publications.values()))
    for name in ("water_system_id", "state", "basis"):
        value = filter_arg(name)
        if value is not None:
            rows = [r for r in rows if r[name] == value]
    page, total = paginate(rows, limit, offset)
    return respond_list([logic.serialize_publication(r) for r in page],
                        limit, offset, total)


@bp.get("/lsl/inventory-publications/<pub_id>")
@endpoint(PUB_READ_ROLES)
def read_publication(pub_id):
    pub = lookup.publication(pub_id)
    return respond_object(logic.serialize_publication(pub))


@bp.post("/lsl/inventory-publications/<pub_id>/certify")
@endpoint(["ComplianceOfficer"])
def certify_publication(pub_id):
    pub = lookup.publication(pub_id)
    if g.user_id == pub["drafted_by_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES",
             "The analyst that drafted this publication may not certify it.")
    if pub["state"] != "DRAFT":
        fail("ERR_PUBLICATION_STATE_INVALID",
             "Certification requires state DRAFT, not %s." % pub["state"])

    ws = db.water_systems.get(pub["water_system_id"])
    batches = logic.batches_of_system(pub["water_system_id"])
    if not batches or any(b["state"] != "VALIDATED" for b in batches):
        fail("ERR_UNVALIDATED_SAMPLING_STRATUM",
             "The water system must carry at least one sampling batch and every "
             "batch must be VALIDATED.")
    for note in logic.notifications_of_system(pub["water_system_id"]):
        if logic.notification_overdue(note):
            fail("ERR_NOTIFICATION_OVERDUE_BLOCK",
                 "A customer notification of this water system is overdue.")
    deadline = parse_date(ws["compliance_deadline_date"]) if ws else None
    if deadline is not None and db.clock.date() > deadline:
        fail("ERR_COMPLIANCE_DEADLINE_PASSED",
             "The regulatory compliance deadline %s has passed."
             % ws["compliance_deadline_date"])

    counts = logic.system_counts(ws)
    pub["state"] = "CERTIFIED"
    pub["certified_by_user_id"] = g.user_id
    pub["pinned_lead_count"] = counts["lead_count"]
    pub["pinned_grr_count"] = counts["grr_count"]
    pub["pinned_unknown_count"] = counts["unknown_count"]
    pub["pinned_non_lead_count"] = counts["non_lead_count"]
    pub["notifiable_line_count"] = (counts["lead_count"] + counts["grr_count"]
                                    + counts["unknown_count"])
    touch(pub)
    return respond_object(logic.serialize_publication(pub))


@bp.post("/lsl/inventory-publications/<pub_id>/publish")
@endpoint(["ComplianceOfficer"])
def publish_publication(pub_id):
    pub = lookup.publication(pub_id)
    if pub["state"] != "CERTIFIED":
        fail("ERR_PUBLICATION_STATE_INVALID",
             "Publishing requires state CERTIFIED, not %s." % pub["state"])

    ws = db.water_systems.get(pub["water_system_id"])
    notifiable = [l for l in logic.lines_of_system(pub["water_system_id"])
                  if l["classification"] in NOTIFIABLE]
    if pub["notifiable_line_count"] != len(notifiable):
        fail("ERR_PINNED_SNAPSHOT_STALE",
             "The pinned notifiable count %s no longer matches the live count %d."
             % (pub["notifiable_line_count"], len(notifiable)))

    published_at = db.clock
    pub["state"] = "PUBLISHED"
    pub["published_at"] = iso_ms(published_at)
    pub["notification_due_at"] = iso_ms(published_at + timedelta(days=30))
    touch(pub)

    # LINK 1 -- one PENDING notification per notifiable line.
    for line in notifiable:
        note = new_row()
        note.update({
            "service_line_id": line["id"],
            "inventory_publication_id": pub["id"],
            "notified_classification": line["classification"],
            "state": "PENDING",
            "delivery_channel": None,
            "delivered_at": None,
            "acknowledged_at": None,
            "return_reason": None,
            "delivery_attempt_count": 0,
            "due_at": pub["notification_due_at"],
        })
        db.notifications[note["id"]] = note

    # LINK 2 / LINK 3 -- the counter and the posture are derived on read, so they
    # are already refreshed for every subsequent observer.
    if ws is not None and ws["inventory_status"] != "PUBLISHED":
        ws["inventory_status"] = "PUBLISHED"
        touch(ws)

    # A later publication supersedes the earlier PUBLISHED one.
    for other in by_created_at(list(db.publications.values())):
        if other["id"] == pub["id"] or other["water_system_id"] != pub["water_system_id"]:
            continue
        if other["state"] == "PUBLISHED":
            other["state"] = "SUPERSEDED"
            other["supersede_reason"] = "AMENDED_BY_NEWER_PUBLICATION"
            touch(other)

    return respond_object(logic.serialize_publication(pub))


# --------------------------------------------------------- CustomerNotification
@bp.get("/lsl/customer-notifications")
@endpoint(PUB_READ_ROLES)
def list_notifications():
    limit, offset = read_pagination()
    rows = by_created_at(list(db.notifications.values()))
    for name in ("service_line_id", "inventory_publication_id", "state"):
        value = filter_arg(name)
        if value is not None:
            rows = [r for r in rows if r[name] == value]
    flag = filter_bool("overdue")
    if flag is not None:
        rows = [r for r in rows if logic.notification_overdue(r) == flag]
    page, total = paginate(rows, limit, offset)
    return respond_list([logic.serialize_notification(r) for r in page],
                        limit, offset, total)


@bp.get("/lsl/customer-notifications/<note_id>")
@endpoint(PUB_READ_ROLES)
def read_notification(note_id):
    note = lookup.notification(note_id)
    return respond_object(logic.serialize_notification(note))


@bp.post("/lsl/customer-notifications/<note_id>/deliver")
@endpoint(["CustomerRepresentative"])
def deliver_notification(note_id):
    data = validate_body(body_json(), [
        field("delivery_channel", "string", required=True, enum=CHANNELS),
        field("delivered_at", "datetime", required=True),
    ])
    note = lookup.notification(note_id)
    if note["state"] not in ("PENDING", "RETURNED"):
        fail("ERR_NOTIFICATION_STATE_INVALID",
             "Delivery is legal from PENDING or RETURNED, not from %s."
             % note["state"])

    note["state"] = "DELIVERED"
    note["delivery_channel"] = data["delivery_channel"]
    note["delivered_at"] = data["delivered_at"]
    note["delivery_attempt_count"] = note["delivery_attempt_count"] + 1
    note["return_reason"] = None
    touch(note)
    return respond_object(logic.serialize_notification(note))


@bp.post("/lsl/customer-notifications/<note_id>/acknowledge")
@endpoint(["CustomerRepresentative"])
def acknowledge_notification(note_id):
    data = validate_body(body_json(), [
        field("acknowledged_at", "datetime", required=True),
    ])
    note = lookup.notification(note_id)
    if note["state"] != "DELIVERED":
        fail("ERR_NOTIFICATION_STATE_INVALID",
             "Acknowledgement requires state DELIVERED, not %s." % note["state"])

    note["state"] = "ACKNOWLEDGED"
    note["acknowledged_at"] = data["acknowledged_at"]
    touch(note)
    return respond_object(logic.serialize_notification(note))


@bp.post("/lsl/customer-notifications/<note_id>/return")
@endpoint(["CustomerRepresentative"])
def return_notification(note_id):
    data = validate_body(body_json(), [
        field("return_reason", "string", required=True, enum=RETURN_REASONS),
    ])
    note = lookup.notification(note_id)
    if note["state"] != "DELIVERED":
        fail("ERR_NOTIFICATION_STATE_INVALID",
             "A return requires state DELIVERED, not %s." % note["state"])

    note["state"] = "RETURNED"
    note["return_reason"] = data["return_reason"]
    note["delivered_at"] = None
    touch(note)
    return respond_object(logic.serialize_notification(note))
