"""Forward side effects and the compensating writes that must reverse them exactly."""

from test_helpers import (
    assert_ledger,
    assert_money,
    assert_posture,
    assert_settlement,
    validate_success,
)
from test_helpers.constants import CLOCK_TEST_DATE, CLOCK_TEST_UTC, ELEMENT_NAME_LOW
from test_helpers.fixtures import (
    add_blocks,
    add_participant,
    clear_log,
    confirm_booking,
    create_booking,
    create_element,
    create_funded_client,
    defect_major_log,
    quote_booking,
    set_clock,
    staffed_course,
)
from test_helpers.test_users import PROGRAM_DIRECTOR, make_group_coordinator_headers

DEPOSIT_CENTS = 341
PAYMENT_CENTS = 20000


def _confirmed_booking_holding_a_deposit(api):
    """A confirmed two-block booking holding a 341-cent deposit against 20,000 cents of credit."""
    set_clock(api, CLOCK_TEST_UTC)
    world = staffed_course(api)
    gc_id = create_funded_client(api, amount_cents=PAYMENT_CENTS)
    b_id, _ = create_booking(api, world["course_id"], gc_id, 1)
    add_participant(api, gc_id, b_id, "ADULT")
    add_blocks(
        api,
        b_id,
        [
            (1, "ICEBREAKER", "2026-09-15T09:00:00Z", "2026-09-15T09:45:00Z"),
            (2, "DEBRIEF", "2026-09-15T09:45:00Z", "2026-09-15T10:15:00Z"),
        ],
    )
    quote_booking(api, b_id)
    confirmed = confirm_booking(api, gc_id, b_id)

    world.update(
        {
            "gc_id": gc_id,
            "gc_headers": make_group_coordinator_headers(gc_id),
            "b_id": b_id,
            "confirmed": confirmed,
        }
    )
    return world


class TestClientFundsAreConserved:
    """`payments_received_cents` always equals credit plus allocated plus retained."""

    def test_confirmation_moves_the_deposit_without_creating_or_destroying_money(self, api):
        """The forward half debits credit and allocates the identical amount.

        PRD 3.5: "`credit_balance_cents` is the client's unallocated funds and is
        always reconcilable as `payments_received_cents` less the sum of
        `deposit_allocated_cents` and the sum of `retained_cents` across all of
        that client's bookings."

        PRD 3.5: "On success the booking moves `QUOTED → CONFIRMED`, its
        `deposit_allocated_cents` is set to `deposit_required_cents`, the same
        amount is subtracted from the client's `credit_balance_cents` — the
        forward half of the client-funds identity — and both the booking's and the
        client's `version` increment."

        Design: Difficulty/compensating_invariant/client_funds_conserved_across_confirm_then_cancel
        """
        world = _confirmed_booking_holding_a_deposit(api)

        booking = world["confirmed"]
        assert booking["status"] == "CONFIRMED"
        assert_money(booking["deposit_required_cents"], DEPOSIT_CENTS, "deposit_required_cents")
        assert_money(booking["deposit_allocated_cents"], DEPOSIT_CENTS, "deposit_allocated_cents")
        assert_money(booking["retained_cents"], 0, "retained_cents")

        client = validate_success(api.get_group_client(world["gc_id"], PROGRAM_DIRECTOR))
        assert_ledger(client, credit=19659, payments=PAYMENT_CENTS)
        assert (
            client["credit_balance_cents"]
            + booking["deposit_allocated_cents"]
            + booking["retained_cents"]
            == client["payments_received_cents"]
        )

    def test_cancelling_at_thirty_six_days_notice_restores_the_whole_ledger(self, api):
        """The compensating half returns the deposit and zeroes the allocation.

        PRD 3.9: "Under `CLIENT_INITIATED`, a notice of 30 days or more forfeits
        nothing; a notice from 14 through 29 days forfeits 25 percent; a notice
        from 7 through 13 days forfeits 50 percent; and a notice of 6 days or
        fewer, including a negative notice, forfeits the whole deposit."

        PRD 3.9: "One reputational counter falls out of all this: a group client's
        `late_cancellation_count` is the number of its bookings that are
        `CANCELLED` with `cancellation_variant` `CLIENT_INITIATED` and a
        `notice_days_at_cancel` below fourteen days."

        Design: Difficulty/compensating_invariant/client_funds_conserved_across_confirm_then_cancel
        """
        world = _confirmed_booking_holding_a_deposit(api)

        cancelled = validate_success(
            api.cancel_booking(
                world["b_id"],
                {"reason": "Group cancelled well ahead of the program date"},
                world["gc_headers"],
            )
        )

        assert cancelled["status"] == "CANCELLED"
        assert_settlement(
            cancelled,
            variant="CLIENT_INITIATED",
            fee=0,
            refund=DEPOSIT_CENTS,
            retained=0,
            notice_days=36,
        )
        assert_money(cancelled["deposit_allocated_cents"], 0, "deposit_allocated_cents")

        client = validate_success(api.get_group_client(world["gc_id"], PROGRAM_DIRECTOR))
        assert_ledger(client, credit=PAYMENT_CENTS, payments=PAYMENT_CENTS)
        assert client["late_cancellation_count"] == 0


