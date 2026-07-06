"""Fulfillment partner + job + reprint request endpoints."""
from flask import Blueprint, request

import db
from errors import raise_error
from middleware import require_auth
from response import ok, created, paginate_and_serialize
from services.calc import REASON_WEIGHTS, reprint_surcharge_partner_charge
from services.serialize import serialize

bp = Blueprint("fulfillment", __name__)


# ==== FulfillmentPartner ====

def _get_partner_or_404(pid):
    row = db.fulfillment_partners.get(pid)
    if not row:
        raise_error("ERR_NOT_FOUND", f"partner {pid} not found")
    return row


@bp.post("/pod/fulfillment-partners")
@require_auth(["PlatformAdmin"])
def create_partner():
    body = request.get_json(silent=True) or {}
    for f in ("name", "country_code", "cost_multiplier_bps"):
        if f not in body:
            raise_error("ERR_INVALID_REQUEST", f"missing {f}")
    if not isinstance(body["cost_multiplier_bps"], int) or isinstance(body["cost_multiplier_bps"], bool):
        raise_error("ERR_INVALID_REQUEST", "cost_multiplier_bps must be int")
    max_backlog = body.get("max_backlog_hours", 168)
    if not isinstance(max_backlog, int) or isinstance(max_backlog, bool):
        raise_error("ERR_INVALID_REQUEST", "max_backlog_hours must be int")

    row = db.new_common_fields()
    row.update(
        {
            "name": body["name"],
            "country_code": body["country_code"],
            "cost_multiplier_bps": body["cost_multiplier_bps"],
            "current_backlog_hours": 0,
            "max_backlog_hours": max_backlog,
            "status": "ACTIVE",
        }
    )
    db.fulfillment_partners.insert(row)
    return created(serialize(row))


@bp.get("/pod/fulfillment-partners/<pid>")
@require_auth(["PlatformAdmin", "FulfillmentPartner"])
def read_partner(pid):
    return ok(serialize(_get_partner_or_404(pid)))


@bp.get("/pod/fulfillment-partners")
@require_auth(["PlatformAdmin"])
def list_partners():
    country_code = request.args.get("country_code")
    status = request.args.get("status")
    rows = db.fulfillment_partners.all()
    if country_code is not None:
        rows = [r for r in rows if r["country_code"] == country_code]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    rows = db.sorted_rows(rows)
    return paginate_and_serialize(rows, serialize)


# ==== FulfillmentJob ====

def _get_job_or_404(jid):
    row = db.fulfillment_jobs.get(jid)
    if not row:
        raise_error("ERR_NOT_FOUND", f"fulfillment_job {jid} not found")
    return row


@bp.get("/pod/fulfillment-jobs/<jid>")
@require_auth(["Creator", "PlatformAdmin", "FulfillmentPartner"])
def read_job(jid):
    return ok(serialize(_get_job_or_404(jid)))


@bp.get("/pod/fulfillment-jobs")
@require_auth(["Creator", "PlatformAdmin", "FulfillmentPartner"])
def list_jobs():
    order_id = request.args.get("order_id")
    partner_id = request.args.get("partner_id")
    rows = db.fulfillment_jobs.all()
    if order_id is not None:
        rows = [r for r in rows if r["order_id"] == order_id]
    if partner_id is not None:
        rows = [r for r in rows if r["partner_id"] == partner_id]
    rows = db.sorted_rows(rows)
    return paginate_and_serialize(rows, serialize)


@bp.post("/pod/fulfillment-jobs/<jid>/mark-failed")
@require_auth(["FulfillmentPartner"])
def mark_failed(jid):
    job = _get_job_or_404(jid)
    if job["status"] != "SHIPPED":
        raise_error("ERR_INVALID_STATE", "job must be SHIPPED to mark failed")
    job["status"] = "FAILED"
    db.bump(job)
    return ok(serialize(job))


