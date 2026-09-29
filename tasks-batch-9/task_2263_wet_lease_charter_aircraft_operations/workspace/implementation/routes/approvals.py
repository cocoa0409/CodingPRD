"""Regulatory approvals — the authority docket (PRD 3.2)."""

from flask import Blueprint, request

from db import db, touch, public, clock_now, iso
from errors import ApiError, bad_request
from middleware import (
    require, check_ownership, scope_for_lessee,
    LESSOR_OPS, LESSEE, REGULATORY_AUTHORITY,
)
from response import object_response, pagination, paged
from routes.common import find_approval, filtered
from services import workflows as W
import validate as V

bp = Blueprint("approvals", __name__)


@bp.get("/wetlease/regulatory-approvals/<approval_id>")
def get_approval(approval_id):
    actor = require((REGULATORY_AUTHORITY, LESSOR_OPS, LESSEE))
    approval = find_approval(approval_id)
    check_ownership(actor, "approval", approval)
    return object_response(public(approval))


@bp.get("/wetlease/regulatory-approvals")
def list_approvals():
    actor = require((REGULATORY_AUTHORITY, LESSOR_OPS, LESSEE))
    limit, offset = pagination(request.args)
    rows = filtered(list(db.regulatory_approvals.values()), request.args, {
        "lease_id": "lease_id",
        "determination": "determination",
    })
    rows = scope_for_lessee(actor, "approval", rows)
    return paged(rows, limit, offset)


@bp.post("/wetlease/regulatory-approvals/<approval_id>/decision")
def record_decision(approval_id):
    require((REGULATORY_AUTHORITY,))
    body = V.json_body()
    determination = V.req_enum(body, "determination", ("APPROVED", "CONDITIONAL", "DENIED"))
    conditions = V.opt_str_list(body, "conditions", default=[])
    expires_on_raw, _expires_on = V.opt_date(body, "expires_on")
    if determination == "APPROVED" and len(conditions) > 0:
        raise bad_request("an APPROVED determination must not carry conditions")
    if determination == "CONDITIONAL" and len(conditions) == 0:
        raise bad_request("a CONDITIONAL determination requires a non-empty conditions array")

    approval = find_approval(approval_id)
    current = approval["determination"]
    if determination in ("APPROVED", "CONDITIONAL"):
        if current != "UNDER_REVIEW":
            raise ApiError("ERR_APPROVAL_INVALID_STATE")
    else:
        if current not in ("UNDER_REVIEW", "CONDITIONAL"):
            raise ApiError("ERR_APPROVAL_INVALID_STATE")

    approval["determination"] = determination
    approval["decided_at"] = iso(clock_now())
    if expires_on_raw is not None:
        approval["expires_on"] = expires_on_raw
    if determination == "APPROVED":
        approval["conditions"] = []
        approval["open_condition_codes"] = []
    elif determination == "CONDITIONAL":
        approval["conditions"] = list(conditions)
        approval["open_condition_codes"] = list(conditions)
    touch(approval)

    lease = db.leases.get(approval["lease_id"])
    if lease is not None:
        if determination in ("APPROVED", "CONDITIONAL"):
            if lease["status"] == "PENDING_REGULATORY_APPROVAL":
                lease["status"] = "APPROVED"
                touch(lease)
        else:
            if lease["status"] in ("PENDING_REGULATORY_APPROVAL", "APPROVED"):
                lease["status"] = "DRAFT"
                touch(lease)

    return object_response(public(approval))


@bp.post("/wetlease/regulatory-approvals/<approval_id>/clear-conditions")
def clear_conditions(approval_id):
    require((REGULATORY_AUTHORITY,))
    body = V.json_body()
    cleared = V.req_str_list(body, "cleared_condition_codes")
    approval = find_approval(approval_id)
    if approval["determination"] != "CONDITIONAL":
        raise ApiError("ERR_APPROVAL_INVALID_STATE")
    remaining = [c for c in approval["open_condition_codes"] if c not in set(cleared)]
    if remaining:
        raise bad_request("every open condition code must appear in cleared_condition_codes")

    approval["open_condition_codes"] = []
    approval["determination"] = "APPROVED"
    approval["decided_at"] = iso(clock_now())
    touch(approval)
    return object_response(public(approval))


@bp.post("/wetlease/regulatory-approvals/<approval_id>/revoke")
def revoke_approval(approval_id):
    require((REGULATORY_AUTHORITY,))
    body = V.json_body()
    reason = V.req_str(body, "revocation_reason")
    approval = find_approval(approval_id)
    if approval["determination"] not in ("APPROVED", "CONDITIONAL"):
        raise ApiError("ERR_APPROVAL_INVALID_STATE")

    approval["determination"] = "REVOKED"
    approval["revocation_reason"] = reason
    approval["decided_at"] = iso(clock_now())
    touch(approval)

    lease = db.leases.get(approval["lease_id"])
    if lease is not None:
        W.suspend_lease(lease, "REGULATORY_APPROVAL_REVOKED", "REGULATORY")

    return object_response(public(approval))
