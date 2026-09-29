"""Cycle-count schedules, tasks, lines and submission (PRD 3.4, 3.5)."""

from decimal import Decimal

from flask import Blueprint

import calc
from db import clock_now_iso, db, new_id
from errors import ApiError
from middleware import acting_user, require_read, require_roles, scope_store
from response import created, ok, ok_list, paginate, read_pagination
from validate import (S, body_json, filter_enum, filter_str, lookup, parse_body,
                      parse_date, parse_instant)

bp = Blueprint("counts", __name__)
PREFIX = "/inventory-integrity"

READER_MODES = ("HANDHELD", "OVERHEAD")
SCHEDULE_STATUSES = ("ACTIVE", "PAUSED", "RETIRED")
TASK_STATUSES = ("SCHEDULED", "IN_PROGRESS", "COUNTED", "RECONCILED", "VOIDED")

CAPABILITY_MODES = {
    "HANDHELD_ONLY": ("HANDHELD",),
    "OVERHEAD_ONLY": ("OVERHEAD",),
    "BOTH": ("HANDHELD", "OVERHEAD"),
}


def _list(collection, predicates):
    matched = [r for r in getattr(db, collection).values()
               if all(r.get(key) == value for key, value in predicates)]
    limit, offset = read_pagination()
    page, total = paginate(calc.newest_first(matched), limit, offset)
    return ok_list(page, limit, offset, total)


def _require_store_supports(store, reader_mode):
    if reader_mode not in CAPABILITY_MODES[store["reader_capability"]]:
        raise ApiError("ERR_READER_MODE_UNSUPPORTED",
                       "the store's reader_capability does not support %s" % reader_mode)


def _require_category_permits(category, reader_mode):
    required = category["reader_mode_required"]
    if required != "EITHER" and required != reader_mode:
        raise ApiError("ERR_CATEGORY_READER_MODE_MISMATCH",
                       "the category requires reader mode %s" % required)


# --------------------------------------------------------------------------
# CountSchedule
# --------------------------------------------------------------------------
SCHEDULE_SPECS = [
    S("first_due_date", "date"),
    S("cadence_days", "int", required=False, min=7, max=365),
    S("reader_mode", "enum", allowed=READER_MODES),
]

NOTE_SPECS = [S("note", "str", required=False, max_len=2000)]


@bp.post(PREFIX + "/count-schedules")
def create_count_schedule():
    require_roles("InventoryAnalyst", "InventorySupervisor")
    body = body_json()
    store = lookup("stores", body.get("store_id"))
    category = lookup("categories", body.get("category_id"))
    data = parse_body(body, SCHEDULE_SPECS)
    _require_store_supports(store, data["reader_mode"])
    _require_category_permits(category, data["reader_mode"])
    cadence = data.get("cadence_days")
    if cadence is None:
        cadence = category["count_cadence_days"]
    row = calc.base_row({"id": new_id()})
    record = {
        "id": row["id"],
        "store_id": store["id"],
        "category_id": category["id"],
        "cadence_days": cadence,
        "reader_mode": data["reader_mode"],
        "first_due_date": data["first_due_date"].isoformat(),
        "next_due_date": data["first_due_date"].isoformat(),
        "status": "ACTIVE",
        "completed_cycle_count": 0,
    }
    record.update({k: row[k] for k in ("created_at", "updated_at", "version", "_seq")})
    db.count_schedules[record["id"]] = record
    return created(record)


@bp.get(PREFIX + "/count-schedules/<count_schedule_id>")
def get_count_schedule(count_schedule_id):
    require_read()
    return ok(lookup("count_schedules", count_schedule_id))


@bp.get(PREFIX + "/count-schedules")
def list_count_schedules():
    require_read()
    status = filter_enum("status", SCHEDULE_STATUSES)
    predicates = []
    for param in ("store_id", "category_id"):
        value = filter_str(param)
        if value is not None:
            predicates.append((param, value))
    if status is not None:
        predicates.append(("status", status))
    return _list("count_schedules", predicates)


