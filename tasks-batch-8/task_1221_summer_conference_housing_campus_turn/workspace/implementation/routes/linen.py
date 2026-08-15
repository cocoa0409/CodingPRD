"""Linen issues and incremental returns (PRD 3.7)."""
from flask import Blueprint, request

from authz import ADMIN, HOUSEKEEPING, FINANCE, require_roles
from calc import linen_loss_charge
from db import store
from errors import ApiError, invalid_state
from respond import success
from serialize import ser_linen_issue
from store_ops import (
    get_or_404, json_body, new_common_fields, new_id, paginate, req_int,
    sorted_by_creation, touch,
)

bp = Blueprint("linen", __name__)

READ_ROLES = [ADMIN, HOUSEKEEPING, FINANCE]
WORK_ROLES = [HOUSEKEEPING, ADMIN]


@bp.route("/conference-groups/<gid>/linen-issues", methods=["POST"])
def issue_linen(gid):
    require_roles(WORK_ROLES)
    g = get_or_404(store.groups, gid)
    data = json_body()
    packs_issued = req_int(data, "packs_issued", minimum=1)
    if g["status"] not in ("CONFIRMED", "IN_HOUSE"):
        raise invalid_state("Linen may be issued only while the group is CONFIRMED or IN_HOUSE")
    issue = {
        "id": new_id(),
        "_seq": next(store.seq),
        "group_id": gid,
        "packs_issued": packs_issued,
        "packs_returned": 0,
        "packs_damaged": 0,
        "status": "ISSUED",
        "loss_charge_cents": 0,
    }
    issue.update(new_common_fields())
    issue["loss_charge_cents"] = linen_loss_charge(issue)
    store.linen_issues[issue["id"]] = issue
    return success(ser_linen_issue(issue), status=201)


@bp.route("/linen-issues", methods=["GET"])
def list_linen_issues():
    require_roles(READ_ROLES)
    group_id = request.args.get("group_id")
    status = request.args.get("status")
    items = [i for i in store.linen_issues.values()
             if (group_id is None or i["group_id"] == group_id)
             and (status is None or i["status"] == status)]
    items = sorted_by_creation(items)
    page, pagination = paginate(items)
    return success([ser_linen_issue(i) for i in page], response_type="array", pagination=pagination)


@bp.route("/linen-issues/<iid>", methods=["GET"])
def get_linen_issue(iid):
    require_roles(READ_ROLES)
    return success(ser_linen_issue(get_or_404(store.linen_issues, iid)))


@bp.route("/linen-issues/<iid>/record-return", methods=["POST"])
def record_return(iid):
    require_roles(WORK_ROLES)
    issue = get_or_404(store.linen_issues, iid)
    data = json_body()
    returned = req_int(data, "packs_returned", minimum=0)
    damaged = req_int(data, "packs_damaged", minimum=0)
    if issue["status"] not in ("ISSUED", "PARTIALLY_RETURNED"):
        raise invalid_state("Linen issue must be ISSUED or PARTIALLY_RETURNED to record a return")
    new_returned = issue["packs_returned"] + returned
    new_damaged = issue["packs_damaged"] + damaged
    if new_returned + new_damaged > issue["packs_issued"]:
        raise ApiError("ERR_LINEN_OVERRETURN", 422,
                       "Cumulative packs_returned + packs_damaged would exceed packs_issued")
    issue["packs_returned"] = new_returned
    issue["packs_damaged"] = new_damaged
    issue["status"] = "RECONCILED" if new_returned + new_damaged == issue["packs_issued"] else "PARTIALLY_RETURNED"
    issue["loss_charge_cents"] = linen_loss_charge(issue)
    touch(issue)
    return success(ser_linen_issue(issue))
