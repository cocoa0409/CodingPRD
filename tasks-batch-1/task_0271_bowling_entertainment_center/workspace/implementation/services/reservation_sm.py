"""Reservation state machine + cascades (PRD §3.3–§3.7, SCAFFOLD §1.2).

States: DRAFT, HELD, CONFIRMED, CHECKED_IN, COMPLETED, CANCELLED, EXPIRED,
NO_SHOW, plus the off-lifecycle WAITLISTED.
"""
from datetime import timedelta

from db import db, touch
from errors import err
from services.util import parse_datetime
from services import pricing
from services import ledger

CHECKIN_WINDOW_MINUTES = pricing.CHECKIN_WINDOW_MINUTES
HOLD_TTL_MINUTES = pricing.HOLD_TTL_MINUTES


def _resource(res):
    if res["resource_kind"] == "LANE":
        return db.lanes.get(res["lane_id"])
    return db.bays.get(res["bay_id"])


def _conflict_error(res):
    return err(
        "ERR_LANE_TIME_CONFLICT" if res["resource_kind"] == "LANE" else "ERR_BAY_TIME_CONFLICT",
        "Requested window conflicts with an existing booking",
    )


def _check_capacity(res):
    """ERR_CAPACITY_EXCEEDED / ERR_PARTY_GUESTS_EXCEED_MAX (PRD §3.3)."""
    # Party guest cap first (more specific error).
    if res.get("party_package_id"):
        pkg = db.party_packages.get(res["party_package_id"])
        if pkg and res.get("guest_count", 0) > pkg["max_guests"]:
            raise err("ERR_PARTY_GUESTS_EXCEED_MAX", "guest_count exceeds package max_guests")
    if res["resource_kind"] == "LANE":
        lane = db.lanes.get(res["lane_id"])
        if lane and res["bowler_count"] > lane["max_bowlers"]:
            raise err("ERR_CAPACITY_EXCEEDED", "bowler_count exceeds lane max_bowlers")
    else:
        bay = db.bays.get(res["bay_id"])
        if bay and res["bowler_count"] > bay["capacity"]:
            raise err("ERR_CAPACITY_EXCEEDED", "bowler_count exceeds bay capacity")


def hold(res):
    """DRAFT -> HELD (PRD §3.3). Validation order per §1.4 priorities 40/50/51/52/60."""
    if res["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Reservation must be DRAFT to hold")

    customer = db.customers.get(res["customer_id"])
    # Resource out of service (P40)
    resource = _resource(res)
    if resource is None:
        raise err("ERR_NOT_FOUND", "Target resource not found")
    if resource["status"] != "IN_SERVICE":
        raise err("ERR_RESOURCE_OUT_OF_SERVICE", "Target resource is OUT_OF_SERVICE")

    # Temporal overlap (P50/P51)
    if pricing.has_conflict(res):
        raise _conflict_error(res)

    # Capacity (P52)
    _check_capacity(res)

    # Fiscal: customer suspended (P60)
    if customer["status"] != "ACTIVE":
        raise err("ERR_CUSTOMER_SUSPENDED", "Customer is suspended")

    # Price + capture deposit
    new_deposit = pricing.recompute_subtotals(res)
    res["held_deposit_cents"] = new_deposit
    res["status"] = "HELD"
    res["hold_placed_at"] = db.current_utc().isoformat()
    touch(res)
    ledger.deposit_credit(customer, new_deposit)
    return res


def confirm(res, expected_version):
    """HELD -> CONFIRMED, OCC-guarded (PRD §3.5, §2.7)."""
    if res["status"] != "HELD":
        raise err("ERR_INVALID_STATE", "Reservation must be HELD to confirm")
    if expected_version != res["version"]:
        raise err("ERR_STALE_VERSION", "expected_reservation_version does not match")

    resource = _resource(res)
    if resource is None:
        raise err("ERR_NOT_FOUND", "Target resource not found")
    if resource["status"] != "IN_SERVICE":
        raise err("ERR_RESOURCE_OUT_OF_SERVICE", "Target resource is OUT_OF_SERVICE")
    if pricing.has_conflict(res):
        raise _conflict_error(res)

    res["status"] = "CONFIRMED"
    touch(res)
    return res


