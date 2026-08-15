"""Consumers, rights requests, and request tasks."""
from flask import Blueprint, request

import db
from errors import ApiError
from middleware import STAFF_ROLES, get_body, require_roles
from response import list_response, success
from serialize import ser_consumer, ser_rights_request, ser_task
from services.core import base_entity, created_asc, touch
from services.requests_svc import (bubble_task_started, bubble_task_terminal,
                                   cancel_open_tasks, final_due,
                                   provisional_due, resolve_governing_rule,
                                   select_routing_systems)
from services.risk import DATA_CATEGORIES, REQUEST_TYPES

bp = Blueprint("consumers", __name__)

REQUEST_READ_ROLES = ("Consumer", "PrivacyAdmin", "DataSteward", "LegalCounsel")


# --- Consumer --------------------------------------------------------------------

@bp.post("/privacy/consumers")
def create_consumer():
    require_roles("PrivacyAdmin")
    body = get_body()
    email = body.get("email")
    if isinstance(email, str) and any(
            c["email"] == email for c in db.consumers.values()):
        raise ApiError("ERR_DUPLICATE_KEY", "email already exists")
    full_name = body.get("full_name")
    state_code = body.get("state_code")
    if not isinstance(email, str) or not email:
        raise ApiError("ERR_INVALID_REQUEST", "email is required")
    if not isinstance(full_name, str) or not full_name:
        raise ApiError("ERR_INVALID_REQUEST", "full_name is required")
    if (not isinstance(state_code, str) or len(state_code) != 2
            or not state_code.isalpha()):
        raise ApiError("ERR_INVALID_REQUEST", "state_code must be a 2-letter code")
    consumer = base_entity()
    consumer.update({
        "email": email,
        "full_name": full_name,
        "state_code": state_code,
    })
    db.consumers[consumer["id"]] = consumer
    return success(ser_consumer(consumer), 201)


@bp.get("/privacy/consumers/<consumer_id>")
def get_consumer(consumer_id):
    require_roles(*STAFF_ROLES)
    consumer = db.consumers.get(consumer_id)
    if consumer is None:
        raise ApiError("ERR_NOT_FOUND", "consumer not found")
    return success(ser_consumer(consumer), 200)


# --- RightsRequest -----------------------------------------------------------------

@bp.post("/privacy/consumers/<consumer_id>/rights-requests")
def create_rights_request(consumer_id):
    uid, _ = require_roles("Consumer")
    if uid != consumer_id:
        raise ApiError("ERR_FORBIDDEN_ROLE",
                       "a consumer may file requests only for itself")
    consumer = db.consumers.get(consumer_id)
    if consumer is None:
        raise ApiError("ERR_NOT_FOUND", "consumer not found")
    body = get_body()
    request_type = body.get("request_type")
    requested_categories = body.get("requested_categories")
    if request_type not in REQUEST_TYPES:
        raise ApiError("ERR_INVALID_REQUEST", "invalid request_type")
    if (not isinstance(requested_categories, list)
            or not requested_categories
            or any(c not in DATA_CATEGORIES for c in requested_categories)):
        raise ApiError("ERR_INVALID_REQUEST",
                       "requested_categories must be a non-empty list of data categories")
    rule = resolve_governing_rule(consumer)
    req = base_entity()
    req.update({
        "consumer_id": consumer_id,
        "request_type": request_type,
        "requested_categories": list(requested_categories),
        "applicable_state_code": rule["state_code"] if rule is not None else None,
        "provisional_due_at": provisional_due(req["created_at"], rule),
        "final_due_at": None,
        "verification_status": "UNVERIFIED",
        "fulfillment_status": "INTAKE",
    })
    db.rights_requests[req["id"]] = req
    return success(ser_rights_request(req), 201)


@bp.get("/privacy/consumers/<consumer_id>/rights-requests")
def list_consumer_rights_requests(consumer_id):
    uid, role = require_roles(*REQUEST_READ_ROLES)
    if role == "Consumer" and uid != consumer_id:
        raise ApiError("ERR_FORBIDDEN_ROLE",
                       "a consumer may read only its own requests")
    consumer = db.consumers.get(consumer_id)
    if consumer is None:
        raise ApiError("ERR_NOT_FOUND", "consumer not found")
    items = created_asc([r for r in db.rights_requests.values()
                         if r["consumer_id"] == consumer_id])
    return list_response(items, ser_rights_request)


@bp.get("/privacy/rights-requests/<request_id>")
def get_rights_request(request_id):
    uid, role = require_roles(*REQUEST_READ_ROLES)
    req = db.rights_requests.get(request_id)
    if req is None:
        raise ApiError("ERR_NOT_FOUND", "rights request not found")
    if role == "Consumer" and req["consumer_id"] != uid:
        raise ApiError("ERR_FORBIDDEN_ROLE",
                       "a consumer may read only its own requests")
    return success(ser_rights_request(req), 200)


@bp.post("/privacy/rights-requests/<request_id>/verify")
def verify_rights_request(request_id):
    require_roles("DataSteward")
    req = db.rights_requests.get(request_id)
    if req is None:
        raise ApiError("ERR_NOT_FOUND", "rights request not found")
    if req["verification_status"] != "UNVERIFIED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "request is not UNVERIFIED")
    rule = None
    if req["applicable_state_code"] is not None:
        rule = next((r for r in db.state_law_rules.values()
                     if r["state_code"] == req["applicable_state_code"]), None)
    req["verification_status"] = "VERIFIED"
    req["final_due_at"] = final_due(req["created_at"], req["request_type"], rule)
    touch(req)
    return success(ser_rights_request(req), 200)


