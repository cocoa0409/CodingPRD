"""Derivation chains, cascades and shared domain lookups (PRD 2.9, section 3).

Aggregate fields are never patched incrementally: they are recomputed from
scratch from the rows underneath them, in the fixed order the PRD names.  A row
whose fields are re-derived to the values it already held is not re-versioned.
"""

from flask import g

import calc
from errors import ApiError
from store import (
    db,
    day_span,
    midnight,
    nights_between,
    now,
    now_iso,
    parse_date,
    parse_datetime,
)

LIVE_BLOCK_STATUSES = ("OPEN", "RESTRICTED")
COUNTED_BLOCK_STATUSES = ("OPEN", "RESTRICTED", "RELEASED", "SETTLED")
HELD_BOOKING_STATUSES = ("DRAFT", "ROOMING_LIST_SUBMITTED", "CONFIRMED", "CHECKED_OUT")
COMMITTED_BOOKING_STATUSES = ("CONFIRMED", "CHECKED_OUT")
OPEN_EXCEPTION_STATUSES = ("SUBMITTED", "UNDER_REVIEW", "INFO_REQUESTED")

_VERSION_IGNORED_FIELDS = ("version", "updated_at", "compliance_evaluated_at")


# ---------------------------------------------------------------------------
# Version / timestamp bookkeeping
# ---------------------------------------------------------------------------

def _bumped():
    if not hasattr(g, "bumped"):
        g.bumped = set()
    return g.bumped


def bump(row):
    """Refresh updated_at and increment version by exactly 1 per request."""
    seen = _bumped()
    row["updated_at"] = now_iso()
    if row["id"] in seen:
        return
    seen.add(row["id"])
    row["version"] = row["version"] + 1


def snapshot(row):
    return dict(
        (k, v)
        for k, v in row.items()
        if k not in _VERSION_IGNORED_FIELDS and not k.startswith("_")
    )


def bump_if_changed(row, before):
    if snapshot(row) != before:
        bump(row)
        return True
    return False


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------

def contracts_of_tournament(tournament_id):
    return [c for c in db.contracts.values() if c["tournament_id"] == tournament_id]


def blocks_of_contract(contract_id):
    return [b for b in db.room_blocks.values() if b["contract_id"] == contract_id]


def blocks_of_tournament(tournament_id):
    out = []
    for contract in contracts_of_tournament(tournament_id):
        out.extend(blocks_of_contract(contract["id"]))
    return out


def registrations_of_tournament(tournament_id):
    return [r for r in db.registrations.values() if r["tournament_id"] == tournament_id]


def bookings_of_registration(registration_id):
    return [b for b in db.bookings.values() if b["registration_id"] == registration_id]


def bookings_of_block(block_id):
    return [b for b in db.bookings.values() if b["room_block_id"] == block_id]


def bookings_of_contract(contract_id):
    block_ids = set(b["id"] for b in blocks_of_contract(contract_id))
    return [b for b in db.bookings.values() if b["room_block_id"] in block_ids]


def requests_of_registration(registration_id):
    return [
        r for r in db.exception_requests.values() if r["registration_id"] == registration_id
    ]


def invoices_of_contract(contract_id):
    return [i for i in db.invoices.values() if i["contract_id"] == contract_id]


def invoices_of_tournament(tournament_id):
    out = []
    for contract in contracts_of_tournament(tournament_id):
        out.extend(invoices_of_contract(contract["id"]))
    return out


def distributions_of_tournament(tournament_id):
    return [d for d in db.distributions.values() if d["tournament_id"] == tournament_id]


def distributions_of_invoice(invoice_id):
    return [d for d in db.distributions.values() if d["source_invoice_id"] == invoice_id]


def entries_of_booking(booking_id):
    return [e for e in db.rooming_entries.values() if e["booking_id"] == booking_id]


def reports_of_booking(booking_id):
    return [r for r in db.actualizations.values() if r["booking_id"] == booking_id]


def contract_of_block(block):
    return db.contracts[block["contract_id"]]


def tournament_of_contract(contract):
    return db.tournaments[contract["tournament_id"]]


def block_of_booking(booking):
    return db.room_blocks[booking["room_block_id"]]


def contract_of_booking(booking):
    return contract_of_block(block_of_booking(booking))


def registration_of_booking(booking):
    return db.registrations[booking["registration_id"]]


