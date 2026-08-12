"""Billing: invoice generation/aggregation, credit application, payment
waterfall, refund reversal, dispute side effects, ops run-cycle."""

from datetime import timedelta

from core import db, now, today, stamp_new, touch, ApiError
from domain import (
    active_rate_card, any_rate_card_covering, compute_fare, round_half_up_cents,
    posture_complete, driver_release_cascade, generate_occurrences,
    append_event, GENERATION_HORIZON_DAYS, NET_DAYS, MAX_CREDIT_SHARE_BP,
)


def ride_rate_card(ride):
    """The card used for pricing this ride: snapshot first, then ACTIVE lookup."""
    card = None
    if ride.get("_rate_card_id"):
        card = db.rate_cards.get(ride["_rate_card_id"])
    if card is None:
        card = active_rate_card(
            ride["service_class"], ride["scheduled_pickup_at"].date()
        )
    if card is None:
        card = any_rate_card_covering(
            ride["service_class"], ride["scheduled_pickup_at"].date()
        )
    return card


def billable_rides(client_id, period_start, period_end):
    out = []
    for ride in db.rides.values():
        if ride["client_id"] != client_id:
            continue
        day = ride["scheduled_pickup_at"].date()
        if not (period_start <= day < period_end):
            continue
        st = ride["status"]
        if st == "COMPLETED" or st == "NO_SHOW":
            out.append(ride)
        elif st == "CANCELLED" and ride["cancellation_fee_cents"] > 0:
            out.append(ride)
    out.sort(key=lambda r: (r["scheduled_pickup_at"], r["created_at"], r["_seq"]))
    return out


def emit_lines_for_ride(invoice, ride):
    """Emit invoice lines for one billable ride in pinned order."""
    lines = []
    card = ride_rate_card(ride)

    def add(line_kind, quantity, unit_rate, amount):
        line = {
            "invoice_id": invoice["id"],
            "ride_id": ride["id"],
            "line_kind": line_kind,
            "quantity": quantity,
            "unit_rate_cents": unit_rate,
            "amount_cents": amount,
        }
        stamp_new(line)
        db.invoice_lines[line["id"]] = line
        lines.append(line)

    if ride["status"] == "COMPLETED":
        service_minutes = ride["service_minutes"] or 0
        miles = ride["actual_distance_miles"] or 0
        hourly_amount = round_half_up_cents(card["hourly_rate_cents"] * service_minutes, 60)
        add("HOURLY", service_minutes, card["hourly_rate_cents"], hourly_amount)
        mileage_amount = card["per_mile_cents"] * miles
        add("MILEAGE", miles, card["per_mile_cents"], mileage_amount)
        billable_wait = max(0, ride["wait_minutes"] - card["included_wait_minutes"])
        if billable_wait > 0:
            add("WAIT", billable_wait, card["wait_per_minute_cents"],
                billable_wait * card["wait_per_minute_cents"])
        if ride["service_class"] == "WAV":
            add("WAV_SURCHARGE", 1, card["wav_surcharge_cents"],
                card["wav_surcharge_cents"])
        # Minimum adjustment: recompute per fare formula on actuals.
        _fare, minimum_adjustment, _bw = compute_fare(
            card, service_minutes, miles, ride["wait_minutes"],
            ride["scheduled_pickup_at"], ride["service_class"],
        )
        if minimum_adjustment > 0:
            add("MINIMUM_ADJUSTMENT", 1, 0, minimum_adjustment)
    elif ride["status"] == "CANCELLED":
        unit = card["minimum_charge_cents"] if card else ride["cancellation_fee_cents"]
        add("CANCELLATION_FEE", 1, unit, ride["cancellation_fee_cents"])
    elif ride["status"] == "NO_SHOW":
        unit = card["minimum_charge_cents"] if card else ride["no_show_fee_cents"]
        add("NO_SHOW_FEE", 1, unit, ride["no_show_fee_cents"])
    return lines


def generate_invoice(client, period_start, period_end):
    """Build the DRAFT invoice with lines, credit application, due date."""
    invoice = {
        "client_id": client["id"],
        "period_start": period_start,
        "period_end": period_end,
        "issuance_status": "DRAFT",
        "dispute_status": "NONE",
        "charges_cents": 0,
        "credit_applied_cents": 0,
        "total_due_cents": 0,
        "paid_cents": 0,
        "due_date": period_end + timedelta(days=NET_DAYS),
        "past_due": False,
        "resolved_by_user_id": None,
        "resolution_credit_cents": 0,
    }
    stamp_new(invoice)
    db.invoices[invoice["id"]] = invoice

    charges = 0
    for ride in billable_rides(client["id"], period_start, period_end):
        for line in emit_lines_for_ride(invoice, ride):
            charges += line["amount_cents"]
    invoice["charges_cents"] = charges
    credit_applied = min(
        client["credit_balance_cents"],
        (charges * MAX_CREDIT_SHARE_BP) // 10000,
    )
    invoice["credit_applied_cents"] = credit_applied
    invoice["total_due_cents"] = charges - credit_applied
    if credit_applied > 0:
        client["credit_balance_cents"] -= credit_applied
        touch(client)
    return invoice


