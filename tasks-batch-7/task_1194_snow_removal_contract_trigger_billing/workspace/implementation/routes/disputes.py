"""Dispute endpoints — open, submit-evidence, request-evidence, resolve."""
from flask import Blueprint, request
import db
from middleware import require_roles, get_pagination, get_json_body
from response import success_object, success_created, success_list
from errors import *
from services.helpers import recompute_contract_accumulators, _touch, _touch_client

bp = Blueprint("disputes", __name__)

ALLOWED_CREATE_FIELDS = {"invoice_id", "visit_id", "reason"}
VALID_REASONS = {"TRIGGER_NOT_MET", "INCOMPLETE_SERVICE", "PHOTO_INSUFFICIENT", "RATE_DISAGREEMENT", "MATERIAL_QUANTITY"}


@bp.route("/disputes", methods=["POST"])
def create_dispute():
    user_id, role = require_roles("ClientContact")
    body = get_json_body()
    unknown = set(body.keys()) - ALLOWED_CREATE_FIELDS
    if unknown:
        raise ApiError(ERR_INVALID_REQUEST, f"Unknown fields: {', '.join(unknown)}", 400)

    invoice_id = body.get("invoice_id")
    visit_id = body.get("visit_id")
    reason = body.get("reason")

    if not invoice_id:
        raise ApiError(ERR_INVALID_REQUEST, "invoice_id is required", 400)
    if not visit_id:
        raise ApiError(ERR_INVALID_REQUEST, "visit_id is required", 400)
    if not reason or reason not in VALID_REASONS:
        raise ApiError(ERR_INVALID_REQUEST, f"reason must be one of {', '.join(VALID_REASONS)}", 400)

    invoice = db.invoices.get(invoice_id)
    if not invoice:
        raise ApiError(ERR_NOT_FOUND, f"Invoice {invoice_id} not found", 404)
    visit = db.visits.get(visit_id)
    if not visit:
        raise ApiError(ERR_NOT_FOUND, f"Visit {visit_id} not found", 404)

    # Ownership: only own client's invoices
    contract = db.contracts.get(invoice.get("contract_id"))
    if contract and contract.get("client_id") != user_id:
        raise ApiError(ERR_FORBIDDEN_OWNERSHIP, "Not your invoice", 403)

    # Visit must appear among invoice's lines
    visit_in_lines = False
    for line in invoice.get("lines", []):
        if line.get("visit_id") == visit_id:
            visit_in_lines = True
            break
    if not visit_in_lines:
        raise ApiError(ERR_DISPUTE_LINE_NOT_FOUND, "Visit is not a line of this invoice", 422)

    dispute = {
        "id": db._new_id(),
        "invoice_id": invoice_id,
        "visit_id": visit_id,
        "reason": reason,
        "status": "OPEN",
        "opened_by_client_id": user_id,
        "evidence_items": [],
        "resolved_by_user_id": None,
        "resolution_credit_cents": None,
        "created_at": db.now_iso(),
        "updated_at": db.now_iso(),
        "version": 1,
    }
    db.disputes.create(dispute)

    # Move visit billing to DISPUTED
    if visit.get("billing_status") == "INVOICED":
        visit["billing_status"] = "DISPUTED"
        _touch(visit)
        db.visits.update(visit_id, visit)

    return success_created(dispute)


def _get_dispute_or_404(id):
    d = db.disputes.get(id)
    if not d:
        raise ApiError(ERR_NOT_FOUND, f"Dispute {id} not found", 404)
    return d


@bp.route("/disputes/<id>", methods=["GET"])
def get_dispute(id):
    user_id, role = require_roles("PlatformAdmin", "OpsDispatcher", "ClientContact")
    dispute = _get_dispute_or_404(id)
    if role == "ClientContact" and dispute.get("opened_by_client_id") != user_id:
        raise ApiError(ERR_FORBIDDEN_OWNERSHIP, "Not your dispute", 403)
    return success_object(dispute)


