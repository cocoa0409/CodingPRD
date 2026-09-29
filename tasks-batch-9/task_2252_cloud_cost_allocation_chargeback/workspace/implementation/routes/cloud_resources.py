"""Cloud resources and telemetry (PRD 3.3, 3.8)."""
from flask import Blueprint

from db import db, touch
from errors import fail
from middleware import authorize
from routes.common import lookup, serve, serve_list
from services import derived
from services.calc import RIGHTSIZE_UTILIZATION_MAX_PCT, D, pct2
from validation import body, opt_int, present, req_number

bp = Blueprint("cloud_resources", __name__)

READERS = ("FinOpsAnalyst", "FinOpsController", "PlatformAdmin", "ResourceOwner")


@bp.route("/finops/cloud-resources", methods=["GET"])
@authorize(*READERS)
def list_resources():
    return serve_list(
        db.cloud_resources.values(),
        {
            "provisioning_request_id": "provisioning_request_id",
            "business_unit_id": "business_unit_id",
            "tag_state": "tag_state",
            "lifecycle_state": "lifecycle_state",
        },
    )


@bp.route("/finops/cloud-resources/<resource_id>", methods=["GET"])
@authorize(*READERS)
def get_resource(resource_id):
    return serve(lookup("cloud_resources", resource_id))


@bp.route("/finops/cloud-resources/<resource_id>/telemetry", methods=["PATCH"])
@authorize("PlatformAdmin")
def push_telemetry(resource_id):
    resource = lookup("cloud_resources", resource_id)
    data = body()
    utilization = req_number(data, "utilization_pct", minimum=0, maximum=100)
    run_rate = opt_int(data, "monthly_run_rate_cents", minimum=0) if present(
        data, "monthly_run_rate_cents"
    ) else None

    if resource["lifecycle_state"] == "TERMINATED":
        fail("ERR_RESOURCE_STATE_INVALID", "A TERMINATED resource accepts no further action.")

    resource["utilization_pct"] = pct2(utilization)
    if run_rate is not None:
        resource["monthly_run_rate_cents"] = run_rate
    if resource["lifecycle_state"] == "RESIZED" and D(utilization) > RIGHTSIZE_UTILIZATION_MAX_PCT:
        resource["lifecycle_state"] = "ACTIVE"
    touch(resource)
    derived.bu_sync_id(resource["business_unit_id"])
    return serve(resource)
