"""Disposition requests, disposition items, destruction certificates."""
from flask import Blueprint, request

from db import db, new_id, touch, bump, now
from errors import err, not_found
from middleware import authenticate, body_json, READ_STAFF
from response import success_object, success_list, paginate
from serializers import (
    disposition_request_view, disposition_item_view, certificate_view)
from services.core import (
    derive_posture, record_active_hold_count, open_conflict_for,
    freeze_window_active, create_certificate, destroy_record)
from utils import check_str, check_str_list, check_enum

bp = Blueprint("dispositions", __name__)

METHODS = {"SECURE_ERASE", "SHRED", "CRYPTO_SHRED"}


def _request_items(request_id):
    """Disposition items of a request in creation order (the record_ids
    order of the request)."""
    items = [i for i in db.disposition_items.values()
             if i["request_id"] == request_id]
    items.sort(key=lambda i: i["seq"])
    return items


def _get_request(requestId):
    r = db.disposition_requests.get(requestId)
    if r is None:
        not_found("Disposition request not found")
    return r


def _check_owner(req, uid):
    if uid != req["requester_user_id"]:
        raise err("ERR_NOT_REQUEST_OWNER", 403,
                  "Only the original requester may perform this action")


def _check_all_eligible(req):
    """Every item's record must currently be ELIGIBLE; the error message
    names the first failing record_id in request creation order."""
    for item in _request_items(req["id"]):
        rec = db.records[item["record_id"]]
        if derive_posture(rec) != "ELIGIBLE":
            raise err("ERR_RECORD_NOT_ELIGIBLE", 409,
                      "Record %s is not currently ELIGIBLE"
                      % item["record_id"])


def _capture_snapshots(req):
    for item in _request_items(req["id"]):
        rec = db.records[item["record_id"]]
        item["snapshot_posture"] = derive_posture(rec)
        item["snapshot_due_date"] = rec.get("retention_due_date")
        item["snapshot_hold_count"] = record_active_hold_count(rec)
        bump(item)
    req["stale_item_count"] = 0


def _clear_snapshots(req):
    for item in _request_items(req["id"]):
        item["snapshot_posture"] = None
        item["snapshot_due_date"] = None
        item["snapshot_hold_count"] = None
        bump(item)
    req["stale_item_count"] = 0


# ---------------------------------------------------------------------------
# Disposition Requests
# ---------------------------------------------------------------------------
@bp.route("/ig/disposition-requests", methods=["POST"])
def create_request():
    uid, _ = authenticate(["RecordsManager"])
    body = body_json()
    program_id = check_str(body, "program_id")
    record_ids = check_str_list(body, "record_ids")
    method = check_enum(body, "method", METHODS)
    justification = check_str(body, "justification")
    if len(justification) < 20:
        raise err("ERR_JUSTIFICATION_TOO_SHORT", 400,
                  "justification must be at least 20 characters")
    if len(record_ids) == 0:
        raise err("ERR_EMPTY_COLLECTION", 400,
                  "record_ids must be a non-empty collection")
    if program_id not in db.programs:
        raise err("ERR_REFERENCED_ENTITY_NOT_FOUND", 404,
                  "Referenced program does not exist")
    records = []
    for rid in record_ids:
        r = db.records.get(rid)
        if r is None:
            raise err("ERR_REFERENCED_RECORD_NOT_FOUND", 404,
                      "Referenced record does not exist: %s" % rid)
        records.append(r)
    for r in records:
        if r["program_id"] != program_id:
            raise err("ERR_CROSS_PROGRAM_REFERENCE", 409,
                      "Record %s belongs to a different program" % r["id"])
    if len(set(record_ids)) != len(record_ids):
        raise err("ERR_DUPLICATE_REQUEST_ITEM", 409,
                  "The same record id appears twice in the request")
    for r in records:
        if r["status"] == "DESTROYED":
            raise err("ERR_RECORD_ALREADY_DESTROYED", 409,
                      "Record %s has already been destroyed" % r["id"])
    req = {
        "id": new_id(),
        "program_id": program_id,
        "requester_user_id": uid,
        "method": method,
        "justification": justification,
        "submitted_at": None,
        "decided_at": None,
        "decided_by_user_id": None,
        "rejection_reason": None,
        "executed_at": None,
        "stale_item_count": 0,
        "status": "DRAFT",
    }
    touch(req)
    db.disposition_requests[req["id"]] = req
    for seq, rid in enumerate(record_ids):
        item = {
            "id": new_id(),
            "request_id": req["id"],
            "record_id": rid,
            "program_id": program_id,
            "seq": seq,
            "snapshot_posture": None,
            "snapshot_due_date": None,
            "snapshot_hold_count": None,
            "destroyed_at": None,
            "status": "PENDING",
        }
        touch(item)
        db.disposition_items[item["id"]] = item
    return success_object(disposition_request_view(req), 201)


