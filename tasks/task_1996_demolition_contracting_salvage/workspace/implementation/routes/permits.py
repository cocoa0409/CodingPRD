"""DemolitionPermit endpoints: creation with tiered fee, the municipal review
loop, activation gated on confirmed utilities, and OCC-guarded renewals."""

from datetime import timedelta

from flask import Blueprint, g

from db import store, now, new_record, touch
from errors import (err, ERR_VALIDATION, ERR_INVALID_STATE, ERR_STALE_VERSION,
                    ERR_PERMIT_EXPIRED, ERR_UTILITY_UNVERIFIED,
                    ERR_DUPLICATE_ACTIVE_PERMIT, ERR_FORBIDDEN)
from middleware import require_roles, body
from response import success, list_response
from serializers import ser_permit
from services import (get_project, get_permit, project_permits, project_disconnects,
                      compute_permit_fee_cents, PERMIT_NON_TERMINAL,
                      PERMIT_VALIDITY_DAYS, RENEWAL_EXTENSION_DAYS)
from util import req_str, req_int

bp = Blueprint("permits", __name__)

PERMIT_READ_ROLES = ("ContractorAdmin", "SiteSupervisor", "PermitCoordinator", "AuthorityReviewer")
PERMIT_ACTIONS = ("SUBMIT", "APPROVE", "REQUEST_REVISION", "REJECT", "ACTIVATE")
PERMIT_ACTION_ROLES = {
    "SUBMIT": ("PermitCoordinator",),
    "APPROVE": ("AuthorityReviewer",),
    "REQUEST_REVISION": ("AuthorityReviewer",),
    "REJECT": ("AuthorityReviewer",),
    "ACTIVATE": ("PermitCoordinator",),
}


def _has_other_live_permit(project_id, exclude_id=None):
    return any(p["status"] in PERMIT_NON_TERMINAL and p["id"] != exclude_id
               for p in project_permits(project_id))


@bp.post("/demolition/projects/<pid>/permits")
@require_roles("PermitCoordinator")
def create_permit(pid):
    b = body()
    permit_number = req_str(b, "permit_number")
    area = req_int(b, "gross_floor_area_sqft", minimum=1)
    project = get_project(pid)
    if _has_other_live_permit(project["id"]):
        raise err(ERR_DUPLICATE_ACTIVE_PERMIT,
                  "another permit of this project is outside a terminal status")

    rec = new_record()
    rec.update({
        "project_id": project["id"],
        "permit_number": permit_number,
        "gross_floor_area_sqft": area,
        "fee_cents": compute_permit_fee_cents(area),
        "status": "DRAFT",
        "revision_count": 0,
        "renewal_count": 0,
        "activated_at": None,
        "expires_at": None,
    })
    store.permits[rec["id"]] = rec
    return success(ser_permit(rec), status=201)


@bp.get("/demolition/projects/<pid>/permits")
@require_roles(*PERMIT_READ_ROLES)
def list_permits(pid):
    project = get_project(pid)
    return list_response(project_permits(project["id"]), ser_permit)


@bp.post("/demolition/permits/<pid>/transition")
@require_roles("PermitCoordinator", "AuthorityReviewer")
def permit_transition(pid):
    b = body()
    action = b.get("action")
    if not isinstance(action, str) or action not in PERMIT_ACTIONS:
        raise err(ERR_VALIDATION, "invalid action")
    permit = get_permit(pid)
    if g.role not in PERMIT_ACTION_ROLES[action]:
        raise err(ERR_FORBIDDEN, "role not permitted for this action")
    status = permit["status"]

    if action == "SUBMIT":
        if status == "DRAFT":
            if _has_other_live_permit(permit["project_id"], exclude_id=permit["id"]):
                raise err(ERR_DUPLICATE_ACTIVE_PERMIT,
                          "another permit of this project is outside a terminal status")
        elif status != "REVISION_REQUIRED":
            raise err(ERR_INVALID_STATE, "SUBMIT requires DRAFT or REVISION_REQUIRED")
        permit["status"] = "UNDER_REVIEW"
    elif action == "APPROVE":
        if status != "UNDER_REVIEW":
            raise err(ERR_INVALID_STATE, "APPROVE requires UNDER_REVIEW")
        permit["status"] = "APPROVED"
    elif action == "REQUEST_REVISION":
        if status != "UNDER_REVIEW":
            raise err(ERR_INVALID_STATE, "REQUEST_REVISION requires UNDER_REVIEW")
        permit["status"] = "REVISION_REQUIRED"
        permit["revision_count"] += 1
    elif action == "REJECT":
        if status != "UNDER_REVIEW":
            raise err(ERR_INVALID_STATE, "REJECT requires UNDER_REVIEW")
        permit["status"] = "REJECTED"
    else:  # ACTIVATE
        if status != "APPROVED":
            raise err(ERR_INVALID_STATE, "ACTIVATE requires APPROVED")
        disconnects = project_disconnects(permit["project_id"])
        if not disconnects or any(
                u["disconnect_status"] != "REPORTED_DISCONNECTED" or u["verification_status"] != "CONFIRMED"
                for u in disconnects):
            raise err(ERR_UTILITY_UNVERIFIED,
                      "all utility disconnects must be reported and CONFIRMED")
        permit["activated_at"] = now()
        permit["expires_at"] = permit["activated_at"] + timedelta(days=PERMIT_VALIDITY_DAYS)
        permit["status"] = "ACTIVE"

    touch(permit)
    return success(ser_permit(permit))


@bp.post("/demolition/permits/<pid>/renewals")
@require_roles("PermitCoordinator")
def renew_permit(pid):
    b = body()
    expected_version = req_int(b, "expected_permit_version")
    permit = get_permit(pid)
    if permit["status"] == "EXPIRED":
        raise err(ERR_PERMIT_EXPIRED, "cannot renew an EXPIRED permit")
    if permit["status"] != "ACTIVE":
        raise err(ERR_INVALID_STATE, "renewal requires ACTIVE")
    if expected_version != permit["version"]:
        raise err(ERR_STALE_VERSION, "expected_permit_version is stale")
    permit["expires_at"] = permit["expires_at"] + timedelta(days=RENEWAL_EXTENSION_DAYS)
    permit["renewal_count"] += 1
    touch(permit)
    return success(ser_permit(permit))
