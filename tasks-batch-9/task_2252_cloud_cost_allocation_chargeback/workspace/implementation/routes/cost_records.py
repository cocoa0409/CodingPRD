"""Billing ingestion (PRD 3.4)."""
from flask import Blueprint

from db import base_fields, db
from middleware import authorize
from routes.common import lookup, optional_ref, serve, serve_list
from services import derived
from validation import body, present, req_enum, req_int, req_interval

bp = Blueprint("cost_records", __name__)

KINDS = ("COMPUTE", "DATABASE", "STORAGE")


@bp.route("/finops/cost-records", methods=["POST"])
@authorize("PlatformAdmin", "FinOpsAnalyst")
def ingest_cost_record():
    data = body()
    resource = None
    if present(data, "cloud_resource_id"):
        resource = optional_ref("cloud_resources", data.get("cloud_resource_id"))
    (start_raw, start), (end_raw, end) = req_interval(
        data, "billing_period_start", "billing_period_end"
    )
    resource_kind = req_enum(data, "resource_kind", KINDS)
    list_cost = req_int(data, "list_cost_cents", minimum=0)

    record = base_fields()
    record.update(
        {
            "cloud_resource_id": resource["id"] if resource else None,
            "shared_cost_pool_id": None,
            "business_unit_id": resource["business_unit_id"] if resource else None,
            "applied_commitment_id": None,
            "allocated_by_run_id": None,
            "billing_period_start": start_raw,
            "billing_period_end": end_raw,
            "resource_kind": resource_kind,
            "list_cost_cents": list_cost,
            "effective_cost_cents": list_cost,
            "allocation_state": "UNALLOCATED",
            "_billing_period_start_dt": start,
            "_billing_period_end_dt": end,
        }
    )
    db.cost_records[record["id"]] = record
    if record["business_unit_id"]:
        derived.bu_sync_id(record["business_unit_id"])
    return serve(record, 201)


@bp.route("/finops/cost-records", methods=["GET"])
@authorize("FinOpsAnalyst", "FinOpsController", "PlatformAdmin")
def list_cost_records():
    return serve_list(
        db.cost_records.values(),
        {
            "cloud_resource_id": "cloud_resource_id",
            "shared_cost_pool_id": "shared_cost_pool_id",
            "business_unit_id": "business_unit_id",
            "applied_commitment_id": "applied_commitment_id",
            "allocated_by_run_id": "allocated_by_run_id",
            "allocation_state": "allocation_state",
        },
    )


@bp.route("/finops/cost-records/<record_id>", methods=["GET"])
@authorize("FinOpsAnalyst", "FinOpsController", "PlatformAdmin")
def get_cost_record(record_id):
    return serve(lookup("cost_records", record_id))
