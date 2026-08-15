"""MigrationBatch endpoints (PRD 3.7)."""

from flask import Blueprint

from db import STORE
from errors import (
    ApiError,
    ERR_MIGRATION_INVALID_STATE,
    ERR_MIGRATION_TARGET_NOT_EFFECTIVE,
    ERR_SHEET_NOT_FOUND,
    bad_request,
    not_found,
)
from middleware import get_body, paginate, query_enum, require_roles
from response import ok_object
from serialize import serialize, serialize_many
from services.cascade import execute_migration
from utils import bump, req_enum, req_str, stamp_new

bp = Blueprint("migrations", __name__)

MIGRATION_STATUSES = ("PLANNED", "COMPLETED", "ABORTED")
MIGRATION_ACTIONS = ("EXECUTE", "ABORT")


@bp.post("/migration-batches")
@require_roles("OperationsAdmin")
def create_batch():
    data = get_body()
    source_sheet_id = req_str(data, "source_sheet_id")
    target_sheet_id = req_str(data, "target_sheet_id")
    if source_sheet_id not in STORE["sheets"]:
        raise ApiError(ERR_SHEET_NOT_FOUND, 422,
                       "Referenced source_sheet_id does not exist")
    if target_sheet_id not in STORE["sheets"]:
        raise ApiError(ERR_SHEET_NOT_FOUND, 422,
                       "Referenced target_sheet_id does not exist")
    row = {
        "source_sheet_id": source_sheet_id,
        "target_sheet_id": target_sheet_id,
        "migrated_count": 0,
        "skipped_count": 0,
        "status": "PLANNED",
    }
    stamp_new(row)
    STORE["migrations"][row["id"]] = row
    return ok_object(serialize("migrations", row), 201)


@bp.get("/migration-batches")
@require_roles("OperationsAdmin", "PricingAnalyst")
def list_batches():
    from flask import request
    source_sheet_id = request.args.get("source_sheet_id")
    target_sheet_id = request.args.get("target_sheet_id")
    status = query_enum("status", MIGRATION_STATUSES)
    rows = list(STORE["migrations"].values())
    if source_sheet_id is not None:
        rows = [r for r in rows if r["source_sheet_id"] == source_sheet_id]
    if target_sheet_id is not None:
        rows = [r for r in rows if r["target_sheet_id"] == target_sheet_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return paginate(serialize_many("migrations", rows))


@bp.get("/migration-batches/<batch_id>")
@require_roles("OperationsAdmin", "PricingAnalyst")
def get_batch(batch_id):
    row = STORE["migrations"].get(batch_id)
    if row is None:
        raise not_found("Migration batch not found")
    return ok_object(serialize("migrations", row))


@bp.post("/migration-batches/<batch_id>/execution")
@require_roles("OperationsAdmin")
def execute_batch(batch_id):
    data = get_body()
    action = req_enum(data, "action", MIGRATION_ACTIONS)
    row = STORE["migrations"].get(batch_id)
    if row is None:
        raise not_found("Migration batch not found")
    if action == "ABORT":
        if row["status"] != "PLANNED":
            raise ApiError(ERR_MIGRATION_INVALID_STATE, 409,
                           f"Cannot ABORT a batch in {row['status']}")
        row["status"] = "ABORTED"
        bump(row)
        return ok_object(serialize("migrations", row))
    # EXECUTE: batch + source state, then target effectiveness, then pair match.
    if row["status"] != "PLANNED":
        raise ApiError(ERR_MIGRATION_INVALID_STATE, 409,
                       f"Cannot EXECUTE a batch in {row['status']}")
    src = STORE["sheets"][row["source_sheet_id"]]
    tgt = STORE["sheets"][row["target_sheet_id"]]
    if src["status"] != "SUPERSEDED":
        raise ApiError(ERR_MIGRATION_INVALID_STATE, 409,
                       "Source sheet must be SUPERSEDED")
    if tgt["status"] != "EFFECTIVE":
        raise ApiError(ERR_MIGRATION_TARGET_NOT_EFFECTIVE, 422,
                       "Target sheet must be EFFECTIVE")
    if (src["product_id"] != tgt["product_id"]
            or src["market_code"] != tgt["market_code"]):
        raise bad_request("Source and target sheets must share product and market")
    execute_migration(row)
    return ok_object(serialize("migrations", row))
