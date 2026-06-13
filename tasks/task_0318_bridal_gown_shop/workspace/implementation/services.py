"""Cross-entity domain services: lookups, ledger recompute, derived fields."""
import db


# ---- Existence lookups (raise the entity-specific 404 on miss) ----

def get_stylist(sid):
    import errors
    obj = db.stylists.get(sid)
    if obj is None:
        errors.raise_error(errors.ERR_STYLIST_NOT_FOUND, "Stylist not found")
    return obj


def get_fitting_room(rid):
    import errors
    obj = db.fitting_rooms.get(rid)
    if obj is None:
        errors.raise_error(errors.ERR_FITTING_ROOM_NOT_FOUND, "Fitting room not found")
    return obj


def get_party(pid):
    import errors
    obj = db.bridal_parties.get(pid)
    if obj is None:
        errors.raise_error(errors.ERR_PARTY_NOT_FOUND, "Bridal party not found")
    return obj


def get_appointment(aid):
    import errors
    obj = db.appointments.get(aid)
    if obj is None:
        errors.raise_error(errors.ERR_APPOINTMENT_NOT_FOUND, "Appointment not found")
    return obj


def get_booking(bid):
    import errors
    obj = db.fitting_room_bookings.get(bid)
    if obj is None:
        errors.raise_error(errors.ERR_BOOKING_NOT_FOUND, "Fitting-room booking not found")
    return obj


def get_order(oid):
    import errors
    obj = db.gown_orders.get(oid)
    if obj is None:
        errors.raise_error(errors.ERR_ORDER_NOT_FOUND, "Gown order not found")
    return obj


def get_accessory(aid):
    import errors
    obj = db.accessory_addons.get(aid)
    if obj is None:
        errors.raise_error(errors.ERR_ACCESSORY_NOT_FOUND, "Accessory add-on not found")
    return obj


def get_job(jid):
    import errors
    obj = db.alteration_jobs.get(jid)
    if obj is None:
        errors.raise_error(errors.ERR_ALTERATION_JOB_NOT_FOUND, "Alteration job not found")
    return obj


def get_plan(pid):
    import errors
    obj = db.payment_plans.get(pid)
    if obj is None:
        errors.raise_error(errors.ERR_PAYMENT_PLAN_NOT_FOUND, "Payment plan not found")
    return obj


# ---- Derived-field helpers ----

def active_accessory_prices(order_id):
    """Sorted-irrelevant list of ACTIVE accessory price_cents for an order."""
    return [
        a["price_cents"]
        for a in db.accessory_addons.values()
        if a["gown_order_id"] == order_id and a["status"] == "ACTIVE"
    ]


def recompute_member_order_count(party_id):
    """member_order_count = count of non-CANCELLED orders linked to the party.

    This is a mutation on the party (PRD §2.4): bump version + updated_at when
    the value changes.
    """
    party = db.bridal_parties.get(party_id)
    if party is None:
        return
    count = sum(
        1
        for o in db.gown_orders.values()
        if o.get("bridal_party_id") == party_id
        and o["fulfillment_status"] != "CANCELLED"
    )
    if party.get("member_order_count") != count:
        party["member_order_count"] = count
        db.touch(party)


def compute_plan_ledger(plan):
    """Exact ledger (PRD §3.7). Returns (amount_paid_cents, balance_due_cents).

    amount_paid = sum(SETTLED DEPOSIT/INSTALLMENT) - sum(SETTLED REFUND).

    A full refund (PRD §3.7) flips every prior SETTLED positive payment to
    REVERSED (so they drop from the positive sum) and posts a SETTLED REFUND
    of the amount that was paid. The conserved-quantity rule states the ledger
    "returns to 0" after such an unwind, so the difference is floored at 0 — the
    REFUND has nothing left to subtract against once the positives are reversed.
    In every non-refund state the positives are SETTLED and no REFUND exists, so
    the floor never engages and the raw difference is returned unchanged.
    """
    plan_id = plan["id"]
    paid = 0
    refunded = 0
    for p in db.payments.values():
        if p["payment_plan_id"] != plan_id:
            continue
        if p["settlement_status"] != "SETTLED":
            continue
        if p["kind"] in ("DEPOSIT", "INSTALLMENT"):
            paid += p["amount_cents"]
        elif p["kind"] == "REFUND":
            refunded += p["amount_cents"]
    amount_paid = paid - refunded
    if amount_paid < 0:
        amount_paid = 0
    balance_due = plan["plan_total_cents"] - amount_paid
    return amount_paid, balance_due


def refresh_plan_ledger(plan):
    """Recompute and store the plan's derived ledger figures (no version bump).

    The PRD says these recompute on read; version bumps are handled by the
    write paths (payment post / refund) explicitly. We store the values so a
    read of the plan reflects current state.
    """
    amount_paid, balance_due = compute_plan_ledger(plan)
    plan["amount_paid_cents"] = amount_paid
    plan["balance_due_cents"] = balance_due
    return amount_paid, balance_due
