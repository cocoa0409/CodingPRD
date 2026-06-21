"""Reservation state-machine transitions and their cascades.

These functions assume preconditions (state, role, ownership) have already been
validated by the route layer. They execute the side effects atomically.
"""
from db import store
from errors import err
from services import calculations as calc
from services.inventory import recompute_lot_availability
from services.records import make_payment_txn, touch


def _backing_stall_hold(reservation):
    """Return the active (non-RELEASED) StallHold backing this reservation, or None."""
    active = None
    for hold in store.stall_holds.values():
        if hold["reservation_id"] == reservation["id"] and hold["status"] != "RELEASED":
            active = hold
    return active


def _release_shuttle_seat(reservation):
    """Release the assigned shuttle seat if any (PRD cascade hop 3)."""
    trip_id = reservation.get("shuttle_trip_id")
    if not trip_id:
        return
    trip = store.shuttle_trips.get(trip_id)
    if trip is not None:
        trip["seats_taken"] = max(0, trip["seats_taken"] - 1)
        touch(trip)
    reservation["shuttle_trip_id"] = None


# ---------------------------------------------------------------------------
# check-in: BOOKED -> CHECKED_IN
# ---------------------------------------------------------------------------
def check_in(reservation):
    now = store.current_utc()
    customer = store.customers[reservation["customer_id"]]

    # Preconditions (PRD §3.5).
    if reservation["occupancy_status"] != "BOOKED":
        raise err("ERR_INVALID_STATE")
    hold = _backing_stall_hold(reservation)
    early_grace_threshold = reservation["scheduled_start"] - _minutes(calc.CHECKIN_EARLY_GRACE_MIN)
    if not (now >= early_grace_threshold):
        raise err("ERR_INVALID_STATE")
    if hold is None or hold["status"] != "HELD":
        raise err("ERR_INVALID_STATE")
    if customer["status"] != "ACTIVE":
        raise err("ERR_CUSTOMER_SUSPENDED")

    # Side effects.
    reservation["actual_in"] = now
    reservation["occupancy_status"] = "CHECKED_IN"
    touch(reservation)

    hold["status"] = "OCCUPIED"
    hold["hold_start"] = now
    touch(hold)
    # Availability unchanged (HELD and OCCUPIED both consume inventory).


# ---------------------------------------------------------------------------
# gate-exit: CHECKED_IN -> OUT_TEMP
# ---------------------------------------------------------------------------
def gate_exit(reservation):
    if reservation["occupancy_status"] != "CHECKED_IN":
        raise err("ERR_INVALID_STATE")
    lot = store.lots[reservation["lot_id"]]
    if not lot["in_out_allowed"]:
        raise err("ERR_IN_OUT_NOT_ALLOWED")
    reservation["occupancy_status"] = "OUT_TEMP"
    touch(reservation)
    # StallHold stays OCCUPIED; no charge finalized.


# ---------------------------------------------------------------------------
# gate-reentry: OUT_TEMP -> CHECKED_IN
# ---------------------------------------------------------------------------
def gate_reentry(reservation):
    if reservation["occupancy_status"] != "OUT_TEMP":
        raise err("ERR_INVALID_STATE")
    reservation["occupancy_status"] = "CHECKED_IN"
    touch(reservation)


# ---------------------------------------------------------------------------
# check-out: CHECKED_IN -> CHECKED_OUT  (+ final charge + settlement cascade)
# ---------------------------------------------------------------------------
def check_out(reservation):
    if reservation["occupancy_status"] != "CHECKED_IN":
        raise err("ERR_INVALID_STATE")

    now = store.current_utc()
    snapshot = reservation["rate_snapshot"]

    reservation["actual_out"] = now
    reservation["occupancy_status"] = "CHECKED_OUT"

    # Final charge over [actual_in, actual_out) + overstay.
    gross = calc.compute_parking_charge(
        snapshot, reservation["stall_class"], reservation["actual_in"], now
    )
    overstay = calc.compute_overstay_surcharge(snapshot, reservation["scheduled_end"], now)
    reservation["overstay_cents"] = overstay
    reservation["final_charge_cents"] = gross + overstay
    touch(reservation)

    # Cascade hop 2: release stall hold.
    hold = _backing_stall_hold(reservation)
    if hold is not None:
        hold["status"] = "RELEASED"
        hold["hold_end"] = now
        touch(hold)
        recompute_lot_availability(store.lots[reservation["lot_id"]])

    # Cascade hop 3: release shuttle seat.
    _release_shuttle_seat(reservation)

    # Settlement.
    _settle_on_checkout(reservation)


