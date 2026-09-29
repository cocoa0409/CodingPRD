"""Repricing runs: modelling and committing a new classification standard."""
from datetime import timedelta

from flask import Blueprint

import auth
import clock
import db
import response
import serialize
import validation
from constants import REPRICING_BUFFER_HOURS, REPRICING_SCOPES, REPRICING_STATUSES
from errors import fail
from routes import _helpers as h
from services import modeling

bp = Blueprint("repricing", __name__)

BUFFER = timedelta(hours=REPRICING_BUFFER_HOURS)


@bp.post("/ltl/repricing-runs")
def create_repricing_run():
    auth.authenticate(("PricingAnalyst",))
    body = validation.body()
    tariff = validation.fk(
        body, "new_tariff_version_id", "tariff_versions", "ERR_TARIFF_VERSION_NOT_FOUND"
    )
    if tariff is None:
        validation.req_str(body, "new_tariff_version_id")

    scope = validation.req_enum(body, "scope", REPRICING_SCOPES)
    start = validation.req_datetime(body, "sample_window_start_at")
    end = validation.req_datetime(body, "sample_window_end_at")
    validation.check_interval(
        start, end, "sample_window_end_at must be strictly after sample_window_start_at"
    )

    # PRD 3.3 places the PUBLISHED requirement on the modelling step, not on the
    # opening of the run: "Modelling a run moves it DRAFT -> MODELED and requires
    # that the cited standard release is in status PUBLISHED".
    for other in db.all_rows(
        "repricing_runs",
        lambda r: (
            r["new_tariff_version_id"] == tariff["id"] and r["status"] in ("DRAFT", "MODELED")
        ),
    ):
        if start <= other["sample_window_end_at"] + BUFFER and other[
            "sample_window_start_at"
        ] <= end + BUFFER:
            fail(
                "ERR_REPRICING_WINDOW_OVERLAP",
                "Another open repricing run's sample window is within %d hours."
                % REPRICING_BUFFER_HOURS,
            )

    row = db.insert(
        "repricing_runs",
        {
            "new_tariff_version_id": tariff["id"],
            "scope": scope,
            "sample_window_start_at": start,
            "sample_window_end_at": end,
            "status": "DRAFT",
            "impacted_customer_count": 0,
            "aggregate_delta_cents": 0,
            "modeled_at": None,
            "committed_at": None,
        },
    )
    return response.created(serialize.repricing_run(row))


@bp.get("/ltl/repricing-runs/<run_id>")
def read_repricing_run(run_id):
    auth.authenticate(("PricingAnalyst",))
    row = validation.path_row("repricing_runs", run_id, "ERR_REPRICING_RUN_NOT_FOUND")
    return response.ok(serialize.repricing_run(row))


@bp.get("/ltl/repricing-runs")
def list_repricing_runs():
    auth.authenticate(("PricingAnalyst",))
    rows = db.all_rows("repricing_runs")
    rows = h.apply_filters(
        rows,
        (
            ("new_tariff_version_id", "new_tariff_version_id", None),
            ("status", "status", REPRICING_STATUSES),
        ),
    )
    return h.paged(rows, serialize.repricing_run)


@bp.post("/ltl/repricing-runs/<run_id>/model")
def model_repricing_run(run_id):
    auth.authenticate(("PricingAnalyst",))
    row = validation.path_row("repricing_runs", run_id, "ERR_REPRICING_RUN_NOT_FOUND")
    if row["status"] != "DRAFT":
        fail("ERR_INVALID_STATE_TRANSITION", "Repricing run is %s, not DRAFT." % row["status"])

    tariff = db.get("tariff_versions", row["new_tariff_version_id"])
    if tariff is None or tariff["status"] != "PUBLISHED":
        fail("ERR_TARIFF_NOT_PUBLISHED", "The tariff version is no longer PUBLISHED.")

    programs = modeling.scoped_programs(row["scope"])
    window = (row["sample_window_start_at"], row["sample_window_end_at"])
    aggregate = 0
    customer_ids = set()
    for program in programs:
        customer_ids.add(program["customer_id"])
        model = modeling.compute_model(program, tariff_id=tariff["id"], window=window)
        aggregate += int(model["modeled_annual_revenue_cents"]) - int(
            model["baseline_revenue_cents"]
        )

    row["impacted_customer_count"] = len(customer_ids)
    row["aggregate_delta_cents"] = aggregate
    row["status"] = "MODELED"
    row["modeled_at"] = clock.now()
    db.touch(row)
    return response.ok(serialize.repricing_run(row))


@bp.post("/ltl/repricing-runs/<run_id>/commit")
def commit_repricing_run(run_id):
    auth.authenticate(("PricingAnalyst",))
    row = validation.path_row("repricing_runs", run_id, "ERR_REPRICING_RUN_NOT_FOUND")
    if row["status"] != "MODELED":
        fail("ERR_INVALID_STATE_TRANSITION", "Repricing run is %s, not MODELED." % row["status"])

    tariff_id = row["new_tariff_version_id"]
    for program in modeling.scoped_programs(row["scope"]):
        program["pinned_tariff_version_id"] = tariff_id
        modeling.apply_model(program, modeling.compute_model(program))
        db.touch(program)

    row["status"] = "COMMITTED"
    row["committed_at"] = clock.now()
    db.touch(row)
    return response.ok(serialize.repricing_run(row))
