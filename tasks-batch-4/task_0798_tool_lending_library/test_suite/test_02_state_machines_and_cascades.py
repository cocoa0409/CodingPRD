"""Non-linear state machines, transitive cascades, and conservation invariants.

Difficulty queue A: non_linear_state_machine, transitive_cascade,
compensating_invariant.
"""
from test_helpers import (
    create_member, create_item, add_copy, set_clock, checkout, return_loan,
    renew_loan, create_reservation, create_hold, create_ticket, resolve_ticket,
    first_fee_for_loan, waive_fee, get_member, get_item, get_copy, get_reservation,
    get_hold, get_loan,
    assert_same_instant, assert_item_partition, assert_member_ledger_conserved,
)


# =========================================================================== #
# Difficulty/non_linear_state_machine/loan_renewal_cycle_active_to_active
# =========================================================================== #
def _renewable_loan():
    member = create_member(tier="PLUS")
    item = create_item(name="Wrench", category="TOOL", replacement_value_cents=5000,
                       loan_period_days=7, daily_late_fee_cents=100, max_renewals=2)
    copy = add_copy(item["id"], asset_tag="W-1", acquired_on="2025-01-01T00:00:00Z")
    set_clock("2026-03-01T00:00:00Z")
    loan = checkout(member["id"], copy["id"], item["id"])
    return member, item, copy, loan


def test_first_renewal_advances_due_date_one_period(api):
    """One renewal keeps the loan ACTIVE and advances due_date by one period.

    PRD §3.4: "A renewal advances `due_date` by another `loan_period_days` and
    increments `renewals_used` by one."

    Design: Difficulty/non_linear_state_machine/loan_renewal_cycle_active_to_active
    """
    _m, _i, _c, loan = _renewable_loan()
    renewed = renew_loan(loan["id"])
    assert renewed["status"] == "ACTIVE"
    assert renewed["renewals_used"] == 1
    assert_same_instant(renewed["due_date"], "2026-03-15T00:00:00Z", "due_date after one renewal")


def test_two_renewals_cycle_active_to_active(api):
    """The ACTIVE -> ACTIVE cycle: two renewals leave renewals_used=2, due 03-22.

    PRD §3.4: "A loan may be renewed by the owning member, a volunteer, or a
    coordinator, forming a cyclic `ACTIVE → ACTIVE` loop that pushes the return
    date out. A renewal advances `due_date` by another `loan_period_days` and
    increments `renewals_used` by one."

    Design: Difficulty/non_linear_state_machine/loan_renewal_cycle_active_to_active
    """
    _m, _i, _c, loan = _renewable_loan()
    renew_loan(loan["id"])
    renewed = renew_loan(loan["id"])
    assert renewed["status"] == "ACTIVE"
    assert renewed["renewals_used"] == 2
    assert_same_instant(renewed["due_date"], "2026-03-22T00:00:00Z", "due_date after two renewals")


# =========================================================================== #
# Difficulty/non_linear_state_machine/itemcopy_parallel_axes_independence
# =========================================================================== #
def _minor_damage_returned_copy():
    member = create_member()
    item = create_item(name="Blender", category="KITCHEN", replacement_value_cents=8000,
                       loan_period_days=14, daily_late_fee_cents=50)
    copy = add_copy(item["id"], asset_tag="K-1", acquired_on="2025-06-01T00:00:00Z")
    set_clock("2026-03-01T00:00:00Z")
    loan = checkout(member["id"], copy["id"], item["id"])
    return_loan(loan["id"], "MINOR_DAMAGE")
    return member, item, copy


def test_minor_damage_copy_axes_diverge(api):
    """After MINOR_DAMAGE the two axes hold divergent values: AVAILABLE yet
    NEEDS_MAINTENANCE.

    PRD §2.6: "The two axes move separately: a copy returned with damage is set
    back to `AVAILABLE` on the availability axis yet `NEEDS_MAINTENANCE` on the
    condition axis, so it is not lendable until repaired."

    Design: Difficulty/non_linear_state_machine/itemcopy_parallel_axes_independence
    """
    _m, _i, copy = _minor_damage_returned_copy()
    got = get_copy(copy["id"])
    assert got["availability_status"] == "AVAILABLE"
    assert got["condition_status"] == "NEEDS_MAINTENANCE"