def recompute_issuance(invoice):
    """Recompute issuance_status from paid_cents vs total_due_cents."""
    if invoice["issuance_status"] in ("DRAFT", "VOIDED"):
        return
    paid = invoice["paid_cents"]
    due = invoice["total_due_cents"]
    if paid <= 0:
        invoice["issuance_status"] = "ISSUED"
    elif paid < due:
        invoice["issuance_status"] = "PARTIALLY_PAID"
    else:
        invoice["issuance_status"] = "PAID"


def apply_payment_waterfall(payment, client):
    """Apply payment amount to open invoices; remainder to client credit."""
    candidates = [
        inv
        for inv in db.invoices.values()
        if inv["client_id"] == client["id"]
        and inv["issuance_status"] in ("ISSUED", "PARTIALLY_PAID")
        and inv["total_due_cents"] > inv["paid_cents"]
    ]
    candidates.sort(key=lambda i: (i["due_date"], i["created_at"], i["_seq"]))
    remaining = payment["amount_cents"]
    for inv in candidates:
        if remaining <= 0:
            break
        applied = min(remaining, inv["total_due_cents"] - inv["paid_cents"])
        payment["applications"].append(
            {"invoice_id": inv["id"], "applied_cents": applied}
        )
        inv["paid_cents"] += applied
        recompute_issuance(inv)
        touch(inv)
        remaining -= applied
    if remaining > 0:
        client["credit_balance_cents"] += remaining
        touch(client)


def reverse_refund(payment, client, amount):
    """Reverse applications newest-first. Raises ERR_REFUND_CREDIT_SPENT.

    Atomic: computes the split first, then mutates.
    """
    total_applied = sum(a["applied_cents"] for a in payment["applications"])
    reversed_total = min(amount, total_applied)
    credit_portion = amount - reversed_total
    if credit_portion > client["credit_balance_cents"]:
        raise ApiError(
            "ERR_REFUND_CREDIT_SPENT", 409,
            "Refund credit portion exceeds the client's current credit balance",
        )
    remaining = amount
    apps = payment["applications"]
    for i in range(len(apps) - 1, -1, -1):
        if remaining <= 0:
            break
        app = apps[i]
        if app["applied_cents"] <= 0:
            continue
        rev = min(remaining, app["applied_cents"])
        inv = db.invoices.get(app["invoice_id"])
        if inv is not None:
            inv["paid_cents"] -= rev
            recompute_issuance(inv)
            touch(inv)
        app["applied_cents"] -= rev
        remaining -= rev
    payment["applications"] = [a for a in apps if a["applied_cents"] > 0]
    if credit_portion > 0:
        client["credit_balance_cents"] -= credit_portion
        touch(client)
    payment["refunded_cents"] += amount
    if payment["refunded_cents"] >= payment["amount_cents"]:
        payment["status"] = "REFUNDED"
    else:
        payment["status"] = "PARTIALLY_REFUNDED"
    touch(payment)


# ----------------------------------------------------------------------------
# Ops run-cycle
# ----------------------------------------------------------------------------


def run_cycle():
    expired_doc_ids = []
    generated_ride_ids = []
    expired_assignment_ids = []
    past_due_invoice_ids = []

    t = today()
    now_ts = now()

    # Sweep 1: compliance doc expiry (+ driver auto-suspension cascade)
    for doc in sorted(
        db.compliance_docs.values(), key=lambda d: (d["created_at"], d["_seq"])
    ):
        if doc["status"] == "APPROVED" and doc["valid_until"] <= t:
            doc["status"] = "EXPIRED"
            touch(doc)
            expired_doc_ids.append(doc["id"])
            driver = db.drivers.get(doc["driver_id"])
            if driver is not None and driver["status"] == "ACTIVE":
                if not posture_complete(driver["id"], t):
                    driver["status"] = "SUSPENDED"
                    touch(driver)
                    driver_release_cascade(driver)

    # Sweep 2: standing-ride horizon generation
    for series in sorted(
        db.standing_rides.values(), key=lambda s: (s["created_at"], s["_seq"])
    ):
        if series["status"] != "ACTIVE":
            continue
        for ride in generate_occurrences(series):
            generated_ride_ids.append(ride["id"])

    # Sweep 3: offer timeouts
    for asg in sorted(
        db.assignments.values(), key=lambda a: (a["created_at"], a["_seq"])
    ):
        if asg["status"] == "OFFERED" and asg["offer_expires_at"] <= now_ts:
            asg["status"] = "EXPIRED"
            touch(asg)
            expired_assignment_ids.append(asg["id"])
            ride = db.rides.get(asg["ride_id"])
            if ride is not None:
                if asg["driver_id"] not in ride["excluded_driver_ids"]:
                    ride["excluded_driver_ids"].append(asg["driver_id"])
                touch(ride)
                append_event(ride, "EXPIRED", "system", "system")

    # Sweep 4: receivables aging (past_due latch)
    for inv in sorted(
        db.invoices.values(), key=lambda i: (i["created_at"], i["_seq"])
    ):
        if (
            inv["issuance_status"] in ("ISSUED", "PARTIALLY_PAID")
            and t > inv["due_date"]
            and not inv["past_due"]
        ):
            inv["past_due"] = True
            touch(inv)
            past_due_invoice_ids.append(inv["id"])

    db.ops_epoch += 1
    return {
        "ops_epoch": db.ops_epoch,
        "expired_compliance_doc_ids": expired_doc_ids,
        "generated_ride_ids": generated_ride_ids,
        "expired_assignment_ids": expired_assignment_ids,
        "past_due_invoice_ids": past_due_invoice_ids,
    }
