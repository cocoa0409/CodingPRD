"""InventoryProgram and ReleaseOrder endpoints."""
from flask import Blueprint, request

from db import db
from errors import (
    err_insufficient_program_balance,
    err_invalid_quantity,
    err_invalid_request,
    err_invalid_state,
    err_not_found,
    err_ownership_mismatch,
    err_program_not_releasable,
)
from middleware import require_roles
from response import success_object
from services.calcs import (
    bump,
    recompute_program_balance,
    reorder_threshold_check,
)
from services.serialize import serialize_inventory_program, serialize_release_order
from util import D, is_int, is_num, new_id, parse_date, utcnow_iso
from ._helpers import get_json_body, paginate_list, require_fields

bp = Blueprint("inventory_programs", __name__)

ALL_ROLES = ("PlantAdmin", "SalesRep", "ProductionPlanner", "CustomerService", "ClaimsAdjuster", "Customer")
ROUTING_TYPES = {"DIE_CUT", "SLOTTED"}


def _get_program_or_404(pid):
    p = db.inventory_programs.get(pid)
    if p is None:
        raise err_not_found("inventory program not found")
    return p


@bp.route("/api/inventory-programs", methods=["POST"])
@require_roles("SalesRep")
def create_program(_user_id, _role):
    body = get_json_body()
    require_fields(body, [
        "customer_id", "board_grade_id", "program_name", "routing_type",
        "blank_width_in", "blank_length_in", "reorder_point", "replenishment_qty",
    ])

    customer_id = body["customer_id"]
    board_grade_id = body["board_grade_id"]
    program_name = body["program_name"]
    routing_type = body["routing_type"]
    blank_width = body["blank_width_in"]
    blank_length = body["blank_length_in"]
    reorder_point = body["reorder_point"]
    replenishment_qty = body["replenishment_qty"]

    if routing_type not in ROUTING_TYPES:
        raise err_invalid_request("routing_type must be DIE_CUT or SLOTTED")
    if not isinstance(program_name, str) or not program_name.strip():
        raise err_invalid_request("program_name must be a non-empty string")
    if not is_num(blank_width) or D(blank_width) <= 0:
        raise err_invalid_request("blank_width_in must be > 0")
    if not is_num(blank_length) or D(blank_length) <= 0:
        raise err_invalid_request("blank_length_in must be > 0")
    if not is_int(reorder_point) or reorder_point < 0:
        raise err_invalid_request("reorder_point must be an integer >= 0")
    if not is_int(replenishment_qty) or replenishment_qty <= 0:
        raise err_invalid_request("replenishment_qty must be an integer > 0")

    # Existence
    if customer_id not in db.customer_accounts:
        raise err_not_found("customer not found")
    if board_grade_id not in db.board_grades:
        raise err_not_found("board grade not found")

    now = utcnow_iso()
    pid = new_id()
    program = {
        "id": pid,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "customer_id": customer_id,
        "board_grade_id": board_grade_id,
        "program_name": program_name,
        "routing_type": routing_type,
        "blank_width_in": D(blank_width),
        "blank_length_in": D(blank_length),
        "reorder_point": reorder_point,
        "replenishment_qty": replenishment_qty,
        "on_hand_qty": 0,
        "committed_qty": 0,
        "available_qty": 0,
        "status": "ACTIVE",
    }
    db.inventory_programs[pid] = program
    return success_object(serialize_inventory_program(program), 201)