def test_minor_damage_excluded_from_available_count(api):
    """The damaged-but-available copy is excluded from available_copies_count and
    counted in maintenance_count.

    PRD §2.6: "`available_copies_count` is the number of copies that are
    simultaneously `AVAILABLE` on the availability axis and `GOOD` on the
    condition axis."
    PRD §2.6: "`maintenance_count` is the number of copies whose
    `condition_status` is either `NEEDS_MAINTENANCE` or `UNDER_MAINTENANCE`."

    Design: Difficulty/non_linear_state_machine/itemcopy_parallel_axes_independence
    """
    _m, item, _c = _minor_damage_returned_copy()
    got = get_item(item["id"])
    assert got["available_copies_count"] == 0
    assert got["maintenance_count"] == 1


# =========================================================================== #
# Difficulty/transitive_cascade/return_fee_suspends_member_cancels_reservation
# =========================================================================== #
def _cascade_world():
    member = create_member()
    item_a = create_item(name="Chainsaw", category="OUTDOOR", replacement_value_cents=12345,
                         loan_period_days=7, daily_late_fee_cents=100)
    copy_a = add_copy(item_a["id"], asset_tag="A-1", acquired_on="2024-03-01T00:00:00Z")
    item_b = create_item(name="Tent", category="OUTDOOR", replacement_value_cents=6000,
                         loan_period_days=7, daily_late_fee_cents=100)
    copy_b = add_copy(item_b["id"], asset_tag="B-1", acquired_on="2025-01-01T00:00:00Z")
    set_clock("2026-03-13T00:00:00Z")
    reservation = create_reservation(member["id"], item_b["id"],
                                     "2026-04-01T00:00:00Z", "2026-04-05T00:00:00Z")
    loan_a = checkout(member["id"], copy_a["id"], item_a["id"])
    return member, item_a, copy_a, item_b, copy_b, reservation, loan_a


def test_return_fee_suspends_member(api):
    """A 9875 REPLACEMENT fee pushes outstanding to the threshold and suspends the
    member.

    PRD §3.1: "Whenever a fee finalization — a loan return, an overdue accrual
    during housekeeping, or a replacement charge — pushes a member's
    `outstanding_balance_cents` to at least the suspension threshold of 2000
    cents, that member transitions from `ACTIVE` to `SUSPENDED`."

    Design: Difficulty/transitive_cascade/return_fee_suspends_member_cancels_reservation
    """
    member, _ia, _ca, _ib, _cb, _res, loan_a = _cascade_world()
    return_loan(loan_a["id"], "MAJOR_DAMAGE")
    got = get_member(member["id"])
    assert got["outstanding_balance_cents"] == 9875
    assert got["status"] == "SUSPENDED"


def test_suspension_cascade_cancels_reservation_and_releases_copy(api):
    """Suspension cascades: the member's PENDING reservation is CANCELLED and its
    copy is released back to AVAILABLE.

    PRD §3.1: "Suspension cascades: all of the member's `PENDING` reservations
    move to `CANCELLED`, each releasing its assigned copy from `RESERVED` back to
    `AVAILABLE` and triggering the item's count recomputation; and all of the
    member's `PENDING` and `PROMOTED` holds move to `EXPIRED`, with a `PROMOTED`
    hold additionally releasing its promoted copy back to `AVAILABLE`."

    Design: Difficulty/transitive_cascade/return_fee_suspends_member_cancels_reservation
    """
    _m, _ia, _ca, _ib, copy_b, reservation, loan_a = _cascade_world()
    return_loan(loan_a["id"], "MAJOR_DAMAGE")
    assert get_reservation(reservation["id"])["status"] == "CANCELLED"
    assert get_copy(copy_b["id"])["availability_status"] == "AVAILABLE"


