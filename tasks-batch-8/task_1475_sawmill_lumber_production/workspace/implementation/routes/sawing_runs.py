"""SawingRun endpoints: plan, get, complete."""
from flask import Blueprint

from db import DB, new_id, now_iso
from errors import ApiError
from middleware import ALL_ROLES, auth
from response import ok
from services import (
    DIMENSIONS,
    LENGTHS_FT,
    SAW_LINES,
    SAWING_PATTERNS,
    SPECIES,
    effective_mbf,
    estimated_dry,
    get_run,
    ser_run,
    stamp,
    touch,
)
from util import (
    as_enum,
    as_int,
    as_list,
    as_num,
    as_ymd,
    body,
    dec,
    required,
    round_mbf,
    round_pct2,
)

bp = Blueprint("sawing_runs", __name__)


@bp.post("/api/sawing-runs")
def create_run():
    auth(["Sawyer"])
    data = body()
    saw_line = as_enum(required(data, "saw_line"), "saw_line", SAW_LINES)
    scheduled_date = as_ymd(required(data, "scheduled_date"), "scheduled_date")
    sawing_pattern = as_enum(
        required(data, "sawing_pattern"), "sawing_pattern", SAWING_PATTERNS
    )
    load_ids = as_list(required(data, "log_load_ids"), "log_load_ids", non_empty=True)
    for i, lid in enumerate(load_ids):
        if not isinstance(lid, str):
            raise ApiError(
                "ERR_INVALID_REQUEST", 400, f"log_load_ids[{i}] must be a string"
            )

    # Existence: every referenced load must exist.
    loads = []
    for lid in load_ids:
        load = DB["log_loads"].get(lid)
        if load is None:
            raise ApiError("ERR_NOT_FOUND", 404, f"LogLoad {lid} not found")
        loads.append(load)

    # State: every listed load must be DECKED.
    for load in loads:
        if load["status"] != "DECKED":
            raise ApiError(
                "ERR_INVALID_STATE",
                409,
                f"LogLoad {load['id']} is not DECKED",
            )

    # Business constraint: saw line daily booking (whole-calendar-day, per line).
    for r in DB["sawing_runs"].values():
        if (
            r["status"] == "PLANNED"
            and r["saw_line"] == saw_line
            and r["scheduled_date"] == scheduled_date
        ):
            raise ApiError(
                "ERR_SAW_LINE_BOOKED",
                409,
                "Another PLANNED run occupies this saw line on this date",
            )

    # Business constraint: log set integrity (no duplicates, none attached to
    # another PLANNED run).
    if len(set(load_ids)) != len(load_ids):
        raise ApiError(
            "ERR_DUPLICATE_LOAD_IN_RUN", 422, "log_load_ids contains a duplicate"
        )
    for load in loads:
        if load["sawing_run_id"] is not None:
            raise ApiError(
                "ERR_DUPLICATE_LOAD_IN_RUN",
                422,
                f"LogLoad {load['id']} is already attached to another planned run",
            )

    run = {
        "id": new_id(),
        "saw_line": saw_line,
        "scheduled_date": scheduled_date,
        "sawing_pattern": sawing_pattern,
        "log_load_ids": list(load_ids),
        "status": "PLANNED",
        "input_mbf": None,
        "output_green_mbf": None,
        "recovery_pct_provisional": None,
        "recovery_pct_certified": None,
        "completed_at": None,
        "chip_tons": None,
        "sawdust_tons": None,
        "bark_tons": None,
    }
    stamp(run)
    DB["sawing_runs"][run["id"]] = run
    # Attach: set sawing_run_id on each load (mutating update bumps version).
    for load in loads:
        load["sawing_run_id"] = run["id"]
        touch(load)
    return ok(ser_run(run), 201)


@bp.get("/api/sawing-runs/<rid>")
def get_one_run(rid):
    auth(ALL_ROLES)
    return ok(ser_run(get_run(rid)))


