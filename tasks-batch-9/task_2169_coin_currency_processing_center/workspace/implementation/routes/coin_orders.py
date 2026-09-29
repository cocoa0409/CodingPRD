"""CoinOrder routes: placement, waterfall allocation, release and return."""

from decimal import Decimal

from flask import Blueprint

import calc
from core import (
    BOX_FACE_VALUE_CENTS,
    COIN_ORDER_STATUSES,
    COIN_VALUE_CENTS,
    DENOMINATIONS,
    ROLE_CUSTOMER,
    ROLE_VAULT_MANAGER,
    ROLE_VAULT_TELLER,
    authorize,
    body_json,
    check_ownership,
    db,
    fail,
    get_coin_order,
    get_customer,
    get_pagination,
    get_vault,
    inventory_row,
    lines_of_order,
    make_row,
    ordered,
    paginate,
    query_enum,
    query_str,
    req_bool,
    req_datetime,
    req_int,
    req_list,
    req_str,
    respond,
    touch,
)
from serializers import coin_line_out, coin_order_out

bp = Blueprint("coin_orders", __name__)


def _validate_lines(body):
    entries = req_list(body, "lines", allow_empty=False)
    parsed = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            fail("ERR_INVALID_REQUEST", "lines[%d] must be an object." % index)
        denomination = entry.get("denomination")
        if not isinstance(denomination, str) or denomination not in DENOMINATIONS:
            fail("ERR_INVALID_REQUEST", "lines[%d].denomination is invalid." % index)
        boxes = entry.get("boxes_requested")
        if isinstance(boxes, bool) or not isinstance(boxes, int):
            fail("ERR_INVALID_REQUEST", "lines[%d].boxes_requested must be an integer." % index)
        if boxes < 1:
            fail("ERR_INVALID_REQUEST", "lines[%d].boxes_requested must be at least 1." % index)
        parsed.append({"denomination": denomination, "boxes_requested": boxes})
    return parsed


@bp.post("/coin-orders")
def place_order():
    actor = authorize(ROLE_CUSTOMER)
    body = body_json()
    customer_account_id = req_str(body, "customer_account_id")
    vault_id = req_str(body, "vault_id")
    start_raw, start_dt = req_datetime(body, "pickup_window_start")
    end_raw, end_dt = req_datetime(body, "pickup_window_end")
    lines = _validate_lines(body)
    if end_dt <= start_dt:
        fail(
            "ERR_INVALID_REQUEST",
            "'pickup_window_end' must be strictly after 'pickup_window_start'.",
        )

    # ladder 6 - body references in declared field order
    get_customer(customer_account_id)
    vault = get_vault(vault_id)

    # ladder 7 - a customer may only order for their own account
    check_ownership(actor, customer_account_id)

    # ladder 25 - dock capacity over CLOSED pickup intervals
    live = [
        o for o in db.coin_orders.values()
        if o["vault_id"] == vault_id
        and o["status"] in ("REQUESTED", "APPROVED_FULL", "APPROVED_PARTIAL")
    ]
    candidates = [start_dt, end_dt]
    for other in live:
        for instant in (other["_pickup_start_dt"], other["_pickup_end_dt"]):
            if start_dt <= instant <= end_dt:
                candidates.append(instant)
    for instant in candidates:
        covering = sum(
            1 for o in live
            if o["_pickup_start_dt"] <= instant <= o["_pickup_end_dt"]
        )
        if covering >= vault["pickup_concurrency_limit"]:
            fail("ERR_PICKUP_CAPACITY_EXCEEDED", "The vault's pickup dock is at capacity.")

    # ladder 26 - at most one line per denomination
    seen = set()
    for line in lines:
        if line["denomination"] in seen:
            fail(
                "ERR_DUPLICATE_DENOMINATION",
                "Denomination %s appears more than once." % line["denomination"],
            )
        seen.add(line["denomination"])

    row = make_row()
    row.update({
        "customer_account_id": customer_account_id,
        "vault_id": vault_id,
        "pickup_window_start": start_raw,
        "pickup_window_end": end_raw,
        "_pickup_start_dt": start_dt,
        "_pickup_end_dt": end_dt,
        "status": "REQUESTED",
        "approved_by_user_id": None,
        "released_by_user_id": None,
        "total_boxes_requested": sum(l["boxes_requested"] for l in lines),
        "total_boxes_allocated": 0,
        "fill_ratio_pct": Decimal("0.00"),
        "charge_cents": 0,
        "return_reason": None,
    })
    db.coin_orders[row["id"]] = row

    for line in lines:
        line_row = make_row(common=False)
        line_row.update({
            "coin_order_id": row["id"],
            "denomination": line["denomination"],
            "boxes_requested": line["boxes_requested"],
            "boxes_allocated": 0,
            "boxes_returned": 0,
            "line_face_value_cents": 0,
        })
        db.coin_lines[line_row["id"]] = line_row

    return respond(coin_order_out(row), 201)


