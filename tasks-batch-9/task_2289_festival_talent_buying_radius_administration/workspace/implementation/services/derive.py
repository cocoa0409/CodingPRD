"""Derived-field reconciliation and the four four-hop cascades (PRD 2.10)."""

from db import apply_changes, clock_now, db, iso_instant, new_row, touch
from services import calc
from validators import date_str, stored_date, stored_instant


# --------------------------------------------------------------------------- #
# aggregate re-derivations (no version bump; the caller decides)
# --------------------------------------------------------------------------- #
def recompute_tier(tier):
    committed = 0
    slots = 0
    for booking in calc.tier_bookings(tier["id"]):
        if booking["contract_status"] == "CANCELLED":
            continue
        committed += booking["guarantee_cents"] + booking["production_fee_cents"]
        slots += 1
    allocation = tier["allocation_cents"]
    closed = slots >= tier["max_slots"] or (
        committed >= allocation and (allocation > 0 or committed > 0)
    )
    return apply_changes(
        tier,
        {
            "committed_cents": committed,
            "slots_committed": slots,
            "status": "CLOSED" if closed else "OPEN",
        },
    )


def recompute_stage(stage):
    minutes = 0
    for booking in calc.stage_bookings(stage["id"]):
        if booking["contract_status"] == "CANCELLED":
            continue
        minutes += booking["set_length_minutes"]
    return apply_changes(stage, {"booked_minutes": minutes})


def recompute_festival(festival):
    tiers = calc.festival_tiers(festival["id"])
    committed = sum(t["committed_cents"] for t in tiers)
    anchors = 0
    for booking in calc.festival_bookings(festival["id"]):
        if booking["contract_status"] == "CANCELLED":
            continue
        tier = db.budget_tiers.get(booking["budget_tier_id"])
        if tier is not None and tier["tier_code"] == "HEADLINER":
            anchors += 1
    changed = apply_changes(
        festival,
        {"committed_budget_cents": committed, "headliner_anchor_count": anchors},
    )
    posture = calc.lineup_posture(festival)
    changed = apply_changes(festival, {"lineup_posture": posture}) or changed
    return changed


def recompute_artist(artist):
    parts = calc.risk_components(artist)
    return apply_changes(
        artist,
        {
            "reported_conflict_count": parts["reported_conflict_count"],
            "radius_breach_count": parts["radius_breach_count"],
            "strict_risk_score": parts["strict_risk_score"],
            "adjudicated_risk_score": parts["adjudicated_risk_score"],
        },
    )


def recompute_wave(wave):
    assignments = 0
    headliners = 0
    for booking in db.bookings.values():
        if booking["announcement_wave_id"] != wave["id"]:
            continue
        if booking["contract_status"] == "CANCELLED":
            continue
        assignments += 1
        if booking["billing_position"] == 1:
            headliners += 1
    changes = {"assignment_count": assignments, "headliner_count": headliners}
    if assignments == 0 and wave["status"] == "LOCKED":
        changes["status"] = "PLANNED"
        changes["headliner_count"] = 0
    return apply_changes(wave, changes)


def recompute_deposit_paid(booking):
    total = 0
    for row in calc.booking_installments(booking["id"]):
        if row["installment_type"] != "DEPOSIT":
            continue
        if row["status"] in ("PAID", "CLAWBACK_PENDING", "RECOVERED"):
            total += row["paid_amount_cents"]
    return total


def recompute_booking_money(booking):
    """Rider totals, deposit ledger, settlement figure and recovery replay."""
    totals = calc.rider_totals(booking["id"])
    changed = apply_changes(
        booking,
        {
            "rider_proposed_cents": totals["proposed_scope_cents"],
            "rider_estimate_cents": totals["contracted_scope_cents"],
            "deposit_paid_cents": recompute_deposit_paid(booking),
        },
    )
    breakdown = calc.settlement_breakdown(booking)
    changed = (
        apply_changes(
            booking,
            {"settlement_total_cents": breakdown["settlement_total_cents"]},
        )
        or changed
    )
    changed = (
        apply_changes(booking, {"actual_recovered_cents": calc.actual_recovered(booking)})
        or changed
    )
    return changed


def reconcile_ledgers(booking):
    """Tier, stage and festival re-derivation after a booking ledger moves."""
    tier = db.budget_tiers.get(booking["budget_tier_id"])
    previous_tier_status = tier["status"] if tier else None
    if tier is not None and recompute_tier(tier):
        touch(tier)
    stage = db.stages.get(booking["stage_id"])
    if stage is not None and recompute_stage(stage):
        touch(stage)
    festival = db.festivals.get(booking["festival_id"])
    if festival is not None and recompute_festival(festival):
        touch(festival)
    return previous_tier_status, tier


def release_clause(clause):
    if clause is not None and clause["enforcement_status"] != "RELEASED":
        clause["enforcement_status"] = "RELEASED"
        touch(clause)


