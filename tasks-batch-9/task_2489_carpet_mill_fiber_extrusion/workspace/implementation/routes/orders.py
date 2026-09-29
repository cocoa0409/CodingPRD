"""Cut orders: submission, allocation, cutting, shipping and cancellation (PRD 3.9)."""

from decimal import Decimal

from flask import Blueprint

import calc
from calc import dec, rhu
from db import store, touch
from errors import ApiError
from routes.common import authenticate, created, fetch, listing, ok, unique
from services import allocation, cascades, compliance, ledgers
from validators import json_body, opt_str, req_enum, req_int, req_num, req_str

bp = Blueprint("orders", __name__)

ORDER_TYPES = ("RUNNING_LINE", "CUSTOM")
SHADE_TOLERANCES = ("SINGLE_LOT", "BAND_MATCH", "ANY")
ORDER_STATUSES = (
    "SUBMITTED",
    "ALLOCATED",
    "BACKORDERED",
    "CUT",
    "SHIPPED",
    "CANCELLED",
)
LINE_STATUSES = ("RESERVED", "CUT", "SHIPPED", "RELEASED", "VOIDED")

CREATE_ROLES = ("DealerBuyer", "MillPlanner", "PlantAdmin")
PLANNER_ROLES = ("MillPlanner", "PlantAdmin")
ORDER_READ_ROLES = ("MillPlanner", "DealerBuyer", "PlantAdmin")
LINE_READ_ROLES = ("MillPlanner", "DealerBuyer", "QALabTechnician", "PlantAdmin")


def _scope(actor, account_id):
    """Rung 3 — a DealerBuyer may only act on its own account."""
    if actor.role != "DealerBuyer":
        return
    if actor.user_id != account_id:
        raise ApiError(
            "ERR_ACCOUNT_SCOPE_VIOLATION",
            "A DealerBuyer may only act on its own account",
        )


def _require_flammability(style):
    """Rung 11 — carpet may not be committed without effective cover."""
    if not compliance.has_effective_flammability_cert(style["id"]):
        raise ApiError(
            "ERR_FLAMMABILITY_CERT_REQUIRED",
            "The style holds no effective DOC_FF_1_70 certificate",
        )


@bp.post("/mill/cut-orders")
def submit_order():
    actor = authenticate(CREATE_ROLES)
    body = json_body()

    # Rung 3 — account scope, evaluated on the raw body value.
    raw_account = body.get("account_id")
    if isinstance(raw_account, str):
        _scope(actor, raw_account)

    order_code = req_str(body, "order_code")
    account_id = req_str(body, "account_id")
    style_id = req_str(body, "style_id")
    order_type = req_enum(body, "order_type", ORDER_TYPES)
    requested_yards = req_num(body, "requested_yards", 1, gt=0)
    shade_tolerance = req_enum(body, "shade_tolerance", SHADE_TOLERANCES)

    # Rung 6 — body reference existence.
    account = fetch("accounts", account_id)
    style = fetch("styles", style_id)

    # Rung 7 — natural-key uniqueness.
    unique("cut_orders", "order_code", order_code)

    # Rung 9 — the buying account must be ACTIVE.
    if account["status"] == "CREDIT_HOLD":
        raise ApiError("ERR_ACCOUNT_CREDIT_HOLD", "The account is on credit hold")
    if account["status"] == "CLOSED":
        raise ApiError("ERR_ACCOUNT_CLOSED", "The account is closed")

    # Rung 25 — the style must accept the order.
    if style["status"] not in ("ACTIVE", "RUNOUT"):
        raise ApiError("ERR_STYLE_NOT_ORDERABLE", "The style is not orderable")
    if style["status"] == "RUNOUT" and order_type == "CUSTOM":
        raise ApiError(
            "ERR_STYLE_RUNOUT_NO_CUSTOM",
            "A RUNOUT style refuses a CUSTOM order",
        )

    # Rung 30 — the credit admission gate, evaluated before anything is written.
    reserved = calc.cents(
        dec(requested_yards) * Decimal(int(style["list_price_cents_per_yard"]))
    )
    if int(account["credit_used_cents"]) + reserved > int(account["credit_limit_cents"]):
        raise ApiError(
            "ERR_CREDIT_LIMIT_EXCEEDED",
            "The reservation of %d cents would exceed the account's credit limit"
            % reserved,
        )

    from db import insert

    order = insert(
        store.cut_orders,
        {
            "order_code": order_code,
            "account_id": account_id,
            "style_id": style_id,
            "order_type": order_type,
            "requested_yards": requested_yards,
            "shade_tolerance": shade_tolerance,
            "allocated_yards": 0.0,
            "reserved_credit_cents": reserved,
            "gross_cents": 0,
            "freight_cents": 0,
            "remnant_credit_cents": 0,
            "net_invoice_cents": 0,
            "status": "SUBMITTED",
        },
    )

    ledgers.recompute_account(account)
    ledgers.recompute_style_posture(style)
    return created("cut_order", order)


