"""Data export / deletion requests (PRD §3.10)."""
from flask import Blueprint, g, request

import calc
import db
import services as S
from auth import endpoint, require_owner
from errors import ApiError
from response import ok, paginate
from routes.common import body

bp = Blueprint("privacy", __name__)

REQUEST_TYPES = ("EXPORT", "DELETE")
DECISIONS = ("APPROVE", "REJECT")
EXPORT_URL_PREFIX = "https://export.dna.example/"


@bp.post("/dna/data-requests")
@endpoint(["Customer"])
def file_request():
    payload = body()
    S.require_fields(payload, ["customer_id", "request_type"])
    customer = S.get("customers", payload["customer_id"])
    require_owner(customer["id"])
    S.require_enum(payload["request_type"], REQUEST_TYPES, "request_type")

    S.require_not_purged(customer)

    for other in db.db.data_requests.values():
        if other["customer_id"] == customer["id"] and other["status"] in ("PENDING", "SCHEDULED"):
            raise ApiError("ERR_PENDING_DATA_REQUEST")

    record = db.new_record(
        {
            "customer_id": customer["id"],
            "request_type": payload["request_type"],
            "status": "PENDING",
            "reviewed_by": None,
            "scheduled_purge_at": None,
            "export_url": None,
        }
    )
    db.db.data_requests[record["id"]] = record
    return ok(S.data_request_json(record), 201)


@bp.get("/dna/data-requests/<request_id>")
@endpoint(["Customer", "PrivacyOfficer"])
def read_request(request_id):
    record = S.get("data_requests", request_id)
    require_owner(record["customer_id"])
    return ok(S.data_request_json(record))


@bp.get("/dna/data-requests")
@endpoint(["Customer", "PrivacyOfficer", "PlatformAdmin"])
def list_requests():
    records = S.all_of("data_requests")
    customer_id = request.args.get("customer_id")
    status = request.args.get("status")
    if customer_id:
        records = [r for r in records if r["customer_id"] == customer_id]
    if status:
        records = [r for r in records if r["status"] == status]
    return paginate(records, S.data_request_json)


@bp.post("/dna/data-requests/<request_id>/decide")
@endpoint(["PrivacyOfficer"])
def decide(request_id):
    record = S.get("data_requests", request_id)
    payload = body()
    S.require_fields(payload, ["decision"])
    decision = payload["decision"]
    S.require_enum(decision, DECISIONS, "decision")

    if record["status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE")

    record["reviewed_by"] = g.user_id

    if decision == "REJECT":
        record["status"] = "REJECTED"
    elif record["request_type"] == "EXPORT":
        record["status"] = "COMPLETED"
        record["export_url"] = EXPORT_URL_PREFIX + record["id"]
    else:
        record["status"] = "SCHEDULED"
        record["scheduled_purge_at"] = db.now() + db.days(calc.PURGE_GRACE_DAYS)

    db.touch(record)
    return ok(S.data_request_json(record))


@bp.post("/dna/data-requests/<request_id>/cancel")
@endpoint(["Customer"])
def cancel(request_id):
    record = S.get("data_requests", request_id)
    require_owner(record["customer_id"])

    if record["status"] not in ("PENDING", "SCHEDULED"):
        raise ApiError("ERR_INVALID_STATE")
    if record["status"] == "SCHEDULED" and not db.now() < record["scheduled_purge_at"]:
        raise ApiError("ERR_INVALID_STATE", "The purge instant has already passed.")

    record["status"] = "CANCELLED"
    db.touch(record)
    return ok(S.data_request_json(record))
