"""The category review calendar and the award decision (PRD sections 3.4, 3.6)."""

from flask import Blueprint

import clock
import db
import response
import validators as v
from errors import ApiError
from middleware import ALL_ROLES, authorize, check_retailer_scope
from services import calc, domain

bp = Blueprint("reviews", __name__)


def serialize(rec):
    return {
        "id": rec["id"],
        "retailer_id": rec["retailer_id"],
        "category_code": rec["category_code"],
        "review_window_start": rec["review_window_start"],
        "review_window_end": rec["review_window_end"],
        "submission_deadline": rec["submission_deadline"],
        "new_item_slots": rec["new_item_slots"],
        "slots_awarded": rec["slots_awarded"],
        "slots_remaining": rec["new_item_slots"] - rec["slots_awarded"],
        "status": rec["status"],
        "reopen_count": rec["reopen_count"],
        "decided_at": rec["decided_at"],
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
    }


@bp.post("/category-reviews")
def create_review():
    user_id, role = authorize("RetailerBuyer")
    data = v.body()

    retailer_id = v.req_id(data, "retailer_id")
    category_code = v.req_enum(data, "category_code", v.CATEGORY_CODES)
    window_start = v.req_date(data, "review_window_start")
    window_end = v.req_date(data, "review_window_end")
    deadline, deadline_text = v.req_instant_raw(data, "submission_deadline")
    new_item_slots = v.req_int(data, "new_item_slots", 0)

    retailer = db.get("retailers", retailer_id)
    check_retailer_scope(role, user_id, retailer["id"])

    blackout = retailer["review_blackout_days"]
    for other in db.ordered("reviews"):
        if other["retailer_id"] != retailer["id"] or other["category_code"] != category_code:
            continue
        other_start = clock.parse_date(other["review_window_start"])
        other_end = clock.parse_date(other["review_window_end"])
        if window_start < clock.add_days(other_end, blackout) and \
                clock.add_days(other_start, -blackout) < window_end:
            raise ApiError("ERR_REVIEW_BLACKOUT_CONFLICT")

    if window_end <= window_start or deadline >= clock.midnight(window_start):
        raise ApiError("ERR_REVIEW_CALENDAR_INVALID")

    rec = db.base_record()
    rec.update({
        "retailer_id": retailer["id"],
        "category_code": category_code,
        "review_window_start": clock.date_str(window_start),
        "review_window_end": clock.date_str(window_end),
        "submission_deadline": deadline_text,
        "new_item_slots": new_item_slots,
        "slots_awarded": 0,
        "status": "SCHEDULED",
        "reopen_count": 0,
        "decided_at": None,
    })
    db.insert("reviews", rec)
    return response.created(serialize(rec))


@bp.get("/category-reviews/<review_id>")
def read_review(review_id):
    authorize(*ALL_ROLES)
    return response.ok(serialize(db.get("reviews", review_id)))


@bp.get("/category-reviews")
def list_reviews():
    authorize(*ALL_ROLES)
    limit, offset = v.pagination()
    retailer_id = v.filter_value("retailer_id")
    category_code = v.filter_value("category_code")
    status = v.filter_value("status")
    rows = []
    for rec in db.ordered("reviews"):
        if retailer_id is not None and rec["retailer_id"] != retailer_id:
            continue
        if category_code is not None and rec["category_code"] != category_code:
            continue
        if status is not None and rec["status"] != status:
            continue
        rows.append(rec)
    return response.listing([serialize(r) for r in rows], limit, offset)


@bp.post("/category-reviews/<review_id>/open")
def open_review(review_id):
    user_id, role = authorize("RetailerBuyer")
    rec = db.get("reviews", review_id)
    check_retailer_scope(role, user_id, rec["retailer_id"])

    if rec["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE")
    if clock.now() >= clock.parse_instant(rec["submission_deadline"]):
        raise ApiError("ERR_REVIEW_SUBMISSION_CLOSED")

    rec["status"] = "OPEN"
    db.touch(rec)
    return response.ok(serialize(rec))


@bp.post("/category-reviews/<review_id>/lock")
def lock_review(review_id):
    user_id, role = authorize("RetailerBuyer")
    rec = db.get("reviews", review_id)
    check_retailer_scope(role, user_id, rec["retailer_id"])

    if rec["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE")
    if clock.now() < clock.parse_instant(rec["submission_deadline"]):
        raise ApiError("ERR_SUBMISSION_WINDOW_STILL_OPEN")

    rec["status"] = "PRESENTATION_LOCKED"
    db.touch(rec)
    return response.ok(serialize(rec))


@bp.post("/category-reviews/<review_id>/reopen")
def reopen_review(review_id):
    user_id, role = authorize("RetailerBuyer")
    data = v.body()
    new_deadline, new_deadline_text = v.req_instant_raw(data, "new_submission_deadline")

    rec = db.get("reviews", review_id)
    check_retailer_scope(role, user_id, rec["retailer_id"])

    if rec["status"] != "PRESENTATION_LOCKED":
        raise ApiError("ERR_INVALID_STATE")

    window_start_instant = clock.midnight(clock.parse_date(rec["review_window_start"]))
    if clock.now() >= window_start_instant:
        raise ApiError("ERR_REVIEW_WINDOW_STARTED")

    if not (clock.now() < new_deadline < window_start_instant):
        raise ApiError("ERR_REVIEW_CALENDAR_INVALID")

    if rec["reopen_count"] >= calc.MAX_REVIEW_REOPENS:
        raise ApiError("ERR_REVIEW_REOPEN_LIMIT")

    rec["status"] = "OPEN"
    rec["submission_deadline"] = new_deadline_text
    rec["reopen_count"] = rec["reopen_count"] + 1
    db.touch(rec)
    return response.ok(serialize(rec))