@bp.post("/mill/cut-orders/<cut_order_id>/allocate")
def allocate(cut_order_id):
    authenticate(PLANNER_ROLES)
    order = fetch("cut_orders", cut_order_id)

    # Rung 8 — state legality.
    if order["status"] not in ("SUBMITTED", "BACKORDERED"):
        raise ApiError(
            "ERR_INVALID_STATE",
            "Only a SUBMITTED or BACKORDERED order may be allocated",
        )

    style = store.styles.get(order["style_id"])

    # Rung 11 — the flammability gate.
    _require_flammability(style)

    # Rung 25 — the style must still accept the order.
    if style["status"] not in ("ACTIVE", "RUNOUT"):
        raise ApiError("ERR_STYLE_NOT_ORDERABLE", "The style is not orderable")

    allocation.auto_allocate(order)
    return ok("cut_order", order)


@bp.post("/mill/cut-orders/<cut_order_id>/allocations")
def create_allocation(cut_order_id):
    authenticate(PLANNER_ROLES)
    body = json_body()
    roll_good_id = req_str(body, "roll_good_id")
    yards = req_num(body, "yards", 1, gt=0)
    expected_version = req_int(body, "expected_roll_good_version", ge=1)

    order = fetch("cut_orders", cut_order_id)
    roll = fetch("roll_goods", roll_good_id)

    # Rung 8 — state legality of the order and of the roll's dye lot.
    if order["status"] not in ("SUBMITTED", "BACKORDERED"):
        raise ApiError(
            "ERR_INVALID_STATE",
            "Only a SUBMITTED or BACKORDERED order may take an allocation line",
        )
    lot = store.dye_lots.get(roll["dye_lot_id"]) if roll.get("dye_lot_id") else None
    if lot is not None and lot["status"] not in ("APPROVED", "EXHAUSTED", "REJECTED"):
        raise ApiError("ERR_DYE_LOT_NOT_APPROVED", "The roll's dye lot is not APPROVED")

    # Rung 10 — optimistic concurrency on the roll.
    if expected_version != roll["version"]:
        raise ApiError(
            "ERR_STALE_ROLL_GOOD_VERSION",
            "expected_roll_good_version %d does not match the roll's version %d"
            % (expected_version, roll["version"]),
        )

    style = store.styles.get(order["style_id"])

    # Rung 11 — the flammability gate.
    _require_flammability(style)

    # Rung 20 — shade continuity against the order's earliest live line.
    earliest = None
    for line in ledgers.lines_of_order(order["id"]):
        if line["status"] in ledgers.LIVE_LINE_STATUSES:
            earliest = line
            break
    if earliest is not None:
        anchor = store.roll_goods.get(earliest["roll_good_id"])
        if order["shade_tolerance"] == "SINGLE_LOT":
            anchor_lot = anchor.get("dye_lot_id") if anchor else None
            if roll.get("dye_lot_id") != anchor_lot:
                raise ApiError(
                    "ERR_SHADE_BAND_MISMATCH",
                    "A SINGLE_LOT order requires every line to draw from one dye lot",
                )
        elif order["shade_tolerance"] == "BAND_MATCH":
            if roll["shade_band"] != earliest["shade_band"]:
                raise ApiError(
                    "ERR_SHADE_BAND_MISMATCH",
                    "A BAND_MATCH order requires every line to share one shade band",
                )

    # Rung 26 — dye-lot availability for allocation.
    if lot is not None:
        if lot["status"] == "REJECTED":
            raise ApiError(
                "ERR_DYE_LOT_EXHAUSTED", "The roll's dye lot has been rejected"
            )
        if order["shade_tolerance"] == "SINGLE_LOT" and lot["status"] == "EXHAUSTED":
            raise ApiError(
                "ERR_DYE_LOT_EXHAUSTED",
                "A SINGLE_LOT order may not be closed out of an exhausted lot",
            )

    # Rung 27 — yardage first, then allocatability.
    if dec(yards) > dec(roll["available_yards"]):
        raise ApiError(
            "ERR_ROLL_YARDAGE_INSUFFICIENT",
            "The roll holds only %s available yards" % roll["available_yards"],
        )
    if roll["qa_status"] != "PASSED" or roll["inventory_status"] != "AVAILABLE":
        raise ApiError(
            "ERR_ROLL_NOT_ALLOCATABLE",
            "The roll is not PASSED on quality and AVAILABLE on inventory",
        )

    line = allocation.create_line(order, roll, dec(yards))
    touch(roll)
    allocation.settle(order, [line])

    if dec(order["allocated_yards"]) >= dec(order["requested_yards"]):
        order["status"] = "ALLOCATED"
        touch(order)

    if style is not None:
        ledgers.recompute_style_posture(style)
    return created("cut_allocation", line)


