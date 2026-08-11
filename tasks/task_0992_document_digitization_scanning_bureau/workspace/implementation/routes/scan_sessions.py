"""Scan sessions: open, page-logs, commit (OCC), void."""

from flask import Blueprint, request

from db import db
from errors import (
    ApiError,
    ERR_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_STALE_VERSION,
    ERR_SCANNER_BUSY,
    ERR_SCANNER_UNAVAILABLE,
    ERR_SCANNER_OVER_CAPACITY,
    ERR_EMPTY_SCAN_SESSION,
    ERR_CLIENT_SUSPENDED,
)
from middleware import require_roles
from response import success_object, success_list, parse_pagination, iso_ts
from util import (
    get_body,
    require_fields,
    reject_unknown,
    as_str,
    as_int,
    make_entity,
    make_event,
    bump,
    now_iso,
)
from services.serializers import (
    scan_session_view,
    page_log_view,
    get_agreement_for_client,
    get_invoice_for_batch,
)
from services.pricing import page_subtotal_cents, storage_fee_total

bp = Blueprint("scan_sessions", __name__)

STAFF_ROLES = (
    "PlatformAdmin", "IntakeClerk", "PrepTechnician", "ScanOperator", "QAReviewer",
    "Indexer", "DestructionSpecialist", "ComplianceOfficer", "BillingClerk",
)


def get_session_or_404(session_id):
    s = db.scan_sessions.get(session_id)
    if not s:
        raise ApiError(ERR_NOT_FOUND, "Scan session not found", 404)
    return s


def check_client_active_for_batch(batch):
    client = db.clients.get(batch["client_id"])
    if client and client["status"] == "SUSPENDED":
        raise ApiError(ERR_CLIENT_SUSPENDED, "Client is suspended", 403)


@bp.route("/batches/<id>/scan-sessions", methods=["POST"])
@require_roles("ScanOperator")
def open_session(id, _user_id, _role):
    batch = db.batches.get(id)
    if not batch:
        raise ApiError(ERR_NOT_FOUND, "Batch not found", 404)
    body = get_body()
    require_fields(body, ["scanner_id"])
    reject_unknown(body, {"scanner_id"})
    scanner_id = as_str(body["scanner_id"], "scanner_id")
    scanner = db.scanner_units.get(scanner_id)
    if not scanner:
        raise ApiError(ERR_NOT_FOUND, "Scanner unit not found", 404)
    check_client_active_for_batch(batch)
    if batch["status"] != "SCANNING":
        raise ApiError(ERR_INVALID_STATE, "Batch is not in SCANNING", 409)
    if scanner["status"] != "AVAILABLE":
        raise ApiError(ERR_SCANNER_UNAVAILABLE, "Scanner is in MAINTENANCE", 409)
    # One OPEN session per scanner (on any batch)
    for s in db.scan_sessions.values():
        if s["scanner_id"] == scanner_id and s["status"] == "OPEN":
            raise ApiError(ERR_SCANNER_BUSY, "Scanner already has an OPEN session", 409)
    session = make_entity(
        {
            "batch_id": id,
            "scanner_id": scanner_id,
            "operator_id": _user_id,
            "status": "OPEN",
            "page_count": 0,
            "started_at": now_iso(),
            "ended_at": None,
        }
    )
    db.scan_sessions[session["id"]] = session
    return success_object(scan_session_view(session), status=201)


@bp.route("/scan-sessions/<id>", methods=["GET"])
@require_roles(*STAFF_ROLES)
def get_session(id, _user_id, _role):
    session = get_session_or_404(id)
    return success_object(scan_session_view(session))


@bp.route("/scan-sessions/<id>/page-logs", methods=["POST"])
@require_roles("ScanOperator")
def log_pages(id, _user_id, _role):
    session = get_session_or_404(id)
    body = get_body()
    require_fields(body, ["document_id", "pages"])
    reject_unknown(body, {"document_id", "pages"})
    document_id = as_str(body["document_id"], "document_id")
    pages = as_int(body["pages"], "pages", minimum=1)
    batch = db.batches.get(session["batch_id"])
    if batch:
        check_client_active_for_batch(batch)
    if session["status"] != "OPEN":
        raise ApiError(ERR_INVALID_STATE, "Scan session is not OPEN", 409)
    doc = db.documents.get(document_id)
    if not doc or doc["batch_id"] != session["batch_id"]:
        raise ApiError(ERR_NOT_FOUND, "Document not found in this batch", 404)
    log = make_event(
        {
            "session_id": session["id"],
            "batch_id": session["batch_id"],
            "document_id": document_id,
            "pages": pages,
        }
    )
    db.page_logs[log["id"]] = log
    session["page_count"] += pages
    bump(session)
    return success_object(page_log_view(log), status=201)


@bp.route("/scan-sessions/<id>/page-logs", methods=["GET"])
@require_roles(*STAFF_ROLES)
def list_session_page_logs(id, _user_id, _role):
    get_session_or_404(id)
    limit, offset = parse_pagination(request.args)
    items = [p for p in db.page_logs.values() if p["session_id"] == id]
    items.sort(key=lambda p: (p["created_at"], p["id"]))
    total = len(items)
    page = items[offset : offset + limit]
    return success_list([page_log_view(p) for p in page], limit, offset, total)


