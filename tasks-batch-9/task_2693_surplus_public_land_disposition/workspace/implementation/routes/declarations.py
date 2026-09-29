"""Surplus declarations: the statutory spine of the disposition (PRD 3.5, 3.8, 3.9)."""

from flask import Blueprint, g

import clockmod
import db
import listing
import lookup
import response
import shape
from errors import fail
from middleware import (AGENCY_REP, BIDDER, CLERK, FINANCE, MONITOR, RPO, SYSADMIN,
                        authorize)
from services import calc, cascade, derive

bp = Blueprint("declarations", __name__)

DECLARATION_STATUSES = ("DRAFT", "ADOPTED", "NOTICED", "PREFERENCE_CLOSED",
                        "NEGOTIATION_AGREED", "OFFERING_AUTHORIZED", "UNSUCCESSFUL",
                        "CONVEYED", "WITHDRAWN")
DISPOSITION_TYPES = ("COMPETITIVE_SALE", "NEGOTIATED_SALE", "EXCHANGE")
TERMINAL_STATUSES = ("CONVEYED", "WITHDRAWN")
READ_ROLES = (RPO, CLERK, MONITOR, FINANCE, AGENCY_REP, BIDDER, SYSADMIN)


def _state(declaration, *from_states):
    if declaration["status"] not in from_states:
        fail("ERR_INVALID_DECLARATION_STATE",
             "A declaration in %s cannot take this action." % declaration["status"])


@bp.post("/declarations")
@authorize(RPO)
def create_declaration():
    payload = shape.body()
    justification = shape.req_str(payload, "justification", 1)
    restriction = shape.opt_str(payload, "intended_use_restriction", 1)
    parcel_id = payload.get("parcel_id")
    if parcel_id is None:
        fail("ERR_INVALID_REQUEST", "parcel_id is required.")
    parcel = lookup.must_fk("parcels", parcel_id)
    if parcel["ownership_status"] != "AGENCY_OWNED":
        fail("ERR_INVALID_REQUEST",
             "A parcel whose ownership_status is %s cannot be declared surplus."
             % parcel["ownership_status"])
    for other in db.all_rows("declarations"):
        if other["parcel_id"] == parcel["id"] and other["status"] not in TERMINAL_STATUSES:
            fail("ERR_DUPLICATE_ACTIVE_DECLARATION",
                 "This parcel already carries a live declaration.")
    row = db.insert("declarations", {
        "parcel_id": parcel["id"],
        "justification": justification,
        "intended_use_restriction": restriction,
        "status": "DRAFT",
        "resolution_number": None,
        "adopted_by_user_id": None,
        "adopted_at": None,
        "notice_issued_at": None,
        "notice_response_window_days": None,
        "notice_response_deadline_at": None,
        "authorized_disposition_type": None,
        "authority_findings": None,
        "reoffer_count": 0,
        "reoffer_eligible_at": None,
        "withdrawn_reason": None,
    })
    return response.object_response(derive.declaration_out(row), 201)


@bp.get("/declarations/<row_id>")
@authorize(*READ_ROLES)
def get_declaration(row_id):
    row = lookup.must("declarations", row_id)
    return response.object_response(derive.declaration_out(row))


