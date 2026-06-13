"""Dispute file / fetch / list / review / withdraw / resolve (PRD §3.10).

Dispute state machine: OPEN -> UNDER_REVIEW -> APPROVED/DENIED; OPEN/UNDER_REVIEW
-> WITHDRAWN. Approval fires the backward refund cascade through the invoice, the
customer wallet, and the Pro callback counters.
"""
from flask import Blueprint, request, g

from db import store
from errors import ApiError
from middleware import require_role
from models import common, touch, serialize, DISPUTE_FIELDS
from response import object_response, array_response
from services import pricing
from services.lookup import (
    require_body, require_string, require_enum, require_int, get_or_404,
    paginate, sorted_by_creation,
)

bp = Blueprint("disputes", __name__)

_REASONS = {"WORK_INCOMPLETE", "OVERCHARGED", "DAMAGE", "NO_SHOW"}
_DESTINATIONS = {"ORIGINAL", "WALLET"}


def _v_file_dispute(body):
    return {
        "job_id": require_string(body, "job_id"),
        "invoice_id": require_string(body, "invoice_id"),
        "reason": require_enum(body, "reason", _REASONS),
        "requested": require_int(body, "requested_refund_cents"),
        "refund_destination": require_enum(body, "refund_destination", _DESTINATIONS,
                                           required=False, default="ORIGINAL"),
    }