# --------------------------------------------------------------------------- #
# CASCADE-1: acceptance / the commitment cascade
# --------------------------------------------------------------------------- #
def cascade_accept(offer, festival, tier, stage):
    now = clock_now()

    # hop one - the offer closes and the booking is written
    offer["status"] = "ACCEPTED"
    touch(offer)

    booking = new_row(
        festival_id=offer["festival_id"],
        artist_id=offer["artist_id"],
        offer_id=offer["id"],
        budget_tier_id=offer["budget_tier_id"],
        stage_id=offer["stage_id"],
        replaces_booking_id=offer["replaces_booking_id"],
        announcement_wave_id=None,
        reveal_order=None,
        guarantee_cents=offer["guarantee_cents"],
        production_fee_cents=offer["production_fee_cents"],
        billing_position=offer["billing_position"],
        set_length_minutes=offer["set_length_minutes"],
        slot_start_utc=offer["slot_start_utc"],
        slot_end_utc=offer["slot_end_utc"],
        contract_status="PENDING_RIDER",
        settlement_status="UNFUNDED",
        rider_proposed_cents=0,
        rider_estimate_cents=0,
        settlement_total_cents=0,
        deposit_paid_cents=0,
        cancelled_at=None,
        cancellation_reason=None,
        cancelling_party=None,
        contractual_recovery_cents=0,
        actual_recovered_cents=0,
    )
    db.bookings[booking["id"]] = booking

    clause = calc.clause_for_offer(offer["id"])
    if clause is not None:
        changes = {"booking_id": booking["id"]}
        if clause["enforcement_status"] == "PROVISIONAL":
            changes["enforcement_status"] = "ACTIVE"
        if apply_changes(clause, changes):
            touch(clause)

    # hops two and three - ledgers debited, dependants re-derived
    previous_tier_status, tier_row = reconcile_ledgers(booking)

    # hop four - a tier that just closed clears the table
    if previous_tier_status == "OPEN" and tier_row is not None and tier_row["status"] == "CLOSED":
        for sibling in list(db.offers.values()):
            if sibling["budget_tier_id"] != tier_row["id"]:
                continue
            if sibling["id"] == offer["id"]:
                continue
            if sibling["status"] not in ("DRAFT", "ISSUED", "COUNTERED"):
                continue
            sibling["status"] = "SUPERSEDED"
            touch(sibling)
            release_clause(calc.clause_for_offer(sibling["id"]))

    # the money schedule
    schedule = calc.payment_schedule(booking, festival, now)
    deposit = new_row(
        booking_id=booking["id"],
        installment_type="DEPOSIT",
        sequence_index=1,
        amount_cents=schedule["deposit_cents"],
        due_date=date_str(schedule["deposit_due_date"]),
        status="SCHEDULED",
        released_at=None,
        paid_at=None,
        paid_amount_cents=0,
        recovered_cents=0,
    )
    balance = new_row(
        booking_id=booking["id"],
        installment_type="BALANCE",
        sequence_index=2,
        amount_cents=schedule["balance_cents"],
        due_date=date_str(schedule["balance_due_date"]),
        status="SCHEDULED",
        released_at=None,
        paid_at=None,
        paid_amount_cents=0,
        recovered_cents=0,
    )
    db.payment_installments[deposit["id"]] = deposit
    db.payment_installments[balance["id"]] = balance

    recompute_booking_money(booking)
    booking["version"] = 1
    booking["updated_at"] = booking["created_at"]
    return booking


# --------------------------------------------------------------------------- #
# CASCADE-2: cancellation / the compensating cascade
# --------------------------------------------------------------------------- #
def cascade_cancel(booking, festival, cancelling_party, cancellation_reason):
    now = clock_now()

    # hop one
    booking["contract_status"] = "CANCELLED"
    booking["cancelled_at"] = iso_instant(now)
    booking["cancellation_reason"] = cancellation_reason
    booking["cancelling_party"] = cancelling_party
    booking["contractual_recovery_cents"] = calc.contractual_recovery(
        booking, festival, now, cancelling_party
    )

    # hop two
    clawback_pending = False
    for row in calc.booking_installments(booking["id"]):
        if row["status"] in ("SCHEDULED", "HELD", "RELEASED"):
            row["status"] = "VOIDED"
            touch(row)
        elif row["status"] == "PAID":
            row["status"] = "CLAWBACK_PENDING"
            touch(row)
            clawback_pending = True
        elif row["status"] == "CLAWBACK_PENDING":
            clawback_pending = True
    release_clause(calc.clause_for_booking(booking["id"]))

    # hop three
    if clawback_pending:
        booking["settlement_status"] = "RECOVERY_PENDING"
    else:
        booking["settlement_status"] = "RECOVERED"
        booking["actual_recovered_cents"] = 0
    recompute_booking_money(booking)
    if not clawback_pending:
        booking["actual_recovered_cents"] = 0

    # hop four removes the booking from its announcement wave
    wave = db.announcement_waves.get(booking["announcement_wave_id"])
    booking["announcement_wave_id"] = None
    touch(booking)
    reconcile_ledgers(booking)

    if wave is not None and recompute_wave(wave):
        touch(wave)
    return booking