@bp.route("/disputes", methods=["GET"])
def list_disputes():
    user_id, role = require_roles("PlatformAdmin", "OpsDispatcher", "ClientContact")
    limit, offset = get_pagination()
    all_disputes = db.disputes.list_all()

    invoice_id = request.args.get("invoice_id")
    visit_id = request.args.get("visit_id")
    status = request.args.get("status")
    if invoice_id:
        all_disputes = [d for d in all_disputes if d.get("invoice_id") == invoice_id]
    if visit_id:
        all_disputes = [d for d in all_disputes if d.get("visit_id") == visit_id]
    if status:
        all_disputes = [d for d in all_disputes if d.get("status") == status]
    if role == "ClientContact":
        all_disputes = [d for d in all_disputes if d.get("opened_by_client_id") == user_id]

    all_disputes = sorted(all_disputes, key=lambda d: d.get("created_at", ""))
    total = len(all_disputes)
    page = all_disputes[offset:offset + limit]
    return success_list(page, total, limit, offset)


@bp.route("/disputes/<id>/submit-evidence", methods=["POST"])
def submit_evidence(id):
    user_id, role = require_roles("ClientContact")
    dispute = _get_dispute_or_404(id)
    if dispute["status"] in ("RESOLVED_UPHELD", "RESOLVED_ADJUSTED", "RESOLVED_REMOVED"):
        raise ApiError(ERR_ALREADY_TERMINAL, f"Dispute is {dispute['status']} (terminal)", 409)
    if dispute["status"] != "OPEN":
        raise ApiError(ERR_INVALID_STATE, f"Cannot submit evidence from {dispute['status']}", 409)
    if dispute.get("opened_by_client_id") != user_id:
        raise ApiError(ERR_FORBIDDEN_OWNERSHIP, "Not your dispute", 403)

    body = get_json_body()
    evidence_note = body.get("evidence_note")
    photo_ids = body.get("photo_ids")

    if not evidence_note and not photo_ids:
        raise ApiError(ERR_EVIDENCE_REQUIRED, "At least one of evidence_note or photo_ids required", 422)

    # Validate photo_ids reference existing photos
    if photo_ids:
        for pid in photo_ids:
            photo = db.photos.get(pid)
            if not photo:
                raise ApiError(ERR_NOT_FOUND, f"Photo {pid} not found", 404)

    evidence = {}
    if evidence_note:
        evidence["note"] = evidence_note
    if photo_ids:
        evidence["photo_ids"] = photo_ids

    dispute["evidence_items"] = (dispute.get("evidence_items") or []) + [evidence]
    dispute["status"] = "EVIDENCE_REVIEW"
    _touch(dispute)
    db.disputes.update(id, dispute)
    return success_object(dispute)


@bp.route("/disputes/<id>/request-evidence", methods=["POST"])
def request_evidence(id):
    user_id, role = require_roles("OpsDispatcher")
    dispute = _get_dispute_or_404(id)
    if dispute["status"] in ("RESOLVED_UPHELD", "RESOLVED_ADJUSTED", "RESOLVED_REMOVED"):
        raise ApiError(ERR_ALREADY_TERMINAL, f"Dispute is {dispute['status']} (terminal)", 409)
    if dispute["status"] != "EVIDENCE_REVIEW":
        raise ApiError(ERR_INVALID_STATE, f"Cannot request evidence from {dispute['status']}", 409)
    dispute["status"] = "OPEN"
    _touch(dispute)
    db.disputes.update(id, dispute)
    return success_object(dispute)


