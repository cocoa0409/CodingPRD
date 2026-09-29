"""Geo cells (PRD section 3.1)."""

from flask import Blueprint, request

import db as store
from db import base_row, db
from errors import ApiError
from lookup import must, must_field
from middleware import DATA_ENGINEER, READ_ROLES, authenticate
from response import created, listing, ok
from services import ordering
from services.market import sync_market
from validation import field_int, field_string, get_body

bp = Blueprint("geo_cells", __name__)

CELL_CODE_PATTERN = r"^[A-Z][A-Z0-9_]{1,15}$"
ASSIGNMENT_STATES = ("UNASSIGNED", "TREATMENT", "CONTROL", "WASHOUT")


@bp.post("/mmm/geo-cells")
def create_cell():
    authenticate((DATA_ENGINEER,))
    body = get_body()
    cell_code = field_string(body, "cell_code", pattern=CELL_CODE_PATTERN)
    population = field_int(body, "population", minimum=1)
    market = must_field("markets", body, "market_id")

    for existing in store.cells_of_market(market["id"]):
        if existing["cell_code"] == cell_code:
            raise ApiError("ERR_DUPLICATE_RESOURCE",
                           "cell_code '%s' is already used in this market." % cell_code)

    row = base_row("geo_cells")
    row.update({
        "market_id": market["id"],
        "cell_code": cell_code,
        "population": population,
        "assignment_state": "UNASSIGNED",
        "assigned_experiment_id": None,
        "washout_until_date": None,
        "_washout_until_date": None,
    })
    db.add("geo_cells", row)
    # Adding a cell enlarges the market's celled_population and bumps its version.
    sync_market(market)
    return created(row)


@bp.get("/mmm/geo-cells")
def list_cells():
    authenticate(READ_ROLES)
    rows = db.all("geo_cells")
    market_id = request.args.get("market_id")
    if market_id:
        rows = [r for r in rows if r["market_id"] == market_id]
    state = request.args.get("assignment_state")
    if state:
        rows = [r for r in rows if r["assignment_state"] == state]
    cell_code = request.args.get("cell_code")
    if cell_code:
        rows = [r for r in rows if r["cell_code"] == cell_code]
    experiment_id = request.args.get("assigned_experiment_id")
    if experiment_id:
        rows = [r for r in rows if r["assigned_experiment_id"] == experiment_id]
    return listing(ordering.sort_rows("geo_cells", rows), request.args)


@bp.get("/mmm/geo-cells/<cell_id>")
def get_cell(cell_id):
    authenticate(READ_ROLES)
    return ok(must("geo_cells", cell_id))
