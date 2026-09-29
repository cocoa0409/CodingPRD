"""Derived-field maintenance and the three named cascades (PRD §2.8, §3).

Nothing in here validates: every guard has already passed by the time a service
function runs, because the ladder of PRD §2.9 is evaluated in the route before a
single row is mutated. Each function is therefore free to write.
"""

import calc
from db import by_created_at, db, new_row, touch
from timeutil import parse_dt

AMENDABLE_EXCLUDED_BUILD_STATUSES = ("DELIVERED", "WARRANTY_ACTIVE", "CANCELLED")


def clock_raw():
    """The logical plant clock as the text a business field should record."""
    return db.clock_raw


def clock_now():
    return db.clock


# ==========================================================================
# BidSpecification derived figures
# ==========================================================================


def recompute_spec_counts(spec):
    clauses = calc.spec_clauses(spec["id"])
    spec["clause_count"] = len(clauses)
    spec["mandatory_clause_count"] = sum(1 for c in clauses if c["mandatory"])


def recompute_spec_scores(spec):
    spec["compliance_score_strict"] = calc.compliance_readiness_score(
        spec["id"], provisional=False
    )
    spec["compliance_score_provisional"] = calc.compliance_readiness_score(
        spec["id"], provisional=True
    )


def recompute_spec_ratio(spec):
    spec["restrictive_clause_ratio_pct"] = calc.restrictive_clause_ratio(spec["id"])


def recompute_spec_all(spec):
    recompute_spec_counts(spec)
    recompute_spec_scores(spec)
    recompute_spec_ratio(spec)
    touch(spec)
    return spec


# ==========================================================================
# SupplierSlotLine occupancy
# ==========================================================================


def sync_slot_line(line):
    """Rebuild the line's occupancy. Always a mutation, even when unchanged."""
    reserved = calc.slot_line_occupancy(line["id"])
    line["reserved_slot_count"] = reserved
    line["available_slot_count"] = int(line["total_slot_count"]) - reserved
    touch(line)
    return line


# ==========================================================================
# UnitOrder derived figures
# ==========================================================================


def sync_unit_change_orders(unit):
    unit["change_order_total_cents"] = calc.unit_change_order_total(unit["id"])
    unit["open_change_order_count"] = calc.unit_open_change_order_count(unit["id"])


# ==========================================================================
# The program ledger and the soft-ceiling auto-suspension
# ==========================================================================


def ledger_sync(program):
    """Recompute `committed_cents` and apply the soft-ceiling auto-suspension."""
    if program is None:
        return None
    program["committed_cents"] = calc.program_committed_cents(program["id"])
    if (
        program["status"] == "ACTIVE"
        and program["committed_cents"] > calc.soft_ceiling_cents(program)
    ):
        program["status"] = "SUSPENDED"
        program["suspension_reason"] = "SOFT_CEILING_BREACH"
    touch(program)
    return program


# ==========================================================================
# Trip cancellation cascades (bay capacity is derived, so nothing to release)
# ==========================================================================


def cancel_scheduled_trips(unit_id, trip_type):
    """Cancel every still-`SCHEDULED` trip of one type, oldest first."""
    candidates = [
        t
        for t in db.trips.values()
        if t["unit_order_id"] == unit_id
        and t["trip_type"] == trip_type
        and t["status"] == "SCHEDULED"
    ]
    cancelled = 0
    for trip in by_created_at(candidates):
        trip["status"] = "CANCELLED"
        touch(trip)
        cancelled += 1
    return cancelled


# ==========================================================================
# Certification teardown — shared by Cascade A hop 2 and Cascade B hop 3
# ==========================================================================


def invalidate_certification(unit, reason):
    """Reset the certification dimension and tear up every `PASSED` test.

    Returns True when the unit actually held a `CERTIFIED` status that was reset,
    because the build revert of Cascade A hop 3 is caused by that reset and not
    by the weight verdict on its own.
    """
    if unit["certification_status"] != "CERTIFIED":
        return False
    unit["certification_status"] = "NOT_SUBMITTED"
    tests = [
        t
        for t in db.certification_tests.values()
        if t["unit_order_id"] == unit["id"] and t["status"] == "PASSED"
    ]
    for test in by_created_at(tests):
        test["status"] = "INVALIDATED"
        test["invalidated_reason"] = reason
        touch(test)
    touch(unit)
    return True


# ==========================================================================
# Cascade C — release or expiry of a chassis reservation
# ==========================================================================


def release_reservation(reservation, terminal_status):
    """Cascade C. `terminal_status` is `RELEASED` (operator) or `EXPIRED` (sweep)."""
    reservation["status"] = terminal_status
    touch(reservation)

    # Hop 1 — the slot is genuinely back on the market.
    line = db.slot_lines.get(reservation["slot_line_id"])
    if line is not None:
        sync_slot_line(line)

    # Hop 2 — caused by the freed slot: the unit counting on it goes at risk.
    unit_id = reservation.get("unit_order_id")
    if not unit_id:
        return
    unit = db.unit_orders.get(unit_id)
    if unit is None:
        return
    if unit["build_status"] not in ("SPEC_LOCKED", "PRE_CON_HELD"):
        return
    unit["chassis_reservation_id"] = None
    unit["long_lead_status"] = "AT_RISK"
    touch(unit)

    # Hop 3 — caused by the unit going at risk.
    cancel_scheduled_trips(unit["id"], "PRE_CONSTRUCTION")


# ==========================================================================
# Cascade B — release of a specification revision naming a predecessor
# ==========================================================================


