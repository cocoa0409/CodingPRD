"""Statutory notices of availability and the recipient's response (PRD 3.5)."""

from flask import Blueprint, g

import clockmod
import db
import listing
import lookup
import response
import shape
from errors import fail
from middleware import AGENCY_REP, CLERK, MONITOR, RPO, SYSADMIN, authorize
from services import calc, derive

bp = Blueprint("notices", __name__)

NOTICE_STATUSES = ("ISSUED", "INTEREST_EXPRESSED", "DECLINED", "EXPIRED")
RESPONSE_TYPES = ("EXPRESS_INTEREST", "DECLINE")
OFFER_CATEGORIES = ("AFFORDABLE_HOUSING", "PARK_OPEN_SPACE", "SCHOOL_SITE",
                    "INFILL_INFRASTRUCTURE")
READ_ROLES = (RPO, CLERK, MONITOR, AGENCY_REP, SYSADMIN)


@bp.get("/notices/<row_id>")
@authorize(*READ_ROLES)
def get_notice(row_id):
    row = lookup.must("notices", row_id)
    return response.object_response(derive.notice_out(row))


@bp.get("/notices")
@authorize(*READ_ROLES)
def list_notices():
    limit, offset = listing.bounds()
    declaration_id = shape.query_str("declaration_id")
    recipient_agency_id = shape.query_str("recipient_agency_id")
    status = shape.query_enum("status", NOTICE_STATUSES)
    notice_round = shape.query_int("notice_round")
    rows = db.all_rows("notices")
    if declaration_id is not None:
        rows = [r for r in rows if r["declaration_id"] == declaration_id]
    if recipient_agency_id is not None:
        rows = [r for r in rows if r["recipient_agency_id"] == recipient_agency_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if notice_round is not None:
        rows = [r for r in rows if r["notice_round"] == notice_round]
    return listing.respond(rows, derive.notice_out, limit, offset, listing.by_created_at)


@bp.post("/notices/<row_id>/respond")
@authorize(AGENCY_REP)
def respond_to_notice(row_id):
    row = lookup.must("notices", row_id)
    if row["recipient_agency_id"] != g.user_id:
        fail("ERR_NOT_RESOURCE_OWNER",
             "Only the noticed agency may respond to its own notice.")
    agency = db.get("agencies", row["recipient_agency_id"])
    payload = shape.body()
    response_type = shape.req_enum(payload, "response_type", RESPONSE_TYPES)
    claimed = None
    intended_use = shape.opt_str(payload, "intended_use", 1)
    if response_type == "EXPRESS_INTEREST":
        # Presence and enum membership are shape checks (PRD 2.10) and stay here.
        claimed = shape.req_enum(payload, "claimed_preference_category", OFFER_CATEGORIES)

    if row["status"] != "ISSUED":
        fail("ERR_INVALID_NOTICE_STATE",
             "A notice that is %s can no longer be answered." % row["status"])
    if response_type == "EXPRESS_INTEREST" and not agency["is_preference_entity"]:
        fail("ERR_NOT_PREFERENCE_ENTITY",
             "Only an agency holding a statutory preference right may express interest.")
    if response_type == "EXPRESS_INTEREST" and claimed != agency["preference_category"]:
        # PRD 3.5 gates on the preference right first and only then "further
        # requires" the claim to match the agency's own category, so a
        # non-preference recipient is told so rather than told its claim mismatched.
        fail("ERR_INVALID_REQUEST",
             "claimed_preference_category must equal the agency's own preference_category.")
    if clockmod.now() > row["response_deadline_at"]:
        fail("ERR_NOTICE_RESPONSE_LATE",
             "The statutory response deadline has passed.")

    if response_type == "DECLINE":
        row["responded_at"] = clockmod.now()
        row["response_type"] = "DECLINE"
        row["status"] = "DECLINED"
        db.touch(row)
        return response.object_response(derive.notice_out(row))

    now = clockmod.now()
    row["responded_at"] = now
    row["response_type"] = "EXPRESS_INTEREST"
    row["claimed_preference_category"] = claimed
    row["intended_use"] = intended_use
    row["status"] = "INTEREST_EXPRESSED"
    db.touch(row)

    offer = db.insert("preference_offers", {
        "declaration_id": row["declaration_id"],
        "notice_id": row["id"],
        "offeror_agency_id": row["recipient_agency_id"],
        "preference_category": claimed,
        "negotiation_status": "OPEN",
        "good_faith_status": "UNREVIEWED",
        "negotiation_opened_at": now,
        "negotiation_deadline_at": clockmod.plus_days(now, calc.GOOD_FAITH_NEGOTIATION_DAYS),
        "ah_minimum_price_cents": None,
        "agreed_price_cents": None,
        "interim_good_faith_score": None,
        "final_good_faith_score": None,
        "remediation_note": None,
    })
    calc.recompute_offer_minimum(offer)
    return response.object_response(derive.notice_out(row))
