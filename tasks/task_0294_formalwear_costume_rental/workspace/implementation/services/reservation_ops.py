"""Reservation lifecycle operations (PRD §3.3–§3.8).

Pure state-transition logic separated from routing/auth so the workflow rules
read top-to-bottom matching the PRD prose.
"""
import db
from clock import parse_iso
from errors import (
    err,
    ERR_INVALID_STATE,
    ERR_NO_UNIT_AVAILABLE,
    ERR_CUSTOMER_WINDOW_CONFLICT,
    ERR_PARTY_NOT_OPEN,
    ERR_PARTY_LOCKED,
    ERR_STALE_VERSION,
    ERR_FIT_NOT_CLEARED,
    ERR_ALTERATION_PENDING,
    ERR_BALANCE_OUTSTANDING,
)
from services import calculations, ledger, party, views


# ---------------------------------------------------------------------------
# Unit selection (PRD §3.4 / calc unit_selection)
# ---------------------------------------------------------------------------
GRADE_RANK = {"GRADE_A": 0, "GRADE_B": 1, "GRADE_C": 2}


def _windows_overlap(a_start, a_end, b_start, b_end):
    """Half-open [start, end) overlap test (no buffer)."""
    return a_start < b_end and b_start < a_end


def select_unit(reservation):
    """Return the chosen GarmentUnit for confirmation or raise ERR_NO_UNIT_AVAILABLE."""
    pickup_start = parse_iso(reservation["pickup_window_start_iso"])
    candidates = []
    for u in db.garment_units.values():
        if u["catalog_id"] != reservation["catalog_id"]:
            continue
        if u["size_code"] != reservation["requested_size_code"]:
            continue
        if u["status"] != "AVAILABLE":
            continue
        if u["condition_grade"] not in ("GRADE_A", "GRADE_B"):
            continue
        afi = u["available_from_iso"]
        if afi is not None and parse_iso(afi) > pickup_start:
            continue
        candidates.append(u)
    if not candidates:
        raise err(ERR_NO_UNIT_AVAILABLE, "No allocatable garment unit")
    # Rank: condition_grade ASC, damage_strike_count ASC, created_at ASC (seq tie-break).
    candidates.sort(
        key=lambda u: (
            GRADE_RANK[u["condition_grade"]],
            u["damage_strike_count"],
            u["created_at"],
            db.seq_of(u),
        )
    )
    return candidates[0]


# ---------------------------------------------------------------------------
# Confirm (PENDING -> CONFIRMED)
# ---------------------------------------------------------------------------
ACTIVE_CONFLICT_STATES = {"CONFIRMED", "PICKED_UP", "OVERDUE"}


def confirm(reservation, body):
    if reservation["status"] != "PENDING":
        raise err(ERR_INVALID_STATE, "Reservation is not PENDING")

    party_order = None
    if reservation["party_order_id"] is not None:
        # Party referenced by the reservation must exist (already validated at create),
        # re-fetch current state.
        party_order = db.party_orders.get(reservation["party_order_id"])

    # Customer rental-window conflict (priority 9, ERR_CUSTOMER_WINDOW_CONFLICT).
    new_start = parse_iso(reservation["pickup_window_start_iso"])
    new_end = parse_iso(reservation["return_window_end_iso"])
    for other in db.reservations.values():
        if other["id"] == reservation["id"]:
            continue
        if other["customer_id"] != reservation["customer_id"]:
            continue
        if other["status"] not in ACTIVE_CONFLICT_STATES:
            continue
        o_start = parse_iso(other["pickup_window_start_iso"])
        o_end = parse_iso(other["return_window_end_iso"])
        if _windows_overlap(new_start, new_end, o_start, o_end):
            raise err(ERR_CUSTOMER_WINDOW_CONFLICT, "Overlapping rental window for customer")

    # Party open check (priority 7, ERR_PARTY_NOT_OPEN).
    if party_order is not None:
        posture = views.derive_posture(party_order)
        if posture not in ("FORMING", "READY"):
            raise err(ERR_PARTY_NOT_OPEN, "Party is not open for member confirmation")
        if party_order["event_date_iso"] != reservation["event_date_iso"]:
            raise err(ERR_PARTY_NOT_OPEN, "Member event_date does not match party event_date")
        # OCC (priority 14): expected_party_order_version when supplied must match.
        expected = body.get("expected_party_order_version")
        if expected is not None and expected != party_order["version"]:
            raise err(ERR_STALE_VERSION, "expected_party_order_version mismatch")

    # Allocatable unit (priority 10, ERR_NO_UNIT_AVAILABLE) — selection is the check.
    unit = select_unit(reservation)

    # --- Commit ---
    reservation["garment_unit_id"] = unit["id"]
    unit["status"] = "RESERVED"
    db.touch(unit)

    days = calculations.rental_days(
        reservation["pickup_window_start_iso"], reservation["return_window_end_iso"]
    )
    catalog = db.catalogs[reservation["catalog_id"]]
    reservation["rental_days"] = days
    reservation["quoted_charge_cents"] = calculations.booking_quote(
        catalog, days, reservation["damage_waiver_opted"]
    )
    reservation["status"] = "CONFIRMED"
    db.touch(reservation)

    if party_order is not None:
        party.recompute_after_member_change(party_order)

    return reservation


