"""CredentialRequest endpoints (PRD 3.4)."""

from flask import Blueprint

from db import base_record, db, public, sort_created_asc, touch
from errors import ApiError
from middleware import auth, f_dt, f_enum, f_int, f_str, get_body, q
from response import ok
from services import calc
from services.domain import (
    append_audit,
    create_ticket_record,
    get_or_404,
    recompute_zone_posture,
)
from routes._common import filter_eq, paginated

bp = Blueprint("credentials", __name__)

CREDENTIAL_READERS = ("BoxOfficeAgent", "TicketingApprover", "SecurityInvestigator", "VenueAdmin")
DISTRIBUTION_TYPES = ("COMP", "WILL_CALL", "CREDENTIAL")


@bp.route("/credential-requests", methods=["POST"])
def draft_request():
    auth(("BoxOfficeAgent",))
    body = get_body()
    event_id = f_str(body, "event_id", allow_empty=False)
    access_zone_id = f_str(body, "access_zone_id", allow_empty=False)
    recipient_patron_id = f_str(body, "recipient_patron_id", allow_empty=False)
    distribution_type = f_enum(body, "distribution_type", DISTRIBUTION_TYPES)
    quantity = f_int(body, "quantity", minimum=1, maximum=50)
    valid_from_raw, valid_from_dt = f_dt(body, "valid_from")
    valid_until_raw, valid_until_dt = f_dt(body, "valid_until")
    justification = f_str(body, "justification", allow_empty=False)
    if valid_until_dt <= valid_from_dt:
        raise ApiError("ERR_INVALID_REQUEST", "'valid_until' must be strictly after 'valid_from'.")

    get_or_404(db.events, event_id, "ERR_EVENT_NOT_FOUND")
    zone = get_or_404(db.zones, access_zone_id, "ERR_ZONE_NOT_FOUND")
    recipient = get_or_404(db.patrons, recipient_patron_id, "ERR_PATRON_NOT_FOUND")
    if zone["event_id"] != event_id:
        raise ApiError("ERR_CROSS_EVENT_REFERENCE")

    rec = base_record()
    rec["event_id"] = event_id
    rec["access_zone_id"] = access_zone_id
    rec["recipient_patron_id"] = recipient["id"]
    rec["distribution_type"] = distribution_type
    rec["quantity"] = quantity
    rec["valid_from"] = valid_from_raw
    rec["valid_until"] = valid_until_raw
    rec["justification"] = justification
    rec["requested_by_user_id"] = None
    rec["approved_by_user_id"] = None
    rec["status"] = "DRAFT"
    rec["revision_count"] = 0
    rec["issued_ticket_count"] = 0
    rec["forgone_revenue_cents"] = 0
    rec["_valid_from_dt"] = valid_from_dt
    rec["_valid_until_dt"] = valid_until_dt
    db.credential_requests[rec["id"]] = rec
    return ok(public(rec), 201)


@bp.route("/credential-requests/<request_id>", methods=["GET"])
def get_request(request_id):
    auth(CREDENTIAL_READERS)
    record = get_or_404(db.credential_requests, request_id, "ERR_CREDENTIAL_REQUEST_NOT_FOUND")
    return ok(public(record))


@bp.route("/credential-requests", methods=["GET"])
def list_requests():
    auth(CREDENTIAL_READERS)
    rows = sort_created_asc(list(db.credential_requests.values()))
    rows = filter_eq(rows, "event_id", q("event_id"))
    rows = filter_eq(rows, "access_zone_id", q("access_zone_id"))
    rows = filter_eq(rows, "recipient_patron_id", q("recipient_patron_id"))
    rows = filter_eq(rows, "status", q("status"))
    rows = filter_eq(rows, "distribution_type", q("distribution_type"))
    return paginated(rows)


@bp.route("/credential-requests/<request_id>/submit", methods=["POST"])
def submit_request(request_id):
    user_id, role = auth(("BoxOfficeAgent",))
    record = get_or_404(db.credential_requests, request_id, "ERR_CREDENTIAL_REQUEST_NOT_FOUND")
    if record["status"] not in ("DRAFT", "CHANGES_REQUESTED"):
        raise ApiError("ERR_INVALID_STATE", "Only a DRAFT or CHANGES_REQUESTED request may be submitted.")

    event = db.events[record["event_id"]]
    zone = db.zones[record["access_zone_id"]]
    if event["status"] not in ("ON_SALE", "DOORS_OPEN"):
        raise ApiError("ERR_EVENT_STATE_FORBIDS_OPERATION")
    if zone["posture"] == "FROZEN":
        raise ApiError("ERR_ZONE_FROZEN")

    resubmission = record["status"] == "CHANGES_REQUESTED"
    if resubmission and record["revision_count"] >= calc.MAX_CREDENTIAL_REVISIONS:
        raise ApiError("ERR_MAX_REVISIONS_EXCEEDED")

    record["status"] = "SUBMITTED"
    record["requested_by_user_id"] = user_id
    if resubmission:
        record["revision_count"] += 1
    touch(record)

    append_audit(
        event["id"], "CREDENTIAL_REQUEST", record["id"], "CREDENTIAL_REQUEST_SUBMITTED",
        role, user_id,
        "Credential request %s submitted (%s x%d, revision_count %d): %s"
        % (record["id"], record["distribution_type"], record["quantity"],
           record["revision_count"], record["justification"]),
    )
    return ok(public(record))