@bp.post(PREFIX + "/count-schedules/<count_schedule_id>/pause")
def pause_count_schedule(count_schedule_id):
    require_roles("InventorySupervisor", "ShrinkController")
    schedule = lookup("count_schedules", count_schedule_id)
    parse_body(body_json(), NOTE_SPECS)
    if schedule["status"] != "ACTIVE":
        raise ApiError("ERR_COUNT_SCHEDULE_NOT_ACTIVE",
                       "only an ACTIVE schedule may be paused")
    schedule["status"] = "PAUSED"
    calc.touch(schedule)
    return ok(schedule)


@bp.post(PREFIX + "/count-schedules/<count_schedule_id>/resume")
def resume_count_schedule(count_schedule_id):
    require_roles("InventorySupervisor", "ShrinkController")
    schedule = lookup("count_schedules", count_schedule_id)
    parse_body(body_json(), [])
    if schedule["status"] != "PAUSED":
        raise ApiError("ERR_COUNT_SCHEDULE_NOT_ACTIVE",
                       "only a PAUSED schedule may be resumed")
    schedule["status"] = "ACTIVE"
    calc.touch(schedule)
    return ok(schedule)


# --------------------------------------------------------------------------
# CountTask
# --------------------------------------------------------------------------
TASK_SPECS = [
    S("window_start", "datetime"),
    S("window_end", "datetime"),
    S("reader_mode", "enum", allowed=READER_MODES),
]


@bp.post(PREFIX + "/count-tasks")
def create_count_task():
    require_roles("InventoryAnalyst", "InventorySupervisor")
    body = body_json()
    schedule = lookup("count_schedules", body.get("count_schedule_id"))
    data = parse_body(body, TASK_SPECS)
    store = db.stores[schedule["store_id"]]
    if schedule["status"] != "ACTIVE":
        raise ApiError("ERR_COUNT_SCHEDULE_NOT_ACTIVE",
                       "the backing schedule is not ACTIVE")
    _require_store_supports(store, data["reader_mode"])
    window_start = data["window_start"]
    window_end = data["window_end"]
    # Check A — same store and category exclusivity.
    if calc.overlapping_tasks(store["id"], schedule["category_id"],
                              window_start, window_end):
        raise ApiError("ERR_COUNT_WINDOW_OVERLAP",
                       "another count task already holds an overlapping window")
    # Check B — aggregate overhead reader capacity.
    if data["reader_mode"] == "OVERHEAD":
        busy = calc.overlapping_tasks(store["id"], None, window_start, window_end,
                                      reader_mode="OVERHEAD")
        if len(busy) >= store["overhead_reader_capacity"]:
            raise ApiError("ERR_OVERHEAD_READER_CAPACITY_EXCEEDED",
                           "the store's overhead reader pool is fully committed")
    if window_start.date().isoformat() < schedule["next_due_date"]:
        raise ApiError("ERR_COUNT_WINDOW_NOT_DUE",
                       "window_start precedes the schedule's next_due_date")
    if not window_end > window_start:
        raise ApiError("ERR_INVALID_WINDOW", "window_end must be after window_start")
    row = calc.base_row({"id": new_id()})
    record = {
        "id": row["id"],
        "count_schedule_id": schedule["id"],
        "store_id": store["id"],
        "category_id": schedule["category_id"],
        "reader_mode": data["reader_mode"],
        "window_start": body["window_start"],
        "window_end": body["window_end"],
        "status": "SCHEDULED",
        "recount_round": 0,
        "in_scope_position_count": 0,
        "counted_line_count": 0,
        "coverage_pct": Decimal("0.00"),
        "variance_line_count": 0,
        "total_variance_value_cents": 0,
        "_window_start": window_start,
        "_window_end": window_end,
    }
    record.update({k: row[k] for k in ("created_at", "updated_at", "version", "_seq")})
    db.count_tasks[record["id"]] = record
    return created(record)


