"""MassChangeBatch and BatchLine endpoints."""
from flask import Blueprint, request

from engine import execute_batch, rollback_batch, validate_line
from errors import ApiError
from serialize import ser_batch, ser_batch_line
from services import bump, get_or_404, is_salary_field, valid_salary_literal
from store import db
from util import (
    ALL_ROLES, auth, body, clock_date, inv, list_page, new_entity, ok,
    parse_date_val, parse_int_val, req_field,
)

bp = Blueprint("batches", __name__)


def _ser_batch(b):
    return ser_batch(b, db.batch_lines.values())


@bp.post("/hris/mass-change-batches")
def create_batch():
    auth(["HrisAnalyst"])
    b = body()
    name = req_field(b, "name")
    batch = new_entity(db.batches)
    batch.update({"name": name, "status": "DRAFT", "scheduled_effective_date": None})
    db.batches[batch["id"]] = batch
    return ok(_ser_batch(batch), code=201)


@bp.get("/hris/mass-change-batches/<batchId>")
def get_batch(batchId):
    auth(ALL_ROLES)
    batch = get_or_404(db.batches, batchId, "ERR_BATCH_NOT_FOUND")
    return ok(_ser_batch(batch))


@bp.post("/hris/mass-change-batches/<batchId>/lines")
def add_line(batchId):
    auth(["HrisAnalyst"])
    batch = get_or_404(db.batches, batchId, "ERR_BATCH_NOT_FOUND")
    b = body()
    target_worker_id = req_field(b, "target_worker_id")
    target_field_id = req_field(b, "target_field_id")
    if isinstance(target_worker_id, str):
        get_or_404(db.workers, target_worker_id, "ERR_WORKER_NOT_FOUND")
    else:
        raise inv("Invalid target_worker_id")
    if isinstance(target_field_id, str):
        field = get_or_404(db.data_fields, target_field_id, "ERR_DATA_FIELD_NOT_FOUND")
    else:
        raise inv("Invalid target_field_id")
    line_index = parse_int_val(req_field(b, "line_index"), "line_index")
    new_value = req_field(b, "new_value")
    if isinstance(new_value, (dict, list)) or new_value is None:
        raise inv("new_value must be a scalar")
    new_value = str(new_value)
    effective_date = parse_date_val(req_field(b, "effective_date"), "effective_date")
    if line_index < 0:
        raise inv("line_index must be >= 0")
    if any(l["batch_id"] == batchId and l["line_index"] == line_index
           for l in db.batch_lines.values()):
        raise inv("line_index must be unique within the batch")
    if is_salary_field(field) and not valid_salary_literal(new_value, allow_pct=True):
        raise inv("new_value must be integer cents or '+P%%' for salary lines")
    if batch["status"] != "DRAFT":
        raise ApiError("ERR_BATCH_NOT_DRAFT", 409, "Lines can only be added to a DRAFT batch")
    # §3.1: a new batch line referencing a DEPRECATED field is rejected. DRAFT
    # fields and RESTRICTED fields are accepted here and fail per line at
    # submit/execute validation (§3.5), captured in the line's error_id.
    if field["status"] == "DEPRECATED":
        raise ApiError("ERR_FIELD_NOT_ACTIVE", 409, "Data field is DEPRECATED")
    line = new_entity(db.batch_lines)
    line.update({"batch_id": batchId, "line_index": line_index,
                 "target_worker_id": target_worker_id,
                 "target_field_id": target_field_id, "new_value": new_value,
                 "effective_date": effective_date, "status": "PENDING",
                 "error_id": None, "resolved_delta_cents": None})
    db.batch_lines[line["id"]] = line
    bump(batch)
    return ok(ser_batch_line(line), code=201)


@bp.get("/hris/mass-change-batches/<batchId>/lines")
def list_batch_lines(batchId):
    auth(ALL_ROLES)
    get_or_404(db.batches, batchId, "ERR_BATCH_NOT_FOUND")
    items = [l for l in db.batch_lines.values() if l["batch_id"] == batchId]
    return list_page(items, ser_batch_line)


@bp.get("/hris/batch-lines")
def list_all_lines():
    auth(ALL_ROLES)
    items = list(db.batch_lines.values())
    for key in ("batch_id", "target_worker_id", "target_field_id", "status"):
        v = request.args.get(key)
        if v is not None:
            items = [l for l in items if l[key] == v]
    return list_page(items, ser_batch_line)


