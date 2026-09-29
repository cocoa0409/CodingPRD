"""Cancellation events: refunds, insurance and rescheduling (PRD 3.9)."""

from datetime import timedelta

from flask import Blueprint

import calc
import common
import recompute
import serializers as ser
import store
import validation as v
from envelope import created, list_response, object_response
from errors import ApiError
from store import db, new_entity

bp = Blueprint("cancellations", __name__)

CANCEL_FROM_STATUSES = ("PLANNED", "CONFIRMED", "ON_SALE")
POSTPONE_FROM_STATUSES = ("CONFIRMED", "ON_SALE")
WITHDRAWABLE_OFFER_STATUSES = ("DRAFT", "SUBMITTED", "COUNTERED")


@bp.post("/cancellation-events")
def create_event():
    common.auth("TalentBuyer", "RiskOfficer")
    body = v.get_body()
    show_id = v.req_str(body, "show_id")
    kind = v.req_enum(body, "kind", ("CANCELLED", "POSTPONED"))
    reason = v.req_str(body, "reason", max_len=200)

    show = common.get_show(show_id)
    if show["show_status"] in common.TERMINAL_SHOW_STATUS:
        common.already_terminal(show["show_status"])
    if store.events_of_show(show_id):
        common.invalid_state("the show already carries a cancellation event")
    allowed = (CANCEL_FROM_STATUSES if kind == "CANCELLED"
               else POSTPONE_FROM_STATUSES)
    common.require(show["show_status"] in allowed,
                   "a %s event may not be opened from %s"
                   % (kind, show["show_status"]))

    refund_liability = show["gross_sold_cents"] + show["transferred_in_gross_cents"]
    event = new_entity(
        show_id=show_id,
        replacement_show_id=None,
        kind=kind,
        reason=reason,
        status="OPENED",
        occurred_at=store.now(),
        refund_liability_cents=refund_liability,
        refunded_ticket_count=0,
        unrecovered_cost_cents=0,
        claim_amount_cents=None,
        covered_loss_cents=0,
        insurance_recovery_cents=0,
        claim_documentation_ref=None,
        insurer_reference=None,
        filed_by_user_id=None,
    )
    db.cancellation_events[event["id"]] = event

    show["refund_liability_cents"] = refund_liability
    show["sales_status"] = "CLOSED"
    for tier in store.tiers_of_show(show_id):
        if tier["status"] != "CLOSED":
            tier["status"] = "CLOSED"
            recompute.recompute_tier(tier)
            store.touch(tier)

    if kind == "CANCELLED":
        show["show_status"] = "CANCELLED"
        for line in store.lines_of_show(show_id):
            if line["status"] == "ACTIVE":
                line["status"] = "VOID"
                store.touch(line)
        for offer in store.offers_of_show(show_id):
            if offer["status"] in WITHDRAWABLE_OFFER_STATUSES:
                offer["status"] = "WITHDRAWN"
                store.touch(offer)
    else:
        show["show_status"] = "POSTPONED"

    artist = common.artist_of(show)
    if artist is not None:
        recompute.recompute_artist(artist)
    recompute.cascade(show, bump_show=True, bump_market=True)
    show["refund_liability_cents"] = refund_liability
    return created(ser.cancellation_event_json(event))


@bp.get("/cancellation-events/<cancellation_event_id>")
def read_event(cancellation_event_id):
    common.auth(*common.ALL_ROLES)
    event = common.get_event(cancellation_event_id)
    return object_response(ser.cancellation_event_json(event))


@bp.get("/cancellation-events")
def list_events():
    common.auth(*common.ALL_ROLES)
    show_id = common.filter_fk("show_id", common.get_show)
    replacement_show_id = common.filter_fk("replacement_show_id", common.get_show)
    kind = common.filter_arg("kind")
    status = common.filter_arg("status")
    rows = []
    for event in db.cancellation_events.values():
        if show_id is not None and event["show_id"] != show_id:
            continue
        if (replacement_show_id is not None
                and event["replacement_show_id"] != replacement_show_id):
            continue
        if kind is not None and event["kind"] != kind:
            continue
        if status is not None and event["status"] != status:
            continue
        rows.append(event)
    page, limit, offset, total = common.listing(rows, ser.cancellation_event_json)
    return list_response(page, limit, offset, total)


@bp.post("/cancellation-events/<cancellation_event_id>/process-refunds")
def process_refunds(cancellation_event_id):
    common.auth("TourAccountant")
    v.get_body()
    event = common.get_event(cancellation_event_id)
    common.state_guard(event["status"], ("OPENED",), common.TERMINAL_EVENT)
    show = common.get_show(event["show_id"])
    common.require(show["show_status"] in ("CANCELLED", "POSTPONED"),
                   "the show has not been pulled")

    unrecovered = sum(l["settlement_expense_cents"]
                      for l in store.lines_of_show(show["id"])
                      if l["status"] in ("ACTIVE", "VOID"))
    offer = store.accepted_offer(show["id"])
    if offer is not None:
        unrecovered += offer["deposit_cents"]

    event["status"] = "REFUNDS_PROCESSED"
    event["refund_liability_cents"] = show["refund_liability_cents"]
    event["refunded_ticket_count"] = (show["paid_tickets_sold"]
                                     + show["transferred_in_paid_tickets"])
    event["unrecovered_cost_cents"] = unrecovered
    store.touch(event)

    show["_refunds_processed"] = True
    refund_liability = show["refund_liability_cents"]
    recompute.cascade(show, bump_show=True, bump_market=False)
    show["refund_liability_cents"] = refund_liability
    return object_response(ser.cancellation_event_json(event))


