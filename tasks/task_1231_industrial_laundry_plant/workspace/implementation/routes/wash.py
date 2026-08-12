"""WashLoad and FinishRun endpoints."""

from flask import Blueprint

import clock
import db
import services
from errors import (
    ApiError,
    ERR_INVALID_STATE,
    ERR_INVALID_REQUEST,
    ERR_BATCH_NOT_LOCKED,
    ERR_CATEGORY_NOT_IN_BATCH,
    ERR_MACHINE_TIME_OVERLAP,
    ERR_LINE_TIME_OVERLAP,
    ERR_INVALID_TIME_RANGE,
    ERR_TEST_REQUIRED,
    ERR_TEST_NOT_REQUIRED,
    ERR_REWASH_LIMIT_REACHED,
    ERR_TALLY_EXCEEDS_INPUT,
)
from response import success, list_response
from util import (
    FLOOR_READ,
    authenticate,
    require_roles,
    body_json,
    field,
    path_get,
    ref_get,
    filter_eq,
    round2,
    D,
)

bp = Blueprint("wash", __name__)

OPERATOR = {"PlantOperator"}


# ------------------------------------------------------------ WashLoad
@bp.route("/wash-loads", methods=["POST"])
def create_wash_load():
    data = body_json()
    batch_id = field(data, "batch_id", "s")
    category_id = field(data, "category_id", "s")
    machine_id = field(data, "machine_id", "s")
    start_s = field(data, "scheduled_start", "datetime")
    end_s = field(data, "scheduled_end", "datetime")
    auth = authenticate()
    require_roles(auth, OPERATOR)
    batch = ref_get(db.sort_batches, batch_id)
    cat = ref_get(db.categories, category_id)
    # Category must be present with disposition ACCEPTED in the linked batch.
    if not any(
        i["batch_id"] == batch["id"] and i["category_id"] == cat["id"] and i["disposition"] == "ACCEPTED"
        for i in db.sort_items.values()
    ):
        raise ApiError(ERR_CATEGORY_NOT_IN_BATCH, 422, "No ACCEPTED sort item of this category in the batch")
    start = clock.parse_dt(start_s)
    end = clock.parse_dt(end_s)
    if not end > start:
        raise ApiError(ERR_INVALID_TIME_RANGE, 422, "scheduled_end must be after scheduled_start")
    if services.machine_conflict(machine_id, start, end):
        raise ApiError(ERR_MACHINE_TIME_OVERLAP, 409, "Machine interval overlaps an active load")
    load = db.new_entity()
    load.update(
        {
            "plant_id": batch["plant_id"],
            "batch_id": batch["id"],
            "category_id": cat["id"],
            "machine_id": machine_id,
            "scheduled_start": start_s,
            "scheduled_end": end_s,
            "formula_code": cat["wash_formula_code"],
            "rewash_count": 0,
            "hygienic_test_result": "PENDING",
            "clean_weight_lb": None,
            "status": "STAGED",
            "_unloaded_at": None,
        }
    )
    db.wash_loads[load["id"]] = load
    return success(load, 201)


@bp.route("/wash-loads/<wid>", methods=["GET"])
def get_wash_load(wid):
    auth = authenticate()
    require_roles(auth, FLOOR_READ)
    return success(path_get(db.wash_loads, wid))


@bp.route("/plants/<pid>/wash-loads", methods=["GET"])
def list_plant_wash_loads(pid):
    auth = authenticate()
    require_roles(auth, FLOOR_READ)
    plant = path_get(db.plants, pid)
    items = [w for w in db.sorted_all(db.wash_loads) if w["plant_id"] == plant["id"]]
    items = filter_eq(items, "machine_id", "machine_id")
    items = filter_eq(items, "status", "status")
    items = filter_eq(items, "category_id", "category_id")
    return list_response(items)


@bp.route("/sort-batches/<bid>/wash-loads", methods=["GET"])
def list_batch_wash_loads(bid):
    auth = authenticate()
    require_roles(auth, FLOOR_READ)
    batch = path_get(db.sort_batches, bid)
    items = [w for w in db.sorted_all(db.wash_loads) if w["batch_id"] == batch["id"]]
    return list_response(items)


@bp.route("/wash-loads/<wid>/start", methods=["POST"])
def start_wash_load(wid):
    auth = authenticate()
    require_roles(auth, OPERATOR)
    load = path_get(db.wash_loads, wid)
    if load["status"] not in ("STAGED", "REWASH_PENDING"):
        raise ApiError(ERR_INVALID_STATE, 409, "Load is not STAGED or REWASH_PENDING")
    batch = db.sort_batches.get(load["batch_id"])
    if not batch or batch["status"] not in ("LOCKED", "POSTED"):
        raise ApiError(ERR_BATCH_NOT_LOCKED, 409, "Sort batch must be LOCKED or POSTED")
    start = clock.parse_dt(load["scheduled_start"])
    end = clock.parse_dt(load["scheduled_end"])
    if services.machine_conflict(load["machine_id"], start, end, exclude_id=load["id"]):
        raise ApiError(ERR_MACHINE_TIME_OVERLAP, 409, "Machine interval overlaps an active load")
    load["status"] = "RUNNING"
    db.touch(load)
    cust = db.customers.get(services.customer_of_wash_load(load))
    services.garment_cascade(cust, "SOILED_RECEIVED", "WASHING", category_id=load["category_id"])
    return success(load)


