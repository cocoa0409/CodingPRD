"""Sourcing requests and the sample cycle."""

from flask import Blueprint, request

from db import new_id, public, stamp_new, store, touch
from errors import ApiError
from middleware import (
    ALL_ROLES,
    body_json,
    get_or_404,
    opt_str,
    paginate,
    req_enum,
    req_int,
    req_str,
    require_roles,
    sorted_created,
)
from response import success_list, success_object
from services.domain import REVISION_CAP

bp = Blueprint("sourcing_requests", __name__)

PRODUCT_CATEGORIES = ("APPAREL", "ELECTRONICS", "TOYS", "FURNITURE")
COMMISSION_MODES = ("FOB", "CIF")
SR_ACTIVE_STATES = ("OPEN", "IN_PROGRESS")


def _get_sr(srId):
    return get_or_404(
        store.sourcing_requests, srId, "ERR_SOURCING_REQUEST_NOT_FOUND", "SourcingRequest"
    )


@bp.route("/sourcing/sourcing-requests", methods=["POST"])
def create_sourcing_request():
    uid, _ = require_roles("BuyerManager")
    data = body_json()
    assigned_agent_id = req_str(data, "assigned_agent_id")
    title = req_str(data, "title")
    product_category = req_enum(data, "product_category", PRODUCT_CATEGORIES)
    target_price_cents = req_int(data, "target_price_cents")
    quantity = req_int(data, "quantity", lo=1)
    commission_mode = req_enum(data, "commission_mode", COMMISSION_MODES)
    sr = stamp_new(
        {
            "id": new_id(),
            "buyer_id": uid,
            "assigned_agent_id": assigned_agent_id,
            "title": title,
            "product_category": product_category,
            "target_price_cents": target_price_cents,
            "quantity": quantity,
            "commission_mode": commission_mode,
            "status": "OPEN",
        }
    )
    store.sourcing_requests[sr["id"]] = sr
    return success_object(public(sr), 201)


@bp.route("/sourcing/sourcing-requests", methods=["GET"])
def list_sourcing_requests():
    require_roles(*ALL_ROLES)
    items = list(store.sourcing_requests.values())
    buyer_id = request.args.get("buyer_id")
    agent_id = request.args.get("assigned_agent_id")
    status = request.args.get("status")
    if buyer_id is not None:
        items = [s for s in items if s["buyer_id"] == buyer_id]
    if agent_id is not None:
        items = [s for s in items if s["assigned_agent_id"] == agent_id]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    items = sorted_created(items)
    page, limit, offset, total = paginate(items)
    return success_list([public(s) for s in page], limit, offset, total)


@bp.route("/sourcing/sourcing-requests/<srId>", methods=["GET"])
def get_sourcing_request(srId):
    require_roles(*ALL_ROLES)
    return success_object(public(_get_sr(srId)))


@bp.route("/sourcing/sourcing-requests/<srId>/cancel", methods=["POST"])
def cancel_sourcing_request(srId):
    uid, _ = require_roles("BuyerManager")
    sr = _get_sr(srId)
    if sr["buyer_id"] != uid:
        raise ApiError(
            "ERR_OWNERSHIP_SCOPE_VIOLATION",
            "Caller does not own this sourcing request",
            403,
        )
    if sr["status"] not in SR_ACTIVE_STATES:
        raise ApiError(
            "ERR_SR_NOT_CANCELLABLE",
            "SourcingRequest is not OPEN or IN_PROGRESS",
            409,
        )
    sr["status"] = "CANCELLED"
    touch(sr)
    for sample in store.samples.values():
        if sample["sourcing_request_id"] == sr["id"] and sample["status"] in (
            "SUBMITTED",
            "REVISION_REQUESTED",
        ):
            sample["status"] = "REJECTED"
            touch(sample)
    for quotation in store.quotations.values():
        if quotation["sourcing_request_id"] == sr["id"] and quotation["status"] in (
            "OPEN",
            "COUNTERED",
        ):
            quotation["status"] = "REJECTED"
            touch(quotation)
    return success_object(public(sr))


# ---------------------------------------------------------------------------
# Samples
# ---------------------------------------------------------------------------

