from flask import Blueprint, request

from db import stamp_new, store, today_str, touch
from envelope import ok, ok_list
from errors import (
    ERR_CONVERSION_ALREADY_REQUESTED,
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
    ERR_VALIDATION,
    raise_err,
)
from security import require_roles
from services import conversion_fee, cumulative_tenure
from validators import apply_filters, get_body, paginate, req_str
import serializers

bp = Blueprint("conversions", __name__)

READ_ROLES = ("ProgramAdmin", "HiringManager", "FinanceAnalyst")


def _get_conversion(cr_id):
    cr = store.conversion_requests.get(cr_id)
    if cr is None:
        raise_err(ERR_NOT_FOUND, f"Conversion request {cr_id} not found.")
    return cr


@bp.post("/v1/conversion-requests")
def create_conversion_request():
    require_roles("HiringManager")
    body = get_body()
    worker_id = req_str(body, "worker_id")
    assignment_id = req_str(body, "assignment_id")
    worker = store.workers.get(worker_id)
    if worker is None:
        raise_err(ERR_NOT_FOUND, f"Worker {worker_id} not found.")
    a = store.assignments.get(assignment_id)
    if a is None:
        raise_err(ERR_NOT_FOUND, f"Assignment {assignment_id} not found.")
    if a["worker_id"] != worker_id:
        raise_err(ERR_VALIDATION, "The assignment does not belong to the named worker.")
    if a["status"] != "ACTIVE":
        raise_err(ERR_INVALID_STATE, "The referenced assignment must be ACTIVE.")
    for cr in store.conversion_requests.values():
        if cr["worker_id"] == worker_id and cr["status"] in ("REQUESTED", "APPROVED"):
            raise_err(
                ERR_CONVERSION_ALREADY_REQUESTED,
                "The worker already has a conversion request in REQUESTED or APPROVED.",
            )
    eng = store.engagements.get(a["engagement_id"])
    sup = store.suppliers.get(a["supplier_id"])
    tenure = cumulative_tenure(worker)
    variant, fee = conversion_fee(
        tenure, eng["prorata_conversion"] if eng else False, sup["tier"] if sup else "PROBATION"
    )
    rec = {
        "worker_id": worker_id,
        "assignment_id": assignment_id,
        "tenure_days_at_request": tenure,
        "fee_variant": variant,
        "fee_cents": fee,
        "status": "REQUESTED",
        "decline_reason": None,
    }
    stamp_new(rec)
    store.conversion_requests[rec["id"]] = rec
    worker["conversion_status"] = "REQUESTED"
    touch(worker)
    return ok(serializers.conversion_request(rec), 201)


@bp.get("/v1/conversion-requests")
def list_conversion_requests():
    require_roles(*READ_ROLES)
    filters = {
        "worker_id": request.args.get("worker_id"),
        "assignment_id": request.args.get("assignment_id"),
        "status": request.args.get("status"),
    }
    records = apply_filters(list(store.conversion_requests.values()), filters)
    page, total, limit, offset = paginate(records, serializers.conversion_request)
    return ok_list(page, total, limit, offset)


@bp.get("/v1/conversion-requests/<cr_id>")
def get_conversion_request(cr_id):
    require_roles(*READ_ROLES)
    return ok(serializers.conversion_request(_get_conversion(cr_id)))


@bp.post("/v1/conversion-requests/<cr_id>/approve")
def approve_conversion(cr_id):
    require_roles("ProgramAdmin")
    cr = _get_conversion(cr_id)
    if cr["status"] != "REQUESTED":
        raise_err(ERR_INVALID_STATE, "Only a REQUESTED conversion request can be approved.")
    cr["status"] = "APPROVED"
    touch(cr)
    worker = store.workers.get(cr["worker_id"])
    if worker is not None:
        worker["conversion_status"] = "APPROVED"
        touch(worker)
    return ok(serializers.conversion_request(cr))


@bp.post("/v1/conversion-requests/<cr_id>/decline")
def decline_conversion(cr_id):
    require_roles("ProgramAdmin")
    body = get_body()
    reason = req_str(body, "reason")
    cr = _get_conversion(cr_id)
    if cr["status"] != "REQUESTED":
        raise_err(ERR_INVALID_STATE, "Only a REQUESTED conversion request can be declined.")
    cr["status"] = "DECLINED"
    cr["decline_reason"] = reason
    touch(cr)
    worker = store.workers.get(cr["worker_id"])
    if worker is not None:
        worker["conversion_status"] = "DECLINED"
        touch(worker)
    return ok(serializers.conversion_request(cr))


@bp.post("/v1/conversion-requests/<cr_id>/complete")
def complete_conversion(cr_id):
    require_roles("ProgramAdmin")
    cr = _get_conversion(cr_id)
    if cr["status"] != "APPROVED":
        raise_err(ERR_INVALID_STATE, "Only an APPROVED conversion request can be completed.")
    cr["status"] = "COMPLETED"
    touch(cr)
    a = store.assignments.get(cr["assignment_id"])
    if a is not None and a["status"] == "ACTIVE":
        a["status"] = "TERMINATED"
        a["termination_reason"] = "CONVERTED"
        a["actual_end_date"] = today_str()
        touch(a)
    worker = store.workers.get(cr["worker_id"])
    if worker is not None:
        worker["status"] = "EXITED"  # offboarding bypassed on conversion
        worker["conversion_status"] = "CONVERTED"
        touch(worker)
    return ok(serializers.conversion_request(cr))
