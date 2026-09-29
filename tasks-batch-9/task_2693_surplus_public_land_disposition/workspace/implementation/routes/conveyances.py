"""Conveyance, net proceeds, recording, and the deed-restriction / reverter
cycle (PRD 3.10, 3.11).
"""

from decimal import Decimal

from flask import Blueprint

import clockmod
import db
import listing
import lookup
import response
import shape
from errors import fail
from middleware import (AGENCY_REP, BIDDER, CLERK, FINANCE, MONITOR, RPO, SYSADMIN,
                        authorize)
from services import calc, cascade, derive, waterfall

bp = Blueprint("conveyances", __name__)

RECORDING_STATUSES = ("PENDING_TITLE", "READY_TO_RECORD", "RECORDED", "RESCINDED")
COMPLIANCE_STATUSES = ("NOT_MONITORED", "COMPLIANT", "VIOLATION_NOTICED", "CURED", "REVERTED")
READ_ROLES = (RPO, CLERK, MONITOR, FINANCE, AGENCY_REP, BIDDER, SYSADMIN)

DEED_RESTRICTION_MIN = 1
DEED_RESTRICTION_MAX = 10
CURE_PERIOD_DEFAULT_DAYS = 180
CURE_PERIOD_MIN_DAYS = 30
CURE_PERIOD_MAX_DAYS = 730
LIVE_CONVEYANCE_STATUSES = ("PENDING_TITLE", "READY_TO_RECORD", "RECORDED")


def _recording_state(row, *from_states):
    if row["recording_status"] not in from_states:
        fail("ERR_INVALID_CONVEYANCE_STATE",
             "A conveyance whose recording status is %s cannot take this action."
             % row["recording_status"])


def _compliance_state(row, *from_states):
    if row["compliance_status"] not in from_states:
        fail("ERR_INVALID_CONVEYANCE_STATE",
             "A conveyance whose compliance status is %s cannot take this action."
             % row["compliance_status"])


@bp.post("/offerings/<row_id>/conveyance")
@authorize(RPO)
def open_conveyance(row_id):
    payload = shape.body()
    closing_costs = shape.req_cents(payload, "closing_costs_cents")
    broker_fee = shape.req_cents(payload, "broker_fee_cents")
    restrictions = shape.req_str_list(payload, "deed_restrictions",
                                     DEED_RESTRICTION_MIN, DEED_RESTRICTION_MAX)
    reverter_condition = shape.req_str(payload, "reverter_condition", 1)
    cure_period = shape.opt_int(payload, "reverter_cure_period_days",
                                CURE_PERIOD_MIN_DAYS, CURE_PERIOD_MAX_DAYS,
                                default=CURE_PERIOD_DEFAULT_DAYS)
    offering = lookup.must("offerings", row_id)

    if offering["status"] != "AWARDED":
        fail("ERR_INVALID_OFFERING_STATE",
             "A conveyance file is opened on an AWARDED offering.")

    declaration = db.get("declarations", offering["declaration_id"])
    parcel_id = declaration["parcel_id"] if declaration is not None else None
    reserved = derive.reserved_easement_count(parcel_id) if parcel_id else 0
    if len(restrictions) < reserved:
        fail("ERR_EASEMENT_RESERVATION_MISSING",
             "The deed must carry at least %d clauses for the reserved easements." % reserved)

    for other in cascade.offering_conveyances(offering["id"]):
        if other["recording_status"] in LIVE_CONVEYANCE_STATUSES:
            fail("ERR_CONVEYANCE_ALREADY_EXISTS",
                 "This offering already carries a live conveyance.")

    grantee_kind = None
    grantee_bidder_id = None
    grantee_agency_id = None
    if offering["offering_type"] == "COMPETITIVE_SALE":
        winner = cascade.winning_bid(offering["id"])
        grantee_kind = "BIDDER"
        grantee_bidder_id = winner["bidder_id"] if winner is not None else None
    elif offering.get("counterparty_bidder_id") is not None:
        grantee_kind = "BIDDER"
        grantee_bidder_id = offering["counterparty_bidder_id"]
    else:
        grantee_kind = "AGENCY"
        grantee_agency_id = offering.get("counterparty_agency_id")

    row = db.insert("conveyances", {
        "offering_id": offering["id"],
        "parcel_id": parcel_id,
        "grantee_kind": grantee_kind,
        "grantee_bidder_id": grantee_bidder_id,
        "grantee_agency_id": grantee_agency_id,
        "sale_price_cents": offering.get("winning_bid_amount_cents"),
        "closing_costs_cents": closing_costs,
        "broker_fee_cents": broker_fee,
        "recoverable_curative_cost_cents": 0,
        "net_proceeds_cents": 0,
        "deed_restrictions": list(restrictions),
        "reverter_condition": reverter_condition,
        "reverter_cure_period_days": cure_period,
        "recording_status": "PENDING_TITLE",
        "compliance_status": "NOT_MONITORED",
        "recorded_instrument_number": None,
        "recorded_at": None,
        "violation_noticed_at": None,
        "cure_deadline_at": None,
        "violation_description": None,
        "cure_note": None,
        "reverted_at": None,
    })
    return response.object_response(derive.conveyance_out(row), 201)


