"""PrintJob endpoints: create, advance, proof-decision."""

from flask import Blueprint, request

import db
import serializers
from errors import (
    ApiError, ERR_INVALID_REQUEST, ERR_PRINT_JOB_NOT_FOUND,
    ERR_PRINT_JOB_INVALID_STATE,
)
from middleware import get_auth, require_role, require_customer_ownership
from response import success_object
from services import risk as risk_service
from services.constants import PRINT_COMPONENTS
from .press_orders import get_order_or_404
from .releases import valid_date_str

bp = Blueprint("print_jobs", __name__)


def get_print_job_or_404(pid):
    p = db.print_jobs.get(pid)
    if not p:
        raise ApiError(ERR_PRINT_JOB_NOT_FOUND, "Print job id does not exist", 404)
    return p


@bp.route("/press-orders/<oid>/print-jobs", methods=["POST"])
def create_print_job(oid):
    _, role = get_auth()
    require_role(role, ["CustomerServiceRep"])
    order = get_order_or_404(oid)
    body = request.get_json(silent=True) or {}

    component = body.get("component")
    quantity = body.get("quantity")
    printer_name = body.get("printer_name")
    due_date = body.get("due_date")

    if component not in PRINT_COMPONENTS:
        raise ApiError(ERR_INVALID_REQUEST, "invalid component", 400)
    if not isinstance(quantity, int) or isinstance(quantity, bool) or quantity <= 0:
        raise ApiError(ERR_INVALID_REQUEST, "quantity must be a positive integer", 400)
    if not isinstance(printer_name, str) or not printer_name:
        raise ApiError(ERR_INVALID_REQUEST, "printer_name is required", 400)
    if not valid_date_str(due_date):
        raise ApiError(ERR_INVALID_REQUEST, "due_date must be yyyy-mm-dd", 400)

    if quantity < order["quantity_ordered"]:
        raise ApiError(
            ERR_INVALID_REQUEST,
            "print-run quantity must be at least the order's quantity_ordered",
            400,
        )

    now = db.timestamp_now()
    job = {
        "id": db.new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "press_order_id": order["id"],
        "component": component,
        "quantity": quantity,
        "printer_name": printer_name,
        "due_date": due_date,
        "proof_round": 0,
        "status": "CREATED",
    }
    db.print_jobs[job["id"]] = job
    return success_object(serializers.print_job(job), 201)


@bp.route("/print-jobs/<pid>/advance", methods=["POST"])
def advance_print_job(pid):
    _, role = get_auth()
    require_role(role, ["CustomerServiceRep"])
    job = get_print_job_or_404(pid)
    body = request.get_json(silent=True) or {}
    event = body.get("event")
    if event not in ("DISPATCH", "PROOFS_IN", "DELIVER"):
        raise ApiError(ERR_INVALID_REQUEST, "invalid print advance event", 400)

    if event == "DISPATCH":
        if job["status"] != "CREATED":
            raise ApiError(ERR_PRINT_JOB_INVALID_STATE, "DISPATCH requires CREATED", 409)
        job["status"] = "AT_PRINTER"
    elif event == "PROOFS_IN":
        if job["status"] != "AT_PRINTER":
            raise ApiError(ERR_PRINT_JOB_INVALID_STATE, "PROOFS_IN requires AT_PRINTER", 409)
        job["status"] = "PROOF_REVIEW"
    else:  # DELIVER
        if job["status"] != "PRINTING":
            raise ApiError(ERR_PRINT_JOB_INVALID_STATE, "DELIVER requires PRINTING", 409)
        job["status"] = "DELIVERED"

    job["version"] += 1
    job["updated_at"] = db.timestamp_now()
    return success_object(serializers.print_job(job))


@bp.route("/print-jobs/<pid>/proof-decision", methods=["POST"])
def proof_decision(pid):
    user_id, role = get_auth()
    require_role(role, ["Customer"])
    job = get_print_job_or_404(pid)
    order = db.press_orders[job["press_order_id"]]
    release = db.releases[order["release_id"]]
    require_customer_ownership(user_id, role, release)

    body = request.get_json(silent=True) or {}
    decision = body.get("decision")
    if decision not in ("APPROVE", "REQUEST_CHANGES"):
        raise ApiError(ERR_INVALID_REQUEST, "decision must be APPROVE or REQUEST_CHANGES", 400)

    if job["status"] != "PROOF_REVIEW":
        raise ApiError(ERR_PRINT_JOB_INVALID_STATE, "proof decision requires PROOF_REVIEW", 409)

    if decision == "APPROVE":
        job["status"] = "PRINTING"
    else:
        job["status"] = "AT_PRINTER"
        job["proof_round"] += 1
        job["version"] += 1
        job["updated_at"] = db.timestamp_now()
        risk_service.recompute_release_risk(release, "SCHEDULE", order["id"])
        return success_object(serializers.print_job(job))

    job["version"] += 1
    job["updated_at"] = db.timestamp_now()
    return success_object(serializers.print_job(job))