def supersede_predecessor(predecessor):
    """Cascade B hops 1 through 3."""
    # Hop 1 — the predecessor is superseded and its pending responses are voided.
    predecessor["status"] = "SUPERSEDED"
    touch(predecessor)
    entries = [
        e
        for e in db.compliance_entries.values()
        if e["specification_id"] == predecessor["id"] and e["disposition"] == "PENDING"
    ]
    for entry in by_created_at(entries):
        entry["disposition"] = "VOID"
        entry["disposition_note"] = "voided by supersede"
        touch(entry)

    # Hop 2 — work still in flight against the replaced revision drifts.
    drifted = [
        u
        for u in db.unit_orders.values()
        if u["specification_id"] == predecessor["id"]
        and u["build_status"] not in AMENDABLE_EXCLUDED_BUILD_STATUSES
    ]
    for unit in by_created_at(drifted):
        unit["spec_drift_flag"] = True
        touch(unit)
        # Hop 3 — caused by hop 2. The certification dimension only; the build
        # dimension is NOT dragged backwards here.
        invalidate_certification(unit, "SPEC_SUPERSEDED")


# ==========================================================================
# Cascade A — change-order approval
# ==========================================================================


def apply_change_order_cascade(change_order, unit, program):
    """Cascade A hops 1 through 4 plus the ledger sync."""
    # Hop 1 — money, open count and axle loads rebuilt over the approved set.
    sync_unit_change_orders(unit)
    calc.apply_axle_loads(unit)
    touch(unit)

    # Hop 2 — caused by hop 1's verdict leaving WITHIN_LIMITS.
    reset = False
    if unit["weight_status"] != "WITHIN_LIMITS":
        build_status_at_reset = unit["build_status"]
        reset = invalidate_certification(unit, "WEIGHT_STATUS_CHANGE")
        # Hop 3 — caused by hop 2's certification reset.
        if reset and build_status_at_reset == "FINAL_INSPECTED":
            unit["build_status"] = "IN_PRODUCTION"
            touch(unit)
            # Hop 4 — caused by hop 3's build revert.
            cancel_scheduled_trips(unit["id"], "FINAL")

    # Ledger sync — caused by hop 1's new change-order total.
    ledger_sync(program)


def reverse_change_order(change_order, unit, program):
    """The compensating half of Cascade A: rescission.

    Money, axle loads and the weight verdict return to their pre-approval values
    because the rescinded change order simply leaves the input set. Nothing the
    approval's certification cascade destroyed is put back.
    """
    change_order["approved_by_user_id"] = None
    change_order["applied_at"] = None
    sync_unit_change_orders(unit)
    calc.apply_axle_loads(unit)
    touch(unit)
    ledger_sync(program)


# ==========================================================================
# Warranty startup creation at delivery
# ==========================================================================


def create_warranty_startup(unit, program, delivery_raw, training_hours, warranty_months):
    start_raw, end_raw = calc.warranty_window(delivery_raw, warranty_months, deferred=True)
    final_price = calc.delivery_year_actual_price(
        program, delivery_raw, unit["option_unit"]
    )
    row = new_row(
        {
            "unit_order_id": unit["id"],
            "delivery_date": delivery_raw,
            "training_hours": training_hours,
            "warranty_months": warranty_months,
            "warranty_start_date": start_raw,
            "warranty_end_date": end_raw,
            "final_price_cents": final_price,
            "price_variance_cents": final_price - int(unit["price_cents"]),
            "status": "PENDING_TRAINING",
        }
    )
    db.warranty_startups[row["id"]] = row
    return row


# ==========================================================================
# The deterministic per-program sweep
# ==========================================================================


def program_units(program_id):
    return by_created_at(
        [u for u in db.unit_orders.values() if u["program_id"] == program_id]
    )


def ops_run(program):
    now = clock_now()
    expired_reservation_count = 0
    warranty_activated_count = 0
    warranty_expired_count = 0

    # 1. Reservations still held past their expiry instant.
    due = [
        r
        for r in db.reservations.values()
        if r["program_id"] == program["id"] and r["status"] == "RESERVED"
    ]
    for reservation in by_created_at(due):
        expiry = parse_dt(reservation["expiry_at"])
        if expiry is not None and expiry <= now:
            release_reservation(reservation, "EXPIRED")
            expired_reservation_count += 1

    # 2. Warranties whose start instant has arrived drive the unit terminal.
    records = by_created_at(
        [
            w
            for w in db.warranty_startups.values()
            if _warranty_program_id(w) == program["id"]
        ]
    )
    for record in records:
        if record["status"] != "ACTIVE":
            continue
        start = parse_dt(record["warranty_start_date"])
        if start is None or start > now:
            continue
        unit = db.unit_orders.get(record["unit_order_id"])
        if unit is not None and unit["build_status"] == "DELIVERED":
            unit["build_status"] = "WARRANTY_ACTIVE"
            touch(unit)
            warranty_activated_count += 1

    # 3. Warranties whose end date has passed run out.
    for record in records:
        if record["status"] != "ACTIVE":
            continue
        end = parse_dt(record["warranty_end_date"])
        if end is not None and end < now:
            record["status"] = "EXPIRED"
            touch(record)
            warranty_expired_count += 1

    # 4. The ledger, and the soft-ceiling auto-suspension with it.
    ledger_sync(program)

    return {
        "program_id": program["id"],
        "expired_reservation_count": expired_reservation_count,
        "warranty_activated_count": warranty_activated_count,
        "warranty_expired_count": warranty_expired_count,
        "committed_cents": program["committed_cents"],
        "program_status": program["status"],
    }


def _warranty_program_id(record):
    unit = db.unit_orders.get(record["unit_order_id"])
    return unit["program_id"] if unit else None
