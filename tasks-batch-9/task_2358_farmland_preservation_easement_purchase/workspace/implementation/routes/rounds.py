"""FundingRound endpoints (PRD 3.1, 3.4)."""

from flask import Blueprint, request

from db import base_row, db, touch
from errors import ApiError
from middleware import authenticate
from response import created, listing, ok, pagination
from services import calc, cascade, lookup, serialize
from validation import Payload, body_fk, raw_body

bp = Blueprint("rounds", __name__)

ROUND_STATUSES = ("DRAFT", "OPEN", "SELECTED", "CLOSED")
SCORE_BASES = ("RECEIPT_BASIS", "ROUND_CLOSE_BASIS")

READ_ROLES = ("ProgramAdmin", "AcquisitionOfficer", "Landowner")


@bp.post("/funding-rounds")
def create_round():
    authenticate(("ProgramAdmin",))
    body = raw_body()
    program = lookup.get_program(body_fk(body, "program_id"))
    payload = Payload(
        body, ("program_id", "round_label", "opens_on", "closes_on", "pool_cents")
    )
    payload.string("program_id", min_len=1)
    label = payload.string("round_label", min_len=1, max_len=120)
    opens_on = payload.instant("opens_on")
    closes_on = payload.instant("closes_on")
    pool_cents = payload.integer("pool_cents", minimum=1)
    if closes_on <= opens_on:
        raise ApiError("ERR_INVALID_REQUEST", "closes_on must be strictly after opens_on")

    row = base_row()
    row.update(
        {
            "program_id": program["id"],
            "round_label": label,
            "opens_on": opens_on,
            "closes_on": closes_on,
            "pool_cents": pool_cents,
            "status": "DRAFT",
            "score_basis": None,
            "ranked_at": None,
        }
    )
    db.rounds[row["id"]] = row
    return created(serialize.funding_round(row))


@bp.get("/funding-rounds/<round_id>")
def read_round(round_id):
    authenticate(READ_ROLES)
    return ok(serialize.funding_round(lookup.get_round(round_id)))


@bp.get("/funding-rounds")
def list_rounds():
    authenticate(READ_ROLES)
    limit, offset = pagination(request.args)
    program_id = request.args.get("program_id")
    status = request.args.get("status")
    if status is not None and status not in ROUND_STATUSES:
        raise ApiError("ERR_INVALID_REQUEST", "status filter is not a valid round status")
    rows = list(db.rounds.values())
    if program_id is not None:
        rows = [r for r in rows if r["program_id"] == program_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    # created_at DESC then id ASC
    rows.sort(key=lambda r: r["id"])
    rows.sort(key=lambda r: r["created_at"], reverse=True)
    return listing(rows, limit, offset, serialize.funding_round)


@bp.post("/funding-rounds/<round_id>/opening")
def open_round(round_id):
    authenticate(("ProgramAdmin",))
    rnd = lookup.get_round(round_id)
    Payload(raw_body(), ())
    program = lookup.program_of_round(rnd)
    if rnd["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_ROUND_STATE", "only a DRAFT round can be opened")
    if program["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_ROUND_STATE", "the parent program is not ACTIVE")
    has_active_source = any(
        s["program_id"] == program["id"] and s["status"] == "ACTIVE"
        for s in db.funding_sources.values()
    )
    if not has_active_source:
        raise ApiError(
            "ERR_INVALID_ROUND_STATE",
            "the program has no ACTIVE funding source",
        )
    rnd["status"] = "OPEN"
    touch(rnd)
    return ok(serialize.funding_round(rnd))


@bp.post("/funding-rounds/<round_id>/rank")
def rank_round(round_id):
    authenticate(("ProgramAdmin",))
    rnd = lookup.get_round(round_id)
    payload = Payload(raw_body(), ("score_basis",))
    score_basis = payload.enum("score_basis", SCORE_BASES)

    if rnd["status"] != "OPEN":
        raise ApiError("ERR_INVALID_ROUND_STATE", "only an OPEN round can be ranked")
    if db.clock <= rnd["closes_on"]:
        raise ApiError(
            "ERR_ROUND_WINDOW_CLOSED",
            "ranking may not run before the clock passes closes_on",
        )
    candidates = [
        a for a in lookup.applications_of_round(rnd["id"]) if a["status"] == "RECEIVED"
    ]
    if not candidates:
        raise ApiError(
            "ERR_NO_SCORED_APPLICATIONS",
            "the round has no RECEIVED application to score",
        )

    program = lookup.program_of_round(rnd)
    ranked = []
    not_selected = []
    for app in candidates:
        parcel = db.parcels[app["parcel_id"]]
        if score_basis == "RECEIPT_BASIS":
            contiguity = app["contiguity_acres_at_receipt"]
        else:
            contiguity = parcel["contiguous_preserved_acres"]
        score = calc.application_composite_score(program, parcel, contiguity)
        app["composite_score"] = score
        if score >= program["min_composite_score"]:
            ranked.append(app)
        else:
            not_selected.append(app)

    ranked.sort(key=lambda a: (-a["composite_score"], a["created_at"], a["_seq"]))
    for position, app in enumerate(ranked, start=1):
        app["status"] = "RANKED"
        app["rank_position"] = position
        touch(app)
    for app in not_selected:
        app["status"] = "NOT_SELECTED"
        app["rank_position"] = None
        cascade.parcel_release(app)
        touch(app)

    rnd["score_basis"] = score_basis
    rnd["ranked_at"] = db.clock
    rnd["status"] = "SELECTED"
    touch(rnd)

    return ok(
        {
            "ranked_count": len(ranked),
            "selected_count": lookup.round_selected_count(rnd["id"]),
            "not_selected_count": len(not_selected),
            "ranked_application_ids": [a["id"] for a in ranked],
        }
    )
