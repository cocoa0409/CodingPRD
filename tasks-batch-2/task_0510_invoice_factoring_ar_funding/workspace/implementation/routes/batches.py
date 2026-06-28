"""PurchaseBatch endpoints (§3.5). The /fund endpoint is the most heavily
guarded operation: OCC, segregation-of-duties, then per-invoice funding
preconditions evaluated in array order, all-or-nothing transactional."""

import copy

from flask import Blueprint, request

import db
import errors
from common import public, req_str, req_str_list, stamp_common, touch
from middleware import authenticate, authorize, ALL_ROLES
from response import success
from routes.helpers import get_body, lookup, list_response
from services import calc, transitions

bp = Blueprint("batches", __name__)

# HTTP status for each per-invoice funding precondition error (all 409 per §1.6).
_ERROR_HTTP = {
    errors.ERR_FUNDING_BLOCKED: 409,
    errors.ERR_CONCENTRATION_EXCEEDED: 409,
    errors.ERR_DEBTOR_CEILING_EXCEEDED: 409,
    errors.ERR_CREDIT_LIMIT_EXCEEDED: 409,
}


@bp.post("/factoring/purchase-batches")
def create_batch():
    _, role = authenticate()
    authorize(role, ("FundingOfficer",))
    body = get_body()
    client_id = req_str(body, "client_id")
    if client_id not in db.clients:
        raise errors.not_found("client_id does not resolve")
    batch_reference = req_str(body, "batch_reference")
    invoice_ids = req_str_list(body, "invoice_ids")
    # FK existence of every invoice_ids member (priority 4).
    for iid in invoice_ids:
        if iid not in db.invoices:
            raise errors.not_found(f"invoice_id {iid} does not resolve")

    batch = {
        "client_id": client_id,
        "batch_reference": batch_reference,
        "invoice_ids": list(invoice_ids),
        "total_advance_cents": 0,
        "failure_error_id": None,
        "status": "DRAFT",
    }
    stamp_common(batch)
    db.purchase_batches[batch["id"]] = batch
    return success(public(batch), status=201)


@bp.get("/factoring/purchase-batches")
def list_batches():
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    client_id = request.args.get("client_id")
    status = request.args.get("status")
    records = []
    for b in db.purchase_batches.values():
        if client_id is not None and b["client_id"] != client_id:
            continue
        if status is not None and b["status"] != status:
            continue
        records.append(b)
    return list_response(records)


@bp.get("/factoring/purchase-batches/<batch_id>")
def read_batch(batch_id):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    batch = lookup(db.purchase_batches, batch_id)
    return success(public(batch), status=200)


def _funding_precondition_error(invoice, client, debtor, program, rel,
                                running_debtor_face, running_client_face,
                                running_client_funded_advance, advance):
    """Evaluate per-invoice funding preconditions in the PRD-defined order.
    Returns an error_id string if one fails, else None.

    The running_* accumulators reflect prior invoices funded earlier in this
    same batch (which mutate denormalized balances in array order).
    """
    # ERR_FUNDING_BLOCKED: client APPROVED, program ACTIVE, relationship NOTICED.
    if (client["status"] != "APPROVED" or program["status"] != "ACTIVE"
            or rel is None or rel["notice_status"] != "NOTICED"):
        return errors.ERR_FUNDING_BLOCKED

    face = invoice["face_amount_cents"]

    # ERR_CONCENTRATION_EXCEEDED (exact integer cross-multiplication, candidate
    # included on both sides; '>' rejects, '==' allows).
    limit = rel["concentration_limit_pct"]
    if limit is None:
        limit = client["default_concentration_limit_pct"]
    if calc.concentration_breached(running_debtor_face, face,
                                   running_client_face, limit):
        return errors.ERR_CONCENTRATION_EXCEEDED

    # ERR_DEBTOR_CEILING_EXCEEDED.
    if running_debtor_face + face > debtor["approved_credit_ceiling_cents"]:
        return errors.ERR_DEBTOR_CEILING_EXCEEDED

    # ERR_CREDIT_LIMIT_EXCEEDED: candidate advance vs remaining headroom.
    headroom = client["credit_limit_cents"] - running_client_funded_advance
    if advance > headroom:
        return errors.ERR_CREDIT_LIMIT_EXCEEDED

    return None


