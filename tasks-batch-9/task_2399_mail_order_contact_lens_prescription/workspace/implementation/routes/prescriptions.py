"""Prescription capture, the submit fork, verification rounds and the audit trail."""

from flask import Blueprint

from db import db, make_row, sort_rows, today, touch
from errors import ApiError
from middleware import (
    ROLE_ADMIN,
    ROLE_COMPLIANCE,
    ROLE_CUSTOMER,
    ROLE_PRESCRIBER,
    identity,
    lookup,
    paginate,
    parse_body,
    parse_pagination,
    parse_query,
    require_owner,
    require_prescriber_link,
    require_role,
)
from response import list_response, object_response
from services import calc
from services.events import append_event
from services.ledger import reconcile_customer_id
from services.workflow import open_hold, supersede_prescription

bp = Blueprint("prescriptions", __name__)

CAPTURE_MODES = ("UPLOAD", "DOCTOR_LOOKUP", "SELF_REPORT")
PRESCRIPTION_STATUSES = (
    "DRAFT",
    "PENDING_VERIFICATION",
    "CORRECTION_PENDING",
    "VERIFIED_ACTIVE",
    "INVALIDATED",
    "EXPIRED",
)
EVENT_TYPES = (
    "RX_SUBMITTED",
    "REQUEST_SENT",
    "RESPONSE_RECEIVED",
    "PASSIVE_PROMOTED",
    "RX_EXPIRED",
    "RX_INVALIDATED",
    "HOLD_OPENED",
    "HOLD_RELEASED",
    "HOLD_ESCALATED",
    "ORDER_BLOCKED",
    "ORDER_CANCELLED",
    "SUBSTITUTION_APPLIED",
    "DISPUTE_FILED",
    "DISPUTE_RESOLVED",
    "CLAIM_VOIDED",
    "SCHEDULE_PAUSED",
)


def _capture_evidence(capture_mode, document_reference, prescriber_id, self_reported_name):
    """Validations 15, 16 and 17, in priority order."""
    if capture_mode == "UPLOAD" and not document_reference:
        raise ApiError("ERR_CAPTURE_MODE_REQUIRES_DOCUMENT")
    if capture_mode == "DOCTOR_LOOKUP" and not prescriber_id:
        raise ApiError("ERR_CAPTURE_MODE_REQUIRES_PRESCRIBER")
    if capture_mode == "SELF_REPORT" and not self_reported_name:
        raise ApiError("ERR_SELF_REPORT_REQUIRES_NAME")


def _overlaps(left, right):
    """Half-open [issue_date, expiry_date) overlap; touching intervals do not overlap."""
    return left["issue_date"] < right["expiry_date"] and right["issue_date"] < left["expiry_date"]


@bp.post("/prescriptions")
def create_prescription():
    user_id, role = identity()
    body = parse_body(
        {
            "customer_id": {"type": "uuid", "required": True},
            "product_id": {"type": "uuid", "required": True},
            "capture_mode": {"type": "enum", "values": CAPTURE_MODES, "required": True},
            "issue_date": {"type": "date", "required": True},
            "expiry_date": {"type": "date", "required": True},
            "od_sphere": {"type": "decimal", "required": True, "places": 2},
            "os_sphere": {"type": "decimal", "required": True, "places": 2},
            "base_curve": {"type": "decimal", "required": True, "places": 2},
            "diameter": {"type": "decimal", "required": True, "places": 2},
            "boxes_authorized_total": {"type": "int", "required": True, "min": 1},
            "prescriber_id": {"type": "uuid"},
            "supersedes_prescription_id": {"type": "uuid"},
            "document_reference": {"type": "string"},
            "self_reported_prescriber_name": {"type": "string"},
        }
    )
    require_role(role, [ROLE_CUSTOMER, ROLE_ADMIN])
    customer = lookup("customer", body["customer_id"])
    lookup("product", body["product_id"])
    if body["prescriber_id"] is not None:
        lookup("prescriber", body["prescriber_id"])
    if body["supersedes_prescription_id"] is not None:
        lookup("prescription", body["supersedes_prescription_id"])
    require_owner(role, user_id, customer["id"])
    if body["expiry_date"] <= body["issue_date"]:
        raise ApiError("ERR_EXPIRY_BEFORE_ISSUE")
    _capture_evidence(
        body["capture_mode"],
        body["document_reference"],
        body["prescriber_id"],
        body["self_reported_prescriber_name"],
    )
    row = make_row(
        {
            "customer_id": body["customer_id"],
            "prescriber_id": body["prescriber_id"],
            "product_id": body["product_id"],
            "supersedes_prescription_id": body["supersedes_prescription_id"],
            "capture_mode": body["capture_mode"],
            "document_reference": body["document_reference"],
            "self_reported_prescriber_name": body["self_reported_prescriber_name"],
            "issue_date": body["issue_date"],
            "expiry_date": body["expiry_date"],
            "od_sphere": body["od_sphere"],
            "os_sphere": body["os_sphere"],
            "base_curve": body["base_curve"],
            "diameter": body["diameter"],
            "boxes_authorized_total": body["boxes_authorized_total"],
            "boxes_consumed": 0,
            "verification_rounds": 0,
            "status": "DRAFT",
        }
    )
    db.prescriptions[row["id"]] = row
    return object_response(row, 201)


