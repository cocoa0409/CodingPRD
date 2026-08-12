"""Offer and Deal endpoints."""
from flask import Blueprint

from core import (DB, F, ERR_NOT_TOP, ERR_SOD, ERR_STALE, ERR_STATE,
                  ERR_STMT_UNRESOLVED, acting_agency, fail, get_ref,
                  get_scoped, guard, list_response, new_record, parse_body,
                  public, success, touch)
from domain import (LIVE_OFFER, LIVE_SUBMISSION, advance_waterfall,
                    offers_of_round, recompute_auction_ranks, round_of_offer,
                    signed_agreement_for_manuscript, subs_of_round)

bp = Blueprint("offers", __name__)

ALL = ("AgencyAdmin", "Agent", "ContractsManager", "RoyaltiesAccountant")

OFFER_TERM_FIELDS = [
    F("advance_cents", "int", required=True, lo=0),
    F("royalty_pct_hardcover", "num", required=True, lo=0),
    F("royalty_pct_trade", "num", required=True, lo=0),
    F("royalty_pct_ebook", "num", required=True, lo=0),
    F("royalty_basis", "enum", enum=("NET", "RETAIL")),
    F("includes_film_rights", "bool"),
    F("includes_foreign_rights", "bool"),
    F("includes_audio_rights", "bool"),
]


def _apply_terms(offer, data, creating):
    offer["advance_cents"] = data["advance_cents"]
    offer["royalty_pct_hardcover"] = data["royalty_pct_hardcover"]
    offer["royalty_pct_trade"] = data["royalty_pct_trade"]
    offer["royalty_pct_ebook"] = data["royalty_pct_ebook"]
    for name, default in (("royalty_basis", "NET"),
                          ("includes_film_rights", False),
                          ("includes_foreign_rights", False),
                          ("includes_audio_rights", False)):
        if creating:
            offer[name] = data[name] if data[name] is not None else default
        elif data[name] is not None:
            offer[name] = data[name]


# ------------------------------------------------------------------- offers ----
@bp.route("/offers", methods=["POST"])
def create_offer():
    ctx = guard("Agent")
    data = parse_body([F("submission_id", "str", required=True)]
                      + OFFER_TERM_FIELDS)
    sub = get_ref("submissions", data["submission_id"], acting_agency(ctx))
    if sub["status"] not in ("SENT", "UNDER_CONSIDERATION"):
        fail(ERR_STATE, 409,
             "offer requires submission SENT or UNDER_CONSIDERATION")
    rec = new_record()
    rec.update({
        "agency_id": sub["agency_id"],
        "submission_id": sub["id"],
        "auction_rank": None,
        "status": "RECEIVED",
    })
    _apply_terms(rec, data, creating=True)
    DB["offers"][rec["id"]] = rec
    sub["status"] = "OFFER_EXTENDED"
    touch(sub)
    rnd = DB["submission_rounds"].get(sub["submission_round_id"])
    if rnd is not None:
        recompute_auction_ranks(rnd)
    return success(public(rec), 201)


@bp.route("/offers/<offerId>", methods=["GET"])
def get_offer(offerId):
    ctx = guard(*ALL)
    return success(public(get_scoped("offers", offerId, ctx)))


@bp.route("/offers", methods=["GET"])
def list_offers():
    ctx = guard(*ALL)
    return list_response("offers", ctx, {
        "agency_id": "str", "status": "str", "submission_id": "str",
    })


@bp.route("/offers/<offerId>/negotiate", methods=["POST"])
def negotiate_offer(offerId):
    ctx = guard("Agent")
    parse_body([])
    offer = get_scoped("offers", offerId, ctx)
    if offer["status"] != "RECEIVED":
        fail(ERR_STATE, 409, "offer is not RECEIVED")
    offer["status"] = "UNDER_NEGOTIATION"
    touch(offer)
    return success(public(offer))