@bp.post("/factoring/purchase-batches/<batch_id>/fund")
def fund_batch(batch_id):
    user_id, role = authenticate()
    authorize(role, ("FundingOfficer",))
    batch = lookup(db.purchase_batches, batch_id)
    body = get_body()

    client = db.clients.get(batch["client_id"])

    # Priority 8: OCC on Client.version.
    if "expected_client_version" not in body or body["expected_client_version"] is None:
        raise errors.invalid_request("expected_client_version is required")
    expected = body["expected_client_version"]
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise errors.invalid_request("expected_client_version must be an integer")
    if expected != client["version"]:
        raise errors.stale_version()

    # Priority 9: segregation of duties — funding user must differ from the
    # credit_decision_user_id of BOTH the client and the debtor of every invoice.
    for iid in batch["invoice_ids"]:
        inv = db.invoices.get(iid)
        if inv is None:
            continue
        c = db.clients.get(inv["client_id"])
        d = db.debtors.get(inv["debtor_id"])
        if (c and c.get("credit_decision_user_id") == user_id) or \
           (d and d.get("credit_decision_user_id") == user_id):
            raise errors.ApiError(errors.ERR_SEGREGATION_OF_DUTIES, 403,
                                  "Funding user underwrote a party in this batch")

    # Priority 10: batch state validity.
    if batch["status"] != "DRAFT":
        raise errors.invalid_state("Batch is not DRAFT")

    # Per-invoice precondition pass (in array order). Determine the first
    # failure WITHOUT mutating any persisted state. We simulate the running
    # denormalized balances as earlier invoices in the batch would fund.
    program = db.programs.get(client["program_id"])

    # Seed running accumulators from current persisted exposure.
    running_debtor_face = {}   # debtor_id -> face accumulator
    running_client_face = 0
    running_client_funded_advance = client["funded_advance_outstanding_cents"]
    # Initialise client portfolio face from existing exposure invoices.
    for inv in db.invoices.values():
        if inv["client_id"] == client["id"] and inv["status"] in calc.EXPOSURE_STATUSES:
            running_client_face += inv["face_amount_cents"]

    plan = []  # (invoice, debtor, advance)
    failure_error = None
    for iid in batch["invoice_ids"]:
        invoice = db.invoices.get(iid)
        # Per-invoice state must be VERIFIED; a non-VERIFIED invoice is a
        # funding precondition failure (ERR_FUNDING_BLOCKED).
        if invoice["status"] != "VERIFIED":
            failure_error = errors.ERR_FUNDING_BLOCKED
            break
        debtor = db.debtors.get(invoice["debtor_id"])
        rel = db.relationships.get(invoice["relationship_id"]) if invoice["relationship_id"] else None

        advance, _reserve = calc.advance_split(invoice["face_amount_cents"],
                                               client["approved_advance_rate_pct"])
        dface = running_debtor_face.get(invoice["debtor_id"], debtor["outstanding_face_cents"] if debtor else 0)

        err = _funding_precondition_error(
            invoice, client, debtor, program, rel,
            running_debtor_face=dface,
            running_client_face=running_client_face,
            running_client_funded_advance=running_client_funded_advance,
            advance=advance,
        )
        if err is not None:
            failure_error = err
            break

        # Advance running accumulators as if this invoice funded.
        running_debtor_face[invoice["debtor_id"]] = dface + invoice["face_amount_cents"]
        running_client_face += invoice["face_amount_cents"]
        running_client_funded_advance += advance
        plan.append((invoice, debtor, advance))

    if failure_error is not None:
        # All-or-nothing: nothing funded; batch -> FAILED (the mutation persists)
        # and the call surfaces the first failing invoice's error as an error
        # envelope with that error_id and its catalog HTTP status.
        batch["status"] = "FAILED"
        batch["failure_error_id"] = failure_error
        touch(batch)
        raise errors.ApiError(failure_error, _ERROR_HTTP[failure_error],
                              f"Batch funding failed: {failure_error}")

    # Commit: fund each invoice in array order with full side-effects.
    total_advance = 0
    for invoice, debtor, _advance in plan:
        transitions.fund_invoice(invoice, client, debtor, program)
        total_advance += invoice["advance_amount_cents"]
        touch(client)  # Client.version +1 per funded invoice.

    batch["status"] = "FUNDED"
    batch["total_advance_cents"] = total_advance
    touch(batch)
    return success(public(batch), status=200)
