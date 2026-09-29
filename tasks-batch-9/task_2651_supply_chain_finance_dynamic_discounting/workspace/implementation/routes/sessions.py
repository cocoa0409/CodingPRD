"""Auction session endpoints (PRD 3.5)."""

from datetime import timedelta

from flask import Blueprint

from db import base_row, db, public, put_dt, sorted_rows
from errors import ApiError
from middleware import BUYER_ADMIN, authenticate, get_program, get_session, scope_program, scope_session
from response import ok
from services import calc, flows
from services import guards as g
from services import recompute as rc
from validation import bad, body, req_dt, req_enum, req_str

bp = Blueprint("sessions", __name__)

COOLDOWN = timedelta(minutes=calc.SESSION_COOLDOWN_MINUTES)


@bp.post("/auction-sessions")
def create_session():
    ctx = authenticate((BUYER_ADMIN,))
    b = body()
    program_id = req_str(b, "program_id", 1)
    opens_raw, opens_at = req_dt(b, "opens_at")
    closes_raw, closes_at = req_dt(b, "closes_at")
    if not opens_at < closes_at:
        bad(detail="opens_at must be strictly before closes_at.")

    program = get_program(program_id)
    scope_program(ctx, program)
    g.require_program_open(program)

    for existing in sorted_rows(
        [s for s in db.sessions.values() if s["program_id"] == program["id"]]
    ):
        if existing["status"] not in ("SCHEDULED", "LIVE"):
            continue
        if opens_at < existing["_closes_at"] + COOLDOWN and existing["_opens_at"] < closes_at + COOLDOWN:
            raise ApiError("ERR_SESSION_WINDOW_CONFLICT")

    row = base_row()
    row.update(
        {
            "program_id": program["id"],
            "status": "SCHEDULED",
            "named_offer_count": 0,
            "clearing_apr_bps": 0,
        }
    )
    put_dt(row, "opens_at", opens_at, opens_raw)
    put_dt(row, "closes_at", closes_at, closes_raw)
    db.sessions[row["id"]] = row
    return ok(public(row), 201)


@bp.post("/auction-sessions/<session_id>/close")
def close_session(session_id):
    ctx = authenticate((BUYER_ADMIN,))
    b = body()
    mode = req_enum(b, "mode", ("SETTLE", "CANCEL"))
    session = get_session(session_id)
    scope_session(ctx, session)
    g.require_session_not_terminal(session)

    if mode == "SETTLE":
        if session["status"] != "LIVE":
            g.invalid_state("Only a LIVE session can be settled.")
        flows.close_session(session)
    else:
        if session["status"] not in ("SCHEDULED", "LIVE"):
            g.invalid_state("Only a SCHEDULED or LIVE session can be cancelled.")
        for offer in rc.session_offers(session["id"]):
            if offer["status"] == "ACCEPTED":
                g.invalid_state("An accepted offer prevents cancellation.")
        flows.cancel_session(session)
    return ok(public(session))
