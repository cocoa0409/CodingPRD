"""Path-id existence resolution with resource-specific not-found errors (PRD §2.5)."""
import db
from errors import (
    ApiError, ERR_SHOP_NOT_FOUND, ERR_PACKAGE_NOT_FOUND,
    ERR_INSPECTION_ITEM_NOT_FOUND, ERR_COUPON_NOT_FOUND, ERR_FLEET_ACCOUNT_NOT_FOUND,
    ERR_VEHICLE_NOT_FOUND, ERR_BAY_NOT_FOUND, ERR_TECHNICIAN_NOT_FOUND,
    ERR_QUEUE_TICKET_NOT_FOUND, ERR_WORK_ORDER_NOT_FOUND, ERR_LINE_NOT_FOUND,
)


def _get(store: dict, key, err: str, label: str) -> dict:
    if not isinstance(key, str) or key not in store:
        raise ApiError(err, 404, f"{label} not found")
    return store[key]


def get_shop(shop_id):
    return _get(db.shops, shop_id, ERR_SHOP_NOT_FOUND, "shop")


def get_package(pkg_id):
    return _get(db.service_packages, pkg_id, ERR_PACKAGE_NOT_FOUND, "service package")


def get_inspection_item(item_id):
    return _get(db.inspection_items, item_id, ERR_INSPECTION_ITEM_NOT_FOUND, "inspection item")


def get_coupon(coupon_id):
    return _get(db.coupons, coupon_id, ERR_COUPON_NOT_FOUND, "coupon")


def get_fleet_account(fleet_id):
    return _get(db.fleet_accounts, fleet_id, ERR_FLEET_ACCOUNT_NOT_FOUND, "fleet account")


def get_vehicle(veh_id):
    return _get(db.vehicles, veh_id, ERR_VEHICLE_NOT_FOUND, "vehicle")


def get_bay(bay_id):
    return _get(db.bays, bay_id, ERR_BAY_NOT_FOUND, "bay")


def get_technician(tech_id):
    return _get(db.technicians, tech_id, ERR_TECHNICIAN_NOT_FOUND, "technician")


def get_queue_ticket(tkt_id):
    return _get(db.queue_tickets, tkt_id, ERR_QUEUE_TICKET_NOT_FOUND, "queue ticket")


def get_work_order(wo_id):
    return _get(db.work_orders, wo_id, ERR_WORK_ORDER_NOT_FOUND, "work order")


def get_line_on_order(work_order_id: str, line_id):
    """Return the line iff it exists and belongs to the order, else ERR_LINE_NOT_FOUND."""
    if not isinstance(line_id, str) or line_id not in db.work_order_lines:
        raise ApiError(ERR_LINE_NOT_FOUND, 404, "line not found")
    ln = db.work_order_lines[line_id]
    if ln["work_order_id"] != work_order_id:
        raise ApiError(ERR_LINE_NOT_FOUND, 404, "line not found on this work order")
    return ln