# =========================================================================== #
# Difficulty/transitive_cascade/maintenance_return_promotes_waitlist_head
# =========================================================================== #
def _maintenance_promotion_world():
    m1 = create_member(name="Hal")
    m2 = create_member(name="Ivy")
    item = create_item(name="Router", category="TOOL", replacement_value_cents=9000,
                       loan_period_days=7, daily_late_fee_cents=100)
    copy = add_copy(item["id"], asset_tag="R-1", acquired_on="2025-01-01T00:00:00Z")
    set_clock("2026-03-01T00:00:00Z")
    ticket = create_ticket(copy["id"], reason="ROUTINE")  # immediate -> NEEDS_MAINTENANCE
    hold = create_hold(m2["id"], item["id"])
    return m1, m2, item, copy, ticket, hold


def test_maintenance_return_to_service_restores_copy(api):
    """RETURN_TO_SERVICE returns the copy to GOOD and — because it is promoted to a
    waitlisted hold — to RESERVED on the availability axis.

    PRD §3.8: "An outcome of `RETURN_TO_SERVICE` returns the copy to `GOOD` on the
    condition axis and `AVAILABLE` on the availability axis, recomputes the
    item's counts, and — because a serviceable copy just reappeared — may promote
    the next waiting hold."
    PRD §3.7: "Promoting a hold mints a new `Reservation` with `source`
    `WAITLIST_PROMOTION` that assigns the now-available copy (moving it from
    `AVAILABLE` to `RESERVED`), sets the hold's `claim_deadline` to the promotion
    instant plus the configured claim window, records the new reservation's
    identifier on the hold's `promoted_reservation_id`, and moves the hold to
    `PROMOTED`."

    Design: Difficulty/transitive_cascade/maintenance_return_promotes_waitlist_head
    """
    _m1, _m2, _item, copy, ticket, _hold = _maintenance_promotion_world()
    resolve_ticket(ticket["id"], "RETURN_TO_SERVICE")
    got = get_copy(copy["id"])
    assert got["condition_status"] == "GOOD"
    assert got["availability_status"] == "RESERVED"


def test_maintenance_return_promotes_waitlisted_hold(api):
    """The queue-head PENDING hold is promoted and gains a promoted_reservation_id.

    PRD §3.7: "Whenever a copy of the item becomes `AVAILABLE` — through a good
    checkin, a reservation cancel or expiry, a maintenance return-to-service, or
    a donation acceptance — the system considers the item's `PENDING` holds whose
    member is currently `ACTIVE`, and if that candidate set is non-empty it
    promotes the single earliest one ordered by `created_at` ascending; ..."
    PRD §3.7: "... records the new reservation's identifier on the hold's
    `promoted_reservation_id`, and moves the hold to `PROMOTED`."

    Design: Difficulty/transitive_cascade/maintenance_return_promotes_waitlist_head
    """
    _m1, _m2, _item, _copy, ticket, hold = _maintenance_promotion_world()
    resolve_ticket(ticket["id"], "RETURN_TO_SERVICE")
    got = get_hold(hold["id"])
    assert got["status"] == "PROMOTED"
    assert got["promoted_reservation_id"] is not None


# =========================================================================== #
# Difficulty/compensating_invariant/copy_partition_conserved_across_checkout_return
# =========================================================================== #
def test_copy_partition_conserved_while_on_loan(api):
    """Mid-cycle: the one copy is on_loan=1, available=0, partition conserved.

    PRD §2.6: "These counts obey a conservation invariant: for the serviceable
    pool, `available_copies_count` plus `reserved_count` plus `on_loan_count`
    plus `maintenance_count` always equals `serviceable_copies_count`."

    Design: Difficulty/compensating_invariant/copy_partition_conserved_across_checkout_return
    """
    member = create_member()
    item = create_item(name="Hoe", category="OUTDOOR", replacement_value_cents=3000,
                       loan_period_days=7, daily_late_fee_cents=100)
    copy = add_copy(item["id"], asset_tag="H-1", acquired_on="2025-01-01T00:00:00Z")
    set_clock("2026-03-01T00:00:00Z")
    checkout(member["id"], copy["id"], item["id"])
    got = get_item(item["id"])
    assert got["on_loan_count"] == 1
    assert got["available_copies_count"] == 0
    assert_item_partition(got)


