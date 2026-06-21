"""Machine + VendTransaction endpoints (PRD §3.2, §3.3)."""
from datetime import timedelta, timezone

from flask import Blueprint, request

from db import db, stamp_create, touch
from errors import (
    err,
    ERR_INVALID_STATE,
    ERR_STALE_VERSION,
    ERR_MACHINE_UNAVAILABLE,
    ERR_DRY_BLOCKS_REQUIRED,
    ERR_MEMBER_NOT_ACTIVE,
    ERR_NO_FREE_CREDIT,
    ERR_INSUFFICIENT_WALLET,
    ERR_INVALID_REQUEST,
    ERR_FORBIDDEN,
)
from middleware import get_identity, require_roles
from response import object_response, array_response
from services.common import (
    get_body,
    require_fields,
    require_int,
    require_str,
    require_enum,
    require_bool,
    parse_pagination,
    paginate,
    get_or_404,
    require_active_plan,
    write_ledger,
    open_shift_for,
)
from services.calc import vend_quote_cents, floor_div
from services.cycle import complete_machine_cycle, format_iso
from services.shift_calc import recompute_and_touch
from services.serialize import view

bp = Blueprint("machines", __name__)

MACHINE_TYPES = {"WASHER", "DRYER"}
PAYMENT_METHODS = {"COIN", "CARD", "APP_WALLET"}


# ===== Machine CRUD ==========================================================
@bp.post("/machines")
def create_machine():
    _, role = get_identity()
    require_roles(role, {"Manager"})
    body = get_body()
    require_fields(body, ["label", "machine_type", "capacity_lb"])
    label = require_str(body["label"], "label")
    machine_type = body["machine_type"]
    require_enum(machine_type, MACHINE_TYPES, "machine_type")
    capacity = require_int(body["capacity_lb"], "capacity_lb", gt=0)
    cycle_minutes = 30
    if "cycle_minutes" in body and body["cycle_minutes"] is not None:
        cycle_minutes = require_int(body["cycle_minutes"], "cycle_minutes", gt=0)

    machine = {
        "label": label,
        "machine_type": machine_type,
        "capacity_lb": capacity,
        "cycle_minutes": cycle_minutes,
        "status": "IDLE",
        "current_vend_id": None,
        "cycle_ends_at": None,
        "lifetime_vend_count": 0,
        "fault_count": 0,
    }
    stamp_create(machine)
    with db.lock:
        db.machines[machine["id"]] = machine
    return object_response(view(machine), status=201)


@bp.get("/machines")
def list_machines():
    _, role = get_identity()
    require_roles(role, {"Manager", "Attendant", "Member"})
    limit, offset = parse_pagination()
    status = request.args.get("status")
    machine_type = request.args.get("machine_type")
    current_vend_id = request.args.get("current_vend_id")
    items = list(db.machines.values())
    if status is not None:
        items = [m for m in items if m["status"] == status]
    if machine_type is not None:
        items = [m for m in items if m["machine_type"] == machine_type]
    if current_vend_id is not None:
        items = [m for m in items if m.get("current_vend_id") == current_vend_id]
    window, total = paginate(items, limit, offset)
    return array_response([view(m) for m in window], limit, offset, total)


@bp.get("/machines/<machine_id>")
def get_machine(machine_id):
    _, role = get_identity()
    require_roles(role, {"Manager", "Attendant", "Member"})
    machine = get_or_404(db.machines, machine_id, "Machine")
    return object_response(view(machine))


# ===== Vend lists ============================================================
@bp.get("/machines/<machine_id>/vends")
def list_machine_vends(machine_id):
    _, role = get_identity()
    require_roles(role, {"Manager", "Attendant", "Member"})
    get_or_404(db.machines, machine_id, "Machine")
    limit, offset = parse_pagination()
    items = [v for v in db.vends.values() if v["machine_id"] == machine_id]
    window, total = paginate(items, limit, offset)
    return array_response([view(v) for v in window], limit, offset, total)


@bp.get("/vends")
def list_vends():
    _, role = get_identity()
    require_roles(role, {"Manager", "Attendant", "Member"})
    limit, offset = parse_pagination()
    machine_id = request.args.get("machine_id")
    member_id = request.args.get("member_id")
    shift_id = request.args.get("shift_id")
    payment_status = request.args.get("payment_status")
    cycle_status = request.args.get("cycle_status")
    items = list(db.vends.values())
    if machine_id is not None:
        items = [v for v in items if v["machine_id"] == machine_id]
    if member_id is not None:
        items = [v for v in items if v.get("member_id") == member_id]
    if shift_id is not None:
        items = [v for v in items if v.get("shift_id") == shift_id]
    if payment_status is not None:
        items = [v for v in items if v["payment_status"] == payment_status]
    if cycle_status is not None:
        items = [v for v in items if v["cycle_status"] == cycle_status]
    window, total = paginate(items, limit, offset)
    return array_response([view(v) for v in window], limit, offset, total)


