"""Offer negotiation and DealMemo endpoints."""
from flask import Blueprint, request

import db
from errors import (err_invalid_offer_terms, err_invalid_request,
                    err_invalid_state, err_not_found, err_not_live_offer,
                    err_offer_expired, err_permit_required, err_stale_version,
                    err_unauthorized)
from middleware import require_roles
from response import success_object, success_list
from services import domain
from util import (check_datetime, check_enum, check_int, filter_status,
                  get_payload, logical_now, new_record, paginate, parse_dt,
                  serialize, touch)

S = db.STORE
bp = Blueprint("offers", __name__)

READ_ROLES = ("CastingDirector", "CastingAssociate", "ProductionCoordinator", "Agent")


def _get_submission(sid):
    s = domain.find("submissions", sid)
    if s is None:
        raise err_not_found("Submission not found")
    return s


def _get_offer(oid):
    o = domain.find("offers", oid)
    if o is None:
        raise err_not_found("Offer not found")
    return o


def _check_offer_terms(weekly, guarantee):
    """weekly > 0; guarantee >= 0, <= 52 * weekly, multiple of 100."""
    if isinstance(weekly, int) and not isinstance(weekly, bool) \
            and isinstance(guarantee, int) and not isinstance(guarantee, bool):
        if weekly <= 0 or guarantee < 0 or guarantee > 52 * weekly or guarantee % 100 != 0:
            raise err_invalid_offer_terms()


def _live_offer(submission_id):
    """The live offer of a submission: highest round still EXTENDED."""
    offers = [o for o in S["offers"].values() if o["submission_id"] == submission_id]
    ext = [o for o in offers if o["status"] == "EXTENDED"]
    if not ext:
        return None
    return max(ext, key=lambda o: o["round_number"])


def _offer_context(offer):
    sub = domain.find("submissions", offer["submission_id"])
    bd = domain.find("breakdowns", sub["breakdown_id"]) if sub else None
    role = domain.find("roles", bd["role_id"]) if bd else None
    production = domain.find("productions", bd["production_id"]) if bd else None
    talent = domain.find("talents", sub["talent_id"]) if sub else None
    return sub, bd, role, production, talent


# ---------------------------------------------------------------------------
# Offer creation
# ---------------------------------------------------------------------------

@bp.post("/casting/submissions/<sid>/offers")
def create_offer(sid):
    require_roles("CastingDirector")
    sub = _get_submission(sid)
    body = get_payload()
    if sub["status"] != "CALLBACK_COMPLETED":
        raise err_invalid_state("Offers may be extended only to CALLBACK_COMPLETED submissions")
    weekly = body.get("weekly_rate_cents")
    guarantee = body.get("guarantee_cents")
    _check_offer_terms(weekly, guarantee)
    check_int(body, "weekly_rate_cents")
    check_int(body, "guarantee_cents")
    expires = check_datetime(body, "expires_at")
    rec = new_record({
        "submission_id": sid,
        "weekly_rate_cents": weekly,
        "guarantee_cents": guarantee,
        "round_number": 1,
        "status": "EXTENDED",
        "expires_at": expires,
        "parent_offer_id": None,
    })
    S["offers"][rec["id"]] = rec
    sub["status"] = "OFFER_PENDING"
    touch(sub)
    return success_object(serialize(rec), 201)


@bp.get("/casting/offers")
def list_offers():
    require_roles(*READ_ROLES)
    records = filter_status(S["offers"].values())
    for param in ("submission_id", "parent_offer_id"):
        v = request.args.get(param)
        if v is not None:
            records = [r for r in records if r.get(param) == v]
    page, limit, offset, total = paginate(records)
    return success_list([serialize(r) for r in page], limit, offset, total)


@bp.get("/casting/offers/<oid>")
def get_offer(oid):
    require_roles(*READ_ROLES)
    return success_object(serialize(_get_offer(oid)))