@bp.post("/privacy/rights-requests/<request_id>/fail-verification")
def fail_verification_rights_request(request_id):
    require_roles("DataSteward")
    req = db.rights_requests.get(request_id)
    if req is None:
        raise ApiError("ERR_NOT_FOUND", "rights request not found")
    if req["verification_status"] != "UNVERIFIED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "request is not UNVERIFIED")
    req["verification_status"] = "VERIFICATION_FAILED"
    req["fulfillment_status"] = "DENIED"
    touch(req)
    return success(ser_rights_request(req), 200)


@bp.post("/privacy/rights-requests/<request_id>/route")
def route_rights_request(request_id):
    require_roles("DataSteward")
    req = db.rights_requests.get(request_id)
    if req is None:
        raise ApiError("ERR_NOT_FOUND", "rights request not found")
    if req["fulfillment_status"] != "INTAKE":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "request fulfillment must be INTAKE")
    if req["verification_status"] != "VERIFIED":
        raise ApiError("ERR_REQUEST_NOT_VERIFIED",
                       "request must be VERIFIED before routing")
    pool = select_routing_systems(req["requested_categories"])
    if not pool:
        raise ApiError("ERR_NO_SYSTEMS_IN_SCOPE",
                       "no ACTIVE data system stores any requested category")
    for system in pool:
        task = base_entity()
        task.update({
            "request_id": request_id,
            "data_system_id": system["id"],
            "status": "PENDING",
            "outcome_notes": None,
        })
        db.tasks[task["id"]] = task
    req["fulfillment_status"] = "ROUTED"
    touch(req)
    return success(ser_rights_request(req), 200)


@bp.post("/privacy/rights-requests/<request_id>/deny")
def deny_rights_request(request_id):
    require_roles("LegalCounsel")
    get_body()  # optional reason; accepted and ignored
    req = db.rights_requests.get(request_id)
    if req is None:
        raise ApiError("ERR_NOT_FOUND", "rights request not found")
    if req["fulfillment_status"] not in ("INTAKE", "ROUTED", "IN_PROGRESS"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "request fulfillment must be INTAKE, ROUTED, or IN_PROGRESS")
    req["fulfillment_status"] = "DENIED"
    touch(req)
    cancel_open_tasks(request_id)
    return success(ser_rights_request(req), 200)


@bp.post("/privacy/rights-requests/<request_id>/respond")
def respond_rights_request(request_id):
    require_roles("DataSteward")
    req = db.rights_requests.get(request_id)
    if req is None:
        raise ApiError("ERR_NOT_FOUND", "rights request not found")
    if req["fulfillment_status"] != "READY_TO_RESPOND":
        raise ApiError("ERR_TASKS_OUTSTANDING",
                       "request is not READY_TO_RESPOND")
    req["fulfillment_status"] = "COMPLETED"
    touch(req)
    return success(ser_rights_request(req), 200)


# --- RequestTask -------------------------------------------------------------------

@bp.get("/privacy/rights-requests/<request_id>/tasks")
def list_request_tasks(request_id):
    require_roles(*STAFF_ROLES)
    req = db.rights_requests.get(request_id)
    if req is None:
        raise ApiError("ERR_NOT_FOUND", "rights request not found")
    items = created_asc([t for t in db.tasks.values()
                         if t["request_id"] == request_id])
    return list_response(items, ser_task)


@bp.get("/privacy/tasks/<task_id>")
def get_task(task_id):
    require_roles(*STAFF_ROLES)
    task = db.tasks.get(task_id)
    if task is None:
        raise ApiError("ERR_NOT_FOUND", "task not found")
    return success(ser_task(task), 200)


@bp.get("/privacy/tasks")
def list_tasks():
    require_roles(*STAFF_ROLES)
    items = created_asc(list(db.tasks.values()))
    rights_request_id = request.args.get("rights_request_id")
    data_system_id = request.args.get("data_system_id")
    if rights_request_id is not None:
        items = [t for t in items if t["request_id"] == rights_request_id]
    if data_system_id is not None:
        items = [t for t in items if t["data_system_id"] == data_system_id]
    return list_response(items, ser_task)


@bp.post("/privacy/tasks/<task_id>/start")
def start_task(task_id):
    require_roles("DataSteward")
    task = db.tasks.get(task_id)
    if task is None:
        raise ApiError("ERR_NOT_FOUND", "task not found")
    if task["status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "only a PENDING task can be started")
    task["status"] = "IN_PROGRESS"
    touch(task)
    bubble_task_started(task)
    return success(ser_task(task), 200)


@bp.post("/privacy/tasks/<task_id>/complete")
def complete_task(task_id):
    require_roles("DataSteward")
    task = db.tasks.get(task_id)
    if task is None:
        raise ApiError("ERR_NOT_FOUND", "task not found")
    if task["status"] != "IN_PROGRESS":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "only an IN_PROGRESS task can be completed")
    body = get_body()
    outcome_notes = body.get("outcome_notes")
    if outcome_notes is not None and not isinstance(outcome_notes, str):
        raise ApiError("ERR_INVALID_REQUEST", "outcome_notes must be a string")
    if outcome_notes is not None:
        task["outcome_notes"] = outcome_notes
    task["status"] = "COMPLETED"
    touch(task)
    bubble_task_terminal(task)
    return success(ser_task(task), 200)
