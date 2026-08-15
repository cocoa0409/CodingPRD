"""AlternatePartApproval endpoints."""

from flask import Blueprint, request

import db
import errors as E
from errors import ApiError
from middleware import require_auth, require_role
from response import success
from services.helpers import (
    check_buyer_body_ownership,
    get_alternate_or_404,
    get_json_body,
    mint_id,
    paginate,
    pagination_params,
    req_str,
    serialize_alternate,
    stamp_now,
)

bp = Blueprint("alternates", __name__)

_seq = 0


def _next_seq():
    global _seq
    _seq += 1
    return _seq


@bp.post("/alternate-approvals")
def create_alternate():
    user_id, role = require_auth()
    require_role(user_id, role, {"SalesRep", "CustomerBuyer"})
    body = get_json_body()
    customer_id = req_str(body, "customer_id")
    primary_part_id = req_str(body, "primary_part_id")
    alternate_part_id = req_str(body, "alternate_part_id")
    if alternate_part_id == primary_part_id:
        raise ApiError(
            E.ERR_INVALID_REQUEST, 400, "alternate_part_id must differ from primary_part_id."
        )
    # Ownership (priority 2) precedes FK existence (priority 3) for body customer_id.
    check_buyer_body_ownership(user_id, role, customer_id)
    if customer_id not in db.customers:
        raise ApiError(E.ERR_CUSTOMER_NOT_FOUND, 404, "Customer not found.")
    if primary_part_id not in db.parts:
        raise ApiError(E.ERR_PART_NOT_FOUND, 404, "Part not found.")
    if alternate_part_id not in db.parts:
        raise ApiError(E.ERR_PART_NOT_FOUND, 404, "Part not found.")

    now = stamp_now()
    approval = {
        "id": mint_id(),
        "customer_id": customer_id,
        "primary_part_id": primary_part_id,
        "alternate_part_id": alternate_part_id,
        "status": "PROPOSED",
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": _next_seq(),
    }
    db.alternate_approvals[approval["id"]] = approval
    return success(serialize_alternate(approval), status=201)


@bp.get("/alternate-approvals")
def list_alternates():
    require_auth()
    limit, offset = pagination_params()
    customer_id = request.args.get("customer_id")
    primary_part_id = request.args.get("primary_part_id")
    alternate_part_id = request.args.get("alternate_part_id")
    status = request.args.get("status")
    items = list(db.alternate_approvals.values())
    if customer_id is not None:
        items = [a for a in items if a["customer_id"] == customer_id]
    if primary_part_id is not None:
        items = [a for a in items if a["primary_part_id"] == primary_part_id]
    if alternate_part_id is not None:
        items = [a for a in items if a["alternate_part_id"] == alternate_part_id]
    if status is not None:
        items = [a for a in items if a["status"] == status]
    items.sort(key=lambda a: (a["created_at"], a["_seq"]))
    page, pag = paginate(items, limit, offset)
    return success(
        [serialize_alternate(a) for a in page],
        status=200,
        response_type="array",
        pagination=pag,
    )


@bp.get("/alternate-approvals/<approvalId>")
def get_alternate(approvalId):
    require_auth()
    approval = get_alternate_or_404(approvalId)
    return success(serialize_alternate(approval), status=200)


@bp.post("/alternate-approvals/<approvalId>/decision")
def decide_alternate(approvalId):
    user_id, role = require_auth()
    require_role(user_id, role, {"CustomerBuyer"})
    body = get_json_body()
    decision = body.get("decision")
    if decision not in ("APPROVE", "REJECT", "REVOKE"):
        raise ApiError(E.ERR_INVALID_REQUEST, 400, "decision must be APPROVE, REJECT, or REVOKE.")
    approval = get_alternate_or_404(approvalId)
    check_buyer_body_ownership(user_id, role, approval["customer_id"])

    if decision in ("APPROVE", "REJECT"):
        if approval["status"] != "PROPOSED":
            raise ApiError(
                E.ERR_ALTERNATE_APPROVAL_INVALID_STATE,
                409,
                "Approval is not PROPOSED.",
            )
        approval["status"] = "APPROVED" if decision == "APPROVE" else "REJECTED"
    else:  # REVOKE
        if approval["status"] != "APPROVED":
            raise ApiError(
                E.ERR_ALTERNATE_APPROVAL_INVALID_STATE,
                409,
                "Approval is not APPROVED.",
            )
        approval["status"] = "REVOKED"
    approval["updated_at"] = stamp_now()
    approval["version"] += 1
    return success(serialize_alternate(approval), status=200)