@bp.post("/disputes")
@require_role({"Customer"}, validate=_v_file_dispute)
def file_dispute():
    job_id = g.validated["job_id"]
    invoice_id = g.validated["invoice_id"]
    reason = g.validated["reason"]
    requested = g.validated["requested"]
    refund_destination = g.validated["refund_destination"]

    # existence: body FKs in declaration order (job_id then invoice_id).
    job = get_or_404(store.jobs, job_id)
    invoice = get_or_404(store.invoices, invoice_id)

    # ERR_VALIDATION (422): requested_refund_cents >= 1 (semantic body coherence).
    if requested < 1:
        raise ApiError("ERR_VALIDATION", "requested_refund_cents must be >= 1")

    # ownership: Customer must own the disputed job.
    if g.user_id != job["customer_id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "Customer does not own this job")

    dispute = {
        "job_id": job_id,
        "invoice_id": invoice_id,
        "reason": reason,
        "requested_refund_cents": requested,
        "refund_destination": refund_destination,
        "approved_refund_cents": None,
        "status": "OPEN",
    }
    common(dispute)
    store.disputes[dispute["id"]] = dispute
    return object_response(serialize(dispute, DISPUTE_FIELDS), status=201)


@bp.get("/disputes/<did>")
@require_role({"PlatformAdmin", "Customer"})
def get_dispute(did):
    dispute = get_or_404(store.disputes, did)
    if g.role == "Customer":
        job = store.jobs.get(dispute["job_id"])
        if job is None or job["customer_id"] != g.user_id:
            raise ApiError("ERR_NOT_RESOURCE_OWNER", "Customer does not own this dispute")
    return object_response(serialize(dispute, DISPUTE_FIELDS))


@bp.get("/disputes")
@require_role({"PlatformAdmin", "Customer"})
def list_disputes():
    items = list(store.disputes.values())
    job_id = request.args.get("job_id")
    invoice_id = request.args.get("invoice_id")
    if job_id is not None:
        items = [d for d in items if d["job_id"] == job_id]
    if invoice_id is not None:
        items = [d for d in items if d["invoice_id"] == invoice_id]
    # a Customer sees only disputes on jobs they own.
    if g.role == "Customer":
        items = [d for d in items
                 if store.jobs.get(d["job_id"], {}).get("customer_id") == g.user_id]
    items = sorted_by_creation(items)
    page, limit, offset, total = paginate(request.args, items)
    return array_response([serialize(d, DISPUTE_FIELDS) for d in page],
                          limit, offset, total)


@bp.post("/disputes/<did>/review")
@require_role({"PlatformAdmin"})
def review_dispute(did):
    dispute = get_or_404(store.disputes, did)
    if dispute["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", "Review only from OPEN")
    invoice = store.invoices[dispute["invoice_id"]]
    if invoice["status"] not in ("PAID", "REFUNDED"):
        raise ApiError("ERR_INVALID_STATE", "Invoice must be PAID or REFUNDED to review")
    dispute["status"] = "UNDER_REVIEW"
    touch(dispute)
    return object_response(serialize(dispute, DISPUTE_FIELDS))


@bp.post("/disputes/<did>/withdraw")
@require_role({"Customer"})
def withdraw_dispute(did):
    dispute = get_or_404(store.disputes, did)
    job = store.jobs[dispute["job_id"]]
    if g.user_id != job["customer_id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "Customer does not own this dispute")
    if dispute["status"] not in ("OPEN", "UNDER_REVIEW"):
        raise ApiError("ERR_INVALID_STATE", "Withdraw only from OPEN or UNDER_REVIEW")
    dispute["status"] = "WITHDRAWN"
    touch(dispute)
    return object_response(serialize(dispute, DISPUTE_FIELDS))


def _v_resolve(body):
    decision = require_enum(body, "decision", {"APPROVE", "DENY"})
    # approved_refund_cents is consumed only on APPROVE; validate shape if present.
    approved_raw = body.get("approved_refund_cents")
    if approved_raw is not None and (
            isinstance(approved_raw, bool) or not isinstance(approved_raw, int)):
        raise ApiError("ERR_INVALID_REQUEST", "approved_refund_cents must be an integer")
    return {"decision": decision, "approved_raw": approved_raw}


@bp.post("/disputes/<did>/resolve")
@require_role({"PlatformAdmin"}, validate=_v_resolve)
def resolve_dispute(did):
    decision = g.validated["decision"]
    approved_raw = g.validated["approved_raw"]

    dispute = get_or_404(store.disputes, did)
    if dispute["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_STATE", "Resolve only from UNDER_REVIEW")
    invoice = store.invoices[dispute["invoice_id"]]

    if decision == "DENY":
        dispute["approved_refund_cents"] = 0
        dispute["status"] = "DENIED"
        touch(dispute)
        return object_response(serialize(dispute, DISPUTE_FIELDS))

    # APPROVE: 0 < approved_refund_cents <= amount_paid - already-refunded.
    if approved_raw is None:
        raise ApiError("ERR_INVALID_REQUEST", "approved_refund_cents required on APPROVE")
    refundable = invoice["amount_paid_cents"] - invoice["refunded_cents"]
    if approved_raw <= 0 or approved_raw > refundable:
        raise ApiError("ERR_REFUND_EXCEEDS_PAID",
                       "approved_refund_cents out of refundable range")

    # --- approval cascade (PRD §3.10) ---
    dispute["approved_refund_cents"] = approved_raw
    dispute["status"] = "APPROVED"
    touch(dispute)

    invoice["refunded_cents"] += approved_raw
    pricing.reconcile_balance(invoice)
    # cumulative full refund -> PAID -> REFUNDED.
    if invoice["refunded_cents"] == invoice["amount_paid_cents"]:
        invoice["status"] = "REFUNDED"
    touch(invoice)

    if dispute["refund_destination"] == "WALLET":
        customer = store.customers[store.jobs[dispute["job_id"]]["customer_id"]]
        customer["wallet_credit_cents"] += approved_raw
        touch(customer)

    # WORK_INCOMPLETE: auto-cancel an open warranty callback job, decrement the
    # Pro's callback_job_count, and recompute callback_rate.
    if dispute["reason"] == "WORK_INCOMPLETE":
        job = store.jobs[dispute["job_id"]]
        callback = _open_callback_for(job["id"])
        if callback is not None:
            callback["status"] = "CANCELLED"
            touch(callback)
            pro = store.pros.get(job.get("pro_id"))
            if pro is not None:
                pro["callback_job_count"] = max(0, pro["callback_job_count"] - 1)
                pro["callback_rate"] = pricing.callback_rate(pro)
                touch(pro)

    return object_response(serialize(dispute, DISPUTE_FIELDS))


def _open_callback_for(parent_job_id):
    """Find a not-yet-terminal warranty callback job spawned from this job."""
    for j in store.jobs.values():
        if (j.get("parent_job_id") == parent_job_id
                and j["is_warranty_callback"]
                and j["status"] not in ("CANCELLED", "COMPLETED")):
            return j
    return None
