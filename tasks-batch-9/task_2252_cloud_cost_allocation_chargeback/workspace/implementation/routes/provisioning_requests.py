"""Provisioning requests and the cloud resources they create (PRD 3.3)."""
from flask import Blueprint

from db import base_fields, db, now, touch
from errors import fail
from middleware import authorize
from routes.common import lookup, optional_ref, serve, serve_list
from services import derived
from services.calc import tag_compliance
from validation import body, req_enum, req_int, req_object, req_str

bp = Blueprint("provisioning_requests", __name__)

KINDS = ("COMPUTE", "DATABASE", "STORAGE")


def _evaluate(request_row, policy):
    missing, score, state = tag_compliance(
        policy["mandatory_dimensions"], request_row["requested_tags"]
    )
    request_row["missing_dimensions"] = missing
    request_row["compliance_score"] = score
    request_row["projected_tag_state"] = state
    return missing


@bp.route("/finops/provisioning-requests", methods=["POST"])
@authorize("FinOpsAnalyst", "PlatformAdmin")
def create_request():
    data = body()
    policy = optional_ref("tagging_policies", req_str(data, "tagging_policy_id"))
    bu = optional_ref("business_units", req_str(data, "business_unit_id"))
    resource_kind = req_enum(data, "resource_kind", KINDS)
    requested_tags = req_object(data, "requested_tags")
    run_rate = req_int(data, "monthly_run_rate_cents", minimum=0)
    owner_user_id = req_str(data, "owner_user_id")

    if policy["status"] != "ACTIVE":
        fail("ERR_POLICY_NOT_ACTIVE", "The referenced tagging policy is not ACTIVE.")

    row = base_fields()
    row.update(
        {
            "tagging_policy_id": policy["id"],
            "business_unit_id": bu["id"],
            "resource_kind": resource_kind,
            "requested_tags": requested_tags,
            "monthly_run_rate_cents": run_rate,
            "owner_user_id": owner_user_id,
            "status": "SUBMITTED",
            "missing_dimensions": [],
            "compliance_score": 0.00,
            "projected_tag_state": "UNTAGGED",
            "retag_count": 0,
        }
    )
    missing = _evaluate(row, policy)
    if policy["enforcement_mode"] == "BLOCKING" and missing:
        row["status"] = "TAG_REJECTED"
    db.provisioning_requests[row["id"]] = row
    derived.policy_sync(policy)
    return serve(row, 201)


@bp.route("/finops/provisioning-requests", methods=["GET"])
@authorize("FinOpsAnalyst", "FinOpsController", "PlatformAdmin")
def list_requests():
    return serve_list(
        db.provisioning_requests.values(),
        {
            "tagging_policy_id": "tagging_policy_id",
            "business_unit_id": "business_unit_id",
            "status": "status",
        },
    )


@bp.route("/finops/provisioning-requests/<request_id>", methods=["GET"])
@authorize("FinOpsAnalyst", "FinOpsController", "PlatformAdmin")
def get_request(request_id):
    return serve(lookup("provisioning_requests", request_id))


@bp.route("/finops/provisioning-requests/<request_id>/retag", methods=["POST"])
@authorize("FinOpsAnalyst")
def retag_request(request_id):
    row = lookup("provisioning_requests", request_id)
    data = body()
    requested_tags = req_object(data, "requested_tags")

    if row["status"] != "TAG_REJECTED":
        fail("ERR_REQUEST_STATE_INVALID", "Only a TAG_REJECTED request may be retagged.")
    policy = db.tagging_policies.get(row["tagging_policy_id"])
    if policy is None or policy["status"] != "ACTIVE":
        fail("ERR_POLICY_NOT_ACTIVE", "The referenced tagging policy is not ACTIVE.")

    row["requested_tags"] = requested_tags
    missing = _evaluate(row, policy)
    row["retag_count"] = row["retag_count"] + 1
    if policy["enforcement_mode"] == "BLOCKING" and missing:
        row["status"] = "TAG_REJECTED"
    else:
        row["status"] = "SUBMITTED"
    touch(row)
    derived.policy_sync(policy)
    return serve(row)


@bp.route("/finops/provisioning-requests/<request_id>/approve", methods=["POST"])
@authorize("FinOpsAnalyst")
def approve_request(request_id):
    row = lookup("provisioning_requests", request_id)
    if row["status"] != "SUBMITTED":
        fail("ERR_REQUEST_STATE_INVALID", "Only a SUBMITTED request may be approved.")

    bu = db.business_units.get(row["business_unit_id"])
    if bu is None or bu["status"] != "ACTIVE":
        fail("ERR_BU_SUSPENDED", "The owning business unit is not ACTIVE.")

    policy = db.tagging_policies.get(row["tagging_policy_id"])
    if policy is not None and policy["enforcement_mode"] == "BLOCKING" and row["missing_dimensions"]:
        fail(
            "ERR_MANDATORY_TAG_MISSING",
            "Mandatory tag dimensions are missing under BLOCKING enforcement.",
        )
    if policy is None or policy["status"] != "ACTIVE":
        fail("ERR_POLICY_NOT_ACTIVE", "The referenced tagging policy is not ACTIVE.")

    breached = derived.covering_budget(bu["id"], now(), statuses=("BREACHED",))
    if breached is not None and breached.get("variance_explanation_text") is None:
        fail(
            "ERR_VARIANCE_EXPLANATION_REQUIRED",
            "The business unit has a BREACHED budget without a variance explanation.",
        )

    row["status"] = "APPROVED"
    touch(row)
    return serve(row)


@bp.route("/finops/provisioning-requests/<request_id>/provision", methods=["POST"])
@authorize("FinOpsAnalyst")
def provision_request(request_id):
    row = lookup("provisioning_requests", request_id)
    if row["status"] != "APPROVED":
        fail("ERR_REQUEST_STATE_INVALID", "Only an APPROVED request may be provisioned.")

    bu = db.business_units.get(row["business_unit_id"])
    if bu is None or bu["status"] != "ACTIVE":
        fail("ERR_BU_SUSPENDED", "The owning business unit is not ACTIVE.")

    tags = dict(row["requested_tags"])
    environment = tags.get("environment")
    if not isinstance(environment, str) or environment.strip() == "":
        environment = "untagged"

    resource = base_fields()
    resource.update(
        {
            "provisioning_request_id": row["id"],
            "business_unit_id": bu["id"],
            "resource_kind": row["resource_kind"],
            "environment": environment,
            "applied_tags": tags,
            "tag_state": row["projected_tag_state"],
            "lifecycle_state": "ACTIVE",
            "owner_user_id": row["owner_user_id"],
            "utilization_pct": 100.00,
            "monthly_run_rate_cents": row["monthly_run_rate_cents"],
        }
    )
    db.cloud_resources[resource["id"]] = resource

    row["status"] = "PROVISIONED"
    touch(row)
    derived.bu_sync(bu)
    return serve(row)