@bp.route("/api/inventory-programs/<pid>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_program(pid, _user_id, _role):
    p = _get_program_or_404(pid)
    return success_object(serialize_inventory_program(p), 200)


@bp.route("/api/inventory-programs", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_programs(_user_id, _role):
    filters = {
        "customer_id": request.args.get("customer_id"),
        "board_grade_id": request.args.get("board_grade_id"),
        "status": request.args.get("status"),
    }
    return paginate_list(list(db.inventory_programs.values()), serialize_inventory_program, filters)


@bp.route("/api/inventory-programs/<pid>/receipts", methods=["POST"])
@require_roles("ProductionPlanner")
def post_receipt(pid, _user_id, _role):
    p = _get_program_or_404(pid)
    body = get_json_body()
    require_fields(body, ["qty"])

    qty = body["qty"]
    if not is_int(qty) or qty <= 0:
        raise err_invalid_quantity("qty must be an integer > 0")

    p["on_hand_qty"] = p["on_hand_qty"] + qty
    recompute_program_balance(p)
    reorder_threshold_check(p)
    bump(p)
    return success_object(serialize_inventory_program(p), 200)


@bp.route("/api/inventory-programs/<pid>/suspend", methods=["POST"])
@require_roles("PlantAdmin")
def suspend_program(pid, _user_id, _role):
    p = _get_program_or_404(pid)
    if p["status"] not in ("ACTIVE", "REPLENISHMENT_NEEDED"):
        raise err_invalid_state("program is not ACTIVE or REPLENISHMENT_NEEDED")
    p["status"] = "SUSPENDED"
    bump(p)
    return success_object(serialize_inventory_program(p), 200)


@bp.route("/api/inventory-programs/<pid>/reactivate", methods=["POST"])
@require_roles("PlantAdmin")
def reactivate_program(pid, _user_id, _role):
    p = _get_program_or_404(pid)
    if p["status"] != "SUSPENDED":
        raise err_invalid_state("program is not SUSPENDED")
    p["status"] = "ACTIVE"
    bump(p)
    return success_object(serialize_inventory_program(p), 200)


# =============================================================================
# Release orders under a program
# =============================================================================

@bp.route("/api/inventory-programs/<pid>/release-orders", methods=["POST"])
@require_roles("Customer")
def create_release_order(pid, _user_id, _role):
    p = _get_program_or_404(pid)

    # Ownership check: X-User-ID must equal program.customer_id
    if _user_id != p["customer_id"]:
        raise err_ownership_mismatch("customer does not own the target program")

    body = get_json_body()
    require_fields(body, ["qty", "requested_ship_date"])

    qty = body["qty"]
    requested_ship_date = body["requested_ship_date"]

    if not isinstance(requested_ship_date, str) or parse_date(requested_ship_date) is None:
        raise err_invalid_request("requested_ship_date must be a valid ISO date (YYYY-MM-DD)")

    # State gate: program must be ACTIVE for creation
    if p["status"] != "ACTIVE":
        raise err_program_not_releasable("release creation requires program status ACTIVE")

    # Quantity positivity floor (ERR_INVALID_QUANTITY)
    if not is_int(qty) or qty <= 0:
        raise err_invalid_quantity("qty must be an integer > 0")

    # Balance ceiling (ERR_INSUFFICIENT_PROGRAM_BALANCE)
    if qty > p["available_qty"]:
        raise err_insufficient_program_balance("release qty exceeds program available_qty")

    now = utcnow_iso()
    rid = new_id()
    release = {
        "id": rid,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "program_id": p["id"],
        "qty": qty,
        "requested_ship_date": requested_ship_date,
        "status": "PENDING",
    }
    db.release_orders[rid] = release

    # Commit counted immediately
    recompute_program_balance(p)
    bump(p)

    return success_object(serialize_release_order(release), 201)


@bp.route("/api/inventory-programs/<pid>/release-orders", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_release_orders(pid, _user_id, _role):
    p = _get_program_or_404(pid)
    rels = [r for r in db.release_orders.values() if r["program_id"] == p["id"]]
    filters = {"status": request.args.get("status")}
    return paginate_list(rels, serialize_release_order, filters)


# =============================================================================
# ReleaseOrder action endpoints (top-level path)
# =============================================================================

def _get_release_or_404(rid):
    r = db.release_orders.get(rid)
    if r is None:
        raise err_not_found("release order not found")
    return r


@bp.route("/api/release-orders/<rid>/approve", methods=["POST"])
@require_roles("PlantAdmin")
def approve_release(rid, _user_id, _role):
    r = _get_release_or_404(rid)
    p = db.inventory_programs.get(r["program_id"])
    if p is None:
        raise err_not_found("inventory program not found")

    if r["status"] != "PENDING":
        raise err_invalid_state("release is not PENDING")
    if p["status"] not in ("ACTIVE", "REPLENISHMENT_NEEDED"):
        raise err_program_not_releasable("approve requires program ACTIVE or REPLENISHMENT_NEEDED")

    r["status"] = "APPROVED"
    bump(r)
    # commit already counted from creation — no recompute needed
    return success_object(serialize_release_order(r), 200)


@bp.route("/api/release-orders/<rid>/ship", methods=["POST"])
@require_roles("ProductionPlanner")
def ship_release(rid, _user_id, _role):
    r = _get_release_or_404(rid)
    p = db.inventory_programs.get(r["program_id"])
    if p is None:
        raise err_not_found("inventory program not found")

    if r["status"] != "APPROVED":
        raise err_invalid_state("release is not APPROVED")
    if p["status"] not in ("ACTIVE", "REPLENISHMENT_NEEDED"):
        raise err_program_not_releasable("ship requires program ACTIVE or REPLENISHMENT_NEEDED")

    r["status"] = "SHIPPED"
    bump(r)

    # Decrement on_hand and committed
    p["on_hand_qty"] = p["on_hand_qty"] - r["qty"]
    recompute_program_balance(p)
    # Threshold check may flip to REPLENISHMENT_NEEDED and auto-create a replenishment BoxOrder
    reorder_threshold_check(p)
    bump(p)

    return success_object(serialize_release_order(r), 200)


@bp.route("/api/release-orders/<rid>/cancel", methods=["POST"])
@require_roles("Customer")
def cancel_release(rid, _user_id, _role):
    r = _get_release_or_404(rid)
    p = db.inventory_programs.get(r["program_id"])
    if p is None:
        raise err_not_found("inventory program not found")

    # Ownership
    if _user_id != p["customer_id"]:
        raise err_ownership_mismatch("customer does not own the target program")

    if r["status"] not in ("PENDING", "APPROVED"):
        raise err_invalid_state("release is not PENDING or APPROVED")

    r["status"] = "CANCELLED"
    bump(r)

    recompute_program_balance(p)
    bump(p)

    return success_object(serialize_release_order(r), 200)