@bp.route("/ig/disposition-requests", methods=["GET"])
def list_requests():
    authenticate(READ_STAFF)
    items = list(db.disposition_requests.values())
    a = request.args
    for f in ("program_id", "status", "requester_user_id"):
        v = a.get(f)
        if v is not None:
            items = [r for r in items if r.get(f) == v]
    window, limit, offset, total = paginate(items, request.args)
    return success_list([disposition_request_view(r) for r in window],
                        limit, offset, total)


@bp.route("/ig/disposition-requests/<requestId>", methods=["GET"])
def get_request(requestId):
    authenticate(READ_STAFF)
    return success_object(disposition_request_view(_get_request(requestId)))


@bp.route("/ig/disposition-requests/<requestId>/submit", methods=["POST"])
def submit_request(requestId):
    uid, _ = authenticate(["RecordsManager"])
    req = _get_request(requestId)
    if req["status"] != "DRAFT":
        raise err("ERR_REQUEST_INVALID_STATE", 409,
                  "Only a DRAFT request can be submitted")
    _check_owner(req, uid)
    _check_all_eligible(req)
    _capture_snapshots(req)
    req["status"] = "SUBMITTED"
    req["submitted_at"] = now()
    bump(req)
    return success_object(disposition_request_view(req))


@bp.route("/ig/disposition-requests/<requestId>/refresh-snapshots",
          methods=["POST"])
def refresh_snapshots(requestId):
    uid, _ = authenticate(["RecordsManager"])
    req = _get_request(requestId)
    if req["status"] != "SUBMITTED":
        raise err("ERR_REQUEST_INVALID_STATE", 409,
                  "Only a SUBMITTED request can refresh snapshots")
    _check_owner(req, uid)
    _check_all_eligible(req)
    _capture_snapshots(req)
    bump(req)
    return success_object(disposition_request_view(req))


@bp.route("/ig/disposition-requests/<requestId>/approve", methods=["POST"])
def approve_request(requestId):
    uid, _ = authenticate(["LegalCounsel"])
    req = _get_request(requestId)
    if req["status"] != "SUBMITTED":
        raise err("ERR_REQUEST_INVALID_STATE", 409,
                  "Only a SUBMITTED request can be approved")
    if uid == req["requester_user_id"]:
        raise err("ERR_SEGREGATION_OF_DUTIES", 403,
                  "The approver must differ from the original requester")
    # Conflict gate: no OPEN RetentionConflict covering any item's pair.
    for item in _request_items(req["id"]):
        rec = db.records[item["record_id"]]
        if open_conflict_for(rec["record_class_id"],
                             rec["jurisdiction_id"]):
            raise err("ERR_DISPOSITION_CONFLICT_BLOCKED", 409,
                      "An OPEN retention conflict covers record %s"
                      % item["record_id"])
    if req["stale_item_count"] != 0:
        raise err("ERR_STALE_ELIGIBILITY_SNAPSHOT", 409,
                  "stale_item_count is non-zero; refresh snapshots first")
    _check_all_eligible(req)
    req["status"] = "APPROVED"
    req["decided_at"] = now()
    req["decided_by_user_id"] = uid
    bump(req)
    return success_object(disposition_request_view(req))


@bp.route("/ig/disposition-requests/<requestId>/reject", methods=["POST"])
def reject_request(requestId):
    uid, _ = authenticate(["LegalCounsel"])
    req = _get_request(requestId)
    body = body_json()
    rejection_reason = check_str(body, "rejection_reason")
    if len(rejection_reason) < 10:
        raise err("ERR_JUSTIFICATION_TOO_SHORT", 400,
                  "rejection_reason must be at least 10 characters")
    if req["status"] != "SUBMITTED":
        raise err("ERR_REQUEST_INVALID_STATE", 409,
                  "Only a SUBMITTED request can be rejected")
    req["status"] = "REJECTED"
    req["decided_at"] = now()
    req["decided_by_user_id"] = uid
    req["rejection_reason"] = rejection_reason
    bump(req)
    return success_object(disposition_request_view(req))