@bp.route("/credential-requests/<request_id>/request-changes", methods=["POST"])
def request_changes(request_id):
    user_id, role = auth(("TicketingApprover",))
    body = get_body()
    note = f_str(body, "note", allow_empty=False)
    record = get_or_404(db.credential_requests, request_id, "ERR_CREDENTIAL_REQUEST_NOT_FOUND")
    if record["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", "Only a SUBMITTED request may be returned for revision.")

    record["status"] = "CHANGES_REQUESTED"
    touch(record)
    append_audit(
        record["event_id"], "CREDENTIAL_REQUEST", record["id"],
        "CREDENTIAL_REQUEST_CHANGES_REQUESTED", role, user_id,
        "Credential request %s returned for revision: %s" % (record["id"], note),
    )
    return ok(public(record))


@bp.route("/credential-requests/<request_id>/approve", methods=["POST"])
def approve_request(request_id):
    user_id, role = auth(("TicketingApprover",))
    body = get_body()
    note = f_str(body, "note", required=False)
    record = get_or_404(db.credential_requests, request_id, "ERR_CREDENTIAL_REQUEST_NOT_FOUND")
    if record["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", "Only a SUBMITTED request may be approved.")

    event = db.events[record["event_id"]]
    zone = db.zones[record["access_zone_id"]]
    if event["status"] not in ("ON_SALE", "DOORS_OPEN"):
        raise ApiError("ERR_EVENT_STATE_FORBIDS_OPERATION")
    if zone["posture"] == "FROZEN":
        raise ApiError("ERR_ZONE_FROZEN")
    if record["requested_by_user_id"] == user_id:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    if record["distribution_type"] == "CREDENTIAL":
        overlapping = record["quantity"]
        for other in db.credential_requests.values():
            if other["id"] == record["id"]:
                continue
            if other["status"] != "APPROVED" or other["distribution_type"] != "CREDENTIAL":
                continue
            if other["access_zone_id"] != record["access_zone_id"]:
                continue
            if calc.windows_overlap(
                record["_valid_from_dt"], record["_valid_until_dt"],
                other["_valid_from_dt"], other["_valid_until_dt"],
            ):
                overlapping += other["quantity"]
        if overlapping > zone["credential_capacity"]:
            raise ApiError("ERR_ZONE_CREDENTIAL_WINDOW_CAPACITY")

    # Cascade, in the pinned order of PRD 3.4.
    per_ticket, total_forgone = calc.credential_forgone_revenue(zone, record["quantity"])
    record["forgone_revenue_cents"] = total_forgone

    for _ in range(record["quantity"]):
        create_ticket_record(
            record["event_id"], record["access_zone_id"], record["recipient_patron_id"],
            record["distribution_type"], 0, credential_request_id=record["id"],
        )
        zone["issued_entitlement_count"] += 1
        zone["comp_forgone_cents"] += per_ticket
        event["entitlements_outstanding"] += 1

    recompute_zone_posture(zone)
    touch(zone)
    touch(event)

    record["issued_ticket_count"] = record["quantity"]
    record["status"] = "APPROVED"
    record["approved_by_user_id"] = user_id
    touch(record)

    append_audit(
        event["id"], "CREDENTIAL_REQUEST", record["id"], "CREDENTIAL_REQUEST_APPROVED",
        role, user_id,
        "Credential request %s approved: %d %s tickets issued, forgone revenue %d cents%s"
        % (record["id"], record["quantity"], record["distribution_type"], total_forgone,
           ("; " + note) if note else ""),
    )
    return ok(public(record))


@bp.route("/credential-requests/<request_id>/reject", methods=["POST"])
def reject_request(request_id):
    user_id, role = auth(("TicketingApprover",))
    body = get_body()
    note = f_str(body, "note", allow_empty=False)
    record = get_or_404(db.credential_requests, request_id, "ERR_CREDENTIAL_REQUEST_NOT_FOUND")
    if record["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", "Only a SUBMITTED request may be rejected.")
    if record["requested_by_user_id"] == user_id:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    record["status"] = "REJECTED"
    record["approved_by_user_id"] = user_id
    touch(record)
    append_audit(
        record["event_id"], "CREDENTIAL_REQUEST", record["id"],
        "CREDENTIAL_REQUEST_REJECTED", role, user_id,
        "Credential request %s rejected, no tickets issued: %s" % (record["id"], note),
    )
    return ok(public(record))