@bp.route("/page-logs/<id>", methods=["GET"])
@require_roles(*STAFF_ROLES)
def get_page_log(id, _user_id, _role):
    log = db.page_logs.get(id)
    if not log:
        raise ApiError(ERR_NOT_FOUND, "Page log not found", 404)
    return success_object(page_log_view(log))


def committed_pages_for_document(document_id):
    """Cumulative pages from COMMITTED sessions' PageLogs for a document."""
    total = 0
    for p in db.page_logs.values():
        if p["document_id"] != document_id:
            continue
        session = db.scan_sessions.get(p["session_id"])
        if not session or session["status"] != "COMMITTED":
            continue
        total += p["pages"]
    return total


@bp.route("/scan-sessions/<id>/commit", methods=["POST"])
@require_roles("ScanOperator")
def commit_session(id, _user_id, _role):
    session = get_session_or_404(id)
    body = get_body()
    require_fields(body, ["expected_batch_version"])
    reject_unknown(body, {"expected_batch_version"})
    expected = body["expected_batch_version"]
    if isinstance(expected, bool) or not isinstance(expected, int):
        from errors import ERR_INVALID_REQUEST

        raise ApiError(ERR_INVALID_REQUEST, "expected_batch_version must be an integer", 400)
    batch = db.batches.get(session["batch_id"])
    if not batch:
        raise ApiError(ERR_NOT_FOUND, "Batch not found", 404)
    check_client_active_for_batch(batch)
    if session["status"] != "OPEN":
        raise ApiError(ERR_INVALID_STATE, "Scan session is not OPEN", 409)
    if batch["status"] != "SCANNING":
        raise ApiError(ERR_INVALID_STATE, "Batch is not in SCANNING", 409)
    # OCC check
    if expected != batch["version"]:
        raise ApiError(ERR_STALE_VERSION, "Stale batch version", 412)
    if session["page_count"] <= 0:
        raise ApiError(ERR_EMPTY_SCAN_SESSION, "Session has no pages logged", 409)
    scanner = db.scanner_units.get(session["scanner_id"])
    if not scanner:
        raise ApiError(ERR_NOT_FOUND, "Scanner unit not found", 404)
    if session["page_count"] > scanner["capacity_pages_per_session"]:
        raise ApiError(
            ERR_SCANNER_OVER_CAPACITY, "Session exceeds scanner capacity", 409
        )
    if scanner["status"] != "AVAILABLE":
        raise ApiError(ERR_SCANNER_UNAVAILABLE, "Scanner is in MAINTENANCE", 409)
    # Commit: transition covered documents to SCANNED
    now_s = now_iso()
    session["status"] = "COMMITTED"
    session["ended_at"] = now_s
    bump(session)

    # Rework path: a QA_FAILED document becomes SCANNED again only when the
    # pages committed AFTER it entered QA_FAILED once again cover its declared
    # page count. qa_review snapshots the committed-pages total at the moment
    # the document entered QA_FAILED (qa_failed_committed_pages); pages
    # committed since are the difference from the current cumulative total.
    docs_in_batch = [d for d in db.documents.values() if d["batch_id"] == batch["id"]]
    for doc in docs_in_batch:
        if doc["status"] == "REGISTERED":
            total = committed_pages_for_document(doc["id"])
            if total >= doc["pages"]:
                doc["status"] = "SCANNED"
                bump(doc)
                batch["scanned_pages"] += doc["pages"]
                batch["billable_scanned_pages"] += doc["pages"]
        elif doc["status"] == "QA_FAILED":
            baseline = doc.get("qa_failed_committed_pages") or 0
            total = committed_pages_for_document(doc["id"])
            if total - baseline >= doc["pages"]:
                doc["status"] = "SCANNED"
                doc.pop("qa_failed_committed_pages", None)
                bump(doc)
                batch["scanned_pages"] += doc["pages"]
                # billable_scanned_pages unchanged (count-once ledger)

    # Recompute DRAFT invoice provisional page subtotal
    invoice = get_invoice_for_batch(batch["id"])
    agreement = get_agreement_for_client(batch["client_id"])
    if invoice and invoice["status"] == "DRAFT" and agreement:
        sub = page_subtotal_cents(batch, agreement)
        invoice["page_subtotal_cents"] = sub
        invoice["storage_subtotal_cents"] = storage_fee_total(batch, agreement, db.current_utc)
        invoice["total_cents"] = sub + invoice["storage_subtotal_cents"]
        bump(invoice)
    bump(batch)
    return success_object(scan_session_view(session))


@bp.route("/scan-sessions/<id>/void", methods=["POST"])
@require_roles("ScanOperator")
def void_session(id, _user_id, _role):
    session = get_session_or_404(id)
    get_body()
    batch = db.batches.get(session["batch_id"])
    if batch:
        check_client_active_for_batch(batch)
    if session["status"] != "OPEN":
        raise ApiError(ERR_INVALID_STATE, "Scan session is not OPEN", 409)
    session["status"] = "VOIDED"
    session["ended_at"] = now_iso()
    bump(session)
    return success_object(scan_session_view(session))