@bp.route("/wash-loads/<wid>/finish-cycle", methods=["POST"])
def finish_cycle(wid):
    auth = authenticate()
    require_roles(auth, OPERATOR)
    load = path_get(db.wash_loads, wid)
    if load["status"] != "RUNNING":
        raise ApiError(ERR_INVALID_STATE, 409, "Load is not RUNNING")
    load["status"] = "AWAITING_TEST"
    db.touch(load)
    return success(load)


@bp.route("/wash-loads/<wid>/record-test", methods=["POST"])
def record_test(wid):
    data = body_json()
    outcome = field(data, "outcome", "s", choices=("PASS", "FAIL"))
    auth = authenticate()
    require_roles(auth, OPERATOR)
    load = path_get(db.wash_loads, wid)
    if load["status"] != "AWAITING_TEST":
        raise ApiError(ERR_INVALID_STATE, 409, "Load is not AWAITING_TEST")
    cat = db.categories.get(load["category_id"])
    if not cat or not cat["hygienic_test_required"]:
        raise ApiError(ERR_TEST_NOT_REQUIRED, 422, "Category does not require hygienic testing")
    load["hygienic_test_result"] = outcome
    load["status"] = "TESTED_PASS" if outcome == "PASS" else "TESTED_FAIL"
    db.touch(load)
    return success(load)


@bp.route("/wash-loads/<wid>/bypass-test", methods=["POST"])
def bypass_test(wid):
    auth = authenticate()
    require_roles(auth, OPERATOR)
    load = path_get(db.wash_loads, wid)
    if load["status"] != "AWAITING_TEST":
        raise ApiError(ERR_INVALID_STATE, 409, "Load is not AWAITING_TEST")
    cat = db.categories.get(load["category_id"])
    if cat and cat["hygienic_test_required"]:
        raise ApiError(ERR_TEST_REQUIRED, 422, "Category requires hygienic testing; bypass forbidden")
    load["status"] = "TESTED_PASS"
    db.touch(load)
    return success(load)


@bp.route("/wash-loads/<wid>/request-rewash", methods=["POST"])
def request_rewash(wid):
    auth = authenticate()
    require_roles(auth, OPERATOR)
    load = path_get(db.wash_loads, wid)
    if load["status"] != "TESTED_FAIL":
        raise ApiError(ERR_INVALID_STATE, 409, "Load is not TESTED_FAIL")
    if load["rewash_count"] >= services.MAX_REWASH_COUNT:
        raise ApiError(ERR_REWASH_LIMIT_REACHED, 409, "Rewash limit reached")
    load["rewash_count"] += 1
    load["formula_code"] = services.FORMULA_ESCALATION.get(load["formula_code"], load["formula_code"])
    load["status"] = "REWASH_PENDING"
    db.touch(load)
    return success(load)


@bp.route("/wash-loads/<wid>/unload", methods=["POST"])
def unload_wash_load(wid):
    auth = authenticate()
    require_roles(auth, OPERATOR)
    load = path_get(db.wash_loads, wid)
    if load["status"] != "TESTED_PASS":
        raise ApiError(ERR_INVALID_STATE, 409, "Load is not TESTED_PASS")
    cat = db.categories.get(load["category_id"])
    pieces = services.accepted_pieces(load["batch_id"], load["category_id"])
    weight = D(cat["piece_weight_lb"]) if cat else D(0)
    load["clean_weight_lb"] = float(round2(D(pieces) * weight))
    load["_unloaded_at"] = clock.now()
    load["status"] = "FINISHED"
    db.touch(load)
    cust = db.customers.get(services.customer_of_wash_load(load))
    services.garment_cascade(cust, "WASHING", "CLEAN_STOCK", category_id=load["category_id"])
    return success(load)


@bp.route("/wash-loads/<wid>/cancel", methods=["POST"])
def cancel_wash_load(wid):
    auth = authenticate()
    require_roles(auth, OPERATOR)
    load = path_get(db.wash_loads, wid)
    if load["status"] not in ("STAGED", "REWASH_PENDING"):
        raise ApiError(ERR_INVALID_STATE, 409, "Load is not STAGED or REWASH_PENDING")
    load["status"] = "CANCELLED"
    db.touch(load)
    return success(load)


