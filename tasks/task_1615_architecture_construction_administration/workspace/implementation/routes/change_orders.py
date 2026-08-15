"""ChangeOrder endpoints."""

from flask import Blueprint, request

import db
from errors import (
    ApiError,
    ERR_CHANGE_ORDER_INVALID_STATE,
    ERR_RFI_NOT_COST_IMPACT,
    ERR_STALE_VERSION,
)
from middleware import get_user_context, require_role, get_body
from response import success_object, success_list
from services import calcs
from services.helpers import (
    base_entity, touch, paginate, get_project, get_change_order, get_rfi,
    req_str, req_int, opt_int, opt_enum,
)
from services.lifecycle import require_project_active, check_counterparty

bp = Blueprint("change_orders", __name__)

ALL_ROLES = ("FirmAdmin", "ArchitectCA", "Contractor", "Owner")


@bp.post("/ca/change-orders")
def create_change_order():
    user_id, role = get_user_context()
    require_role(role, ("Contractor",))
    body = get_body(required=True)
    project_id = req_str(body, "project_id")
    title = req_str(body, "title")
    net_cost_change_cents = req_int(body, "net_cost_change_cents")
    time_extension_days = opt_int(body, "time_extension_days", 0)
    if time_extension_days < 0:
        from services.helpers import invalid
        invalid("time_extension_days must be >= 0")
    rfi_id = body.get("rfi_id")
    if rfi_id is not None and not isinstance(rfi_id, str):
        from services.helpers import invalid
        invalid("rfi_id must be a string")

    project = get_project(project_id)
    rfi = get_rfi(rfi_id) if rfi_id is not None else None
    check_counterparty(role, user_id, project)
    require_project_active(project)

    if rfi is not None:
        if (
            rfi["project_id"] != project_id
            or not rfi["cost_impact_flag"]
            or rfi["status"] not in ("ANSWERED", "CLOSED")
        ):
            raise ApiError(
                ERR_RFI_NOT_COST_IMPACT,
                "rfi_id references an RFI with cost_impact_flag false or status not in ANSWERED/CLOSED",
                422,
            )

    markup, total = calcs.change_order_pricing(net_cost_change_cents)

    co = base_entity()
    co.update({
        "project_id": project_id,
        "rfi_id": rfi_id,
        "title": title,
        "net_cost_change_cents": net_cost_change_cents,
        "time_extension_days": time_extension_days,
        "markup_cents": markup,
        "total_amount_cents": total,
        "recommendation": None,
        "recommended_by_user_id": None,
        "status": "SUBMITTED",
    })
    db.change_orders[co["id"]] = co
    return success_object(co, 201)


@bp.get("/ca/change-orders")
def list_change_orders():
    _, role = get_user_context()
    require_role(role, ALL_ROLES)
    items = list(db.change_orders.values())
    project_id = request.args.get("project_id")
    if project_id is not None:
        items = [c for c in items if c["project_id"] == project_id]
    status = request.args.get("status")
    if status is not None:
        items = [c for c in items if c["status"] == status]
    rfi_id = request.args.get("rfi_id")
    if rfi_id is not None:
        items = [c for c in items if c["rfi_id"] == rfi_id]
    page, limit, offset, total = paginate(items)
    return success_list(page, limit, offset, total)


@bp.get("/ca/change-orders/<cid>")
def get_one_change_order(cid):
    _, role = get_user_context()
    require_role(role, ALL_ROLES)
    return success_object(get_change_order(cid))


@bp.post("/ca/change-orders/<cid>/recommend")
def recommend_change_order(cid):
    user_id, role = get_user_context()
    require_role(role, ("ArchitectCA",))
    body = get_body(required=True)
    recommendation = opt_enum(body, "recommendation", ("ACCEPT", "REJECT"))
    get_body_notes = body.get("review_notes")  # optional, not persisted on entity
    co = get_change_order(cid)
    if co["status"] != "SUBMITTED":
        raise ApiError(
            ERR_CHANGE_ORDER_INVALID_STATE,
            "change-order recommend requires SUBMITTED",
            409,
        )
    co["recommendation"] = recommendation
    co["recommended_by_user_id"] = user_id
    co["status"] = "RECOMMEND_ACCEPTANCE" if recommendation == "ACCEPT" else "RECOMMEND_REJECTION"
    touch(co)
    return success_object(co)


@bp.post("/ca/change-orders/<cid>/owner-decision")
def owner_decision_change_order(cid):
    user_id, role = get_user_context()
    require_role(role, ("Owner",))
    body = get_body(required=True)
    decision = opt_enum(body, "decision", ("ACCEPT", "REJECT"))
    co = get_change_order(cid)
    project = db.projects[co["project_id"]]
    check_counterparty(role, user_id, project)
    if co["status"] not in ("RECOMMEND_ACCEPTANCE", "RECOMMEND_REJECTION"):
        raise ApiError(
            ERR_CHANGE_ORDER_INVALID_STATE,
            "owner-decision requires RECOMMEND_ACCEPTANCE or RECOMMEND_REJECTION",
            409,
        )
    co["status"] = "OWNER_ACCEPTED" if decision == "ACCEPT" else "OWNER_REJECTED"
    touch(co)
    return success_object(co)


@bp.post("/ca/change-orders/<cid>/incorporate")
def incorporate_change_order(cid):
    user_id, role = get_user_context()
    require_role(role, ("Owner",))
    body = get_body(required=True)
    expected_project_version = req_int(body, "expected_project_version")
    co = get_change_order(cid)
    project = db.projects[co["project_id"]]

    # OCC (stage 5) precedes counterparty (stage 6) and state gate (stage 8).
    if expected_project_version != project["version"]:
        raise ApiError(
            ERR_STALE_VERSION,
            "expected_project_version does not equal the project's current version",
            412,
        )
    check_counterparty(role, user_id, project)
    if co["status"] != "OWNER_ACCEPTED":
        raise ApiError(
            ERR_CHANGE_ORDER_INVALID_STATE,
            "incorporate requires OWNER_ACCEPTED",
            409,
        )

    co["status"] = "INCORPORATED"
    touch(co)

    # Mutate the project's adjusted position; increments project version by 1.
    project["adjusted_contract_sum_cents"] += co["total_amount_cents"]
    project["adjusted_substantial_completion_date"] = db.add_days(
        project["adjusted_substantial_completion_date"], co["time_extension_days"]
    )
    calcs.recompute_posture(project)
    calcs.recompute_contract_position(project)
    touch(project)
    calcs.recompute_draft_invoices(project)
    return success_object(co)