# ---------------------------------------------------------------------------
# Cancel (PENDING|CONFIRMED -> CANCELLED)
# ---------------------------------------------------------------------------
def cancel(reservation):
    status = reservation["status"]
    if status not in ("PENDING", "CONFIRMED"):
        raise err(ERR_INVALID_STATE, "Reservation cannot be cancelled from its state")

    party_order = None
    if reservation["party_order_id"] is not None:
        party_order = db.party_orders.get(reservation["party_order_id"])

    if status == "CONFIRMED":
        # A CONFIRMED member reservation may not be cancelled while its party is LOCKED.
        if party_order is not None and views.derive_posture(party_order) == "LOCKED":
            raise err(ERR_PARTY_LOCKED, "Cannot cancel: party is LOCKED")
        # Release allocated unit RESERVED -> AVAILABLE.
        if reservation["garment_unit_id"]:
            unit = db.garment_units.get(reservation["garment_unit_id"])
            if unit is not None and unit["status"] == "RESERVED":
                unit["status"] = "AVAILABLE"
                db.touch(unit)
        # Any REQUESTED alteration on this reservation -> CANCELLED.
        for a in db.alterations.values():
            if a["reservation_id"] == reservation["id"] and a["status"] == "REQUESTED":
                a["status"] = "CANCELLED"
                db.touch(a)

    reservation["status"] = "CANCELLED"
    db.touch(reservation)

    if party_order is not None:
        party.recompute_after_member_change(party_order)

    return reservation


# ---------------------------------------------------------------------------
# Pickup (CONFIRMED -> PICKED_UP)
# ---------------------------------------------------------------------------
def _fit_cleared(reservation):
    """PASS, or NEEDS_ALTERATION with at least one COMPLETED alteration; FAIL never clears."""
    fit_checks = [
        f for f in db.fit_checks.values() if f["reservation_id"] == reservation["id"]
    ]
    if any(f["verdict"] == "PASS" for f in fit_checks):
        return True
    has_needs = any(f["verdict"] == "NEEDS_ALTERATION" for f in fit_checks)
    if has_needs:
        has_completed_alt = any(
            a["reservation_id"] == reservation["id"] and a["status"] == "COMPLETED"
            for a in db.alterations.values()
        )
        if has_completed_alt:
            return True
    return False


def pickup(reservation):
    if reservation["status"] != "CONFIRMED":
        raise err(ERR_INVALID_STATE, "Reservation is not CONFIRMED")

    # Business gate 1: fit cleared (ERR_FIT_NOT_CLEARED).
    if not _fit_cleared(reservation):
        raise err(ERR_FIT_NOT_CLEARED, "Reservation is not fit-cleared for pickup")

    # Business gate 2: no REQUESTED alteration remaining (ERR_ALTERATION_PENDING).
    for a in db.alterations.values():
        if a["reservation_id"] == reservation["id"] and a["status"] == "REQUESTED":
            raise err(ERR_ALTERATION_PENDING, "An alteration is still REQUESTED")

    # Business gate 3: customer owes nothing (ERR_BALANCE_OUTSTANDING).
    if ledger.balance_owed_for_customer(reservation["customer_id"]) > 0:
        raise err(ERR_BALANCE_OUTSTANDING, "Customer has an outstanding balance")

    # --- Commit ---
    unit = db.garment_units[reservation["garment_unit_id"]]
    unit["status"] = "OUT"
    db.touch(unit)

    catalog = db.catalogs[reservation["catalog_id"]]
    ledger.post(
        reservation["customer_id"],
        "DEPOSIT_HOLD",
        catalog["deposit_cents"],
        reservation_id=reservation["id"],
    )

    reservation["status"] = "PICKED_UP"
    db.touch(reservation)
    return reservation


