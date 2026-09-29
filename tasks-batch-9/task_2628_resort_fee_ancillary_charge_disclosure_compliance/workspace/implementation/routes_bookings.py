"""Bookings, folios and the immutable folio-line ledger (PRD 3.4, 3.5)."""

import datetime as dt

from flask import Blueprint

import auth
import calc
import clock
import derive
import envelope
import resolve
import serialize
import shape
import store
from errors import ApiError

bp = Blueprint("bookings", __name__)

STAY_STATUSES = ("QUOTED", "CONFIRMED", "IN_HOUSE", "CHECKED_OUT")
DISCLOSURE_STATUSES = ("PENDING_AUDIT", "DISCLOSED", "DISPUTED",
                       "UNDISCLOSED_CONFIRMED", "CURED")
FOLIO_STATUSES = ("OPEN", "ITEMIZED", "POSTED", "ADJUSTED", "CLOSED")
LINE_TYPES = ("ROOM", "MANDATORY_FEE", "OPTIONAL_FEE", "FEE_CREDIT", "FEE_REBILL",
              "COMPLAINT_REFUND")
VARIANCE_TOLERANCE_CENTS = 100
ROOM_LINE_DESCRIPTION = "Room charge"


def _guest_scope(user_id, role, booking_id):
    """Rank 5 — the addressed resource must resolve to the acting booking."""
    if role != auth.GUEST:
        return
    auth.acting_booking(user_id)
    if booking_id is not None:
        auth.booking_owns(user_id, booking_id)


# ------------------------------------------------------------------- bookings

@bp.post("/bookings")
def create_booking():
    user_id, role = auth.require([auth.CHANNEL_OPERATOR, auth.GUEST_SERVICES_AGENT])
    if role == auth.CHANNEL_OPERATOR:
        auth.channel_owns(user_id, shape.peek_body().get("channel_id"))

    payload = shape.body()
    property_id = shape.identifier(payload, "property_id")
    channel_id = shape.identifier(payload, "channel_id")
    profile_id = shape.identifier(payload, "channel_disclosure_profile_id")
    arrival_date = shape.timestamp(payload, "arrival_date")
    nights = shape.integer(payload, "nights", minimum=1, maximum=30)
    guests = shape.integer(payload, "guests", minimum=1, maximum=8)
    room_rate_cents = shape.integer(payload, "room_rate_cents", minimum=0)
    disclosed_fee_amounts = shape.cents_map(payload, "disclosed_fee_amounts")

    prop = resolve.property_(property_id)
    channel = resolve.channel(channel_id)
    profile = resolve.profile(profile_id)

    if profile["channel_id"] != channel["id"]:
        raise ApiError("ERR_INVALID_REQUEST",
                       "channel_id must be the disclosure profile's own channel.")

    # rank 15 — only a live path can take a booking
    if profile["status"] not in ("DEPLOYED", "REMEDIATED"):
        raise ApiError("ERR_PROFILE_NOT_BOOKABLE",
                       "The disclosure profile is not in a bookable status.")

    program = store.fee_programs.get(profile["fee_program_id"])
    jurisdiction = store.jurisdictions.get(prop["jurisdiction_id"])

    # rank 23 — every fee code of the pinned program needs a taxability rule
    for fee in store.fees_of_program(program["id"]):
        if store.taxability_rule(prop["jurisdiction_id"], fee["code"]) is None:
            raise ApiError("ERR_TAXABILITY_RULE_MISSING",
                           "No taxability rule for fee code %s." % fee["code"])

    figures = calc.quote_figures(prop, jurisdiction, program, room_rate_cents, guests,
                                nights, disclosed_fee_amounts)

    row = {
        "property_id": prop["id"],
        "channel_id": channel["id"],
        "channel_disclosure_profile_id": profile["id"],
        "fee_program_id": program["id"],
        "arrival_date": arrival_date,
        "nights": nights,
        "guests": guests,
        "room_rate_cents": room_rate_cents,
        "disclosed_fee_amounts": disclosed_fee_amounts,
        "folio_fee_total_cents": 0,
        "folio_total_cents": 0,
        "quote_folio_variance_cents": 0,
        "guest_out_of_pocket_cents": 0,
        "stay_status": "QUOTED",
        "disclosure_status": "PENDING_AUDIT",
    }
    row.update(figures)
    store.stamp_new(row)
    store.bookings[row["id"]] = row
    return envelope.created(serialize.booking(row))


