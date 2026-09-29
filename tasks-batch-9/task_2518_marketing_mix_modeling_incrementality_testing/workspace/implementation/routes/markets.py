"""Markets and the washout sweep (PRD sections 3.1, 3.6)."""

from decimal import Decimal

from flask import Blueprint, request

import db as store
from db import base_row, db, touch
from errors import ApiError
from lookup import must
from middleware import DATA_ENGINEER, EXPERIMENT_DESIGNER, READ_ROLES, authenticate
from response import created, listing, ok
from services import ordering
from services.market import sync_market
from validation import field_int, field_string, get_body

bp = Blueprint("markets", __name__)

CODE_PATTERN = r"^[A-Z][A-Z0-9_]{2,31}$"
POSTURES = ("OPEN", "RESTRICTED", "FROZEN")


@bp.post("/mmm/markets")
def create_market():
    authenticate((DATA_ENGINEER,))
    body = get_body()
    market_code = field_string(body, "market_code", pattern=CODE_PATTERN)
    name = field_string(body, "name", min_len=1, max_len=120)
    total_population = field_int(body, "total_population", minimum=1000)
    ceiling = field_int(body, "annual_budget_ceiling_cents", minimum=0)
    currency_code = field_string(body, "currency_code", required=False, default="USD",
                                 pattern=r"^[A-Z]{3}$")

    for existing in db.all("markets"):
        if existing["market_code"] == market_code:
            raise ApiError("ERR_DUPLICATE_RESOURCE",
                           "market_code '%s' is already in use." % market_code)

    row = base_row("markets")
    row.update({
        "market_code": market_code,
        "name": name,
        "total_population": total_population,
        "annual_budget_ceiling_cents": ceiling,
        "currency_code": currency_code,
        "celled_population": 0,
        "held_out_population": 0,
        "held_out_population_pct": Decimal("0.00"),
        "data_posture": "RESTRICTED",
        "published_model_run_id": None,
    })
    db.add("markets", row)
    return created(row)


@bp.get("/mmm/markets")
def list_markets():
    authenticate(READ_ROLES)
    rows = db.all("markets")
    market_code = request.args.get("market_code")
    if market_code:
        rows = [r for r in rows if r["market_code"] == market_code]
    posture = request.args.get("data_posture")
    if posture:
        rows = [r for r in rows if r["data_posture"] == posture]
    return listing(ordering.sort_rows("markets", rows), request.args)


@bp.get("/mmm/markets/<market_id>")
def get_market(market_id):
    authenticate(READ_ROLES)
    return ok(must("markets", market_id))


@bp.post("/mmm/markets/<market_id>/washout-sweep")
def washout_sweep(market_id):
    authenticate((EXPERIMENT_DESIGNER,))
    market = must("markets", market_id)
    now = db.clock
    for cell in store.cells_of_market(market_id):
        if cell["assignment_state"] != "WASHOUT":
            continue
        until = cell["_washout_until_date"]
        if until is None:
            continue
        if until <= now.date():
            cell["assignment_state"] = "UNASSIGNED"
            cell["assigned_experiment_id"] = None
            cell["washout_until_date"] = None
            cell["_washout_until_date"] = None
            touch(cell)
    # PRD 3.6: the market's aggregates are recomputed and its version is incremented.
    sync_market(market, force=True)
    return ok(market)
