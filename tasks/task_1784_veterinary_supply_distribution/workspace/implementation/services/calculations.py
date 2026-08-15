"""Calculation services: order totals, credit exposure, FEFO allocation,
backorder waterfall, rebate accrual, short-date credit tiers, quarterly caps.

All monetary math is exact integer cents with pinned round-half-up points
(PRD 2.6). No floats anywhere in money paths.
"""
from datetime import date, timedelta

from db import db, mint_allocation_sequence
from util import CLOCK, quarter_label, round_half_up_int, touch

FREIGHT_FLAT_CENTS = 2500
EQUIPMENT_SURCHARGE_CENTS_PER_UNIT = 1500
MIN_SHELF_LIFE_ON_DELIVERY_DAYS = 30

PRODUCT_TYPES = {"RX_PHARMACEUTICAL", "VACCINE", "EQUIPMENT", "CONSUMABLE"}


# ---------------------------------------------------------------------------
# Credit exposure (PRD 2.9): sum of total_cents over clinic orders in
# {APPROVED, BACKORDERED, SHIPPED}; recomputed on every order status change.
# ---------------------------------------------------------------------------

CREDIT_COUNTED_STATUSES = {"APPROVED", "BACKORDERED", "SHIPPED"}


def recompute_credit_used(clinic_id):
    clinic = db["clinics"].get(clinic_id)
    if clinic is None:
        return
    used = sum(
        o["total_cents"]
        for o in db["orders"].values()
        if o["clinic_id"] == clinic_id and o["status"] in CREDIT_COUNTED_STATUSES
    )
    if clinic.get("credit_used_cents") != used:
        clinic["credit_used_cents"] = used
        touch(clinic)


# ---------------------------------------------------------------------------
# Bundle qualification + order totals (PRD 3.4, pinned evaluation order)
# ---------------------------------------------------------------------------

def find_active_enrollment(clinic_id, quarter=None):
    """ACTIVE BundleEnrollment for (clinic, quarter label of current clock date)
    whose BundleProgram is ACTIVE. Returns (enrollment, program) or (None, None).
    """
    if quarter is None:
        quarter = quarter_label(CLOCK.today())
    for enr in db["bundle_enrollments"].values():
        if enr["clinic_id"] == clinic_id and enr["quarter"] == quarter and enr["status"] == "ACTIVE":
            prog = db["bundle_programs"].get(enr["program_id"])
            if prog is not None and prog["status"] == "ACTIVE":
                return enr, prog
    return None, None


def qualifying_lines(order_lines, program):
    """Lines whose product matches program.manufacturer_code and whose
    product_type is in program.qualifying_product_types."""
    out = []
    for line in order_lines:
        prod = db["products"].get(line["product_id"])
        if prod is None:
            continue
        if prod["manufacturer_code"] != program["manufacturer_code"]:
            continue
        if prod["product_type"] not in program["qualifying_product_types"]:
            continue
        out.append(line)
    return out


def line_discount_cents(line, program):
    """Per-line bundle discount: round_half_up(line_total * pct / 100)."""
    return round_half_up_int(line["line_total_cents"] * program["bundle_discount_pct"], 100)


def net_line_cents(line, program):
    """Qualifying net line amount: line_total minus its per-line discount."""
    return line["line_total_cents"] - line_discount_cents(line, program)