@bp.get(PREFIX + "/count-tasks/<count_task_id>")
def get_count_task(count_task_id):
    require_read()
    return ok(lookup("count_tasks", count_task_id))


@bp.get(PREFIX + "/count-tasks")
def list_count_tasks():
    require_read()
    status = filter_enum("status", TASK_STATUSES)
    predicates = []
    for param in ("count_schedule_id", "store_id", "category_id"):
        value = filter_str(param)
        if value is not None:
            predicates.append((param, value))
    if status is not None:
        predicates.append(("status", status))
    return _list("count_tasks", predicates)


def _bad_task_state(message):
    raise ApiError("ERR_COUNT_TASK_INVALID_STATE", message)


@bp.post(PREFIX + "/count-tasks/<count_task_id>/start")
def start_count_task(count_task_id):
    require_roles("StoreOps", "InventoryAnalyst", "InventorySupervisor")
    task = lookup("count_tasks", count_task_id)
    scope_store(task["store_id"])
    parse_body(body_json(), [])
    if task["status"] != "SCHEDULED":
        _bad_task_state("only a SCHEDULED task may be started")
    schedule = db.count_schedules[task["count_schedule_id"]]
    if schedule["status"] != "ACTIVE":
        raise ApiError("ERR_COUNT_SCHEDULE_NOT_ACTIVE",
                       "the backing schedule is no longer ACTIVE")
    in_scope = 0
    for position in calc.rows("stock_positions"):
        if position["store_id"] != task["store_id"]:
            continue
        item = db.items[position["item_id"]]
        if item["category_id"] == task["category_id"]:
            in_scope += 1
    task["in_scope_position_count"] = in_scope
    task["status"] = "IN_PROGRESS"
    task["coverage_pct"] = calc.count_coverage_pct(task)
    calc.touch(task)
    return ok(task)


# --------------------------------------------------------------------------
# CountLine
# --------------------------------------------------------------------------
LINE_SPECS = [
    S("counted_units", "int", min=0),
    S("read_mode_used", "enum", allowed=READER_MODES),
]


@bp.post(PREFIX + "/count-tasks/<count_task_id>/lines")
def create_count_line(count_task_id):
    require_roles("StoreOps", "InventoryAnalyst")
    task = lookup("count_tasks", count_task_id)
    scope_store(task["store_id"])
    body = body_json()
    item = lookup("items", body.get("item_id"))
    data = parse_body(body, LINE_SPECS)
    if task["status"] != "IN_PROGRESS":
        _bad_task_state("lines may only be recorded against an IN_PROGRESS task")
    if item["category_id"] != task["category_id"]:
        raise ApiError("ERR_ITEM_CATEGORY_MISMATCH",
                       "the SKU does not belong to the task's category")
    position = calc.position_for(task["store_id"], item["id"])
    if position is None:
        raise ApiError("ERR_ITEM_NOT_STOCKED_AT_STORE",
                       "no stock position exists for this store and SKU")
    for line in calc.rows("count_lines"):
        if line["count_task_id"] == task["id"] and line["item_id"] == item["id"]:
            raise ApiError("ERR_DUPLICATE_COUNT_LINE",
                           "this SKU already has a counted line on the task")
    store = db.stores[task["store_id"]]
    _require_store_supports(store, data["read_mode_used"])

    category = db.categories[item["category_id"]]
    snapshot_units = position["on_hand_units"]
    variance_units = data["counted_units"] - snapshot_units
    variance_value_cents = calc.count_variance_valuation(variance_units, item, category)
    row = calc.base_row({"id": new_id()})
    record = {
        "id": row["id"],
        "count_task_id": task["id"],
        "item_id": item["id"],
        "stock_position_id": position["id"],
        "counted_units": data["counted_units"],
        "system_units_snapshot": snapshot_units,
        "read_mode_used": data["read_mode_used"],
        "variance_units": variance_units,
        "variance_value_cents": variance_value_cents,
        "within_tolerance": calc.within_tolerance(variance_units, variance_value_cents,
                                                  category),
    }
    record.update({k: row[k] for k in ("created_at", "updated_at", "version", "_seq")})
    db.count_lines[record["id"]] = record
    task["counted_line_count"] += 1
    task["coverage_pct"] = calc.count_coverage_pct(task)
    calc.touch(task)
    return created(record)