@bp.route("/offers/<offerId>/revise", methods=["POST"])
def revise_offer(offerId):
    ctx = guard("Agent")
    data = parse_body(OFFER_TERM_FIELDS)
    offer = get_scoped("offers", offerId, ctx)
    if offer["status"] != "UNDER_NEGOTIATION":
        fail(ERR_STATE, 409, "offer is not UNDER_NEGOTIATION")
    _apply_terms(offer, data, creating=False)
    offer["status"] = "RECEIVED"
    touch(offer)
    rnd = round_of_offer(offer)
    recompute_auction_ranks(rnd)
    return success(public(offer))


def _kill_offer(offer, terminal, ctx):
    """Decline / editor-withdraw: live offer -> terminal, submission -> PASSED."""
    if offer["status"] not in LIVE_OFFER:
        fail(ERR_STATE, 409, "offer is not live")
    agency = DB["agencies"].get(offer["agency_id"])
    offer["status"] = terminal
    touch(offer)
    sub = DB["submissions"].get(offer["submission_id"])
    if sub is not None and sub["status"] == "OFFER_EXTENDED":
        sub["status"] = "PASSED"
        sub["response_period_index"] = agency["period_index"] if agency else None
        touch(sub)
    rnd = round_of_offer(offer)
    recompute_auction_ranks(rnd)
    return success(public(offer))


@bp.route("/offers/<offerId>/decline", methods=["POST"])
def decline_offer(offerId):
    ctx = guard("Agent")
    parse_body([])
    return _kill_offer(get_scoped("offers", offerId, ctx), "DECLINED", ctx)


@bp.route("/offers/<offerId>/editor-withdraw", methods=["POST"])
def editor_withdraw_offer(offerId):
    ctx = guard("Agent")
    parse_body([])
    return _kill_offer(get_scoped("offers", offerId, ctx),
                       "WITHDRAWN_BY_EDITOR", ctx)


@bp.route("/offers/<offerId>/accept", methods=["POST"])
def accept_offer(offerId):
    ctx = guard("ContractsManager")
    parse_body([])
    offer = get_scoped("offers", offerId, ctx)
    if offer["status"] not in LIVE_OFFER:
        fail(ERR_STATE, 409, "offer is not live")
    sub = DB["submissions"][offer["submission_id"]]
    rnd = DB["submission_rounds"][sub["submission_round_id"]]
    if ctx.uid == rnd["agent_id"]:
        fail(ERR_SOD, 403,
             "the round's agent may not accept an offer on that round")
    if rnd["auction_mode"] and offer["auction_rank"] != 1:
        fail(ERR_NOT_TOP, 409, "only the rank-1 offer may be accepted")
    agency = DB["agencies"].get(offer["agency_id"])
    period = agency["period_index"] if agency else None

    offer["status"] = "ACCEPTED"
    touch(offer)

    # Award cascade, link 1: create the Deal.
    agreement = signed_agreement_for_manuscript(rnd["manuscript_id"])
    deal = new_record()
    deal.update({
        "agency_id": offer["agency_id"],
        "offer_id": offer["id"],
        "submission_id": offer["submission_id"],
        "client_agreement_id": agreement["id"] if agreement else None,
        "advance_cents": offer["advance_cents"],
        "royalty_basis": offer["royalty_basis"],
        "retains_film_rights": not offer["includes_film_rights"],
        "retains_foreign_rights": not offer["includes_foreign_rights"],
        "retains_audio_rights": not offer["includes_audio_rights"],
        "advance_earned_out_cents": 0,
        "executed_period_index": None,
        "status": "NEGOTIATING",
    })
    DB["deals"][deal["id"]] = deal

    # Award cascade, link 2: supersede losing offers; their submissions pass.
    for other in offers_of_round(rnd["id"]):
        if other["id"] == offer["id"] or other["status"] not in LIVE_OFFER:
            continue
        other["status"] = "SUPERSEDED"
        touch(other)
        osub = DB["submissions"].get(other["submission_id"])
        if osub is not None and osub["status"] == "OFFER_EXTENDED":
            osub["status"] = "PASSED"
            osub["response_period_index"] = period
            touch(osub)

    # Fan-out: remaining live submissions in the round withdraw.
    for s in subs_of_round(rnd["id"]):
        if s["id"] == sub["id"]:
            continue
        if s["status"] in ("QUEUED", "SENT", "UNDER_CONSIDERATION"):
            s["status"] = "WITHDRAWN"
            touch(s)

    recompute_auction_ranks(rnd)
    return success(public(offer))