def test_copy_partition_returns_to_available_after_good_return(api):
    """After a checkout + GOOD return the partition returns to available=1,
    on_loan=0 and remains conserved.

    PRD §2.6: "These counts obey a conservation invariant: for the serviceable
    pool, `available_copies_count` plus `reserved_count` plus `on_loan_count`
    plus `maintenance_count` always equals `serviceable_copies_count`."

    Design: Difficulty/compensating_invariant/copy_partition_conserved_across_checkout_return
    """
    member = create_member()
    item = create_item(name="Hoe", category="OUTDOOR", replacement_value_cents=3000,
                       loan_period_days=7, daily_late_fee_cents=100)
    copy = add_copy(item["id"], asset_tag="H-1", acquired_on="2025-01-01T00:00:00Z")
    set_clock("2026-03-01T00:00:00Z")
    loan = checkout(member["id"], copy["id"], item["id"])
    return_loan(loan["id"], "GOOD")
    got = get_item(item["id"])
    assert got["serviceable_copies_count"] == 1
    assert got["available_copies_count"] == 1
    assert got["on_loan_count"] == 0
    assert got["reserved_count"] == 0
    assert got["maintenance_count"] == 0
    assert_item_partition(got)


# =========================================================================== #
# Difficulty/compensating_invariant/member_ledger_conserved_across_assess_waive
# =========================================================================== #
def _assessed_damage_fee():
    member = create_member()
    item = create_item(name="Peeler", category="KITCHEN", replacement_value_cents=20000,
                       loan_period_days=14, daily_late_fee_cents=50)
    copy = add_copy(item["id"], asset_tag="PE-1", acquired_on="2025-06-01T00:00:00Z")
    set_clock("2026-03-13T00:00:00Z")
    loan = checkout(member["id"], copy["id"], item["id"])
    return_loan(loan["id"], "MINOR_DAMAGE")
    fee = first_fee_for_loan(loan["id"])
    return member, fee


def test_pending_damage_fee_counts_toward_outstanding_and_assessed(api):
    """Before waiving, a PENDING 1500 DAMAGE fee sits in both outstanding and
    assessed totals.

    PRD §2.7: "`outstanding_balance_cents` is the sum of `amount_cents` across
    the member's fees whose status is `ACCRUING` or `PENDING`."
    PRD §2.7: "`total_assessed_cents` is the lifetime sum of `amount_cents` across
    the member's **finalized** fees — those whose status is `PENDING`, `PAID`, or
    `WAIVED` ..."

    Design: Difficulty/compensating_invariant/member_ledger_conserved_across_assess_waive
    """
    member, fee = _assessed_damage_fee()
    assert fee["amount_cents"] == 1500
    got = get_member(member["id"])
    assert got["outstanding_balance_cents"] == 1500
    assert got["total_assessed_cents"] == 1500


def test_waive_conserves_assessed_moving_charge_to_waived(api):
    """Waiving the fee conserves total_assessed_cents while outstanding returns to
    0 and total_waived_cents holds the charge.

    PRD §3.9: "Only a `Coordinator` may waive a fee, optionally recording a
    `reason`; a waiver may act on an `ACCRUING` or `PENDING` fee, moves it to
    `WAIVED`, subtracts its `amount_cents` from the member's
    `outstanding_balance_cents`, and adds it to `total_waived_cents`."
    PRD §2.7: "The ledger is conserved: a member's `total_assessed_cents` always
    equals the sum of their still-outstanding finalized (`PENDING`) fees plus
    `total_paid_cents` plus `total_waived_cents`."

    Design: Difficulty/compensating_invariant/member_ledger_conserved_across_assess_waive
    """
    member, fee = _assessed_damage_fee()
    waived = waive_fee(fee["id"], reason="goodwill")
    assert waived["status"] == "WAIVED"
    got = get_member(member["id"])
    assert got["outstanding_balance_cents"] == 0
    assert got["total_waived_cents"] == 1500
    assert got["total_assessed_cents"] == 1500
    assert_member_ledger_conserved(got, outstanding_pending_cents=0)