def compute_order_totals(order):
    """Pinned evaluation order (scaffold §1.3 order_totals):
      1. line_total per line (already snapshotted at submit)
      2. merchandise_subtotal
      3. bundle qualification
      4. bundle_discount (gross qualifying lines, round per line)
      5. merchandise_net
      6. equipment surcharge 1500/unit over EQUIPMENT lines
      7. freight on the NET (equality waives)
      8. total = net + surcharge + freight
    Mutates and returns the order.
    """
    lines = [l for l in db["order_lines"].values() if l["order_id"] == order["id"]]
    lines.sort(key=lambda l: (l["created_at"], l["id"]))

    subtotal = sum(l["line_total_cents"] for l in lines)

    enrollment, program = find_active_enrollment(order["clinic_id"])
    discount = 0
    if program is not None:
        qlines = qualifying_lines(lines, program)
        distinct_types = set()
        for l in qlines:
            prod = db["products"][l["product_id"]]
            distinct_types.add(prod["product_type"])
        if len(distinct_types) >= program["min_distinct_categories"]:
            discount = sum(line_discount_cents(l, program) for l in qlines)

    net = subtotal - discount

    equip_units = 0
    for l in lines:
        prod = db["products"].get(l["product_id"])
        if prod is not None and prod["product_type"] == "EQUIPMENT":
            equip_units += l["qty_requested"]
    surcharge = EQUIPMENT_SURCHARGE_CENTS_PER_UNIT * equip_units

    clinic = db["clinics"][order["clinic_id"]]
    freight = 0 if net >= clinic["free_freight_threshold_cents"] else FREIGHT_FLAT_CENTS

    order["merchandise_subtotal_cents"] = subtotal
    order["bundle_discount_cents"] = discount
    order["merchandise_net_cents"] = net
    order["equipment_surcharge_cents"] = surcharge
    order["freight_fee_cents"] = freight
    order["total_cents"] = net + surcharge + freight
    return order


# ---------------------------------------------------------------------------
# Lot status maintenance (conservation invariant: on_hand == allocated + avail)
# ---------------------------------------------------------------------------

def sync_lot_status(lot):
    """Auto AVAILABLE <-> DEPLETED on qty_available crossing zero."""
    lot["qty_available"] = lot["qty_on_hand"] - lot["qty_allocated"]
    if lot["status"] in ("AVAILABLE", "DEPLETED"):
        new_status = "DEPLETED" if lot["qty_available"] == 0 else "AVAILABLE"
        if new_status != lot["status"]:
            lot["status"] = new_status
            touch(lot)


# ---------------------------------------------------------------------------
# FEFO allocation (PRD 3.5) — single lot, all-or-nothing, earliest expiry then
# earliest lot created_at; requires expiry >= delivery_window_end date + 30 days.
# ---------------------------------------------------------------------------

def _eligible_lots(product_id, qty_needed, window_end_dt):
    min_expiry = window_end_dt.date() + timedelta(days=MIN_SHELF_LIFE_ON_DELIVERY_DAYS)
    cands = []
    for lot in db["inventory_lots"].values():
        if lot["product_id"] != product_id:
            continue
        if lot["status"] != "AVAILABLE":
            continue
        if lot["qty_available"] < qty_needed:
            continue
        if lot["expiry_date"] < min_expiry:
            continue
        cands.append(lot)
    cands.sort(key=lambda l: (l["expiry_date"], l["created_at"]))
    return cands


def _allocate_line_to_lot(line, lot):
    line["qty_allocated"] = line["qty_requested"]
    line["lot_id"] = lot["id"]
    line["status"] = "ALLOCATED"
    lot["qty_allocated"] += line["qty_requested"]
    touch(line)
    sync_lot_status(lot)
    touch(lot)


def _backorder_line(line):
    line["qty_allocated"] = 0
    line["lot_id"] = None
    line["status"] = "BACKORDERED"
    touch(line)
    mint_backorder(line)


def mint_backorder(line):
    bo = {
        "id": __import__("util").new_id(),
        "created_at": __import__("util").now_ts(),
        "updated_at": __import__("util").now_ts(),
        "version": 1,
        "order_line_id": line["id"],
        "qty_open": line["qty_requested"],
        "allocation_sequence": mint_allocation_sequence(),
        "status": "OPEN",
    }
    db["backorder_lines"][bo["id"]] = bo
    return bo


def fefo_allocate_order(order):
    """Run FEFO allocation over the order's PENDING lines in creation order."""
    lines = [l for l in db["order_lines"].values()
             if l["order_id"] == order["id"] and l["status"] == "PENDING"]
    lines.sort(key=lambda l: (l["created_at"], l["id"]))
    window_end = __import__("util").parse_datetime(order["delivery_window_end"])
    for line in lines:
        cands = _eligible_lots(line["product_id"], line["qty_requested"], window_end)
        if cands:
            _allocate_line_to_lot(line, cands[0])
        else:
            _backorder_line(line)