@bp.get("/vends/<vend_id>")
def get_vend(vend_id):
    _, role = get_identity()
    require_roles(role, {"Manager", "Attendant", "Member"})
    vend = get_or_404(db.vends, vend_id, "VendTransaction")
    return object_response(view(vend))


# ===== Vend capture ==========================================================
@bp.post("/machines/<machine_id>/vends")
def capture_vend(machine_id):
    user_id, role = get_identity()
    require_roles(role, {"Member", "Attendant"})
    with db.lock:
        machine = get_or_404(db.machines, machine_id, "Machine")
        body = get_body()
        # Well-formedness (priority 4).
        require_fields(body, ["payment_method", "expected_machine_version"])
        payment_method = body["payment_method"]
        require_enum(payment_method, PAYMENT_METHODS, "payment_method")
        expected_version = require_int(body["expected_machine_version"], "expected_machine_version")
        member_id = body.get("member_id")
        dry_blocks = body.get("dry_blocks", 0)
        if dry_blocks is None:
            dry_blocks = 0
        require_int(dry_blocks, "dry_blocks", minimum=0)
        used_free_credit = body.get("used_free_credit", False)
        if used_free_credit is None:
            used_free_credit = False
        require_bool(used_free_credit, "used_free_credit")
        if "card_token" in body and body["card_token"] is not None:
            require_str(body["card_token"], "card_token")

        # Existence of referenced member (priority 3) before business rules.
        member = None
        if member_id is not None:
            member = get_or_404(db.members, member_id, "Member")
        # Ownership (priority 5): a Member capturing with member_id must own it.
        if role == "Member" and member_id is not None and member_id != user_id:
            raise err(ERR_FORBIDDEN, "Member may only act on their own account")

        # OCC (priority 7) is checked before the machine-availability rule
        # (priority 9): a stale-version writer is rejected with ERR_STALE_VERSION
        # before ERR_MACHINE_UNAVAILABLE.
        if expected_version != machine["version"]:
            raise err(ERR_STALE_VERSION, "Stale machine version")

        # No ACTIVE plan -> ERR_NO_ACTIVE_PLAN (priority 8).
        plan = require_active_plan()

        # Machine availability (priority 9): vend rejected if machine not IDLE.
        if machine["status"] != "IDLE":
            raise err(ERR_MACHINE_UNAVAILABLE, "Machine is not IDLE")

        # DRYER requires dry_blocks >= 1 (priority 10).
        if machine["machine_type"] == "DRYER":
            if dry_blocks < 1:
                raise err(ERR_DRY_BLOCKS_REQUIRED, "DRYER vend requires dry_blocks >= 1")
        else:  # WASHER: dry_blocks ignored / forced 0
            dry_blocks = 0

        # ---- Quote (forward-looking) -------------------------------------
        hour = db.capture_clock.astimezone(timezone.utc).hour
        quoted, surge_applied = vend_quote_cents(plan, machine, dry_blocks, hour)

        # ---- Charged amount (chronological, pinned order) ----------------
        charged = quoted
        consume_free = False
        free_credit_requested = used_free_credit
        if used_free_credit:
            free_ok = (
                payment_method == "APP_WALLET"
                and machine["machine_type"] == "WASHER"
                and member is not None
                and member["free_wash_credits"] >= 1
            )
            if free_ok:
                charged = 0
                consume_free = True
            else:
                # used_free_credit set but conditions not met -> ERR_NO_FREE_CREDIT.
                raise err(ERR_NO_FREE_CREDIT, "Free credit conditions not met")

        # Loyalty accrual: APP_WALLET only, on net charged amount, floored.
        if payment_method == "APP_WALLET":
            loyalty_earned = floor_div(charged, plan["loyalty_cents_per_point"])
        else:
            loyalty_earned = 0

        # ---- Tender-specific settlement preconditions --------------------
        shift_id = None
        if payment_method == "APP_WALLET":
            # APP_WALLET requires a member (the acting member's wallet).
            if member is None:
                raise err(ERR_INVALID_REQUEST, "APP_WALLET vend requires a member_id")
            # Member must be ACTIVE (priority 11).
            if member["status"] != "ACTIVE":
                raise err(ERR_MEMBER_NOT_ACTIVE, "Member is not ACTIVE")
            # Sufficient wallet (priority 13).
            if member["wallet_cents"] < charged:
                raise err(ERR_INSUFFICIENT_WALLET, "Insufficient wallet balance")
        elif payment_method == "COIN":
            # COIN captured by an Attendant with an OPEN shift -> stamp shift.
            if role == "Attendant":
                shift = open_shift_for(user_id)
                if shift is not None:
                    shift_id = shift["id"]

        # ---- Purchased minutes & cycle_ends_at ---------------------------
        if machine["machine_type"] == "WASHER":
            purchased_minutes = machine["cycle_minutes"]
        else:
            purchased_minutes = dry_blocks * plan["dry_block_minutes"]
        cycle_ends_dt = db.capture_clock + timedelta(minutes=purchased_minutes)
        cycle_ends_at = format_iso(cycle_ends_dt)

        # ---- Create the vend ---------------------------------------------
        vend = {
            "machine_id": machine_id,
            "member_id": member_id,
            "shift_id": shift_id,
            "payment_method": payment_method,
            "dry_blocks": dry_blocks,
            "used_free_credit": free_credit_requested,
            "quoted_amount_cents": quoted,
            "charged_amount_cents": charged,
            "surge_applied": surge_applied,
            "loyalty_points_earned": loyalty_earned,
            "payment_status": "CAPTURED",
            "cycle_status": "RUNNING",
            "cycle_ends_at": cycle_ends_at,
        }
        stamp_create(vend)
        db.vends[vend["id"]] = vend

        # ---- Machine IDLE -> RUNNING (bumps version) ---------------------
        machine["status"] = "RUNNING"
        machine["current_vend_id"] = vend["id"]
        machine["cycle_ends_at"] = cycle_ends_at
        touch(machine)

        # ---- APP_WALLET settlement side effects --------------------------
        if payment_method == "APP_WALLET":
            if consume_free:
                member["free_wash_credits"] -= 1
            member["wallet_cents"] -= charged
            member["lifetime_spend_cents"] += charged
            if loyalty_earned > 0:
                member["loyalty_points"] += loyalty_earned
                touch(member)
                write_ledger(member, "ACCRUAL", loyalty_earned, vend["id"])
            else:
                touch(member)

        # ---- COIN shift recompute ----------------------------------------
        if shift_id is not None:
            recompute_and_touch(db.shifts[shift_id])

    return object_response(view(vend), status=201)


