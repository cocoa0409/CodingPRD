"""Cancelling an approved enrollment restores the programme budget exactly."""

from prd_bench_local_runner.testing import validate_error

from test_helpers import (
    ERR_INVALID_STATE,
    PROGRAM_TYPE_GRANT,
    advance_cycle,
    assert_award,
    assert_cents,
    assert_program_capacity,
    cancel_enrollment,
    create_parcel,
    create_program,
    enroll,
    get_enrollment,
    get_program,
    open_cycle,
    reason_payload,
)
from test_helpers.test_users import PROGRAM_ADMIN_HEADERS, make_property_owner_headers


def _one_slot_grant_world(client):
    """A single-slot grant programme with one approved and one waitlisted owner.

    The hardship parcel enrols first against a 191667-cent invoice and is
    approved for 126500, taking the only slot and leaving 373500.  The second
    parcel claims 100000 cents and is waitlisted at position 1, reserving nothing.
    """
    cycle = open_cycle(client)
    program = create_program(
        client,
        cycle["id"],
        PROGRAM_TYPE_GRANT,
        budget_total_cents=500000,
        capacity_slots=1,
        service_window_start_utc="2026-08-01T00:00:00Z",
        service_window_end_utc="2026-12-01T00:00:00Z",
    )
    hardship = create_parcel(client, owner_hardship_flag=True)
    standard = create_parcel(client, owner_hardship_flag=False)

    approved = enroll(
        client,
        program["id"],
        hardship["id"],
        program["version"],
        vendor_invoice_cents=191667,
    )
    waitlisted = enroll(
        client,
        program["id"],
        standard["id"],
        get_program(client, program["id"])["version"],
        vendor_invoice_cents=100000,
    )
    return {
        "cycle": cycle,
        "program": program,
        "hardship": hardship,
        "standard": standard,
        "approved": approved,
        "waitlisted": waitlisted,
    }


class TestEnrollmentCancelCompensation:
    """The credit returns the budget to its pre-approval value, once and only once."""

    def test_cancel_credits_the_budget_and_frees_the_slot(self, client):
        """The approved row releases its reservation while keeping its award for
        audit, and the waitlisted row - which reserved nothing - credits nothing.

        PRD: "From APPROVED it exactly compensates the approval:
        reserved_amount_cents is zeroed, the program's budget_remaining_cents is
        credited back by the previously reserved amount so it returns to precisely
        its pre-approval value, reserved_slots is decremented by 1, and both
        version counters advance."

        PRD: "From WAITLISTED there is nothing to compensate -
        budget_remaining_cents and reserved_slots are left untouched because nothing was
        ever reserved - but the remaining waitlisted enrollments on that program are
        renumbered from 1 in created_at ascending order, and the enrollment's version
        advances by 1."

        PRD: "A waitlisted enrollment sets reserved_amount_cents to 0, takes a
        waitlist_position of one more than the count of enrollments already
        waitlisted on that program, and leaves both budget_remaining_cents and
        reserved_slots untouched."

        PRD: "COMPLETED, NO_SHOW, REIMBURSED and CANCELLED are all terminal."

        Design: Difficulty/compensating_invariant/support_program_budget_restored_on_enrollment_cancel
        """
        world = _one_slot_grant_world(client)
        program_id = world["program"]["id"]
        assert_cents(world["program"]["budget_remaining_cents"], 500000)

        assert world["approved"]["status"] == "APPROVED"
        assert_award(world["approved"], 115000, 0.10, 11500, 126500, reserved=126500)
        assert world["waitlisted"]["status"] == "WAITLISTED"
        assert_cents(world["waitlisted"]["reserved_amount_cents"], 0)
        assert world["waitlisted"]["waitlist_position"] == 1
        assert_program_capacity(
            get_program(client, program_id), 373500, reserved_slots=1
        )

        cancelled = cancel_enrollment(
            client,
            world["approved"]["id"],
            headers=make_property_owner_headers(world["hardship"]["id"]),
            reason="owner withdrew the cost-share request",
        )
        assert cancelled["status"] == "CANCELLED"
        assert_cents(cancelled["reserved_amount_cents"], 0)
        assert_cents(cancelled["award_cents"], 126500)
        assert_program_capacity(
            get_program(client, program_id), 500000, reserved_slots=0
        )

        # The cancel itself promotes nobody.
        still_waiting = get_enrollment(client, world["waitlisted"]["id"])
        assert still_waiting["status"] == "WAITLISTED"
        assert still_waiting["waitlist_position"] == 1

        # And cancelling the waitlisted row moves neither counter.
        cancel_enrollment(client, world["waitlisted"]["id"])
        assert_program_capacity(
            get_program(client, program_id), 500000, reserved_slots=0
        )

        # The credit cannot be applied twice.
        validate_error(
            client.cancel_enrollment(
                world["approved"]["id"],
                headers=PROGRAM_ADMIN_HEADERS,
                payload=reason_payload("second attempt"),
            ),
            ERR_INVALID_STATE,
        )
        assert_program_capacity(
            get_program(client, program_id), 500000, reserved_slots=0
        )

    def test_the_restored_budget_is_spendable_by_the_waitlist_promotion(self, client):
        """A cycle advance after the cancel promotes the waitlisted owner and
        re-debits a different amount, 60000 rather than the 126500 released.

        PRD: "For each program in the advancing cycle, the earliest remaining
        waitlisted enrollment by created_at ascending that still fits both an
        unused slot and - for a grant - enough remaining budget for its full
        award_cents is promoted WAITLISTED -> APPROVED: its reserved_amount_cents
        becomes its award_cents, its waitlist_position is cleared to null, the
        program's budget_remaining_cents is debited and its reserved_slots
        incremented, and both the enrollment's and the program's version advance
        by 1."

        PRD: "where the flag is false the bonus is exactly 0."

        Design: Difficulty/compensating_invariant/support_program_budget_restored_on_enrollment_cancel
        """
        world = _one_slot_grant_world(client)
        program_id = world["program"]["id"]

        cancel_enrollment(
            client,
            world["approved"]["id"],
            headers=make_property_owner_headers(world["hardship"]["id"]),
            reason="owner withdrew the cost-share request",
        )
        assert_program_capacity(
            get_program(client, program_id), 500000, reserved_slots=0
        )

        advance_cycle(client, world["cycle"]["id"])

        promoted = get_enrollment(client, world["waitlisted"]["id"])
        assert promoted["status"] == "APPROVED"
        assert promoted["waitlist_position"] is None
        assert_award(promoted, 60000, 0.10, 0, 60000, reserved=60000)
        assert_program_capacity(
            get_program(client, program_id), 440000, reserved_slots=1
        )