# ---------------------------------------------------------------------------
# Return (PICKED_UP|OVERDUE -> RETURNED|SETTLED) creating the Settlement
# ---------------------------------------------------------------------------
def record_return(reservation, returned_at_iso, disposition):
    prior_status = reservation["status"]
    if prior_status not in ("PICKED_UP", "OVERDUE"):
        raise err(ERR_INVALID_STATE, "Reservation is not PICKED_UP or OVERDUE")

    catalog = db.catalogs[reservation["catalog_id"]]
    returned = parse_iso(returned_at_iso)
    window_end = parse_iso(reservation["return_window_end_iso"])
    on_time = returned <= window_end

    charges = calculations.settlement_charges(
        catalog, reservation, returned_at_iso, disposition, on_time
    )

    settlement = {
        "reservation_id": reservation["id"],
        "returned_at_iso": returned_at_iso,
        "disposition": disposition,
        "late_days": charges["late_days"],
        "late_fee_cents": charges["late_fee_cents"],
        "damage_fee_cents": charges["damage_fee_cents"],
        "waiver_credit_cents": charges["waiver_credit_cents"],
        "net_charge_cents": charges["net_charge_cents"],
        "deposit_refund_cents": charges["deposit_refund_cents"],
    }
    db.stamp_create(settlement)
    db.settlements[settlement["id"]] = settlement

    # Conservation postings (PRD §2.9): DEPOSIT_CAPTURE for applied_from_deposit,
    # FEE_WAIVE for waiver credit, FEE_CHARGE for overflow beyond deposit.
    if charges["applied_from_deposit"] > 0:
        ledger.post(
            reservation["customer_id"],
            "DEPOSIT_CAPTURE",
            -charges["applied_from_deposit"],
            reservation_id=reservation["id"],
        )
    if charges["waiver_credit_cents"] > 0:
        ledger.post(
            reservation["customer_id"],
            "FEE_WAIVE",
            -charges["waiver_credit_cents"],
            reservation_id=reservation["id"],
        )
    if charges["net_charge_cents"] > 0:
        ledger.post(
            reservation["customer_id"],
            "FEE_CHARGE",
            charges["net_charge_cents"],
            reservation_id=reservation["id"],
        )

    # Physical unit: OUT -> IN_CLEANING; available_from_iso = returned_at + buffer.
    unit = db.garment_units[reservation["garment_unit_id"]]
    unit["status"] = "IN_CLEANING"
    from datetime import timedelta

    avail_from = returned + timedelta(days=catalog["cleaning_buffer_days"])
    from clock import to_iso

    unit["available_from_iso"] = to_iso(avail_from)

    auto_retire = False
    if disposition in ("DAMAGED", "LOST"):
        unit["condition_grade"] = _downgrade(unit["condition_grade"])
        unit["damage_strike_count"] += 1
        if unit["damage_strike_count"] >= calculations.MAX_STRIKES or disposition == "LOST":
            auto_retire = True
    if auto_retire:
        unit["status"] = "RETIRED"
    db.touch(unit)

    # Branch routing (PRD §3.7 / §3.8):
    #  - on-time branch (from PICKED_UP): -> RETURNED, awaiting finalize.
    #  - late branch from PICKED_UP: -> OVERDUE, awaiting its deposit disposition
    #    ("a settlement reached on the late branch may leave the reservation in OVERDUE").
    #  - return executed while already OVERDUE (sweep-flagged): -> SETTLED
    #    ("a return executed while the reservation is already OVERDUE likewise follows
    #     the late branch and carries the reservation through to SETTLED").
    if on_time:
        reservation["status"] = "RETURNED"
    elif prior_status == "OVERDUE":
        reservation["status"] = "SETTLED"
    else:
        reservation["status"] = "OVERDUE"
    db.touch(reservation)

    return settlement


def _downgrade(grade):
    order = ["GRADE_A", "GRADE_B", "GRADE_C"]
    idx = order.index(grade)
    return order[min(idx + 1, len(order) - 1)]
