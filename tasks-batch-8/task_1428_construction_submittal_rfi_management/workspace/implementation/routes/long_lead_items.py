"""LongLeadItem routes: list/get, patch, advance, expedite."""
from flask import Blueprint, request

import calc
from authz import ALL_ROLES, PROJECT_ENGINEER, PROJECT_MANAGER, require_roles
from db import store
from errors import (
    invalid_request,
    lli_invalid_advance,
    lli_not_found,
    project_not_found,
    submittal_not_found,
)
from respond import success
from serialize import ser_lli
from services import (
    find_lli_for_submittal,
    recompute_lli_with_events,
    require_active,
)
from store_ops import (
    json_body,
    opt_enum,
    opt_str,
    paginate,
    req_date,
    req_enum,
    sorted_by_creation,
    touch,
)

bp = Blueprint("long_lead_items", __name__)

CRITICALITIES = ("CRITICAL", "HIGH", "STANDARD")


def get_lli_or_404(item_id):
    i = store.long_lead_items.get(item_id)
    if i is None:
        raise lli_not_found()
    return i


@bp.route("/v1/projects/<projectId>/long-lead-items", methods=["GET"])
def list_project_llis(projectId):
    require_roles(ALL_ROLES)
    project = store.projects.get(projectId)
    if project is None:
        raise project_not_found()
    items = sorted_by_creation(
        [i for i in store.long_lead_items.values() if i["project_id"] == projectId]
    )
    page, pagination = paginate(items)
    return success([ser_lli(i) for i in page], response_type="array", pagination=pagination)


@bp.route("/v1/long-lead-items", methods=["GET"])
def list_llis():
    require_roles(ALL_ROLES)
    items = list(store.long_lead_items.values())
    project_id = request.args.get("project_id")
    if project_id:
        items = [i for i in items if i["project_id"] == project_id]
    submittal_id = request.args.get("submittal_id")
    if submittal_id:
        items = [i for i in items if i["submittal_id"] == submittal_id]
    status = request.args.get("status")
    if status:
        items = [i for i in items if i["status"] == status]
    escalation_level = request.args.get("escalation_level")
    if escalation_level is not None:
        try:
            target = int(escalation_level)
        except ValueError:
            raise invalid_request("escalation_level must be an integer")
        items = [i for i in items if i["escalation_level"] == target]
    items = sorted_by_creation(items)
    page, pagination = paginate(items)
    return success([ser_lli(i) for i in page], response_type="array", pagination=pagination)


@bp.route("/v1/long-lead-items/<itemId>", methods=["GET"])
def get_lli(itemId):
    require_roles(ALL_ROLES)
    item = get_lli_or_404(itemId)
    return success(ser_lli(item))


@bp.route("/v1/submittals/<submittalId>/long-lead-item", methods=["GET"])
def get_lli_by_submittal(submittalId):
    require_roles(ALL_ROLES)
    sub = store.submittals.get(submittalId)
    if sub is None:
        raise submittal_not_found()
    item = find_lli_for_submittal(submittalId)
    items = [item] if item is not None else []
    return success([ser_lli(i) for i in items], response_type="array", pagination={
        "limit": 10, "offset": 0, "total_count": len(items), "has_more": False,
    })


@bp.route("/v1/long-lead-items/<itemId>", methods=["PATCH"])
def patch_lli(itemId):
    require_roles([PROJECT_ENGINEER])
    item = get_lli_or_404(itemId)
    project = store.projects.get(item["project_id"])
    if project is None:
        raise project_not_found()
    require_active(project)
    data = json_body()
    if "criticality" in data and data["criticality"] is not None:
        item["criticality"] = opt_enum(data, "criticality", CRITICALITIES)
    if "description" in data and data["description"] is not None:
        item["description"] = opt_str(data, "description", "")
    submittal = store.submittals.get(item["submittal_id"])
    calc.recompute_lli(item, submittal)
    touch(item)
    return success(ser_lli(item))


@bp.route("/v1/long-lead-items/<itemId>/advance", methods=["POST"])
def advance_lli(itemId):
    require_roles([PROJECT_ENGINEER])
    item = get_lli_or_404(itemId)
    project = store.projects.get(item["project_id"])
    if project is None:
        raise project_not_found()
    require_active(project)
    data = json_body()
    to_status = req_enum(data, "to_status", calc.LLI_ADVANCE_CHAIN + ["CANCELLED"])
    actual_date = req_date(data, "actual_date")

    if item["status"] in ("DELIVERED", "CANCELLED"):
        raise lli_invalid_advance("Item is terminal")
    try:
        current_idx = calc.LLI_ADVANCE_CHAIN.index(item["status"])
    except ValueError:
        raise lli_invalid_advance("Unknown current status")
    if current_idx + 1 >= len(calc.LLI_ADVANCE_CHAIN):
        raise lli_invalid_advance("No further step")
    expected_next = calc.LLI_ADVANCE_CHAIN[current_idx + 1]
    if to_status != expected_next:
        raise lli_invalid_advance("to_status must be exactly %s" % expected_next)

    if to_status == "QUOTED":
        item["quoted_date"] = actual_date
    elif to_status == "PO_ISSUED":
        item["po_issued_date"] = actual_date
    elif to_status == "SHIPPED":
        item["shipped_date"] = actual_date
    elif to_status == "DELIVERED":
        item["delivered_date"] = actual_date
    item["status"] = to_status

    submittal = store.submittals.get(item["submittal_id"])
    if to_status == "DELIVERED":
        item["days_late"] = 0
        item["escalation_level"] = 0
        item["priority_score"] = calc.compute_priority_score(item, submittal)
        if submittal is not None:
            submittal["expediting_status"] = "CLEAR"
            touch(submittal)
    else:
        calc.recompute_lli(item, submittal)
    touch(item)
    return success(ser_lli(item))


@bp.route("/v1/long-lead-items/<itemId>/expedite", methods=["POST"])
def expedite_lli(itemId):
    require_roles([PROJECT_MANAGER])
    item = get_lli_or_404(itemId)
    project = store.projects.get(item["project_id"])
    if project is None:
        raise project_not_found()
    require_active(project)
    submittal = store.submittals.get(item["submittal_id"])
    if submittal is not None and submittal["expediting_status"] == "MONITORING":
        submittal["expediting_status"] = "EXPEDITING"
        touch(submittal)
    calc.recompute_lli(item, submittal)
    touch(item)
    return success(ser_lli(item))
