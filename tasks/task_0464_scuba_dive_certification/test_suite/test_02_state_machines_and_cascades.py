"""Non-linear state machines (ELIGIBLE<->ACTIVE revert cycle, rental
RETURNED-vs-VOIDED fork) and transitive cascades (session-cancel depth-3,
rental-checkin depth-2 to the diver ledger).

Queue A (Difficulty): non_linear_state_machine, transitive_cascade.
"""
from test_helpers import (
    validate_success, get_success_data,
    make_shop_admin_headers,
    create_diver, create_rental, set_clock,
    setup_eligible_enrollment,
)

ADMIN = make_shop_admin_headers()


class TestEnrollmentRevertCycle:
    def test_eligible_reverts_to_active_when_session_cancelled(self, api):
        """PRD 3.3: "if an enrollment is `ELIGIBLE` and at least one eligibility
        precondition no longer holds — for instance because a previously attended
        session was cancelled, dropping an attendance counter, or because the
        diver's waiver has expired — the enrollment reverts `ELIGIBLE → ACTIVE`
        and its `completion_pct` recomputes to a value below 100."
        PRD 3.4: "For each cancelled booking that had been `ATTENDED`, the owning
        enrollment's matching attendance counter ... is decremented and its
        `completion_pct` is recomputed; and if that enrollment had been `ELIGIBLE`
        but now fails a prerequisite, it reverts `ELIGIBLE → ACTIVE`."

        Design: Difficulty/non_linear_state_machine/enrollment_active_eligible_revert_cycle
        """
        diver, course, instructor, enr, session, booking = setup_eligible_enrollment()
        assert enr["status"] == "ELIGIBLE", enr  # A -> B reached

        validate_success(api.cancel_session(session["id"], ADMIN))
        reverted = get_success_data(api.get_enrollment(enr["id"], ADMIN))
        # B -> A revert: ADVANCED course requires 1 OW; e-learning still 100.
        assert reverted["status"] == "ACTIVE", reverted
        assert reverted["open_water_sessions_attended"] == 0, reverted
        # raw = 0.2*100 + 0.3*100 (no pool required => frac 1) + 0.5*0 = 50
        assert reverted["completion_pct"] == 50, reverted

    def test_rental_active_forks_returned_vs_voided(self, api):
        """PRD 3.8: "Check-in drives the agreement `ACTIVE → RETURNED`, stamps
        `actual_return_at` from the logical clock, and finalizes the charge as
        `actual_cost_cents`."
        PRD 3.8: "Voiding drives the agreement `ACTIVE → VOIDED`, sets
        `actual_cost_cents` to 0 and `deposit_refund_cents` to the full
        `deposit_cents`, and cascades to recompute the renter's
        `deposit_on_hold_cents`, fully reversing the checkout debit."
        PRD 3.8: "the `deposit_refund_cents` is the `deposit_cents` minus that
        overage, floored at zero."

        Design: Difficulty/non_linear_state_machine/rental_branching_returned_vs_voided
        """
        set_clock("2026-06-10T09:00:00Z")
        diver = create_diver(full_name="Ronan Rent")
        rental_void = create_rental(
            diver["id"], item_description="Wetsuit",
            daily_rate_cents=4500, deposit_cents=20000,
            scheduled_return_at="2026-06-12T09:00:00Z",
        )
        rental_return = create_rental(
            diver["id"], item_description="Fins",
            daily_rate_cents=4500, deposit_cents=20000,
            scheduled_return_at="2026-06-12T09:00:00Z",
        )
        # VOID branch: must occur while clock == checkout_at.
        voided = validate_success(api.void_rental_agreement(rental_void["id"], ADMIN))
        assert voided["status"] == "VOIDED", voided
        assert voided["actual_cost_cents"] == 0, voided
        assert voided["deposit_refund_cents"] == 20000, voided

        # RETURNED branch: late return -> actual charge + settlement.
        set_clock("2026-06-13T15:00:00Z")
        returned = validate_success(
            api.checkin_rental_agreement(rental_return["id"], {}, ADMIN)
        )
        assert returned["status"] == "RETURNED", returned
        assert returned["actual_cost_cents"] == 22500, returned
        # est 9000, actual 22500 -> overage 13500; refund max(0, 20000-13500)=6500
        assert returned["deposit_refund_cents"] == 6500, returned


class TestTransitiveCascades:
    def test_session_cancel_cascades_depth3_to_enrollment(self, api):
        """PRD 3.4: "Cancellation triggers a three-level cascade. Every booking on
        the session whose status is `BOOKED` or `ATTENDED` is moved to `CANCELLED`,
        and the session's `confirmed_seats` is driven to 0."
        PRD 3.4: "For each cancelled booking that had been `ATTENDED`, the owning
        enrollment's matching attendance counter ... is decremented and its
        `completion_pct` is recomputed; and if that enrollment had been `ELIGIBLE`
        but now fails a prerequisite, it reverts `ELIGIBLE → ACTIVE`."

        Design: Difficulty/transitive_cascade/session_cancel_cascade_depth3_to_enrollment
        """
        diver, course, instructor, enr, session, booking = setup_eligible_enrollment()
        assert enr["status"] == "ELIGIBLE", enr

        cancelled_session = validate_success(api.cancel_session(session["id"], ADMIN))
        assert cancelled_session["status"] == "CANCELLED", cancelled_session

        booking_after = get_success_data(api.get_session_booking(booking["id"], ADMIN))
        assert booking_after["status"] == "CANCELLED", booking_after  # hop 2

        enr_after = get_success_data(api.get_enrollment(enr["id"], ADMIN))
        assert enr_after["open_water_sessions_attended"] == 0, enr_after  # hop 3
        assert enr_after["status"] == "ACTIVE", enr_after

    def test_rental_checkin_cascades_depth2_to_diver_ledger(self, api):
        """PRD 2.5: "A `Diver` tracks `deposit_on_hold_cents`, defined as the sum
        of `deposit_cents` across that diver's rental agreements whose status is
        `ACTIVE`; this ledger is recomputed on every rental checkout, check-in, and
        void so that money debited at checkout is restored exactly when the gear is
        returned or the rental is voided."
        PRD 3.8: "Check-in then cascades to recompute the renter's
        `deposit_on_hold_cents` (now that this rental has left `ACTIVE`, its deposit
        is no longer held), restoring the money-conservation invariant."

        Design: Difficulty/transitive_cascade/rental_checkin_cascade_depth2_to_diver_ledger
        """
        set_clock("2026-06-10T09:00:00Z")
        diver = create_diver(full_name="Dana Deposit")
        rental = create_rental(
            diver["id"], item_description="Reg set",
            daily_rate_cents=4500, deposit_cents=20000,
            scheduled_return_at="2026-06-12T09:00:00Z",
        )
        held = get_success_data(api.get_diver(diver["id"], ADMIN))
        assert held["deposit_on_hold_cents"] == 20000, held  # debit applied at checkout

        returned = validate_success(
            api.checkin_rental_agreement(rental["id"], {}, ADMIN)
        )
        assert returned["status"] == "RETURNED", returned  # hop 1
        diver_after = get_success_data(api.get_diver(diver["id"], ADMIN))
        assert diver_after["deposit_on_hold_cents"] == 0, diver_after  # hop 2
