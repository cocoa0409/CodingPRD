"""Shared booking orchestration: assignment + pricing + visit window +
collision checks + ledger charge, plus cancellation settlement.

Used by one-time booking creation, series generation, series-cancel cascade,
and reclean scheduling.
"""
import db
from errors import err
from services import calc, assignment, collisions, ledger


def resolve_cleaner_for_booking(customer_id, postal_code, pinned_cleaner_id):
    """Determine the cleaner for a new booking.

    Pinned (variant preferred_pin): the pinned cleaner is used iff ACTIVE and
    serving the postal code.
      - exists, serves area, not ACTIVE -> ERR_CLEANER_NOT_CLEARED
      - exists but does not serve area  -> ERR_NO_CLEANER_AVAILABLE
    The pinned cleaner's existence is validated earlier (ERR_NOT_FOUND).

    Unpinned: run the auto-assignment selector (may raise
    ERR_NO_CLEANER_AVAILABLE on an empty pool).

    Returns the assigned cleaner record.
    """
    if pinned_cleaner_id is not None:
        cleaner = db.cleaners.get(pinned_cleaner_id)
        # Existence already checked by caller, but guard defensively.
        if cleaner is None:
            raise err("ERR_NOT_FOUND", "cleaner not found")
        serves = postal_code in (cleaner.get("service_postal_codes") or [])
        if cleaner.get("status") != "ACTIVE":
            # PRD §3.3: not-ACTIVE pin -> ERR_CLEANER_NOT_CLEARED.
            raise err("ERR_CLEANER_NOT_CLEARED",
                      "pinned cleaner is not ACTIVE")
        if not serves:
            raise err("ERR_NO_CLEANER_AVAILABLE",
                      "pinned cleaner does not serve the area")
        return cleaner
    return assignment.select_cleaner(customer_id, postal_code)


def create_booking_record(customer, address, plan, scheduled_start, add_ons,
                          supplies_provided_by, cleaner_id, series_id=None,
                          is_reclean=False, reclean_of_booking_id=None,
                          run_collisions=True):
    """Build, price, collision-check, persist, and charge a new booking.

    Cleaner is already resolved (cleaner_id may be None only for reclean paths
    where the original cleaner is copied directly). Returns the booking record.

    Pricing: loyalty tier read from the customer's CURRENT
    lifetime_booking_count (the in-flight booking is not counted).
    Charges the customer with a CHARGE ledger entry + wallet draw-down, except
    reclean bookings which write a RECLEAN_CREDIT marker (0) and no charge.
    """
    home_size = address["home_size"]
    scheduled_end = calc.visit_window(home_size, scheduled_start)

    # Collision checks (cleaner first per priority 12, then address priority 13).
    if run_collisions:
        collisions.check_cleaner_double_booked(cleaner_id, scheduled_start, scheduled_end)
        collisions.check_address_double_booked(address["id"], scheduled_start, scheduled_end)

    quoted = calc.price_quote(
        is_reclean=is_reclean,
        plan=plan,
        home_size=home_size,
        add_ons=add_ons,
        supplies_provided_by=supplies_provided_by,
        lifetime_booking_count=customer.get("lifetime_booking_count", 0),
    )

    rec = {
        "customer_id": customer["id"],
        "address_id": address["id"],
        "pricing_plan_id": plan["id"],
        "series_id": series_id,
        "cleaner_id": cleaner_id,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
        "home_size": home_size,
        "add_ons": add_ons,
        "supplies_provided_by": supplies_provided_by,
        "status": "SCHEDULED",
        "quoted_price_cents": quoted,
        "change_fee_cents": 0,
        "is_reclean": is_reclean,
        "reclean_of_booking_id": reclean_of_booking_id,
    }
    booking = db.insert(db.bookings, rec)

    # Ledger interplay.
    if is_reclean:
        ledger.reclean_credit(customer, booking["id"])
    else:
        ledger.charge_customer(customer, quoted, booking["id"])

    return booking


def settle_cancellation(booking, customer):
    """Run cancel-branch fee + refund settlement for a booking being cancelled.

    Computes change_fee under the CANCEL branch, writes a REFUND for the full
    quoted_price_cents, and (when fee>0) a negative CHANGE_FEE. Pins
    change_fee_cents on the booking. Does NOT change booking.status or bump
    version (caller owns the transition).
    """
    from clock import clock
    fee = calc.reschedule_or_cancel_fee(
        "CANCEL", booking["quoted_price_cents"],
        booking["scheduled_start"], clock.now(),
    )
    booking["change_fee_cents"] = fee
    ledger.refund_customer(customer, booking["quoted_price_cents"], booking["id"])
    if fee > 0:
        ledger.change_fee(customer, fee, booking["id"])
