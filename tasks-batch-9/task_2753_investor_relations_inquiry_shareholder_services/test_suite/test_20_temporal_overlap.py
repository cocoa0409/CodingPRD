"""Two interval-overlap rules with deliberately opposite adjacency semantics.

The contact is the occupied resource for meeting slots: the interval is half-open
and padded by thirty minutes on each side, so a gap of exactly thirty minutes is
legal while twenty-nine minutes collides. The issuer is the occupied resource for
dividend cycles: the interval is closed and unpadded, so a new record date landing
exactly on a stored payable date does collide.
"""

from test_helpers import (
    ApiClient,
    ApiErrorId,
    IR_ADMIN,
    assertions,
    factories,
    fixtures,
    validate_error,
    validate_success,
)

CLOCK_START = "2026-08-01T00:00:00Z"


def _build_buffer_world(api: ApiClient):
    """An open event and one holder already booked for 14:00-14:30."""
    fixtures.set_clock(api, CLOCK_START)
    company = fixtures.create_company(
        api,
        ticker="BUF",
        legal_name="Buffer Semantics Corp",
        shares_outstanding=1000000,
    )
    holder = fixtures.create_holder(
        api,
        company["id"],
        20000,
        display_name="Buffer Holder",
        email="buf@funds.test",
        nda_on_file=True,
    )
    event = fixtures.open_event(
        api,
        company["id"],
        event_type="CONFERENCE",
        venue_city="Zurich",
        window_start="2026-09-01T13:00:00Z",
        window_end="2026-09-01T18:00:00Z",
        slot_minutes=30,
        capacity_slots=5,
    )
    standing = fixtures.create_meeting_request(
        api,
        event["id"],
        holder["id"],
        requested_slot_start="2026-09-01T14:00:00Z",
        requested_slot_end="2026-09-01T14:30:00Z",
    )
    assertions.assert_meeting_request(standing, status="REQUESTED")
    return company, holder, event, standing


def _bid(event_id: str, contact_id: str, start: str, end: str):
    return factories.meeting_request_payload(
        event_id, contact_id, requested_slot_start=start, requested_slot_end=end
    )


class TestContactMeetingBuffer:
    """The thirty-minute travel buffer around a contact's stored slots."""

    def test_twenty_nine_minute_gap_falls_inside_the_buffer_and_collides(
        self, api: ApiClient
    ):
        """A 14:59 start is earlier than the stored 14:30 end plus thirty minutes.

        PRD §3.8: "Nobody can be in two meetings at once, and management needs travel time
        between them, so a request collides with any *other* meeting request of the same
        contact whose status is `REQUESTED`, `ALLOCATED` or `WAITLISTED` when the two
        intervals overlap after the stored one is padded by half an hour on each side."
        PRD §3.8: "Concretely, the collision test is that the new start is earlier than the
        stored end plus thirty minutes **and** the stored start minus thirty minutes is
        earlier than the new end."
        PRD §3.8: "A collision is refused with `ERR_CONTACT_DOUBLE_BOOKED`."

        Design: Difficulty/resource_temporal_overlap/contact_meeting_buffer_thirty_minute_gap_is_allowed
        """
        company, holder, event, standing = _build_buffer_world(api)

        validate_error(
            api.create_meeting_request(
                _bid(
                    event["id"],
                    holder["id"],
                    "2026-09-01T14:59:00Z",
                    "2026-09-01T15:29:00Z",
                ),
                IR_ADMIN,
            ),
            ApiErrorId.CONTACT_DOUBLE_BOOKED.value,
        )

        assertions.assert_roadshow_event(
            fixtures.read_event(api, event["id"]), request_ledger_total=1
        )
        assertions.assert_meeting_request(
            fixtures.read_meeting_request(api, standing["id"]), status="REQUESTED"
        )

    def test_gap_of_exactly_thirty_minutes_is_accepted(self, api: ApiClient):
        """Adjacency at the buffer edge is legal and the ledger counts both bids.

        PRD §3.8: "A gap of exactly thirty minutes between two slots therefore does not
        collide, while a gap of twenty-nine minutes does."
        PRD §3.8: "A surviving request is born in `REQUESTED` with `final_priority_score`
        null, `allocated_at` null, `release_reason` null and `promoted_from_waitlist`
        false, and it increments the parent event's `request_ledger_total` by 1 along with
        the event's `version`."

        Design: Difficulty/resource_temporal_overlap/contact_meeting_buffer_thirty_minute_gap_is_allowed
        """
        company, holder, event, standing = _build_buffer_world(api)

        created = validate_success(
            api.create_meeting_request(
                _bid(
                    event["id"],
                    holder["id"],
                    "2026-09-01T15:00:00Z",
                    "2026-09-01T15:30:00Z",
                ),
                IR_ADMIN,
            ),
            expected_status=201,
        )
        assertions.assert_meeting_request(
            created,
            status="REQUESTED",
            final_priority_score=None,
            allocated_at=None,
            promoted_from_waitlist=False,
        )
        assertions.assert_ts_equals(
            created["requested_slot_start"],
            "2026-09-01T15:00:00.000Z",
            "requested_slot_start",
        )
        assert created["provisional_priority_score"] == assertions.approx_2dp(61.20)

        assertions.assert_roadshow_event(
            fixtures.read_event(api, event["id"]), request_ledger_total=2
        )
        assertions.assert_meeting_request(
            fixtures.read_meeting_request(api, standing["id"]), status="REQUESTED"
        )


