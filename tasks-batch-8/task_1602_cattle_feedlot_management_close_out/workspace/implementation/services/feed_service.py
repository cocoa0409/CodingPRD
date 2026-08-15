"""Feed call business logic."""
import store
import clock
from util import new_record
from errors import raise_err, ERR_INVALID_REQUEST, ERR_PEN_NOT_OCCUPIED, \
    ERR_FEED_CALL_DATE_NOT_AFTER_PREVIOUS, ERR_COMMINGLE_RULE_VIOLATION, \
    ERR_PEN_NOT_FOUND
from . import calculations
from . import pen_service


def create_feed_call(pen_id, call_date, bunk_score, base_qty_lbs_per_head):
    """Create a feed call for a pen.

    Returns the created FeedCall record.
    """
    pen = store.pens.get(pen_id)
    if pen is None:
        raise_err(ERR_PEN_NOT_FOUND, "Pen not found: %s" % pen_id)

    # Check pen is OCCUPIED
    pen_service.check_pen_occupied(pen)

    # Check call_date is strictly after latest feed call
    prior_calls = [fc for fc in store.feed_calls.values() if fc["pen_id"] == pen_id]
    if prior_calls:
        latest_call_date = max(fc["call_date"] for fc in prior_calls)
        if call_date <= latest_call_date:
            raise_err(ERR_FEED_CALL_DATE_NOT_AFTER_PREVIOUS,
                      "call_date must be strictly after the pen's latest feed call date (%s)"
                      % latest_call_date.isoformat())

    # Compute quantity
    qty_lbs_per_head = calculations.compute_feed_call_quantity(
        pen, bunk_score, base_qty_lbs_per_head
    )

    # Derive ration
    ration = calculations.derive_common_ration(pen)
    if ration is None:
        raise_err(ERR_COMMINGLE_RULE_VIOLATION,
                  "Cannot derive common ration for pen %s (lots may not share a ration)" % pen_id)

    # Compute totals
    total_qty_lbs, total_cost_cents = calculations.compute_feed_call_totals(
        pen, qty_lbs_per_head, ration
    )

    # Create feed call record (immutable)
    rec = {
        "id": store.new_id(),
        "created_at": clock.now(),
        "pen_id": pen_id,
        "call_date": call_date,
        "bunk_score": bunk_score,
        "base_qty_lbs_per_head": base_qty_lbs_per_head,
        "ration_id": ration["id"],
        "qty_lbs_per_head": qty_lbs_per_head,
        "total_qty_lbs": total_qty_lbs,
        "total_cost_cents": total_cost_cents,
        "_seq": store.next_seq(),
    }
    store.feed_calls[rec["id"]] = rec

    # Allocate cost to lots
    calculations.allocate_feed_cost(pen, total_cost_cents)

    return rec
