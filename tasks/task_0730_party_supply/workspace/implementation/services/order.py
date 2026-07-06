"""Order-level services: totals, reserve cascade, transitions."""
from __future__ import annotations
from datetime import timedelta
from decimal import Decimal

from db import db, bump, parse_iso, now_iso
from errors import (
    raise_error,
    ERR_INVALID_STATE,
    ERR_STALE_ORDER_VERSION,
    ERR_INSUFFICIENT_STOCK,
    ERR_HELIUM_INSUFFICIENT,
    ERR_SEASONAL_WINDOW_CLOSED,
    ERR_INVALID_REQUEST,
)
from services import calc


# ----------------------------------------------------------------------
# Reverse lookups
# ----------------------------------------------------------------------

def order_lines_for(order_id: str) -> list[dict]:
    return [ln for ln in db.order_lines.values() if ln["order_id"] == order_id]


def helium_order_for(order_id: str) -> dict | None:
    for h in db.helium_orders.values():
        if h["order_id"] == order_id:
            return h
    return None


def rental_contracts_for(order_id: str) -> list[dict]:
    return [r for r in db.rental_contracts.values() if r["order_id"] == order_id]


def custom_print_for(order_id: str) -> dict | None:
    for c in db.custom_print_orders.values():
        if c["order_id"] == order_id:
            return c
    return None


def event_booking_for(order_id: str) -> dict | None:
    for b in db.event_bookings.values():
        if b["order_id"] == order_id:
            return b
    return None


def delivery_slot_for(order_id: str) -> dict | None:
    for s in db.delivery_slots.values():
        if s.get("order_id") == order_id:
            return s
    return None


# ----------------------------------------------------------------------
# reserved_qty reconciliation (PRD §2.8)
# ----------------------------------------------------------------------

NON_TERMINAL_FULFILL = {"RESERVED", "PICKING", "READY_FOR_PICKUP"}


def recompute_reserved_qty() -> None:
    totals: dict[str, int] = {sku_id: 0 for sku_id in db.skus}
    for ln in db.order_lines.values():
        order = db.orders.get(ln["order_id"])
        if not order or order["fulfillment_status"] not in NON_TERMINAL_FULFILL:
            continue
        qty = int(ln["qty"])
        if ln.get("sku_id"):
            if ln["sku_id"] in totals:
                totals[ln["sku_id"]] += qty
        elif ln.get("bundle_id"):
            for bl in db.bundle_lines.values():
                if bl["bundle_id"] == ln["bundle_id"] and bl["sku_id"] in totals:
                    totals[bl["sku_id"]] += int(bl["qty"]) * qty
    for rc in db.rental_contracts.values():
        if rc["status"] == "RESERVED" and rc["sku_id"] in totals:
            totals[rc["sku_id"]] += int(rc["qty"])
    for sku_id, val in totals.items():
        db.skus[sku_id]["reserved_qty"] = val


# ----------------------------------------------------------------------
# Grand-total recompute (finalized variant)
# ----------------------------------------------------------------------

