"""Order creation, the clearance chain and the reversal chain (PRD 3.5 / 3.6)."""
import clock
from store import db, base_row, touch
from services import charges, derive, screening, volume


def create_order(winery, consumer, state_rule, sub_id, address_line, state_code,
                 zip_code, line_inputs):
    """Create the order, freeze its money, and bump Consumer.version by 1."""
    money, line_rows = charges.compute(line_inputs, state_rule, winery, sub_id is not None)
    row = base_row()
    row.update({
        "winery_id": winery["id"],
        "consumer_id": consumer["id"],
        "club_subscription_id": sub_id,
        "ship_to_address_line": address_line,
        "ship_to_state_code": state_code,
        "ship_to_zip": zip_code,
        "compliance_status": "DRAFT",
        "fulfillment_status": "UNFULFILLED",
        "rejection_error_id": None,
        "override_applied": False,
        "excise_reversed_cents": 0,
        "sales_tax_reversed_cents": 0,
        # taken from the governing state rule at creation and re-asserted at
        # the first clearance -- the same row either way (PRD 3.5)
        "adult_signature_required": state_rule["adult_signature_required"],
        "cleared_at": None,
        "returned_at": None,
        "_has_cleared_once": False,
    })
    row.update(money)
    db.orders[row["id"]] = row

    for line in line_rows:
        line_row = base_row(versioned=False)
        line_row.update(line)
        line_row["order_id"] = row["id"]
        db.order_lines[line_row["id"]] = line_row

    derive.bump_consumer(consumer)
    return row


def lines_of(order_id):
    rows = [l for l in db.order_lines.values() if l["order_id"] == order_id]
    return sorted(rows, key=lambda l: l["line_index"])


def apply_clearance(order, first_clear):
    """The five things a clearance does at once (PRD 3.6)."""
    consumer = db.consumers.get(order["consumer_id"])
    winery = db.wineries.get(order["winery_id"])
    rule = volume.state_rule_for(order["ship_to_state_code"])
    order["compliance_status"] = "CLEARED"
    order["rejection_error_id"] = None
    if not first_clear:
        # a SUSPENDED_PERMIT re-clearance leaves cleared_at at its original
        # value, appends no second entry and does not accrue excise twice
        return
    order["cleared_at"] = clock.now_iso()
    if rule is not None:
        order["adult_signature_required"] = rule["adult_signature_required"]
    order["_has_cleared_once"] = True
    volume.append_entry(
        consumer_id=order["consumer_id"],
        winery_id=order["winery_id"],
        state_code=order["ship_to_state_code"],
        liters=order["total_liters"],
        event_type="SHIPMENT_ACCEPTED",
        order_id=order["id"],
        shipment_id=None,
    )
    if consumer is not None:
        derive.bump_consumer(consumer)
    if winery is not None:
        derive.bump_winery(winery)
    sub_id = order.get("club_subscription_id")
    if sub_id:
        sub = db.club_subscriptions.get(sub_id)
        if sub is not None:
            touch(sub)


def reverse_order(order, shipment_id=None):
    """Compensating movement: a signed RETURN_CREDIT plus the reversal fields."""
    consumer = db.consumers.get(order["consumer_id"])
    winery = db.wineries.get(order["winery_id"])
    volume.append_entry(
        consumer_id=order["consumer_id"],
        winery_id=order["winery_id"],
        state_code=order["ship_to_state_code"],
        liters=-volume.dec(order["total_liters"]),
        event_type="RETURN_CREDIT",
        order_id=order["id"],
        shipment_id=shipment_id,
    )
    order["excise_reversed_cents"] = order["excise_tax_cents"]
    order["sales_tax_reversed_cents"] = order["sales_tax_cents"]
    if winery is not None:
        derive.bump_winery(winery)
    if consumer is not None:
        derive.bump_consumer(consumer)


def redebit_order(order):
    """A re-ship re-debits the liters the return credited back (PRD 3.7)."""
    consumer = db.consumers.get(order["consumer_id"])
    winery = db.wineries.get(order["winery_id"])
    volume.append_entry(
        consumer_id=order["consumer_id"],
        winery_id=order["winery_id"],
        state_code=order["ship_to_state_code"],
        liters=order["total_liters"],
        event_type="SHIPMENT_ACCEPTED",
        order_id=order["id"],
        shipment_id=None,
    )
    order["excise_reversed_cents"] = 0
    order["sales_tax_reversed_cents"] = 0
    if winery is not None:
        derive.bump_winery(winery)
    if consumer is not None:
        derive.bump_consumer(consumer)


def screen(order):
    """Run the ladder and move the compliance dimension. Never raises."""
    was = order["compliance_status"]
    failing = screening.evaluate(order)
    if failing is None:
        apply_clearance(order, first_clear=not order.get("_has_cleared_once"))
    elif failing in screening.OVERRIDABLE:
        order["compliance_status"] = "OVERRIDE_PENDING"
        order["rejection_error_id"] = failing
    else:
        order["compliance_status"] = "REJECTED"
        order["rejection_error_id"] = failing
        if was == "SUSPENDED_PERMIT":
            reverse_order(order)
    touch(order)
    return order
