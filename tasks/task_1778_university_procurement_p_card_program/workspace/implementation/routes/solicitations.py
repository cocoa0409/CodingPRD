"""Bid solicitation lifecycle: quotes, close (scoring), award, cancel (PRD 3.4)."""

import db
import services as svc
from middleware import authenticate, ROLES
from response import success_obj, success_list
from routes import make_blueprint
from util import (
    body_json,
    check_shape,
    pagination_params,
    paginate,
    require_fk,
    dt_of,
)
from errors import (
    ApiError,
    ERR_SOLICITATION_NOT_OPEN,
    ERR_SOLICITATION_NOT_CLOSED,
    ERR_SOLICITATION_NOT_CANCELLABLE,
    ERR_SOLICITATION_EXPIRED,
    ERR_SOLICITATION_DEADLINE_NOT_PASSED,
    ERR_DUPLICATE_QUOTE,
    ERR_VENDOR_SUSPENDED,
    ERR_NO_ELIGIBLE_QUOTES,
    ERR_INSUFFICIENT_QUOTES,
    ERR_AWARD_NOT_TOP_SCORE,
    ERR_QUOTE_NOT_FOUND,
)

bp = make_blueprint("solicitations")


@bp.get("/solicitations/<sid>")
def get_solicitation(sid):
    authenticate(ROLES)
    sol = require_fk("solicitations", sid)
    return success_obj(db.public(sol), 200)


@bp.post("/solicitations/<sid>/quotes")
def submit_quote(sid):
    authenticate(["Buyer"])
    sol = require_fk("solicitations", sid)
    body = body_json()
    if body.get("vendor_id") is not None and isinstance(body.get("vendor_id"), str):
        require_fk("vendors", body["vendor_id"])  # p3 body-FK existence
    if sol["status"] != "OPEN":
        raise ApiError(ERR_SOLICITATION_NOT_OPEN, 409, "quotes are accepted while the solicitation is OPEN")
    check_shape(body, {
        "vendor_id": {"type": "string", "required": True},
        "price_cents": {"type": "integer", "required": True, "min_exclusive": 0},
    })
    vendor = db.get("vendors", body["vendor_id"])
    # p8 temporal: the submission window is half-open [ , deadline).
    if not db.now() < dt_of(sol, "response_deadline"):
        raise ApiError(ERR_SOLICITATION_EXPIRED, 409, "the response deadline has passed")
    # p9 structural: one SUBMITTED quote per vendor per solicitation.
    for q in svc.quotes_of_solicitation(sol["id"]):
        if q["vendor_id"] == vendor["id"] and q["status"] == "SUBMITTED":
            raise ApiError(ERR_DUPLICATE_QUOTE, 409, "vendor already has a SUBMITTED quote on this solicitation")
    # p10 referential: bidding vendor must be ACTIVE.
    if vendor["status"] != "ACTIVE":
        raise ApiError(ERR_VENDOR_SUSPENDED, 409, "bidding vendor must be ACTIVE")
    quote = db.new_entity("quotes", {
        "solicitation_id": sol["id"],
        "vendor_id": vendor["id"],
        "price_cents": body["price_cents"],
        "submitted_at": db.logical_ts(),
        "status": "SUBMITTED",
        "score": None,
    })
    return success_obj(db.public(quote), 201)


@bp.get("/solicitations/<sid>/quotes")
def list_quotes(sid):
    authenticate(ROLES)
    sol = require_fk("solicitations", sid)
    limit, offset = pagination_params()
    items = svc.quotes_of_solicitation(sol["id"])
    page, total, has_more = paginate(items, limit, offset)
    return success_list([db.public(q) for q in page], limit, offset, total, has_more)