def _validate_package_entry(entry, index):
    if not isinstance(entry, dict):
        raise ApiError(
            "ERR_INVALID_REQUEST", 400, f"packages[{index}] must be an object"
        )
    species = as_enum(required(entry, "species"), f"packages[{index}].species", SPECIES)
    dimension = as_enum(
        required(entry, "dimension"), f"packages[{index}].dimension", DIMENSIONS
    )
    length_ft = as_int(required(entry, "length_ft"), f"packages[{index}].length_ft")
    if length_ft not in LENGTHS_FT:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            400,
            f"packages[{index}].length_ft must be one of {sorted(LENGTHS_FT)}",
        )
    pieces = as_int(
        required(entry, "pieces"), f"packages[{index}].pieces", positive=True
    )
    green_mbf = as_num(
        required(entry, "green_mbf"), f"packages[{index}].green_mbf", positive=True
    )
    return species, dimension, length_ft, pieces, green_mbf


@bp.post("/api/sawing-runs/<rid>/complete")
def complete_run(rid):
    auth(["Sawyer"])
    run = get_run(rid)
    data = body()
    entries = as_list(required(data, "packages"), "packages", non_empty=True)
    parsed = [_validate_package_entry(e, i) for i, e in enumerate(entries)]
    chip_tons = as_num(required(data, "chip_tons"), "chip_tons", non_negative=True)
    sawdust_tons = as_num(
        required(data, "sawdust_tons"), "sawdust_tons", non_negative=True
    )
    bark_tons = as_num(required(data, "bark_tons"), "bark_tons", non_negative=True)

    # State preconditions: run PLANNED and every listed load still DECKED and
    # still attached to this run.
    if run["status"] != "PLANNED":
        raise ApiError(
            "ERR_INVALID_STATE", 409, "Only a PLANNED run can be completed"
        )
    for lid in run["log_load_ids"]:
        load = DB["log_loads"].get(lid)
        if (
            load is None
            or load["status"] != "DECKED"
            or load["sawing_run_id"] != run["id"]
        ):
            raise ApiError(
                "ERR_INVALID_STATE",
                409,
                "Every attached load must still be DECKED and attached to this run",
            )

    # Single atomic write: consume loads, create packages, compute recovery.
    input_total = dec(0)
    for lid in run["log_load_ids"]:
        load = DB["log_loads"][lid]
        eff = effective_mbf(load)
        input_total += dec(eff)
        load["status"] = "CONSUMED"
        touch(load)
    input_mbf = round_mbf(input_total)

    output_total = dec(0)
    for species, dimension, length_ft, pieces, green_mbf in parsed:
        pkg = {
            "id": new_id(),
            "sawing_run_id": run["id"],
            "species": species,
            "dimension": dimension,
            "length_ft": length_ft,
            "pieces": pieces,
            "green_mbf": green_mbf,
            "estimated_dry_mbf": estimated_dry(green_mbf, species),
            "actual_dry_mbf": None,
            "kiln_charge_id": None,
            "exit_moisture_pct": None,
            "stamped_grade": None,
            "status": "GREEN",
            "stamped_at": None,
            "sales_order_id": None,
        }
        stamp(pkg)
        DB["lumber_packages"][pkg["id"]] = pkg
        output_total += dec(green_mbf)
    output_green_mbf = round_mbf(output_total)

    run["input_mbf"] = input_mbf
    run["output_green_mbf"] = output_green_mbf
    run["recovery_pct_provisional"] = round_pct2(
        dec(output_green_mbf) / dec(input_mbf) * dec(100)
    )
    run["chip_tons"] = chip_tons
    run["sawdust_tons"] = sawdust_tons
    run["bark_tons"] = bark_tons
    run["completed_at"] = now_iso()
    run["status"] = "COMPLETED"
    touch(run)
    return ok(ser_run(run))