@bp.get("/bookings/<identifier>")
def read_booking(identifier):
    user_id, role = auth.require(auth.ALL_ROLES)
    existing = resolve.peek("booking", identifier)
    if role == auth.CHANNEL_OPERATOR:
        auth.acting_channel(user_id)
        if existing is not None:
            auth.channel_owns(user_id, existing["channel_id"])
    if role == auth.GUEST:
        _guest_scope(user_id, role, existing["id"] if existing is not None else None)
    return envelope.ok(serialize.booking(resolve.booking(identifier)))


@bp.get("/bookings")
def list_bookings():
    auth.require(auth.ALL_ROLES)
    rows = envelope.apply_filters(
        store.sort_default(store.bookings.values()),
        [("property_id", envelope.str_filter("property_id")),
         ("channel_id", envelope.str_filter("channel_id")),
         ("channel_disclosure_profile_id",
          envelope.str_filter("channel_disclosure_profile_id")),
         ("fee_program_id", envelope.str_filter("fee_program_id")),
         ("stay_status", envelope.str_filter("stay_status")),
         ("disclosure_status", envelope.str_filter("disclosure_status"))],
    )
    return envelope.page(rows, serialize.booking)


@bp.post("/bookings/<identifier>/confirm")
def confirm_booking(identifier):
    auth.require([auth.CHANNEL_OPERATOR, auth.GUEST_SERVICES_AGENT])
    booking = resolve.booking(identifier)

    if booking["stay_status"] != "QUOTED":
        raise ApiError("ERR_INVALID_STATE", "Only a QUOTED booking may be confirmed.")

    program = store.fee_programs.get(booking["fee_program_id"])
    profile = store.profiles.get(booking["channel_disclosure_profile_id"])
    if program is None or program["status"] != "PUBLISHED":
        raise ApiError("ERR_FEE_PROGRAM_NOT_PUBLISHED",
                       "The pinned fee program is no longer PUBLISHED.")
    if profile is None or profile["status"] not in ("DEPLOYED", "REMEDIATED"):
        raise ApiError("ERR_PROFILE_NOT_BOOKABLE",
                       "The booking path is no longer bookable.")

    booking["stay_status"] = "CONFIRMED"
    if (profile["first_quote_shows_total"]
            and profile["disclosure_placement"] in ("FIRST_QUOTE", "RATE_DETAILS")
            and booking["quote_disclosure_gap_cents"] == 0
            and booking["disclosure_status"] == "PENDING_AUDIT"):
        booking["disclosure_status"] = "DISCLOSED"
    store.touch(booking)
    return envelope.ok(serialize.booking(booking))


@bp.post("/bookings/<identifier>/check-in")
def check_in(identifier):
    auth.require([auth.GUEST_SERVICES_AGENT])
    booking = resolve.booking(identifier)

    if booking["stay_status"] != "CONFIRMED":
        raise ApiError("ERR_INVALID_STATE", "Only a CONFIRMED booking may check in.")
    if clock.now() < booking["arrival_date"]:
        raise ApiError("ERR_ARRIVAL_NOT_REACHED",
                       "The logical clock has not reached the arrival date.")

    booking["stay_status"] = "IN_HOUSE"
    folio = {
        "booking_id": booking["id"],
        "status": "OPEN",
        "line_count": 0,
        "charges_subtotal_cents": 0,
        "credits_total_cents": 0,
        "tax_total_cents": 0,
        "folio_total_cents": 0,
        "itemization_complete": False,
        "posted_at": None,
    }
    store.stamp_new(folio)
    store.folios[folio["id"]] = folio
    store.touch(booking)
    return envelope.ok(serialize.booking(booking))


@bp.post("/bookings/<identifier>/check-out")
def check_out(identifier):
    auth.require([auth.GUEST_SERVICES_AGENT])
    booking = resolve.booking(identifier)

    if booking["stay_status"] != "IN_HOUSE":
        raise ApiError("ERR_INVALID_STATE", "Only an IN_HOUSE booking may check out.")
    departure = booking["arrival_date"] + dt.timedelta(days=booking["nights"])
    if clock.now() < departure:
        raise ApiError("ERR_DEPARTURE_NOT_REACHED",
                       "The logical clock has not reached the departure instant.")

    booking["stay_status"] = "CHECKED_OUT"
    store.touch(booking)
    return envelope.ok(serialize.booking(booking))


