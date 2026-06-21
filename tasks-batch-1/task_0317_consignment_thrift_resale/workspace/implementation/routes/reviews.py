from flask import Blueprint, request

from db import store
from errors import err
from middleware import require
from response import success
from services.common import base_record, touch, require_body, require_enum
from services import serialize

bp = Blueprint("reviews", __name__)


@bp.post("/authentication-reviews")
@require("Authenticator")
def open_review():
    body = require_body()
    if "item_id" not in body or not isinstance(body["item_id"], str):
        raise err("ERR_INVALID_REQUEST", "item_id required")
    item = store.items.get(body["item_id"])
    if item is None:
        raise err("ERR_REFERENCE_NOT_FOUND", "Item not found")

    # State: item must require auth and be ACCEPTED at grading.
    if not item["requires_authentication"] or item["grading_status"] != "ACCEPTED":
        raise err("ERR_INVALID_STATE", "Item not eligible for authentication review")

    # Segregation of duties: opener must not be the grader.
    if request.user_id == item.get("graded_by_user_id"):
        raise err("ERR_SEGREGATION_OF_DUTIES", "Authenticator graded this item")

    rec = base_record()
    rec.update({
        "item_id": item["id"],
        "opened_by_user_id": request.user_id,
        "status": "IN_REVIEW",
        "dispute_round": 0,
        "verdict_note": None,
    })
    store.authentication_reviews[rec["id"]] = rec
    return success(serialize.review_out(rec), 201)


@bp.get("/authentication-reviews/<rid>")
@require("Authenticator", "SettlementManager", "StoreAdmin", "IntakeGrader")
def get_review(rid):
    r = store.authentication_reviews.get(rid)
    if r is None:
        raise err("ERR_NOT_FOUND", "Review not found")
    return success(serialize.review_out(r), 200)


@bp.post("/authentication-reviews/<rid>/verdict")
@require("Authenticator")
def verdict(rid):
    r = store.authentication_reviews.get(rid)
    if r is None:
        raise err("ERR_NOT_FOUND", "Review not found")
    body = require_body()
    decision = require_enum(body, "verdict", {"AUTHENTIC", "COUNTERFEIT"})
    note = body.get("verdict_note")
    if note is not None and not isinstance(note, str):
        raise err("ERR_INVALID_REQUEST", "verdict_note must be a string")

    # State precedes business rule (PRD §2.5).
    if r["status"] != "IN_REVIEW":
        raise err("ERR_INVALID_STATE", "Review is not IN_REVIEW")

    item = store.items[r["item_id"]]
    # Segregation of duties: ruler must not be the grader.
    if request.user_id == item.get("graded_by_user_id"):
        raise err("ERR_SEGREGATION_OF_DUTIES", "Authenticator graded this item")

    if note is not None:
        r["verdict_note"] = note

    if decision == "AUTHENTIC":
        r["status"] = "AUTHENTIC"
        item["authentication_status"] = "AUTHENTIC"
        touch(item)
    else:  # COUNTERFEIT
        r["status"] = "COUNTERFEIT"
        item["authentication_status"] = "COUNTERFEIT"
        item["grading_status"] = "REJECTED"
        touch(item)

    touch(r)
    return success(serialize.review_out(r), 200)


@bp.post("/authentication-reviews/<rid>/dispute")
@require("SettlementManager", "StoreAdmin")
def dispute(rid):
    r = store.authentication_reviews.get(rid)
    if r is None:
        raise err("ERR_NOT_FOUND", "Review not found")
    if r["status"] != "IN_REVIEW":
        raise err("ERR_INVALID_STATE", "Review is not IN_REVIEW")
    r["status"] = "DISPUTED"
    touch(r)
    return success(serialize.review_out(r), 200)


@bp.post("/authentication-reviews/<rid>/reopen")
@require("Authenticator")
def reopen(rid):
    r = store.authentication_reviews.get(rid)
    if r is None:
        raise err("ERR_NOT_FOUND", "Review not found")
    if r["status"] != "DISPUTED":
        raise err("ERR_INVALID_STATE", "Review is not DISPUTED")
    r["status"] = "IN_REVIEW"
    r["dispute_round"] += 1
    touch(r)
    return success(serialize.review_out(r), 200)
