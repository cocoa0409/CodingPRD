"""DonationBatch endpoints (PRD §3.1, §3.2, §3.9)."""
from flask import Blueprint

from db import db, new_record, touch, iso_now
from errors import (
    ApiError, not_found, invalid_request,
    ERR_BATCH_INVALID_STATE, ERR_BATCH_HAS_UNTRIAGED_ITEMS,
    ERR_BATCH_RECEIPT_MISSING, ERR_REVALUE_BLOCKED_BY_RECEIPT,
    ERR_STALE_BATCH_VERSION, ERR_DONOR_INACTIVE, ERR_NOT_FOUND,
)
from middleware import require_roles, get_body, ALL_ROLES, paginate, query_filters, apply_filters
from response import success_object, success_list
from services import calc
from services.helpers import recompute_batch_rollups, issued_receipt_for_batch

bp = Blueprint("batches", __name__)


def batch_view(b):
    return dict(b)


def item_view(i):
    return dict(i)


def receipt_view(r):
    return dict(r)


def _get_batch(batch_id):
    b = db.batches.get(batch_id)
    if b is None:
        raise not_found("donation batch")
    return b


@bp.route("/api/donation-batches", methods=["POST"])
def create_batch():
    require_roles(["IntakeAttendant"])
    payload = get_body(
        required=[("donor_id", "string"), ("source", "string")],
        optional=[("receipt_requested", "boolean")],
        enums={"source": ["WALK_IN", "DONATION_DRIVE", "PICKUP_STOP"]},
    )
    # PICKUP_STOP source is system-only (set by pickup-stop completion)
    if payload["source"] == "PICKUP_STOP":
        raise invalid_request("source PICKUP_STOP is system-set only")
    donor = db.donors.get(payload["donor_id"])
    if donor is None:
        raise not_found("donor")
    if donor["status"] != "ACTIVE":
        raise ApiError(ERR_DONOR_INACTIVE, 422, "Referenced donor is INACTIVE")
    rec = new_record()
    rec.update({
        "donor_id": payload["donor_id"],
        "source": payload["source"],
        "pickup_stop_id": None,
        "receipt_requested": payload.get("receipt_requested", False),
        "status": "OPEN",
        "item_count": 0,
        "untriaged_count": 0,
        "provisional_value_cents": 0,
        "sold_item_count": 0,
        "closed_at": None,
    })
    db.batches[rec["id"]] = rec
    return success_object(batch_view(rec), status=201)


@bp.route("/api/donation-batches/<batch_id>", methods=["GET"])
def get_batch(batch_id):
    require_roles(ALL_ROLES)
    return success_object(batch_view(_get_batch(batch_id)))


@bp.route("/api/donation-batches", methods=["GET"])
def list_batches():
    require_roles(ALL_ROLES)
    filters = query_filters(["donor_id", "pickup_stop_id", "status"])
    records = apply_filters(list(db.batches.values()), filters)
    page, limit, offset, total = paginate(records)
    return success_list([batch_view(b) for b in page], limit, offset, total)


@bp.route("/api/donation-batches/<batch_id>/items", methods=["POST"])
def add_item(batch_id):
    require_roles(["IntakeAttendant"])
    payload = get_body(
        required=[("category", "string"), ("condition", "string")],
        optional=[("description", "string"), ("weight_lbs", "number")],
        enums={
            "category": ["CLOTHING", "FURNITURE", "ELECTRONICS", "HOUSEWARES",
                         "BOOKS_MEDIA", "TOYS", "COLLECTIBLES"],
            "condition": ["NEW_WITH_TAGS", "GOOD", "FAIR", "POOR"],
        },
    )
    batch = _get_batch(batch_id)
    if batch["status"] != "OPEN":
        raise ApiError(ERR_BATCH_INVALID_STATE, 409,
                       "Items can only be added to an OPEN batch")
    rec = new_record()
    rec.update({
        "batch_id": batch["id"],
        "category": payload["category"],
        "condition": payload["condition"],
        "description": payload.get("description"),
        "weight_lbs": payload.get("weight_lbs"),
        "salvage_category": None,
        "appraisal_confirmed": False,
        "provisional_value_cents": calc.calc_provisional_item_value(
            payload["category"], payload["condition"]),
        "base_price_cents": None,
        "current_price_cents": None,
        "markdown_round": 0,
        "status": "RECEIVED",
        "floor_cycle_id": None,
        "tag_color": None,
        "hold_expires_at": None,
        "value_at_shrink_cents": None,
        "shrunk_cycle_id": None,
        "shrink_reason": None,
        "sale_id": None,
        "bale_id": None,
        "priced_at": None,
        "sold_at": None,
    })
    db.items[rec["id"]] = rec
    recompute_batch_rollups(batch)
    touch(batch)
    return success_object(item_view(rec), status=201)