@bp.get(PREFIX + "/count-lines/<count_line_id>")
def get_count_line(count_line_id):
    require_read()
    return ok(lookup("count_lines", count_line_id))


@bp.get(PREFIX + "/count-lines")
def list_count_lines():
    require_read()
    predicates = []
    for param in ("count_task_id", "item_id", "stock_position_id"):
        value = filter_str(param)
        if value is not None:
            predicates.append((param, value))
    return _list("count_lines", predicates)


def _task_lines(task_id):
    return [line for line in calc.rows("count_lines") if line["count_task_id"] == task_id]


# --------------------------------------------------------------------------
# submission and closure (PRD 3.5)
# --------------------------------------------------------------------------

def _open_investigation(line, task, period):
    row = calc.base_row({"id": new_id()})
    record = {
        "id": row["id"],
        "count_line_id": line["id"],
        "store_id": task["store_id"],
        "shrink_period_id": period["id"] if period else None,
        "variance_units": line["variance_units"],
        "variance_value_cents": line["variance_value_cents"],
        "status": "OPEN",
        "assigned_investigator_id": None,
        "proposed_root_cause": None,
        "approved_root_cause": None,
        "proposed_by_user_id": None,
        "approved_by_user_id": None,
        "proposal_round": 0,
        "evidence_note": None,
        "_stock_position_id": line["stock_position_id"],
        "_item_id": line["item_id"],
        "_count_task_id": task["id"],
    }
    record.update({k: row[k] for k in ("created_at", "updated_at", "version", "_seq")})
    db.investigations[record["id"]] = record
    return record


@bp.post(PREFIX + "/count-tasks/<count_task_id>/submit")
def submit_count_task(count_task_id):
    require_roles("StoreOps", "InventoryAnalyst", "InventorySupervisor")
    task = lookup("count_tasks", count_task_id)
    scope_store(task["store_id"])
    parse_body(body_json(), [])
    if task["status"] != "IN_PROGRESS":
        _bad_task_state("only an IN_PROGRESS task may be submitted")
    lines = _task_lines(task["id"])
    if task["counted_line_count"] < 1:
        raise ApiError("ERR_NO_COUNT_LINES", "the task carries no counted lines")
    coverage = calc.count_coverage_pct(task)
    if coverage < calc.MIN_COVERAGE_PCT:
        raise ApiError("ERR_COUNT_COVERAGE_BELOW_MIN",
                       "weighted coverage_pct is below 90.00")
    out_of_tolerance = [line for line in lines if not line["within_tolerance"]]
    period = None
    if out_of_tolerance:
        period = calc.covering_period(task["store_id"], task["_window_end"].date(),
                                      ("OPEN", "PROVISIONAL_CLOSED"))
        if period is None:
            raise ApiError("ERR_NO_COVERING_SHRINK_PERIOD",
                           "no OPEN or PROVISIONAL_CLOSED shrink period covers window_end")

    task["coverage_pct"] = coverage
    task["variance_line_count"] = len(out_of_tolerance)
    task["total_variance_value_cents"] = sum(line["variance_value_cents"] for line in lines)

    stamp = clock_now_iso()
    touched = []
    for line in lines:
        position = db.stock_positions.get(line["stock_position_id"])
        if position is None:
            continue
        item = db.items[line["item_id"]]
        position["last_counted_at"] = stamp
        position["last_variance_units"] = line["variance_units"]
        position["last_variance_value_cents"] = line["variance_value_cents"]
        position["last_count_system_units"] = line["system_units_snapshot"]
        position["last_count_book_value_cents"] = (line["system_units_snapshot"]
                                                  * item["unit_cost_cents"])
        unit_pct, value_pct = calc.stock_accuracy_pct(position)
        position["unit_accuracy_pct"] = unit_pct
        position["value_accuracy_pct"] = value_pct
        if position["id"] not in touched:
            touched.append(position["id"])

    for line in out_of_tolerance:
        _open_investigation(line, task, period)
    if period is not None:
        calc.recompute_period(period)

    calc.settle(touched)
    task["status"] = "COUNTED"
    calc.touch(task)
    return ok(task)


