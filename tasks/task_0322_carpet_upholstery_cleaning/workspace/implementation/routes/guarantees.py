"""Re-clean guarantee claims (PRD §3.5)."""
from __future__ import annotations

from flask import Blueprint, g, request

import db
from errors import (
    APIError,
    ERR_CLAIM_NOT_FILED,
    ERR_GUARANTEE_WINDOW_EXPIRED,
    ERR_JOB_NOT_COMPLETED,
    ERR_NOT_RESOURCE_OWNER,
)
from middleware import is_customer, require
from response import ok_array, ok_object
from services.calculations import (
    GUARANTEE_GOODWILL_CENTS,
    guarantee_eligible,
)
from services.common import (
    by_created_asc,
    get_json_body,
    init_common,
    init_ledger,
    paginate,
    parse_pagination,
    public,
    public_list,
    require_int,
    require_str,
    touch,
)
from services.computed import recompute_wallet_credit, rooms_of_job
from services.lookups import get_claim, get_job

bp = Blueprint("guarantees", __name__)


@bp.post("/guarantee-claims")
def file_claim():
    require(["Customer", "ServiceManager"])
    body = get_json_body()
    cleaning_job_id = require_str(body, "cleaning_job_id")
    job = get_job(cleaning_job_id)
    reason = require_str(body, "reason")
    filed_at_minute = require_int(body, "filed_at_minute", minimum=0)

    # ownership (priority 5): a Customer files only on their own job
    if is_customer() and job["customer_id"] != g.user_id:
        raise APIError(ERR_NOT_RESOURCE_OWNER, 403, "Customer does not own this job")

    claim = init_common({
        "cleaning_job_id": cleaning_job_id,
        "reason": reason,
        "filed_at_minute": filed_at_minute,
        "reclean_job_id": None,
        "status": "FILED",
    })
    db.guarantee_claims[claim["id"]] = claim
    return ok_object(public(claim), 201)


@bp.get("/guarantee-claims/<cid>")
def get_claim_ep(cid):
    require(["Customer", "ServiceManager"])
    c = get_claim(cid)
    return ok_object(public(c), 200)


@bp.get("/cleaning-jobs/<jid>/guarantee-claims")
def list_job_claims(jid):
    require(["Customer", "ServiceManager"])
    get_job(jid)
    limit, offset = parse_pagination()
    rows = [c for c in db.guarantee_claims.values() if c["cleaning_job_id"] == jid]
    rows = by_created_asc(rows)
    window, total = paginate(rows, limit, offset)
    return ok_array(public_list(window), limit, offset, total, 200)


@bp.get("/guarantee-claims")
def list_claims():
    require(["Customer", "ServiceManager"])
    limit, offset = parse_pagination()
    rows = list(db.guarantee_claims.values())
    cleaning_job_id = request.args.get("cleaning_job_id")
    if cleaning_job_id is not None:
        rows = [c for c in rows if c["cleaning_job_id"] == cleaning_job_id]
    reclean_job_id = request.args.get("reclean_job_id")
    if reclean_job_id is not None:
        rows = [c for c in rows if c.get("reclean_job_id") == reclean_job_id]
    status = request.args.get("status")
    if status is not None:
        rows = [c for c in rows if c["status"] == status]
    rows = by_created_asc(rows)
    window, total = paginate(rows, limit, offset)
    return ok_array(public_list(window), limit, offset, total, 200)


@bp.post("/guarantee-claims/<cid>/grant")
def grant_claim(cid):
    require(["ServiceManager"])
    claim = get_claim(cid)

    # state gate (priority 6): claim must be FILED -> ERR_CLAIM_NOT_FILED
    if claim["status"] != "FILED":
        raise APIError(ERR_CLAIM_NOT_FILED, 409, "Claim is not FILED")

    origin = db.cleaning_jobs.get(claim["cleaning_job_id"])
    # referenced job must be COMPLETED -> ERR_JOB_NOT_COMPLETED
    if origin is None or origin["lifecycle_status"] != "COMPLETED":
        raise APIError(ERR_JOB_NOT_COMPLETED, 409, "Origin job is not COMPLETED")

    origin_catalog = db.service_catalogs[origin["service_catalog_id"]]
    # guarantee window (priority 11): filed - completed <= window, inclusive
    if not guarantee_eligible(claim["filed_at_minute"], origin["completed_at_minute"], origin_catalog):
        raise APIError(ERR_GUARANTEE_WINDOW_EXPIRED, 409, "Guarantee window expired")

    # mint a re-clean DRAFT job copying customer/catalog/plan, origin_job_id set
    reclean = init_common({
        "customer_id": origin["customer_id"],
        "service_catalog_id": origin["service_catalog_id"],
        "recurring_plan_id": origin["recurring_plan_id"],
        "origin_job_id": origin["id"],
        "move_furniture": origin.get("move_furniture", False),
        "total_sqft": 0,
        "quoted_price_cents": None,
        "settled_price_cents": None,
        "lifecycle_status": "DRAFT",
        "billing_status": "UNBILLED",
        "completed_at_minute": None,
        "scheduled_slot_id": None,
        "invoice_id": None,
    })
    db.cleaning_jobs[reclean["id"]] = reclean

    # copy each origin RoomAssessment onto the re-clean job (cascade hop)
    for r in by_created_asc(rooms_of_job(origin["id"])):
        copy = init_common({
            "cleaning_job_id": reclean["id"],
            "area_label": r["area_label"],
            "area_sqft": r["area_sqft"],
            "soiling_level": r["soiling_level"],
        })
        db.room_assessments[copy["id"]] = copy
    # keep re-clean total_sqft consistent with copied rooms
    reclean["total_sqft"] = sum(r["area_sqft"] for r in rooms_of_job(reclean["id"]))

    # grant goodwill wallet credit (cascade hop)
    customer = db.customers[origin["customer_id"]]
    entry = init_ledger({
        "customer_id": customer["id"],
        "delta_cents": GUARANTEE_GOODWILL_CENTS,
        "reason": "GUARANTEE_CREDIT",
        "cleaning_job_id": origin["id"],
    })
    db.wallet_ledger_entries[entry["id"]] = entry
    recompute_wallet_credit(customer)

    claim["reclean_job_id"] = reclean["id"]
    claim["status"] = "GRANTED"
    touch(claim)
    return ok_object(public(claim), 200)


@bp.post("/guarantee-claims/<cid>/deny")
def deny_claim(cid):
    require(["ServiceManager"])
    claim = get_claim(cid)
    # state gate (priority 6): claim must be FILED -> ERR_CLAIM_NOT_FILED
    if claim["status"] != "FILED":
        raise APIError(ERR_CLAIM_NOT_FILED, 409, "Claim is not FILED")
    # DENIED branch is deliberately the empty mirror: no reclean, no credit.
    claim["status"] = "DENIED"
    touch(claim)
    return ok_object(public(claim), 200)