@bp.get("/coin-orders/<order_id>")
def read_order(order_id):
    actor = authorize(ROLE_VAULT_MANAGER, ROLE_VAULT_TELLER, ROLE_CUSTOMER)
    order = get_coin_order(order_id)
    check_ownership(actor, order["customer_account_id"])
    return respond(coin_order_out(order))


@bp.get("/coin-orders")
def list_orders():
    authorize(ROLE_VAULT_MANAGER, ROLE_VAULT_TELLER, ROLE_CUSTOMER)
    limit, offset = get_pagination()
    customer_account_id = query_str("customer_account_id")
    vault_id = query_str("vault_id")
    status = query_enum("status", COIN_ORDER_STATUSES)

    rows = ordered(db.coin_orders.values())
    if customer_account_id is not None:
        rows = [r for r in rows if r["customer_account_id"] == customer_account_id]
    if vault_id is not None:
        rows = [r for r in rows if r["vault_id"] == vault_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return paginate(rows, limit, offset, coin_order_out)


@bp.get("/coin-orders/<order_id>/lines")
def list_order_lines(order_id):
    actor = authorize(ROLE_VAULT_MANAGER, ROLE_VAULT_TELLER, ROLE_CUSTOMER)
    limit, offset = get_pagination()
    order = get_coin_order(order_id)
    check_ownership(actor, order["customer_account_id"])
    return paginate(lines_of_order(order_id), limit, offset, coin_line_out)


@bp.post("/coin-orders/<order_id>/approve")
def approve_order(order_id):
    actor = authorize(ROLE_VAULT_MANAGER)
    body = body_json()
    allow_partial = req_bool(body, "allow_partial")
    order = get_coin_order(order_id)

    if order["status"] != "REQUESTED":
        fail("ERR_INVALID_STATE", "Coin order is not in REQUESTED.")

    # ladder 35 - the depositor account must be ACTIVE
    account = db.customers.get(order["customer_account_id"])
    if account is None or account["status"] != "ACTIVE":
        fail("ERR_ACCOUNT_SUSPENDED", "The depositor account is not ACTIVE.")

    lines = sorted(
        lines_of_order(order_id), key=lambda l: COIN_VALUE_CENTS[l["denomination"]]
    )

    # Dry run: allocation is sequential, each line's reservation visible to the next.
    pending_reserved = {}
    plan = []
    for line in lines:
        inv = inventory_row(order["vault_id"], line["denomination"])
        if inv is None:
            available = 0
        else:
            extra = pending_reserved.get(inv["id"], 0)
            available = max(inv["on_hand_boxes"] - (inv["reserved_boxes"] + extra), 0)
        allocated = min(line["boxes_requested"], available)
        if inv is not None:
            pending_reserved[inv["id"]] = pending_reserved.get(inv["id"], 0) + allocated
        plan.append((line, inv, allocated))

    total_allocated = sum(p[2] for p in plan)
    total_requested = order["total_boxes_requested"]
    ratio = calc.fill_ratio(total_allocated, total_requested)

    if total_allocated == 0:
        new_status = "REJECTED"
    elif ratio == Decimal("100.00"):
        new_status = "APPROVED_FULL"
    elif allow_partial:
        new_status = "APPROVED_PARTIAL"
    else:
        # ladder 36 - nothing is reserved when a partial fill is refused
        fail(
            "ERR_INSUFFICIENT_COIN_INVENTORY",
            "Coin inventory cannot fill the order and allow_partial is false.",
        )

    if new_status == "REJECTED":
        order["total_boxes_allocated"] = 0
        order["fill_ratio_pct"] = Decimal("0.00")
        order["charge_cents"] = 0
    else:
        charge = 0
        for line, inv, allocated in plan:
            line["boxes_allocated"] = allocated
            line["line_face_value_cents"] = allocated * BOX_FACE_VALUE_CENTS[line["denomination"]]
            charge += line["line_face_value_cents"]
            if inv is not None and allocated:
                inv["reserved_boxes"] += allocated
                calc.recompute_available_boxes(inv)
                touch(inv)
        order["total_boxes_allocated"] = total_allocated
        order["fill_ratio_pct"] = ratio
        order["charge_cents"] = charge

    order["approved_by_user_id"] = actor.user_id
    order["status"] = new_status
    touch(order)

    vault = db.vaults.get(order["vault_id"])
    if vault is not None:
        touch(vault)
    return respond(coin_order_out(order))


@bp.post("/coin-orders/<order_id>/release")
def release_order(order_id):
    actor = authorize(ROLE_VAULT_TELLER)
    body = body_json()
    expected_vault_version = req_int(body, "expected_vault_version")
    order = get_coin_order(order_id)

    vault = db.vaults.get(order["vault_id"])

    # ladder 8 - optimistic concurrency against the fulfilling vault
    if vault is None or expected_vault_version != vault["version"]:
        fail("ERR_STALE_VERSION", "expected_vault_version does not match the vault version.")

    # ladder 9 - release is legal from either approved state
    if order["status"] not in ("APPROVED_FULL", "APPROVED_PARTIAL"):
        fail("ERR_INVALID_STATE", "Coin order is not in an approved state.")

    # ladder 13 / 14 - posture gates the physical release
    if vault["posture"] == "FROZEN":
        fail("ERR_VAULT_FROZEN", "The vault is FROZEN.")
    if vault["posture"] == "RESTRICTED":
        fail("ERR_VAULT_RESTRICTED", "The vault is RESTRICTED.")

    # ladder 16 - dual control
    if actor.user_id == order["approved_by_user_id"]:
        fail("ERR_DUAL_CONTROL_VIOLATION", "The approver may not also release the order.")

    lines = lines_of_order(order_id)

    # ladder 36 - the physical position must still cover every allocation
    for line in lines:
        if line["boxes_allocated"] <= 0:
            continue
        inv = inventory_row(order["vault_id"], line["denomination"])
        if inv is None or inv["on_hand_boxes"] < line["boxes_allocated"]:
            fail(
                "ERR_INSUFFICIENT_COIN_INVENTORY",
                "On-hand boxes no longer cover the allocation for %s." % line["denomination"],
            )

    for line in lines:
        if line["boxes_allocated"] <= 0:
            continue
        inv = inventory_row(order["vault_id"], line["denomination"])
        inv["on_hand_boxes"] -= line["boxes_allocated"]
        inv["reserved_boxes"] -= line["boxes_allocated"]
        calc.recompute_available_boxes(inv)
        touch(inv)

    calc.recompute_vault_coin_face_value(vault)

    account = db.customers.get(order["customer_account_id"])
    if account is not None:
        account["ledger_balance_cents"] -= order["charge_cents"]
        calc.recompute_account_available(account)
        touch(account)

    order["released_by_user_id"] = actor.user_id
    order["status"] = "RELEASED"
    touch(order)
    touch(vault)
    return respond(coin_order_out(order))


@bp.post("/coin-orders/<order_id>/return")
def return_order(order_id):
    authorize(ROLE_VAULT_TELLER)
    body = body_json()
    return_reason = req_str(body, "return_reason")
    order = get_coin_order(order_id)

    if order["status"] != "RELEASED":
        fail("ERR_INVALID_STATE", "Coin order is not in RELEASED.")

    vault = db.vaults.get(order["vault_id"])
    for line in lines_of_order(order_id):
        line["boxes_returned"] = line["boxes_allocated"]
        if line["boxes_allocated"] <= 0:
            continue
        inv = inventory_row(order["vault_id"], line["denomination"])
        if inv is None:
            inv = make_row()
            inv.update({
                "vault_id": order["vault_id"],
                "denomination": line["denomination"],
                "on_hand_boxes": 0,
                "reserved_boxes": 0,
                "available_boxes": 0,
            })
            db.inventory[inv["id"]] = inv
        inv["on_hand_boxes"] += line["boxes_allocated"]
        calc.recompute_available_boxes(inv)
        touch(inv)

    if vault is not None:
        calc.recompute_vault_coin_face_value(vault)
        touch(vault)

    account = db.customers.get(order["customer_account_id"])
    if account is not None:
        account["ledger_balance_cents"] += order["charge_cents"]
        calc.recompute_account_available(account)
        touch(account)

    order["return_reason"] = return_reason
    order["status"] = "RETURNED"
    touch(order)
    return respond(coin_order_out(order))
