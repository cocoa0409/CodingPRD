"""Motor routes."""
from flask import Blueprint, request
from middleware import require_role
from errors import err_invalid_input, err_duplicate_active, err_reference_not_found
from db import store, new_id
from response import success_object, success_list
from serializers import motor_view
from routes.common import (
    get_json_body, parse_str_field, parse_int_field, parse_number_field,
    parse_bool_field, get_shop_or_404, get_motor_or_404,
    get_pagination, paginate,
)

bp = Blueprint("motors", __name__)


@bp.route("/shops/<shopId>/motors", methods=["POST"])
def create_motor(shopId):
    require_role("ServiceManager")
    get_shop_or_404(shopId)
    body = get_json_body()
    is_pool_spare = parse_bool_field(body, "is_pool_spare", default=False)
    owner_customer_id = body.get("owner_customer_id")
    if is_pool_spare:
        # nullable only for pool spares
        if owner_customer_id is not None and not isinstance(owner_customer_id, str):
            raise err_invalid_input("owner_customer_id must be a string or null")
        if owner_customer_id is not None:
            # if provided it must resolve
            cust = store.customers.get(owner_customer_id)
            if cust is None or cust["shop_id"] != shopId:
                raise err_reference_not_found("owner_customer_id does not resolve")
    else:
        if not isinstance(owner_customer_id, str):
            raise err_invalid_input("owner_customer_id is required for non-pool motors")
        cust = store.customers.get(owner_customer_id)
        if cust is None or cust["shop_id"] != shopId:
            raise err_reference_not_found("owner_customer_id does not resolve")

    serial = parse_str_field(body, "serial_number", required=True)
    # unique per shop
    for m in store.motors.values():
        if m["shop_id"] == shopId and m["serial_number"] == serial:
            raise err_duplicate_active("serial_number already exists in shop")

    rated_kw = parse_number_field(body, "rated_kw", required=True, min_value=0)
    frame_mm = parse_int_field(body, "frame_mm", required=True, min_value=0)
    voltage_v = parse_int_field(body, "voltage_v", required=True)
    manufacture_year = parse_int_field(body, "manufacture_year", required=True)
    supersedes = body.get("supersedes_motor_id")
    if supersedes is not None:
        if not isinstance(supersedes, str):
            raise err_invalid_input("supersedes_motor_id must be a string or null")
        sup = store.motors.get(supersedes)
        if sup is None or sup["shop_id"] != shopId:
            raise err_reference_not_found("supersedes_motor_id does not resolve")

    now = store.now()
    m = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "shop_id": shopId,
        "owner_customer_id": owner_customer_id,
        "serial_number": serial,
        "rated_kw": rated_kw,
        "frame_mm": frame_mm,
        "voltage_v": voltage_v,
        "manufacture_year": manufacture_year,
        "custody": "IN_POOL" if is_pool_spare else "WITH_CUSTOMER",
        "is_pool_spare": is_pool_spare,
        "supersedes_motor_id": supersedes,
    }
    store.motors[m["id"]] = m
    return success_object(motor_view(m), status=201)


def _list_motors(shop_id_filter):
    items = list(store.motors.values())
    if shop_id_filter is not None:
        items = [m for m in items if m["shop_id"] == shop_id_filter]
    if request.args.get("owner_customer_id"):
        v = request.args["owner_customer_id"]
        items = [m for m in items if m["owner_customer_id"] == v]
    if request.args.get("supersedes_motor_id"):
        v = request.args["supersedes_motor_id"]
        items = [m for m in items if m["supersedes_motor_id"] == v]
    if request.args.get("custody"):
        v = request.args["custody"]
        items = [m for m in items if m["custody"] == v]
    if "is_pool_spare" in request.args:
        v = request.args["is_pool_spare"].lower()
        flag = v in ("true", "1", "yes")
        items = [m for m in items if m["is_pool_spare"] == flag]
    items.sort(key=lambda m: m["created_at"])
    return items


@bp.route("/shops/<shopId>/motors", methods=["GET"])
def list_motors(shopId):
    require_role("ShopAdmin", "Technician", "WindingTechnician", "Estimator", "ServiceManager")
    get_shop_or_404(shopId)
    limit, offset = get_pagination()
    items = _list_motors(shopId)
    page, total = paginate(items, limit, offset)
    return success_list([motor_view(m) for m in page], limit, offset, total)


@bp.route("/shops/<shopId>/motors/<motorId>", methods=["GET"])
def get_motor(shopId, motorId):
    require_role("ShopAdmin", "Technician", "WindingTechnician", "Estimator", "ServiceManager", "Customer")
    get_shop_or_404(shopId)
    m = get_motor_or_404(motorId, shopId)
    return success_object(motor_view(m))


@bp.route("/shops/motors", methods=["GET"])
def list_motors_flat():
    require_role("ShopAdmin", "Technician", "WindingTechnician", "Estimator", "ServiceManager")
    limit, offset = get_pagination()
    shop_id = request.args.get("shop_id")
    items = _list_motors(shop_id)
    page, total = paginate(items, limit, offset)
    return success_list([motor_view(m) for m in page], limit, offset, total)


@bp.route("/shops/motors/<motorId>", methods=["GET"])
def get_motor_flat(motorId):
    require_role("ShopAdmin", "Technician", "WindingTechnician", "Estimator", "ServiceManager", "Customer")
    m = get_motor_or_404(motorId)
    return success_object(motor_view(m))
