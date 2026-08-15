"""ProcurementPosting endpoints: competitive bidding lifecycle (PRD 3.3)."""
from datetime import timedelta

from flask import Blueprint, request

from db import db
from errors import (
    raise_error, ERR_INVALID_REQUEST, ERR_INVALID_STATE_TRANSITION,
    ERR_PRICE_NOT_PRIMARY, ERR_NO_QUALIFIED_BIDS, ERR_BID_WINDOW_STILL_OPEN,
)
from middleware import (
    get_caller, check_role, check_applicant_scope,
)
from response import success_object
from routes.helpers import public, list_collection, get_one
from services.calcs import score_qualified_bids, pick_winner
from services.core import new_record, touch
from util import CLOCK, parse_datetime, fmt_datetime
from validate import (
    get_body, check_allowed, req_str, req_int, req_enum, require_ref,
    require_path_resource,
)

bp = Blueprint("postings", __name__, url_prefix="/erate")

CATEGORIES = ("CATEGORY_ONE", "CATEGORY_TWO")

CREATE_FIELDS = {"applicant_id", "funding_cycle_id", "category", "description",
                 "price_weight_pct", "other_factor_weights"}


def _scope_existing_posting(caller, posting):
    """Tier 3 ownership for path-targeted actions (skipped when the posting does
    not exist; tier-5 existence reports the 404)."""
    if posting is not None:
        check_applicant_scope(caller, posting["applicant_id"])


@bp.post("/procurement-postings")
def create_posting():
    caller = get_caller()
    check_role(caller, ["ApplicantCoordinator"])
    body = get_body()
    # Tier 3 ownership: caller's applicant must match the body's applicant_id.
    raw_applicant = body.get("applicant_id")
    if isinstance(raw_applicant, str):
        check_applicant_scope(caller, raw_applicant)
    check_allowed(body, CREATE_FIELDS)
    applicant_id = req_str(body, "applicant_id")
    funding_cycle_id = req_str(body, "funding_cycle_id")
    category = req_enum(body, "category", CATEGORIES)
    description = req_str(body, "description")
    price_weight_pct = req_int(body, "price_weight_pct", minimum=1, maximum=100)
    other_factor_weights = body.get("other_factor_weights")
    if other_factor_weights is None:
        other_factor_weights = []
    if not isinstance(other_factor_weights, list):
        raise_error(ERR_INVALID_REQUEST, "other_factor_weights must be an array")
    for item in other_factor_weights:
        if not isinstance(item, dict):
            raise_error(ERR_INVALID_REQUEST, "other_factor_weights entries must be objects")
        fname = item.get("factor_name")
        if not isinstance(fname, str) or fname.strip() == "":
            raise_error(ERR_INVALID_REQUEST, "factor_name must be a non-empty string")
        wpct = item.get("weight_pct")
        if wpct is None or isinstance(wpct, bool) or not isinstance(wpct, int):
            raise_error(ERR_INVALID_REQUEST, "weight_pct must be an integer")
    require_ref("applicants", applicant_id, "applicant_id")
    require_ref("funding_cycles", funding_cycle_id, "funding_cycle_id")
    # Structural: price must be the primary factor.
    for w in other_factor_weights:
        if price_weight_pct < w["weight_pct"]:
            raise_error(ERR_PRICE_NOT_PRIMARY,
                        "price_weight_pct is below another evaluation factor weight")
    rec = new_record("procurement_postings", {
        "applicant_id": applicant_id,
        "funding_cycle_id": funding_cycle_id,
        "category": category,
        "description": description,
        "price_weight_pct": price_weight_pct,
        "other_factor_weights": [
            {"factor_name": w["factor_name"], "weight_pct": w["weight_pct"]}
            for w in other_factor_weights
        ],
        "status": "DRAFT",
        "posted_at": None,
        "window_close_at": None,
        "selected_bid_id": None,
        "selected_by_user_id": None,
    })
    return success_object(public(rec), 201)


@bp.get("/procurement-postings")
def list_postings():
    return list_collection("procurement_postings", {
        "applicant_id": request.args.get("applicant_id"),
        "funding_cycle_id": request.args.get("funding_cycle_id"),
        "status": request.args.get("status"),
    })