def tournament_of_registration(registration):
    return db.tournaments[registration["tournament_id"]]


def tournament_of_booking(booking):
    return tournament_of_registration(registration_of_booking(booking))


def tournament_of_block(block):
    return tournament_of_contract(contract_of_block(block))


def tournament_of_invoice(invoice):
    return tournament_of_contract(db.contracts[invoice["contract_id"]])


# ---------------------------------------------------------------------------
# Occupancy helpers
# ---------------------------------------------------------------------------

def block_nights(block):
    return nights_between(parse_date(block["arrival_date"]), parse_date(block["departure_date"]))


def booking_covers(booking, night):
    """Half-open [check_in_date, check_out_date) coverage of a night."""
    check_in = parse_date(booking["check_in_date"])
    check_out = parse_date(booking["check_out_date"])
    return check_in <= night < check_out


def peak_occupancy(block, bookings, statuses, extra_rooms=0, extra_range=None):
    peak = 0
    for night in block_nights(block):
        total = 0
        for booking in bookings:
            if booking["booking_status"] not in statuses:
                continue
            if booking_covers(booking, night):
                total += booking["rooms_requested"]
        if extra_range is not None and extra_range[0] <= night < extra_range[1]:
            total += extra_rooms
        if total > peak:
            peak = total
    return peak


def held_occupancy_on(block, night, exclude_ids=()):
    total = 0
    for booking in bookings_of_block(block["id"]):
        if booking["id"] in exclude_ids:
            continue
        if booking["booking_status"] not in HELD_BOOKING_STATUSES:
            continue
        if booking_covers(booking, night):
            total += booking["rooms_requested"]
    return total


# ---------------------------------------------------------------------------
# Recompute chain — registration
# ---------------------------------------------------------------------------

def recompute_registration(registration):
    before = snapshot(registration)
    tournament = tournament_of_registration(registration)

    registration["required_rooms_registered"] = calc.segregated_rooms(
        registration["roster_player_count"], registration["roster_staff_count"]
    )
    registration["required_room_nights"] = (
        registration["required_rooms_registered"] * tournament["night_count"]
    )
    registration["minimum_rooms_for_compliance"] = calc.pooled_rooms(
        registration["roster_player_count"], registration["roster_staff_count"]
    )

    registration["exempt_rooms_granted"] = sum(
        r["approved_rooms_exempt"]
        for r in requests_of_registration(registration["id"])
        if r["status"] == "APPROVED"
    )
    registration["effective_required_rooms"] = max(
        0,
        registration["minimum_rooms_for_compliance"] - registration["exempt_rooms_granted"],
    )
    registration["committed_rooms"] = sum(
        b["rooms_requested"]
        for b in bookings_of_registration(registration["id"])
        if b["booking_status"] in COMMITTED_BOOKING_STATUSES
    )

    if not tournament["stay_to_play_required"]:
        status = "HOUSING_COMPLIANT"
    elif registration["effective_required_rooms"] == 0 and registration["exempt_rooms_granted"] >= 1:
        status = "EXCEPTION_GRANTED"
    elif registration["committed_rooms"] >= registration["effective_required_rooms"]:
        status = "HOUSING_COMPLIANT"
    elif tournament["posture"] == "OPEN":
        status = "PENDING_HOUSING"
    else:
        status = "NON_COMPLIANT"
    registration["status"] = status
    registration["compliance_evaluated_at"] = now_iso()
    bump_if_changed(registration, before)


# ---------------------------------------------------------------------------
# Recompute chain — block, contract, tournament
# ---------------------------------------------------------------------------

def recompute_block_occupancy(block):
    """Refresh the three occupancy counters and the utilization posture.

    Blocks that have reached RELEASED or SETTLED are frozen: their committed,
    released-unsold and available counters are never recomputed, which is what
    keeps the room-inventory conservation invariant of PRD 2.12 true.
    """
    before = snapshot(block)
    if block["status"] in LIVE_BLOCK_STATUSES:
        committed = peak_occupancy(
            block, bookings_of_block(block["id"]), COMMITTED_BOOKING_STATUSES
        )
        block["rooms_committed"] = committed
        block["rooms_available"] = block["block_size_rooms"] - committed
        block["rooms_released_unsold"] = 0
        block["utilization_pct"] = calc.ratio_4dp(committed, block["block_size_rooms"])
        if block["utilization_pct"] >= calc.BLOCK_RESTRICT_UTILIZATION:
            block["status"] = "RESTRICTED"
        else:
            block["status"] = "OPEN"
    bump_if_changed(block, before)
    propagate_from_block(block)


