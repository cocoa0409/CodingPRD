"""Royalty statements, lines, reconciliation and close — PRD §3.7, §3.8."""

from fractions import Fraction

from flask import Blueprint, request

from db import db, common_fields, new_id, next_seq, now, touch
from errors import ApiError
from middleware import auth, require_ownership
from response import created, ok, ok_list, paginate, read_pagination
from services import calc, core
import validation as v

bp = Blueprint("royalty", __name__)

SOURCES = {"STREAMING", "DOWNLOAD", "CONTENT_ID"}


def owned_statement(user_id, role, statement_id):
    statement = db.royalty_statements.get(statement_id)
    if role == "Artist" and statement is not None:
        require_ownership(user_id == statement["artist_id"])
    return core.find_statement(statement_id)


@bp.post("/api/royalty-statements")
def create_statement():
    auth("FinanceOps")
    data = v.body()
    artist_id = v.req_id(data, "artist_id")
    period_start = v.req_datetime(data, "period_start")
    period_end = v.req_datetime(data, "period_end")

    core.find_artist(artist_id)

    for existing in db.royalty_statements.values():
        if existing["artist_id"] != artist_id:
            continue
        if existing["period_start"] < period_end and period_start < existing["period_end"]:
            raise ApiError("ERR_STATEMENT_PERIOD_OVERLAP")

    row = common_fields()
    row.update({
        "artist_id": artist_id,
        "period_start": period_start,
        "period_end": period_end,
        "status": "OPEN",
        "line_count": 0,
        "gross_cents": 0,
        "content_id_gross_cents": 0,
        "commission_cents": 0,
        "content_id_bonus_cents": 0,
        "provisional_net_cents": 0,
        "net_cents": 0,
        "reconciled_by_user_id": None,
        "closed_by_user_id": None,
    })
    db.royalty_statements[row["id"]] = row
    return created(row)


@bp.get("/api/royalty-statements/<statement_id>")
def read_statement(statement_id):
    user_id, role = auth("FinanceOps", "Artist", "PlatformAdmin")
    return ok(owned_statement(user_id, role, statement_id))


@bp.get("/api/royalty-statements")
def list_statements():
    user_id, role = auth("FinanceOps", "Artist", "PlatformAdmin")
    limit, offset = read_pagination(request.args)
    rows = list(db.royalty_statements.values())
    if role == "Artist":
        rows = [s for s in rows if s["artist_id"] == user_id]
    artist_id = request.args.get("artist_id")
    if artist_id is not None:
        rows = [s for s in rows if s["artist_id"] == artist_id]
    status = request.args.get("status")
    if status is not None:
        rows = [s for s in rows if s["status"] == status]
    page, total = paginate(rows, limit, offset)
    return ok_list(page, limit, offset, total)


@bp.post("/api/royalty-statements/<statement_id>/ingest")
def ingest_lines(statement_id):
    auth("FinanceOps")
    data = v.body()
    expected_version = v.req_int(data, "expected_statement_version", minimum=0)
    raw_lines = v.require(data, "lines")
    if not isinstance(raw_lines, list):
        v.bad("Field 'lines' must be an array.")

    parsed = []
    for element in raw_lines:
        if not isinstance(element, dict):
            v.bad("Each element of 'lines' must be an object.")
        parsed.append({
            "track_id": v.req_id(element, "track_id"),
            "store_id": v.req_id(element, "store_id"),
            "units": v.req_int(element, "units", minimum=0),
            "gross_cents": v.req_int(element, "gross_cents", minimum=0),
            "source": v.req_enum(element, "source", SOURCES),
            "reported_at": v.req_datetime(element, "reported_at"),
        })

    statement = core.find_statement(statement_id)

    for line in parsed:
        core.find_track(line["track_id"])
        core.find_store(line["store_id"])

    if statement["status"] not in ("OPEN", "INGESTING"):
        raise ApiError("ERR_INVALID_STATE")

    if expected_version != statement["version"]:
        raise ApiError("ERR_STALE_VERSION")

    for line in parsed:
        if not (statement["period_start"] <= line["reported_at"] < statement["period_end"]):
            raise ApiError("ERR_LINE_OUTSIDE_PERIOD")

    for line in parsed:
        row = {
            "id": new_id(),
            "created_at": now(),
            "_seq": next_seq(),
            "royalty_statement_id": statement["id"],
        }
        row.update(line)
        db.royalty_lines[row["id"]] = row

    statement["status"] = "INGESTING"
    calc.recompute_statement_aggregates(statement)
    touch(statement)
    return ok(statement)


@bp.get("/api/royalty-lines/<line_id>")
def read_line(line_id):
    user_id, role = auth("FinanceOps", "Artist", "PlatformAdmin")
    line = db.royalty_lines.get(line_id)
    if role == "Artist" and line is not None:
        statement = db.royalty_statements.get(line["royalty_statement_id"])
        if statement is not None:
            require_ownership(user_id == statement["artist_id"])
    return ok(core.find_line(line_id))