def revise(res, expected_version, updates):
    """CONFIRMED -> HELD, OCC-guarded, re-priced (PRD §3.5)."""
    if res["status"] != "CONFIRMED":
        raise err("ERR_INVALID_STATE", "Reservation must be CONFIRMED to revise")
    if expected_version != res["version"]:
        raise err("ERR_STALE_VERSION", "expected_reservation_version does not match")

    # Apply supplied new terms.
    for field in ("start_at", "end_at", "pricing_mode", "bowler_count", "game_count", "guest_count"):
        if field in updates and updates[field] is not None:
            res[field] = updates[field]

    # Re-run temporal-overlap check on the (possibly new) window.
    if pricing.has_conflict(res):
        raise _conflict_error(res)
    _check_capacity(res)

    customer = db.customers.get(res["customer_id"])
    old_deposit = res["held_deposit_cents"]
    new_deposit = pricing.recompute_subtotals(res)
    res["held_deposit_cents"] = new_deposit
    res["status"] = "HELD"
    res["hold_placed_at"] = db.current_utc().isoformat()
    touch(res)
    ledger.deposit_reconcile_delta(customer, new_deposit - old_deposit)
    return res


def check_in(res):
    """CONFIRMED -> CHECKED_IN within the check-in window (PRD §3.5)."""
    if res["status"] != "CONFIRMED":
        raise err("ERR_INVALID_STATE", "Reservation must be CONFIRMED to check in")
    now = db.current_utc()
    start = parse_datetime(res["start_at"])
    end = parse_datetime(res["end_at"])
    if not (now >= start - timedelta(minutes=CHECKIN_WINDOW_MINUTES) and now <= end):
        raise err("ERR_INVALID_STATE", "Outside the check-in window")
    res["status"] = "CHECKED_IN"
    touch(res)
    return res


def complete(res):
    """CHECKED_IN -> COMPLETED; all rentals must be RETURNED (PRD §3.5)."""
    if res["status"] != "CHECKED_IN":
        raise err("ERR_INVALID_STATE", "Reservation must be CHECKED_IN to complete")
    for line in db.rental_lines.values():
        if line["reservation_id"] == res["id"] and line["status"] == "OPEN":
            raise err("ERR_RENTALS_OUTSTANDING", "Open rental lines remain")
    customer = db.customers.get(res["customer_id"])
    held = res["held_deposit_cents"]
    res["status"] = "COMPLETED"
    touch(res)
    ledger.deposit_debit(customer, held)
    return res


def cancel(res):
    """HELD/CONFIRMED/WAITLISTED -> CANCELLED (PRD §3.6, §3.7)."""
    now = db.current_utc()
    if res["status"] == "WAITLISTED":
        # No deposit was held; no ledger change.
        res["status"] = "CANCELLED"
        res["cancelled_at"] = now.isoformat()
        touch(res)
        return res

    if res["status"] not in ("HELD", "CONFIRMED"):
        raise err("ERR_INVALID_STATE", "Reservation cannot be cancelled in its current state")

    customer = db.customers.get(res["customer_id"])
    held = res["held_deposit_cents"]
    refund = pricing.cancellation_refund(held, res["start_at"], now)

    res["refund_cents"] = refund
    res["held_deposit_cents"] = 0
    res["status"] = "CANCELLED"
    res["cancelled_at"] = now.isoformat()
    touch(res)

    ledger.deposit_release_with_wallet(customer, held, refund)
    ledger.return_open_rentals(res["id"])

    # CASCADE: promote earliest eligible waitlisted reservation on freed window.
    promote_waitlist(res)
    return res