@bp.post("/mill/cut-orders/<cut_order_id>/cut")
def cut_order(cut_order_id):
    authenticate(PLANNER_ROLES)
    order = fetch("cut_orders", cut_order_id)

    # Rung 8 — state legality.
    if order["status"] != "ALLOCATED":
        raise ApiError("ERR_INVALID_STATE", "Only an ALLOCATED order may be cut")

    lines = ledgers.lines_of_order(order["id"])
    live = [l for l in lines if l["status"] in ledgers.LIVE_LINE_STATUSES]
    for line in live:
        if line["status"] != "RESERVED":
            raise ApiError(
                "ERR_INVALID_STATE", "Every live line of the order must be RESERVED"
            )

    roll_ids = []
    for line in live:
        line["status"] = "CUT"
        touch(line)
        if line["roll_good_id"] not in roll_ids:
            roll_ids.append(line["roll_good_id"])

    for roll_id in roll_ids:
        roll = store.roll_goods.get(roll_id)
        if roll is None:
            continue
        ledgers.recompute_roll(roll)
        cascades.resolve_roll_after_cut(roll)

    ledgers.recompute_order_financials(order)
    ledgers.recompute_dye_lots_for_lines(live)

    order["status"] = "CUT"
    touch(order)
    return ok("cut_order", order)


@bp.post("/mill/cut-orders/<cut_order_id>/ship")
def ship_order(cut_order_id):
    authenticate(PLANNER_ROLES)
    order = fetch("cut_orders", cut_order_id)

    # Rung 8 — state legality.
    if order["status"] != "CUT":
        raise ApiError("ERR_INVALID_STATE", "Only a CUT order may be shipped")

    shipped = []
    for line in ledgers.lines_of_order(order["id"]):
        if line["status"] == "CUT":
            line["status"] = "SHIPPED"
            touch(line)
            shipped.append(line)

    ledgers.recompute_order_financials(order)
    order["status"] = "SHIPPED"
    touch(order)

    # The credit hold becomes an invoice on the account ledger.
    account = store.accounts.get(order["account_id"])
    if account is not None:
        ledgers.recompute_account(account)

    ledgers.recompute_dye_lots_for_lines(shipped)

    style = store.styles.get(order["style_id"])
    if style is not None:
        ledgers.recompute_style_posture(style)
    compliance.evaluate_runout_discontinuation()
    return ok("cut_order", order)


@bp.post("/mill/cut-orders/<cut_order_id>/cancel")
def cancel_order(cut_order_id):
    actor = authenticate(CREATE_ROLES)
    body = json_body()
    opt_str(body, "reason")

    order = fetch("cut_orders", cut_order_id)
    _scope(actor, order["account_id"])

    # Rung 8 — state legality.
    if order["status"] not in ("SUBMITTED", "ALLOCATED", "BACKORDERED"):
        raise ApiError(
            "ERR_INVALID_STATE",
            "Only a SUBMITTED, ALLOCATED or BACKORDERED order may be cancelled",
        )

    cascades.release_order_lines(order)

    order["status"] = "CANCELLED"
    order["reserved_credit_cents"] = 0
    touch(order)
    ledgers.recompute_order_financials(order)

    account = store.accounts.get(order["account_id"])
    if account is not None:
        ledgers.recompute_account(account)

    style = store.styles.get(order["style_id"])
    if style is not None:
        ledgers.recompute_style_posture(style)
    compliance.evaluate_runout_discontinuation()
    return ok("cut_order", order)


@bp.get("/mill/cut-orders/<cut_order_id>")
def read_order(cut_order_id):
    actor = authenticate(ORDER_READ_ROLES)
    order = fetch("cut_orders", cut_order_id)
    _scope(actor, order["account_id"])
    return ok("cut_order", order)


@bp.get("/mill/cut-orders")
def list_orders():
    authenticate(ORDER_READ_ROLES)
    return listing(
        "cut_order",
        "cut_orders",
        enum_filters={"status": ORDER_STATUSES, "order_type": ORDER_TYPES},
        value_filters=("account_id", "style_id"),
    )


@bp.get("/mill/cut-allocations/<cut_allocation_id>")
def read_allocation(cut_allocation_id):
    authenticate(ORDER_READ_ROLES)
    return ok("cut_allocation", fetch("cut_allocations", cut_allocation_id))


@bp.get("/mill/cut-allocations")
def list_allocations():
    authenticate(LINE_READ_ROLES)
    return listing(
        "cut_allocation",
        "cut_allocations",
        enum_filters={"status": LINE_STATUSES},
        value_filters=("cut_order_id", "roll_good_id"),
    )
