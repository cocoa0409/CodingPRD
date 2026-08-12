"""RecycleBatch endpoints: creation with selector policy, fill, ship,
delivery acknowledgment, and the processing cascade (PRD §3.7)."""

from flask import Blueprint

import db
import serialize
import utils
from errors import (ApiError, ERR_BATCH_EMPTY, ERR_BATCH_NOT_FOUND,
                    ERR_BATCH_NOT_STAGING, ERR_DATA_SANITIZATION_UNVERIFIED,
                    ERR_EXPORT_NOT_ALLOWED, ERR_INVALID_STATE,
                    ERR_ITEM_NOT_FOUND, ERR_ITEM_NOT_RECYCLE_ROUTED,
                    ERR_NO_ELIGIBLE_RECYCLER, ERR_RECYCLER_CATEGORY_UNSUPPORTED,
                    ERR_RECYCLER_CERT_EXPIRED, ERR_RECYCLER_DAILY_CAPACITY_EXCEEDED,
                    ERR_RECYCLER_NOT_FOUND)
from middleware import require_roles
from response import ok_object, paginate, sort_created
from services import calculations as calc
from services import workflow

bp = Blueprint("batches", __name__)


def get_batch_or_404(batch_id):
    batch = db.batches.get(batch_id)
    if batch is None:
        raise ApiError(ERR_BATCH_NOT_FOUND, 404, "no RecycleBatch with the given id")
    return batch


def _cert_valid(recycler, delivery_date):
    """Expiry-exclusive: certification must be strictly after the delivery date."""
    return recycler["certification_expires_at"] > delivery_date


@bp.post("/itad/recycle-batches")
def create_batch():
    uid, role = require_roles("LogisticsCoordinator")
    data = utils.body_json()
    recycler_id = utils.opt_str(data, "recycler_id")
    delivery_date = utils.req_datetime(data, "scheduled_delivery_date")
    is_export = utils.req_bool(data, "is_export")

    recycler = None
    if recycler_id is not None:
        recycler = db.recyclers.get(recycler_id)
        if recycler is None:
            raise ApiError(ERR_RECYCLER_NOT_FOUND, 404, "no Recycler with the given id")

    policy = calc.active_policy()
    if is_export and policy is not None and not policy["export_allowed"]:
        raise ApiError(ERR_EXPORT_NOT_ALLOWED, 422,
                       "the active compliance policy forbids export shipments")

    if recycler is None:
        recycler = calc.select_recycler(delivery_date)
        if recycler is None:
            raise ApiError(ERR_NO_ELIGIBLE_RECYCLER, 422,
                           "no recycler with certification valid on the delivery date")

    if not _cert_valid(recycler, delivery_date):
        raise ApiError(ERR_RECYCLER_CERT_EXPIRED, 422,
                       "recycler certification is not strictly valid at the delivery date")

    batch = {
        "id": utils.new_id(),
        "recycler_id": recycler["id"],
        "scheduled_delivery_date": delivery_date,
        "is_export": is_export,
        "status": "STAGING",
        "gross_weight_kg": calc.Decimal("0"),
        "item_count": 0,
        "item_ids": [],
    }
    utils.stamp_new(batch)
    db.batches[batch["id"]] = batch
    return ok_object(serialize.batch(batch), code=201)


@bp.get("/itad/recycle-batches/<batch_id>")
def read_batch(batch_id):
    uid, role = require_roles("PlatformAdmin", "LogisticsCoordinator", "ComplianceOfficer")
    batch = get_batch_or_404(batch_id)
    return ok_object(serialize.batch(batch))


@bp.get("/itad/recycle-batches/<batch_id>/items")
def list_batch_items(batch_id):
    uid, role = require_roles("PlatformAdmin", "LogisticsCoordinator", "ComplianceOfficer")
    batch = get_batch_or_404(batch_id)
    contained = [db.items[iid] for iid in batch["item_ids"] if iid in db.items]
    contained = sort_created(contained)
    return paginate([serialize.item(i) for i in contained])


@bp.post("/itad/recycle-batches/<batch_id>/items")
def add_batch_item(batch_id):
    uid, role = require_roles("LogisticsCoordinator")
    batch = get_batch_or_404(batch_id)
    data = utils.body_json()
    item_id = utils.req_str(data, "item_id")
    item = db.items.get(item_id)
    if item is None:
        raise ApiError(ERR_ITEM_NOT_FOUND, 404, "no Item with the given id")
    if batch["status"] != "STAGING":
        raise ApiError(ERR_BATCH_NOT_STAGING, 409, "batch is not STAGING")
    if item["data_bearing"] and item["data_status"] != "VERIFIED":
        raise ApiError(ERR_DATA_SANITIZATION_UNVERIFIED, 422,
                       "batching a data-bearing item requires data_status VERIFIED")
    recycler = db.recyclers[batch["recycler_id"]]
    if item["category"] not in recycler["accepted_categories"]:
        raise ApiError(ERR_RECYCLER_CATEGORY_UNSUPPORTED, 422,
                       "recycler does not accept the item category")
    if item["disposition"] != "RECYCLE" or item["processing_status"] != "FOR_RECYCLE":
        raise ApiError(ERR_ITEM_NOT_RECYCLE_ROUTED, 422,
                       "item must be RECYCLE-routed and FOR_RECYCLE")
    item["processing_status"] = "BATCHED"
    item["recycle_batch_id"] = batch["id"]
    utils.touch(item)
    batch["item_ids"].append(item["id"])
    workflow.recompute_batch_totals(batch)
    utils.touch(batch)
    workflow.write_custody("ITEM", item["id"], "TRANSFERRED", uid,
                           to_location="batch:" + batch["id"])
    return ok_object(serialize.batch(batch))