def no_show(res):
    """CONFIRMED -> NO_SHOW after the window (PRD §3.6). Deposit forfeited."""
    if res["status"] != "CONFIRMED":
        raise err("ERR_INVALID_STATE", "Reservation must be CONFIRMED to mark no-show")
    now = db.current_utc()
    end = parse_datetime(res["end_at"])
    if not (now > end):
        raise err("ERR_INVALID_STATE", "Reservation window has not passed")

    customer = db.customers.get(res["customer_id"])
    held = res["held_deposit_cents"]
    res["refund_cents"] = 0
    res["held_deposit_cents"] = 0
    res["status"] = "NO_SHOW"
    touch(res)
    # Deposit forfeited: debit balance, no wallet credit. (No waitlist promotion.)
    ledger.deposit_debit(customer, held)
    return res


def expire(res):
    """HELD -> EXPIRED (system). Full waiver back to wallet (PRD §3.6)."""
    if res["status"] != "HELD":
        return res
    customer = db.customers.get(res["customer_id"])
    held = res["held_deposit_cents"]
    res["refund_cents"] = held
    res["held_deposit_cents"] = 0
    res["status"] = "EXPIRED"
    touch(res)
    ledger.deposit_release_with_wallet(customer, held, held)
    ledger.return_open_rentals(res["id"])
    # Expiry frees a window -> promote a waitlisted reservation.
    promote_waitlist(res)
    return res


def promote_waitlist(freed_res):
    """Promote earliest WAITLISTED reservation on the same resource+window (PRD §3.7).

    Promotion fires as a cascade off a cancel/expire that freed the window. The
    candidate must (a) target the same resource, (b) have an overlapping window
    with the freed booking, (c) now have no temporal-overlap conflict, and be
    the earliest by created_at ASC. Promotion prices the booking and captures a
    fresh deposit — the depth-3 final hop.
    """
    resource_kind = freed_res["resource_kind"]
    if resource_kind == "LANE":
        resource_id = freed_res["lane_id"]
    else:
        resource_id = freed_res["bay_id"]

    freed_start = parse_datetime(freed_res["start_at"])
    freed_end = parse_datetime(freed_res["end_at"])

    candidates = []
    for r in db.reservations.values():
        if r["status"] != "WAITLISTED":
            continue
        if r["resource_kind"] != resource_kind:
            continue
        if resource_kind == "LANE" and r.get("lane_id") != resource_id:
            continue
        if resource_kind == "BAY" and r.get("bay_id") != resource_id:
            continue
        # Same window: overlaps the freed booking's window.
        rs = parse_datetime(r["start_at"])
        re = parse_datetime(r["end_at"])
        if not (rs < freed_end and freed_start < re):
            continue
        candidates.append(r)

    candidates.sort(key=lambda r: (r["created_at"], r["id"]))
    for cand in candidates:
        # Freed window must now have no conflict for this candidate.
        if pricing.has_conflict(cand):
            continue
        customer = db.customers.get(cand["customer_id"])
        if customer is None or customer["status"] != "ACTIVE":
            continue
        new_deposit = pricing.recompute_subtotals(cand)
        cand["held_deposit_cents"] = new_deposit
        cand["status"] = "HELD"
        cand["hold_placed_at"] = db.current_utc().isoformat()
        touch(cand)
        ledger.deposit_credit(customer, new_deposit)
        return cand
    return None


def suspend_cascade(customer):
    """Customer suspension: every HELD reservation -> EXPIRED (PRD §3.2, depth-3)."""
    held_reservations = [
        r for r in db.reservations.values()
        if r["customer_id"] == customer["id"] and r["status"] == "HELD"
    ]
    # Deterministic order.
    held_reservations.sort(key=lambda r: (r["created_at"], r["id"]))
    for r in held_reservations:
        expire(r)


def hold_ttl_sweep():
    """Expire HELD reservations whose hold has aged >= HOLD_TTL_MINUTES (PRD §3.9)."""
    now = db.current_utc()
    aged = []
    for r in db.reservations.values():
        if r["status"] != "HELD":
            continue
        placed = r.get("hold_placed_at")
        if not placed:
            continue
        placed_dt = parse_datetime(placed)
        if (now - placed_dt) >= timedelta(minutes=HOLD_TTL_MINUTES):
            aged.append(r)
    aged.sort(key=lambda r: (r["created_at"], r["id"]))
    for r in aged:
        expire(r)
