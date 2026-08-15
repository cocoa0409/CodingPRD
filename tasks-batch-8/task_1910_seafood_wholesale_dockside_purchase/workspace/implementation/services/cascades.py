"""Cross-entity side effects: allocation release, lot recall/condemn/expiry,
order fulfillment and regression, credit exposure, substitution auto-create.

Every mutation bumps the affected resource's ``version`` and refreshes
``updated_at`` (PRD section 2.4).
"""
from decimal import Decimal

from db import store, new_record, touch
from services.calc import ZERO, select_substitute

EXPOSURE_STATES = ("CONFIRMED", "FULFILLED", "INVOICED")


def order_lines_of(order_id):
    return [l for l in store.order_lines.values() if l["sales_order_id"] == order_id]


def ticket_lines(ticket_id):
    return [l for l in store.lines.values() if l["dock_ticket_id"] == ticket_id]


def ticket_lots(ticket_id):
    line_ids = {l["id"] for l in ticket_lines(ticket_id)}
    return [lot for lot in store.lots.values() if lot["landing_line_id"] in line_ids]


def lot_allocations(lot_id, statuses=("RESERVED", "COMMITTED")):
    return [
        a for a in store.allocations.values()
        if a["inventory_lot_id"] == lot_id and a["status"] in statuses
    ]


# ---------------------------------------------------------------------------
# Recomputations
# ---------------------------------------------------------------------------
def recompute_line(line):
    """allocated = sum over {RESERVED, COMMITTED}; committed = sum over COMMITTED."""
    allocs = [
        a for a in store.allocations.values()
        if a["order_line_id"] == line["id"]
    ]
    allocated = sum(
        (a["qty_kg"] for a in allocs if a["status"] in ("RESERVED", "COMMITTED")),
        ZERO,
    )
    committed = sum(
        (a["qty_kg"] for a in allocs if a["status"] == "COMMITTED"),
        ZERO,
    )
    changed = False
    if line["allocated_qty_kg"] != allocated:
        line["allocated_qty_kg"] = allocated
        changed = True
    if line["committed_qty_kg"] != committed:
        line["committed_qty_kg"] = committed
        changed = True
    if changed:
        touch(line)


def recompute_provisional_total(ticket):
    total = sum(
        l["provisional_amount_cents"] for l in ticket_lines(ticket["id"])
        if not l["voided"]
    )
    if ticket["provisional_total_cents"] != total:
        ticket["provisional_total_cents"] = total


def recompute_final_total(ticket):
    """Sum of final_amount_cents over lines whose latest assessment is FINAL."""
    total = 0
    for line in ticket_lines(ticket["id"]):
        assessments = [
            a for a in store.assessments.values()
            if a["landing_line_id"] == line["id"]
        ]
        if not assessments:
            continue
        latest = max(assessments, key=lambda a: a["_seq"])
        if latest["status"] == "FINAL":
            total += line["final_amount_cents"]
    ticket["final_total_cents"] = total


def recompute_exposure(customer):
    total = sum(
        o["total_cents"] for o in store.orders.values()
        if o["customer_id"] == customer["id"] and o["status"] in EXPOSURE_STATES
    )
    if customer["credit_exposure_cents"] != total:
        customer["credit_exposure_cents"] = total
        touch(customer)


# ---------------------------------------------------------------------------
# Order fulfillment / regression
# ---------------------------------------------------------------------------
def fulfill_check(order):
    """CONFIRMED -> FULFILLED when every line is fully committed."""
    if order["status"] != "CONFIRMED":
        return
    lines = order_lines_of(order["id"])
    if lines and all(
        l["committed_qty_kg"] >= l["requested_qty_kg"] for l in lines
    ):
        order["status"] = "FULFILLED"
        touch(order)


def regress_order(order):
    """FULFILLED -> CONFIRMED when any line drops below fully committed."""
    if order["status"] != "FULFILLED":
        return
    lines = order_lines_of(order["id"])
    if any(l["committed_qty_kg"] < l["requested_qty_kg"] for l in lines):
        order["status"] = "CONFIRMED"
        touch(order)


def deplete_check(lot):
    """ACTIVE -> DEPLETED when available+reserved+committed are all zero and
    received > 0 (after a delivery, write-off, or condemnation)."""
    if (
        lot["lifecycle_status"] == "ACTIVE"
        and lot["received_weight_kg"] > ZERO
        and lot["available_weight_kg"] == ZERO
        and lot["reserved_weight_kg"] == ZERO
        and lot["committed_weight_kg"] == ZERO
    ):
        lot["lifecycle_status"] = "DEPLETED"