@bp.get("/hris/batch-lines/<lineId>")
def get_line(lineId):
    auth(ALL_ROLES)
    line = get_or_404(db.batch_lines, lineId, "ERR_BATCH_LINE_NOT_FOUND")
    return ok(ser_batch_line(line))


@bp.post("/hris/mass-change-batches/<batchId>/submit")
def submit_batch(batchId):
    auth(["HrisAnalyst"])
    batch = get_or_404(db.batches, batchId, "ERR_BATCH_NOT_FOUND")
    b = body()
    if "expected_batch_version" not in b or b["expected_batch_version"] is None:
        raise inv("expected_batch_version is required")
    expected = parse_int_val(b["expected_batch_version"], "expected_batch_version")
    if expected != batch["version"]:
        raise ApiError("ERR_STALE_BATCH_VERSION", 412,
                       "expected_batch_version does not match current version")
    if batch["status"] != "DRAFT":
        raise ApiError("ERR_BATCH_NOT_DRAFT", 409, "Submit requires DRAFT")
    lines = [l for l in db.batch_lines.values() if l["batch_id"] == batchId]
    lines.sort(key=lambda l: (l["line_index"], l["created_at"], l["_seq"]))
    any_failed = False
    for line in lines:
        err = validate_line(line)
        if err is not None:
            line["status"] = "FAILED"
            line["error_id"] = err
            any_failed = True
        else:
            line["status"] = "VALIDATED"
            line["error_id"] = None
        bump(line)
    batch["status"] = "VALIDATION_FAILED" if any_failed else "VALIDATED"
    bump(batch)
    return ok(_ser_batch(batch))


@bp.post("/hris/mass-change-batches/<batchId>/reopen")
def reopen_batch(batchId):
    auth(["HrisAnalyst"])
    batch = get_or_404(db.batches, batchId, "ERR_BATCH_NOT_FOUND")
    if batch["status"] != "VALIDATION_FAILED":
        raise ApiError("ERR_BATCH_NOT_REOPENABLE", 409,
                       "Reopen requires VALIDATION_FAILED")
    for line in db.batch_lines.values():
        if line["batch_id"] == batchId:
            line["status"] = "PENDING"
            line["error_id"] = None
            bump(line)
    batch["status"] = "DRAFT"
    bump(batch)
    return ok(_ser_batch(batch))


@bp.post("/hris/mass-change-batches/<batchId>/schedule")
def schedule_batch(batchId):
    auth(["HrisAnalyst"])
    batch = get_or_404(db.batches, batchId, "ERR_BATCH_NOT_FOUND")
    b = body()
    sched = parse_date_val(req_field(b, "scheduled_effective_date"),
                           "scheduled_effective_date")
    if batch["status"] != "VALIDATED":
        raise ApiError("ERR_BATCH_NOT_EXECUTABLE", 409, "Schedule requires VALIDATED")
    if sched < clock_date():
        raise ApiError("ERR_EFFECTIVE_DATE_OUT_OF_WINDOW", 422,
                       "scheduled_effective_date must not precede the clock date")
    batch["scheduled_effective_date"] = sched
    batch["status"] = "SCHEDULED"
    bump(batch)
    return ok(_ser_batch(batch))


@bp.post("/hris/mass-change-batches/<batchId>/execute")
def execute(batchId):
    caller = auth(["HrisAnalyst"])
    batch = get_or_404(db.batches, batchId, "ERR_BATCH_NOT_FOUND")
    if batch["status"] != "SCHEDULED":
        raise ApiError("ERR_BATCH_NOT_EXECUTABLE", 409, "Execute requires SCHEDULED")
    execute_batch(batch, caller)
    return ok(_ser_batch(batch))


@bp.post("/hris/mass-change-batches/<batchId>/rollback")
def rollback(batchId):
    caller = auth(["HrisAnalyst"])
    batch = get_or_404(db.batches, batchId, "ERR_BATCH_NOT_FOUND")
    if batch["status"] != "COMPLETED_WITH_ERRORS":
        raise ApiError("ERR_BATCH_NOT_ROLLBACKABLE", 409,
                       "Rollback requires COMPLETED_WITH_ERRORS")
    rollback_batch(batch, caller)
    return ok(_ser_batch(batch))
