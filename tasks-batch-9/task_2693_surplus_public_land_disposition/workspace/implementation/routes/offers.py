"""Preference offers, the negotiation round log and the good-faith track
(PRD 3.6, 3.7).
"""

from flask import Blueprint, g, request

import clockmod
import db
import listing
import lookup
import response
import shape
from errors import fail
from middleware import AGENCY_REP, CLERK, MONITOR, RPO, SYSADMIN, authorize
from services import calc, derive

bp = Blueprint("offers", __name__)

NEGOTIATION_STATUSES = ("OPEN", "IN_NEGOTIATION", "AGREED", "IMPASSE", "LAPSED")
GOOD_FAITH_STATUSES = ("UNREVIEWED", "UNDER_REVIEW", "SATISFIED", "DEFICIENT")
CATEGORIES = ("AFFORDABLE_HOUSING", "PARK_OPEN_SPACE", "SCHOOL_SITE",
              "INFILL_INFRASTRUCTURE")
PARTIES = ("CUSTODIAN_AGENCY", "PREFERENCE_ENTITY")
OUTCOMES = ("AGREED", "IMPASSE")
READ_ROLES = (RPO, CLERK, MONITOR, AGENCY_REP, SYSADMIN)
LIVE_NEGOTIATION = ("OPEN", "IN_NEGOTIATION")


def _declaration_state(offer, *from_states):
    declaration = db.get("declarations", offer["declaration_id"])
    if declaration is None or declaration["status"] not in from_states:
        fail("ERR_INVALID_DECLARATION_STATE",
             "The parent declaration does not admit this action.")
    return declaration


@bp.get("/preference-offers/<row_id>")
@authorize(*READ_ROLES)
def get_offer(row_id):
    row = lookup.must("preference_offers", row_id)
    return response.object_response(derive.offer_out(row))


@bp.get("/preference-offers")
@authorize(*READ_ROLES)
def list_offers():
    limit, offset = listing.bounds()
    declaration_id = shape.query_str("declaration_id")
    notice_id = shape.query_str("notice_id")
    offeror_agency_id = shape.query_str("offeror_agency_id")
    negotiation_status = shape.query_enum("negotiation_status", NEGOTIATION_STATUSES)
    good_faith_status = shape.query_enum("good_faith_status", GOOD_FAITH_STATUSES)
    category = shape.query_enum("preference_category", CATEGORIES)
    rows = db.all_rows("preference_offers")
    if declaration_id is not None:
        rows = [r for r in rows if r["declaration_id"] == declaration_id]
    if notice_id is not None:
        rows = [r for r in rows if r["notice_id"] == notice_id]
    if offeror_agency_id is not None:
        rows = [r for r in rows if r["offeror_agency_id"] == offeror_agency_id]
    if negotiation_status is not None:
        rows = [r for r in rows if r["negotiation_status"] == negotiation_status]
    if good_faith_status is not None:
        rows = [r for r in rows if r["good_faith_status"] == good_faith_status]
    if category is not None:
        rows = [r for r in rows if r["preference_category"] == category]
    return listing.respond(rows, derive.offer_out, limit, offset, listing.by_created_at)


@bp.post("/preference-offers/<row_id>/rounds")
@authorize(RPO, AGENCY_REP)
def append_round(row_id):
    row = lookup.must("preference_offers", row_id)
    if g.role == AGENCY_REP:
        raw = request.get_json(force=True, silent=True) or {}
        claimed_party = raw.get("party") if isinstance(raw, dict) else None
        if row["offeror_agency_id"] != g.user_id:
            fail("ERR_NOT_RESOURCE_OWNER",
                 "A representative may only tender rounds on its own offer.")
        if claimed_party != "PREFERENCE_ENTITY":
            fail("ERR_NOT_RESOURCE_OWNER",
                 "A representative may only tender rounds as the preference entity.")

    payload = shape.body()
    party = shape.req_enum(payload, "party", PARTIES)
    price = shape.req_cents(payload, "price_offered_cents")
    terms = shape.req_str(payload, "terms_summary", 1)
    responded_to = shape.opt_int(payload, "responded_to_round_number", 1)

    _declaration_state(row, "NOTICED", "PREFERENCE_CLOSED")
    if row["negotiation_status"] not in LIVE_NEGOTIATION:
        fail("ERR_INVALID_OFFER_STATE",
             "An offer that is %s accepts no further rounds." % row["negotiation_status"])
    if clockmod.now() > row["negotiation_deadline_at"]:
        fail("ERR_NEGOTIATION_WINDOW_EXPIRED",
             "The 90-day good-faith negotiation window has expired.")

    existing = derive.offer_rounds(row["id"])
    referenced = None
    if responded_to is not None:
        for candidate in existing:
            if candidate["round_number"] == responded_to:
                referenced = candidate
                break
        if (referenced is None or referenced["party"] == party
                or referenced["round_number"] >= len(existing) + 1):
            fail("ERR_INVALID_ROUND_REFERENCE",
                 "responded_to_round_number must name an earlier round of the opposite party.")

    now = clockmod.now()
    responded_within_days = None
    if referenced is not None:
        responded_within_days = clockmod.whole_days_between(referenced["created_at"], now)
    is_timely = (responded_within_days is not None
                 and responded_within_days <= calc.TIMELY_RESPONSE_DAYS)
    round_row = db.insert_event("negotiation_rounds", {
        "offer_id": row["id"],
        "round_number": len(existing) + 1,
        "party": party,
        "price_offered_cents": price,
        "terms_summary": terms,
        "responded_to_round_number": responded_to,
        "responded_within_days": responded_within_days,
        "is_timely": is_timely,
    })

    if row["negotiation_status"] == "OPEN":
        row["negotiation_status"] = "IN_NEGOTIATION"
    calc.recompute_offer_minimum(row)
    calc.recompute_interim_score(row)
    db.touch(row)
    return response.object_response(derive.round_out(round_row), 201)


