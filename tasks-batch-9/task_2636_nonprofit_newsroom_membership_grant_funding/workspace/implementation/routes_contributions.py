"""The contribution ledger: two independent dimensions (§3.9)."""

from flask import Blueprint

import calc
import derive
import guards
from core import (
    DB, ROLE_BOARD_OVERSIGHT, ROLE_DEVELOPMENT_OFFICER, ROLE_FINANCE_CONTROLLER,
    ROLE_MEMBER, apply_changes, authenticate, body, fail, is_member_caller, iso_date,
    iso_ms, list_response, lookup, lookup_fk, member_scope, new_row,
    next_receipt_number, now_clock, object_response, pagination, paginate,
    parse_date, public, q_enum, q_str, rows, v_bool, v_date, v_enum, v_int, v_str,
)

bp = Blueprint("contributions", __name__)

CONTRIBUTION_READ_ROLES = (ROLE_DEVELOPMENT_OFFICER, ROLE_FINANCE_CONTROLLER,
                           ROLE_BOARD_OVERSIGHT, ROLE_MEMBER)

# Which source keys each stream requires and forbids (§3.9).
STREAM_REQUIRES = {
    "MEMBERSHIP": ("member_id",),
    "MAJOR_GIFT": ("funder_id",),
    "SYNDICATION": ("collaboration_id",),
    "EVENTS": (),
}
STREAM_FORBIDS = {
    "MEMBERSHIP": ("funder_id",),
    "MAJOR_GIFT": ("member_id",),
    "SYNDICATION": (),
    "EVENTS": ("gift_offer_id",),
}


def get_contribution(contribution_id):
    return lookup("contributions", contribution_id, "ERR_CONTRIBUTION_NOT_FOUND")


def member_tier(member):
    if member is None:
        return None
    return DB["membership_tiers"].get(member.get("tier_id"))


@bp.post("/contributions")
def create_contribution():
    authenticate(ROLE_DEVELOPMENT_OFFICER, ROLE_MEMBER)
    data = body()
    period = lookup_fk("fiscal_periods", data.get("fiscal_period_id"),
                       "ERR_FISCAL_PERIOD_NOT_FOUND")
    if period is None:
        fail("ERR_INVALID_REQUEST", "fiscal_period_id is required")
    member = lookup_fk("members", data.get("member_id"), "ERR_MEMBER_NOT_FOUND")
    funder = lookup_fk("funders", data.get("funder_id"), "ERR_FUNDER_NOT_FOUND")
    offer = lookup_fk("gift_offers", data.get("gift_offer_id"),
                      "ERR_GIFT_OFFER_NOT_FOUND")
    collaboration = lookup_fk("collaborations", data.get("collaboration_id"),
                              "ERR_COLLABORATION_NOT_FOUND")
    if is_member_caller():
        member_scope(member["id"] if member else None)

    revenue_stream = v_enum(data, "revenue_stream", calc.REVENUE_STREAMS)
    amount_cents = v_int(data, "amount_cents", minimum=1)
    received_date = v_date(data, "received_date")
    source_label = v_str(data, "source_label", required=False, default=None, min_len=0)
    start = parse_date(period["start_date"])
    end = parse_date(period["end_date"])
    if start is not None and end is not None and not (start <= received_date <= end):
        fail("ERR_INVALID_REQUEST",
             "received_date must fall inside the fiscal period's date range")

    guards.require_period_open(period)
    if revenue_stream == "MEMBERSHIP" and member is not None:
        if member["status"] not in ("PENDING", "ACTIVE", "GRACE"):
            fail("ERR_MEMBER_NOT_ACTIVE", "the member is %s" % member["status"])
    if funder is not None:
        guards.require_funder_not_restricted(funder)

    supplied = {
        "member_id": member["id"] if member else None,
        "funder_id": funder["id"] if funder else None,
        "gift_offer_id": offer["id"] if offer else None,
        "collaboration_id": collaboration["id"] if collaboration else None,
    }
    for key in STREAM_REQUIRES[revenue_stream]:
        if supplied[key] is None:
            fail("ERR_STREAM_SOURCE_MISMATCH",
                 "a %s contribution requires %s" % (revenue_stream, key))
    for key in STREAM_FORBIDS[revenue_stream]:
        if supplied[key] is not None:
            fail("ERR_STREAM_SOURCE_MISMATCH",
                 "a %s contribution may not carry %s" % (revenue_stream, key))

    tier = member_tier(member)
    if revenue_stream == "MEMBERSHIP" and tier is not None:
        if amount_cents < int(tier["contribution_amount_cents"]):
            fail("ERR_CONTRIBUTION_BELOW_TIER_MINIMUM",
                 "the tier requires at least %s cents"
                 % tier["contribution_amount_cents"])

    qpq, deductible = calc.contribution_deductible_split(revenue_stream, amount_cents,
                                                         tier)
    contribution = new_row("contributions", {
        "fiscal_period_id": period["id"],
        "member_id": supplied["member_id"],
        "funder_id": supplied["funder_id"],
        "gift_offer_id": supplied["gift_offer_id"],
        "collaboration_id": supplied["collaboration_id"],
        "revenue_stream": revenue_stream,
        "amount_cents": amount_cents,
        "received_date": iso_date(received_date),
        "source_label": source_label,
        "settlement_status": "INITIATED",
        "acknowledgment_status": "UNACKNOWLEDGED",
        "quid_pro_quo_cents": qpq,
        "deductible_cents": deductible,
        "receipt_number": None,
        "refunded_at": None,
    })
    return object_response(public(contribution), 201)


