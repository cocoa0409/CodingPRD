"""Follow-up Adjustments + warranty/no-charge windows (PRD §3.7)."""
from flask import Blueprint

from db import db, base_common_fields
from errors import ApiError
from middleware import get_auth, require_roles
from response import ok_object, ok_array
from validation import lookup, parse_pagination, paginate
from clock import parse_iso, add_days, to_iso_z
from services import touch, FREE_FITTING_DAYS
from serializers import adjustment_out

bp = Blueprint("adjustments", __name__)


@bp.route("/op/device-orders/<rid>/adjustments", methods=["POST"])
def create_adjustment(rid):
    _, role = get_auth()
    require_roles(role, {"Practitioner"})
    order = lookup(db.device_orders, rid)

    if order["status"] != "DELIVERED":
        raise ApiError("ERR_NOT_DELIVERED", "Adjustment can only be recorded on a DELIVERED order.")

    adjustment_dt = parse_iso(db.current_utc)
    delivery_dt = parse_iso(order["delivery_date"])
    warranty_expiry = parse_iso(order["warranty_expiry"])

    free_fitting_cutoff = add_days(delivery_dt, FREE_FITTING_DAYS)
    within_free_fitting = adjustment_dt <= free_fitting_cutoff
    within_warranty = adjustment_dt <= warranty_expiry
    billable = not (within_free_fitting or within_warranty)

    adj = base_common_fields()
    adj.update({
        "device_order_id": order["id"],
        "adjustment_date": to_iso_z(adjustment_dt),
        "within_warranty": within_warranty,
        "billable": billable,
    })
    db.adjustments[adj["id"]] = adj
    return ok_object(adjustment_out(adj), 201)


@bp.route("/op/device-orders/<rid>/adjustments", methods=["GET"])
def list_adjustments(rid):
    _, role = get_auth()
    require_roles(role, {"Practitioner", "BillingSpecialist", "ComplianceOfficer"})
    order = lookup(db.device_orders, rid)
    limit, offset = parse_pagination()

    items = [a for a in db.adjustments.values() if a["device_order_id"] == order["id"]]
    page, total = paginate(items, limit, offset)
    return ok_array([adjustment_out(a) for a in page], limit, offset, total, 200)
