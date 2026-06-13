from flask import Blueprint, request

from db import store
from errors import err
from middleware import require
from response import success, paginated
from services.common import (
    base_record, touch, require_body, require_int, require_enum,
    parse_pagination, page, now,
)
from services import serialize, calc

bp = Blueprint("items", __name__)


@bp.post("/items")
@require("IntakeGrader", "StoreAdmin")
def create_item():
    body = require_body()
    if "batch_id" not in body or not isinstance(body["batch_id"], str):
        raise err("ERR_INVALID_REQUEST", "batch_id required")
    if "title" not in body or not isinstance(body["title"], str) or body["title"].strip() == "":
        raise err("ERR_INVALID_REQUEST", "title required and non-empty")
    requires_auth = body.get("requires_authentication", False)
    if requires_auth is None:
        requires_auth = False
    if not isinstance(requires_auth, bool):
        raise err("ERR_INVALID_REQUEST", "requires_authentication must be boolean")

    batch = store.intake_batches.get(body["batch_id"])
    if batch is None:
        raise err("ERR_REFERENCE_NOT_FOUND", "Batch not found")
    if batch["status"] != "OPEN":
        raise err("ERR_BATCH_CLOSED", "Batch is CLOSED")

    agreement = store.agreements[batch["agreement_id"]]
    rec = base_record()
    rec.update({
        "batch_id": batch["id"],
        "agreement_id": agreement["id"],
        "consignor_id": agreement["consignor_id"],
        "title": body["title"],
        "requires_authentication": requires_auth,
        "list_price_cents": None,
        "graded_by_user_id": None,
        "grading_status": "PENDING_GRADE",
        "listing_status": "NOT_LISTED",
        "authentication_status": "PENDING_AUTH" if requires_auth else "NOT_REQUIRED",
        "floor_date": None,
        "floor_date_dt": None,
        "current_price_cents": None,
        "sold_price_cents": None,
    })
    store.items[rec["id"]] = rec
    return success(serialize.item_out(rec), 201)


@bp.get("/items/<iid>")
@require("IntakeGrader", "StoreAdmin", "SettlementManager", "CashierClerk", "Authenticator")
def get_item(iid):
    it = store.items.get(iid)
    if it is None:
        raise err("ERR_NOT_FOUND", "Item not found")
    return success(serialize.item_out(it), 200)


@bp.get("/items")
@require("IntakeGrader", "StoreAdmin", "SettlementManager", "CashierClerk")
def list_items():
    limit, offset = parse_pagination()
    recs = list(store.items.values())
    for key in ("consignor_id", "agreement_id", "listing_status", "grading_status"):
        val = request.args.get(key)
        if val is not None:
            recs = [it for it in recs if it[key] == val]
    window, total = page(recs, limit, offset)
    return paginated([serialize.item_out(it) for it in window], limit, offset, total)


@bp.post("/items/<iid>/grade")
@require("IntakeGrader")
def grade_item(iid):
    it = store.items.get(iid)
    if it is None:
        raise err("ERR_NOT_FOUND", "Item not found")
    body = require_body()

    decision = require_enum(body, "decision", {"ACCEPT", "REJECT"})
    if "expected_item_version" not in body:
        raise err("ERR_INVALID_REQUEST", "expected_item_version required")
    expected = body["expected_item_version"]
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise err("ERR_INVALID_REQUEST", "expected_item_version must be an integer")

    # State precedes OCC (PRD §2.5): grading only from PENDING_GRADE, batch OPEN.
    if it["grading_status"] != "PENDING_GRADE":
        raise err("ERR_INVALID_STATE", "Item is not PENDING_GRADE")
    batch = store.intake_batches[it["batch_id"]]
    if batch["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", "Batch is not OPEN")

    # OCC check
    if expected != it["version"]:
        raise err("ERR_STALE_ITEM_VERSION", "expected_item_version does not match")

    if decision == "ACCEPT":
        if "list_price_cents" not in body or body["list_price_cents"] is None:
            raise err("ERR_LIST_PRICE_REQUIRED", "list_price_cents required to ACCEPT")
        lp = body["list_price_cents"]
        if isinstance(lp, bool) or not isinstance(lp, int):
            raise err("ERR_INVALID_REQUEST", "list_price_cents must be an integer")
        if lp < 0:
            raise err("ERR_INVALID_REQUEST", "list_price_cents must be >= 0")
        it["grading_status"] = "ACCEPTED"
        it["list_price_cents"] = lp
        it["graded_by_user_id"] = request.user_id
        if it["requires_authentication"]:
            it["authentication_status"] = "PENDING_AUTH"
    else:  # REJECT
        it["grading_status"] = "REJECTED"
        it["graded_by_user_id"] = request.user_id

    touch(it)
    return success(serialize.item_out(it), 200)