@bp.post(PREFIX + "/count-tasks/<count_task_id>/return-to-count")
def return_count_task(count_task_id):
    require_roles("InventorySupervisor", "ShrinkController")
    task = lookup("count_tasks", count_task_id)
    parse_body(body_json(), NOTE_SPECS)
    if task["status"] != "COUNTED":
        _bad_task_state("only a COUNTED task may be returned to the floor")
    if task["recount_round"] >= calc.MAX_RECOUNT_ROUNDS:
        raise ApiError("ERR_REWORK_LIMIT_REACHED",
                       "the task has already been returned to the floor once")
    task["recount_round"] += 1
    lines = _task_lines(task["id"])
    deleted_ids = set()
    touched = []
    for line in lines:
        deleted_ids.add(line["id"])
        if line["stock_position_id"] not in touched:
            touched.append(line["stock_position_id"])
        db.count_lines.pop(line["id"], None)
    task["counted_line_count"] = 0
    task["coverage_pct"] = Decimal("0.00")
    task["variance_line_count"] = 0
    task["total_variance_value_cents"] = 0
    task["status"] = "IN_PROGRESS"

    periods = []
    for investigation in calc.rows("investigations"):
        if investigation["count_line_id"] in deleted_ids and investigation["status"] == "OPEN":
            investigation["status"] = "WAIVED"
            calc.touch(investigation)
            period_id = investigation.get("shrink_period_id")
            if period_id and period_id not in periods:
                periods.append(period_id)
    for period_id in periods:
        period = db.shrink_periods.get(period_id)
        if period is not None:
            calc.recompute_period(period)

    calc.settle(touched)
    calc.touch(task)
    return ok(task)


@bp.post(PREFIX + "/count-tasks/<count_task_id>/reconcile")
def reconcile_count_task(count_task_id):
    require_roles("InventorySupervisor", "ShrinkController")
    task = lookup("count_tasks", count_task_id)
    parse_body(body_json(), [])
    if task["status"] != "COUNTED":
        _bad_task_state("only a COUNTED task may be reconciled")
    for investigation in calc.rows("investigations"):
        if (investigation.get("_count_task_id") == task["id"]
                and investigation["status"] not in ("CLOSED", "WAIVED")):
            raise ApiError("ERR_OPEN_INVESTIGATIONS",
                           "an investigation opened by this task is still unresolved")
    task["status"] = "RECONCILED"
    calc.touch(task)
    schedule = db.count_schedules[task["count_schedule_id"]]
    schedule["completed_cycle_count"] += 1
    from db import timedelta
    schedule["next_due_date"] = (task["_window_end"].date()
                                 + timedelta(days=schedule["cadence_days"])).isoformat()
    calc.touch(schedule)
    return ok(task)


@bp.post(PREFIX + "/count-tasks/<count_task_id>/void")
def void_count_task(count_task_id):
    require_roles("InventorySupervisor", "ShrinkController")
    task = lookup("count_tasks", count_task_id)
    parse_body(body_json(), NOTE_SPECS)
    if task["status"] not in ("SCHEDULED", "IN_PROGRESS"):
        _bad_task_state("only a SCHEDULED or IN_PROGRESS task may be voided")
    for line in _task_lines(task["id"]):
        db.count_lines.pop(line["id"], None)
    task["counted_line_count"] = 0
    task["status"] = "VOIDED"
    calc.touch(task)
    return ok(task)