def _settle_on_checkout(reservation):
    provisional = reservation["provisional_quote_cents"]
    final = reservation["final_charge_cents"]
    if reservation["settlement_status"] == "AUTHORIZED":
        # Prepaid path.
        make_payment_txn(reservation["id"], "CAPTURE", min(provisional, final), "prepay capture")
        if final > provisional:
            make_payment_txn(
                reservation["id"], "CAPTURE", final - provisional, "overstay capture"
            )
        elif final < provisional:
            make_payment_txn(
                reservation["id"], "REFUND", provisional - final, "early-departure refund"
            )
        reservation["settlement_status"] = "SETTLED"
        touch(reservation)
    elif reservation["settlement_status"] == "UNSETTLED":
        # Pay-on-exit path.
        make_payment_txn(reservation["id"], "CAPTURE", final, "pay-on-exit capture")
        reservation["settlement_status"] = "SETTLED"
        touch(reservation)


# ---------------------------------------------------------------------------
# cancel: BOOKED -> CANCELLED
# ---------------------------------------------------------------------------
def cancel(reservation):
    now = store.current_utc()
    if reservation["occupancy_status"] != "BOOKED":
        raise err("ERR_INVALID_STATE")
    if not (now < reservation["scheduled_start"]):
        raise err("ERR_INVALID_STATE")

    reservation["occupancy_status"] = "CANCELLED"
    touch(reservation)

    # Release inventory.
    hold = _backing_stall_hold(reservation)
    if hold is not None:
        hold["status"] = "RELEASED"
        touch(hold)
        recompute_lot_availability(store.lots[reservation["lot_id"]])

    # Release shuttle seat.
    _release_shuttle_seat(reservation)

    # Settlement: only prepaid reservations refund.
    if reservation["settlement_status"] == "AUTHORIZED":
        policy = _policy_for_lot(reservation["lot_id"])
        free_cancel_hours = policy["free_cancel_hours"] if policy else 0
        late_fee_bps = policy["late_cancel_fee_bps"] if policy else 0
        hours_to_start = (reservation["scheduled_start"] - now).total_seconds() / 3600.0
        retained, refund = calc.compute_cancellation_fee(
            reservation["provisional_quote_cents"],
            hours_to_start,
            free_cancel_hours,
            late_fee_bps,
        )
        if retained > 0:
            make_payment_txn(
                reservation["id"], "FEE_RETAIN", retained, "late-cancel fee retained"
            )
        make_payment_txn(reservation["id"], "REFUND", refund, "cancellation refund")
        reservation["settlement_status"] = "REFUNDED"
        touch(reservation)


# ---------------------------------------------------------------------------
# no-show: BOOKED -> NO_SHOW
# ---------------------------------------------------------------------------
def mark_no_show(reservation):
    now = store.current_utc()
    if reservation["occupancy_status"] != "BOOKED":
        raise err("ERR_INVALID_STATE")
    grace_threshold = reservation["scheduled_start"] + _minutes(calc.NO_SHOW_GRACE_MIN)
    if not (now >= grace_threshold):
        raise err("ERR_INVALID_STATE")
    _apply_no_show(reservation)


def _apply_no_show(reservation):
    """Execute the four-hop no-show cascade (PRD §3.7). State precheck done by caller."""
    reservation["occupancy_status"] = "NO_SHOW"
    touch(reservation)

    # Hop 2: release stall hold.
    hold = _backing_stall_hold(reservation)
    if hold is not None:
        hold["status"] = "RELEASED"
        touch(hold)
        recompute_lot_availability(store.lots[reservation["lot_id"]])

    # Hop 3: release shuttle seat.
    _release_shuttle_seat(reservation)

    # Hop 4: strike the customer.
    customer = store.customers[reservation["customer_id"]]
    customer["no_show_strikes"] += 1
    if customer["no_show_strikes"] >= calc.NO_SHOW_SUSPEND_THRESHOLD:
        customer["status"] = "SUSPENDED"
    touch(customer)

    # Settlement: prepaid retains a fee + refunds remainder.
    if reservation["settlement_status"] == "AUTHORIZED":
        retained, refund = calc.compute_no_show_fee(reservation["provisional_quote_cents"])
        if retained > 0:
            make_payment_txn(
                reservation["id"], "FEE_RETAIN", retained, "no-show fee retained"
            )
        make_payment_txn(reservation["id"], "REFUND", refund, "no-show refund")
        reservation["settlement_status"] = "REFUNDED"
        touch(reservation)


def no_show_sweep():
    """Advance every eligible BOOKED reservation to NO_SHOW. Returns swept count."""
    now = store.current_utc()
    swept = 0
    for reservation in list(store.reservations.values()):
        if reservation["occupancy_status"] != "BOOKED":
            continue
        grace_threshold = reservation["scheduled_start"] + _minutes(calc.NO_SHOW_GRACE_MIN)
        if now >= grace_threshold:
            _apply_no_show(reservation)
            swept += 1
    return swept


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _policy_for_lot(lot_id):
    """Return the lot's cancellation policy (earliest-created), or None."""
    candidates = [p for p in store.cancellation_policies.values() if p["lot_id"] == lot_id]
    if not candidates:
        return None
    candidates.sort(key=lambda r: (r["created_at"], r["_seq"]))
    return candidates[0]


def _minutes(n):
    from datetime import timedelta

    return timedelta(minutes=n)