@bp.get("/casting/submissions/<sid>/offers")
def list_submission_offers(sid):
    require_roles(*READ_ROLES)
    _get_submission(sid)
    records = filter_status(domain.children("offers", "submission_id", sid))
    page, limit, offset, total = paginate(records)
    return success_list([serialize(r) for r in page], limit, offset, total)


# ---------------------------------------------------------------------------
# Counter / accept / decline / withdraw
# ---------------------------------------------------------------------------

@bp.post("/casting/offers/<oid>/counter")
def counter_offer(oid):
    user_id, role = require_roles("CastingDirector", "Agent")
    offer = _get_offer(oid)
    sub, bd, role_rec, production, talent = _offer_context(offer)
    if role == "Agent" and sub.get("agent_id") != user_id:
        raise err_unauthorized("Only the submission's agent may counter talent-side")
    # state-machine legality: counter is defined from EXTENDED/COUNTERED; an
    # EXPIRED offer is handled by the expiry gate; other terminal states lock.
    if offer["status"] not in ("EXTENDED", "COUNTERED", "EXPIRED"):
        raise err_invalid_state("Offer cannot be countered from its current state")
    # OCC on Offer.version
    body = get_payload()
    expected = body.get("expected_offer_version")
    if isinstance(expected, int) and not isinstance(expected, bool):
        if expected != offer["version"]:
            raise err_stale_version("expected_offer_version does not match the offer version")
    # terms validity
    weekly = body.get("weekly_rate_cents")
    guarantee = body.get("guarantee_cents")
    _check_offer_terms(weekly, guarantee)
    # liveness
    if offer["status"] == "COUNTERED":
        raise err_not_live_offer()
    # expiry
    if offer["status"] == "EXPIRED" or not logical_now() < offer["expires_at"]:
        raise err_offer_expired()
    # final field validation
    check_int(body, "weekly_rate_cents")
    check_int(body, "guarantee_cents")
    expires = check_datetime(body, "expires_at")
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise err_invalid_request("expected_offer_version is required and must be an integer")
    offer["status"] = "COUNTERED"
    touch(offer)
    rec = new_record({
        "submission_id": offer["submission_id"],
        "weekly_rate_cents": weekly,
        "guarantee_cents": guarantee,
        "round_number": offer["round_number"] + 1,
        "status": "EXTENDED",
        "expires_at": expires,
        "parent_offer_id": offer["id"],
    })
    S["offers"][rec["id"]] = rec
    return success_object(serialize(rec), 201)


@bp.post("/casting/offers/<oid>/accept")
def accept_offer(oid):
    user_id, role = require_roles("Agent", "CastingDirector")
    offer = _get_offer(oid)
    sub, bd, role_rec, production, talent = _offer_context(offer)
    # signature: the submission's agent; or a CastingDirector countersigning a
    # self-submission (agent_id null)
    if role == "Agent":
        if sub.get("agent_id") != user_id:
            raise err_unauthorized("Only the submission's agent may accept this offer")
    else:
        if sub.get("agent_id") is not None:
            raise err_unauthorized("CastingDirector may accept only on self-submissions")
    if offer["status"] not in ("EXTENDED", "COUNTERED", "EXPIRED"):
        raise err_invalid_state("Offer cannot be accepted from its current state")
    body = get_payload()
    # minor-permit gate (evaluated before liveness per PRD 3.7)
    eng_end = parse_dt(body.get("engagement_end")) if body.get("engagement_end") is not None else None
    if role_rec is not None and role_rec.get("is_minor_role") \
            and talent is not None and domain.compute_is_minor(talent):
        if domain.permit_covers(talent["id"], production["id"], eng_end) is None:
            raise err_permit_required()
    # liveness
    if offer["status"] == "COUNTERED":
        raise err_not_live_offer()
    # expiry
    if offer["status"] == "EXPIRED" or not logical_now() < offer["expires_at"]:
        raise err_offer_expired()
    # final field validation
    eng_start = check_datetime(body, "engagement_start")
    eng_end = check_datetime(body, "engagement_end")
    mode = check_enum(body, "proration_mode", {"CALENDAR_SPAN", "WORKDAY_SPAN"})
    if eng_end < eng_start:
        raise err_invalid_request("engagement_end must be on or after engagement_start")
    fee = domain.engagement_fee_proration(offer["weekly_rate_cents"], eng_start, eng_end, mode)
    memo = new_record({
        "offer_id": offer["id"],
        "engagement_start": eng_start,
        "engagement_end": eng_end,
        "proration_mode": mode,
        "computed_fee_cents": fee,
        "cancellation_penalty_cents": 0,
        "status": "EXECUTED",
    })
    S["deal_memos"][memo["id"]] = memo
    offer["status"] = "ACCEPTED"
    touch(offer)
    return success_object(serialize(memo), 200)