@bp.post("/cancellation-events/<cancellation_event_id>/file-claim")
def file_claim(cancellation_event_id):
    user_id, _role = common.auth("RiskOfficer")
    body = v.get_body()
    claim_amount = v.req_cents(body, "claim_amount_cents", minimum=1)
    documentation_ref = v.req_str(body, "claim_documentation_ref", max_len=64)

    event = common.get_event(cancellation_event_id)
    common.state_guard(event["status"], ("REFUNDS_PROCESSED",),
                       common.TERMINAL_EVENT)

    deadline = event["occurred_at"] + timedelta(days=calc.INSURANCE_CLAIM_WINDOW_DAYS)
    if store.now() > deadline:
        raise ApiError("ERR_CLAIM_WINDOW_CLOSED",
                       "the 30 day insurance filing window has closed")

    event["status"] = "CLAIM_FILED"
    event["claim_amount_cents"] = claim_amount
    event["claim_documentation_ref"] = documentation_ref
    event["filed_by_user_id"] = user_id
    store.touch(event)
    return object_response(ser.cancellation_event_json(event))


@bp.post("/cancellation-events/<cancellation_event_id>/settle-claim")
def settle_claim(cancellation_event_id):
    user_id, _role = common.auth("RiskOfficer")
    body = v.get_body()
    outcome = v.req_enum(body, "outcome", ("SETTLE", "DENY"))
    insurer_reference = None
    if outcome == "SETTLE":
        insurer_reference = v.req_str(body, "insurer_reference", max_len=120)
    else:
        v.req_str(body, "reason", max_len=500)

    event = common.get_event(cancellation_event_id)
    common.state_guard(event["status"], ("CLAIM_FILED",), common.TERMINAL_EVENT)
    common.require_different_actor(
        user_id, event["filed_by_user_id"],
        "the settling officer must differ from the filing officer")

    if outcome == "SETTLE":
        covered, recovery = calc.insurance_amounts(
            event["claim_amount_cents"] or 0, event["unrecovered_cost_cents"])
        event["status"] = "CLAIM_SETTLED"
        event["covered_loss_cents"] = covered
        event["insurance_recovery_cents"] = recovery
        event["insurer_reference"] = insurer_reference
        store.touch(event)
        show = common.get_show(event["show_id"])
        market = common.market_of(show)
        if market is not None:
            recompute.recompute_market(market)
            store.touch(market)
        return object_response(ser.cancellation_event_json(event))

    event["status"] = "CLAIM_DENIED"
    event["covered_loss_cents"] = 0
    event["insurance_recovery_cents"] = 0
    store.touch(event)
    return object_response(ser.cancellation_event_json(event))


@bp.post("/cancellation-events/<cancellation_event_id>/reschedule")
def reschedule(cancellation_event_id):
    common.auth("TalentBuyer")
    body = v.get_body()
    replacement_show_id = v.req_str(body, "replacement_show_id")

    event = common.get_event(cancellation_event_id)
    replacement = common.get_show(replacement_show_id)
    common.state_guard(event["status"], ("OPENED",), common.TERMINAL_EVENT)
    common.require(event["kind"] == "POSTPONED",
                   "only a postponed date may be rescheduled")
    original = common.get_show(event["show_id"])
    common.require(original["show_status"] == "POSTPONED",
                   "the original show is not POSTPONED")

    if (replacement["id"] == original["id"]
            or replacement["rescheduled_from_show_id"] != original["id"]
            or replacement["show_status"] != "PLANNED"):
        raise ApiError("ERR_REPLACEMENT_SHOW_INVALID",
                       "the replacement show does not point back at the original")

    event["status"] = "RESCHEDULED"
    event["replacement_show_id"] = replacement["id"]
    event["refund_liability_cents"] = 0
    store.touch(event)

    replacement["transferred_in_gross_cents"] += original["gross_sold_cents"]
    replacement["transferred_in_paid_tickets"] += original["paid_tickets_sold"]
    original["show_status"] = "RESCHEDULED"
    original["refund_liability_cents"] = 0

    recompute.recompute_show(original)
    original["refund_liability_cents"] = 0
    store.touch(original)
    recompute.recompute_show(replacement)
    store.touch(replacement)
    market = common.market_of(original)
    if market is not None:
        recompute.recompute_market(market)
        store.touch(market)
    replacement_market = common.market_of(replacement)
    if replacement_market is not None and replacement_market is not market:
        recompute.recompute_market(replacement_market)
    return object_response(ser.cancellation_event_json(event))
