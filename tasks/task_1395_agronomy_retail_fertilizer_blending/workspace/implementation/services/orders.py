"""Blend order services: pricing, booking gates, inventory FIFO, batch
completion cascade, payment waterfall."""

from datetime import timedelta
from decimal import Decimal

import db
from errors import (
    business, invalid_transition, validation, not_found,
    ERR_NMP_REQUIRED, ERR_NITROGEN_CAP_EXCEEDED, ERR_PHOSPHORUS_RESTRICTED,
    ERR_NO_CURRENT_PRICE, ERR_INSUFFICIENT_INVENTORY, ERR_CREDIT_LIMIT_EXCEEDED,
    ERR_RECOMMENDATION_NOT_APPROVED, ERR_RECOMMENDATION_EXPIRED,
    ERR_RECOMMENDATION_SUPERSEDED, ERR_PREPAY_CONTRACT_MISMATCH,
    ERR_BATCH_VARIANCE_EXCEEDED, ERR_OVERPAYMENT,
)
from services.core import (
    touch, append_ledger, recompute_grower_balances, current_published_sheet,
    exposure_balance_cents, lazy_recommendation, lazy_plan,
    recompute_season_closed_tons, now_stamp_helper,
)
from util import D, r3, r0_int

BATCH_VARIANCE_TOLERANCE_PCT = Decimal("0.05")
CLEANUP_BUFFER_MINUTES = 30
REBATE_TIER1_MIN_TONS = 50
REBATE_TIER1_PCT = Decimal("0.02")
REBATE_TIER2_MIN_TONS = 150
REBATE_TIER2_PCT = Decimal("0.035")

N_CAP_STATUSES = ("BOOKED", "SCHEDULED", "BATCHED", "LOADED", "DELIVERED",
                  "APPLIED_CONFIRMED", "CLOSED")


# ---------------------------------------------------------------------------
# Provisional / final line pricing
# ---------------------------------------------------------------------------

def resolve_provisional_unit_price(order, product_id):
    """PRICE_LOCKED + contract product -> contract price; else current sheet."""
    if order["price_mode"] == "PRICE_LOCKED" and order.get("prepay_contract_id"):
        contract = db.prepay_contracts.get(order["prepay_contract_id"])
        if contract and contract["product_id"] == product_id:
            return contract["unit_price_cents"]
    sheet = current_published_sheet(product_id)
    if sheet is None:
        raise business(ERR_NO_CURRENT_PRICE, 422, "No current published price sheet")
    return sheet["price_per_ton_cents"]


def resolve_final_unit_price(order, product_id):
    if order["price_mode"] == "PRICE_LOCKED" and order.get("prepay_contract_id"):
        contract = db.prepay_contracts.get(order["prepay_contract_id"])
        if contract and contract["product_id"] == product_id:
            return contract["unit_price_cents"]
    sheet = current_published_sheet(product_id)
    if sheet is None:
        raise business(ERR_NO_CURRENT_PRICE, 422, "No current published price sheet at completion")
    return sheet["price_per_ton_cents"]


def compute_line_quantity(target_rate, acres):
    return r3(D(target_rate) * D(acres) / D(2000))


def compute_line_n_contribution(target_rate, product):
    return r3(D(target_rate) * D(product["analysis_n_pct"]) / D(100))


def recompute_order_provisional(order, touch_lines=True):
    """Recompute line provisional pricing and order aggregates from the order's
    current lines. Assumes line entities in db.blend_lines belong to the order.

    touch_lines=False is used when the lines were just created with their
    computed values (creation is not a mutation, so version stays 1)."""
    lines = [l for l in db.blend_lines.values() if l["blend_order_id"] == order["id"]]
    lines.sort(key=lambda l: (l["created_at"], l["id"]))
    total = 0
    tons_total = Decimal(0)
    n_total = Decimal(0)
    for line in lines:
        product = db.products[line["product_id"]]
        unit = resolve_provisional_unit_price(order, line["product_id"])
        qty = compute_line_quantity(line["target_rate_lbs_per_acre"], order["acres"])
        line["quantity_tons"] = float(qty)
        line["unit_price_cents"] = unit
        line_amount = r0_int(qty * D(unit))
        line["line_provisional_cents"] = line_amount
        total += line_amount
        tons_total += qty
        n_total += compute_line_n_contribution(line["target_rate_lbs_per_acre"], product)
        if touch_lines:
            touch(line)
    order["provisional_total_cents"] = total
    order["tons_total"] = float(tons_total)
    order["n_lbs_per_acre"] = float(n_total)


