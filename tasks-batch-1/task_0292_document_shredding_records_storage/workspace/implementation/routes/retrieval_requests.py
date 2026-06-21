"""RetrievalRequest endpoints (PRD §3.9)."""
from flask import Blueprint, request

from db import db, stamp_create, touch
from errors import err
from middleware import get_auth, require_role
from response import object_response, array_response
from common import (
    body, serialize, paginate, sort_by_created,
    require_present, require_enum, as_str,
    get_account_or_404, get_box_or_404, get_request_or_404,
    active_rate_card, has_active_hold,
)
from services.calculations import retrieval_charge

bp = Blueprint("retrieval_requests", __name__)

PRIORITIES = {"STANDARD", "RUSH"}


@bp.post("/retrieval-requests")
def create_request():
    _, role = get_auth()
    require_role(role, {"AccountManager"})
    data = body()
    require_present(data, "box_id", "account_id", "priority", "requested_by")
    box_id = as_str(data["box_id"], "box_id")
    account_id = as_str(data["account_id"], "account_id")
    # Existence left-to-right: box then account (both referenced in body).
    get_box_or_404(box_id)
    acct = get_account_or_404(account_id)
    require_enum(data["priority"], PRIORITIES, "priority")
    requested_by = as_str(data["requested_by"], "requested_by")

    # Account must be ACTIVE to open a request.
    if acct["status"] != "ACTIVE":
        raise err("ERR_ACCOUNT_NOT_ACTIVE", "Account is not ACTIVE")

    req = {
        "box_id": box_id,
        "account_id": account_id,
        "priority": data["priority"],
        "retrieval_charge_cents": 0,
        "delivered_period": -1,
        "requested_by": requested_by,
        "status": "PENDING",
    }
    stamp_create(req)
    db.retrieval_requests[req["id"]] = req
    return object_response(serialize(req), 201)


@bp.get("/retrieval-requests/<request_id>")
def get_request(request_id):
    _, role = get_auth()
    require_role(role, {"AccountManager", "PlantOperator", "ComplianceOfficer"})
    r = get_request_or_404(request_id)
    return object_response(serialize(r), 200)


@bp.get("/retrieval-requests")
def list_requests():
    _, role = get_auth()
    require_role(role, {"AccountManager", "PlantOperator", "ComplianceOfficer"})
    items = list(db.retrieval_requests.values())
    box_id = request.args.get("box_id")
    account_id = request.args.get("account_id")
    status = request.args.get("status")
    if box_id is not None:
        items = [r for r in items if r["box_id"] == box_id]
    if account_id is not None:
        items = [r for r in items if r["account_id"] == account_id]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    items = sort_by_created(items)
    page, limit, offset, total = paginate(items)
    return array_response([serialize(r) for r in page], limit, offset, total, 200)


@bp.post("/retrieval-requests/<request_id>/fulfill")
def fulfill_request(request_id):
    _, role = get_auth()
    require_role(role, {"PlantOperator"})
    r = get_request_or_404(request_id)
    if r["status"] != "PENDING":
        raise err("ERR_REQUEST_NOT_PENDING", "Request is not in PENDING")
    box = db.retention_boxes.get(r["box_id"])
    if box is None or box["status"] != "STORED":
        raise err("ERR_BOX_NOT_STORED", "Box is not in STORED")
    if has_active_hold("RETENTION_BOX", box["id"]):
        raise err("ERR_SUBJECT_ON_HOLD", "Box is under an active compliance hold")

    rate = active_rate_card(r["account_id"])
    if rate is None:
        raise err("ERR_NO_ACTIVE_RATE_CARD", "No ACTIVE rate card on the account")

    acct = db.accounts[r["account_id"]]
    r["retrieval_charge_cents"] = retrieval_charge(r["priority"], rate)
    r["delivered_period"] = acct["current_period_index"]
    r["status"] = "DELIVERED"
    touch(r)

    box["status"] = "OUT_FOR_RETRIEVAL"
    touch(box)
    return object_response(serialize(r), 200)


@bp.post("/retrieval-requests/<request_id>/start-return")
def start_return(request_id):
    _, role = get_auth()
    require_role(role, {"AccountManager"})
    r = get_request_or_404(request_id)
    if r["status"] != "DELIVERED":
        raise err("ERR_REQUEST_NOT_DELIVERED", "Request is not in DELIVERED")
    r["status"] = "RETURN_PENDING"
    touch(r)
    return object_response(serialize(r), 200)


@bp.post("/retrieval-requests/<request_id>/return")
def complete_return(request_id):
    _, role = get_auth()
    require_role(role, {"PlantOperator"})
    r = get_request_or_404(request_id)
    if r["status"] != "RETURN_PENDING":
        raise err("ERR_RETURN_NOT_PENDING", "Request is not in RETURN_PENDING")
    box = db.retention_boxes.get(r["box_id"])
    if box is None or box["status"] != "OUT_FOR_RETRIEVAL":
        raise err("ERR_BOX_NOT_OUT", "Box is not OUT_FOR_RETRIEVAL")
    r["status"] = "RETURNED"
    touch(r)
    box["status"] = "STORED"
    touch(box)
    return object_response(serialize(r), 200)


@bp.post("/retrieval-requests/<request_id>/refuse-return")
def refuse_return(request_id):
    _, role = get_auth()
    require_role(role, {"PlantOperator"})
    r = get_request_or_404(request_id)
    if r["status"] != "RETURN_PENDING":
        raise err("ERR_RETURN_NOT_PENDING", "Request is not in RETURN_PENDING")
    # Cycle back to DELIVERED; box stays OUT_FOR_RETRIEVAL.
    r["status"] = "DELIVERED"
    touch(r)
    return object_response(serialize(r), 200)


@bp.post("/retrieval-requests/<request_id>/cancel")
def cancel_request(request_id):
    _, role = get_auth()
    require_role(role, {"AccountManager"})
    r = get_request_or_404(request_id)
    if r["status"] != "PENDING":
        raise err("ERR_REQUEST_NOT_CANCELLABLE", "Request is not in PENDING")
    r["status"] = "CANCELLED"
    touch(r)
    return object_response(serialize(r), 200)