@bp.post("/items/<iid>/list")
@require("IntakeGrader")
def list_item(iid):
    it = store.items.get(iid)
    if it is None:
        raise err("ERR_NOT_FOUND", "Item not found")

    # State: grading ACCEPTED and listing in {NOT_LISTED, PULLED}.
    if it["grading_status"] != "ACCEPTED" or it["listing_status"] not in ("NOT_LISTED", "PULLED"):
        raise err("ERR_INVALID_STATE", "Item cannot be listed from its current state")

    # Business rule: authentication gating (priority 8).
    if it["authentication_status"] not in ("NOT_REQUIRED", "AUTHENTIC"):
        raise err("ERR_AUTHENTICATION_REQUIRED", "Item authentication not cleared")

    ts = now()
    it["listing_status"] = "ON_FLOOR"
    it["floor_date_dt"] = ts
    it["floor_date"] = serialize.iso_dt(ts)
    it["current_price_cents"] = serialize.item_current_price(it)
    touch(it)
    return success(serialize.item_out(it), 200)


@bp.post("/items/<iid>/pull")
@require("IntakeGrader", "StoreAdmin")
def pull_item(iid):
    it = store.items.get(iid)
    if it is None:
        raise err("ERR_NOT_FOUND", "Item not found")

    if it["listing_status"] != "ON_FLOOR":
        raise err("ERR_INVALID_STATE", "Item is not ON_FLOOR")

    # Pull requires NOT past the return window (priority 12).
    agreement = store.agreements[it["agreement_id"]]
    age = calc.age_days(it["floor_date_dt"], now())
    if age >= agreement["return_window_days"]:
        raise err("ERR_RETURN_WINDOW_ELAPSED", "Item past return window; dispose instead")

    it["listing_status"] = "PULLED"
    touch(it)
    return success(serialize.item_out(it), 200)


@bp.post("/items/<iid>/dispose")
@require("SettlementManager", "StoreAdmin")
def dispose_item(iid):
    it = store.items.get(iid)
    if it is None:
        raise err("ERR_NOT_FOUND", "Item not found")

    if it["listing_status"] != "ON_FLOOR":
        raise err("ERR_INVALID_STATE", "Item is not ON_FLOOR")

    agreement = store.agreements[it["agreement_id"]]
    age = calc.age_days(it["floor_date_dt"], now())
    if age < agreement["return_window_days"]:
        raise err("ERR_RETURN_WINDOW_NOT_ELAPSED", "Item not past return window")

    unsold = agreement["unsold_disposition"]
    if unsold == "RETURN_TO_CONSIGNOR":
        it["listing_status"] = "RETURNED"
        disposition = "RETURNED"
    elif unsold == "DONATE":
        it["listing_status"] = "DONATED"
        disposition = "DONATED"
    else:  # STORE_KEEPS
        it["listing_status"] = "DONATED"
        disposition = "STORE_KEPT"

    tax_value = calc.donation_valuation(it["list_price_cents"], disposition)
    rec = base_record()
    rec.update({
        "item_id": it["id"],
        "consignor_id": it["consignor_id"],
        "disposition": disposition,
        "tax_receipt_value_cents": tax_value,
    })
    store.donation_records[rec["id"]] = rec
    touch(it)
    return success(serialize.donation_out(rec), 201)


@bp.get("/items/<iid>/authentication-reviews")
@require("Authenticator", "IntakeGrader", "StoreAdmin", "SettlementManager")
def item_reviews(iid):
    if iid not in store.items:
        raise err("ERR_NOT_FOUND", "Item not found")
    limit, offset = parse_pagination()
    recs = [r for r in store.authentication_reviews.values() if r["item_id"] == iid]
    window, total = page(recs, limit, offset)
    return paginated([serialize.review_out(r) for r in window], limit, offset, total)


@bp.get("/items/<iid>/donation-record")
@require("SettlementManager", "StoreAdmin")
def item_donation(iid):
    if iid not in store.items:
        raise err("ERR_NOT_FOUND", "Item not found")
    limit, offset = parse_pagination()
    recs = [d for d in store.donation_records.values() if d["item_id"] == iid]
    window, total = page(recs, limit, offset)
    return paginated([serialize.donation_out(d) for d in window], limit, offset, total)


@bp.get("/items/<iid>/sale-lines")
@require("CashierClerk", "SettlementManager", "StoreAdmin")
def item_sale_lines(iid):
    if iid not in store.items:
        raise err("ERR_NOT_FOUND", "Item not found")
    limit, offset = parse_pagination()
    recs = [l for l in store.sale_lines.values() if l["item_id"] == iid]
    window, total = page(recs, limit, offset)
    return paginated([serialize.sale_line_out(l) for l in window], limit, offset, total)
