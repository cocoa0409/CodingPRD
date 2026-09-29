"""Rejection-precedence pairs: which of two simultaneously violated rules answers.

Both pairs assert an ordering the PRD commits to explicitly in its ascending
precedence list, so the precedence itself is asserted rather than softened into
``validate_error_is_one_of``:

* an addressed row's own state precondition (level 8) outranks the fiscal
  reserve-sufficiency check (level 17) on dividend execution;
* slot-window temporal validity (level 13) outranks contact interval overlap
  (level 14) on meeting-request creation.
"""

from test_helpers import (
    ApiClient,
    ApiErrorId,
    IR_ADMIN,
    TRANSFER_AGENT,
    assertions,
    fixtures,
    validate_error,
)

CLOCK_START = "2026-08-01T00:00:00Z"
CLOCK_PAYABLE = "2026-08-25T00:00:00Z"


def _build_short_reserve_dividend(api: ApiClient):
    """An issuer with a 100-cent reserve and a 500,000-cent dividend still SUBMITTED."""
    fixtures.set_clock(api, CLOCK_START)
    company = fixtures.create_company(
        api,
        ticker="SHT",
        legal_name="Short Reserve Corp",
        shares_outstanding=1000000,
        dividend_reserve_cents=100,
    )
    holder = fixtures.create_holder(
        api,
        company["id"],
        1000,
        display_name="Short Holder",
        email="sht@funds.test",
    )
    instruction = fixtures.submit_dividend(
        api,
        company["id"],
        record_date="2026-08-15",
        payable_date="2026-08-25",
        declared_rate_cents_per_share=500,
        funding_mode="DECLARED_RATE",
        headers=IR_ADMIN,
    )
    fixtures.set_clock(api, CLOCK_PAYABLE)
    return company, holder, instruction


class TestExecuteStateOutranksReserveShortfall:
    """Level-8 state versus level-17 fiscal on POST /{id}/execute."""

    def test_execute_on_submitted_instruction_answers_with_state_not_reserve(
        self, api: ApiClient
    ):
        """One call violates both the state and the fiscal rule; state answers.

        PRD §2.10: "Checks therefore run in a fixed order, and the **first** check to
        fail decides the response; later checks are never reached."
        PRD §2.10: "8. The addressed resource's own state precondition for the requested
        transition."
        PRD §2.10: "17. Fiscal checks — instruction payability and reserve sufficiency,
        evaluated last of all."
        PRD §3.9: "Five preconditions guard it, and per §2.10 they are evaluated in the
        precedence order given there."
        PRD §3.9: "The instruction must be in `ACKNOWLEDGED`, or execution is refused
        with `ERR_INSTRUCTION_NOT_ACKNOWLEDGED`."

        Design: Difficulty/priority_pair_validation_conflict/execute_state_check_outranks_dividend_reserve_shortfall
        """
        company, holder, instruction = _build_short_reserve_dividend(api)

        response = api.execute_instruction(instruction["id"], TRANSFER_AGENT)
        validate_error(response, ApiErrorId.INSTRUCTION_NOT_ACKNOWLEDGED.value)

        stored = fixtures.read_instruction(api, instruction["id"])
        assertions.assert_instruction(
            stored,
            status="SUBMITTED",
            total_payout_cents=None,
            payout_ledger=None,
            executed_at=None,
            executed_by_user_id=None,
        )
        assertions.assert_version(stored, 1, "TransferAgentInstruction")

    def test_reserve_shortfall_surfaces_only_once_the_instruction_is_acknowledged(
        self, api: ApiClient
    ):
        """With the state precondition satisfied the fiscal check finally decides.

        PRD §3.9: "And the payout total computed below must not exceed the issuer's
        `dividend_reserve_cents`, or it is refused with
        `ERR_DIVIDEND_RESERVE_INSUFFICIENT` with nothing whatsoever written."
        PRD §3.9: "Under `DECLARED_RATE` the effective rate is exactly
        `declared_rate_cents_per_share` as submitted, and if the resulting total exceeds
        the reserve the execution is refused with `ERR_DIVIDEND_RESERVE_INSUFFICIENT`
        and nothing is written."

        Design: Difficulty/priority_pair_validation_conflict/execute_state_check_outranks_dividend_reserve_shortfall
        """
        company, holder, instruction = _build_short_reserve_dividend(api)

        acknowledged = fixtures.acknowledge_instruction(
            api, instruction["id"], headers=TRANSFER_AGENT
        )
        assertions.assert_instruction(acknowledged, status="ACKNOWLEDGED")

        response = api.execute_instruction(instruction["id"], TRANSFER_AGENT)
        validate_error(response, ApiErrorId.DIVIDEND_RESERVE_INSUFFICIENT.value)

        stored = fixtures.read_instruction(api, instruction["id"])
        assertions.assert_instruction(
            stored,
            status="ACKNOWLEDGED",
            total_payout_cents=None,
            payout_ledger=None,
            executed_at=None,
            executed_by_user_id=None,
        )

        issuer = fixtures.read_company(api, company["id"])
        assertions.assert_company(
            issuer, dividend_reserve_cents=100, dividend_paid_cents=0
        )
        payee = fixtures.read_contact(api, holder["id"])
        assertions.assert_contact(payee, dividend_received_cents=0)