@bp.get("/contributions/<contribution_id>")
def read_contribution(contribution_id):
    authenticate(*CONTRIBUTION_READ_ROLES)
    contribution = get_contribution(contribution_id)
    member_scope(contribution.get("member_id"))
    return object_response(public(contribution))


@bp.get("/contributions")
def list_contributions():
    authenticate(ROLE_DEVELOPMENT_OFFICER, ROLE_FINANCE_CONTROLLER,
                 ROLE_BOARD_OVERSIGHT)
    period_id = q_str("fiscal_period_id")
    member_id = q_str("member_id")
    funder_id = q_str("funder_id")
    offer_id = q_str("gift_offer_id")
    collaboration_id = q_str("collaboration_id")
    revenue_stream = q_enum("revenue_stream", calc.REVENUE_STREAMS)
    settlement_status = q_enum("settlement_status", calc.SETTLEMENT_STATUSES)
    acknowledgment_status = q_enum("acknowledgment_status", calc.ACK_STATUSES)
    limit, offset = pagination()
    items = []
    for contribution in rows("contributions"):
        if period_id is not None and contribution["fiscal_period_id"] != period_id:
            continue
        if member_id is not None and contribution["member_id"] != member_id:
            continue
        if funder_id is not None and contribution["funder_id"] != funder_id:
            continue
        if offer_id is not None and contribution["gift_offer_id"] != offer_id:
            continue
        if collaboration_id is not None and contribution["collaboration_id"] != collaboration_id:
            continue
        if revenue_stream is not None and contribution["revenue_stream"] != revenue_stream:
            continue
        if settlement_status is not None and contribution["settlement_status"] != settlement_status:
            continue
        if acknowledgment_status is not None and contribution["acknowledgment_status"] != acknowledgment_status:
            continue
        items.append(contribution)
    items.sort(key=lambda c: (c["received_date"], c["_seq"]))
    page, total = paginate(items, limit, offset)
    return list_response([public(c) for c in page], total, limit, offset)