@bp.get("/preference-offers/<row_id>/rounds")
@authorize(*READ_ROLES)
def list_rounds(row_id):
    limit, offset = listing.bounds()
    party = shape.query_enum("party", PARTIES)
    row = lookup.must("preference_offers", row_id)
    rows = derive.offer_rounds(row["id"])
    if party is not None:
        rows = [r for r in rows if r["party"] == party]
    return listing.respond(rows, derive.round_out, limit, offset,
                           lambda r: r["round_number"])


@bp.post("/preference-offers/<row_id>/good-faith-review")
@authorize(MONITOR)
def open_good_faith_review(row_id):
    row = lookup.must("preference_offers", row_id)
    if row["good_faith_status"] != "UNREVIEWED":
        fail("ERR_INVALID_GOOD_FAITH_STATE",
             "An offer that is %s cannot be opened for review." % row["good_faith_status"])
    row["good_faith_status"] = "UNDER_REVIEW"
    db.touch(row)
    return response.object_response(derive.offer_out(row))


@bp.post("/preference-offers/<row_id>/good-faith-determination")
@authorize(MONITOR)
def determine_good_faith(row_id):
    payload = shape.body()
    note = shape.opt_str(payload, "remediation_note", 1)
    row = lookup.must("preference_offers", row_id)
    if row["good_faith_status"] != "UNDER_REVIEW":
        fail("ERR_INVALID_GOOD_FAITH_STATE",
             "A determination requires the offer to be UNDER_REVIEW.")
    if row["negotiation_status"] not in ("AGREED", "IMPASSE", "LAPSED"):
        fail("ERR_NEGOTIATION_STILL_ACTIVE",
             "The negotiation dimension has not concluded.")
    if note is not None:
        row["remediation_note"] = note
    score = calc.good_faith_score(row, "FINAL")
    row["final_good_faith_score"] = score
    row["good_faith_status"] = ("SATISFIED" if score >= calc.GOOD_FAITH_PASS_SCORE
                                else "DEFICIENT")
    db.touch(row)
    return response.object_response(derive.offer_out(row))


@bp.post("/preference-offers/<row_id>/conclude")
@authorize(RPO)
def conclude_negotiation(row_id):
    payload = shape.body()
    outcome = shape.req_enum(payload, "outcome", OUTCOMES)
    agreed_price = shape.opt_cents(payload, "agreed_price_cents")
    if outcome == "AGREED" and agreed_price is None:
        fail("ERR_INVALID_REQUEST", "agreed_price_cents is required when concluding AGREED.")
    row = lookup.must("preference_offers", row_id)
    declaration = _declaration_state(row, "PREFERENCE_CLOSED")
    if row["negotiation_status"] != "IN_NEGOTIATION":
        fail("ERR_INVALID_OFFER_STATE",
             "A conclusion requires the offer to be IN_NEGOTIATION.")

    now = clockmod.now()
    if outcome == "IMPASSE":
        row["_concluded_at"] = now
        row["negotiation_status"] = "IMPASSE"
        db.touch(row)
        db.touch(declaration)
        return response.object_response(derive.offer_out(row))

    if derive.officer_round_count(row["id"]) < calc.REQUIRED_ROUNDS:
        fail("ERR_GOOD_FAITH_ROUNDS_NOT_MET",
             "At least %d custodian-agency rounds are required." % calc.REQUIRED_ROUNDS)
    floor_price = row.get("ah_minimum_price_cents")
    if floor_price is not None and agreed_price < floor_price:
        fail("ERR_AGREED_PRICE_BELOW_MINIMUM",
             "agreed_price_cents must be at least the quoted minimum price.")

    row["_concluded_at"] = now
    row["agreed_price_cents"] = agreed_price
    row["negotiation_status"] = "AGREED"
    db.touch(row)
    for sibling in derive.declaration_offers(declaration["id"]):
        if sibling["id"] == row["id"]:
            continue
        if sibling["negotiation_status"] in LIVE_NEGOTIATION:
            sibling["negotiation_status"] = "LAPSED"
            db.touch(sibling)
    declaration["status"] = "NEGOTIATION_AGREED"
    db.touch(declaration)
    return response.object_response(derive.offer_out(row))