def _build_two_windows_with_a_standing_booking(api: ApiClient):
    """One holder, two open events with different window ends, one 17:30-18:00 booking."""
    fixtures.set_clock(api, CLOCK_START)
    company = fixtures.create_company(
        api,
        ticker="OVL",
        legal_name="Overlap Priority Corp",
        shares_outstanding=1000000,
    )
    holder = fixtures.create_holder(
        api,
        company["id"],
        20000,
        display_name="Overlap Holder",
        email="ovl@funds.test",
        nda_on_file=True,
    )
    narrow_event = fixtures.open_event(
        api,
        company["id"],
        event_type="CONFERENCE",
        venue_city="New York",
        window_start="2026-09-01T13:00:00Z",
        window_end="2026-09-01T18:00:00Z",
        slot_minutes=30,
        capacity_slots=5,
    )
    wide_event = fixtures.open_event(
        api,
        company["id"],
        event_type="NDR",
        venue_city="New York",
        window_start="2026-09-01T13:00:00Z",
        window_end="2026-09-01T19:00:00Z",
        slot_minutes=30,
        capacity_slots=5,
    )
    standing = fixtures.create_meeting_request(
        api,
        narrow_event["id"],
        holder["id"],
        requested_slot_start="2026-09-01T17:30:00Z",
        requested_slot_end="2026-09-01T18:00:00Z",
    )
    return company, holder, narrow_event, wide_event, standing


class TestSlotWindowOutranksContactDoubleBooking:
    """Level-13 temporal validity versus level-14 interval overlap on POST /meeting-requests."""

    def test_slot_poking_past_the_window_end_answers_with_out_of_window(
        self, api: ApiClient
    ):
        """The 18:00-18:30 bid breaks the window and the 30-minute buffer at once.

        PRD §2.10: "13. Temporal validity — slot windows, slot durations, record and
        payable dates, and the reversal window."
        PRD §2.10: "14. Interval and cycle overlap."
        PRD §3.8: "The slot must sit entirely inside the event's meeting window, meaning
        `requested_slot_start` is at or after `window_start` and `requested_slot_end` is
        at or before `window_end`; a slot poking out either side is refused with
        `ERR_SLOT_OUT_OF_WINDOW`."

        Design: Difficulty/priority_pair_validation_conflict/meeting_slot_window_check_outranks_contact_double_booking
        """
        company, holder, narrow_event, wide_event, standing = (
            _build_two_windows_with_a_standing_booking(api)
        )

        response = api.create_meeting_request(
            {
                "event_id": narrow_event["id"],
                "contact_id": holder["id"],
                "requested_slot_start": "2026-09-01T18:00:00Z",
                "requested_slot_end": "2026-09-01T18:30:00Z",
            },
            IR_ADMIN,
        )
        validate_error(response, ApiErrorId.SLOT_OUT_OF_WINDOW.value)

        stored_event = fixtures.read_event(api, narrow_event["id"])
        assertions.assert_roadshow_event(stored_event, request_ledger_total=1)
        assertions.assert_meeting_request(
            fixtures.read_meeting_request(api, standing["id"]), status="REQUESTED"
        )

    def test_same_slot_inside_a_wider_window_answers_with_double_booking(
        self, api: ApiClient
    ):
        """Remove the window violation and the buffer collision decides instead.

        PRD §3.8: "Concretely, the collision test is that the new start is earlier than
        the stored end plus thirty minutes **and** the stored start minus thirty minutes
        is earlier than the new end."
        PRD §3.8: "A collision is refused with `ERR_CONTACT_DOUBLE_BOOKED`."

        Design: Difficulty/priority_pair_validation_conflict/meeting_slot_window_check_outranks_contact_double_booking
        """
        company, holder, narrow_event, wide_event, standing = (
            _build_two_windows_with_a_standing_booking(api)
        )

        response = api.create_meeting_request(
            {
                "event_id": wide_event["id"],
                "contact_id": holder["id"],
                "requested_slot_start": "2026-09-01T18:00:00Z",
                "requested_slot_end": "2026-09-01T18:30:00Z",
            },
            IR_ADMIN,
        )
        validate_error(response, ApiErrorId.CONTACT_DOUBLE_BOOKED.value)

        assertions.assert_roadshow_event(
            fixtures.read_event(api, wide_event["id"]), request_ledger_total=0
        )
        assertions.assert_roadshow_event(
            fixtures.read_event(api, narrow_event["id"]), request_ledger_total=1
        )
        assertions.assert_meeting_request(
            fixtures.read_meeting_request(api, standing["id"]), status="REQUESTED"
        )
