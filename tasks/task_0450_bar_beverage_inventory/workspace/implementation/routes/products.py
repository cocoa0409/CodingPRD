"""Product endpoints (PRD §3.1, §3.2)."""
from flask import Blueprint, request

import serialize
from db import db, stamp_create, touch
from errors import ApiError, ERR_DUPLICATE_SKU
from middleware import require_roles
from money import to_number, D
from response import object_response, array_response
from routes.lookup import get_product
from services.calc import keg_yield, reorder_quantity, DEFAULT_LINE_LOSS_PCT
from validate import (get_json_body, require, opt, as_str, as_enum, as_number,
                      as_int, parse_pagination, paginate, parse_bool_param)

bp = Blueprint("products", __name__)

CONTAINER_TYPES = {"BOTTLE", "KEG"}


def _sku_in_use(sku, exclude_id=None):
    for p in db.products.values():
        if p["id"] == exclude_id:
            continue
        if p["status"] != "ARCHIVED" and p["sku"] == sku:
            return True
    return False


@bp.route("/products", methods=["POST"])
@require_roles("InventoryManager")
def create_product():
    body = get_json_body()
    sku = as_str(require(body, "sku"), "sku", min_len=1, max_len=40)
    name = as_str(require(body, "name"), "name")
    container_type = as_enum(require(body, "container_type"), "container_type", CONTAINER_TYPES)
    container_volume_ml = as_number(require(body, "container_volume_ml"), "container_volume_ml", gt=0)
    unit_cost_cents = as_int(require(body, "unit_cost_cents"), "unit_cost_cents", ge=0)
    empty_container_weight_g = as_number(opt(body, "empty_container_weight_g", 0), "empty_container_weight_g", ge=0)
    density_g_per_ml = as_number(opt(body, "density_g_per_ml", 1.0), "density_g_per_ml", gt=0)
    case_pack = as_int(opt(body, "case_pack", 1), "case_pack", ge=1)

    if _sku_in_use(sku):
        raise ApiError(ERR_DUPLICATE_SKU, 409, "sku collides with an existing non-archived product.")

    record = {
        "sku": sku,
        "name": name,
        "container_type": container_type,
        "container_volume_ml": to_number(D(container_volume_ml)),
        "empty_container_weight_g": to_number(D(empty_container_weight_g)),
        "density_g_per_ml": to_number(D(density_g_per_ml)),
        "unit_cost_cents": unit_cost_cents,
        "case_pack": case_pack,
        "on_hand_units": 0,
        "status": "ACTIVE",
        "needs_reorder": False,
    }
    stamp_create(record)
    db.products[record["id"]] = record
    return object_response(serialize.product(record), 201)


@bp.route("/products/<pid>", methods=["GET"])
@require_roles("InventoryManager", "PurchasingAgent", "BarManager")
def read_product(pid):
    p = get_product(pid)
    return object_response(serialize.product(p))


@bp.route("/products", methods=["GET"])
@require_roles("InventoryManager", "PurchasingAgent", "BarManager")
def list_products():
    limit, offset = parse_pagination()
    status = request.args.get("status")
    container_type = request.args.get("container_type")
    needs_reorder = parse_bool_param("needs_reorder")
    items = list(db.products.values())
    if status is not None:
        items = [p for p in items if p["status"] == status]
    if container_type is not None:
        items = [p for p in items if p["container_type"] == container_type]
    if needs_reorder is not None:
        items = [p for p in items if p["needs_reorder"] == needs_reorder]
    page, total = paginate(items, limit, offset)
    return array_response([serialize.product(p) for p in page], limit, offset, total)


@bp.route("/products/<pid>/archive", methods=["POST"])
@require_roles("InventoryManager")
def archive_product(pid):
    p = get_product(pid)
    p["status"] = "ARCHIVED"
    touch(p)
    return object_response(serialize.product(p))