@bp.post("/casting/offers/<oid>/decline")
def decline_offer(oid):
    user_id, role = require_roles("Agent")
    offer = _get_offer(oid)
    sub, bd, role_rec, production, talent = _offer_context(offer)
    if sub.get("agent_id") != user_id:
        raise err_unauthorized("Only the submission's agent may decline this offer")
    if offer["status"] not in ("EXTENDED", "COUNTERED", "EXPIRED"):
        raise err_invalid_state("Offer cannot be declined from its current state")
    if offer["status"] != "EXTENDED":
        raise err_not_live_offer()
    offer["status"] = "DECLINED"
    touch(offer)
    if sub["status"] == "OFFER_PENDING":
        sub["status"] = "CALLBACK_COMPLETED"
        touch(sub)
    return success_object(serialize(offer))


@bp.post("/casting/offers/<oid>/withdraw")
def withdraw_offer(oid):
    require_roles("CastingDirector")
    offer = _get_offer(oid)
    sub, bd, role_rec, production, talent = _offer_context(offer)
    if offer["status"] not in ("EXTENDED", "COUNTERED", "EXPIRED"):
        raise err_invalid_state("Offer cannot be withdrawn from its current state")
    if offer["status"] != "EXTENDED":
        raise err_not_live_offer()
    offer["status"] = "WITHDRAWN"
    touch(offer)
    if sub["status"] == "OFFER_PENDING":
        sub["status"] = "CALLBACK_COMPLETED"
        touch(sub)
    domain.release_active_holds_on_submission(sub["id"], kinds=("CONFIRMED",))
    return success_object(serialize(offer))


# ---------------------------------------------------------------------------
# Deal memos
# ---------------------------------------------------------------------------

@bp.get("/casting/deal-memos/<mid>")
def get_deal_memo(mid):
    require_roles(*READ_ROLES)
    m = domain.find("deal_memos", mid)
    if m is None:
        raise err_not_found("DealMemo not found")
    return success_object(serialize(m))


@bp.get("/casting/offers/<oid>/deal-memos")
def get_offer_deal_memos(oid):
    require_roles(*READ_ROLES)
    _get_offer(oid)
    records = domain.children("deal_memos", "offer_id", oid)
    page, limit, offset, total = paginate(records)
    return success_list([serialize(r) for r in page], limit, offset, total)


@bp.post("/casting/deal-memos/<mid>/void")
def void_deal_memo(mid):
    require_roles("CastingDirector")
    m = domain.find("deal_memos", mid)
    if m is None:
        raise err_not_found("DealMemo not found")
    if m["status"] != "EXECUTED":
        raise err_invalid_state("Only an EXECUTED deal memo can be voided")
    referencing = [b for b in S["bookings"].values() if b["deal_memo_id"] == mid]
    if any(b["status"] == "CONFIRMED" for b in referencing):
        raise err_invalid_state("Cannot void a memo backing a CONFIRMED booking")
    m["status"] = "VOIDED"
    touch(m)
    for b in referencing:
        if b["status"] == "PENDING":
            domain.cancel_booking_record(b, "PRODUCTION_CANCELLED", compute_penalty=False)
    return success_object(serialize(m))