# ------------------------------------------------------------ FinishRun
@bp.route("/finish-runs", methods=["POST"])
def create_finish_run():
    data = body_json()
    wash_load_id = field(data, "wash_load_id", "s")
    line_id = field(data, "line_id", "s")
    start_s = field(data, "scheduled_start", "datetime")
    end_s = field(data, "scheduled_end", "datetime")
    auth = authenticate()
    require_roles(auth, OPERATOR)
    load = ref_get(db.wash_loads, wash_load_id)
    start = clock.parse_dt(start_s)
    end = clock.parse_dt(end_s)
    if not end > start:
        raise ApiError(ERR_INVALID_TIME_RANGE, 422, "scheduled_end must be after scheduled_start")
    if services.line_conflict(line_id, start, end):
        raise ApiError(ERR_LINE_TIME_OVERLAP, 409, "Line buffered interval overlaps an active run")
    run = db.new_entity()
    run.update(
        {
            "plant_id": load["plant_id"],
            "wash_load_id": load["id"],
            "line_id": line_id,
            "scheduled_start": start_s,
            "scheduled_end": end_s,
            "pieces_in": services.accepted_pieces(load["batch_id"], load["category_id"]),
            "pieces_out": None,
            "linen_loss_pieces": None,
            "throughput_pieces_per_hour": None,
            "status": "QUEUED",
        }
    )
    db.finish_runs[run["id"]] = run
    return success(run, 201)


@bp.route("/finish-runs/<fid>", methods=["GET"])
def get_finish_run(fid):
    auth = authenticate()
    require_roles(auth, FLOOR_READ)
    return success(path_get(db.finish_runs, fid))


@bp.route("/plants/<pid>/finish-runs", methods=["GET"])
def list_plant_finish_runs(pid):
    auth = authenticate()
    require_roles(auth, FLOOR_READ)
    plant = path_get(db.plants, pid)
    items = [f for f in db.sorted_all(db.finish_runs) if f["plant_id"] == plant["id"]]
    items = filter_eq(items, "line_id", "line_id")
    items = filter_eq(items, "status", "status")
    return list_response(items)


@bp.route("/wash-loads/<wid>/finish-runs", methods=["GET"])
def list_load_finish_runs(wid):
    auth = authenticate()
    require_roles(auth, FLOOR_READ)
    load = path_get(db.wash_loads, wid)
    items = [f for f in db.sorted_all(db.finish_runs) if f["wash_load_id"] == load["id"]]
    return list_response(items)


@bp.route("/finish-runs/<fid>/tally", methods=["POST"])
def tally_finish_run(fid):
    data = body_json()
    pieces_out = field(data, "pieces_out", "i", minv=0)
    auth = authenticate()
    require_roles(auth, OPERATOR)
    run = path_get(db.finish_runs, fid)
    if run["status"] != "QUEUED":
        raise ApiError(ERR_INVALID_STATE, 409, "Finish run is not QUEUED")
    if pieces_out > run["pieces_in"]:
        raise ApiError(ERR_TALLY_EXCEEDS_INPUT, 422, "pieces_out exceeds pieces_in")
    start = clock.parse_dt(run["scheduled_start"])
    end = clock.parse_dt(run["scheduled_end"])
    if services.line_conflict(run["line_id"], start, end, exclude_id=run["id"]):
        raise ApiError(ERR_LINE_TIME_OVERLAP, 409, "Line buffered interval overlaps an active run")
    run["pieces_out"] = pieces_out
    run["linen_loss_pieces"] = run["pieces_in"] - pieces_out
    hours = D(int((end - start).total_seconds())) / D(3600)
    if hours > 0:
        run["throughput_pieces_per_hour"] = float(round2(D(pieces_out) / hours))
    else:
        run["throughput_pieces_per_hour"] = 0
    run["status"] = "TALLIED"
    db.touch(run)
    return success(run)


@bp.route("/finish-runs/<fid>/post", methods=["POST"])
def post_finish_run(fid):
    auth = authenticate()
    require_roles(auth, OPERATOR)
    run = path_get(db.finish_runs, fid)
    if run["status"] != "TALLIED":
        raise ApiError(ERR_INVALID_STATE, 409, "Finish run is not TALLIED")
    load = db.wash_loads.get(run["wash_load_id"])
    if load:
        cust_id = services.customer_of_wash_load(load)
        if cust_id:
            key = (cust_id, load["category_id"])
            db.clean_stock[key] = db.clean_stock.get(key, 0) + (run["pieces_out"] or 0)
    run["status"] = "POSTED"
    db.touch(run)
    return success(run)


@bp.route("/finish-runs/<fid>/void", methods=["POST"])
def void_finish_run(fid):
    auth = authenticate()
    require_roles(auth, OPERATOR)
    run = path_get(db.finish_runs, fid)
    if run["status"] != "QUEUED":
        raise ApiError(ERR_INVALID_STATE, 409, "Finish run is not QUEUED")
    run["status"] = "VOIDED"
    db.touch(run)
    return success(run)
