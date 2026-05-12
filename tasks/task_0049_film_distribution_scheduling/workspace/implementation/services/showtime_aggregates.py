"""Recompute showtime aggregates from underlying tickets."""

from db import db


def recompute_showtime_aggregates(showtime):
    """Recompute tickets_sold_count, tickets_refunded_count, gross_box_office_cents."""
    showtime_id = showtime["id"]
    valid = 0
    refunded = 0
    gross = 0
    for t in db.tickets.values():
        if t["showtime_id"] != showtime_id:
            continue
        if t["status"] == "VALID":
            valid += 1
            gross += t["paid_amount_cents"]
        elif t["status"] in ("REFUNDED", "EXCHANGED"):
            refunded += 1
    showtime["tickets_sold_count"] = valid
    showtime["tickets_refunded_count"] = refunded
    showtime["gross_box_office_cents"] = gross