@bp.route("/products/<pid>/keg-yield", methods=["GET"])
@require_roles("InventoryManager", "BarManager")
def keg_yield_read(pid):
    p = get_product(pid)
    raw_pour = request.args.get("pour_size_ml")
    if raw_pour is None or raw_pour == "":
        raise ApiError("ERR_INVALID_REQUEST", 400, "pour_size_ml is required.")
    try:
        pour_size_ml = float(raw_pour)
    except (ValueError, TypeError):
        raise ApiError("ERR_INVALID_REQUEST", 400, "pour_size_ml must be a number.")
    if not (pour_size_ml > 0):
        raise ApiError("ERR_INVALID_REQUEST", 400, "pour_size_ml must be greater than 0.")
    raw_loss = request.args.get("line_loss_pct")
    if raw_loss is None or raw_loss == "":
        line_loss_pct = DEFAULT_LINE_LOSS_PCT
    else:
        try:
            line_loss_pct = float(raw_loss)
        except (ValueError, TypeError):
            raise ApiError("ERR_INVALID_REQUEST", 400, "line_loss_pct must be a number.")
    result = keg_yield(p, pour_size_ml, line_loss_pct)
    return object_response(result)


@bp.route("/products/<pid>/reorder-suggestion", methods=["GET"])
@require_roles("InventoryManager", "PurchasingAgent")
def reorder_suggestion_read(pid):
    p = get_product(pid)
    result = reorder_quantity(p)
    return object_response(result)


# ---- Reverse-reachability sub-resource lists (PRD §3.1) ---------------------

def _paged_response(items, limit, offset, serializer):
    page, total = paginate(items, limit, offset)
    return array_response([serializer(r) for r in page], limit, offset, total)


@bp.route("/products/<pid>/par-settings", methods=["GET"])
@require_roles("InventoryManager", "PurchasingAgent")
def product_par_settings(pid):
    get_product(pid)
    limit, offset = parse_pagination()
    status = request.args.get("status")
    items = [r for r in db.par_settings.values() if r["product_id"] == pid]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    return _paged_response(items, limit, offset, serialize.par_setting)


@bp.route("/products/<pid>/recipe-lines", methods=["GET"])
@require_roles("BarManager", "InventoryManager")
def product_recipe_lines(pid):
    get_product(pid)
    limit, offset = parse_pagination()
    items = [r for r in db.recipe_lines.values() if r["product_id"] == pid]
    return _paged_response(items, limit, offset, serialize.recipe_line)


@bp.route("/products/<pid>/count-lines", methods=["GET"])
@require_roles("InventoryManager")
def product_count_lines(pid):
    get_product(pid)
    limit, offset = parse_pagination()
    session_filter = request.args.get("count_session_id")
    items = [r for r in db.count_lines.values() if r["product_id"] == pid]
    if session_filter is not None:
        items = [r for r in items if r["count_session_id"] == session_filter]
    return _paged_response(items, limit, offset, serialize.count_line)


@bp.route("/products/<pid>/po-lines", methods=["GET"])
@require_roles("PurchasingAgent", "InventoryManager")
def product_po_lines(pid):
    get_product(pid)
    limit, offset = parse_pagination()
    items = [r for r in db.po_lines.values() if r["product_id"] == pid]
    return _paged_response(items, limit, offset, serialize.po_line)


@bp.route("/products/<pid>/invoice-lines", methods=["GET"])
@require_roles("PurchasingAgent", "InventoryManager")
def product_invoice_lines(pid):
    get_product(pid)
    limit, offset = parse_pagination()
    items = [r for r in db.invoice_lines.values() if r["product_id"] == pid]
    return _paged_response(items, limit, offset, serialize.invoice_line)


@bp.route("/products/<pid>/waste-logs", methods=["GET"])
@require_roles("BarManager", "InventoryManager")
def product_waste_logs(pid):
    get_product(pid)
    limit, offset = parse_pagination()
    reason = request.args.get("reason")
    items = [r for r in db.waste_logs.values() if r["product_id"] == pid]
    if reason is not None:
        items = [r for r in items if r["reason"] == reason]
    return _paged_response(items, limit, offset, serialize.waste_log)


@bp.route("/products/<pid>/keg-taps", methods=["GET"])
@require_roles("BarManager", "InventoryManager")
def product_keg_taps(pid):
    get_product(pid)
    limit, offset = parse_pagination()
    draft_line = request.args.get("draft_line_no")
    items = [r for r in db.keg_taps.values() if r["product_id"] == pid]
    if draft_line is not None:
        try:
            dln = int(draft_line)
        except (ValueError, TypeError):
            from errors import invalid_request
            raise invalid_request("draft_line_no must be an integer.")
        items = [r for r in items if r["draft_line_no"] == dln]
    return _paged_response(items, limit, offset, serialize.keg_tap)