# ---------------------------------------------------------------------------
# Allocation release (direct and cascade)
# ---------------------------------------------------------------------------
def release_allocation(alloc, lot, dest):
    """Release a RESERVED/COMMITTED allocation, moving its weight from its
    current bucket into ``dest`` (available | condemned | recalled | spoiled).
    Returns the affected order_line_id, or None if already terminal."""
    qty = alloc["qty_kg"]
    if alloc["status"] == "RESERVED":
        lot["reserved_weight_kg"] -= qty
    elif alloc["status"] == "COMMITTED":
        lot["committed_weight_kg"] -= qty
    else:
        return None
    if dest == "available":
        lot["available_weight_kg"] += qty
    elif dest == "condemned":
        lot["condemned_weight_kg"] += qty
    elif dest == "recalled":
        lot["recalled_weight_kg"] += qty
    elif dest == "spoiled":
        lot["spoiled_weight_kg"] += qty
    alloc["status"] = "RELEASED"
    touch(alloc)
    return alloc["order_line_id"]


# ---------------------------------------------------------------------------
# Lot cascades
# ---------------------------------------------------------------------------
def recall_lot(lot):
    """Ticket void / re-grade: all remaining available+reserved+committed
    weight moves to recalled; allocations released; lifecycle -> RECALLED.
    Caller touches the lot after any follow-on evaluation (e.g. deplete)."""
    affected = []
    for alloc in lot_allocations(lot["id"]):
        line_id = release_allocation(alloc, lot, "recalled")
        if line_id:
            affected.append(line_id)
    lot["recalled_weight_kg"] += lot["available_weight_kg"]
    lot["available_weight_kg"] = ZERO
    lot["lifecycle_status"] = "RECALLED"
    return affected


def condemn_lot(lot):
    """Inspection condemn: available+reserved+committed -> condemned;
    allocations released; hold dimension -> CONDEMNED. Caller touches."""
    affected = []
    for alloc in lot_allocations(lot["id"]):
        line_id = release_allocation(alloc, lot, "condemned")
        if line_id:
            affected.append(line_id)
    lot["condemned_weight_kg"] += lot["available_weight_kg"]
    lot["available_weight_kg"] = ZERO
    lot["hold_status"] = "CONDEMNED"
    return affected


def expire_lot(lot):
    """Clock sweep expiry: available+reserved -> spoiled (committed stays put);
    RESERVED allocations released; lifecycle -> EXPIRED. Caller touches."""
    affected = []
    for alloc in lot_allocations(lot["id"], statuses=("RESERVED",)):
        line_id = release_allocation(alloc, lot, "spoiled")
        if line_id:
            affected.append(line_id)
    lot["spoiled_weight_kg"] += lot["available_weight_kg"]
    lot["available_weight_kg"] = ZERO
    lot["lifecycle_status"] = "EXPIRED"
    return affected


# ---------------------------------------------------------------------------
# Cascade epilogue: line recompute, order regression, auto-substitution
# ---------------------------------------------------------------------------
def post_release_epilogue(affected_line_ids, fire_substitution):
    lines = [
        store.order_lines[i]
        for i in dict.fromkeys(affected_line_ids)
        if i in store.order_lines
    ]
    for line in lines:
        recompute_line(line)
    order_ids = dict.fromkeys(l["sales_order_id"] for l in lines)
    for oid in order_ids:
        order = store.orders.get(oid)
        if order is not None:
            regress_order(order)
    if fire_substitution:
        for line in lines:
            if (
                line["allow_substitution"]
                and line["allocated_qty_kg"] < line["requested_qty_kg"]
            ):
                auto_create_substitution(line)


def auto_create_substitution(line):
    substitute = select_substitute(line)
    if substitute is None:
        return None
    rec = new_record({
        "order_line_id": line["id"],
        "original_species_id": line["species_id"],
        "substitute_species_id": substitute["id"],
        "status": "REQUESTED",
        "price_credit_cents": 0,
        "auto_created": True,
        "requested_by_user_id": "",
        "decided_by_user_id": "",
    })
    store.substitutions[rec["id"]] = rec
    return rec


# ---------------------------------------------------------------------------
# Clock sweeps (PRD section 2.6)
# ---------------------------------------------------------------------------
def run_clock_sweeps():
    now = store.clock
    today = now.date()
    # Quote expiry: PUBLISHED quotes whose quote_date has passed -> EXPIRED.
    for q in sorted(store.quotes.values(), key=lambda r: r["_seq"]):
        if q["status"] == "PUBLISHED" and q["_quote_date"] < today:
            q["status"] = "EXPIRED"
            touch(q)
    # Lot expiry: ACTIVE lots whose expiry instant has been reached -> EXPIRED,
    # with allocation-release and auto-substitution cascades.
    for lot in sorted(store.lots.values(), key=lambda r: r["_seq"]):
        if lot["lifecycle_status"] == "ACTIVE" and now >= lot["expires_at"]:
            affected = expire_lot(lot)
            touch(lot)
            post_release_epilogue(affected, fire_substitution=True)
