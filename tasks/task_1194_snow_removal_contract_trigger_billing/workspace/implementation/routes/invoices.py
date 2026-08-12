"""Invoice endpoints — create, get, list, issue, void, pay."""
from flask import Blueprint, request
from datetime import timedelta
import db
from middleware import require_roles, get_pagination, get_json_body
from response import success_object, success_created, success_list
from errors import *
from services.helpers import (
    recompute_contract_accumulators, _touch, _touch_client,
    recompute_invoice_lines,
)

bp = Blueprint("invoices", __name__)

ALLOWED_CREATE_FIELDS = {"contract_id", "kind", "storm_event_id", "period_start", "period_end"}


@bp.route("/invoices", methods=["POST"])
def create_invoice():
    user_id, role = require_roles("OpsDispatcher")
    body = get_json_body()
    unknown = set(body.keys()) - ALLOWED_CREATE_FIELDS
    if unknown:
        raise ApiError(ERR_INVALID_REQUEST, f"Unknown fields: {', '.join(unknown)}", 400)

    contract_id = body.get("contract_id")
    kind = body.get("kind")
    storm_event_id = body.get("storm_event_id")
    period_start = body.get("period_start")
    period_end = body.get("period_end")

    if not contract_id:
        raise ApiError(ERR_INVALID_REQUEST, "contract_id is required", 400)
    contract = db.contracts.get(contract_id)
    if not contract:
        raise ApiError(ERR_NOT_FOUND, f"Contract {contract_id} not found", 404)

    if not kind or kind not in ("EVENT", "PERIOD"):
        raise ApiError(ERR_INVALID_REQUEST, "kind must be EVENT or PERIOD", 400)

    # Contract-type conditional
    if kind == "EVENT" and contract.get("contract_type") != "PER_PUSH":
        raise ApiError(ERR_CONTRACT_TYPE_FORBIDS, "EVENT invoices only for PER_PUSH contracts", 409)
    if kind == "PERIOD" and contract.get("contract_type") != "HOURLY":
        raise ApiError(ERR_CONTRACT_TYPE_FORBIDS, "PERIOD invoices only for HOURLY contracts", 409)

    if kind == "EVENT":
        if not storm_event_id:
            raise ApiError(ERR_INVALID_REQUEST, "storm_event_id required for EVENT invoice", 400)
        event = db.storm_events.get(storm_event_id)
        if not event:
            raise ApiError(ERR_NOT_FOUND, f"StormEvent {storm_event_id} not found", 404)
        if event.get("status") not in ("VERIFIED", "CLOSED"):
            raise ApiError(ERR_EVENT_NOT_VERIFIED, "Storm event not VERIFIED/CLOSED", 409)
        # Uniqueness: one non-VOIDED EVENT invoice per (contract, event)
        for inv in db.invoices.list_all():
            if (inv.get("contract_id") == contract_id
                and inv.get("storm_event_id") == storm_event_id
                and inv.get("kind") == "EVENT"
                and inv.get("status") != "VOIDED"):
                raise ApiError(ERR_DUPLICATE_INVOICE, "Invoice already exists for this contract+event", 409)
    elif kind == "PERIOD":
        if not period_start or not period_end:
            raise ApiError(ERR_INVALID_REQUEST, "period_start and period_end required for PERIOD invoice", 400)
        ps = db._parse_iso(period_start)
        pe = db._parse_iso(period_end)
        if not ps or not pe:
            raise ApiError(ERR_INVALID_REQUEST, "Invalid period dates", 400)
        if pe <= ps:
            raise ApiError(ERR_INVALID_REQUEST, "period_end must be > period_start", 400)
        # Uniqueness: one non-VOIDED PERIOD invoice per (contract, period_start)
        for inv in db.invoices.list_all():
            if (inv.get("contract_id") == contract_id
                and inv.get("period_start") == period_start
                and inv.get("kind") == "PERIOD"
                and inv.get("status") != "VOIDED"):
                raise ApiError(ERR_DUPLICATE_INVOICE, "Invoice already exists for this contract+period", 409)

    invoice = {
        "id": db._new_id(),
        "contract_id": contract_id,
        "storm_event_id": storm_event_id,
        "kind": kind,
        "period_start": period_start,
        "period_end": period_end,
        "status": "DRAFT",
        "lines": [],
        "subtotal_cents": 0,
        "credit_cents": 0,
        "total_cents": 0,
        "paid_cents": 0,
        "issued_at": None,
        "issued_by_user_id": None,
        "created_at": db.now_iso(),
        "updated_at": db.now_iso(),
        "version": 1,
    }
    db.invoices.create(invoice)

    # Compute initial lines
    recompute_invoice_lines(invoice)

    return success_created(invoice)