def _build_live_dividend_cycle(api: ApiClient):
    """An issuer carrying one SUBMITTED dividend cycle over 2026-08-15..2026-08-25."""
    fixtures.set_clock(api, CLOCK_START)
    company = fixtures.create_company(
        api,
        ticker="CYL",
        legal_name="Cycle Overlap Corp",
        shares_outstanding=1000000,
        dividend_reserve_cents=100000,
    )
    holder = fixtures.create_holder(
        api,
        company["id"],
        1000,
        display_name="Cycle Holder",
        email="cyl@funds.test",
    )
    instruction = fixtures.submit_dividend(
        api,
        company["id"],
        record_date="2026-08-15",
        payable_date="2026-08-25",
        declared_rate_cents_per_share=1.0000,
        funding_mode="DECLARED_RATE",
    )
    assertions.assert_instruction(instruction, status="SUBMITTED")
    assertions.assert_version(instruction, 1, "TransferAgentInstruction")
    return company, holder, instruction


def _dividend_bid(company_id: str, record_date: str, payable_date: str):
    return factories.dividend_instruction_payload(
        company_id,
        record_date=record_date,
        payable_date=payable_date,
        declared_rate_cents_per_share=1.0000,
        funding_mode="DECLARED_RATE",
    )


class TestDividendCycleClosedInterval:
    """The closed, date-inclusive [record_date, payable_date] cycle interval."""

    def test_record_date_equal_to_the_stored_payable_date_collides(self, api: ApiClient):
        """Touching the stored endpoint is an overlap because the interval is closed.

        PRD §3.9: "A cycle is the **closed** date interval running from `record_date`
        through `payable_date` inclusive, and two cycles overlap when the new record date is
        on or before the stored payable date **and** the stored record date is on or before
        the new payable date."
        PRD §3.9: "A new record date falling exactly on a stored payable date therefore does
        collide — the opposite inclusivity from the half-open meeting-slot rule of §3.8, and
        a deliberate difference."
        PRD §3.9: "A collision is refused with `ERR_DIVIDEND_CYCLE_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/dividend_cycle_closed_interval_endpoint_touch_collides
        """
        company, holder, stored = _build_live_dividend_cycle(api)

        validate_error(
            api.create_instruction(
                _dividend_bid(company["id"], "2026-08-25", "2026-09-05"), IR_ADMIN
            ),
            ApiErrorId.DIVIDEND_CYCLE_OVERLAP.value,
        )

        untouched = fixtures.read_instruction(api, stored["id"])
        assertions.assert_instruction(untouched, status="SUBMITTED")
        assertions.assert_version(untouched, 1, "TransferAgentInstruction")

    def test_record_date_one_day_after_the_stored_payable_date_is_accepted(
        self, api: ApiClient
    ):
        """One day clear of the stored endpoint the cycles no longer intersect.

        PRD §3.9: "When a `DIVIDEND_PAYMENT` instruction is submitted, the system compares
        its cycle against every other `DIVIDEND_PAYMENT` instruction of that issuer whose
        status is `SUBMITTED`, `ACKNOWLEDGED` or `EXECUTED`."
        PRD §3.9: "A new instruction is born in `SUBMITTED` with
        `acknowledged_by_user_id`, `executed_by_user_id`, `snapshot_holder_count`,
        `snapshot_shares_total`, `payout_ledger`, `total_payout_cents`, `executed_at` and
        `decision_reason` all null, and `version` at 1."

        Design: Difficulty/resource_temporal_overlap/dividend_cycle_closed_interval_endpoint_touch_collides
        """
        company, holder, stored = _build_live_dividend_cycle(api)

        created = validate_success(
            api.create_instruction(
                _dividend_bid(company["id"], "2026-08-26", "2026-09-05"), IR_ADMIN
            ),
            expected_status=201,
        )
        assertions.assert_instruction(
            created,
            instruction_type="DIVIDEND_PAYMENT",
            funding_mode="DECLARED_RATE",
            status="SUBMITTED",
            acknowledged_by_user_id=None,
            executed_by_user_id=None,
            snapshot_holder_count=None,
            snapshot_shares_total=None,
            payout_ledger=None,
            total_payout_cents=None,
            executed_at=None,
            decision_reason=None,
        )
        assertions.assert_version(created, 1, "TransferAgentInstruction")

        untouched = fixtures.read_instruction(api, stored["id"])
        assertions.assert_instruction(untouched, status="SUBMITTED")
        assertions.assert_version(untouched, 1, "TransferAgentInstruction")