@bp.get("/conveyances/<row_id>")
@authorize(*READ_ROLES)
def get_conveyance(row_id):
    row = lookup.must("conveyances", row_id)
    return response.object_response(derive.conveyance_out(row))


@bp.get("/conveyances")
@authorize(*READ_ROLES)
def list_conveyances():
    limit, offset = listing.bounds()
    offering_id = shape.query_str("offering_id")
    parcel_id = shape.query_str("parcel_id")
    grantee_bidder_id = shape.query_str("grantee_bidder_id")
    grantee_agency_id = shape.query_str("grantee_agency_id")
    recording_status = shape.query_enum("recording_status", RECORDING_STATUSES)
    compliance_status = shape.query_enum("compliance_status", COMPLIANCE_STATUSES)
    rows = db.all_rows("conveyances")
    if offering_id is not None:
        rows = [r for r in rows if r["offering_id"] == offering_id]
    if parcel_id is not None:
        rows = [r for r in rows if r["parcel_id"] == parcel_id]
    if grantee_bidder_id is not None:
        rows = [r for r in rows if r.get("grantee_bidder_id") == grantee_bidder_id]
    if grantee_agency_id is not None:
        rows = [r for r in rows if r.get("grantee_agency_id") == grantee_agency_id]
    if recording_status is not None:
        rows = [r for r in rows if r["recording_status"] == recording_status]
    if compliance_status is not None:
        rows = [r for r in rows if r["compliance_status"] == compliance_status]
    return listing.respond(rows, derive.conveyance_out, limit, offset, listing.by_created_at)


@bp.post("/conveyances/<row_id>/clear-title")
@authorize(RPO)
def clear_title(row_id):
    row = lookup.must("conveyances", row_id)
    _recording_state(row, "PENDING_TITLE")
    if derive.open_title_item_count(row["parcel_id"]) > 0:
        fail("ERR_TITLE_ITEMS_UNRESOLVED",
             "Every title curative item on the parcel must have left OPEN.")
    offering = db.get("offerings", row["offering_id"])
    declaration_id = offering["declaration_id"] if offering is not None else None
    certified = any(r["status"] == "CERTIFIED" for r in db.all_rows("environmental_reviews")
                    if r["declaration_id"] == declaration_id)
    if not certified:
        fail("ERR_ENV_REVIEW_NOT_CERTIFIED",
             "No environmental review on this declaration has been certified.")
    if calc.provisional_net(row) <= 0:
        fail("ERR_NET_PROCEEDS_NON_POSITIVE",
             "The provisional net proceeds must be strictly greater than zero.")

    calc.freeze_net_proceeds(row)
    row["recording_status"] = "READY_TO_RECORD"
    db.touch(row)
    return response.object_response(derive.conveyance_out(row))