@bp.route("/api/donation-batches/<batch_id>/items", methods=["GET"])
def list_batch_items(batch_id):
    require_roles(ALL_ROLES)
    _get_batch(batch_id)
    records = [i for i in db.items.values() if i["batch_id"] == batch_id]
    page, limit, offset, total = paginate(records)
    return success_list([item_view(i) for i in page], limit, offset, total)


@bp.route("/api/donation-batches/<batch_id>/begin-sort", methods=["POST"])
def begin_sort(batch_id):
    require_roles(["IntakeAttendant"])
    get_body()  # schema: no fields allowed
    batch = _get_batch(batch_id)
    if batch["status"] != "OPEN" or batch["item_count"] < 1:
        raise ApiError(ERR_BATCH_INVALID_STATE, 409,
                       "begin-sort requires an OPEN batch with at least one item")
    batch["status"] = "SORTING"
    touch(batch)
    return success_object(batch_view(batch))


@bp.route("/api/donation-batches/<batch_id>/complete-sort", methods=["POST"])
def complete_sort(batch_id):
    require_roles(["IntakeAttendant"])
    get_body()
    batch = _get_batch(batch_id)
    if batch["status"] != "SORTING":
        raise ApiError(ERR_BATCH_INVALID_STATE, 409,
                       "complete-sort requires a SORTING batch")
    recompute_batch_rollups(batch)
    if batch["untriaged_count"] != 0:
        raise ApiError(ERR_BATCH_HAS_UNTRIAGED_ITEMS, 409,
                       "complete-sort while untriaged_count > 0")
    batch["status"] = "SORTED"
    touch(batch)
    return success_object(batch_view(batch))


@bp.route("/api/donation-batches/<batch_id>/revalue", methods=["POST"])
def revalue_batch(batch_id):
    require_roles(["IntakeAttendant"])
    payload = get_body(
        required=[("expected_batch_version", "integer"), ("adjustments", "array")],
    )
    batch = _get_batch(batch_id)
    # priority 6: state preconditions
    if batch["status"] in ("CLOSED", "CANCELLED"):
        raise ApiError(ERR_BATCH_INVALID_STATE, 409,
                       "revalue forbidden on a CLOSED or CANCELLED batch")
    if issued_receipt_for_batch(batch["id"]) is not None:
        raise ApiError(ERR_REVALUE_BLOCKED_BY_RECEIPT, 409,
                       "revalue forbidden while an ISSUED receipt exists for the batch")
    # priority 7: OCC (after state preconditions)
    if payload["expected_batch_version"] != batch["version"]:
        raise ApiError(ERR_STALE_BATCH_VERSION, 412,
                       "expected_batch_version does not match the batch version")
    adjustments = payload["adjustments"]
    if len(adjustments) == 0:
        raise invalid_request("adjustments must be a non-empty array")
    # Validate adjustment shapes, then resolve FKs (priority 4 body references)
    parsed = []
    for adj in adjustments:
        if not isinstance(adj, dict):
            raise invalid_request("adjustments entries must be objects")
        for key in adj:
            if key not in ("item_id", "provisional_value_cents"):
                raise invalid_request("Unknown adjustment field: %s" % key)
        if "item_id" not in adj or not isinstance(adj["item_id"], str):
            raise invalid_request("adjustment item_id is required")
        if "provisional_value_cents" not in adj or not isinstance(
                adj["provisional_value_cents"], int) or isinstance(
                adj["provisional_value_cents"], bool):
            raise invalid_request("adjustment provisional_value_cents must be an integer")
        if adj["provisional_value_cents"] < 0:
            raise invalid_request("adjustment provisional_value_cents must be non-negative")
        item = db.items.get(adj["item_id"])
        if item is None or item["batch_id"] != batch["id"]:
            raise ApiError(ERR_NOT_FOUND, 404,
                           "adjustment item_id does not resolve to an item of this batch")
        parsed.append((item, adj["provisional_value_cents"]))
    for item, value in parsed:
        item["provisional_value_cents"] = value
        touch(item)
    recompute_batch_rollups(batch)
    touch(batch)
    return success_object(batch_view(batch))


