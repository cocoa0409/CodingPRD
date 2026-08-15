"""Agent credit exposure accounting (SCAFFOLD calculations.agent_credit_exposure,
PRD §2.7).

committed_exposure_cents =
    SUM(order.total_cents | agent's orders with payment UNINVOICED and
        fulfillment IN {OPEN, PARTIALLY_DELIVERED, DELIVERED})
  + SUM(invoice.outstanding_cents | agent's invoices IN {ISSUED, PARTIALLY_PAID})
settled_exposure_cents =
    SUM(invoice.outstanding_cents | agent's invoices IN {ISSUED, PARTIALLY_PAID})

Currency caveat is pinned: order totals are USD cents, invoice outstanding is
settlement cents; the exposure sums them raw without conversion.
"""
import db


def _agent_invoices(agent_id):
    """Invoices reachable via their order's agent_id."""
    result = []
    for inv in db.invoices.values():
        order = db.orders.get(inv["order_id"])
        if order is not None and order.get("agent_id") == agent_id:
            result.append(inv)
    return result


def recompute_agent_exposure(agent_id):
    agent = db.ship_agents.get(agent_id)
    if agent is None:
        return
    committed = 0
    for order in db.orders.values():
        if order.get("agent_id") != agent_id:
            continue
        if order.get("payment_status") != "UNINVOICED":
            continue
        if order.get("fulfillment_status") in ("OPEN", "PARTIALLY_DELIVERED", "DELIVERED"):
            committed += order["total_cents"]
    settled = 0
    for inv in _agent_invoices(agent_id):
        if inv.get("status") in ("ISSUED", "PARTIALLY_PAID"):
            settled += inv["outstanding_cents"]
    committed += settled
    agent["committed_exposure_cents"] = committed
    agent["settled_exposure_cents"] = settled
