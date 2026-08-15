"""Branch endpoints."""
from flask import Blueprint, request

from db import stamp_new, store, touch
from errors import ERR_BRANCH_NOT_FOUND, ERR_INVALID_STATE_TRANSITION, ApiError, bad_request
from middleware import authenticate, body, f_str, f_str_opt, sorted_page
from response import ok, ok_list
from serializers import serialize_branch
from services.audit import main_event

bp = Blueprint("branches", __name__)

ALL_ROLES = ["SystemAdmin", "BranchManager", "Teller", "ComplianceAnalyst", "BSAOfficer", "Examiner"]


def get_branch_or_404(branch_id):
    b = store.branches.get(branch_id)
    if b is None:
        raise ApiError(ERR_BRANCH_NOT_FOUND, "Branch not found", 404)
    return b


@bp.post("/branches")
def create_branch():
    authenticate(["SystemAdmin"])
    b = body()
    name = f_str(b, "name")
    branch_code = f_str(b, "branch_code")
    region = f_str_opt(b, "region")
    for existing in store.branches.values():
        if existing["branch_code"] == branch_code:
            raise bad_request("branch_code must be unique across all branches")
    branch = {
        "name": name,
        "branch_code": branch_code,
        "region": region,
        "status": "ACTIVE",
    }
    stamp_new(branch)
    store.branches[branch["id"]] = branch
    main_event("POST /branches", "Branch", branch["id"], None, serialize_branch(branch))
    return ok(serialize_branch(branch), status=201)


@bp.get("/branches")
def list_branches():
    authenticate(ALL_ROLES)
    status = request.args.get("status")
    items = list(store.branches.values())
    if status is not None:
        items = [b for b in items if b["status"] == status]
    page, limit, offset, total = sorted_page(items)
    return ok_list([serialize_branch(b) for b in page], limit, offset, total)


@bp.get("/branches/<branch_id>")
def get_branch(branch_id):
    authenticate(ALL_ROLES)
    return ok(serialize_branch(get_branch_or_404(branch_id)))


@bp.post("/branches/<branch_id>/deactivate")
def deactivate_branch(branch_id):
    authenticate(["SystemAdmin"])
    branch = get_branch_or_404(branch_id)
    if branch["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, "Branch is not ACTIVE", 409)
    before = serialize_branch(branch)
    branch["status"] = "INACTIVE"
    touch(branch)
    main_event(
        "POST /branches/{id}/deactivate", "Branch", branch["id"], before,
        serialize_branch(branch),
    )
    return ok(serialize_branch(branch))


@bp.post("/branches/<branch_id>/reactivate")
def reactivate_branch(branch_id):
    authenticate(["SystemAdmin"])
    branch = get_branch_or_404(branch_id)
    if branch["status"] != "INACTIVE":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, "Branch is not INACTIVE", 409)
    before = serialize_branch(branch)
    branch["status"] = "ACTIVE"
    touch(branch)
    main_event(
        "POST /branches/{id}/reactivate", "Branch", branch["id"], before,
        serialize_branch(branch),
    )
    return ok(serialize_branch(branch))