@bp.route("/api/donation-batches/<batch_id>/close", methods=["POST"])
def close_batch(batch_id):
    require_roles(["IntakeAttendant"])
    get_body()
    batch = _get_batch(batch_id)
    if batch["status"] != "SORTED":
        raise ApiError(ERR_BATCH_INVALID_STATE, 409,
                       "close requires a SORTED batch")
    if batch["receipt_requested"] and issued_receipt_for_batch(batch["id"]) is None:
        raise ApiError(ERR_BATCH_RECEIPT_MISSING, 409,
                       "close of a receipt_requested batch requires an ISSUED receipt")
    batch["status"] = "CLOSED"
    batch["closed_at"] = iso_now()
    touch(batch)
    # donor rollup + tier recompute
    donor = db.donors.get(batch["donor_id"])
    if donor is not None:
        donor["lifetime_donation_count"] += 1
        donor["tier"] = ("FREQUENT" if donor["lifetime_donation_count"]
                         >= calc.DONOR_FREQUENT_THRESHOLD else "STANDARD")
        touch(donor)
    return success_object(batch_view(batch))


@bp.route("/api/donation-batches/<batch_id>/cancel", methods=["POST"])
def cancel_batch(batch_id):
    require_roles(["IntakeAttendant"])
    get_body()
    batch = _get_batch(batch_id)
    if batch["status"] != "OPEN" or batch["item_count"] != 0:
        raise ApiError(ERR_BATCH_INVALID_STATE, 409,
                       "cancel requires an OPEN batch with zero items")
    batch["status"] = "CANCELLED"
    touch(batch)
    return success_object(batch_view(batch))


@bp.route("/api/donation-batches/<batch_id>/receipt", methods=["POST"])
def issue_receipt(batch_id):
    require_roles(["IntakeAttendant"])
    get_body()
    batch = _get_batch(batch_id)
    # priority 6: state
    if batch["status"] != "SORTED":
        raise ApiError(ERR_BATCH_INVALID_STATE, 409,
                       "receipt issuance requires a SORTED batch")
    # priority 8 sub-order: (a) receipt_requested, (b) appraisal, (c) address
    if not batch["receipt_requested"]:
        raise ApiError("ERR_RECEIPT_NOT_REQUESTED", 422,
                       "Receipt issuance for a batch with receipt_requested == false")
    items = [i for i in db.items.values() if i["batch_id"] == batch["id"]]
    total = sum(i["provisional_value_cents"] for i in items)
    for i in items:
        if i["provisional_value_cents"] >= calc.APPRAISAL_THRESHOLD_CENTS \
                and not i["appraisal_confirmed"]:
            raise ApiError("ERR_APPRAISAL_REQUIRED", 422,
                           "An item with provisional_value_cents >= 500000 lacks appraisal_confirmed")
    donor = db.donors.get(batch["donor_id"])
    if total >= calc.ADDRESS_THRESHOLD_CENTS:
        if donor is None or not donor.get("address_line"):
            raise ApiError("ERR_DONOR_ADDRESS_REQUIRED", 422,
                           "total >= 50000 cents requires donor.address_line")
    # priority 9: at most one ISSUED receipt per batch
    if issued_receipt_for_batch(batch["id"]) is not None:
        raise ApiError("ERR_RECEIPT_INVALID_STATE", 409,
                       "An ISSUED receipt already exists for this batch")
    rec = new_record()
    rec.update({
        "batch_id": batch["id"],
        "donor_id": batch["donor_id"],
        "receipt_number": db.next_receipt_number(),
        "total_value_cents": total,
        "itemized_required": total >= calc.ITEMIZED_THRESHOLD_CENTS,
        "form_8283_required": total >= calc.ADDRESS_THRESHOLD_CENTS,
        "status": "ISSUED",
        "issued_at": iso_now(),
        "voided_at": None,
    })
    db.receipts[rec["id"]] = rec
    return success_object(receipt_view(rec), status=201)