# ---------------------------------------------------------------------------
# Backorder waterfall (PRD 3.6): strict allocation_sequence ASC, all-or-nothing
# single-lot fills, FEFO lot choice, unfillable backorders skipped.
# ---------------------------------------------------------------------------

def _recompute_order_after_backorder_change(order):
    """BACKORDERED -> APPROVED when its last OPEN backorder resolved and every
    remaining line is ALLOCATED."""
    if order["status"] != "BACKORDERED":
        return
    lines = [l for l in db["order_lines"].values() if l["order_id"] == order["id"]]
    open_bos = [b for b in db["backorder_lines"].values()
                if b["status"] == "OPEN"
                and any(l["id"] == b["order_line_id"] for l in lines)]
    if open_bos:
        return
    if any(l["status"] == "BACKORDERED" for l in lines):
        return
    if any(l["status"] == "ALLOCATED" for l in lines):
        order["status"] = "APPROVED"
        touch(order)
        recompute_credit_used(order["clinic_id"])


def run_backorder_waterfall(product_id):
    """Fill OPEN backorders for the product in allocation_sequence ASC order."""
    # Collect candidate backorders joined to their order line.
    entries = []
    for bo in db["backorder_lines"].values():
        if bo["status"] != "OPEN":
            continue
        line = db["order_lines"].get(bo["order_line_id"])
        if line is None or line["product_id"] != product_id:
            continue
        if line["status"] != "BACKORDERED":
            continue
        entries.append((bo, line))
    entries.sort(key=lambda t: t[0]["allocation_sequence"])

    affected_orders = set()
    for bo, line in entries:
        if bo["status"] != "OPEN":
            continue
        order = db["orders"].get(line["order_id"])
        if order is None:
            continue
        window_end = __import__("util").parse_datetime(order["delivery_window_end"])
        cands = _eligible_lots(product_id, bo["qty_open"], window_end)
        if not cands:
            continue  # skipped; sweep continues
        lot = cands[0]
        # Fill: bo FILLED (qty_open zeroed), line ALLOCATED, lot debited.
        filled_qty = bo["qty_open"]
        bo["qty_open"] = 0
        bo["status"] = "FILLED"
        touch(bo)
        line["qty_allocated"] = line["qty_requested"]
        line["lot_id"] = lot["id"]
        line["status"] = "ALLOCATED"
        touch(line)
        lot["qty_allocated"] += filled_qty
        sync_lot_status(lot)
        touch(lot)
        affected_orders.add(order["id"])

    for oid in affected_orders:
        order = db["orders"].get(oid)
        if order is not None:
            _recompute_order_after_backorder_change(order)


# ---------------------------------------------------------------------------
# Order-line helpers
# ---------------------------------------------------------------------------

def order_lines(order_id):
    lines = [l for l in db["order_lines"].values() if l["order_id"] == order_id]
    lines.sort(key=lambda l: (l["created_at"], l["id"]))
    return lines


# ---------------------------------------------------------------------------
# Rebate accrual (PRD 3.8) — provisional at approval, final at program close.
# ---------------------------------------------------------------------------

def mint_provisional_accrual(order, enrollment, program, lines):
    qlines = qualifying_lines(lines, program)
    if not qlines:
        return None
    qtd_before = enrollment["qtd_qualifying_cents"]
    rate_bp = (program["rebate_bonus_rate_bp"]
               if qtd_before >= program["bonus_threshold_cents"]
               else program["rebate_base_rate_bp"])
    amount = sum(round_half_up_int(net_line_cents(l, program) * rate_bp, 10000)
                 for l in qlines)
    from util import new_id, now_ts
    accrual = {
        "id": new_id(),
        "created_at": now_ts(),
        "updated_at": now_ts(),
        "version": 1,
        "enrollment_id": enrollment["id"],
        "order_id": order["id"],
        "provisional_amount_cents": amount,
        "final_amount_cents": None,
        "status": "PROVISIONAL",
    }
    db["rebate_accruals"][accrual["id"]] = accrual
    enrollment["qtd_qualifying_cents"] += sum(net_line_cents(l, program) for l in qlines)
    touch(enrollment)
    return accrual


