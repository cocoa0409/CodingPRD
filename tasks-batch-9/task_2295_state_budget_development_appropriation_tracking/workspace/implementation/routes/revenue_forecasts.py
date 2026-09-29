"""Revenue forecasts: draft creation under cycle OCC, and adoption."""

from flask import Blueprint

import auth
import db
import response
import util
from errors import fail
from services import constants as C
from services import core
from validators import (
    body_json,
    listing,
    peek_fk,
    read_enum,
    read_id,
    read_instant,
    read_int,
    read_str,
    query_enum,
)

bp = Blueprint("revenue_forecasts", __name__)


@bp.post("/fiscal/revenue-forecasts")
def create_forecast():
    auth.authenticate((auth.BUDGET_ANALYST,))
    body = body_json()

    cycle = peek_fk(body, "budget_cycle_id", core.get_cycle)

    read_id(body, "budget_cycle_id")
    source_code = read_str(body, "source_code", min_len=1, max_len=32)
    fund_type = read_enum(body, "fund_type", C.FUND_TYPES)
    forecast_round = read_enum(body, "forecast_round", C.FORECAST_ROUNDS)
    amount_cents = read_int(body, "amount_cents")
    if amount_cents <= 0:
        fail("ERR_INVALID_REQUEST", "amount_cents must be greater than zero.")
    effective_from = read_instant(body, "effective_from")
    effective_to = read_instant(body, "effective_to")
    if effective_to <= effective_from:
        fail("ERR_INVALID_REQUEST", "effective_to must be later than effective_from.")
    expected_version = read_int(body, "expected_budget_cycle_version")

    if expected_version != cycle["version"]:
        fail(
            "ERR_STALE_VERSION",
            "Budget cycle version is %d, not %d." % (cycle["version"], expected_version),
        )
    core.require_not_closed(cycle)

    row = db.new_row()
    row.update(
        {
            "budget_cycle_id": cycle["id"],
            "source_code": source_code,
            "fund_type": fund_type,
            "forecast_round": forecast_round,
            "amount_cents": amount_cents,
            "effective_from": body["effective_from"],
            "effective_to": body["effective_to"],
            "status": "DRAFT",
            "_effective_from": effective_from,
            "_effective_to": effective_to,
        }
    )
    db.revenue_forecasts[row["id"]] = row
    db.touch(cycle)
    return response.created(db.serialize(row))


@bp.post("/fiscal/revenue-forecasts/<forecast_id>/adopt")
def adopt_forecast(forecast_id):
    auth.authenticate((auth.BUDGET_DIRECTOR,))
    forecast = core.get_forecast(forecast_id)
    body = body_json()
    prior = peek_fk(body, "supersedes_forecast_id", core.get_forecast)

    cycle = core.get_cycle(forecast["budget_cycle_id"])
    core.require_phase(cycle, ("DEVELOPMENT", "EXECUTIVE_PREP"))

    if forecast["status"] != "DRAFT":
        fail("ERR_INVALID_STATE", "Only a DRAFT forecast may be adopted.")

    if prior is not None:
        if (
            prior["budget_cycle_id"] != forecast["budget_cycle_id"]
            or prior["source_code"] != forecast["source_code"]
            or prior["status"] != "ADOPTED"
        ):
            fail(
                "ERR_INVALID_STATE",
                "supersedes_forecast_id must name an ADOPTED forecast of the same cycle "
                "and source_code.",
            )

    buffer_days = C.FORECAST_QUIET_BUFFER_DAYS
    a_from = forecast["_effective_from"]
    a_to = forecast["_effective_to"]
    for other in db.revenue_forecasts.values():
        if other["id"] == forecast["id"]:
            continue
        if prior is not None and other["id"] == prior["id"]:
            continue
        if other["budget_cycle_id"] != forecast["budget_cycle_id"]:
            continue
        if other["source_code"] != forecast["source_code"]:
            continue
        if other["status"] != "ADOPTED":
            continue
        b_from = other["_effective_from"]
        b_to = other["_effective_to"]
        if a_from < util.add_days(b_to, buffer_days) and b_from < util.add_days(
            a_to, buffer_days
        ):
            fail(
                "ERR_FORECAST_WINDOW_CONFLICT",
                "The adopted window is within %d days of forecast %s."
                % (buffer_days, other["id"]),
            )

    db.apply_changes(forecast, {"status": "ADOPTED"})
    if prior is not None:
        db.apply_changes(prior, {"status": "SUPERSEDED"})
    core.sync(cycle, force_cycle=True)
    return response.ok(db.serialize(forecast))


@bp.get("/fiscal/budget-cycles/<cycle_id>/revenue-forecasts")
def list_cycle_forecasts(cycle_id):
    auth.authenticate(auth.ANY_ROLE)
    cycle = core.get_cycle(cycle_id)
    status = query_enum("status", C.FORECAST_STATUSES)
    fund_type = query_enum("fund_type", C.FUND_TYPES)
    rows = []
    for row in db.revenue_forecasts.values():
        if row["budget_cycle_id"] != cycle["id"]:
            continue
        if status is not None and row["status"] != status:
            continue
        if fund_type is not None and row["fund_type"] != fund_type:
            continue
        rows.append(row)
    data, meta = listing(rows)
    return response.ok_list(data, meta)
