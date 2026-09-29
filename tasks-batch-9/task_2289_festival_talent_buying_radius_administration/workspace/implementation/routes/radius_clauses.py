"""Radius clause reads and the waiver request / decision pair."""

from flask import Blueprint, g

from db import db, public, public_list, touch
from errors import fail
from middleware import endpoint, is_artist_rep, require_artist_scope
from response import paginate, respond_array, respond_object
from services import calc, derive
from validators import (
    body,
    body_fk,
    load,
    opt_int,
    opt_string,
    pagination,
    query_enum,
    query_string,
    req_enum,
    req_int,
    req_string,
    stored_date,
)

bp = Blueprint("radius_clauses", __name__)

ENFORCEMENT_STATUSES = ("PROVISIONAL", "ACTIVE", "BREACHED", "WAIVED", "RELEASED")
WAIVER_STATUSES = ("NONE", "REQUESTED", "GRANTED", "DENIED")
READ_ROLES = ["TalentBuyer", "ArtistRep", "BusinessAffairs", "FinanceController"]


@bp.get("/radius-clauses/<clause_id>")
@endpoint(READ_ROLES)
def get_clause(clause_id):
    clause = load("radius_clauses", clause_id)
    require_artist_scope(clause["artist_id"])
    return respond_object(public(clause))


@bp.get("/radius-clauses")
@endpoint(READ_ROLES)
def list_clauses():
    offer_id = query_string("offer_id")
    booking_id = query_string("booking_id")
    artist_id = query_string("artist_id")
    performance_id = query_string("waiver_competing_performance_id")
    enforcement_status = query_enum("enforcement_status", ENFORCEMENT_STATUSES)
    waiver_status = query_enum("waiver_status", WAIVER_STATUSES)
    limit, offset = pagination()

    rows = list(db.radius_clauses.values())
    if is_artist_rep():
        rows = [r for r in rows if r["artist_id"] == g.user_id]
    if offer_id is not None:
        rows = [r for r in rows if r["offer_id"] == offer_id]
    if booking_id is not None:
        rows = [r for r in rows if r["booking_id"] == booking_id]
    if artist_id is not None:
        rows = [r for r in rows if r["artist_id"] == artist_id]
    if performance_id is not None:
        rows = [
            r for r in rows if r["waiver_competing_performance_id"] == performance_id
        ]
    if enforcement_status is not None:
        rows = [r for r in rows if r["enforcement_status"] == enforcement_status]
    if waiver_status is not None:
        rows = [r for r in rows if r["waiver_status"] == waiver_status]

    rows = sorted(rows, key=lambda r: r["_seq"])
    rows = sorted(rows, key=lambda r: stored_date(r["window_start_date"]))
    rows = sorted(rows, key=lambda r: r["radius_miles"], reverse=True)
    window, meta = paginate(rows, limit, offset)
    return respond_array(public_list(window), pagination=meta)


@bp.post("/radius-clauses/<clause_id>/waiver-request")
@endpoint(["ArtistRep"])
def waiver_request(clause_id):
    payload = body()
    req_string(payload, "competing_performance_id", 1)
    req_int(payload, "waiver_fee_offer_cents", 0, None)
    opt_string(payload, "request_note", None, 1, None)

    clause = load("radius_clauses", clause_id)
    performance = body_fk(payload, "competing_performance_id", "competing_performances")
    require_artist_scope(clause["artist_id"])

    if clause["enforcement_status"] == "RELEASED" or clause["waiver_status"] != "NONE":
        fail("ERR_INVALID_CLAUSE_STATE", "the clause cannot take a waiver request")

    clause["waiver_status"] = "REQUESTED"
    clause["waiver_competing_performance_id"] = performance["id"]
    clause["waiver_fee_offer_cents"] = payload["waiver_fee_offer_cents"]
    touch(clause)
    return respond_object(public(clause))


@bp.post("/radius-clauses/<clause_id>/waiver-decision")
@endpoint(["BusinessAffairs"])
def waiver_decision(clause_id):
    payload = body()
    decision = req_enum(payload, "decision", ("GRANTED", "DENIED"))
    waiver_fee_cents = opt_int(payload, "waiver_fee_cents", 0, 0, None)
    opt_string(payload, "decision_note", None, 1, None)

    clause = load("radius_clauses", clause_id)
    if clause["enforcement_status"] != "BREACHED" or clause["waiver_status"] != "REQUESTED":
        fail("ERR_INVALID_CLAUSE_STATE", "no pending waiver request on a breached clause")

    performance = db.competing_performances.get(
        clause["waiver_competing_performance_id"]
    )
    if performance is None or performance["status"] != "VIOLATION":
        fail(
            "ERR_ADJUDICATION_MISMATCH",
            "the referenced adjudication is not an open violation",
        )

    if decision == "DENIED":
        clause["waiver_status"] = "DENIED"
        touch(clause)
        return respond_object(public(clause))

    if waiver_fee_cents < clause["waiver_fee_offer_cents"]:
        fail("ERR_WAIVER_FEE_BELOW_OFFER", "a granted waiver may not undercut the offer")

    derive.cascade_waiver_granted(clause, waiver_fee_cents)
    return respond_object(public(clause))
