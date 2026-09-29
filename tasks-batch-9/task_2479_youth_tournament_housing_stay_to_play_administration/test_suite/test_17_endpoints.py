"""Routes exercised for the shape of what they return and what they refuse.

A rebate invoice read two ways, a manifest rejected in one piece, a supersede
link that quietly cancels what it replaces, a block list that carries its own
derived counters, and a release that has to wait for its deadline.
"""

from test_helpers import (
    HOUSING_MANAGER_HEADERS,
    RIGHTS_HOLDER_HEADERS,
    ApiErrorId,
    factories as f,
    fixtures as fx,
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

HM = HOUSING_MANAGER_HEADERS
RIGHTS = RIGHTS_HOLDER_HEADERS


def _second_block_env(api) -> fx.Env:
    """A confirmed four-room booking on a twenty-room block, beside an untouched
    ten-room block held under the same contract."""
    env = fx.confirmed_booking_env(api)
    env.booked_block = env.block
    env.spare_block = fx.add_block(env, block_size_rooms=10)
    return env


class TestRebateInvoiceReadRoutes:
    """One invoice, reachable by identifier and through a filtered list."""

    def test_the_invoice_reads_back_by_id_with_its_whole_ledger(self, api):
        """Twelve actualized room nights at nine hundred cents each, with no
        attrition shortfall to net off, read back as a ten-thousand-eight-hundred
        cent claim that nothing has been collected against yet.

        PRD §3.8: "`invoiced_room_nights` is the sum of `actualized_room_nights`
        across the scope."

        PRD §3.8: "The **billed** variant, stored as
        `attrition_shortfall_room_nights_per_block`, clamps each block
        independently: for each block take its threshold nights less its actual
        nights, floor that difference at 0, and sum the clamped per-block
        results."

        PRD §3.8: "`total_due_cents` is `invoiced_rebate_cents` less
        `attrition_penalty_cents`, floored at 0 — a penalty larger than the rebate
        zeroes the claim rather than turning it into a debt owed by the event."

        PRD §3.8: "The ledger fields open at `collected_cents` 0,
        `written_off_cents` 0, `outstanding_cents` equal to `total_due_cents`, and
        `distributed_cents` 0, with `status` at `DRAFT` and `dispute_note` null."

        Design: Corner/endpoints/rebate_invoice_readable_by_id_and_by_filtered_list
        """
        env = fx.invoiced_env(api)

        invoice = get_success_data(api.get_rebate_invoice(env.invoice_id, HM))

        assert invoice["id"] == env.invoice_id
        assert invoice["contract_id"] == env.contract_id
        assert invoice["period_label"] == "2026-09"
        assert invoice["invoiced_room_nights"] == 12
        assert invoice["invoiced_rebate_cents"] == 10800
        assert invoice["attrition_shortfall_room_nights_per_block"] == 0
        assert invoice["attrition_shortfall_room_nights_aggregate"] == 0
        assert invoice["attrition_penalty_cents"] == 0
        assert invoice["total_due_cents"] == 10800
        assert invoice["collected_cents"] == 0
        assert invoice["written_off_cents"] == 0
        assert invoice["outstanding_cents"] == 10800
        assert invoice["distributed_cents"] == 0
        assert invoice["status"] == "DRAFT"
        assert invoice["dispute_note"] is None

    def test_the_hotel_finds_the_same_invoice_through_the_filtered_list(self, api):
        """Filtering the list by the contract and by the `DRAFT` status returns
        exactly the one invoice, and the hotel's own representative may read it.

        PRD §2.3: "List endpoints additionally accept the domain filters named in
        their §4 descriptions; a filter that is supplied narrows the result set by
        exact match on the named field, and filters combine conjunctively."

        PRD §2.3: "For every list response, the `meta` block carries `limit`,
        `offset`, `total_count` and `has_more`, where `total_count` is the number
        of rows matching the filters before pagination and `has_more` indicates
        whether rows remain beyond the current page."

        Design: Corner/endpoints/rebate_invoice_readable_by_id_and_by_filtered_list
        """
        env = fx.invoiced_env(api)

        response = api.list_rebate_invoices(
            env.hotel_headers, {"contract_id": env.contract_id, "status": "DRAFT"}
        )

        invoices, meta = validate_paginated(response)
        assert meta["total_count"] == 1
        assert meta["has_more"] is False
        assert len(invoices) == 1
        assert invoices[0]["id"] == env.invoice_id
        assert invoices[0]["total_due_cents"] == 10800
        assert invoices[0]["outstanding_cents"] == 10800


class TestRoomingListSubmissionIsAllOrNothing:
    """One oversized room voids the whole manifest."""

    def test_a_single_five_occupant_room_leaves_no_entries_stored(self, api):
        """Three well-formed rooms and one holding five occupants are submitted
        together; the batch is refused and the booking keeps no entries at all.

        PRD §3.4: "Every entry must keep `occupant_count` at or below the
        four-occupant room ceiling and must not report more minors than occupants
        — `minor_occupant_count` must be at least 0 and no greater than
        `occupant_count` — otherwise `ERR_ROOM_OCCUPANCY_EXCEEDED`."

        PRD §3.4: "A first submission moves the booking `DRAFT →
        ROOMING_LIST_SUBMITTED`, creating one row per submitted element."

        PRD §2.4: "Most resources additionally carry `updated_at`, an ISO 8601
        UTC timestamp in the same format, and `version`, an integer that starts at
        1 when the row is created and is incremented by exactly 1 on every
        mutation of that row."

        Design: Corner/endpoints/rooming_list_batch_rejected_whole_on_one_bad_entry
        """
        env = fx.draft_booking_env(api)

        response = api.submit_rooming_list(
            env.booking_id,
            f.rooming_list_payload(
                entries=[
                    f.rooming_list_entry(1, occupant_count=4),
                    f.rooming_list_entry(2, occupant_count=4),
                    f.rooming_list_entry(3, occupant_count=5),
                    f.rooming_list_entry(4, occupant_count=3),
                ]
            ),
            HM,
        )

        validate_error(
            response, ApiErrorId.ERR_ROOM_OCCUPANCY_EXCEEDED.value, expected_status=422
        )
        entries, meta = validate_paginated(api.list_rooming_list(env.booking_id, HM))
        assert meta["total_count"] == 0
        assert entries == []
        booking = env.refresh_booking()
        assert booking["booking_status"] == "DRAFT"
        assert booking["version"] == 1


class TestSupersedeLink:
    """Booking a replacement cancels the booking it names."""

    def test_the_replacement_booking_is_created_and_records_the_link(self, api):
        """A second four-room booking on the same block names the confirmed one it
        replaces, and is created at `DRAFT` with its own projection.

        PRD §3.4: "A supplied `supersedes_booking_id` must name a booking of the
        **same** `registration_id` whose `booking_status` is `DRAFT`,
        `ROOMING_LIST_SUBMITTED` or `CONFIRMED`; pointing at another
        registration's booking, or at one already `CHECKED_OUT` or `CANCELLED`, is
        rejected with `ERR_SUPERSEDE_TARGET_INVALID`."

        PRD §3.4: "The server computes `nights` as the whole days from
        `check_in_date` up to but not including `check_out_date`, and
        `projected_room_nights` as `rooms_requested` multiplied by `nights` — the
        pre-stay estimate that cancellation penalties are assessed against."

        Design: Corner/endpoints/supersede_link_cancels_the_referenced_booking
        """
        env = fx.confirmed_booking_env(api)
        superseded_id = env.booking_id
        registration = env.refresh_registration()

        response = api.create_booking(
            f.booking_payload(
                registration["id"],
                env.block_id,
                registration["version"],
                supersedes_booking_id=superseded_id,
            ),
            HM,
        )

        replacement = validate_success(response, expected_status=201)
        assert replacement["booking_status"] == "DRAFT"
        assert replacement["rebate_status"] == "NOT_DUE"
        assert replacement["supersedes_booking_id"] == superseded_id
        assert replacement["rooms_requested"] == 4
        assert replacement["projected_room_nights"] == 12
        assert replacement["penalty_cents"] == 0

    def test_the_referenced_booking_is_cancelled_with_its_quarter_tier_penalty(
        self, api
    ):
        """Forty days before check-in the superseded booking falls in the quarter
        tier, so three of its twelve room nights are charged, and the rooms it was
        holding go straight back to the block.

        PRD §3.4: "When `supersedes_booking_id` was supplied, the named booking is
        moved to `CANCELLED` as a side effect, with its `cancellation_reason` set
        to `SUPERSEDED` and the deadline-tier penalty of §3.5 assessed against it
        exactly as if it had been cancelled directly."

        PRD §3.5: "The system first computes the **days out**: take the instant of
        `check_in_date` at midnight UTC, subtract the current logical instant, and
        take the whole number of 86,400-second days in that difference, rounding
        **down**."

        PRD §3.5: "From twenty-one days out up to forty-four,
        `penalty_room_nights` is one quarter of `projected_room_nights`, rounded
        **up** to a whole room night."

        PRD §3.5: "`penalty_cents` is then `penalty_room_nights` multiplied by the
        `negotiated_nightly_rate_cents` of the contract that owns the booking's
        room block — reached from the booking through its block, since the rate
        lives on the contract rather than on the block."

        PRD §3.5: "The server also stamps `cancelled_at` with the current logical
        instant."

        PRD §3.3: "Third, `committed_rooms` becomes the sum of `rooms_requested`
        across the registration's bookings whose `booking_status` is `CONFIRMED`
        or `CHECKED_OUT`; bookings at `DRAFT`, `ROOMING_LIST_SUBMITTED` or
        `CANCELLED` contribute nothing."

        Design: Corner/endpoints/supersede_link_cancels_the_referenced_booking
        """
        env = fx.confirmed_booking_env(api)
        superseded = env.booking
        registration = env.refresh_registration()

        validate_success(
            api.create_booking(
                f.booking_payload(
                    registration["id"],
                    env.block_id,
                    registration["version"],
                    supersedes_booking_id=superseded["id"],
                ),
                HM,
            ),
            expected_status=201,
        )

        cancelled = env.refresh_booking(superseded)
        assert cancelled["booking_status"] == "CANCELLED"
        assert cancelled["cancellation_reason"] == "SUPERSEDED"
        assert cancelled["penalty_room_nights"] == 3
        assert cancelled["penalty_cents"] == 44700
        assert cancelled["cancelled_at"] is not None
        block = env.refresh_block()
        assert block["rooms_committed"] == 0
        assert block["rooms_available"] == 20
        assert block["utilization_pct"] == 0.0
        assert block["status"] == "OPEN"
        refreshed_registration = env.refresh_registration()
        assert refreshed_registration["committed_rooms"] == 0
        assert refreshed_registration["status"] == "PENDING_HOUSING"


class TestRoomBlockListRoute:
    """The block list carries every counter the confirm chain moved."""

    def test_the_list_reports_each_block_with_its_own_derived_counters(self, api):
        """Two blocks under one contract, one carrying four confirmed rooms and
        one untouched, read back with their own committed, available, utilization
        and attrition-floor figures.

        PRD §3.2: "A new block starts at `status` `OPEN` with `rooms_committed` at
        0, `rooms_available` equal to `block_size_rooms`, `rooms_released_unsold`
        at 0, `utilization_pct` at 0 and `actualized_room_nights` at 0."

        PRD §3.2: "The server also stamps `threshold_room_nights`, the block's
        attrition floor: multiply `block_size_rooms` by the number of whole nights
        in the block window, multiply by the contract's `attrition_threshold_pct`,
        and round the product **up** to the next whole room night."

        PRD §3.4: "`utilization_pct` is `rooms_committed` divided by
        `block_size_rooms`, rounded half up to four decimal places."

        PRD §2.3: "List endpoints additionally accept the domain filters named in
        their §4 descriptions; a filter that is supplied narrows the result set by
        exact match on the named field, and filters combine conjunctively."

        Design: Corner/endpoints/room_block_read_route_serves_derived_counters
        """
        env = _second_block_env(api)

        response = api.list_contract_room_blocks(
            env.contract_id, RIGHTS, {"status": "OPEN"}
        )

        blocks, meta = validate_paginated(response)
        assert meta["total_count"] == 2
        by_id = {row["id"]: row for row in blocks}
        booked = by_id[env.booked_block["id"]]
        assert booked["block_size_rooms"] == 20
        assert booked["rooms_committed"] == 4
        assert booked["rooms_available"] == 16
        assert booked["rooms_released_unsold"] == 0
        assert booked["utilization_pct"] == 0.2
        assert booked["threshold_room_nights"] == 6
        assert booked["status"] == "OPEN"
        spare = by_id[env.spare_block["id"]]
        assert spare["block_size_rooms"] == 10
        assert spare["rooms_committed"] == 0
        assert spare["rooms_available"] == 10
        assert spare["utilization_pct"] == 0.0
        assert spare["threshold_room_nights"] == 3
        assert spare["status"] == "OPEN"


class TestBlockReleaseDeadline:
    """Rooms go back to the hotel only once the release deadline is reached."""

    def test_a_release_three_weeks_early_is_refused(self, api):
        """At the first of August the block's twenty-fifth-of-August deadline is
        still in the future, so the block keeps all twenty rooms available.

        PRD §3.2: "An attempt before that instant is rejected with
        `ERR_RELEASE_BEFORE_DEADLINE`; note the comparison is inclusive, so a
        release exactly at the deadline is permitted."

        PRD §2.11: "A block release happens at or after the block's
        `release_deadline` — otherwise `ERR_RELEASE_BEFORE_DEADLINE`."

        PRD §2.12: "While a room block's `status` is `OPEN` or `RESTRICTED`, its
        `rooms_committed` and `rooms_available` sum to exactly `block_size_rooms`,
        and its `rooms_released_unsold` is 0."

        Design: Corner/endpoints/release_before_deadline_rejected
        """
        env = fx.executed_contract_env(api)

        response = api.release_room_block(env.block_id, HM)

        validate_error(
            response, ApiErrorId.ERR_RELEASE_BEFORE_DEADLINE.value, expected_status=422
        )
        block = env.refresh_block()
        assert block["status"] == "OPEN"
        assert block["rooms_committed"] == 0
        assert block["rooms_available"] == 20
        assert block["rooms_released_unsold"] == 0

    def test_the_same_release_a_day_after_the_deadline_hands_back_every_room(self, api):
        """Once the clock has passed the deadline the identical call succeeds, and
        all twenty unsold rooms are frozen as released while the contract's block
        posture falls back to available.

        PRD §3.2: "Both source states behave identically: the transition freezes
        `rooms_released_unsold` at `block_size_rooms` minus `rooms_committed`, sets
        `rooms_available` to 0, leaves `rooms_committed` untouched, then recomputes
        the contract's `block_posture` and, from that, the tournament's
        `housing_pressure`."

        PRD §3.2: "If the contract has no live blocks at all, `block_posture` is
        `AVAILABLE`."

        PRD §3.2: "`housing_pressure` reads `CONSTRAINED` when
        `executed_contract_count` is at least 1 and `sold_out_contract_count`
        equals `executed_contract_count`; in every other case, including the case
        of no executed contracts at all, it reads `NORMAL`."

        Design: Corner/endpoints/release_before_deadline_rejected
        """
        env = fx.executed_contract_env(api)
        validate_error(
            api.release_room_block(env.block_id, HM),
            ApiErrorId.ERR_RELEASE_BEFORE_DEADLINE.value,
            expected_status=422,
        )
        fx.set_clock(api, "2026-08-26T00:00:00Z")

        block = validate_success(
            api.release_room_block(env.block_id, HM), expected_status=200
        )

        assert block["status"] == "RELEASED"
        assert block["rooms_committed"] == 0
        assert block["rooms_released_unsold"] == 20
        assert block["rooms_available"] == 0
        contract = env.refresh_contract()
        assert contract["status"] == "EXECUTED"
        assert contract["block_posture"] == "AVAILABLE"
        tournament = env.refresh_tournament()
        assert tournament["executed_contract_count"] == 1
        assert tournament["sold_out_contract_count"] == 0
        assert tournament["housing_pressure"] == "NORMAL"