def reverse_accruals_for_order(order):
    """PROVISIONAL accruals of the order -> REVERSED; enrollment QTD decremented."""
    for acc in db["rebate_accruals"].values():
        if acc["order_id"] != order["id"] or acc["status"] != "PROVISIONAL":
            continue
        acc["status"] = "REVERSED"
        touch(acc)
        enr = db["bundle_enrollments"].get(acc["enrollment_id"])
        if enr is not None:
            lines = order_lines(order["id"])
            prog = db["bundle_programs"].get(enr["program_id"])
            if prog is not None:
                qlines = qualifying_lines(lines, prog)
                enr["qtd_qualifying_cents"] -= sum(
                    net_line_cents(l, prog) for l in qlines)
                touch(enr)


def reverse_accruals_for_enrollment(enrollment):
    """Supersede: PROVISIONAL accruals of the enrollment -> REVERSED.

    The superseded enrollment's own QTD stays as recorded (terminal snapshot);
    the NEW enrollment starts at zero.
    """
    for acc in db["rebate_accruals"].values():
        if acc["enrollment_id"] == enrollment["id"] and acc["status"] == "PROVISIONAL":
            acc["status"] = "REVERSED"
            touch(acc)


def finalize_program_accruals(program):
    """Program close: per enrollment, final QTD over DELIVERED orders only;
    PROVISIONAL accruals FINALIZED (order DELIVERED) or REVERSED; ACTIVE
    enrollments -> FINALIZED."""
    enrollments = [e for e in db["bundle_enrollments"].values()
                   if e["program_id"] == program["id"]]
    for enr in enrollments:
        delivered_orders = [o for o in db["orders"].values()
                            if o["clinic_id"] == enr["clinic_id"]
                            and o["status"] == "DELIVERED"]
        final_qtd = 0
        for o in delivered_orders:
            qlines = qualifying_lines(order_lines(o["id"]), program)
            final_qtd += sum(net_line_cents(l, program) for l in qlines)
        final_rate_bp = (program["rebate_bonus_rate_bp"]
                         if final_qtd >= program["bonus_threshold_cents"]
                         else program["rebate_base_rate_bp"])
        for acc in db["rebate_accruals"].values():
            if acc["enrollment_id"] != enr["id"] or acc["status"] != "PROVISIONAL":
                continue
            order = db["orders"].get(acc["order_id"])
            if order is not None and order["status"] == "DELIVERED":
                qlines = qualifying_lines(order_lines(order["id"]), program)
                acc["final_amount_cents"] = sum(
                    round_half_up_int(net_line_cents(l, program) * final_rate_bp, 10000)
                    for l in qlines)
                acc["status"] = "FINALIZED"
            else:
                acc["status"] = "REVERSED"
            touch(acc)
        if enr["status"] == "ACTIVE":
            enr["status"] = "FINALIZED"
            touch(enr)


# ---------------------------------------------------------------------------
# Quarterly cap (PRD 3.5): lazy reset when the clock's calendar quarter changes.
# ---------------------------------------------------------------------------

def lazy_reset_quarterly_counter(auth):
    current_q = quarter_label(CLOCK.today())
    if auth.get("_counter_quarter") != current_q:
        auth["_counter_quarter"] = current_q
        auth["quantity_approved_this_quarter"] = 0
        touch(auth)


# ---------------------------------------------------------------------------
# Short-date credit tiers (PRD 3.9)
# ---------------------------------------------------------------------------

def short_date_rate(days_to_expiry):
    """days <= 30 -> 1.00 | 31..90 -> 0.50 | 91..180 -> 0.25 | > 180 -> None.
    Rates as (numerator, denominator) to stay in exact integer arithmetic."""
    if days_to_expiry <= 30:
        return (1, 1)
    if days_to_expiry <= 90:
        return (1, 2)
    if days_to_expiry <= 180:
        return (1, 4)
    return None


def per_unit_credit_cents(unit_price_cents, rate):
    num, den = rate
    return round_half_up_int(unit_price_cents * num, den)