@bp.route("/disputes/<id>/resolve", methods=["POST"])
def resolve_dispute(id):
    user_id, role = require_roles("OpsDispatcher")
    dispute = _get_dispute_or_404(id)
    if dispute["status"] in ("RESOLVED_UPHELD", "RESOLVED_ADJUSTED", "RESOLVED_REMOVED"):
        raise ApiError(ERR_ALREADY_TERMINAL, f"Dispute is {dispute['status']} (terminal)", 409)
    if dispute["status"] != "EVIDENCE_REVIEW":
        raise ApiError(ERR_INVALID_STATE, f"Cannot resolve from {dispute['status']}", 409)

    body = get_json_body()
    outcome = body.get("outcome")
    credit_cents = body.get("credit_cents")

    if not outcome or outcome not in ("UPHELD", "ADJUSTED", "REMOVED"):
        raise ApiError(ERR_INVALID_REQUEST, "outcome must be UPHELD, ADJUSTED, or REMOVED", 400)

    # Segregation of duties
    invoice = db.invoices.get(dispute.get("invoice_id"))
    visit = db.visits.get(dispute.get("visit_id"))
    if invoice and invoice.get("issued_by_user_id") == user_id:
        raise ApiError(ERR_DISPUTE_SEGREGATION, "Resolver is the invoice issuer", 403)
    if visit and visit.get("completed_by_user_id") == user_id:
        raise ApiError(ERR_DISPUTE_SEGREGATION, "Resolver is the visit completer", 403)

    dispute["resolved_by_user_id"] = user_id

    if outcome == "UPHELD":
        dispute["status"] = "RESOLVED_UPHELD"
        dispute["resolution_credit_cents"] = 0
        if visit:
            visit["billing_status"] = "SETTLED"
            _touch(visit)
            db.visits.update(visit["id"], visit)

    elif outcome == "ADJUSTED":
        if credit_cents is None or credit_cents <= 0:
            raise ApiError(ERR_INVALID_REQUEST, "credit_cents must be > 0 for ADJUSTED", 400)

        # Compute visit's combined line amount on this invoice
        visit_line_total = 0
        if invoice:
            for line in invoice.get("lines", []):
                if line.get("visit_id") == dispute.get("visit_id"):
                    visit_line_total += line.get("line_cents", 0)
        if credit_cents > visit_line_total:
            raise ApiError(ERR_INVALID_REQUEST, f"credit_cents {credit_cents} exceeds visit line total {visit_line_total}", 400)

        dispute["status"] = "RESOLVED_ADJUSTED"
        dispute["resolution_credit_cents"] = credit_cents

        # Credit the invoice
        if invoice:
            invoice["credit_cents"] = (invoice.get("credit_cents") or 0) + credit_cents
            invoice["total_cents"] = (invoice.get("subtotal_cents") or 0) - invoice["credit_cents"]
            invoice["status"] = "PARTIALLY_CREDITED"
            _touch(invoice)
            db.invoices.update(invoice["id"], invoice)

        if visit:
            visit["billing_status"] = "SETTLED"
            _touch(visit)
            db.visits.update(visit["id"], visit)

        # Recompute
        if invoice and invoice.get("contract_id"):
            recompute_contract_accumulators(invoice["contract_id"])
        if invoice:
            contract = db.contracts.get(invoice.get("contract_id"))
            if contract:
                client = db.clients.get(contract.get("client_id"))
                if client:
                    _touch_client(client["id"])

    elif outcome == "REMOVED":
        dispute["status"] = "RESOLVED_REMOVED"

        # Credit invoice by ALL lines of this visit
        total_credit = 0
        if invoice:
            for line in invoice.get("lines", []):
                if line.get("visit_id") == dispute.get("visit_id"):
                    total_credit += line.get("line_cents", 0)
            invoice["credit_cents"] = (invoice.get("credit_cents") or 0) + total_credit
            invoice["total_cents"] = (invoice.get("subtotal_cents") or 0) - invoice["credit_cents"]
            invoice["status"] = "PARTIALLY_CREDITED"
            _touch(invoice)
            db.invoices.update(invoice["id"], invoice)

        dispute["resolution_credit_cents"] = total_credit

        if visit:
            visit["billing_status"] = "WRITTEN_OFF"
            _touch(visit)
            db.visits.update(visit["id"], visit)

        # Recompute
        if invoice and invoice.get("contract_id"):
            recompute_contract_accumulators(invoice["contract_id"])
        if invoice:
            contract = db.contracts.get(invoice.get("contract_id"))
            if contract:
                client = db.clients.get(contract.get("client_id"))
                if client:
                    _touch_client(client["id"])

    _touch(dispute)
    db.disputes.update(id, dispute)
    return success_object(dispute)
