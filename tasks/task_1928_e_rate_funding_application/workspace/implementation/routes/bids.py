"""Bid endpoints: submission inside the half-open 28-day window, curation (PRD 3.3)."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error, ERR_INVALID_REQUEST, ERR_INVALID_STATE_TRANSITION,
    ERR_BID_WINDOW_CLOSED,
)
from middleware import (
    get_caller, check_role, check_applicant_scope, check_provider_identity,
)
from response import success_object
from routes.helpers import public, list_collection, get_one
from services.core import new_record, touch
from util import CLOCK, parse_datetime
from validate import (
    get_body, check_allowed, req_str, req_int, opt_int, require_ref,
    require_path_resource,
)

bp = Blueprint("bids", __name__, url_prefix="/erate")

CREATE_FIELDS = {"posting_id", "eligible_price_cents", "ineligible_price_cents",
                 "factor_scores"}


def _posting_applicant_id(bid):
    posting = db["procurement_postings"].get(bid["posting_id"])
    return posting["applicant_id"] if posting else None


@bp.post("/bids")
def create_bid():
    caller = get_caller()
    check_role(caller, ["VendorRepresentative"])
    # Bid submission is open to any registered provider; the identity must resolve.
    check_provider_identity(caller)
    body = get_body()
    check_allowed(body, CREATE_FIELDS)
    posting_id = req_str(body, "posting_id")
    eligible_price_cents = req_int(body, "eligible_price_cents", positive=True)
    ineligible_price_cents = opt_int(body, "ineligible_price_cents", default=0,
                                     non_negative=True)
    factor_scores = body.get("factor_scores")
    if not isinstance(factor_scores, list):
        raise_error(ERR_INVALID_REQUEST, "factor_scores must be an array")
    for item in factor_scores:
        if not isinstance(item, dict):
            raise_error(ERR_INVALID_REQUEST, "factor_scores entries must be objects")
        fname = item.get("factor_name")
        if not isinstance(fname, str) or fname.strip() == "":
            raise_error(ERR_INVALID_REQUEST, "factor_scores factor_name must be a non-empty string")
        score = item.get("score")
        if score is None or isinstance(score, bool) or not isinstance(score, int) \
                or score < 0 or score > 100:
            raise_error(ERR_INVALID_REQUEST, "factor_scores score must be an integer 0..100")
    posting = require_ref("procurement_postings", posting_id, "posting_id")
    # factor_scores must cover exactly the posting's other-factor set.
    expected = [w["factor_name"] for w in posting["other_factor_weights"]]
    given = [fs["factor_name"] for fs in factor_scores]
    if set(given) != set(expected) or len(given) != len(set(given)):
        raise_error(ERR_INVALID_REQUEST,
                    "factor_scores must cover exactly the posting's factor set")
    # State gate: bids only against a POSTED posting.
    if posting["status"] != "POSTED":
        raise_error(ERR_INVALID_STATE_TRANSITION, "posting is not POSTED")
    # Temporal gate: the bid window is half-open [posted_at, window_close_at);
    # a bid at exactly window_close_at is already late.
    if CLOCK.now() >= parse_datetime(posting["window_close_at"]):
        raise_error(ERR_BID_WINDOW_CLOSED, "the 28-day bid window has closed")
    rec = new_record("bids", {
        "posting_id": posting_id,
        "service_provider_id": caller.user_id,
        "eligible_price_cents": eligible_price_cents,
        "ineligible_price_cents": ineligible_price_cents,
        "factor_scores": [
            {"factor_name": fs["factor_name"], "score": fs["score"]}
            for fs in factor_scores
        ],
        "total_score": None,
        "status": "SUBMITTED",
    })
    return success_object(public(rec), 201)


@bp.get("/bids")
def list_bids():
    return list_collection("bids", {
        "posting_id": request.args.get("posting_id"),
        "service_provider_id": request.args.get("service_provider_id"),
        "status": request.args.get("status"),
    })


@bp.get("/bids/<rid>")
def get_bid(rid):
    return get_one("bids", rid)


@bp.post("/bids/<rid>/qualify")
def qualify(rid):
    caller = get_caller()
    check_role(caller, ["ApplicantCoordinator"])
    existing = db["bids"].get(rid)
    if existing is not None:
        check_applicant_scope(caller, _posting_applicant_id(existing))
    body = get_body()
    check_allowed(body, set())
    bid = require_path_resource("bids", rid)
    if bid["status"] != "SUBMITTED":
        raise_error(ERR_INVALID_STATE_TRANSITION, "bid is not SUBMITTED")
    bid["status"] = "QUALIFIED"
    touch(bid)
    return success_object(public(bid))


@bp.post("/bids/<rid>/disqualify")
def disqualify(rid):
    caller = get_caller()
    check_role(caller, ["ApplicantCoordinator"])
    existing = db["bids"].get(rid)
    if existing is not None:
        check_applicant_scope(caller, _posting_applicant_id(existing))
    body = get_body()
    check_allowed(body, {"reason"})
    bid = require_path_resource("bids", rid)
    if bid["status"] == "SUBMITTED":
        pass
    elif bid["status"] == "QUALIFIED":
        posting = db["procurement_postings"].get(bid["posting_id"])
        if posting is not None and posting["status"] == "AWARDED":
            raise_error(ERR_INVALID_STATE_TRANSITION,
                        "a QUALIFIED bid cannot be disqualified after award")
    else:
        raise_error(ERR_INVALID_STATE_TRANSITION,
                    "only SUBMITTED or QUALIFIED bids may be disqualified")
    bid["status"] = "DISQUALIFIED"
    touch(bid)
    return success_object(public(bid))