# ---------------------------------------------------------------------------
# Inventory FIFO
# ---------------------------------------------------------------------------

def product_lots_fifo(product_id):
    lots = [l for l in db.inventory_lots.values() if l["product_id"] == product_id]
    lots.sort(key=lambda l: (l["_received_at"], l["created_at"], l["id"]))
    return lots


def check_inventory_available(order):
    """Verify per-line availability without mutating anything."""
    lines = [l for l in db.blend_lines.values() if l["blend_order_id"] == order["id"]]
    for line in lines:
        lots = product_lots_fifo(line["product_id"])
        available = sum(D(l["on_hand_tons"]) - D(l["reserved_tons"]) for l in lots)
        if available < D(line["quantity_tons"]):
            raise business(ERR_INSUFFICIENT_INVENTORY, 422, "Insufficient inventory for line")


def reserve_inventory(order):
    """FIFO reserve all lines; raises ERR_INSUFFICIENT_INVENTORY with no partial
    state kept. Records allocation in db.order_reservations[order_id]."""
    lines = [l for l in db.blend_lines.values() if l["blend_order_id"] == order["id"]]
    lines.sort(key=lambda l: (l["created_at"], l["id"]))
    allocations = []  # (lot, tons)
    try:
        for line in lines:
            need = D(line["quantity_tons"])
            for lot in product_lots_fifo(line["product_id"]):
                if need <= 0:
                    break
                avail = D(lot["on_hand_tons"]) - D(lot["reserved_tons"])
                take = min(need, avail)
                if take > 0:
                    lot["reserved_tons"] = float(D(lot["reserved_tons"]) + take)
                    touch(lot)
                    allocations.append((lot["id"], take))
                    need -= take
            if need > 0:
                raise business(ERR_INSUFFICIENT_INVENTORY, 422, "Insufficient inventory for line")
    except Exception:
        # roll back partial reservations
        for lot_id, tons in allocations:
            lot = db.inventory_lots[lot_id]
            lot["reserved_tons"] = float(D(lot["reserved_tons"]) - tons)
            touch(lot)
        raise
    db.order_reservations[order["id"]] = allocations


def release_inventory(order):
    for lot_id, tons in db.order_reservations.pop(order["id"], []):
        lot = db.inventory_lots[lot_id]
        lot["reserved_tons"] = float(D(lot["reserved_tons"]) - tons)
        touch(lot)


def convert_inventory_at_completion(order):
    """Convert reservations to shipped: on_hand -= actual share, reserved -=
    recorded allocation, shipped += actual share, over the same FIFO lots."""
    reservations = db.order_reservations.pop(order["id"], [])
    lines = [l for l in db.blend_lines.values() if l["blend_order_id"] == order["id"]]
    lines.sort(key=lambda l: (l["created_at"], l["id"]))
    # Walk each line across the FIFO lots of its product; consume both the
    # recorded reservation and the actual tonnage in the same lot order.
    res_by_lot = {}
    for lot_id, tons in reservations:
        res_by_lot[lot_id] = res_by_lot.get(lot_id, Decimal(0)) + tons
    # We don't know which reservation belonged to which line from the flat
    # record, so re-derive per-line by walking lots in FIFO order matching the
    # recorded allocations in order. Reservations were appended line-by-line
    # in line order, so zip them per line.
    # Simpler: consume per line across that product's FIFO lots.
    # Reserved amounts per (line,lot) — reconstruct from recorded sequence.
    # allocations recorded as flat list in line order; we instead store
    # per-line allocations at reservation time.
    for lot_id, tons in res_by_lot.items():
        lot = db.inventory_lots[lot_id]
        lot["reserved_tons"] = float(D(lot["reserved_tons"]) - tons)
    # Now apply actuals per line
    for line in lines:
        need = D(line["actual_quantity_tons"])
        for lot in product_lots_fifo(line["product_id"]):
            if need <= 0:
                break
            # ship from lots that had reservations first (they're the same FIFO
            # lots), then any other on_hand
            take = min(need, D(lot["on_hand_tons"]))
            if take > 0:
                lot["on_hand_tons"] = float(D(lot["on_hand_tons"]) - take)
                lot["shipped_tons"] = float(D(lot["shipped_tons"]) + take)
                touch(lot)
                need -= take
    for lot_id in res_by_lot:
        touch(db.inventory_lots[lot_id])