@bp.get("/prescriptions/<prescription_id>")
def get_prescription(prescription_id):
    user_id, role = identity()
    parse_query({})
    require_role(role, [ROLE_ADMIN, ROLE_COMPLIANCE, ROLE_CUSTOMER, ROLE_PRESCRIBER])
    prescription = lookup("prescription", prescription_id)
    require_owner(role, user_id, prescription["customer_id"])
    require_prescriber_link(role, user_id, prescription["prescriber_id"])
    return object_response(prescription)


@bp.get("/prescriptions")
def list_prescriptions():
    user_id, role = identity()
    filters = parse_query(
        {
            "customer_id": {"type": "string"},
            "prescriber_id": {"type": "string"},
            "product_id": {"type": "string"},
            "supersedes_prescription_id": {"type": "string"},
            "status": {"type": "enum", "values": PRESCRIPTION_STATUSES},
        }
    )
    limit, offset = parse_pagination()
    require_role(role, [ROLE_ADMIN, ROLE_COMPLIANCE, ROLE_CUSTOMER, ROLE_PRESCRIBER])
    rows = list(db.prescriptions.values())
    if role == ROLE_CUSTOMER:
        rows = [r for r in rows if r["customer_id"] == user_id]
    if role == ROLE_PRESCRIBER:
        rows = [r for r in rows if r["prescriber_id"] == user_id]
    for field in ("customer_id", "prescriber_id", "product_id", "supersedes_prescription_id"):
        if filters[field]:
            rows = [r for r in rows if r[field] == filters[field]]
    if filters["status"]:
        rows = [r for r in rows if r["status"] == filters["status"]]
    page, total = paginate(sort_rows(rows), limit, offset)
    return list_response(page, limit, offset, total)


