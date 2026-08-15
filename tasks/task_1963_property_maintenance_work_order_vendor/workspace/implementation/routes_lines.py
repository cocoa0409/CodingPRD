"""Work-order-part read endpoints."""

from flask import Blueprint, request

from db import store
from errors import not_found
from helpers import pagination, sorted_page
from middleware import authn, authorize
from response import ok_list, ok_object
from serializers import work_order_part_out

bp = Blueprint("lines", __name__)

READ_ROLES = ("Dispatcher", "Technician", "Vendor", "PropertyManager")


@bp.get("/work-order-parts")
def list_work_order_parts():
    authn_role = authn()[1]
    authorize(authn_role, READ_ROLES)
    limit, offset = pagination()
    items = list(store.work_order_parts.values())
    wo_filter = request.args.get("work_order_id")
    if wo_filter is not None:
        items = [w for w in items if w["work_order_id"] == wo_filter]
    part_filter = request.args.get("part_id")
    if part_filter is not None:
        items = [w for w in items if w["part_id"] == part_filter]
    page, total = sorted_page(items, limit, offset)
    return ok_list([work_order_part_out(w) for w in page], limit, offset, total)


@bp.get("/work-order-parts/<wop_id>")
def get_work_order_part(wop_id):
    authn_role = authn()[1]
    authorize(authn_role, READ_ROLES)
    line = store.work_order_parts.get(wop_id)
    if line is None:
        not_found("work order part")
    return ok_object(work_order_part_out(line))