def recompute_order_totals(order: dict) -> None:
    """Finalised variant per PRD §3.4 — used at and after reserve.

    While the order is DRAFT (before reserve), the provisional variant runs
    instead — see recompute_provisional_totals.
    """
    if order["fulfillment_status"] == "DRAFT":
        recompute_provisional_totals(order)
        return

    order_id = order["id"]
    lines = order_lines_for(order_id)
    subtotal = 0
    for ln in lines:
        subtotal += int(ln.get("unit_price_cents_at_capture", 0)) * int(ln["qty"])

    cp = custom_print_for(order_id)
    if cp and cp["status"] != "CANCELLED" and cp.get("print_fee_cents"):
        subtotal += int(cp["print_fee_cents"])

    helium = helium_order_for(order_id)
    helium_fee = int(helium.get("fill_fee_cents", 0)) if helium else 0

    delivery_fee_val = 0
    if order["channel"] == "DELIVERY":
        slot = delivery_slot_for(order_id)
        if slot:
            ds_start = parse_iso(slot["window_start"])
            delivery_fee_val = calc.delivery_fee(
                ds_start, bool(slot.get("setup_included", False))
            )

    deposit = 0
    for rc in rental_contracts_for(order_id):
        if rc["status"] in {"RESERVED", "PICKED_UP"}:
            deposit += int(rc.get("deposit_cents", 0))
    eb = event_booking_for(order_id)
    if eb and eb["status"] in {"HELD", "CONFIRMED"}:
        deposit += int(eb.get("deposit_cents", 0))

    order["subtotal_cents"] = subtotal
    order["helium_fee_cents"] = helium_fee
    order["delivery_fee_cents"] = delivery_fee_val
    order["deposit_cents"] = deposit
    order["grand_total_cents"] = subtotal + helium_fee + delivery_fee_val + deposit


def recompute_provisional_totals(order: dict) -> None:
    """Provisional variant of the order totals, valid while DRAFT (PRD §3.4).

    "Before reserve, while the order is still in DRAFT, the system exposes a
    provisional variant of the same total that reads the live
    Sku.unit_price_cents without any clearance snapshot lock, and that
    excludes HeliumOrder, DeliverySlot, and RentalContract deposits — this
    provisional total is intended for quoting only".

    Included: SKU/bundle line totals at live unit_price_cents (no clearance),
    the attached non-cancelled CustomPrintOrder's print_fee_cents if pinned,
    and the attached EventBooking deposit (HELD/CONFIRMED).
    Excluded: HeliumOrder fill fee, DeliverySlot delivery fee, RentalContract
    deposits.
    """
    order_id = order["id"]
    lines = order_lines_for(order_id)
    subtotal = 0
    for ln in lines:
        qty = int(ln["qty"])
        if ln.get("sku_id"):
            sku = db.skus.get(ln["sku_id"])
            unit_price = int(sku["unit_price_cents"]) if sku else 0
            subtotal += unit_price * qty
        elif ln.get("bundle_id"):
            bundle = db.bundles.get(ln["bundle_id"])
            bundle_price = int(bundle["bundle_price_cents"]) if bundle else 0
            subtotal += bundle_price * qty

    cp = custom_print_for(order_id)
    if cp and cp["status"] != "CANCELLED" and cp.get("print_fee_cents"):
        subtotal += int(cp["print_fee_cents"])

    deposit = 0
    eb = event_booking_for(order_id)
    if eb and eb["status"] in {"HELD", "CONFIRMED"}:
        deposit += int(eb.get("deposit_cents", 0))

    order["subtotal_cents"] = subtotal
    order["helium_fee_cents"] = 0
    order["delivery_fee_cents"] = 0
    order["deposit_cents"] = deposit
    order["grand_total_cents"] = subtotal + deposit


# ----------------------------------------------------------------------
# OCC
# ----------------------------------------------------------------------

def check_order_occ(order: dict, expected_version) -> None:
    if expected_version is None:
        raise_error(ERR_INVALID_REQUEST, "expected_order_version is required")
    if not isinstance(expected_version, int) or isinstance(expected_version, bool):
        raise_error(ERR_INVALID_REQUEST, "expected_order_version must be integer")
    if order["version"] != expected_version:
        raise_error(ERR_STALE_ORDER_VERSION, "Order version has advanced")


# ----------------------------------------------------------------------
# Helium allocation / restore
# ----------------------------------------------------------------------

def _fmt_num(dec: Decimal):
    """Store as int when whole, else float, so JSON serializes nicely."""
    return int(dec) if dec == int(dec) else float(dec)