def recompute_block_actualized(block):
    before = snapshot(block)
    block["actualized_room_nights"] = sum(
        b["actualized_room_nights"]
        for b in bookings_of_block(block["id"])
        if b["booking_status"] == "CHECKED_OUT"
    )
    bump_if_changed(block, before)


def propagate_from_block(block):
    contract = contract_of_block(block)
    recompute_contract_posture(contract)
    try_close_contract(contract)


def recompute_contract_posture(contract):
    before = snapshot(contract)
    blocks = blocks_of_contract(contract["id"])
    live = [b for b in blocks if b["status"] in LIVE_BLOCK_STATUSES]
    restricted = [b for b in live if b["status"] == "RESTRICTED"]
    if not live:
        posture = "AVAILABLE"
    elif len(restricted) == len(live):
        posture = "SOLD_OUT"
    elif len(restricted) >= 1:
        posture = "TIGHT"
    else:
        posture = "AVAILABLE"
    contract["block_posture"] = posture
    contract["contracted_room_nights"] = sum(
        b["block_size_rooms"]
        * day_span(parse_date(b["arrival_date"]), parse_date(b["departure_date"]))
        for b in blocks
        if b["status"] in COUNTED_BLOCK_STATUSES
    )
    bump_if_changed(contract, before)
    recompute_tournament_pressure(tournament_of_contract(contract))


def recompute_tournament_pressure(tournament):
    before = snapshot(tournament)
    counted = [
        c
        for c in contracts_of_tournament(tournament["id"])
        if c["status"] in ("EXECUTED", "CLOSED")
    ]
    executed = len(counted)
    sold_out = len([c for c in counted if c["block_posture"] == "SOLD_OUT"])
    tournament["executed_contract_count"] = executed
    tournament["sold_out_contract_count"] = sold_out
    if executed >= 1 and sold_out == executed:
        tournament["housing_pressure"] = "CONSTRAINED"
    else:
        tournament["housing_pressure"] = "NORMAL"
    bump_if_changed(tournament, before)


# ---------------------------------------------------------------------------
# Block release / settle, contract close, tournament settle
# ---------------------------------------------------------------------------

def release_block(block):
    block["rooms_released_unsold"] = block["block_size_rooms"] - block["rooms_committed"]
    block["rooms_available"] = 0
    block["status"] = "RELEASED"
    bump(block)
    propagate_from_block(block)


def try_settle_block(block):
    if block["status"] != "RELEASED":
        return
    bookings = [
        b for b in bookings_of_block(block["id"]) if b["booking_status"] != "CANCELLED"
    ]
    if not bookings:
        return
    for booking in bookings:
        if booking["rebate_status"] not in ("COLLECTED", "SHORT_PAID", "WRITTEN_OFF"):
            return
    block["status"] = "SETTLED"
    block["rooms_available"] = 0
    bump(block)
    propagate_from_block(block)


def try_close_contract(contract):
    if contract["status"] != "EXECUTED":
        return
    blocks = blocks_of_contract(contract["id"])
    if not blocks:
        return
    for block in blocks:
        if block["status"] != "SETTLED":
            return
    contract["status"] = "CLOSED"
    bump(contract)
    recompute_tournament_pressure(tournament_of_contract(contract))


def try_settle_tournament(tournament):
    if tournament["posture"] != "RECONCILING":
        return
    for invoice in invoices_of_tournament(tournament["id"]):
        if invoice["status"] not in ("PAID", "WRITTEN_OFF"):
            return
    distributions = distributions_of_tournament(tournament["id"])
    if not distributions:
        return
    for distribution in distributions:
        if distribution["status"] != "PAID":
            return
    tournament["posture"] = "SETTLED"
    bump(tournament)


def try_reconcile_tournament(tournament):
    if tournament["posture"] != "BOOKING_CLOSED":
        return
    tournament["posture"] = "RECONCILING"
    bump(tournament)


# ---------------------------------------------------------------------------
# Booking rebate line
# ---------------------------------------------------------------------------