@bp.post("/pod/fulfillment-jobs/<jid>/reprint-requests")
@require_auth(["PlatformAdmin"])
def open_reprint(jid):
    job = _get_job_or_404(jid)
    if job["status"] != "FAILED":
        raise_error("ERR_INVALID_STATE", "job must be FAILED to open reprint")
    # Linked order must be SHIPPED per priority 5 override.
    order = db.orders.get(job["order_id"])
    if not order:
        raise_error("ERR_NOT_FOUND", "order not found")
    if order["fulfillment_status"] != "SHIPPED":
        raise_error("ERR_REPRINT_ORDER_NOT_SHIPPED", "linked order not SHIPPED")

    body = request.get_json(silent=True) or {}
    for f in ("fault_category", "reason_code"):
        if f not in body:
            raise_error("ERR_INVALID_REQUEST", f"missing {f}")
    if body["fault_category"] not in ("PARTNER_FAULT", "CONSUMER_FAULT", "PLATFORM_GESTURE"):
        raise_error("ERR_INVALID_REQUEST", "invalid fault_category")
    if body["reason_code"] not in ("WRONG_SIZE", "DAMAGED", "MISPRINT", "LATE", "OTHER"):
        raise_error("ERR_INVALID_REQUEST", "invalid reason_code")

    row = db.new_common_fields()
    row.update(
        {
            "job_id": job["id"],
            "fault_category": body["fault_category"],
            "reason_code": body["reason_code"],
            "status": "OPEN",
        }
    )
    db.reprint_requests.insert(row)

    job["status"] = "REPRINT_REQUESTED"
    db.bump(job)

    return created(serialize(row))


# ==== ReprintRequest ====

def _get_reprint_or_404(rid):
    row = db.reprint_requests.get(rid)
    if not row:
        raise_error("ERR_NOT_FOUND", f"reprint request {rid} not found")
    return row


@bp.get("/pod/reprint-requests/<rid>")
@require_auth(["Creator", "PlatformAdmin"])
def read_reprint(rid):
    return ok(serialize(_get_reprint_or_404(rid)))


@bp.get("/pod/reprint-requests")
@require_auth(["Creator", "PlatformAdmin"])
def list_reprints():
    job_id = request.args.get("job_id")
    rows = db.reprint_requests.all()
    if job_id is not None:
        rows = [r for r in rows if r["job_id"] == job_id]
    rows = db.sorted_rows(rows)
    return paginate_and_serialize(rows, serialize)


@bp.post("/pod/reprint-requests/<rid>/approve")
@require_auth(["PlatformAdmin"])
def approve_reprint(rid):
    req = _get_reprint_or_404(rid)
    if req["status"] != "OPEN":
        raise_error("ERR_INVALID_STATE", "reprint must be OPEN")
    job = db.fulfillment_jobs.get(req["job_id"])
    if not job or job["status"] != "REPRINT_REQUESTED":
        raise_error("ERR_INVALID_STATE", "job must be REPRINT_REQUESTED")
    order = db.orders.get(job["order_id"])
    if not order:
        raise_error("ERR_NOT_FOUND", "order not found")
    if order["fulfillment_status"] != "SHIPPED":
        raise_error("ERR_REPRINT_ORDER_NOT_SHIPPED", "linked order not SHIPPED")

    req["status"] = "APPROVED"
    db.bump(req)

    job["status"] = "QUEUED"
    job["reprint_generation"] = int(job["reprint_generation"]) + 1

    # Reprint surcharge: consumer_fault -> apply; else unchanged.
    if req["fault_category"] == "CONSUMER_FAULT":
        initial = order.get("_initial_partner_charge_cents") or int(job["partner_charge_cents"])
        job["partner_charge_cents"] = reprint_surcharge_partner_charge(
            initial, int(job["reprint_generation"])
        )
    db.bump(job)

    # Order retrograde: SHIPPED -> IN_PRINT (PRD §3.8 approval side-effect).
    order["fulfillment_status"] = "IN_PRINT"
    db.bump(order)

    # Creator strike increment on CONSUMER_FAULT.
    if req["fault_category"] == "CONSUMER_FAULT":
        listing = db.listings.get(order["listing_id"])
        storefront = db.storefronts.get(listing["storefront_id"]) if listing else None
        creator = db.creators.get(storefront["creator_id"]) if storefront else None
        if creator:
            creator["reprint_strike_count"] = int(creator.get("reprint_strike_count", 0)) + 1
            db.bump(creator)

    return ok(serialize(req))


@bp.post("/pod/reprint-requests/<rid>/deny")
@require_auth(["PlatformAdmin"])
def deny_reprint(rid):
    req = _get_reprint_or_404(rid)
    if req["status"] != "OPEN":
        raise_error("ERR_INVALID_STATE", "reprint must be OPEN")
    job = db.fulfillment_jobs.get(req["job_id"])
    if not job or job["status"] != "REPRINT_REQUESTED":
        raise_error("ERR_INVALID_STATE", "job must be REPRINT_REQUESTED")
    req["status"] = "DENIED"
    db.bump(req)
    job["status"] = "CANCELLED"
    db.bump(job)
    return ok(serialize(req))