# ---------------------------------------------------------------------------
# Booking gate chain (order per PRD §3.5)
# ---------------------------------------------------------------------------

def book_gates(order):
    grower = db.growers[order["grower_id"]]
    field = db.fields[order["field_id"]]
    rec = db.recommendations[order["recommendation_id"]]
    lazy_recommendation(rec)

    # 1. grower ACTIVE
    if grower["credit_status"] != "ACTIVE":
        raise business("ERR_GROWER_NOT_ORDERABLE", 409, "Grower credit status is not ACTIVE")

    # 2. APPROVED, non-expired NMP exists for (field, current crop year)
    current_year = db.CLOCK.now().year
    plan = None
    for p in db.nutrient_plans.values():
        if p["field_id"] != field["id"] or p["crop_year"] != current_year:
            continue
        lazy_plan(p)
        if p["status"] == "APPROVED":
            plan = p
            break
    if plan is None:
        raise business(ERR_NMP_REQUIRED, 422, "No approved nutrient management plan for field-year")

    # 3. nitrogen cap
    field_n = Decimal(0)
    for o in db.blend_orders.values():
        if o["field_id"] == field["id"] and o["fulfillment_status"] in N_CAP_STATUSES \
                and o["id"] != order["id"]:
            field_n += D(o.get("n_lbs_per_acre") or 0)
    if field_n + D(order["n_lbs_per_acre"]) > D(plan["n_cap_lbs_per_acre"]):
        raise business(ERR_NITROGEN_CAP_EXCEEDED, 422, "Nitrogen cap exceeded for field-year")

    # 4. phosphorus restriction
    if plan.get("p_restriction_active"):
        for line in [l for l in db.blend_lines.values() if l["blend_order_id"] == order["id"]]:
            product = db.products[line["product_id"]]
            if D(product["analysis_p2o5_pct"]) > 0:
                raise business(ERR_PHOSPHORUS_RESTRICTED, 422, "Phosphorus restricted on this field")

    # 5. recommendation checks
    if rec["status"] in ("DRAFT", "PENDING_REVIEW"):
        raise business(ERR_RECOMMENDATION_NOT_APPROVED, 422, "Recommendation not approved")
    if rec["status"] == "EXPIRED":
        raise business(ERR_RECOMMENDATION_EXPIRED, 422, "Recommendation expired")
    if rec["status"] == "SUPERSEDED":
        raise business(ERR_RECOMMENDATION_SUPERSEDED, 422, "Recommendation superseded")

    # 6. PRICE_LOCKED contract checks
    if order["price_mode"] == "PRICE_LOCKED":
        cid = order.get("prepay_contract_id")
        contract = db.prepay_contracts.get(cid) if cid else None
        ok = (
            contract is not None
            and contract["grower_id"] == order["grower_id"]
            and contract["status"] == "FUNDED"
            and any(l["product_id"] == contract["product_id"]
                    for l in db.blend_lines.values() if l["blend_order_id"] == order["id"])
            and (contract["funded_cents"] - contract["drawn_cents"]) > 0
        )
        if not ok:
            raise business(ERR_PREPAY_CONTRACT_MISMATCH, 422, "Prepay contract mismatch")

    # 7. inventory availability
    check_inventory_available(order)

    # 8. FLOATING fiscal gate
    if order["price_mode"] == "FLOATING":
        if exposure_balance_cents(grower) + order["provisional_total_cents"] > grower["credit_limit_cents"]:
            raise business(ERR_CREDIT_LIMIT_EXCEEDED, 402, "Credit limit exceeded")