def contract_total_checked_out_nights(contract_id):
    return sum(
        b["actualized_room_nights"]
        for b in bookings_of_contract(contract_id)
        if b["booking_status"] == "CHECKED_OUT"
    )


def booking_rebate_line(booking):
    contract = contract_of_booking(booking)
    total = contract_total_checked_out_nights(contract["id"])
    return calc.rebate_line_cents(contract, booking["actualized_room_nights"], total)


# ---------------------------------------------------------------------------
# Cancellation (direct, and as the supersede side effect)
# ---------------------------------------------------------------------------

def cancel_booking(booking, reason):
    previous_status = booking["booking_status"]
    days_out = calc.penalty_days_out(midnight(parse_date(booking["check_in_date"])), now())
    booking["penalty_room_nights"] = calc.penalty_room_nights(
        booking["projected_room_nights"], days_out
    )
    booking["penalty_cents"] = (
        booking["penalty_room_nights"]
        * contract_of_booking(booking)["negotiated_nightly_rate_cents"]
    )
    booking["booking_status"] = "CANCELLED"
    booking["cancellation_reason"] = reason
    booking["cancelled_at"] = now_iso()
    bump(booking)

    if previous_status in ("ROOMING_LIST_SUBMITTED", "CONFIRMED"):
        for entry in entries_of_booking(booking["id"]):
            del db.rooming_entries[entry["id"]]

    recompute_block_occupancy(block_of_booking(booking))
    recompute_registration(registration_of_booking(booking))


# ---------------------------------------------------------------------------
# Close-booking cascade (PRD 3.7)
# ---------------------------------------------------------------------------

def close_housing_window(tournament):
    tournament["posture"] = "BOOKING_CLOSED"
    bump(tournament)

    # Link 1 — re-evaluate every pending registration under the new posture.
    became_non_compliant = []
    for registration in registrations_of_tournament(tournament["id"]):
        if registration["status"] != "PENDING_HOUSING":
            continue
        recompute_registration(registration)
        if registration["status"] == "NON_COMPLIANT":
            became_non_compliant.append(registration)

    # Link 2 — the system denies every still-open request of those registrations.
    touched = []
    for registration in became_non_compliant:
        denied_any = False
        for request_row in requests_of_registration(registration["id"]):
            if request_row["status"] not in OPEN_EXCEPTION_STATUSES:
                continue
            request_row["status"] = "DENIED"
            request_row["decided_by_user_id"] = "SYSTEM_AUTO"
            request_row["decision_note"] = "closed without decision"
            bump(request_row)
            denied_any = True
        if denied_any:
            touched.append(registration)

    # Link 3 — re-derive each touched registration, whose exempt total changed.
    for registration in touched:
        recompute_registration(registration)

    # The same close sweeps eligible inventory.
    logical_now = now()
    for contract in contracts_of_tournament(tournament["id"]):
        if contract["status"] != "EXECUTED":
            continue
        for block in blocks_of_contract(contract["id"]):
            if block["status"] not in LIVE_BLOCK_STATUSES:
                continue
            deadline = parse_datetime(block["release_deadline"])
            if deadline is not None and logical_now >= deadline:
                release_block(block)


# ---------------------------------------------------------------------------
# Remit / write-off cascades (PRD 3.8)
# ---------------------------------------------------------------------------

def resolve_invoiced_bookings(contract, target_status):
    touched_blocks = []
    for booking in bookings_of_contract(contract["id"]):
        if booking["rebate_status"] != "INVOICED":
            continue
        booking["rebate_status"] = target_status
        bump(booking)
        touched_blocks.append(block_of_booking(booking))
    seen = set()
    for block in touched_blocks:
        if block["id"] in seen:
            continue
        seen.add(block["id"])
        try_settle_block(block)


# ---------------------------------------------------------------------------
# Scope helpers
# ---------------------------------------------------------------------------

def team_scope_registration(registration):
    """Reject a TeamManager acting outside its own team's registration scope."""
    if g.role == "TeamManager" and registration["team_id"] != g.user_id:
        raise ApiError(
            "ERR_TEAM_SCOPE_VIOLATION",
            "The acting team may only operate on its own registrations.",
        )


def hotel_scope_contract(contract):
    if g.role == "HotelRepresentative" and contract["hotel_id"] != g.user_id:
        raise ApiError(
            "ERR_HOTEL_SCOPE_VIOLATION",
            "The acting hotel may only operate on its own contracts.",
        )