def allocate_helium(helium: dict) -> None:
    """Draw helium from ACTIVE tanks in (created_at, tank_code) order.
    Records the exact per-tank amount in helium['_allocations'] for later reversal."""
    required = calc.helium_required_cubic_ft(
        int(helium["latex_count"]), int(helium["foil_count"])
    )
    active = [t for t in db.helium_tanks.values() if t["status"] == "ACTIVE"]
    active.sort(key=lambda t: (t["created_at"], t["tank_code"]))

    remaining_need = required
    used_tank_ids: list[str] = []
    allocations: list[list] = []  # [tank_id, decimal-string amount]

    for tank in active:
        if remaining_need <= 0:
            break
        avail = Decimal(str(tank["remaining_cubic_ft"]))
        if avail <= 0:
            continue
        take = avail if avail <= remaining_need else remaining_need
        new_val = avail - take
        tank["remaining_cubic_ft"] = _fmt_num(new_val)
        if new_val <= 0:
            tank["status"] = "EMPTY"
            tank["remaining_cubic_ft"] = 0
        bump(tank)
        used_tank_ids.append(tank["id"])
        allocations.append([tank["id"], str(take)])
        remaining_need -= take

    helium["helium_tank_ids"] = used_tank_ids
    helium["fill_fee_cents"] = calc.helium_fill_fee(
        int(helium["latex_count"]), int(helium["foil_count"])
    )
    helium["_allocations"] = allocations
    bump(helium)


def restore_helium(helium: dict | None) -> None:
    if not helium:
        return
    allocations = helium.get("_allocations") or []
    for tank_id, amount_str in allocations:
        tank = db.helium_tanks.get(tank_id)
        if not tank:
            continue
        new_val = Decimal(str(tank["remaining_cubic_ft"])) + Decimal(amount_str)
        tank["remaining_cubic_ft"] = _fmt_num(new_val)
        if tank["status"] == "EMPTY" and new_val > 0:
            tank["status"] = "ACTIVE"
        bump(tank)
    helium["helium_tank_ids"] = []
    helium["_allocations"] = []
    bump(helium)


# ----------------------------------------------------------------------
# Reserve cascade
# ----------------------------------------------------------------------

def _compute_line_capture_price(ln: dict) -> int:
    if ln.get("sku_id"):
        sku = db.skus[ln["sku_id"]]
        base = int(sku["unit_price_cents"])
        if sku.get("is_clearance"):
            pct = Decimal(str(sku.get("clearance_pct", 0)))
            return calc.round_half_up(Decimal(base) * (Decimal("1") - pct))
        return base
    if ln.get("bundle_id"):
        return int(db.bundles[ln["bundle_id"]]["bundle_price_cents"])
    return 0