def book_order(order):
    book_gates(order)
    reserve_inventory(order)
    if order["price_mode"] == "PRICE_LOCKED":
        order["payment_status"] = "PREPAY_APPLIED"
    else:
        order["payment_status"] = "CREDIT_APPROVED"
    order["fulfillment_status"] = "BOOKED"
    touch(order)
    grower = db.growers[order["grower_id"]]
    touch(grower)


def requote_order(order):
    release_inventory(order)
    order["payment_status"] = "UNPAID"
    order["fulfillment_status"] = "QUOTED"
    recompute_order_provisional(order)
    touch(order)
    grower = db.growers[order["grower_id"]]
    touch(grower)


def cancel_order(order):
    from services.core import now_stamp_helper  # avoid circular at import
    prev = order["fulfillment_status"]
    if prev == "SCHEDULED":
        # void the order's SCHEDULED batch
        for b in db.blend_batches.values():
            if b["blend_order_id"] == order["id"] and b["status"] == "SCHEDULED":
                b["status"] = "VOIDED"
                b["void_reason"] = "ORDER_CANCELLED"
                touch(b)
    if prev in ("BOOKED", "SCHEDULED"):
        release_inventory(order)
    order["fulfillment_status"] = "CANCELLED"
    order["payment_status"] = "CANCELLED"
    touch(order)
    if prev in ("BOOKED", "SCHEDULED"):
        grower = db.growers[order["grower_id"]]
        touch(grower)


# ---------------------------------------------------------------------------
# Batch completion cascade
# ---------------------------------------------------------------------------