@bp.get("/api/royalty-lines")
def list_lines():
    user_id, role = auth("FinanceOps", "Artist", "PlatformAdmin")
    limit, offset = read_pagination(request.args)
    rows = list(db.royalty_lines.values())
    if role == "Artist":
        own = {s["id"] for s in db.royalty_statements.values() if s["artist_id"] == user_id}
        rows = [l for l in rows if l["royalty_statement_id"] in own]
    statement_id = request.args.get("royalty_statement_id")
    if statement_id is not None:
        rows = [l for l in rows if l["royalty_statement_id"] == statement_id]
    track_id = request.args.get("track_id")
    if track_id is not None:
        rows = [l for l in rows if l["track_id"] == track_id]
    store_id = request.args.get("store_id")
    if store_id is not None:
        rows = [l for l in rows if l["store_id"] == store_id]
    source = request.args.get("source")
    if source is not None:
        rows = [l for l in rows if l["source"] == source]
    page, total = paginate(rows, limit, offset)
    return ok_list(page, limit, offset, total)


@bp.post("/api/royalty-statements/<statement_id>/reconcile")
def reconcile_statement(statement_id):
    user_id, _role = auth("FinanceOps")
    statement = core.find_statement(statement_id)
    if statement["status"] not in ("OPEN", "INGESTING"):
        raise ApiError("ERR_INVALID_STATE")

    artist = db.artists.get(statement["artist_id"])
    commission = calc.commission_cents(statement, artist, "PROVISIONAL")
    statement["commission_cents"] = commission
    statement["content_id_bonus_cents"] = 0
    statement["provisional_net_cents"] = statement["gross_cents"] - commission
    statement["net_cents"] = statement["provisional_net_cents"]
    statement["reconciled_by_user_id"] = user_id
    statement["status"] = "RECONCILED"
    touch(statement)
    return ok(statement)


@bp.post("/api/royalty-statements/<statement_id>/close")
def close_statement(statement_id):
    user_id, _role = auth("FinanceOps")
    statement = core.find_statement(statement_id)
    if statement["status"] != "RECONCILED":
        raise ApiError("ERR_INVALID_STATE")
    if statement["reconciled_by_user_id"] == user_id:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    artist = db.artists.get(statement["artist_id"])

    commission = calc.commission_cents(statement, artist, "FINAL")
    bonus = calc.content_id_bonus_cents(statement)
    statement["commission_cents"] = commission
    statement["content_id_bonus_cents"] = bonus
    statement["net_cents"] = statement["gross_cents"] - commission + bonus

    _materialise_payouts(statement)

    if artist is not None:
        artist["lifetime_gross_cents"] += statement["gross_cents"]
        touch(artist)

    statement["closed_by_user_id"] = user_id
    statement["status"] = "CLOSED"
    touch(statement)
    return ok(statement)


def _materialise_payouts(statement):
    """Cascade hops 2 and 3 of close — PRD §3.8."""
    contributions = calc.allocate_payout_shares(statement)
    totals = {}
    order = []
    for collaborator_id, cents in contributions:
        if collaborator_id not in totals:
            totals[collaborator_id] = 0
            order.append(collaborator_id)
        totals[collaborator_id] += cents

    for collaborator_id in order:
        collaborator = db.collaborators.get(collaborator_id)
        if collaborator is None:
            continue
        gross = totals[collaborator_id]
        bps = calc.withholding_bps(collaborator)
        withholding = calc.round_half_up(Fraction(gross * bps, 10000))
        row = common_fields()
        row.update({
            "collaborator_id": collaborator_id,
            "royalty_statement_id": statement["id"],
            "gross_cents": gross,
            "withholding_bps": bps,
            "withholding_cents": withholding,
            "net_cents": gross - withholding,
            "status": "PENDING",
            "auto_approved": False,
            "approved_by_user_id": None,
            "paid_by_user_id": None,
            "paid_at": None,
            "reversal_reason_code": None,
        })
        db.payouts[row["id"]] = row

        if row["net_cents"] >= core.PAYOUT_THRESHOLD_CENTS:
            row["status"] = "APPROVED"
            row["auto_approved"] = True
            touch(row)

        calc.recompute_collaborator_totals(collaborator)


@bp.get("/api/royalty-statements/<statement_id>/summary")
def statement_summary(statement_id):
    user_id, role = auth("FinanceOps", "Artist", "PlatformAdmin")
    statement = owned_statement(user_id, role, statement_id)
    payouts = core.payouts_of_statement(statement["id"])
    return ok({
        "statement_id": statement["id"],
        "gross_cents": statement["gross_cents"],
        "content_id_gross_cents": statement["content_id_gross_cents"],
        "commission_cents": statement["commission_cents"],
        "content_id_bonus_cents": statement["content_id_bonus_cents"],
        "provisional_net_cents": statement["provisional_net_cents"],
        "net_cents": statement["net_cents"],
        "variant_delta_cents": statement["net_cents"] - statement["provisional_net_cents"],
        "payout_count": len(payouts),
        "payout_gross_total_cents": sum(p["gross_cents"] for p in payouts),
    })