@bp.get("/bookings/<identifier>/folios")
def list_booking_folios(identifier):
    user_id, role = auth.require(auth.ALL_ROLES)
    if role == auth.GUEST:
        existing = resolve.peek("booking", identifier)
        _guest_scope(user_id, role, existing["id"] if existing is not None else None)
    booking = resolve.booking(identifier)
    rows = store.sort_default(store.folios_of_booking(booking["id"]))
    return envelope.page(rows, serialize.folio)


# --------------------------------------------------------------------- folios

@bp.get("/folios/<identifier>")
def read_folio(identifier):
    user_id, role = auth.require(auth.ALL_ROLES)
    if role == auth.GUEST:
        existing = resolve.peek("folio", identifier)
        _guest_scope(user_id, role, existing["booking_id"] if existing else None)
    return envelope.ok(serialize.folio(resolve.folio(identifier)))


@bp.get("/folios")
def list_folios():
    auth.require(auth.ALL_ROLES)
    rows = envelope.apply_filters(
        store.sort_default(store.folios.values()),
        [("booking_id", envelope.str_filter("booking_id")),
         ("status", envelope.str_filter("status"))],
    )
    return envelope.page(rows, serialize.folio)


@bp.post("/folios/<identifier>/itemize")
def itemize_folio(identifier):
    auth.require([auth.GUEST_SERVICES_AGENT])
    folio = resolve.folio(identifier)
    booking = store.bookings.get(folio["booking_id"])

    if folio["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", "Only an OPEN folio may be itemised.")
    if booking["stay_status"] not in ("IN_HOUSE", "CHECKED_OUT"):
        raise ApiError("ERR_INVALID_STATE",
                       "The booking must be IN_HOUSE or CHECKED_OUT to itemise.")

    prop = store.properties.get(booking["property_id"])
    jurisdiction = store.jurisdictions.get(prop["jurisdiction_id"])
    program = store.fee_programs.get(booking["fee_program_id"])
    jurisdiction_id = prop["jurisdiction_id"]

    for fee in store.fees_of_program(program["id"]):
        if store.taxability_rule(jurisdiction_id, fee["code"]) is None:
            raise ApiError("ERR_TAXABILITY_RULE_MISSING",
                           "No taxability rule for fee code %s." % fee["code"])

    room_amount = booking["room_rate_cents"] * booking["nights"]
    room_rate_bps = jurisdiction["occupancy_tax_rate_bps"]
    derive.append_line(
        folio, "ROOM", jurisdiction_id, ROOM_LINE_DESCRIPTION, room_amount,
        "TAXABLE", room_rate_bps, calc.rhu(calc.bps_of(room_amount, room_rate_bps)),
    )

    fee_subtotal = 0
    for fee in store.mandatory_fees_of_program(program["id"]):
        amount = calc.folio_line_amount(
            fee, booking["room_rate_cents"], booking["guests"], booking["nights"])
        fee_subtotal += amount
        if amount <= 0:
            # A mandatory fee that computes to 0 cents produces no folio line at all.
            continue
        rule = store.taxability_rule(jurisdiction_id, fee["code"])
        determination, taxed = calc.line_taxability(rule)
        rate_bps = calc.rule_rate_bps(rule, jurisdiction) if taxed else 0
        derive.append_line(
            folio, "MANDATORY_FEE", jurisdiction_id, fee["disclosure_text"], amount,
            determination, rate_bps, calc.rhu(calc.bps_of(amount, rate_bps)),
            fee_id=fee["id"], fee_code=fee["code"],
        )

    folio["status"] = "ITEMIZED"
    folio["itemization_complete"] = True
    derive.refresh_folio(folio)
    store.touch(folio)

    booking["folio_fee_total_cents"] = fee_subtotal
    derive.refresh_booking_money(booking, folio)
    booking["quote_folio_variance_cents"] = \
        folio["folio_total_cents"] - booking["quoted_total_cents"]

    disputed = False
    if abs(booking["quote_folio_variance_cents"]) > VARIANCE_TOLERANCE_CENTS \
            and booking["disclosure_status"] in ("PENDING_AUDIT", "DISCLOSED"):
        booking["disclosure_status"] = "DISPUTED"
        disputed = True
    store.touch(booking)
    if disputed:
        derive.recompute_property(prop)
    return envelope.ok(serialize.folio(folio))