@bp.post("/prescriptions/<prescription_id>/submit")
def submit_prescription(prescription_id):
    user_id, role = identity()
    parse_body({})
    require_role(role, [ROLE_CUSTOMER, ROLE_ADMIN])
    prescription = lookup("prescription", prescription_id)
    require_owner(role, user_id, prescription["customer_id"])
    if prescription["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    if prescription["expiry_date"] <= today():
        raise ApiError("ERR_PRESCRIPTION_EXPIRED")
    _capture_evidence(
        prescription["capture_mode"],
        prescription["document_reference"],
        prescription["prescriber_id"],
        prescription["self_reported_prescriber_name"],
    )
    actor = (role, user_id)

    if prescription["capture_mode"] == "UPLOAD":
        superseded_id = prescription["supersedes_prescription_id"]
        for other in sort_rows(list(db.prescriptions.values())):
            if other["id"] == prescription["id"]:
                continue
            if other["customer_id"] != prescription["customer_id"]:
                continue
            if other["status"] not in ("VERIFIED_ACTIVE", "PENDING_VERIFICATION"):
                continue
            if not _overlaps(prescription, other):
                continue
            if superseded_id is not None and other["id"] == superseded_id:
                continue
            raise ApiError("ERR_PRESCRIPTION_INTERVAL_OVERLAP")
        prescription["status"] = "VERIFIED_ACTIVE"
        touch(prescription)
        append_event(
            prescription["id"],
            "RX_SUBMITTED",
            "Prescription",
            prescription["id"],
            actor,
            "upload accepted",
        )
        if superseded_id is not None:
            supersede_prescription(db.prescriptions.get(superseded_id), actor)
    else:
        prescription["status"] = "PENDING_VERIFICATION"
        touch(prescription)
        append_event(
            prescription["id"],
            "RX_SUBMITTED",
            "Prescription",
            prescription["id"],
            actor,
            "awaiting prescriber verification",
        )
    return object_response(prescription)


@bp.post("/prescriptions/<prescription_id>/verification-requests")
def send_verification_request(prescription_id):
    user_id, role = identity()
    body = parse_body({"prescriber_id": {"type": "uuid", "required": True}})
    require_role(role, [ROLE_COMPLIANCE, ROLE_ADMIN])
    prescription = lookup("prescription", prescription_id)
    prescriber = lookup("prescriber", body["prescriber_id"])
    if prescription["status"] not in ("PENDING_VERIFICATION", "CORRECTION_PENDING"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    if prescriber["status"] != "ACTIVE":
        raise ApiError("ERR_PRESCRIBER_SUSPENDED")

    current = db.clock
    for existing in db.verification_requests.values():
        if existing["prescription_id"] != prescription["id"]:
            continue
        if existing["prescriber_id"] != prescriber["id"]:
            continue
        if existing.get("sent_at") is None:
            continue
        if current <= calc.cooldown_end(existing["sent_at"]):
            raise ApiError("ERR_PRESCRIBER_CONTACT_COOLDOWN")

    pending = sum(
        1
        for r in db.verification_requests.values()
        if r["prescriber_id"] == prescriber["id"] and r["status"] == "SENT"
    )
    if pending >= calc.MAX_PENDING_REQUESTS_PER_PRESCRIBER:
        raise ApiError("ERR_PRESCRIBER_REQUEST_CAPACITY")
    if prescription["verification_rounds"] >= calc.MAX_VERIFICATION_ROUNDS:
        raise ApiError("ERR_MAX_VERIFICATION_ROUNDS")

    row = make_row(
        {
            "prescription_id": prescription["id"],
            "prescriber_id": prescriber["id"],
            "channel": prescriber["contact_channel"],
            "sent_at": current,
            "passive_deadline_at": calc.passive_deadline(current, prescriber["directory_verified"]),
            "round_number": prescription["verification_rounds"] + 1,
            "response_type": None,
            "status": "SENT",
        }
    )
    db.verification_requests[row["id"]] = row
    prescription["verification_rounds"] = prescription["verification_rounds"] + 1
    if prescription["status"] == "CORRECTION_PENDING":
        prescription["status"] = "PENDING_VERIFICATION"
    touch(prescription)
    append_event(
        prescription["id"], "REQUEST_SENT", "VerificationRequest", row["id"], (role, user_id)
    )
    return object_response(row, 201)


@bp.get("/prescriptions/<prescription_id>/compliance-events")
def list_compliance_events(prescription_id):
    _, role = identity()
    filters = parse_query(
        {
            "event_type": {"type": "enum", "values": EVENT_TYPES},
            "subject_type": {"type": "string"},
        }
    )
    limit, offset = parse_pagination()
    require_role(role, [ROLE_ADMIN, ROLE_COMPLIANCE])
    lookup("prescription", prescription_id)
    rows = [e for e in db.compliance_events.values() if e["prescription_id"] == prescription_id]
    if filters["event_type"]:
        rows = [e for e in rows if e["event_type"] == filters["event_type"]]
    if filters["subject_type"]:
        rows = [e for e in rows if e["subject_type"] == filters["subject_type"]]
    rows = sorted(rows, key=lambda e: (e["occurred_at"], e["_seq"]))
    page, total = paginate(rows, limit, offset)
    return list_response(page, limit, offset, total)


@bp.post("/prescriptions/<prescription_id>/invalidate")
def invalidate_prescription(prescription_id):
    user_id, role = identity()
    parse_body({"reason": {"type": "string", "required": True}})
    require_role(role, [ROLE_COMPLIANCE, ROLE_ADMIN])
    prescription = lookup("prescription", prescription_id)
    if prescription["status"] != "CORRECTION_PENDING":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    prescription["status"] = "INVALIDATED"
    touch(prescription)
    append_event(
        prescription["id"], "RX_INVALIDATED", "Prescription", prescription["id"], (role, user_id)
    )
    open_hold(prescription["customer_id"], prescription["id"], "MANUAL", user_id)
    reconcile_customer_id(prescription["customer_id"])
    return object_response(prescription)