def _get_invoice_or_404(id):
    inv = db.invoices.get(id)
    if not inv:
        raise ApiError(ERR_NOT_FOUND, f"Invoice {id} not found", 404)
    return inv


@bp.route("/invoices/<id>", methods=["GET"])
def get_invoice(id):
    user_id, role = require_roles("PlatformAdmin", "OpsDispatcher", "ClientContact", "ClaimsAdjuster")
    invoice = _get_invoice_or_404(id)
    if role == "ClientContact":
        contract = db.contracts.get(invoice.get("contract_id"))
        if contract and contract.get("client_id") != user_id:
            raise ApiError(ERR_FORBIDDEN_OWNERSHIP, "Not your invoice", 403)
    return success_object(invoice)


@bp.route("/invoices", methods=["GET"])
def list_invoices():
    user_id, role = require_roles("PlatformAdmin", "OpsDispatcher", "ClientContact")
    limit, offset = get_pagination()
    all_invoices = db.invoices.list_all()

    contract_id = request.args.get("contract_id")
    storm_event_id = request.args.get("storm_event_id")
    status = request.args.get("status")
    if contract_id:
        all_invoices = [i for i in all_invoices if i.get("contract_id") == contract_id]
    if storm_event_id:
        all_invoices = [i for i in all_invoices if i.get("storm_event_id") == storm_event_id]
    if status:
        all_invoices = [i for i in all_invoices if i.get("status") == status]
    if role == "ClientContact":
        all_invoices = [i for i in all_invoices if db.contracts.get(i.get("contract_id", ""), {}) and db.contracts.get(i.get("contract_id", "")).get("client_id") == user_id]

    all_invoices = sorted(all_invoices, key=lambda i: i.get("created_at", ""))
    total = len(all_invoices)
    page = all_invoices[offset:offset + limit]
    return success_list(page, total, limit, offset)


