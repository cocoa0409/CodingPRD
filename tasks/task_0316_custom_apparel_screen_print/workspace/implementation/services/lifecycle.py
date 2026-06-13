"""Order / production lifecycle: confirm, cancel, fulfill cascade, invoice
(PRD §3.4, §3.7, §3.8, §3.9; SCAFFOLD §1.2).

Each mutated resource is touched (updated_at + version bump). Cascades that
touch several resources bump each touched resource independently (PRD §2.4).
"""
from db import store, touch, new_common_fields
from errors import err
from clock import parse_iso8601
from services import pricing, inventory
from services.quote import compute_subtotals, _approved_proof, final_total
from services.lookups import (
    lines_of_order,
    proofs_of_order,
    active_reservations_of_order,
    reservations_of_order,
    get_garment_style,
    get_decoration_method,
    blank_skus_of_style,
)


# --- BlankSku matcher for a line's color + size ---------------------------------

def _find_blank_sku(style_id, color, size):
    for sku in blank_skus_of_style(style_id):
        if sku["color"] == color and sku["size"] == size:
            return sku
    return None


# --- Confirm --------------------------------------------------------------------

def confirm_order(order):
    """DRAFT -> CONFIRMED: price (ESTIMATE Quote), reserve blanks, charge deposit.

    Preconditions in PRD §3.4 prose order: ERR_ORDER_EMPTY, ERR_PROOF_NOT_APPROVED,
    ERR_BLANK_INSUFFICIENT.
    """
    if order["fulfillment_status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Order is not DRAFT")

    lines = lines_of_order(order["id"])
    if not lines:
        raise err("ERR_ORDER_EMPTY", "Order has no lines")

    if _approved_proof(order["id"]) is None:
        raise err("ERR_PROOF_NOT_APPROVED", "Order has no APPROVED proof")

    shop = store.shops[order["shop_id"]]
    spoilage_pct = shop["spoilage_pct"]

    # Build the per-(line,size) reservation plan and the blank-sufficiency check.
    plan = []  # list of (sku, ordered_qty, allowance, reserved)
    for line in lines:
        style = get_garment_style(line["garment_style_id"])
        for size, qty in line["size_run"].items():
            sku = _find_blank_sku(line["garment_style_id"], line["color"], size)
            ordered = int(qty)
            allowance = pricing.spoilage_allowance(ordered, spoilage_pct)
            reserved = ordered + allowance
            if sku is None or sku["on_hand_qty"] < reserved:
                raise err("ERR_BLANK_INSUFFICIENT",
                          "Insufficient blank stock for the order")
            plan.append((line, sku, ordered, allowance, reserved))

    # is_rush settled at confirmation.
    requested = parse_iso8601(order["requested_ship_date"])
    current = parse_iso8601(shop["current_utc"])
    order["is_rush"] = pricing.is_rush(requested, current, shop["rush_threshold_days"])

    # Compute the ESTIMATE quote now that is_rush is known.
    subtotals = compute_subtotals(order)
    _store_quote(order, subtotals)

    # Commit reservations (all preconditions already passed -> atomic).
    for (line, sku, ordered, allowance, reserved) in plan:
        _create_reservation(order, sku, ordered, allowance, reserved)
        inventory.reserve(sku, reserved)

    # Deposit + customer balance.
    deposit = pricing.deposit_cents(subtotals["grand_total_cents"])
    order["deposit_paid_cents"] = deposit
    customer = store.customers[order["customer_id"]]
    customer["outstanding_deposit_cents"] += deposit
    touch(customer)

    order["fulfillment_status"] = "CONFIRMED"
    touch(order)
    return order


def _store_quote(order, subtotals):
    quote = new_common_fields()
    quote.update({
        "order_id": order["id"],
        "blank_subtotal_cents": subtotals["blank_subtotal_cents"],
        "setup_subtotal_cents": subtotals["setup_subtotal_cents"],
        "decoration_subtotal_cents": subtotals["decoration_subtotal_cents"],
        "rush_surcharge_cents": subtotals["rush_surcharge_cents"],
        "grand_total_cents": subtotals["grand_total_cents"],
        "variant": "ESTIMATE",
    })
    store.quotes[quote["id"]] = quote
    return quote