@bp.post("/conveyances/<row_id>/record")
@authorize(RPO)
def record_deed(row_id):
    payload = shape.body()
    instrument = shape.req_str(payload, "recorded_instrument_number", 1)
    row = lookup.must("conveyances", row_id)
    _recording_state(row, "READY_TO_RECORD")
    if not db.all_rows("funds"):
        fail("ERR_FUNDS_NOT_CONFIGURED", "No fund is configured to receive the proceeds.")
    if waterfall.allocation_pct_sum() != Decimal(1):
        fail("ERR_ALLOCATION_PCT_SUM_INVALID",
             "The allocation percentages across the funds must sum to exactly 1.")

    now = clockmod.now()
    row["recorded_instrument_number"] = instrument
    row["recorded_at"] = now
    row["recording_status"] = "RECORDED"
    row["compliance_status"] = "COMPLIANT"
    db.touch(row)

    parcel = db.get("parcels", row["parcel_id"])
    if parcel is not None:
        parcel["ownership_status"] = "CONVEYED"
        db.touch(parcel)

    offering = db.get("offerings", row["offering_id"])
    if offering is not None:
        offering["status"] = "CLOSED_CONVEYED"
        db.touch(offering)
        declaration = db.get("declarations", offering["declaration_id"])
        if declaration is not None:
            declaration["status"] = "CONVEYED"
            db.touch(declaration)

    waterfall.run_waterfall(row)

    if offering is not None and offering["offering_type"] == "COMPETITIVE_SALE":
        winner = cascade.winning_bid(offering["id"])
        if winner is not None and winner["deposit_status"] == "HELD":
            winner["deposit_status"] = "APPLIED"
            bidder = db.get("bidders", winner["bidder_id"])
            if bidder is not None:
                calc.apply_deposit(bidder, winner["deposit_amount_cents"])
            db.touch(winner)
    return response.object_response(derive.conveyance_out(row))


@bp.post("/conveyances/<row_id>/violation-notice")
@authorize(MONITOR)
def notice_violation(row_id):
    payload = shape.body()
    description = shape.req_str(payload, "violation_description", 1)
    row = lookup.must("conveyances", row_id)
    if (row["recording_status"] != "RECORDED"
            or row["compliance_status"] not in ("COMPLIANT", "CURED")):
        fail("ERR_INVALID_CONVEYANCE_STATE",
             "A violation is noticed on a RECORDED conveyance that is COMPLIANT or CURED.")
    now = clockmod.now()
    row["compliance_status"] = "VIOLATION_NOTICED"
    row["violation_noticed_at"] = now
    row["violation_description"] = description
    row["cure_deadline_at"] = clockmod.plus_days(now, row["reverter_cure_period_days"])
    db.touch(row)
    return response.object_response(derive.conveyance_out(row))


@bp.post("/conveyances/<row_id>/accept-cure")
@authorize(MONITOR)
def accept_cure(row_id):
    payload = shape.body()
    note = shape.req_str(payload, "cure_note", 1)
    row = lookup.must("conveyances", row_id)
    _compliance_state(row, "VIOLATION_NOTICED")
    if clockmod.now() > row["cure_deadline_at"]:
        fail("ERR_CURE_PERIOD_EXPIRED", "The cure period has expired.")
    row["compliance_status"] = "CURED"
    row["cure_note"] = note
    row["violation_noticed_at"] = None
    row["cure_deadline_at"] = None
    db.touch(row)
    return response.object_response(derive.conveyance_out(row))


@bp.post("/conveyances/<row_id>/revert")
@authorize(MONITOR)
def enforce_reverter(row_id):
    row = lookup.must("conveyances", row_id)
    _compliance_state(row, "VIOLATION_NOTICED")
    if clockmod.now() <= row["cure_deadline_at"]:
        fail("ERR_CURE_PERIOD_NOT_EXPIRED",
             "On the deadline instant itself the grantee still holds the right to cure.")

    row["compliance_status"] = "REVERTED"
    row["recording_status"] = "RESCINDED"
    row["reverted_at"] = clockmod.now()
    db.touch(row)

    parcel = db.get("parcels", row["parcel_id"])
    if parcel is not None:
        parcel["ownership_status"] = "REVERTED_TO_AGENCY"
        parcel["_valuation_forced_stale"] = True
        db.touch(parcel)

    waterfall.reverse_conveyance_allocations(row)
    return response.object_response(derive.conveyance_out(row))