@bp.post("/contributions/<contribution_id>/settlement")
def settle_contribution(contribution_id):
    authenticate(ROLE_FINANCE_CONTROLLER)
    contribution = get_contribution(contribution_id)
    data = body()
    outcome = v_enum(data, "outcome", ("SETTLED", "FAILED"))
    period = DB["fiscal_periods"].get(contribution["fiscal_period_id"])

    guards.require_period_open(period)
    guards.require_not_terminal(contribution["settlement_status"],
                                calc.SETTLEMENT_TERMINAL, "contribution")
    guards.require_state(contribution["settlement_status"], ("INITIATED",),
                         "contribution")

    if outcome == "FAILED":
        apply_changes(contribution, {"settlement_status": "FAILED"}, force=True)
        return object_response(public(contribution))

    apply_changes(contribution, {"settlement_status": "SETTLED"}, force=True)
    if contribution["revenue_stream"] == "MEMBERSHIP":
        member = DB["members"].get(contribution["member_id"])
        if member is not None:
            extra = {}
            tier = member_tier(member)
            if member["status"] == "PENDING" and tier is not None:
                extra["status"] = "ACTIVE"
                extra.update(derive.member_schedule_changes(
                    member, tier, parse_date(contribution["received_date"]),
                    status="ACTIVE"))
            derive.recompute_member_giving(member, extra)
    elif contribution["revenue_stream"] == "MAJOR_GIFT":
        funder = DB["funders"].get(contribution["funder_id"])
        if funder is not None:
            derive.recompute_funder(funder)
    elif contribution["revenue_stream"] == "SYNDICATION":
        collaboration = DB["collaborations"].get(contribution["collaboration_id"])
        if collaboration is not None:
            derive.recompute_collaboration_counts(collaboration)
    if period is not None:
        derive.recompute_period(period)
    return object_response(public(contribution))


@bp.post("/contributions/<contribution_id>/refund")
def refund_contribution(contribution_id):
    authenticate(ROLE_FINANCE_CONTROLLER)
    contribution = get_contribution(contribution_id)
    data = body()
    v_str(data, "refund_reason", required=False, default=None, min_len=0)
    period = DB["fiscal_periods"].get(contribution["fiscal_period_id"])

    guards.require_period_open(period)
    guards.require_not_terminal(contribution["settlement_status"],
                                calc.SETTLEMENT_TERMINAL, "contribution")
    guards.require_state(contribution["settlement_status"], ("SETTLED",),
                         "contribution")
    if contribution["acknowledgment_status"] not in ("UNACKNOWLEDGED", "RECEIPTED"):
        fail("ERR_REFUND_WINDOW_CLOSED",
             "a DISCLOSED contribution has entered transparency reporting")

    apply_changes(contribution, {
        "settlement_status": "REFUNDED",
        "refunded_at": iso_ms(now_clock()),
    }, force=True)
    member = DB["members"].get(contribution.get("member_id"))
    if member is not None:
        derive.recompute_member_giving(member)
    funder_id = (member.get("linked_funder_id") if member is not None
                 else contribution.get("funder_id"))
    funder = DB["funders"].get(funder_id) if funder_id else None
    if funder is not None:
        derive.recompute_funder(funder)
    if contribution["revenue_stream"] == "SYNDICATION":
        collaboration = DB["collaborations"].get(contribution["collaboration_id"])
        if collaboration is not None:
            derive.recompute_collaboration_counts(collaboration)
    if period is not None:
        derive.recompute_period(period)
    return object_response(public(contribution))


@bp.post("/contributions/<contribution_id>/acknowledge")
def acknowledge_contribution(contribution_id):
    authenticate(ROLE_DEVELOPMENT_OFFICER)
    contribution = get_contribution(contribution_id)
    data = body()
    disclose_publicly = v_bool(data, "disclose_publicly")

    guards.require_not_terminal(contribution["acknowledgment_status"], ("DISCLOSED",),
                                "contribution acknowledgment")
    if not disclose_publicly:
        guards.require_state(contribution["acknowledgment_status"],
                             ("UNACKNOWLEDGED",), "contribution acknowledgment")
        if contribution["settlement_status"] == "FAILED":
            fail("ERR_INVALID_STATE", "a FAILED contribution cannot be receipted")
        apply_changes(contribution, {
            "acknowledgment_status": "RECEIPTED",
            "receipt_number": next_receipt_number(),
        }, force=True)
        return object_response(public(contribution))

    guards.require_state(contribution["acknowledgment_status"], ("RECEIPTED",),
                         "contribution acknowledgment")
    if contribution["settlement_status"] != "SETTLED":
        fail("ERR_INVALID_STATE",
             "only a SETTLED contribution may be published")
    if contribution["revenue_stream"] == "MAJOR_GIFT":
        offer = DB["gift_offers"].get(contribution.get("gift_offer_id"))
        if offer is not None and calc.is_designated(offer["designation"]):
            guards.require_active_disclosure(offer["funder_id"],
                                             offer["coverage_area_id"])
    apply_changes(contribution, {"acknowledgment_status": "DISCLOSED"}, force=True)
    return object_response(public(contribution))
