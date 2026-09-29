"""Deposition chamber runs (PRD section 3.3)."""

from decimal import Decimal

from flask import Blueprint

import calculations as calc
import db
import validation as v
from errors import ApiError
from middleware import authenticate
from response import object_response
from routes import common as c
from services import derive, serialize

bp = Blueprint("coating_runs", __name__)

READ_ROLES = ["CoatingEngineer", "QualityApprover", "ProductionPlanner", "ApplicationEngineer"]
OWNER = ["CoatingEngineer"]


def _chamber_capacity_ok(chamber_id, start, end, area):
    """Half-open intervals: check the load at every instant the new run covers."""
    existing = [
        r
        for r in db.coating_runs.values()
        if r["chamber_id"] == chamber_id and r["status"] in ("SCHEDULED", "COMPLETED")
    ]
    instants = [start]
    for run in existing:
        if start <= run["_ws"] < end:
            instants.append(run["_ws"])
    for instant in instants:
        total = calc.D(area)
        for run in existing:
            if run["_ws"] <= instant < run["_we"]:
                total += calc.D(run["loaded_area_cm2"])
        if total > calc.CHAMBER_AREA_CAPACITY_CM2:
            return False
    return True


@bp.route("/tooling/coating-runs", methods=["POST"])
def create():
    authenticate(OWNER)
    payload = v.body(
        required=("recipe_id", "chamber_id", "window_start", "window_end", "loaded_area_cm2")
    )
    recipe_id = v.as_id(payload, "recipe_id")
    chamber_id = v.as_enum(payload, "chamber_id", c.CHAMBERS)
    start = v.as_datetime(payload, "window_start")
    end = v.as_datetime(payload, "window_end")
    area = v.as_number(payload, "loaded_area_cm2", exclusive_min=0)

    recipe = derive.must_exist("recipes", recipe_id)

    if not start < end:
        raise ApiError(
            "ERR_INVALID_WINDOW", "window_start must be strictly earlier than window_end."
        )
    if start < db.now_dt():
        raise ApiError("ERR_WINDOW_IN_PAST", "window_start lies before the current logical time.")
    if not _chamber_capacity_ok(chamber_id, start, end, area):
        raise ApiError(
            "ERR_CHAMBER_CAPACITY_EXCEEDED",
            "Chamber %s would exceed its %s cm2 area budget."
            % (chamber_id, calc.CHAMBER_AREA_CAPACITY_CM2),
        )

    row = db.new_row(
        {
            "recipe_id": recipe["id"],
            "chamber_id": chamber_id,
            "window_start": payload["window_start"],
            "window_end": payload["window_end"],
            "loaded_area_cm2": area,
            "pinned_recipe_revision": recipe["revision"],
            "adhesion_hf_class": None,
            "measured_thickness_um": None,
            "status": "SCHEDULED",
            "_ws": start,
            "_we": end,
        }
    )
    db.coating_runs[row["id"]] = row
    return object_response(serialize.coating_run(row), 201)


@bp.route("/tooling/coating-runs", methods=["GET"])
def index():
    rows, limit, offset = c.listing(
        "coating_runs",
        READ_ROLES,
        {"recipe_id": None, "chamber_id": c.CHAMBERS, "status": c.COATING_RUN_STATUSES},
    )
    return c.list_response("coating_runs", rows, limit, offset)


@bp.route("/tooling/coating-runs/<run_id>", methods=["GET"])
def read(run_id):
    return c.read_one("coating_runs", run_id, READ_ROLES)


@bp.route("/tooling/coating-runs/<run_id>/complete", methods=["POST"])
def complete(run_id):
    authenticate(OWNER)
    payload = v.body(required=("adhesion_hf_class", "measured_thickness_um"))
    hf_class = v.as_int(payload, "adhesion_hf_class", minimum=1, maximum=6)
    thickness = v.as_number(payload, "measured_thickness_um", minimum=0)

    run = derive.must_exist("coating_runs", run_id)
    if run["status"] != "SCHEDULED":
        raise ApiError(
            "ERR_INVALID_COATING_RUN_STATE",
            "Only a SCHEDULED run may be completed (currently %s)." % run["status"],
        )
    if db.now_dt() < run["_we"]:
        raise ApiError(
            "ERR_WINDOW_NOT_ELAPSED",
            "The run's window has not elapsed on the logical clock yet.",
        )

    run["adhesion_hf_class"] = hf_class
    run["measured_thickness_um"] = thickness
    run["status"] = "COMPLETED"
    db.touch(run)

    recipe = db.recipes.get(run["recipe_id"])
    if recipe is not None:
        # adhesion_class and is_validated are derived from the completed-run pool;
        # the recipe row itself is re-evaluated and therefore mutated.
        db.touch(recipe)
    return object_response(serialize.coating_run(run))
