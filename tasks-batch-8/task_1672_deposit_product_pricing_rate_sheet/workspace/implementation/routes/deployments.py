"""RateDeployment endpoints."""

from flask import Blueprint

from db import STORE
from errors import ApiError, ERR_DEPLOYMENT_INVALID_STATE, bad_request, not_found
from middleware import get_body, paginate, query_enum, require_roles
from response import ok_object
from serialize import serialize, serialize_many
from services.rates import CHANNELS
from utils import bump, now_ts, req_field

bp = Blueprint("deployments", __name__)

DEPLOYMENT_STATUSES = ("PENDING", "DEPLOYED", "FAILED", "RETIRED")


@bp.get("/rate-deployments")
@require_roles("PricingAnalyst", "ChannelOperator", "ComplianceOfficer")
def list_deployments():
    from flask import request
    sheet_id = request.args.get("sheet_id")
    channel = query_enum("channel", CHANNELS)
    status = query_enum("status", DEPLOYMENT_STATUSES)
    rows = list(STORE["deployments"].values())
    if sheet_id is not None:
        rows = [r for r in rows if r["sheet_id"] == sheet_id]
    if channel is not None:
        rows = [r for r in rows if r["channel"] == channel]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return paginate(serialize_many("deployments", rows))


@bp.get("/rate-deployments/<dep_id>")
@require_roles("PricingAnalyst", "ChannelOperator", "ComplianceOfficer")
def get_deployment(dep_id):
    row = STORE["deployments"].get(dep_id)
    if row is None:
        raise not_found("Deployment not found")
    return ok_object(serialize("deployments", row))


@bp.post("/rate-deployments/<dep_id>/execution")
@require_roles("ChannelOperator")
def execute_deployment(dep_id):
    data = get_body()
    action = req_field(data, "action")
    if action not in ("DEPLOY", "MARK_FAILED"):
        raise bad_request("action must be DEPLOY or MARK_FAILED")
    row = STORE["deployments"].get(dep_id)
    if row is None:
        raise not_found("Deployment not found")
    if action == "DEPLOY":
        if row["status"] not in ("PENDING", "FAILED"):
            raise ApiError(ERR_DEPLOYMENT_INVALID_STATE, 409,
                           f"Cannot DEPLOY a {row['status']} deployment")
        row["status"] = "DEPLOYED"
        row["deployed_at"] = now_ts()
    else:  # MARK_FAILED
        if row["status"] != "PENDING":
            raise ApiError(ERR_DEPLOYMENT_INVALID_STATE, 409,
                           f"Cannot MARK_FAILED a {row['status']} deployment")
        row["status"] = "FAILED"
    bump(row)
    return ok_object(serialize("deployments", row))