@bp.get("/procurement-postings/<rid>")
def get_posting(rid):
    return get_one("procurement_postings", rid)


@bp.post("/procurement-postings/<rid>/publish")
def publish(rid):
    caller = get_caller()
    check_role(caller, ["ApplicantCoordinator"])
    _scope_existing_posting(caller, db["procurement_postings"].get(rid))
    body = get_body()
    check_allowed(body, set())
    posting = require_path_resource("procurement_postings", rid)
    if posting["status"] != "DRAFT":
        raise_error(ERR_INVALID_STATE_TRANSITION, "posting is not DRAFT")
    posted_dt = CLOCK.now()
    posting["posted_at"] = fmt_datetime(posted_dt)
    posting["window_close_at"] = fmt_datetime(posted_dt + timedelta(days=28))
    posting["status"] = "POSTED"
    touch(posting)
    return success_object(public(posting))


@bp.post("/procurement-postings/<rid>/close-window")
def close_window(rid):
    caller = get_caller()
    check_role(caller, ["ApplicantCoordinator"])
    _scope_existing_posting(caller, db["procurement_postings"].get(rid))
    body = get_body()
    check_allowed(body, set())
    posting = require_path_resource("procurement_postings", rid)
    if posting["status"] != "POSTED":
        raise_error(ERR_INVALID_STATE_TRANSITION, "posting is not POSTED")
    if CLOCK.now() < parse_datetime(posting["window_close_at"]):
        raise_error(ERR_BID_WINDOW_STILL_OPEN,
                    "the 28-day bid window has not fully elapsed")
    posting["status"] = "WINDOW_CLOSED"
    touch(posting)
    return success_object(public(posting))


@bp.post("/procurement-postings/<rid>/cancel")
def cancel(rid):
    caller = get_caller()
    check_role(caller, ["ApplicantCoordinator"])
    _scope_existing_posting(caller, db["procurement_postings"].get(rid))
    body = get_body()
    check_allowed(body, set())
    posting = require_path_resource("procurement_postings", rid)
    if posting["status"] not in ("DRAFT", "POSTED"):
        raise_error(ERR_INVALID_STATE_TRANSITION,
                    "only DRAFT or POSTED postings may be cancelled")
    if posting["status"] == "POSTED":
        # Cascade down: every SUBMITTED/QUALIFIED bid -> DISQUALIFIED.
        for bid in db["bids"].values():
            if bid["posting_id"] == rid and bid["status"] in ("SUBMITTED", "QUALIFIED"):
                bid["status"] = "DISQUALIFIED"
                touch(bid)
    posting["status"] = "CANCELLED"
    touch(posting)
    return success_object(public(posting))


@bp.post("/procurement-postings/<rid>/select-winner")
def select_winner(rid):
    caller = get_caller()
    check_role(caller, ["ApplicantCoordinator", "ApplicantCertifier"])
    _scope_existing_posting(caller, db["procurement_postings"].get(rid))
    body = get_body()
    check_allowed(body, set())
    posting = require_path_resource("procurement_postings", rid)
    if posting["status"] != "WINDOW_CLOSED":
        raise_error(ERR_INVALID_STATE_TRANSITION, "posting is not WINDOW_CLOSED")
    candidates = [b for b in db["bids"].values()
                  if b["posting_id"] == rid and b["status"] == "QUALIFIED"]
    if not candidates:
        raise_error(ERR_NO_QUALIFIED_BIDS, "no QUALIFIED bids on this posting")
    totals = score_qualified_bids(posting, candidates)
    winner = pick_winner(candidates, totals)
    for bid in candidates:
        bid["total_score"] = float(totals[bid["id"]])
        bid["status"] = "SELECTED" if bid["id"] == winner["id"] else "NOT_SELECTED"
        touch(bid)
    posting["status"] = "AWARDED"
    posting["selected_bid_id"] = winner["id"]
    posting["selected_by_user_id"] = caller.user_id
    touch(posting)
    return success_object(public(posting))