def _create_reservation(order, sku, ordered, allowance, reserved):
    res = new_common_fields()
    res.update({
        "order_id": order["id"],
        "blank_sku_id": sku["id"],
        "ordered_qty": ordered,
        "allowance_qty": allowance,
        "reserved_qty": reserved,
        "status": "ACTIVE",
    })
    store.blank_reservations[res["id"]] = res
    return res


# --- Cancel ---------------------------------------------------------------------

NON_TERMINAL_PROOF = {"DRAFT", "SUBMITTED", "CHANGES_REQUESTED"}


def cancel_order(order):
    """DRAFT|CONFIRMED -> CANCELLED. Releases ACTIVE reservations, voids
    non-terminal proofs, refunds deposit (PRD §3.8)."""
    if order["fulfillment_status"] not in ("DRAFT", "CONFIRMED"):
        raise err("ERR_ORDER_NOT_CANCELLABLE", "Order is not cancellable")

    from_confirmed = order["fulfillment_status"] == "CONFIRMED"

    if from_confirmed:
        # Release every ACTIVE reservation; each release restocks its BlankSku.
        for res in active_reservations_of_order(order["id"]):
            res["status"] = "RELEASED"
            touch(res)
            sku = store.blank_skus.get(res["blank_sku_id"])
            if sku is not None:
                inventory.release(sku, res["reserved_qty"])

    # Void every non-terminal proof.
    for proof in proofs_of_order(order["id"]):
        if proof["status"] in NON_TERMINAL_PROOF:
            proof["status"] = "VOID"
            touch(proof)

    if from_confirmed:
        # Compensating deposit restoration.
        customer = store.customers[order["customer_id"]]
        customer["outstanding_deposit_cents"] -= order["deposit_paid_cents"]
        touch(customer)
        order["deposit_paid_cents"] = 0

    order["fulfillment_status"] = "CANCELLED"
    touch(order)
    return order


# --- Fulfill cascade (from ProductionRun complete) ------------------------------

def total_ordered_qty(order_id):
    """Sum of ordered_qty across the order's reservations (PRD §3.7)."""
    return sum(r["ordered_qty"] for r in reservations_of_order(order_id))


def fulfill_order(order, run):
    """IN_PRODUCTION -> FULFILLED. Settle every ACTIVE reservation to CONSUMED;
    each CONSUMED returns only the run's leftover allowance (released_units) to
    its BlankSku on_hand and clears the hold (PRD §3.8)."""
    released_units = run["released_units"]
    for res in active_reservations_of_order(order["id"]):
        res["status"] = "CONSUMED"
        touch(res)
        sku = store.blank_skus.get(res["blank_sku_id"])
        if sku is not None:
            inventory.consume(sku, res["reserved_qty"], released_units)

    order["fulfillment_status"] = "FULFILLED"
    touch(order)
    return order


# --- Invoice (FINAL total) ------------------------------------------------------

def invoice_order(order):
    """Compute the FINAL consumption-based total and set final_total_cents.

    FINAL blank subtotal bills consumed units (good + spoiled, capped at each
    reservation's reserved_qty) * blank_cost_cents; decoration & setup carried
    over; rush re-evaluated against the SAME is_rush (PRD §3.9)."""
    consumed_blank_subtotal = _consumed_blank_subtotal(order)
    order["final_total_cents"] = final_total(order, consumed_blank_subtotal)
    order["billing_status"] = "INVOICED"
    touch(order)
    return order


def _consumed_blank_subtotal(order):
    """Sum over reservations of min(consumed_for_res, reserved_qty) * blank_cost.

    Consumed units for the order come from the completed run (good + spoiled).
    Per reservation, the consumed count is capped at that reservation's
    reserved_qty (PRD §3.9). With single-size lines there is one reservation, so
    the consumed total maps directly to it.
    """
    # The completed run carries consumed_units = good + spoiled.
    completed = _completed_run(order["id"])
    consumed_remaining = completed["consumed_units"] if completed else 0
    subtotal = 0
    for res in reservations_of_order(order["id"]):
        sku = store.blank_skus.get(res["blank_sku_id"])
        style = get_garment_style(sku["garment_style_id"]) if sku else None
        blank_cost = style["blank_cost_cents"] if style else 0
        consumed_for_res = min(consumed_remaining, res["reserved_qty"])
        consumed_remaining -= consumed_for_res
        subtotal += consumed_for_res * blank_cost
    return subtotal


def _completed_run(order_id):
    for r in store.production_runs.values():
        if r["order_id"] == order_id and r["status"] == "COMPLETED":
            return r
    return None
