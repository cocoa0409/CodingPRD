"""Shared cost pool absorption and sealing (PRD 3.5)."""
from flask import Blueprint

from db import db, touch
from errors import fail
from middleware import authorize
from routes.common import lookup, serve
from services import derived
from validation import body, req_str_list

bp = Blueprint("shared_cost_pools", __name__)


@bp.route("/finops/shared-cost-pools/<pool_id>", methods=["GET"])
@authorize("FinOpsAnalyst", "FinOpsController", "PlatformAdmin")
def get_pool(pool_id):
    pool = lookup("shared_cost_pools", pool_id)
    derived.pool_sync(pool, bump=False)
    return serve(pool)


@bp.route("/finops/shared-cost-pools/<pool_id>/absorb-untagged", methods=["POST"])
@authorize("FinOpsAnalyst")
def absorb_untagged(pool_id):
    pool = lookup("shared_cost_pools", pool_id)
    data = body()
    record_ids = req_str_list(data, "cost_record_ids")

    if pool["status"] != "OPEN":
        fail("ERR_POOL_STATE_INVALID", "Only an OPEN pool may absorb cost records.")

    if not record_ids:
        fail("ERR_UNTAGGED_ABSORB_EMPTY", "cost_record_ids must name at least one record.")

    run = db.allocation_runs.get(pool["allocation_run_id"])
    named = [db.cost_records.get(rid) for rid in record_ids]

    matched = []
    for record in named:
        if record is None:
            continue
        if record["allocation_state"] != "UNALLOCATED":
            continue
        if record["business_unit_id"] is not None:
            continue
        if run is not None:
            if record["_billing_period_start_dt"] < run["_period_start_dt"]:
                continue
            if record["_billing_period_end_dt"] > run["_period_end_dt"]:
                continue
        matched.append(record)

    if not matched:
        fail(
            "ERR_UNTAGGED_ABSORB_EMPTY",
            "No named cost record matches unallocated untagged spend inside the run period.",
        )

    for record in named:
        if record is not None and record["allocation_state"] in ("ALLOCATED", "REVERSED"):
            fail(
                "ERR_COST_RECORD_ALREADY_ALLOCATED",
                "Cost record %s is already %s." % (record["id"], record["allocation_state"]),
            )

    for record in matched:
        record["shared_cost_pool_id"] = pool["id"]
        touch(record)

    derived.pool_sync(pool)
    return serve(pool)


@bp.route("/finops/shared-cost-pools/<pool_id>/seal", methods=["POST"])
@authorize("FinOpsAnalyst")
def seal_pool(pool_id):
    pool = lookup("shared_cost_pools", pool_id)
    if pool["status"] != "OPEN":
        fail("ERR_POOL_STATE_INVALID", "Only an OPEN pool may be sealed.")
    pool["status"] = "SEALED"
    derived.pool_sync(pool, bump=False)
    touch(pool)
    return serve(pool)