def _bundle_sku_totals(bundle_id: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for bl in db.bundle_lines.values():
        if bl["bundle_id"] == bundle_id:
            out[bl["sku_id"]] = out.get(bl["sku_id"], 0) + int(bl["qty"])
    return out


def do_reserve(order: dict) -> None:
    """DRAFT -> RESERVED cascade. Preconditions gate all mutation."""
    order_id = order["id"]
    lines = order_lines_for(order_id)

    if not lines:
        raise_error(ERR_INVALID_STATE, "Order has no lines")

    # Seasonal window (priority 10)
    clock = db.clock
    for ln in lines:
        if ln.get("sku_id"):
            sku = db.skus[ln["sku_id"]]
            ws = sku.get("seasonal_window_start")
            we = sku.get("seasonal_window_end")
            if ws and we:
                start_dt = parse_iso(ws)
                end_dt = parse_iso(we)
                if not (start_dt <= clock <= end_dt):
                    raise_error(
                        ERR_SEASONAL_WINDOW_CLOSED,
                        f"SKU {sku['sku_code']} outside seasonal window",
                    )

    # Aggregate demand (priority 14) — bundles fanned out
    demand_by_sku: dict[str, int] = {}
    for ln in lines:
        qty = int(ln["qty"])
        if ln.get("sku_id"):
            demand_by_sku[ln["sku_id"]] = demand_by_sku.get(ln["sku_id"], 0) + qty
        elif ln.get("bundle_id"):
            for sku_id, bl_qty in _bundle_sku_totals(ln["bundle_id"]).items():
                demand_by_sku[sku_id] = demand_by_sku.get(sku_id, 0) + bl_qty * qty

    for sku_id, demand in demand_by_sku.items():
        sku = db.skus[sku_id]
        available = int(sku["on_hand_qty"]) - int(sku["reserved_qty"])
        if available < demand:
            raise_error(
                ERR_INSUFFICIENT_STOCK,
                f"SKU {sku['sku_code']} short {demand} (avail {available})",
            )

    # Helium sufficiency (priority 15)
    helium = helium_order_for(order_id)
    if helium:
        required = calc.helium_required_cubic_ft(
            int(helium["latex_count"]), int(helium["foil_count"])
        )
        total_avail = sum(
            Decimal(str(t["remaining_cubic_ft"]))
            for t in db.helium_tanks.values()
            if t["status"] == "ACTIVE"
        )
        if total_avail < required:
            raise_error(
                ERR_HELIUM_INSUFFICIENT,
                f"Insufficient helium: need {required}, have {total_avail}",
            )

    # DELIVERY channel must reference exactly one AVAILABLE slot
    slot = None
    if order["channel"] == "DELIVERY":
        slot = delivery_slot_for(order_id)
        if slot is None or slot["status"] != "AVAILABLE":
            raise_error(ERR_INVALID_STATE, "DELIVERY order requires AVAILABLE DeliverySlot")

    # ---- Mutate ----

    for sku_id, demand in demand_by_sku.items():
        sku = db.skus[sku_id]
        sku["reserved_qty"] = int(sku["reserved_qty"]) + demand
        bump(sku)

    if helium:
        allocate_helium(helium)

    if slot is not None:
        slot["status"] = "RESERVED"
        slot["order_id"] = order_id
        bump(slot)

    for ln in lines:
        ln["unit_price_cents_at_capture"] = _compute_line_capture_price(ln)
        ln["line_total_cents"] = ln["unit_price_cents_at_capture"] * int(ln["qty"])

    order["fulfillment_status"] = "RESERVED"

    if order["channel"] == "BOPIS" and order.get("pickup_window_end"):
        end = parse_iso(order["pickup_window_end"])
        order["pickup_deadline"] = now_iso(end + timedelta(hours=48))

    recompute_order_totals(order)
    bump(order)


# ----------------------------------------------------------------------
# Reservation release (used by cancel + no-show sweep)
# ----------------------------------------------------------------------

def release_reservation(order: dict) -> None:
    """Reverse the RESERVED cascade: release SKU reservations, refund helium,
    cancel delivery slot. Does not change order.fulfillment_status."""
    order_id = order["id"]
    lines = order_lines_for(order_id)

    demand_by_sku: dict[str, int] = {}
    for ln in lines:
        qty = int(ln["qty"])
        if ln.get("sku_id"):
            demand_by_sku[ln["sku_id"]] = demand_by_sku.get(ln["sku_id"], 0) + qty
        elif ln.get("bundle_id"):
            for sku_id, bl_qty in _bundle_sku_totals(ln["bundle_id"]).items():
                demand_by_sku[sku_id] = demand_by_sku.get(sku_id, 0) + bl_qty * qty

    for sku_id, demand in demand_by_sku.items():
        sku = db.skus.get(sku_id)
        if sku is None:
            continue
        sku["reserved_qty"] = max(0, int(sku["reserved_qty"]) - demand)
        bump(sku)

    helium = helium_order_for(order_id)
    if helium:
        restore_helium(helium)

    slot = delivery_slot_for(order_id)
    if slot is not None and slot["status"] == "RESERVED":
        slot["status"] = "CANCELLED"
        bump(slot)