def complete_batch(batch, actuals):
    order = db.blend_orders[batch["blend_order_id"]]
    lines = [l for l in db.blend_lines.values() if l["blend_order_id"] == order["id"]]
    lines.sort(key=lambda l: (l["created_at"], l["id"]))

    # actuals must cover every line exactly once
    if not isinstance(actuals, list):
        raise validation("actuals must be an array")
    line_ids = [l["id"] for l in lines]
    # PRD 3.6 posts `actuals` "covering every line" without pinning the
    # reference key name; accept the line id under either conventional key.
    norm = []
    for a in actuals:
        if not isinstance(a, dict):
            raise validation("each actual must be an object")
        lid = a.get("blend_line_id", a.get("line_id"))
        if lid not in line_ids:
            raise validation("actual references an unknown or foreign line")
        norm.append((lid, a))
    seen = [lid for lid, _ in norm]
    if sorted(seen) != sorted(line_ids):
        raise validation("actuals must cover every line exactly once")

    # per-line variance check (inclusive 5%)
    for lid, a in norm:
        line = db.blend_lines[lid]
        actual_rate = D(a["actual_rate_lbs_per_acre"])
        target = D(line["target_rate_lbs_per_acre"])
        ratio = abs(actual_rate - target) / target
        if ratio > BATCH_VARIANCE_TOLERANCE_PCT:
            raise business(ERR_BATCH_VARIANCE_EXCEEDED, 422, "Actual rate outside tolerance")

    # final price availability for FLOATING lines
    for line in lines:
        resolve_final_unit_price(order, line["product_id"])

    # ---- cascade hop 1: lines ----
    for lid, a in norm:
        line = db.blend_lines[lid]
        actual_rate = r3(D(a["actual_rate_lbs_per_acre"]))
        target = D(line["target_rate_lbs_per_acre"])
        line["actual_rate_lbs_per_acre"] = float(actual_rate)
        actual_qty = r3(actual_rate * D(order["acres"]) / D(2000))
        line["actual_quantity_tons"] = float(actual_qty)
        final_unit = resolve_final_unit_price(order, line["product_id"])
        line["final_unit_price_cents"] = final_unit
        line["line_final_cents"] = r0_int(actual_qty * D(final_unit))
        ratio = abs(actual_rate - target) / target
        line["variance_flag"] = bool(ratio > BATCH_VARIANCE_TOLERANCE_PCT)
        touch(line)

    # ---- hop 2: order totals + rebate ----
    final_total = sum(l["line_final_cents"] for l in lines)
    tons_total = sum(D(l["actual_quantity_tons"]) for l in lines)
    order["final_total_cents"] = final_total
    order["tons_total"] = float(tons_total)
    order["invoiced_at"] = now_stamp_helper()
    grower = db.growers[order["grower_id"]]
    tier_base = D(grower.get("season_closed_tons") or 0) + tons_total
    if tier_base < D(REBATE_TIER1_MIN_TONS):
        tier_pct = Decimal("0.00")
    elif tier_base < D(REBATE_TIER2_MIN_TONS):
        tier_pct = REBATE_TIER1_PCT
    else:
        tier_pct = REBATE_TIER2_PCT
    rebate = r0_int(D(final_total) * tier_pct)
    order["rebate_cents"] = rebate

    # ---- hop 3: inventory convert ----
    convert_inventory_at_completion(order)

    # ---- hop 3b: credit/prepay settlement ----
    if order["payment_status"] == "PREPAY_APPLIED":
        contract = db.prepay_contracts[order["prepay_contract_id"]]
        draw = min(contract["funded_cents"] - contract["drawn_cents"], final_total)
        if draw > 0:
            contract["drawn_cents"] += draw
            append_ledger(grower["id"], "PREPAY_DRAWN", -draw, contract["id"])
        remainder = final_total - draw
        if remainder > 0:
            append_ledger(grower["id"], "INVOICE_POSTED", remainder, order["id"])
        if rebate > 0:
            append_ledger(grower["id"], "REBATE_CREDIT", -rebate, order["id"])
        if contract["drawn_cents"] == contract["funded_cents"] and contract["status"] == "FUNDED":
            contract["status"] = "CLOSED_SETTLED"
        touch(contract)
        if draw >= final_total:
            order["payment_status"] = "PAID"
        else:
            order["payment_status"] = "INVOICED"
    else:  # CREDIT_APPROVED
        append_ledger(grower["id"], "INVOICE_POSTED", final_total, order["id"])
        if rebate > 0:
            append_ledger(grower["id"], "REBATE_CREDIT", -rebate, order["id"])
        order["payment_status"] = "INVOICED"

    recompute_grower_balances(grower)
    touch(grower)

    order["fulfillment_status"] = "BATCHED"
    touch(order)

    batch["status"] = "COMPLETED"
    touch(batch)


# ---------------------------------------------------------------------------
# Payment waterfall
# ---------------------------------------------------------------------------

def apply_payment(grower, amount_cents):
    invoiced = [o for o in db.blend_orders.values()
                if o["grower_id"] == grower["id"] and o["payment_status"] == "INVOICED"]
    invoiced.sort(key=lambda o: (o["_invoiced_at"], o["created_at"], o["id"]))
    outstanding = sum(
        o["final_total_cents"] - db.order_payments_applied.get(o["id"], 0) for o in invoiced
    )
    if amount_cents > outstanding:
        raise business(ERR_OVERPAYMENT, 422, "Payment exceeds total outstanding billed balance")

    remaining = amount_cents
    for o in invoiced:
        if remaining <= 0:
            break
        applied = db.order_payments_applied.get(o["id"], 0)
        due = o["final_total_cents"] - applied
        pay = min(due, remaining)
        applied += pay
        remaining -= pay
        db.order_payments_applied[o["id"]] = applied
        if applied >= o["final_total_cents"]:
            o["payment_status"] = "PAID"
            if o["fulfillment_status"] == "APPLIED_CONFIRMED":
                o["fulfillment_status"] = "CLOSED"
                recompute_season_closed_tons(grower)
            touch(o)

    entry = append_ledger(grower["id"], "PAYMENT_RECEIVED", -amount_cents, grower["id"])
    touch(grower)
    return entry
