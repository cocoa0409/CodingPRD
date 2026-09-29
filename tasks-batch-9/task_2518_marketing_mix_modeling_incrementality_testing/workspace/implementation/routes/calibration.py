"""Calibration records (PRD section 3.7)."""

from flask import Blueprint, request

import db as store
from db import base_row, db, touch
from errors import ApiError
from lookup import must, must_field
from middleware import MODELER, READ_ROLES, authenticate
from response import created, listing, ok
from services import ordering
from services.market import sync_market
from services.reconcile import calibration_figures
from validation import field_int, get_body, query_bool

bp = Blueprint("calibration", __name__)

USABLE_EXPERIMENT_STATES = ("READ_OUT", "ACCEPTED")


@bp.post("/mmm/calibration-records")
def create_calibration_record():
    user_id = authenticate((MODELER,))
    body = get_body()
    expected_version = field_int(body, "expected_model_run_version", minimum=0)

    run = must_field("model_runs", body, "model_run_id")
    channel = must_field("media_channels", body, "channel_id")
    experiment = must_field("experiments", body, "experiment_id")

    if expected_version != run["version"]:
        raise ApiError("ERR_STALE_MODEL_RUN_VERSION",
                       "expected_model_run_version %d does not match the run's version %d."
                       % (expected_version, run["version"]))

    if experiment["status"] not in USABLE_EXPERIMENT_STATES:
        raise ApiError("ERR_EXPERIMENT_INVALID_STATE",
                       "A calibration record needs an experiment in READ_OUT or ACCEPTED.")

    if channel["id"] not in run["included_channel_ids"]:
        raise ApiError("ERR_CHANNEL_NOT_IN_MARKET",
                       "Channel %s is not part of the run's inclusion list."
                       % channel["channel_code"])
    if channel["id"] != experiment["channel_id"]:
        raise ApiError("ERR_CHANNEL_NOT_IN_MARKET",
                       "The experiment did not measure channel %s." % channel["channel_code"])

    contribution = None
    for row in store.contributions_of_run(run["id"], current_only=True):
        if row["channel_id"] == channel["id"]:
            contribution = row
            break
    if contribution is None:
        raise ApiError("ERR_MODEL_RUN_INVALID_STATE",
                       "The model run carries no current contribution row for that channel.")

    figures = calibration_figures(run, contribution, experiment)

    for existing in store.calibration_records_of_run(run["id"], live_only=True):
        if existing["channel_id"] == channel["id"]:
            existing["superseded"] = True
            touch(existing)

    record = base_row("calibration_records")
    record.update({
        "model_run_id": run["id"],
        "channel_id": channel["id"],
        "experiment_id": experiment["id"],
        "experiment_lift_pct": figures["experiment_lift_pct"],
        "model_implied_lift_pct": figures["model_implied_lift_pct"],
        "calibration_multiplier": figures["calibration_multiplier"],
        "bias_direction": figures["bias_direction"],
        "superseded": False,
        "model_run_version_after": None,
        "created_by_user_id": user_id,
    })
    db.add("calibration_records", record)

    run["calibration_status"] = "PENDING_CALIBRATION"
    touch(run)
    record["model_run_version_after"] = run["version"]
    sync_market(db.markets[run["market_id"]])
    return created(record)


@bp.get("/mmm/calibration-records")
def list_calibration_records():
    authenticate(READ_ROLES)
    rows = db.all("calibration_records")
    for param in ("model_run_id", "channel_id", "experiment_id", "bias_direction"):
        value = request.args.get(param)
        if value:
            rows = [r for r in rows if r[param] == value]
    if request.args.get("superseded") not in (None, ""):
        wanted = query_bool(request.args, "superseded", False)
        rows = [r for r in rows if r["superseded"] == wanted]
    return listing(ordering.sort_rows("calibration_records", rows), request.args)


@bp.get("/mmm/calibration-records/<record_id>")
def get_calibration_record(record_id):
    authenticate(READ_ROLES)
    return ok(must("calibration_records", record_id))