@bp.delete("/itad/recycle-batches/<batch_id>/items/<item_id>")
def remove_batch_item(batch_id, item_id):
    uid, role = require_roles("LogisticsCoordinator")
    batch = get_batch_or_404(batch_id)
    item = db.items.get(item_id)
    if item is None or item.get("recycle_batch_id") != batch["id"]:
        raise ApiError(ERR_ITEM_NOT_FOUND, 404, "no Item with the given id in this batch")
    if batch["status"] != "STAGING":
        raise ApiError(ERR_BATCH_NOT_STAGING, 409, "batch is not STAGING")
    item["processing_status"] = "FOR_RECYCLE"
    item["recycle_batch_id"] = None
    utils.touch(item)
    if item["id"] in batch["item_ids"]:
        batch["item_ids"].remove(item["id"])
    workflow.recompute_batch_totals(batch)
    utils.touch(batch)
    return "", 204


@bp.post("/itad/recycle-batches/<batch_id>/ship")
def ship_batch(batch_id):
    uid, role = require_roles("LogisticsCoordinator")
    batch = get_batch_or_404(batch_id)
    if batch["status"] != "STAGING":
        raise ApiError(ERR_INVALID_STATE, 409, "only STAGING batches can be shipped")
    recycler = db.recyclers[batch["recycler_id"]]
    if not _cert_valid(recycler, batch["scheduled_delivery_date"]):
        raise ApiError(ERR_RECYCLER_CERT_EXPIRED, 422,
                       "recycler certification is not strictly valid at the delivery date")
    # Daily intake: same recycler, same calendar delivery day, batches already
    # accepted downstream; exact fit allowed, strictly-greater overflow rejected.
    day = batch["scheduled_delivery_date"].date()
    committed = calc.Decimal("0")
    for other in db.batches.values():
        if other["id"] == batch["id"]:
            continue
        if other["recycler_id"] != recycler["id"]:
            continue
        if other["status"] not in ("IN_TRANSIT", "DELIVERED", "PROCESSED"):
            continue
        if other["scheduled_delivery_date"].date() != day:
            continue
        committed += other["gross_weight_kg"]
    if committed + batch["gross_weight_kg"] > recycler["daily_intake_capacity_kg"]:
        raise ApiError(ERR_RECYCLER_DAILY_CAPACITY_EXCEEDED, 422,
                       "shipping would exceed the recycler's daily intake capacity")
    if batch["item_count"] < 1:
        raise ApiError(ERR_BATCH_EMPTY, 422, "cannot ship an empty batch")
    batch["status"] = "IN_TRANSIT"
    utils.touch(batch)
    for iid in batch["item_ids"]:
        item = db.items.get(iid)
        if item is not None and item["processing_status"] == "BATCHED":
            item["processing_status"] = "DOWNSTREAM"
            utils.touch(item)
    workflow.write_custody("BATCH", batch["id"], "SHIPPED_DOWNSTREAM", uid)
    return ok_object(serialize.batch(batch))


@bp.post("/itad/recycle-batches/<batch_id>/deliver")
def deliver_batch(batch_id):
    uid, role = require_roles("ComplianceOfficer")
    batch = get_batch_or_404(batch_id)
    if batch["status"] != "IN_TRANSIT":
        raise ApiError(ERR_INVALID_STATE, 409, "only IN_TRANSIT batches can be delivered")
    batch["status"] = "DELIVERED"
    utils.touch(batch)
    workflow.write_custody("BATCH", batch["id"], "DELIVERED_DOWNSTREAM", uid)
    return ok_object(serialize.batch(batch))


@bp.post("/itad/recycle-batches/<batch_id>/process")
def process_batch(batch_id):
    uid, role = require_roles("ComplianceOfficer")
    batch = get_batch_or_404(batch_id)
    if batch["status"] != "DELIVERED":
        raise ApiError(ERR_INVALID_STATE, 409, "only DELIVERED batches can be processed")

    # Completion cascade (PRD §3.7): items complete, diversion accumulates and
    # may upgrade tiers, recycler volume grows, COR auto-issues, custody writes.
    touched_accounts = {}
    for iid in batch["item_ids"]:
        item = db.items.get(iid)
        if item is None or item["processing_status"] != "DOWNSTREAM":
            continue
        manifest = db.manifests[item["manifest_id"]]
        account = db.accounts[manifest["account_id"]]
        workflow.complete_item(item, account, actor_id=uid, write_item_custody=True)
        utils.touch(item)
        touched_accounts[account["id"]] = account

    recycler = db.recyclers[batch["recycler_id"]]
    recycler["total_processed_kg"] += batch["gross_weight_kg"]
    utils.touch(recycler)

    certificate = {
        "id": utils.new_id(),
        "cert_type": "RECYCLING",
        "item_id": None,
        "batch_id": batch["id"],
        "certificate_number": utils.new_cert_number(),
        "issued_by_id": "system",
        "status": "ISSUED",
    }
    utils.stamp_new(certificate)
    db.certificates[certificate["id"]] = certificate

    workflow.write_custody("BATCH", batch["id"], "PROCESSED", uid)
    batch["status"] = "PROCESSED"
    utils.touch(batch)
    for account in touched_accounts.values():
        utils.touch(account)
    return ok_object(serialize.batch(batch))


@bp.get("/itad/recycle-batches/<batch_id>/certificates")
def list_batch_certificates(batch_id):
    uid, role = require_roles("PlatformAdmin", "ComplianceOfficer", "LogisticsCoordinator")
    batch = get_batch_or_404(batch_id)
    records = sort_created([c for c in db.certificates.values()
                            if c.get("batch_id") == batch["id"]])
    return paginate([serialize.certificate(c) for c in records])
