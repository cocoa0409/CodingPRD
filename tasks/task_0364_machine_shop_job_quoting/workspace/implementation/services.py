"""Cross-entity service logic: recomputations, bubble-ups, and cascades.

These helpers mutate the in-memory store. Per PRD §2.6, any automatic
transition refreshes updated_at and increments version exactly as an
explicit call would.
"""
from db import db, touch
import calculations as calc


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------


def routing_ops_for_quote(quote_id):
    return [o for o in db.routing_ops.values() if o["quote_id"] == quote_id]


def active_allocations_for_wo(wo_id):
    return [
        a for a in db.lot_allocations.values()
        if a["work_order_id"] == wo_id and a["status"] == "ACTIVE"
    ]


def inspections_for_wo(wo_id):
    return [i for i in db.inspections.values() if i["work_order_id"] == wo_id]


def quotes_for_rfq(rfq_id):
    return [q for q in db.quotes.values() if q["rfq_id"] == rfq_id]


def part_lines_for_rfq(rfq_id):
    return [p for p in db.part_lines.values() if p["rfq_id"] == rfq_id]


def work_orders_for_quote(quote_id):
    return [w for w in db.work_orders.values() if w["quote_id"] == quote_id]


def shipments_for_wo(wo_id):
    return [s for s in db.shipments.values() if s["work_order_id"] == wo_id]


def invoices_for_wo(wo_id):
    return [inv for inv in db.invoices.values() if inv["work_order_id"] == wo_id]


# ---------------------------------------------------------------------------
# Derived-field recomputation
# ---------------------------------------------------------------------------


def recompute_part_line_count(rfq):
    """part_line_count is a derived count of children (PRD §3.1).

    Recomputing it is a derived-field refresh on PartLine create; it is NOT
    treated as a versioned mutation of the RFQ resource itself per the
    bubble-up rules (only state transitions bump version), so we update the
    count without touch()."""
    rfq["part_line_count"] = len(part_lines_for_rfq(rfq["id"]))


def recompute_work_order_actual_cost(wo):
    """ACTUAL cost rollup over COMPLETED ops + ACTIVE allocations (PRD §3.4)."""
    quote_id = wo["quote_id"]
    completed_ops = [
        o for o in routing_ops_for_quote(quote_id) if o["status"] == "COMPLETED"
    ]
    active_allocs = active_allocations_for_wo(wo["id"])
    wo["actual_cost_cents"] = calc.work_order_actual_cost(
        wo, completed_ops, active_allocs, db.material_lots
    )


# ---------------------------------------------------------------------------
# Bubble-up transitions (PRD §2.6)
# ---------------------------------------------------------------------------


def maybe_bubble_rfq_to_quoted(rfq):
    """If every PartLine of the RFQ has an APPROVED quote and RFQ is
    SUBMITTED, advance SUBMITTED -> QUOTED."""
    if rfq["status"] != "SUBMITTED":
        return
    part_lines = part_lines_for_rfq(rfq["id"])
    if not part_lines:
        return
    for pl in part_lines:
        approved = [
            q for q in db.quotes.values()
            if q["part_line_id"] == pl["id"] and q["status"] == "APPROVED"
        ]
        if not approved:
            return
    rfq["status"] = "QUOTED"
    touch(rfq)


def maybe_bubble_wo_released_to_in_process(wo):
    """First RoutingOp of the WO's quote to reach SCHEDULED drives
    RELEASED -> IN_PROCESS."""
    if wo["status"] != "RELEASED":
        return
    wo["status"] = "IN_PROCESS"
    touch(wo)


def maybe_bubble_wo_in_process_to_completed(wo):
    """qty_in_process == 0 and qty_rework_pending == 0 -> COMPLETED."""
    if wo["status"] != "IN_PROCESS":
        return
    if wo["qty_in_process"] == 0 and wo["qty_rework_pending"] == 0:
        wo["status"] = "COMPLETED"
        touch(wo)


def maybe_bubble_wo_completed_to_shipped(wo):
    """qty_shipped == qty_accepted and qty_accepted > 0 -> SHIPPED."""
    if wo["status"] != "COMPLETED":
        return
    if wo["qty_accepted"] > 0 and wo["qty_shipped"] == wo["qty_accepted"]:
        wo["status"] = "SHIPPED"
        touch(wo)
