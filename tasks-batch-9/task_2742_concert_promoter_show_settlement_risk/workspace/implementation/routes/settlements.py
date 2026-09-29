"""Settlements: calculation, artist response, payment and reopen (PRD 3.7, 3.8)."""

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

bp = Blueprint("settlements", __name__)

ZERO_MONEY = {field: 0 for field in ser.SETTLEMENT_MONEY_FIELDS}
UNRESOLVED_INVOICE_STATUSES = ("SUBMITTED", "VERIFIED", "DISPUTED")


@bp.post("/settlements")
def create_settlement():
    common.auth("TourAccountant")
    body = v.get_body()
    show_id = v.req_str(body, "show_id")
    show = common.get_show(show_id)

    for existing in store.settlements_of_show(show_id):
        if existing["status"] != "PAID":
            raise ApiError("ERR_SETTLEMENT_ALREADY_OPEN",
                           "a settlement is already open for this show")

    settlement = new_entity(
        show_id=show_id,
        status="DRAFT",
        deal_structure_applied=None,
        calculated_by_user_id=None,
        signed_by_user_id=None,
        paid_at=None,
        payment_method=None,
        payment_reference=None,
        dispute_reason=None,
        reopen_count=0,
        reopen_reason=None,
        **ZERO_MONEY
    )
    db.settlements[settlement["id"]] = settlement
    return created(ser.settlement_json(settlement))


@bp.get("/settlements/<settlement_id>")
def read_settlement(settlement_id):
    common.auth(*common.ALL_ROLES)
    settlement = common.get_settlement(settlement_id)
    return object_response(ser.settlement_json(settlement))


@bp.get("/settlements")
def list_settlements():
    common.auth(*common.ALL_ROLES)
    show_id = common.filter_fk("show_id", common.get_show)
    status = common.filter_arg("status")
    rows = []
    for settlement in db.settlements.values():
        if show_id is not None and settlement["show_id"] != show_id:
            continue
        if status is not None and settlement["status"] != status:
            continue
        rows.append(settlement)
    page, limit, offset, total = common.listing(rows, ser.settlement_json)
    return list_response(page, limit, offset, total)


@bp.post("/settlements/<settlement_id>/calculate")
def calculate_settlement(settlement_id):
    user_id, _role = common.auth("TourAccountant")
    v.get_body()
    settlement = common.get_settlement(settlement_id)
    common.state_guard(settlement["status"], ("DRAFT", "DISPUTED", "REOPENED"),
                       common.TERMINAL_SETTLEMENT)
    show = common.get_show(settlement["show_id"])
    common.require(show["show_status"] == "PERFORMED",
                   "the show has not been performed")
    accepted = [o for o in store.offers_of_show(show["id"])
                if o["status"] == "ACCEPTED"]
    common.require(len(accepted) == 1, "the show has no accepted offer")

    lines = store.lines_of_show(show["id"])
    if not lines:
        raise ApiError("ERR_NO_TICKET_TIERS", "the show has no budget lines")
    for invoice in store.invoices_of_show(show["id"]):
        if invoice["status"] in UNRESOLVED_INVOICE_STATUSES:
            raise ApiError("ERR_UNRESOLVED_INVOICES",
                           "every vendor invoice must be approved or rejected")
    participating = [l for l in lines if l["status"] != "VOID"]
    for line in participating:
        if line["variance_status"] == "PENDING_APPROVAL":
            raise ApiError("ERR_UNRESOLVED_VARIANCE",
                           "every budget variance must be decided")

    offer = accepted[0]
    venue = common.venue_of(show)
    artist = common.artist_of(show)
    gross = show["gross_sold_cents"] + show["transferred_in_gross_cents"]
    tickets = show["paid_tickets_sold"] + show["transferred_in_paid_tickets"]
    figures = calc.settlement_figures(show, venue, artist, offer, participating,
                                      gross, tickets, "settlement_expense_cents")

    settlement.update(figures)
    settlement["status"] = "CALCULATED"
    settlement["dispute_reason"] = None
    settlement["calculated_by_user_id"] = user_id
    store.touch(settlement)
    return object_response(ser.settlement_json(settlement))


@bp.post("/settlements/<settlement_id>/artist-response")
def artist_response(settlement_id):
    user_id, role = common.auth("ArtistRep")
    body = v.get_body()
    response = v.req_enum(body, "response", ("SIGN", "DISPUTE"))
    dispute_reason = None
    if response == "DISPUTE":
        dispute_reason = v.req_str(body, "dispute_reason", max_len=500)

    settlement = common.get_settlement(settlement_id)
    show = common.get_show(settlement["show_id"])
    common.require_show_owner(show, user_id, role)
    common.state_guard(settlement["status"], ("CALCULATED",),
                       common.TERMINAL_SETTLEMENT)

    if response == "SIGN":
        settlement["status"] = "ARTIST_SIGNED"
        settlement["signed_by_user_id"] = user_id
    else:
        settlement["status"] = "DISPUTED"
        settlement["dispute_reason"] = dispute_reason
        settlement["signed_by_user_id"] = None
    store.touch(settlement)
    return object_response(ser.settlement_json(settlement))


@bp.post("/settlements/<settlement_id>/pay")
def pay_settlement(settlement_id):
    user_id, _role = common.auth("TourAccountant")
    body = v.get_body()
    payment_method = v.req_enum(body, "payment_method", ("WIRE", "CHECK", "CASH"))
    payment_reference = v.req_str(body, "payment_reference", max_len=120)

    settlement = common.get_settlement(settlement_id)
    common.state_guard(settlement["status"], ("ARTIST_SIGNED",),
                       common.TERMINAL_SETTLEMENT)
    common.require_different_actor(
        user_id, settlement["signed_by_user_id"],
        "the payer must differ from the signer")
    if (payment_method == "CASH"
            and settlement["payment_due_cents"] > calc.CASH_PAYMENT_LIMIT_CENTS):
        raise ApiError("ERR_CASH_PAYMENT_LIMIT",
                       "cash payments are capped at 1,000,000 cents")

    settlement["status"] = "PAID"
    settlement["paid_at"] = store.now()
    settlement["payment_method"] = payment_method
    settlement["payment_reference"] = payment_reference
    store.touch(settlement)

    show = common.get_show(settlement["show_id"])
    if show["show_status"] == "PERFORMED":
        show["show_status"] = "SETTLED"
    for line in store.lines_of_show(show["id"]):
        if line["status"] == "ACTIVE":
            line["status"] = "SETTLED"
            store.touch(line)

    artist = common.artist_of(show)
    if artist is not None:
        recompute.recompute_artist(artist)
    recompute.cascade(show, bump_show=True, bump_market=True)
    return object_response(ser.settlement_json(settlement))


@bp.post("/settlements/<settlement_id>/reopen")
def reopen_settlement(settlement_id):
    user_id, _role = common.auth("RiskOfficer")
    body = v.get_body()
    reopen_reason = v.req_str(body, "reopen_reason", max_len=500)

    settlement = common.get_settlement(settlement_id)
    common.state_guard(settlement["status"], ("CALCULATED", "ARTIST_SIGNED"),
                       common.TERMINAL_SETTLEMENT)
    common.require_different_actor(
        user_id, settlement["calculated_by_user_id"],
        "the reopening officer must differ from the calculating accountant")

    settlement["status"] = "REOPENED"
    settlement["reopen_count"] += 1
    settlement["reopen_reason"] = reopen_reason
    settlement["signed_by_user_id"] = None
    store.touch(settlement)
    return object_response(ser.settlement_json(settlement))