@bp.post("/folios/<identifier>/post")
def post_folio(identifier):
    auth.require([auth.GUEST_SERVICES_AGENT])
    folio = resolve.folio(identifier)
    booking = store.bookings.get(folio["booking_id"])

    if folio["status"] == "ITEMIZED":
        if not folio["itemization_complete"]:
            raise ApiError("ERR_INVALID_STATE", "The folio is not fully itemised.")
    elif folio["status"] == "ADJUSTED":
        for request_row in store.opt_outs_of_booking(booking["id"]):
            if request_row["status"] == "REQUESTED":
                raise ApiError("ERR_INVALID_STATE",
                               "An undecided opt-out request blocks the re-post.")
    else:
        raise ApiError("ERR_INVALID_STATE",
                       "Only an ITEMIZED or ADJUSTED folio may be posted.")

    if booking["stay_status"] != "CHECKED_OUT":
        raise ApiError("ERR_BOOKING_NOT_CHECKED_OUT",
                       "The folio's booking is not CHECKED_OUT.")

    folio["status"] = "POSTED"
    folio["posted_at"] = clock.now()
    store.touch(folio)
    return envelope.ok(serialize.folio(folio))


@bp.post("/folios/<identifier>/close")
def close_folio(identifier):
    auth.require([auth.GUEST_SERVICES_AGENT])
    folio = resolve.folio(identifier)
    booking = store.bookings.get(folio["booking_id"])

    if folio["status"] != "POSTED":
        raise ApiError("ERR_INVALID_STATE", "Only a POSTED folio may be closed.")
    for complaint in store.complaints_of_booking(booking["id"]):
        if complaint["status"] in derive.LIVE_COMPLAINT_STATUSES:
            raise ApiError("ERR_INVALID_STATE", "A live complaint blocks the close.")

    folio["status"] = "CLOSED"
    for request_row in store.opt_outs_of_booking(booking["id"]):
        if request_row["status"] == "REQUESTED":
            request_row["status"] = "EXPIRED"
            request_row["decided_at"] = clock.now()
            store.touch(request_row)
    store.touch(folio)
    return envelope.ok(serialize.folio(folio))


# ---------------------------------------------------------------- folio lines

def _line_booking_id(line):
    folio = store.folios.get(line["folio_id"])
    return folio["booking_id"] if folio else None


@bp.get("/folio-lines/<identifier>")
def read_folio_line(identifier):
    user_id, role = auth.require(auth.ALL_ROLES)
    if role == auth.GUEST:
        existing = resolve.peek("folio_line", identifier)
        _guest_scope(user_id, role,
                     _line_booking_id(existing) if existing is not None else None)
    return envelope.ok(serialize.folio_line(resolve.folio_line(identifier)))


@bp.get("/folio-lines")
def list_folio_lines():
    user_id, role = auth.require(auth.ALL_ROLES)
    own_folio_ids = None
    if role == auth.GUEST:
        booking = auth.acting_booking(user_id)
        own_folio_ids = {f["id"] for f in store.folios_of_booking(booking["id"])}
        folio_filter = envelope.str_filter("folio_id")
        if isinstance(folio_filter, str):
            addressed = store.folios.get(folio_filter)
            if addressed is not None:
                auth.booking_owns(user_id, addressed["booking_id"])

    rows = envelope.apply_filters(
        store.folio_lines.values(),
        [("folio_id", envelope.str_filter("folio_id")),
         ("fee_id", envelope.str_filter("fee_id")),
         ("jurisdiction_id", envelope.str_filter("jurisdiction_id")),
         ("line_type", envelope.str_filter("line_type"))],
    )
    if own_folio_ids is not None:
        rows = [r for r in rows if r["folio_id"] in own_folio_ids]
    # Ordered by folio_id then sequence_no ascending (PRD 2.3).
    rows = sorted(rows, key=lambda r: (r["folio_id"], r["sequence_no"]))
    return envelope.page(rows, serialize.folio_line)
