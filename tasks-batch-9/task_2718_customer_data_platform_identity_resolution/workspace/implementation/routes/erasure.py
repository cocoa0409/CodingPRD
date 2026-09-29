"""Erasure requests and their downstream vendor deletion tasks."""

from flask import Blueprint

import db
import middleware
import validators
from errors import ApiError
from routes import common
from services import privacy

bp = Blueprint("erasure", __name__)

ORIGINS = ("DATA_SUBJECT", "RETENTION", "REGULATOR")
OUTCOMES = ("ACKNOWLEDGED", "FAILED")
ACKNOWLEDGEABLE = ("DISPATCHED", "TIMED_OUT")
PROPAGATABLE = ("RECEIVED", "PARTIALLY_VERIFIED")


# -------------------------------------------------------- deletion requests

@bp.post("/cdp/deletion-requests")
def create_request():
    middleware.require_role(middleware.ROLE_PRIVACY)
    body = validators.body_object()
    profile_id = validators.req_id(body, "profile_id")
    origin = validators.req_enum(body, "request_origin", ORIGINS)
    reference = validators.req_str(body, "requester_reference", 1, 60)

    profile = common.profile(profile_id)
    if profile["resolution_status"] == "MERGED_AWAY":
        raise ApiError("ERR_PROFILE_MERGED_AWAY")
    if profile["privacy_status"] == "DELETED":
        raise ApiError("ERR_PROFILE_DELETED")
    if privacy.open_request_for(profile["id"]) is not None:
        raise ApiError("ERR_INVALID_STATE")
    if profile["privacy_status"] not in ("NORMAL", "SUPPRESSED"):
        raise ApiError("ERR_INVALID_STATE")

    entity = privacy.create_deletion_request(
        profile, origin, reference, middleware.actor_id()
    )
    return common.one("deletion_requests", entity, 201)


@bp.get("/cdp/deletion-requests/<request_id>")
def read_request(request_id):
    middleware.require_role(*middleware.READ_ROLES)
    return common.one("deletion_requests", common.deletion_request(request_id))


@bp.get("/cdp/deletion-requests")
def list_requests():
    middleware.require_role(*middleware.READ_ROLES)
    return common.collection_list(
        "deletion_requests",
        {"profile_id": "profile_id", "status": "status"},
        common.seq_sort,
    )


@bp.post("/cdp/deletion-requests/<request_id>/propagate")
def propagate_request(request_id):
    middleware.require_role(middleware.ROLE_PRIVACY)
    body = validators.body_object()
    expected_version = validators.req_int(body, "expected_deletion_request_version", 1)
    entity = common.deletion_request(request_id)
    common.check_version(entity, expected_version, "ERR_STALE_DELETION_REQUEST_VERSION")
    common.require_status(entity, PROPAGATABLE)
    profile = db.store["profiles"][entity["profile_id"]]
    hold = privacy.active_legal_hold_entry(profile["id"])
    if hold is not None:
        entity["status"] = "BLOCKED_LEGAL_HOLD"
        entity["blocked_reason"] = hold["reason_code"]
        db.touch(entity)
        raise ApiError("ERR_LEGAL_HOLD_ACTIVE")
    privacy.propagate(entity, profile)
    return common.one("deletion_requests", entity)


# ----------------------------------------------------- vendor deletion tasks

@bp.get("/cdp/vendor-deletion-tasks/<task_id>")
def read_task(task_id):
    middleware.require_role(*middleware.READ_ROLES)
    return common.one("vendor_deletion_tasks", common.vendor_task(task_id))


@bp.get("/cdp/vendor-deletion-tasks")
def list_tasks():
    middleware.require_role(*middleware.READ_ROLES)
    return common.collection_list(
        "vendor_deletion_tasks",
        {
            "deletion_request_id": "deletion_request_id",
            "destination_id": "destination_id",
            "status": "status",
        },
        common.seq_sort,
    )


@bp.post("/cdp/vendor-deletion-tasks/<task_id>/acknowledge")
def acknowledge_task(task_id):
    middleware.require_role(middleware.ROLE_DESTINATION)
    entity = common.vendor_task(task_id)
    middleware.require_destination_actor(entity["destination_id"])
    body = validators.body_object()
    outcome = validators.req_enum(body, "outcome", OUTCOMES)
    evidence = validators.opt_str(body, "deletion_evidence_reference", 1)
    record_count = validators.opt_int(body, "acknowledged_record_count", 0)
    common.require_status(entity, ACKNOWLEDGEABLE)
    privacy.acknowledge(entity, outcome, evidence, record_count)
    return common.one("vendor_deletion_tasks", entity)