def _restricted_element_with_the_defect_cleared(api):
    """A restriction cascade in place, with a later CLEAR log ready for the countersignature.

    The major defect was filed by the staff facilitator, so the safety officer is
    the person who may countersign the return to service.
    """
    set_clock(api, CLOCK_TEST_UTC)
    world = staffed_course(api)
    l_id = create_element(
        api, world["course_id"], "LOW_ELEMENT", element_name=ELEMENT_NAME_LOW
    )
    gc_id = create_funded_client(api)
    b_id, _ = create_booking(api, world["course_id"], gc_id, 1)
    add_participant(api, gc_id, b_id, "ADULT")
    block_ids = add_blocks(
        api,
        b_id,
        [
            (1, "ICEBREAKER", "2026-09-15T09:00:00Z", "2026-09-15T09:45:00Z", None),
            (2, "LOW_ELEMENT", "2026-09-15T09:45:00Z", "2026-09-15T10:45:00Z", l_id),
            (3, "DEBRIEF", "2026-09-15T10:45:00Z", "2026-09-15T11:15:00Z", None),
        ],
    )
    quote_booking(api, b_id)
    confirm_booking(api, gc_id, b_id)

    defect_log = defect_major_log(
        api,
        l_id,
        world["f1_id"],
        world["f1_headers"],
        defect_note="Broken cable strand at the north anchor",
    )
    during = validate_success(api.get_course(world["course_id"], PROGRAM_DIRECTOR))
    clear_log(
        api,
        l_id,
        world["f1_id"],
        world["f1_headers"],
        defect_note="Cable strand replaced and re-tensioned",
    )

    world.update(
        {
            "l_id": l_id,
            "gc_id": gc_id,
            "b_id": b_id,
            "blk2_id": block_ids[1],
            "defect_log_id": defect_log["id"],
            "during": during,
        }
    )
    return world


class TestRestrictionCountersAreRestored:
    """Return to service must reverse every counter the restriction moved."""

    def test_the_course_counters_and_posture_return_to_their_opening_values(self, api):
        """Each derived counter that rose to one falls back to exactly zero.

        PRD 2.6: "Each cascade has a compensating half, and the counters are
        maintained symmetrically: returning an element to service decrements
        `restricted_element_count` or `out_of_service_element_count`, releases
        quarantined hardware rigged to it back to `IN_SERVICE`, walks its
        `BLOCKED_UNSAFE` blocks back to `SCHEDULED` in ascending `sequence_index`
        then `created_at` order, and returns any booking whose
        `blocked_block_count` has fallen back to zero from `AT_RISK` to
        `CONFIRMED` with a matching decrement of `at_risk_booking_count`."

        Design: Difficulty/compensating_invariant/restriction_counters_restored_by_return_to_service
        """
        world = _restricted_element_with_the_defect_cleared(api)

        assert world["during"]["restricted_element_count"] == 1
        assert world["during"]["at_risk_booking_count"] == 1

        validate_success(
            api.return_element_to_service(
                world["l_id"],
                {"note": "Anchor cable replaced; independent visual check by the safety officer"},
                world["so_headers"],
            )
        )

        course = validate_success(api.get_course(world["course_id"], PROGRAM_DIRECTOR))
        assert course["restricted_element_count"] == 0
        assert course["out_of_service_element_count"] == 0
        assert course["at_risk_booking_count"] == 0
        assert_posture(course, "OPEN", "NONE")

    def test_the_element_block_and_booking_rows_walk_back_together(self, api):
        """The element, its blocked block and the at-risk booking all reverse in one call.

        PRD 3.3: "On success the element's `restricting_log_id` is cleared,
        quarantined hardware rigged to it returns to `IN_SERVICE`, its
        `BLOCKED_UNSAFE` blocks walk back to `SCHEDULED`, bookings whose
        `blocked_block_count` has returned to zero move `AT_RISK → CONFIRMED`, and
        the course's counters, `posture`, `posture_reason` and `version` all
        settle per §2.6."

        PRD 3.3: "A `DEFECT_MAJOR` result against a `SERVICEABLE` element fires
        Cascade A of §2.6 in full and sets the log's `caused_restriction` to true,
        which is the flag that later identifies this log as the restriction's
        origin."

        Design: Difficulty/compensating_invariant/restriction_counters_restored_by_return_to_service
        """
        world = _restricted_element_with_the_defect_cleared(api)

        restored = validate_success(
            api.return_element_to_service(
                world["l_id"],
                {"note": "Anchor cable replaced; independent visual check by the safety officer"},
                world["so_headers"],
            )
        )

        assert restored["status"] == "SERVICEABLE"
        assert restored["restricting_log_id"] is None
        assert restored["last_clear_log_date"] == CLOCK_TEST_DATE

        block = validate_success(api.get_program_block(world["blk2_id"], PROGRAM_DIRECTOR))
        assert block["status"] == "SCHEDULED"

        booking = validate_success(api.get_booking(world["b_id"], PROGRAM_DIRECTOR))
        assert booking["status"] == "CONFIRMED"
        assert booking["blocked_block_count"] == 0

        defect_log = validate_success(
            api.get_operational_log(world["defect_log_id"], PROGRAM_DIRECTOR)
        )
        assert defect_log["caused_restriction"] is True