@bp.post("/solicitations/<sid>/close")
def close_solicitation(sid):
    authenticate(["Buyer"])
    sol = require_fk("solicitations", sid)
    if sol["status"] != "OPEN":
        raise ApiError(ERR_SOLICITATION_NOT_OPEN, 409, "close requires an OPEN solicitation")
    if not db.now() >= dt_of(sol, "response_deadline"):
        raise ApiError(ERR_SOLICITATION_DEADLINE_NOT_PASSED, 409, "the response deadline has not passed")
    sol["status"] = "CLOSED"
    db.touch(sol)
    svc.compute_scores_at_close(sol)  # scores pinned for every quote
    return success_obj(db.public(sol), 200)


@bp.post("/solicitations/<sid>/award")
def award_solicitation(sid):
    authenticate(["ProcurementDirector"])
    sol = require_fk("solicitations", sid)
    body = body_json()
    named = None
    if body.get("quote_id") is not None:
        # p3 body-FK existence, scoped to this solicitation.
        if not isinstance(body["quote_id"], str):
            raise ApiError(ERR_QUOTE_NOT_FOUND, 404, "quote not found")
        named = db.get("quotes", body["quote_id"])
        if named is None or named["solicitation_id"] != sol["id"]:
            raise ApiError(ERR_QUOTE_NOT_FOUND, 404, "quote not found on this solicitation")
    if sol["status"] != "CLOSED":
        raise ApiError(ERR_SOLICITATION_NOT_CLOSED, 409, "award requires a CLOSED solicitation")
    check_shape(body, {
        "quote_id": {"type": "string"},
        "override_reason": {"type": "string"},
    })
    override = body.get("override_reason")
    # p9 structural: eligible pool, min_quotes gate, top-score rule.
    pool = svc.eligible_pool_at_award(sol)
    if not pool:
        raise ApiError(ERR_NO_ELIGIBLE_QUOTES, 409, "no eligible quotes to award")
    if len(pool) < sol["min_quotes"] and not override:
        raise ApiError(ERR_INSUFFICIENT_QUOTES, 409, "fewer eligible quotes than min_quotes; an override_reason is required")
    winner = svc.select_winner(pool)
    if named is not None and named["id"] != winner["id"]:
        if not override:
            raise ApiError(ERR_AWARD_NOT_TOP_SCORE, 409, "awarding a non-top-scoring quote requires an override_reason")
        if all(q["id"] != named["id"] for q in pool):
            raise ApiError(ERR_AWARD_NOT_TOP_SCORE, 409, "the named quote is not in the eligible pool")
        winner = named
    # Side effects: winner AWARDED, other SUBMITTED quotes NOT_AWARDED.
    for q in svc.quotes_of_solicitation(sol["id"]):
        if q["id"] == winner["id"]:
            q["status"] = "AWARDED"
            db.touch(q)
        elif q["status"] == "SUBMITTED":
            q["status"] = "NOT_AWARDED"
            db.touch(q)
    sol["status"] = "AWARDED"
    sol["awarded_quote_id"] = winner["id"]
    sol["awarded_at"] = db.logical_ts()
    db.touch(sol)
    req = db.get("requisitions", sol["requisition_id"])
    if req is not None:
        req["vendor_id"] = winner["vendor_id"]
        req["sourcing_method"] = "COMPETITIVE_BID"
        db.touch(req)
    return success_obj(db.public(sol), 200)


@bp.post("/solicitations/<sid>/cancel")
def cancel_solicitation(sid):
    """Manual cancel from OPEN or CLOSED; AWARDED cancels only through the
    vendor-suspension cascade."""
    authenticate(["Buyer"])
    sol = require_fk("solicitations", sid)
    if sol["status"] not in ("OPEN", "CLOSED"):
        raise ApiError(ERR_SOLICITATION_NOT_CANCELLABLE, 409, "cancel requires OPEN or CLOSED")
    for q in svc.quotes_of_solicitation(sol["id"]):
        if q["status"] == "SUBMITTED":
            q["status"] = "NOT_AWARDED"
            db.touch(q)
    sol["status"] = "CANCELLED"
    db.touch(sol)
    return success_obj(db.public(sol), 200)
