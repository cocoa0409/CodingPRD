"""Batches: creation, pipeline transitions, sub-resource lists, QA reviews."""

from datetime import timedelta

from flask import Blueprint, request

from db import db
from errors import (
    ApiError,
    ERR_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_BATCH_EMPTY,
    ERR_CUSTODY_GAP,
    ERR_OPEN_SCAN_SESSION_EXISTS,
    ERR_DOCUMENTS_INCOMPLETE,
    ERR_BATCH_NOT_REWORKABLE,
    ERR_BATCH_NOT_INDEXABLE,
    ERR_BOXES_NOT_FINAL,
    ERR_RUSH_CAPACITY_FULL,
    ERR_CLIENT_SUSPENDED,
)
from middleware import require_roles, check_client_user_scope
from response import success_object, success_list, parse_pagination, iso_ts
from util import get_body, require_fields, reject_unknown, as_str, as_enum, make_entity, bump
from services.serializers import (
    batch_view,
    box_view,
    document_view,
    index_record_view,
    scan_session_view,
    page_log_view,
    access_grant_view,
    destruction_certificate_view,
    invoice_view,
    get_agreement_for_client,
    get_invoice_for_batch,
)
from services.pricing import (
    batch_indexable,
    admitted_rush_count,
    RUSH_ADMISSION_LIMIT,
    page_subtotal_cents,
)

bp = Blueprint("batches", __name__)

ALL_ROLES = (
    "PlatformAdmin", "IntakeClerk", "PrepTechnician", "ScanOperator", "QAReviewer",
    "Indexer", "DestructionSpecialist", "ComplianceOfficer", "BillingClerk", "ClientUser",
)
STAFF_ROLES = (
    "PlatformAdmin", "IntakeClerk", "PrepTechnician", "ScanOperator", "QAReviewer",
    "Indexer", "DestructionSpecialist", "ComplianceOfficer", "BillingClerk",
)


def get_batch_or_404(batch_id):
    b = db.batches.get(batch_id)
    if not b:
        raise ApiError(ERR_NOT_FOUND, "Batch not found", 404)
    return b


def check_client_active(batch):
    client = db.clients.get(batch["client_id"])
    if client and client["status"] == "SUSPENDED":
        raise ApiError(ERR_CLIENT_SUSPENDED, "Client is suspended", 403)


def batch_docs(batch_id):
    return [d for d in db.documents.values() if d["batch_id"] == batch_id]


def batch_boxes(batch_id):
    return [b for b in db.boxes.values() if b["batch_id"] == batch_id]


@bp.route("/batches", methods=["POST"])
@require_roles("IntakeClerk")
def create_batch(_user_id, _role):
    body = get_body()
    require_fields(body, ["client_id", "priority"])
    reject_unknown(body, {"client_id", "priority"})
    client_id = as_str(body["client_id"], "client_id")
    priority = as_enum(body["priority"], "priority", {"STANDARD", "RUSH"})
    client = db.clients.get(client_id)
    if not client:
        raise ApiError(ERR_NOT_FOUND, "Client not found", 404)
    if client["status"] == "SUSPENDED":
        raise ApiError(ERR_CLIENT_SUSPENDED, "Client is suspended", 403)
    if priority == "RUSH" and admitted_rush_count() >= RUSH_ADMISSION_LIMIT:
        raise ApiError(ERR_RUSH_CAPACITY_FULL, "Rush admission capacity reached", 409)
    batch = make_entity(
        {
            "client_id": client_id,
            "priority": priority,
            "status": "INTAKE",
            "scanned_pages": 0,
            "billable_scanned_pages": 0,
            "rework_cycle_count": 0,
            "delivery_status": "PENDING",
            "delivered_at": None,
            "disposition_at": None,
        }
    )
    db.batches[batch["id"]] = batch
    # Auto-create DRAFT invoice 1:1 with the batch
    invoice = make_entity(
        {
            "batch_id": batch["id"],
            "client_id": client_id,
            "status": "DRAFT",
            "page_subtotal_cents": 0,
            "storage_subtotal_cents": 0,
            "total_cents": 0,
            "amount_paid_cents": 0,
            "issued_at": None,
            "void_reason": None,
        }
    )
    db.invoices[invoice["id"]] = invoice
    return success_object(batch_view(batch), status=201)