@bp.route("/ig/disposition-requests/<requestId>/revise", methods=["POST"])
def revise_request(requestId):
    uid, _ = authenticate(["RecordsManager"])
    req = _get_request(requestId)
    if req["status"] != "REJECTED":
        raise err("ERR_REQUEST_INVALID_STATE", 409,
                  "Only a REJECTED request can be revised")
    _check_owner(req, uid)
    _clear_snapshots(req)
    req["rejection_reason"] = None
    req["status"] = "DRAFT"
    bump(req)
    return success_object(disposition_request_view(req))


@bp.route("/ig/disposition-requests/<requestId>/withdraw", methods=["POST"])
def withdraw_request(requestId):
    uid, _ = authenticate(["RecordsManager"])
    req = _get_request(requestId)
    if req["status"] != "DRAFT":
        raise err("ERR_REQUEST_INVALID_STATE", 409,
                  "Only a DRAFT request can be withdrawn")
    _check_owner(req, uid)
    req["status"] = "WITHDRAWN"
    bump(req)
    return success_object(disposition_request_view(req))


@bp.route("/ig/disposition-requests/<requestId>/execute", methods=["POST"])
def execute_request(requestId):
    uid, _ = authenticate(["RecordsManager"])
    req = _get_request(requestId)
    if req["status"] != "APPROVED":
        raise err("ERR_REQUEST_INVALID_STATE", 409,
                  "Only an APPROVED request can be executed")
    if freeze_window_active(req["program_id"]):
        raise err("ERR_DISPOSITION_FREEZE_ACTIVE", 409,
                  "An ACTIVE disposition freeze window covers the current "
                  "time for this program")
    t = now()
    # Per-item conditional destruction in request creation order; skips do
    # not fail the request.
    for item in _request_items(req["id"]):
        rec = db.records[item["record_id"]]
        if rec["status"] == "DESTROYED":
            item["status"] = "SKIPPED_ALREADY_DESTROYED"
            bump(item)
        elif derive_posture(rec) != "ELIGIBLE":
            item["status"] = "SKIPPED_HELD"
            bump(item)
        else:
            destroy_record(rec)
            item["status"] = "DESTROYED"
            item["destroyed_at"] = t
            bump(item)
            create_certificate(req["program_id"], req["id"], item["id"],
                               rec, req["method"], uid)
    req["status"] = "EXECUTED"
    req["executed_at"] = t
    bump(req)
    return success_object(disposition_request_view(req))


# ---------------------------------------------------------------------------
# Disposition Items (read)
# ---------------------------------------------------------------------------
@bp.route("/ig/disposition-items", methods=["GET"])
def list_items():
    authenticate(READ_STAFF)
    items = list(db.disposition_items.values())
    a = request.args
    for f in ("request_id", "record_id", "status", "program_id"):
        v = a.get(f)
        if v is not None:
            items = [i for i in items if i.get(f) == v]
    window, limit, offset, total = paginate(items, request.args)
    return success_list([disposition_item_view(i) for i in window],
                        limit, offset, total)


@bp.route("/ig/disposition-items/<itemId>", methods=["GET"])
def get_item(itemId):
    authenticate(READ_STAFF)
    i = db.disposition_items.get(itemId)
    if i is None:
        not_found("Disposition item not found")
    return success_object(disposition_item_view(i))


# ---------------------------------------------------------------------------
# Destruction Certificates (read-only)
# ---------------------------------------------------------------------------
@bp.route("/ig/destruction-certificates", methods=["GET"])
def list_certificates():
    authenticate(READ_STAFF)
    items = list(db.destruction_certificates.values())
    a = request.args
    for f in ("program_id", "record_id", "request_id", "disposition_item_id"):
        v = a.get(f)
        if v is not None:
            items = [c for c in items if c.get(f) == v]
    window, limit, offset, total = paginate(items, request.args)
    return success_list([certificate_view(c) for c in window],
                        limit, offset, total)


@bp.route("/ig/destruction-certificates/<certificateId>", methods=["GET"])
def get_certificate(certificateId):
    authenticate(READ_STAFF)
    c = db.destruction_certificates.get(certificateId)
    if c is None:
        not_found("Destruction certificate not found")
    return success_object(certificate_view(c))