# --------------------------------------------------------------------------- #
# CASCADE-3: adjudicated violation / the enforcement cascade
# --------------------------------------------------------------------------- #
def cascade_violation(performance, clause):
    # hop one
    performance["status"] = "VIOLATION"
    touch(performance)
    artist = db.artists.get(performance["artist_id"])
    if artist is not None and recompute_artist(artist):
        touch(artist)

    # hop two
    clause["enforcement_status"] = "BREACHED"
    clause["breach_count"] = clause["breach_count"] + 1
    touch(clause)

    # hops three and four
    booking = db.bookings.get(clause["booking_id"])
    if booking is not None:
        for row in calc.booking_installments(booking["id"]):
            if row["status"] == "SCHEDULED":
                row["status"] = "HELD"
                touch(row)
        if booking["settlement_status"] in ("UNFUNDED", "DEPOSIT_PAID", "BALANCE_DUE"):
            booking["settlement_status"] = "WITHHELD"
            recompute_booking_money(booking)
            touch(booking)


# --------------------------------------------------------------------------- #
# CASCADE-4: granted waiver / the compensating cascade for enforcement
# --------------------------------------------------------------------------- #
def derived_settlement_status(booking):
    deposit_paid = False
    balance_paid = False
    balance_released = False
    for row in calc.booking_installments(booking["id"]):
        if row["installment_type"] == "DEPOSIT" and row["status"] == "PAID":
            deposit_paid = True
        if row["installment_type"] == "BALANCE":
            if row["status"] == "PAID":
                balance_paid = True
            if row["status"] == "RELEASED":
                balance_released = True
    if deposit_paid and balance_paid:
        return "SETTLED"
    if balance_released:
        return "BALANCE_DUE"
    if deposit_paid:
        return "DEPOSIT_PAID"
    return "UNFUNDED"


def cascade_waiver_granted(clause, waiver_fee_cents):
    # hop one
    clause["waiver_status"] = "GRANTED"
    clause["enforcement_status"] = "WAIVED"
    clause["waiver_fee_cents"] = waiver_fee_cents
    touch(clause)

    # hop two
    performance = db.competing_performances.get(clause["waiver_competing_performance_id"])
    if performance is not None and performance["status"] == "VIOLATION":
        performance["status"] = "WAIVED"
        touch(performance)
        artist = db.artists.get(performance["artist_id"])
        if artist is not None and recompute_artist(artist):
            touch(artist)

    # hops three and four
    booking = db.bookings.get(clause["booking_id"])
    if booking is not None:
        for row in calc.booking_installments(booking["id"]):
            if row["status"] == "HELD":
                row["status"] = "SCHEDULED"
                touch(row)
        changed = False
        if booking["settlement_status"] == "WITHHELD":
            booking["settlement_status"] = derived_settlement_status(booking)
            changed = True
        changed = recompute_booking_money(booking) or changed
        if changed:
            touch(booking)


# --------------------------------------------------------------------------- #
# installment rebuild for a guarantee amendment (PRD 3.8)
# --------------------------------------------------------------------------- #
def rebuild_schedule(booking, festival):
    rows = calc.booking_installments(booking["id"])
    scheduled = [r for r in rows if r["status"] == "SCHEDULED"]
    kept_sum = sum(
        r["amount_cents"]
        for r in rows
        if r["status"] not in ("VOIDED", "SCHEDULED")
    )
    rebuild_types = set(r["installment_type"] for r in scheduled)
    for row in scheduled:
        row["status"] = "VOIDED"
        touch(row)

    schedule = calc.payment_schedule(booking, festival, clock_now())
    remaining = booking["guarantee_cents"] - kept_sum
    if not rebuild_types:
        # Nothing was scheduled, yet the guarantee moved: a single balance row
        # absorbs the difference so installment_total_conservation still holds.
        if remaining == 0:
            return
        rebuild_types = {"BALANCE"}
    amounts = {}
    if "DEPOSIT" in rebuild_types and "BALANCE" in rebuild_types:
        amounts["DEPOSIT"] = schedule["deposit_cents"]
        amounts["BALANCE"] = remaining - schedule["deposit_cents"]
    elif "DEPOSIT" in rebuild_types:
        amounts["DEPOSIT"] = remaining
    else:
        amounts["BALANCE"] = remaining

    for kind in ("DEPOSIT", "BALANCE"):
        if kind not in amounts:
            continue
        due = (
            schedule["deposit_due_date"]
            if kind == "DEPOSIT"
            else schedule["balance_due_date"]
        )
        row = new_row(
            booking_id=booking["id"],
            installment_type=kind,
            sequence_index=1 if kind == "DEPOSIT" else 2,
            amount_cents=amounts[kind],
            due_date=date_str(due),
            status="SCHEDULED",
            released_at=None,
            paid_at=None,
            paid_amount_cents=0,
            recovered_cents=0,
        )
        db.payment_installments[row["id"]] = row