@bp.route("/invoices/<id>/issue", methods=["POST"])
def issue_invoice(id):
    user_id, role = require_roles("OpsDispatcher")
    invoice = _get_invoice_or_404(id)
    if invoice["status"] in ("PAID", "VOIDED"):
        raise ApiError(ERR_ALREADY_TERMINAL, f"Invoice is {invoice['status']} (terminal)", 409)
    if invoice["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, f"Cannot issue from {invoice['status']}", 409)

    contract = db.contracts.get(invoice.get("contract_id"))
    if not contract:
        raise ApiError(ERR_NOT_FOUND, "Contract not found", 404)

    # Must have >= 1 line
    if not invoice.get("lines") or len(invoice["lines"]) == 0:
        raise ApiError(ERR_INVOICE_EMPTY, "Invoice has no lines", 422)

    # Contract must be ACTIVE, or EXPIRED with clock <= season_end + 60 days
    clock = db.get_clock()
    if contract["status"] == "ACTIVE":
        pass
    elif contract["status"] == "EXPIRED":
        se = db._parse_iso(contract.get("season_end"))
        if se:
            billing_deadline = se + timedelta(days=60)
            if clock > billing_deadline:
                raise ApiError(ERR_INVALID_STATE, "Post-season billing window expired", 409)
    else:
        raise ApiError(ERR_INVALID_STATE, f"Contract is {contract['status']}", 409)

    # Credit gate
    client = db.clients.get(contract.get("client_id"))
    if client:
        exposure = client.get("credit_exposure_cents") or 0
        total = invoice.get("total_cents") or 0
        limit = client.get("credit_limit_cents") or 0
        if exposure + total > limit:
            raise ApiError(ERR_CLIENT_CREDIT_EXCEEDED, f"Exposure {exposure} + {total} > limit {limit}", 422)

    # Issue
    invoice["status"] = "ISSUED"
    invoice["issued_at"] = db.now_iso()
    invoice["issued_by_user_id"] = user_id

    # Move line visits to INVOICED
    for line in invoice.get("lines", []):
        v = db.visits.get(line.get("visit_id"))
        if v and v.get("billing_status") == "BILLABLE_CONFIRMED":
            v["billing_status"] = "INVOICED"
            _touch(v)
            db.visits.update(v["id"], v)

    _touch(invoice)
    db.invoices.update(id, invoice)

    # Contract season_billed_cents and version
    recompute_contract_accumulators(contract["id"])
    _touch(contract)
    db.contracts.update(contract["id"], contract)

    # Client exposure
    if client:
        _touch_client(client["id"])

    return success_object(invoice)


@bp.route("/invoices/<id>/void", methods=["POST"])
def void_invoice(id):
    user_id, role = require_roles("OpsDispatcher")
    invoice = _get_invoice_or_404(id)
    if invoice["status"] in ("PAID", "VOIDED"):
        raise ApiError(ERR_ALREADY_TERMINAL, f"Invoice is {invoice['status']} (terminal)", 409)

    if invoice["status"] == "DRAFT":
        invoice["status"] = "VOIDED"
        _touch(invoice)
        db.invoices.update(id, invoice)
        return success_object(invoice)

    # ISSUED / PARTIALLY_PAID / PARTIALLY_CREDITED
    if invoice.get("paid_cents", 0) > 0:
        raise ApiError(ERR_INVOICE_HAS_PAYMENTS, "Invoice has payments", 409)

    # No open disputes
    for d in db.disputes.list_all():
        if d.get("invoice_id") == id and d.get("status") in ("OPEN", "EVIDENCE_REVIEW"):
            raise ApiError(ERR_INVALID_STATE, "Invoice has open disputes", 409)

    old_total = invoice.get("total_cents") or 0
    invoice["status"] = "VOIDED"
    _touch(invoice)
    db.invoices.update(id, invoice)

    # Line visits back to BILLABLE_CONFIRMED
    for line in invoice.get("lines", []):
        v = db.visits.get(line.get("visit_id"))
        if v and v.get("billing_status") == "INVOICED":
            v["billing_status"] = "BILLABLE_CONFIRMED"
            _touch(v)
            db.visits.update(v["id"], v)

    # Compensation
    contract = db.contracts.get(invoice.get("contract_id"))
    if contract:
        recompute_contract_accumulators(contract["id"])
        _touch(contract)
        db.contracts.update(contract["id"], contract)

    client = db.clients.get(contract.get("client_id")) if contract else None
    if client:
        _touch_client(client["id"])

    return success_object(invoice)


@bp.route("/invoices/<id>/pay", methods=["POST"])
def pay_invoice(id):
    user_id, role = require_roles("OpsDispatcher")
    invoice = _get_invoice_or_404(id)
    if invoice["status"] in ("PAID", "VOIDED"):
        raise ApiError(ERR_ALREADY_TERMINAL, f"Invoice is {invoice['status']} (terminal)", 409)
    if invoice["status"] not in ("ISSUED", "PARTIALLY_PAID", "PARTIALLY_CREDITED"):
        raise ApiError(ERR_INVALID_STATE, f"Cannot pay from {invoice['status']}", 409)

    body = get_json_body()
    amount = body.get("amount_cents")
    if amount is None or amount <= 0:
        raise ApiError(ERR_OVERPAYMENT, "amount_cents must be > 0", 422)

    remaining = (invoice.get("total_cents") or 0) - (invoice.get("paid_cents") or 0)
    if amount > remaining:
        raise ApiError(ERR_OVERPAYMENT, f"amount {amount} > remaining {remaining}", 422)

    invoice["paid_cents"] = (invoice.get("paid_cents") or 0) + amount
    if invoice["paid_cents"] >= (invoice.get("total_cents") or 0):
        invoice["status"] = "PAID"
    else:
        invoice["status"] = "PARTIALLY_PAID"

    _touch(invoice)
    db.invoices.update(id, invoice)

    # Client exposure
    contract = db.contracts.get(invoice.get("contract_id"))
    if contract:
        client = db.clients.get(contract.get("client_id"))
        if client:
            _touch_client(client["id"])

    return success_object(invoice)