@bp.get("/declarations")
@authorize(*READ_ROLES)
def list_declarations():
    limit, offset = listing.bounds()
    parcel_id = shape.query_str("parcel_id")
    status = shape.query_enum("status", DECLARATION_STATUSES)
    disposition_type = shape.query_enum("authorized_disposition_type", DISPOSITION_TYPES)
    rows = db.all_rows("declarations")
    if parcel_id is not None:
        rows = [r for r in rows if r["parcel_id"] == parcel_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if disposition_type is not None:
        rows = [r for r in rows if r.get("authorized_disposition_type") == disposition_type]
    return listing.respond(rows, derive.declaration_out, limit, offset, listing.by_created_at)


@bp.post("/declarations/<row_id>/adopt")
@authorize(CLERK)
def adopt_declaration(row_id):
    payload = shape.body()
    resolution_number = shape.req_str(payload, "resolution_number", 1)
    row = lookup.must("declarations", row_id)
    _state(row, "DRAFT")
    row["resolution_number"] = resolution_number
    row["adopted_by_user_id"] = g.user_id
    row["adopted_at"] = clockmod.now()
    row["status"] = "ADOPTED"
    db.touch(row)
    return response.object_response(derive.declaration_out(row))


@bp.post("/declarations/<row_id>/issue-notices")
@authorize(RPO)
def issue_notices(row_id):
    payload = shape.body()
    agency_ids = shape.req_str_list(payload, "recipient_agency_ids", 1, 20, distinct=True)
    window_days = shape.opt_int(payload, "response_window_days")
    row = lookup.must("declarations", row_id)
    recipients = [lookup.must_fk("agencies", agency_id) for agency_id in agency_ids]
    _state(row, "ADOPTED")
    if window_days is None:
        window_days = calc.NOTICE_RESPONSE_WINDOW_DEFAULT_DAYS
    elif (window_days < calc.NOTICE_RESPONSE_WINDOW_MIN_DAYS
            or window_days > calc.NOTICE_RESPONSE_WINDOW_MAX_DAYS):
        fail("ERR_NOTICE_WINDOW_INVALID",
             "response_window_days must fall within %d through %d days."
             % (calc.NOTICE_RESPONSE_WINDOW_MIN_DAYS, calc.NOTICE_RESPONSE_WINDOW_MAX_DAYS))
    for agency in recipients:
        if agency["notice_registry_status"] == "LAPSED":
            fail("ERR_NOTICE_REGISTRY_LAPSED",
                 "Agency %s has lapsed off the notice registry." % agency["id"])
    cascade.issue_notice_round(row, [a["id"] for a in recipients], window_days, 1)
    row["status"] = "NOTICED"
    db.touch(row)
    return response.object_response(derive.declaration_out(row))


@bp.post("/declarations/<row_id>/close-preference-window")
@authorize(RPO)
def close_preference_window(row_id):
    row = lookup.must("declarations", row_id)
    _state(row, "NOTICED")
    notices = cascade.current_round_notices(row["id"])
    nobody_pending = all(n["status"] != "ISSUED" for n in notices)
    deadline = row.get("notice_response_deadline_at")
    deadline_reached = deadline is not None and clockmod.now() >= deadline
    if not (nobody_pending or deadline_reached):
        fail("ERR_PREFERENCE_WINDOW_STILL_OPEN",
             "Recipients may still reply and the statutory deadline has not been reached.")
    for notice in notices:
        if notice["status"] == "ISSUED":
            notice["status"] = "EXPIRED"
            db.touch(notice)
    row["status"] = "PREFERENCE_CLOSED"
    db.touch(row)
    return response.object_response(derive.declaration_out(row))


def _authorization_scope(declaration, disposition_type):
    """The preference offers whose good faith the authorization depends on."""
    offers = derive.declaration_offers(declaration["id"])
    if disposition_type == "COMPETITIVE_SALE":
        return offers
    agreed = calc.agreed_ah_offer(declaration["id"])
    return [agreed] if agreed is not None else []


@bp.post("/declarations/<row_id>/authorize-disposition")
@authorize(CLERK)
def authorize_disposition(row_id):
    payload = shape.body()
    disposition_type = shape.req_enum(payload, "disposition_type", DISPOSITION_TYPES)
    findings = shape.opt_str(payload, "authority_findings", 1)
    row = lookup.must("declarations", row_id)
    _state(row, "PREFERENCE_CLOSED", "NEGOTIATION_AGREED")

    offers = derive.declaration_offers(row["id"])
    if disposition_type == "COMPETITIVE_SALE":
        for offer in offers:
            if offer["negotiation_status"] not in ("IMPASSE", "LAPSED"):
                fail("ERR_NEGOTIATION_STILL_ACTIVE",
                     "Preference offer %s has not cleared the way for open competition."
                     % offer["id"])

    scope = _authorization_scope(row, disposition_type)
    for offer in scope:
        if offer["good_faith_status"] in ("UNREVIEWED", "UNDER_REVIEW"):
            fail("ERR_GOOD_FAITH_NOT_DETERMINED",
                 "Good faith on preference offer %s has not been determined." % offer["id"])
    for offer in scope:
        if offer["good_faith_status"] == "DEFICIENT":
            fail("ERR_GOOD_FAITH_DEFICIENT",
                 "Preference offer %s was graded DEFICIENT." % offer["id"])

    if disposition_type == "NEGOTIATED_SALE" and calc.agreed_ah_offer(row["id"]) is None:
        fail("ERR_PREFERENCE_UNRESOLVED",
             "A negotiated sale requires a preference offer that reached AGREED.")
    if disposition_type == "COMPETITIVE_SALE" and row["status"] == "NEGOTIATION_AGREED":
        fail("ERR_OFFERING_TYPE_AUTHORITY_MISMATCH",
             "A declaration in NEGOTIATION_AGREED cannot be authorized as a competitive sale.")
    if disposition_type == "EXCHANGE" and not findings:
        fail("ERR_EXCHANGE_FINDINGS_REQUIRED",
             "An exchange rests on an express board finding.")

    certified = any(r["status"] == "CERTIFIED" for r in db.all_rows("environmental_reviews")
                    if r["declaration_id"] == row["id"])
    if not certified:
        fail("ERR_ENV_REVIEW_NOT_CERTIFIED",
             "No environmental review on this declaration has been certified.")

    parcel = db.get("parcels", row["parcel_id"])
    if parcel is None or not derive.disposition_ready(parcel):
        fail("ERR_PARCEL_NOT_DISPOSITION_READY", "The parcel is not disposition-ready.")

    row["authorized_disposition_type"] = disposition_type
    if findings is not None:
        row["authority_findings"] = findings
    # Which from-state was used governs the negotiated counterparty rule (PRD 3.8).
    row["_authorized_from"] = row["status"]
    row["status"] = "OFFERING_AUTHORIZED"
    db.touch(row)
    return response.object_response(derive.declaration_out(row))


@bp.post("/declarations/<row_id>/re-offer")
@authorize(RPO)
def reoffer_declaration(row_id):
    row = lookup.must("declarations", row_id)
    _state(row, "UNSUCCESSFUL")

    top_round = cascade.highest_notice_round(row["id"])
    recipient_ids = []
    for notice in cascade.declaration_notices(row["id"]):
        if notice["notice_round"] == top_round and notice["recipient_agency_id"] not in recipient_ids:
            recipient_ids.append(notice["recipient_agency_id"])
    for agency_id in recipient_ids:
        agency = db.get("agencies", agency_id)
        if agency is not None and agency["notice_registry_status"] == "LAPSED":
            fail("ERR_NOTICE_REGISTRY_LAPSED",
                 "Agency %s has lapsed off the notice registry." % agency_id)

    eligible_at = row.get("reoffer_eligible_at")
    if eligible_at is not None and clockmod.now() < eligible_at:
        fail("ERR_REOFFER_COOLING_OFF",
             "The statutory cooling-off period has not run.")
    if row["reoffer_count"] >= calc.REOFFER_LIMIT:
        fail("ERR_REOFFER_LIMIT_REACHED",
             "A declaration may be re-offered at most %d times." % calc.REOFFER_LIMIT)

    window_days = row.get("notice_response_window_days")
    if window_days is None:
        window_days = calc.NOTICE_RESPONSE_WINDOW_DEFAULT_DAYS
    row["reoffer_count"] += 1
    row["reoffer_eligible_at"] = None
    row["status"] = "NOTICED"
    cascade.issue_notice_round(row, recipient_ids, window_days, top_round + 1)
    db.touch(row)
    return response.object_response(derive.declaration_out(row))


@bp.post("/declarations/<row_id>/withdraw")
@authorize(CLERK)
def withdraw_declaration(row_id):
    payload = shape.body()
    reason = shape.req_str(payload, "withdrawn_reason", 1)
    row = lookup.must("declarations", row_id)
    _state(row, "DRAFT", "OFFERING_AUTHORIZED")
    from_state = row["status"]
    row["withdrawn_reason"] = reason
    row["status"] = "WITHDRAWN"
    db.touch(row)
    if from_state == "OFFERING_AUTHORIZED":
        cascade.withdrawal_cascade(row)
    return response.object_response(derive.declaration_out(row))