@bp.route("/batches", methods=["GET"])
@require_roles(*STAFF_ROLES)
def list_batches(_user_id, _role):
    limit, offset = parse_pagination(request.args)
    client_id = request.args.get("client_id")
    status = request.args.get("status")
    items = list(db.batches.values())
    if client_id is not None:
        items = [b for b in items if b["client_id"] == client_id]
    if status is not None:
        items = [b for b in items if b["status"] == status]
    items.sort(key=lambda b: (b["created_at"], b["id"]))
    total = len(items)
    page = items[offset : offset + limit]
    return success_list([batch_view(b) for b in page], limit, offset, total)


@bp.route("/batches/<id>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_batch(id, _user_id, _role):
    batch = get_batch_or_404(id)
    check_client_user_scope(_user_id, _role, batch["client_id"])
    return success_object(batch_view(batch))


def _transition(batch, to_status):
    batch["status"] = to_status
    bump(batch)


@bp.route("/batches/<id>/start-prep", methods=["POST"])
@require_roles("IntakeClerk")
def start_prep(id, _user_id, _role):
    batch = get_batch_or_404(id)
    get_body()
    check_client_active(batch)
    if batch["status"] != "INTAKE":
        raise ApiError(ERR_INVALID_STATE, "Batch is not in INTAKE", 409)
    boxes = batch_boxes(id)
    if len(boxes) < 1:
        raise ApiError(ERR_BATCH_EMPTY, "Batch has no boxes", 409)
    for box in boxes:
        has_event = any(e["box_id"] == box["id"] for e in db.custody_events.values())
        if not has_event:
            raise ApiError(ERR_CUSTODY_GAP, "Box has no custody event", 422)
    _transition(batch, "PREPPING")
    return success_object(batch_view(batch))


@bp.route("/batches/<id>/start-scan", methods=["POST"])
@require_roles("ScanOperator")
def start_scan(id, _user_id, _role):
    batch = get_batch_or_404(id)
    get_body()
    check_client_active(batch)
    if batch["status"] != "PREPPING":
        raise ApiError(ERR_INVALID_STATE, "Batch is not in PREPPING", 409)
    if len(batch_docs(id)) < 1:
        raise ApiError(ERR_BATCH_EMPTY, "Batch has no documents", 409)
    _transition(batch, "SCANNING")
    return success_object(batch_view(batch))


@bp.route("/batches/<id>/submit-qa", methods=["POST"])
@require_roles("ScanOperator")
def submit_qa(id, _user_id, _role):
    batch = get_batch_or_404(id)
    get_body()
    check_client_active(batch)
    if batch["status"] != "SCANNING":
        raise ApiError(ERR_INVALID_STATE, "Batch is not in SCANNING", 409)
    for s in db.scan_sessions.values():
        if s["batch_id"] == id and s["status"] == "OPEN":
            raise ApiError(ERR_OPEN_SCAN_SESSION_EXISTS, "An OPEN scan session exists", 409)
    for d in batch_docs(id):
        if d["status"] not in ("SCANNED", "QA_FAILED", "REJECTED"):
            raise ApiError(
                ERR_DOCUMENTS_INCOMPLETE, "Not all documents are scanned", 409
            )
    _transition(batch, "QA")
    return success_object(batch_view(batch))


@bp.route("/batches/<id>/pass-qa", methods=["POST"])
@require_roles("QAReviewer")
def pass_qa(id, _user_id, _role):
    batch = get_batch_or_404(id)
    get_body()
    check_client_active(batch)
    if batch["status"] != "QA":
        raise ApiError(ERR_INVALID_STATE, "Batch is not in QA", 409)
    for d in batch_docs(id):
        if d["status"] == "QA_FAILED":
            raise ApiError(ERR_DOCUMENTS_INCOMPLETE, "Documents remain QA_FAILED", 409)
    _transition(batch, "INDEXING")
    return success_object(batch_view(batch))


@bp.route("/batches/<id>/fail-qa", methods=["POST"])
@require_roles("QAReviewer")
def fail_qa(id, _user_id, _role):
    batch = get_batch_or_404(id)
    get_body()
    check_client_active(batch)
    if batch["status"] != "QA":
        raise ApiError(ERR_INVALID_STATE, "Batch is not in QA", 409)
    if not any(d["status"] == "QA_FAILED" for d in batch_docs(id)):
        raise ApiError(ERR_BATCH_NOT_REWORKABLE, "No QA_FAILED documents", 409)
    batch["rework_cycle_count"] += 1
    _transition(batch, "SCANNING")
    return success_object(batch_view(batch))


@bp.route("/batches/<id>/deliver", methods=["POST"])
@require_roles("QAReviewer")
def deliver(id, _user_id, _role):
    batch = get_batch_or_404(id)
    get_body()
    check_client_active(batch)
    if batch["status"] != "INDEXING":
        raise ApiError(ERR_INVALID_STATE, "Batch is not in INDEXING", 409)
    if not batch_indexable(batch):
        raise ApiError(ERR_BATCH_NOT_INDEXABLE, "Batch is not indexable", 409)
    now = db.current_utc
    now_s = iso_ts(now)
    docs = batch_docs(id)
    for d in docs:
        if d["status"] == "INDEXED":
            d["status"] = "DELIVERED"
            d["delivered_at"] = now_s
            bump(d)
    batch["delivered_at"] = now_s
    agreement = get_agreement_for_client(batch["client_id"])
    retention_days = agreement["retention_days"] if agreement else 0
    batch["disposition_at"] = iso_ts(now + timedelta(days=retention_days))
    rejected = sum(1 for d in docs if d["status"] == "REJECTED")
    batch["delivery_status"] = "COMPLETE" if rejected == 0 else "PARTIAL"
    # Lock final pricing into the DRAFT invoice
    invoice = get_invoice_for_batch(id)
    if invoice and invoice["status"] == "DRAFT" and agreement:
        final_sub = page_subtotal_cents(batch, agreement)
        invoice["page_subtotal_cents"] = final_sub
        invoice["total_cents"] = final_sub + invoice.get("storage_subtotal_cents", 0)
        bump(invoice)
    _transition(batch, "DELIVERED")
    return success_object(batch_view(batch))


@bp.route("/batches/<id>/close", methods=["POST"])
@require_roles("ComplianceOfficer")
def close_batch(id, _user_id, _role):
    batch = get_batch_or_404(id)
    get_body()
    check_client_active(batch)
    if batch["status"] != "DISPOSITION_PENDING":
        raise ApiError(ERR_INVALID_STATE, "Batch is not in DISPOSITION_PENDING", 409)
    for box in batch_boxes(id):
        if box["status"] not in ("DESTROYED", "RETURNED"):
            raise ApiError(ERR_BOXES_NOT_FINAL, "Not all boxes are final", 409)
    _transition(batch, "CLOSED")
    return success_object(batch_view(batch))


# ---------------- Sub-resource list endpoints ----------------

@bp.route("/batches/<id>/boxes", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_boxes(id, _user_id, _role):
    batch = get_batch_or_404(id)
    check_client_user_scope(_user_id, _role, batch["client_id"])
    limit, offset = parse_pagination(request.args)
    status = request.args.get("status")
    items = batch_boxes(id)
    if status is not None:
        items = [b for b in items if b["status"] == status]
    items.sort(key=lambda b: (b["created_at"], b["id"]))
    total = len(items)
    page = items[offset : offset + limit]
    return success_list([box_view(b) for b in page], limit, offset, total)


@bp.route("/batches/<id>/documents", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_documents(id, _user_id, _role):
    batch = get_batch_or_404(id)
    check_client_user_scope(_user_id, _role, batch["client_id"])
    limit, offset = parse_pagination(request.args)
    status = request.args.get("status")
    box_id = request.args.get("box_id")
    items = batch_docs(id)
    if status is not None:
        items = [d for d in items if d["status"] == status]
    if box_id is not None:
        items = [d for d in items if d["box_id"] == box_id]
    items.sort(key=lambda d: (d["created_at"], d["id"]))
    total = len(items)
    page = items[offset : offset + limit]
    return success_list([document_view(d) for d in page], limit, offset, total)


@bp.route("/batches/<id>/index-records", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_index_records(id, _user_id, _role):
    batch = get_batch_or_404(id)
    check_client_user_scope(_user_id, _role, batch["client_id"])
    limit, offset = parse_pagination(request.args)
    items = [r for r in db.index_records.values() if r["batch_id"] == id]
    items.sort(key=lambda r: (r["created_at"], r["id"]))
    total = len(items)
    page = items[offset : offset + limit]
    return success_list([index_record_view(r) for r in page], limit, offset, total)


@bp.route("/batches/<id>/scan-sessions", methods=["GET"])
@require_roles(*STAFF_ROLES)
def list_scan_sessions(id, _user_id, _role):
    get_batch_or_404(id)
    limit, offset = parse_pagination(request.args)
    status = request.args.get("status")
    items = [s for s in db.scan_sessions.values() if s["batch_id"] == id]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    items.sort(key=lambda s: (s["created_at"], s["id"]))
    total = len(items)
    page = items[offset : offset + limit]
    return success_list([scan_session_view(s) for s in page], limit, offset, total)


@bp.route("/batches/<id>/page-logs", methods=["GET"])
@require_roles(*STAFF_ROLES)
def list_page_logs(id, _user_id, _role):
    get_batch_or_404(id)
    limit, offset = parse_pagination(request.args)
    items = [p for p in db.page_logs.values() if p["batch_id"] == id]
    items.sort(key=lambda p: (p["created_at"], p["id"]))
    total = len(items)
    page = items[offset : offset + limit]
    return success_list([page_log_view(p) for p in page], limit, offset, total)


@bp.route("/batches/<id>/access-grants", methods=["GET"])
@require_roles("PlatformAdmin", "ComplianceOfficer")
def list_batch_grants(id, _user_id, _role):
    get_batch_or_404(id)
    limit, offset = parse_pagination(request.args)
    items = [g for g in db.access_grants.values() if g["batch_id"] == id]
    items.sort(key=lambda g: (g["created_at"], g["id"]))
    total = len(items)
    page = items[offset : offset + limit]
    return success_list([access_grant_view(g) for g in page], limit, offset, total)


@bp.route("/batches/<id>/destruction-certificates", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_batch_certificates(id, _user_id, _role):
    batch = get_batch_or_404(id)
    check_client_user_scope(_user_id, _role, batch["client_id"])
    limit, offset = parse_pagination(request.args)
    items = [c for c in db.destruction_certificates.values() if c["batch_id"] == id]
    items.sort(key=lambda c: (c["created_at"], c["id"]))
    total = len(items)
    page = items[offset : offset + limit]
    return success_list(
        [destruction_certificate_view(c) for c in page], limit, offset, total
    )


@bp.route("/batches/<id>/invoices", methods=["GET"])
@require_roles("PlatformAdmin", "BillingClerk", "ClientUser")
def list_batch_invoices(id, _user_id, _role):
    batch = get_batch_or_404(id)
    check_client_user_scope(_user_id, _role, batch["client_id"])
    limit, offset = parse_pagination(request.args)
    items = [i for i in db.invoices.values() if i["batch_id"] == id]
    items.sort(key=lambda i: (i["created_at"], i["id"]))
    total = len(items)
    page = items[offset : offset + limit]
    return success_list([invoice_view(i) for i in page], limit, offset, total)


@bp.route("/batches/<id>/qa-reviews", methods=["POST"])
@require_roles("QAReviewer")
def qa_review(id, _user_id, _role):
    batch = get_batch_or_404(id)
    body = get_body()
    require_fields(body, ["document_id"])
    reject_unknown(body, {"document_id"})
    check_client_active(batch)
    if batch["status"] not in ("SCANNING", "QA"):
        raise ApiError(ERR_INVALID_STATE, "Batch is not in SCANNING or QA", 409)
    doc = db.documents.get(body["document_id"])
    if not doc or doc["batch_id"] != id:
        raise ApiError(ERR_NOT_FOUND, "Document not found in this batch", 404)
    if doc["status"] != "SCANNED":
        raise ApiError(ERR_INVALID_STATE, "Document is not SCANNED", 409)
    doc["status"] = "QA_FAILED"
    # Snapshot cumulative committed pages at QA_FAILED entry so a rework commit
    # can measure pages committed strictly after this point (the logical clock
    # does not advance between requests, so timestamps cannot express "after").
    doc["qa_failed_committed_pages"] = sum(
        p["pages"]
        for p in db.page_logs.values()
        if p["document_id"] == doc["id"]
        and (db.scan_sessions.get(p["session_id"]) or {}).get("status") == "COMMITTED"
    )
    bump(doc)
    return success_object(document_view(doc), status=201)
