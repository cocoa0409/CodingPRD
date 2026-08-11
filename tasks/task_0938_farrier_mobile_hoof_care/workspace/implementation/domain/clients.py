"""Client standing, the rolling no-show window and the payment waterfall (PRD 3.9)."""

from core.constants import (
    NO_SHOW_PREPAY_THRESHOLD,
    NO_SHOW_ROLLING_WINDOW_DAYS,
    NO_SHOW_SUSPEND_THRESHOLD,
    PREPAY_DEPOSIT_MIN_CENTS,
)
from core.store import db, order_key
from core.timeutil import add_days, clock, parse_iso_date


def horses_of_client(client):
    return [h for h in db.horses.values() if h["client_id"] == client["id"]]


def no_show_rolling_count(client):
    """Both window bounds are inclusive."""
    window_start = add_days(clock.today, -NO_SHOW_ROLLING_WINDOW_DAYS)
    today = clock.today
    horse_ids = {h["id"] for h in horses_of_client(client)}
    count = 0
    for appointment in db.appointments.values():
        if appointment["horse_id"] not in horse_ids:
            continue
        if appointment["status"] != "NO_SHOW":
            continue
        completed = parse_iso_date(appointment.get("completed_on"))
        if completed is None:
            continue
        if window_start <= completed <= today:
            count += 1
    return count


def derive_standing(count, deposit_balance_cents):
    if count >= NO_SHOW_SUSPEND_THRESHOLD:
        return "SUSPENDED"
    if count >= NO_SHOW_PREPAY_THRESHOLD and deposit_balance_cents < PREPAY_DEPOSIT_MIN_CENTS:
        return "PREPAY_REQUIRED"
    return "ACTIVE"


def refresh_client_standing(client):
    """Recompute the rolling count and re-derive the standing.

    Returns (row_changed, standing_changed).
    """
    count = no_show_rolling_count(client)
    standing = derive_standing(count, client["deposit_balance_cents"])
    standing_changed = standing != client["billing_standing"]
    row_changed = standing_changed or count != client["no_show_count_rolling"]
    client["no_show_count_rolling"] = count
    client["billing_standing"] = standing
    return row_changed, standing_changed


def invoices_of_client(client):
    rows = [i for i in db.invoices.values() if i["client_id"] == client["id"]]
    rows.sort(key=order_key)
    return rows


def apply_payment(client, amount_cents):
    """Waterfall over ISSUED and PARTIALLY_PAID invoices with a positive balance.

    Ordered by issued_on ascending, ties by created_at ascending; the oldest
    issued invoice is filled completely before the next is touched.
    """
    targets = [
        inv
        for inv in invoices_of_client(client)
        if inv["status"] in ("ISSUED", "PARTIALLY_PAID") and inv["balance_cents"] > 0
    ]
    targets.sort(key=lambda inv: (inv["issued_on"] or "", inv["created_at"], inv["_seq"]))
    remaining = amount_cents
    for invoice in targets:
        if remaining <= 0:
            break
        applied = min(remaining, invoice["balance_cents"])
        invoice["paid_cents"] += applied
        invoice["balance_cents"] -= applied
        invoice["status"] = "PAID" if invoice["balance_cents"] == 0 else "PARTIALLY_PAID"
        db.touch(invoice)
        remaining -= applied
        if invoice["status"] == "PAID":
            appointment = db.get("appointments", invoice["appointment_id"])
            if appointment is not None and appointment["billing_status"] == "INVOICED":
                appointment["billing_status"] = "SETTLED"
                db.touch(appointment)
    client["credit_balance_cents"] += remaining
    return remaining
