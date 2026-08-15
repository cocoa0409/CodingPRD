"""Purchase-request read endpoints and lifecycle events (PropertyManager)."""

from flask import Blueprint, request

from db import store, touch
from domain import stock_receive
from errors import invalid_state, not_found, validation
from helpers import body, pagination, sorted_page
from middleware import authn, authorize
from response import ok_list, ok_object
from serializers import purchase_request_out

bp = Blueprint("purchase_requests", __name__)

READ_ROLES = ("Dispatcher", "Technician", "Vendor", "PropertyManager")


@bp.get("/purchase-requests")
def list_purchase_requests():
    authn_role = authn()[1]
    authorize(authn_role, READ_ROLES)
    limit, offset = pagination()
    items = list(store.purchase_requests.values())
    wo_filter = request.args.get("work_order_id")
    if wo_filter is not None:
        items = [p for p in items if p["work_order_id"] == wo_filter]
    part_filter = request.args.get("part_id")
    if part_filter is not None:
        items = [p for p in items if p["part_id"] == part_filter]
    page, total = sorted_page(items, limit, offset)
    return ok_list([purchase_request_out(p) for p in page], limit, offset, total)


@bp.get("/purchase-requests/<pr_id>")
def get_purchase_request(pr_id):
    authn_role = authn()[1]
    authorize(authn_role, READ_ROLES)
    pr = store.purchase_requests.get(pr_id)
    if pr is None:
        not_found("purchase request")
    return ok_object(purchase_request_out(pr))


@bp.post("/purchase-requests/<pr_id>/events")
def purchase_request_event(pr_id):
    authn_role = authn()[1]
    authorize(authn_role, {"PropertyManager"})
    pr = store.purchase_requests.get(pr_id)
    if pr is None:
        not_found("purchase request")
    b = body()
    event_type = b.get("event_type")
    if event_type == "APPROVE":
        if pr["status"] != "PENDING":
            invalid_state("only a PENDING purchase request can be approved")
        pr["status"] = "APPROVED"
        pr["auto_approved"] = False  # manual approval is never auto
        touch(pr)
    elif event_type == "REJECT":
        if pr["status"] != "PENDING":
            invalid_state("only a PENDING purchase request can be rejected")
        pr["status"] = "REJECTED"
        pr["decision_reason"] = b.get("decision_reason")
        touch(pr)
    elif event_type == "RECEIVE":
        if pr["status"] != "APPROVED":
            invalid_state("only an APPROVED purchase request can be received")
        pr["status"] = "RECEIVED"
        touch(pr)
        # Receipt posts stock: on_hand rises, reserved untouched.
        part = store.parts.get(pr["part_id"])
        if part is not None:
            stock_receive(part, pr["quantity"])
    else:
        validation("event_type must be APPROVE, REJECT, or RECEIVE")
    return ok_object(purchase_request_out(pr))