@bp.post("/category-reviews/<review_id>/decide")
def decide_review(review_id):
    user_id, role = authorize("RetailerBuyer")
    data = v.body()

    expected_version = v.req_int(data, "expected_review_version", 0)
    awarded_ids = v.opt_id_array(data, "authorized_item_ids", 0, 1000)
    default_store_count = v.opt_int(data, "default_store_count", None, 0)

    review = db.get("reviews", review_id)
    items = [db.get("items", item_id) for item_id in awarded_ids]

    check_retailer_scope(role, user_id, review["retailer_id"])

    if expected_version != review["version"]:
        raise ApiError("ERR_STALE_REVIEW_VERSION")

    if review["status"] != "PRESENTATION_LOCKED":
        raise ApiError("ERR_INVALID_STATE")

    today = clock.today()
    if not (clock.parse_date(review["review_window_start"]) <= today
            < clock.parse_date(review["review_window_end"])):
        raise ApiError("ERR_REVIEW_WINDOW_CLOSED")

    submitted = [p for p in domain.presentations_of_review(review["id"]) if p["status"] == "SUBMITTED"]

    # band 10 — award membership, then catalog validation (PRD section 3.6)
    owner_of = {}
    for item in items:
        holder = None
        for presentation in submitted:
            if item["id"] in (presentation.get("item_ids") or []):
                holder = presentation
                break
        principal = db.find("principals", item["principal_id"])
        if holder is None or principal is None or principal["status"] == "TERMINATED":
            raise ApiError("ERR_ITEM_NOT_IN_SUBMITTED_PRESENTATION")
        owner_of[item["id"]] = holder

    for item in items:
        if item["catalog_state"] != "VALIDATED":
            raise ApiError("ERR_ITEM_CATALOG_NOT_VALIDATED")

    retailer = db.find("retailers", review["retailer_id"])

    # band 11 — no authorization may cover more stores than the chain has
    plan = []
    for item in items:
        presentation = owner_of[item["id"]]
        deal = None
        for candidate in domain.deals_of_presentation(presentation["id"]):
            if candidate["state"] in ("PROPOSED", "COUNTERED"):
                deal = candidate
                break
        if deal is not None:
            store_count = deal["store_count_in_scope"]
        else:
            if default_store_count is None:
                raise ApiError(
                    "ERR_INVALID_REQUEST",
                    "Field 'default_store_count' is required when an awarded item's "
                    "presentation carries no live slotting deal.",
                )
            store_count = default_store_count
        if store_count > retailer["total_store_count"]:
            raise ApiError("ERR_STORE_COUNT_EXCEEDS_CHAIN")
        plan.append((item, presentation, deal, store_count))

    # band 12 — slot pool
    slots_remaining = review["new_item_slots"] - review["slots_awarded"]
    if len(awarded_ids) > slots_remaining:
        raise ApiError("ERR_REVIEW_SLOTS_EXCEEDED")

    # ---------------------------------------------------------------- success
    review["status"] = "DECIDED"
    review["decided_at"] = clock.iso_now()
    review["slots_awarded"] = review["slots_awarded"] + len(awarded_ids)
    db.touch(review)

    plan.sort(key=lambda entry: entry[0]["upc"])
    awarded_per_presentation = {}
    for item, presentation, deal, store_count in plan:
        auth = db.base_record()
        auth.update({
            "review_id": review["id"],
            "item_id": item["id"],
            "retailer_id": review["retailer_id"],
            "slotting_deal_id": deal["id"] if deal is not None else None,
            "authorized_store_count": store_count,
            "void_rate_basis": retailer["void_rate_basis_default"],
            "periods_reported": 0,
            "distributed_store_count": 0,
            "void_store_count": 0,
            "pending_store_count": 0,
            "void_rate_bps": 0,
            "slotting_share_cents": 0,
            "promo_settled_funding_cents": 0,
            "trade_spend_total_cents": 0,
            "authorization_state": "AUTHORIZED" if deal is None else "PENDING_SETUP",
            "settlement_state": "UNBILLED",
            "discontinue_reason": None,
        })
        metrics = calc.void_metrics(auth["void_rate_basis"], store_count, None)
        auth.update(metrics)
        db.insert("authorizations", auth)
        awarded_per_presentation[presentation["id"]] = awarded_per_presentation.get(presentation["id"], 0) + 1

    for presentation in submitted:
        count = awarded_per_presentation.get(presentation["id"], 0)
        if count > 0:
            db.assign(presentation, status="ACCEPTED", authorized_item_count=count)
        else:
            db.assign(presentation, status="DECLINED", authorized_item_count=0)
            for deal in domain.deals_of_presentation(presentation["id"]):
                if deal["state"] in ("DRAFT", "PROPOSED", "COUNTERED"):
                    domain.reject_deal(deal, "PRESENTATION_DECLINED")

    return response.ok(serialize(review))