@bp.route("/sourcing/sourcing-requests/<srId>/samples", methods=["POST"])
def create_sample(srId):
    uid, _ = require_roles("SourcingAgent")
    sr = _get_sr(srId)
    data = body_json()
    notes = req_str(data, "notes")
    if sr["assigned_agent_id"] != uid:
        raise ApiError(
            "ERR_OWNERSHIP_SCOPE_VIOLATION",
            "Caller is not the assigned agent for this sourcing request",
            403,
        )
    if sr["status"] not in SR_ACTIVE_STATES:
        raise ApiError(
            "ERR_SR_NOT_ACTIVE", "SourcingRequest is not OPEN or IN_PROGRESS", 409
        )
    sample = stamp_new(
        {
            "id": new_id(),
            "sourcing_request_id": sr["id"],
            "revision_count": 0,
            "notes": notes,
            "status": "SUBMITTED",
        }
    )
    store.samples[sample["id"]] = sample
    if sr["status"] == "OPEN":
        sr["status"] = "IN_PROGRESS"
        touch(sr)
    return success_object(public(sample), 201)


@bp.route("/sourcing/samples", methods=["GET"])
def list_samples():
    require_roles(*ALL_ROLES)
    items = list(store.samples.values())
    sr_id = request.args.get("sourcing_request_id")
    status = request.args.get("status")
    if sr_id is not None:
        items = [s for s in items if s["sourcing_request_id"] == sr_id]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    items = sorted_created(items)
    page, limit, offset, total = paginate(items)
    return success_list([public(s) for s in page], limit, offset, total)


@bp.route("/sourcing/samples/<sampleId>", methods=["GET"])
def get_sample(sampleId):
    require_roles(*ALL_ROLES)
    sample = get_or_404(store.samples, sampleId, "ERR_SAMPLE_NOT_FOUND", "Sample")
    return success_object(public(sample))


@bp.route("/sourcing/samples/<sampleId>/review", methods=["POST"])
def review_sample(sampleId):
    uid, _ = require_roles("BuyerManager")
    sample = get_or_404(store.samples, sampleId, "ERR_SAMPLE_NOT_FOUND", "Sample")
    data = body_json()
    decision = req_enum(data, "decision", ("APPROVE", "REQUEST_REVISION"))
    opt_str(data, "comments")
    sr = store.sourcing_requests.get(sample["sourcing_request_id"])
    if sr is None or sr["buyer_id"] != uid:
        raise ApiError(
            "ERR_OWNERSHIP_SCOPE_VIOLATION",
            "Caller does not own the parent sourcing request",
            403,
        )
    if sample["status"] != "SUBMITTED":
        raise ApiError(
            "ERR_SAMPLE_NOT_REVIEWABLE", "Sample is not SUBMITTED", 409
        )
    if sr["status"] not in SR_ACTIVE_STATES:
        raise ApiError(
            "ERR_SR_NOT_ACTIVE", "SourcingRequest is not OPEN or IN_PROGRESS", 409
        )
    if decision == "APPROVE":
        sample["status"] = "APPROVED"
    else:
        if sample["revision_count"] < REVISION_CAP:
            sample["status"] = "REVISION_REQUESTED"
        else:
            sample["status"] = "REJECTED"
    touch(sample)
    return success_object(public(sample))


@bp.route("/sourcing/samples/<sampleId>/resubmit", methods=["POST"])
def resubmit_sample(sampleId):
    uid, _ = require_roles("SourcingAgent")
    sample = get_or_404(store.samples, sampleId, "ERR_SAMPLE_NOT_FOUND", "Sample")
    data = body_json()
    notes = req_str(data, "notes")
    sr = store.sourcing_requests.get(sample["sourcing_request_id"])
    if sr is None or sr["assigned_agent_id"] != uid:
        raise ApiError(
            "ERR_OWNERSHIP_SCOPE_VIOLATION",
            "Caller is not the assigned agent for this sourcing request",
            403,
        )
    if sample["status"] != "REVISION_REQUESTED":
        raise ApiError(
            "ERR_SAMPLE_NOT_RESUBMITTABLE", "Sample is not REVISION_REQUESTED", 409
        )
    sample["status"] = "SUBMITTED"
    sample["notes"] = notes
    sample["revision_count"] += 1
    touch(sample)
    return success_object(public(sample))