# ===== Machine cycle transitions ============================================
@bp.post("/machines/<machine_id>/complete-cycle")
def complete_cycle(machine_id):
    _, role = get_identity()
    require_roles(role, {"Attendant"})
    with db.lock:
        machine = get_or_404(db.machines, machine_id, "Machine")
        if machine["status"] != "RUNNING":
            raise err(ERR_INVALID_STATE, "Machine is not RUNNING")
        complete_machine_cycle(machine)
    return object_response(view(machine))


@bp.post("/machines/<machine_id>/clear")
def clear_machine(machine_id):
    _, role = get_identity()
    require_roles(role, {"Member", "Attendant"})
    with db.lock:
        machine = get_or_404(db.machines, machine_id, "Machine")
        status = machine["status"]
        if status == "DONE":
            pass  # Member or Attendant may clear DONE.
        elif status == "FAULT":
            # Only an Attendant may clear FAULT, and no SUBMITTED claim may
            # exist against the retained current_vend_id.
            if role != "Attendant":
                raise err(ERR_FORBIDDEN, "Only an Attendant may clear a FAULT machine")
            cvid = machine.get("current_vend_id")
            if cvid is not None:
                for c in db.refund_claims.values():
                    if c["vend_id"] == cvid and c["status"] == "SUBMITTED":
                        raise err(ERR_INVALID_STATE, "Open refund claim against current vend")
        else:
            raise err(ERR_INVALID_STATE, "Machine is not DONE or FAULT")
        machine["status"] = "IDLE"
        machine["current_vend_id"] = None
        machine["cycle_ends_at"] = None
        touch(machine)
    return object_response(view(machine))


@bp.post("/machines/<machine_id>/declare-fault")
def declare_fault(machine_id):
    _, role = get_identity()
    require_roles(role, {"Attendant"})
    with db.lock:
        machine = get_or_404(db.machines, machine_id, "Machine")
        if machine["status"] not in ("RUNNING", "DONE"):
            raise err(ERR_INVALID_STATE, "Machine is not RUNNING or DONE")
        machine["fault_count"] += 1
        vend = db.vends.get(machine.get("current_vend_id"))
        if vend is not None and vend["cycle_status"] == "RUNNING":
            vend["cycle_status"] = "ABORTED"
            touch(vend)
        machine["status"] = "FAULT"
        # current_vend_id retained for claim linkage.
        touch(machine)
    return object_response(view(machine))


@bp.post("/machines/<machine_id>/take-offline")
def take_offline(machine_id):
    _, role = get_identity()
    require_roles(role, {"Manager"})
    with db.lock:
        machine = get_or_404(db.machines, machine_id, "Machine")
        if machine["status"] != "IDLE":
            raise err(ERR_INVALID_STATE, "Machine is not IDLE")
        machine["status"] = "OUT_OF_SERVICE"
        touch(machine)
    return object_response(view(machine))


@bp.post("/machines/<machine_id>/return-to-service")
def return_to_service(machine_id):
    _, role = get_identity()
    require_roles(role, {"Manager"})
    with db.lock:
        machine = get_or_404(db.machines, machine_id, "Machine")
        if machine["status"] != "OUT_OF_SERVICE":
            raise err(ERR_INVALID_STATE, "Machine is not OUT_OF_SERVICE")
        machine["status"] = "IDLE"
        touch(machine)
    return object_response(view(machine))