# -------------------------------------------------------------------- deals ----
@bp.route("/deals/<dealId>", methods=["GET"])
def get_deal(dealId):
    ctx = guard(*ALL)
    return success(public(get_scoped("deals", dealId, ctx)))


@bp.route("/deals", methods=["GET"])
def list_deals():
    ctx = guard(*ALL)
    return list_response("deals", ctx, {
        "agency_id": "str", "status": "str", "offer_id": "str",
        "submission_id": "str", "client_agreement_id": "str",
    })


@bp.route("/deals/<dealId>", methods=["PATCH"])
def patch_deal(dealId):
    ctx = guard("ContractsManager")
    data = parse_body([
        F("advance_cents", "int", lo=0),
        F("retains_film_rights", "bool"),
        F("retains_foreign_rights", "bool"),
        F("retains_audio_rights", "bool"),
    ])
    deal = get_scoped("deals", dealId, ctx)
    if deal["status"] != "NEGOTIATING":
        fail(ERR_STATE, 409, "deal is not NEGOTIATING")
    for name in ("advance_cents", "retains_film_rights",
                 "retains_foreign_rights", "retains_audio_rights"):
        if data[name] is not None:
            deal[name] = data[name]
    touch(deal)
    return success(public(deal))


@bp.route("/deals/<dealId>/execute", methods=["POST"])
def execute_deal(dealId):
    ctx = guard("ContractsManager")
    data = parse_body([F("expected_deal_version", "int", required=True, lo=0)])
    deal = get_scoped("deals", dealId, ctx)
    if data["expected_deal_version"] != deal["version"]:
        fail(ERR_STALE, 412, "expected_deal_version is stale")
    if deal["status"] != "NEGOTIATING":
        fail(ERR_STATE, 409, "deal is not NEGOTIATING")
    rnd = round_of_offer(DB["offers"][deal["offer_id"]])
    if ctx.uid == rnd["agent_id"]:
        fail(ERR_SOD, 403,
             "the round's agent may not execute the resulting deal")
    agency = DB["agencies"].get(deal["agency_id"])
    executed = agency["period_index"]
    deal["status"] = "EXECUTED"
    deal["executed_period_index"] = executed
    touch(deal)
    # Advance waterfall: pinned floor-then-remainder order.
    for milestone, amount, offset in advance_waterfall(deal["advance_cents"]):
        inst = new_record()
        inst.update({
            "agency_id": deal["agency_id"],
            "deal_id": deal["id"],
            "milestone": milestone,
            "amount_cents": amount,
            "due_period_index": executed + offset,
            "paid_period_index": None,
            "agency_commission_cents": None,
            "status": "SCHEDULED",
        })
        DB["advance_installments"][inst["id"]] = inst
    winning = DB["submissions"].get(deal["submission_id"])
    if winning is not None and winning["status"] == "OFFER_EXTENDED":
        winning["status"] = "WITHDRAWN"
        touch(winning)
    return success(public(deal))


@bp.route("/deals/<dealId>/terminate", methods=["POST"])
def terminate_deal(dealId):
    ctx = guard("ContractsManager")
    parse_body([])
    deal = get_scoped("deals", dealId, ctx)
    if deal["status"] not in ("EXECUTED", "ACTIVE"):
        fail(ERR_STATE, 409, "deal is not EXECUTED or ACTIVE")
    if any(s for s in DB["royalty_statements"].values()
           if s["deal_id"] == deal["id"]
           and s["status"] in ("RECEIVED", "AUDIT_OPEN")):
        fail(ERR_STMT_UNRESOLVED, 409,
             "unresolved royalty statements block termination")
    deal["status"] = "TERMINATED"
    touch(deal)
    for inst in DB["advance_installments"].values():
        if inst["deal_id"] == deal["id"] and inst["status"] in ("SCHEDULED",
                                                                "DUE"):
            inst["status"] = "WAIVED"
            touch(inst)
    return success(public(deal))
