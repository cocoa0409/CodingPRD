"""Version guards, child-write ripples and the sweep's strictly-past thresholds."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ADMIN_HEADERS,
    ERR_COMPLAINT_STATE_INVALID,
    ERR_STALE_BOOKING_VERSION,
    ERR_STALE_POLICY_VERSION,
    OFFICER_HEADERS,
    acknowledge,
    add_ancillary,
    add_checked_bag,
    add_segment,
    answer,
    assert_activity_types,
    assert_booking_ledger,
    assert_list_meta,
    assert_obligation_amounts,
    assert_obligation_axes,
    assert_obligation_deadlines,
    assert_sweep_counters,
    booking_version,
    build_world,
    cancel_segment,
    factories as f,
    file_complaint,
    obligations_with_meta,
    open_report,
    read_ancillary,
    read_bag,
    read_booking,
    read_complaint,
    read_obligation,
    read_passenger,
    read_profile,
    run_sweep,
    set_clock,
    sole_obligation,
)

# ─── The booking version guard on the money path ──────


def _two_leg_booking_at_version_three(api):
    """90000 cents over two legs: the create's own version 1 is already superseded."""
    return build_world(api, total_fare_cents=90000, segment_fares=[30000, 60000])


class TestObligationCreateReadsTheBookingVersion:
    def test_the_version_seen_at_booking_create_is_already_too_old(self, api):
        """Two segment adds moved the booking on, so version 1 buys nothing.

        PRD §2.6: "Minting a refund obligation requires the non-optional field
        `expected_booking_version`, carrying the client's last observed `version` of the target
        booking."

        PRD §2.6: "If that value does not equal the booking's current `version`, the create is
        rejected with `ERR_STALE_BOOKING_VERSION` (HTTP 412)."

        PRD §2.6: "A client whose view of the booking predates such a movement would compute its
        claim against superseded totals, so the stale view is refused outright rather than
        silently clamped to whatever is left."

        Design: Corner/cross_cutting_complexity_layers/obligation_create_refuses_a_stale_booking_version
        """
        world = _two_leg_booking_at_version_three(api)
        assert world.booking["version"] == 1, "the create's own view of the booking"
        assert booking_version(api, world.booking["id"]) == 3, "two legs moved it twice"

        refused = api.create_refund_obligation(
            f.obligation_payload(
                world.booking["id"],
                1,
                issuance_mode="REQUEST_BASED",
                flight_segment_id=world.segments[0]["id"],
            ),
            OFFICER_HEADERS,
        )

        validate_error(refused, ERR_STALE_BOOKING_VERSION, 412)
        assert booking_version(api, world.booking["id"]) == 3, "the refusal wrote nothing"
        _, meta = obligations_with_meta(api, world.booking["id"])
        assert_list_meta(meta, total_count=0, has_more=False)

    def test_the_same_body_with_the_freshly_read_version_is_accepted(self, api):
        """Version 3 lets the identical claim through and the ledger takes 90000.

        PRD §3.6: "In request-based mode the variant is `REQUEST_BASED_UNUSED_PRORATION`, and it
        prorates evenly: when the booking's `segment_count` is 0 the gross entitlement is 0 and
        no division is attempted, and otherwise the per-leg share is the booking's
        `total_fare_cents` divided by its `segment_count` and rounded half up, and the gross
        entitlement is that share multiplied by the booking's `unused_segment_count`."

        PRD §3.6: "Step five, and only then, recomputes the booking's derived ledger fields,
        re-reading the persisted rows **including** the one just written, and advances the
        booking's `version` by 1."

        Design: Corner/cross_cutting_complexity_layers/obligation_create_refuses_a_stale_booking_version
        """
        world = _two_leg_booking_at_version_three(api)

        minted = validate_success(
            api.create_refund_obligation(
                f.obligation_payload(
                    world.booking["id"],
                    3,
                    issuance_mode="REQUEST_BASED",
                    flight_segment_id=world.segments[0]["id"],
                ),
                OFFICER_HEADERS,
            ),
            201,
        )

        assert_obligation_amounts(minted, amount_cents=90000)
        assert booking_version(api, world.booking["id"]) == 4, "the accepted create moved it"
        assert_booking_ledger(
            read_booking(api, world.booking["id"]), total_refund_obligated_cents=90000
        )


# ─── The profile version guard on the filing path ─────


def _profile_with_a_june_draft(api):
    """One profile read at version 1, then one June filing that moves it to 2."""
    profile = validate_success(
        api.create_policy_profile(f.policy_profile_payload("ZQ"), ADMIN_HEADERS), 201
    )
    june = open_report(
        api,
        profile["id"],
        period_start_utc="2026-06-01T00:00:00Z",
        period_end_utc="2026-06-30T23:59:59Z",
        expected_policy_profile_version=profile["version"],
    )
    return profile, june


class TestReportCreateReadsTheProfileVersion:
    def test_a_non_overlapping_july_period_is_still_refused_on_the_stale_version(self, api):
        """July never touches June, yet the pre-June profile version is fatal.

        PRD §2.6: "Opening a regulator report requires the non-optional field
        `expected_policy_profile_version`, carrying the client's last observed `version` of the
        target policy profile."

        PRD §2.6: "A mismatch with the profile's current `version` is rejected with
        `ERR_STALE_POLICY_VERSION` (HTTP 412)."

        PRD §2.9: "`report_count` increases by 1 each time a regulator report is opened against
        the profile, and `open_violation_count` is rewritten by the compliance sweep (§3.9). Both
        start at 0, and the profile's `version` starts at 1 and advances whenever either
        counter's value changes — which is precisely why report creation is guarded by a version
        check (§2.6)."

        Design: Corner/cross_cutting_complexity_layers/report_create_refuses_a_stale_policy_version
        """
        profile, june = _profile_with_a_june_draft(api)
        assert profile["version"] == 1, "the version the client last observed"

        refused = api.create_regulator_report(
            f.report_payload(
                profile["id"], 1, "2026-07-01T00:00:00Z", "2026-07-31T23:59:59Z"
            ),
            ADMIN_HEADERS,
        )

        validate_error(refused, ERR_STALE_POLICY_VERSION, 412)
        after = read_profile(api, profile["id"])
        assert after["report_count"] == 1, "only June was ever opened"
        assert after["version"] == 2, "the refusal moved nothing"
        filings, meta = validate_paginated(
            api.list_policy_profile_reports(profile["id"], ADMIN_HEADERS)
        )
        assert_list_meta(meta, total_count=1, has_more=False)
        assert filings[0]["id"] == june["id"]

    def test_the_same_july_period_opens_once_the_current_version_is_quoted(self, api):
        """Version 2 opens the July draft and pushes the profile to report_count 2.

        PRD §3.9: "A new report opens in `DRAFT` with all seven metrics at 0,
        `policy_version_pinned` at 0 and `amendment_count` at 0; opening it also increases the
        profile's `report_count` and advances the profile's `version` by 1, which is why two
        reports cannot be opened back to back against one stale profile version."

        PRD §3.9: "Reporting periods for one profile may not intersect, and because both ends are
        **inclusive**, two periods that share a single boundary instant do intersect — an overlap
        is `ERR_REPORT_PERIOD_OVERLAP`."

        Design: Corner/cross_cutting_complexity_layers/report_create_refuses_a_stale_policy_version
        """
        profile, _ = _profile_with_a_june_draft(api)

        july = validate_success(
            api.create_regulator_report(
                f.report_payload(
                    profile["id"], 2, "2026-07-01T00:00:00Z", "2026-07-31T23:59:59Z"
                ),
                ADMIN_HEADERS,
            ),
            201,
        )

        assert july["status"] == "DRAFT"
        assert july["amendment_count"] == 0
        after = read_profile(api, profile["id"])
        assert after["report_count"] == 2, "two periods now stand open"
        assert after["version"] == 3, "each opening advances the profile"


# ─── Child writes move the parent's version ───────────


def _booking_with_three_children(api):
    """A bare 50000-cent booking, then a leg, a seat charge and a bag fee."""
    world = build_world(api)
    segment = add_segment(api, world.booking["id"], segment_fare_cents=50000)
    ancillary = add_ancillary(
        api, world.booking["id"], segment["id"], "SEAT_SELECTION", 2000
    )
    bag = add_checked_bag(api, world.booking["id"], fee_cents=4500)
    return world, segment, ancillary, bag


class TestChildCreatesAdvanceTheBookingVersion:
    def test_the_booking_walks_from_one_to_four_across_three_child_creates(self, api):
        """Each child create recomputes the parent, so the OCC token moves three times.

        PRD §2.4: "All entities except the complaint activity trail additionally carry
        `updated_at`, in the same ISO 8601 UTC format with three fractional digits, and `version`,
        an integer that begins at 1 when the row is created and increases by exactly 1 on each
        request that changes the row's persisted field values."

        PRD §2.4: "A request that recomputes a booking's derived ledger fields advances
        `Booking.version` exactly once for the whole request, however many rows the cascade
        touched on the way — a cancellation that suspends three sibling segments, voids two
        ancillary services and mints three obligations still advances the booking's `version` by
        1, not by 8."

        PRD §3.6: "The money collected on the booking is its `total_fare_cents` plus the sum of
        `amount_cents` over all of its ancillary purchases plus the sum of `fee_cents` over all of
        its checked bags, counting every such row whatever its delivery outcome."

        Design: Corner/cross_cutting_complexity_layers/booking_version_increments_on_every_write_including_child_creates
        """
        world, _, _, _ = _booking_with_three_children(api)
        assert world.booking["version"] == 1, "the booking's own create"

        final = read_booking(api, world.booking["id"])

        assert final["version"] == 4, "one bump per child create, never a batch"
        assert_booking_ledger(
            final,
            collected_total_cents=56500,
            total_refund_obligated_cents=0,
            segment_count=1,
            unused_segment_count=1,
            itinerary_scope="DOMESTIC",
        )

    def test_the_child_rows_are_untouched_by_each_others_writes(self, api):
        """Every child sits at version 1 while the parent's token is observably at 4.

        PRD §2.4: "All entities except the complaint activity trail additionally carry
        `updated_at`, in the same ISO 8601 UTC format with three fractional digits, and `version`,
        an integer that begins at 1 when the row is created and increases by exactly 1 on each
        request that changes the row's persisted field values."

        PRD §2.6: "If that value does not equal the booking's current `version`, the create is
        rejected with `ERR_STALE_BOOKING_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/booking_version_increments_on_every_write_including_child_creates
        """
        world, segment, ancillary, bag = _booking_with_three_children(api)

        assert read_ancillary(api, ancillary["id"])["version"] == 1
        assert read_bag(api, bag["id"], world.booking["id"])["version"] == 1

        refused = api.create_refund_obligation(
            f.obligation_payload(
                world.booking["id"],
                3,
                issuance_mode="REQUEST_BASED",
                flight_segment_id=segment["id"],
            ),
            OFFICER_HEADERS,
        )

        validate_error(refused, ERR_STALE_BOOKING_VERSION, 412)


# ─── The election auto-default threshold ──────────────


def _pending_election_at_its_deadline(api):
    """A cancelled leg's obligation, unelected, with the clock parked on the deadline."""
    world = build_world(api, segment_fares=[50000])
    cancel_segment(api, world.segments[0]["id"], "2026-08-10T10:00:00Z")
    world.obligation = sole_obligation(api, world.booking["id"])
    set_clock(api, "2026-08-15T10:00:00Z")
    return world


class TestElectionAutoDefaultIsStrictlyPastTheDeadline:
    def test_the_sweep_defaults_nothing_at_the_exact_election_deadline(self, api):
        """Standing on 2026-08-15T10:00:00Z the passenger still owns the choice.

        PRD §3.9: "For every obligation whose `election_status` still reads `PENDING_ELECTION`
        and whose `election_deadline_utc` the logical clock has strictly passed, the election axis
        advances `PENDING_ELECTION → ELECTED_CASH` with `election_source` recorded as
        `AUTO_DEFAULT` and the `settlement_method` resolved from the booking's `payment_method`
        exactly as in §3.7."

        PRD §3.6: "And `election_deadline_utc` is five days after the start instant, this
        election window being a statutory constant the carrier cannot tune."

        PRD §3.9: "Its response reports the work done: the `policy_profile_id` swept,
        `deadline_breach_flagged_count`, `election_auto_defaulted_count`,
        `complaint_ack_breach_flagged_count`, `complaint_answer_breach_flagged_count`,
        `complaint_auto_closed_count`, the resulting `open_violation_count`, and the profile's
        resulting `policy_profile_version`."

        Design: Corner/cross_cutting_complexity_layers/election_not_auto_defaulted_at_the_exact_election_deadline_instant
        """
        world = _pending_election_at_its_deadline(api)
        assert_obligation_deadlines(
            world.obligation,
            obligation_start_utc="2026-08-10T10:00:00Z",
            election_deadline_utc="2026-08-15T10:00:00Z",
            deadline_utc="2026-08-17T10:00:00Z",
        )

        swept = run_sweep(api, world.profile["id"])

        assert_sweep_counters(
            swept, election_auto_defaulted_count=0, deadline_breach_flagged_count=0
        )
        assert_obligation_axes(
            read_obligation(api, world.obligation["id"]),
            election_status="PENDING_ELECTION",
            election_source=None,
            settlement_status="UNSETTLED",
        )

    def test_one_second_later_it_defaults_to_cash_and_never_to_credit(self, api):
        """The prohibited practice stays prohibited: cash, on the original instrument.

        PRD §3.9: "For every obligation whose `election_status` still reads `PENDING_ELECTION`
        and whose `election_deadline_utc` the logical clock has strictly passed, the election axis
        advances `PENDING_ELECTION → ELECTED_CASH` with `election_source` recorded as
        `AUTO_DEFAULT` and the `settlement_method` resolved from the booking's `payment_method`
        exactly as in §3.7."

        PRD §3.9: "`ELECTED_CREDIT` is **never** the automatic default, regardless of what
        `travel_credit_default_permitted` says on the profile — defaulting a passenger into travel
        credit is the prohibited practice this phase exists to prevent, and the flag's purpose is
        to make that prohibition explicit rather than to license an exception."

        PRD §3.7: "The instrument is a projection of how the ticket was paid for: a
        `CREDIT_CARD` booking resolves to `ORIGINAL_PAYMENT`, a `CASH_OR_CHECK` booking to
        `CASH_OR_CHECK`, a `MILES` booking to `MILES`, and a booking originally paid for in travel
        credit resolves back to `TRAVEL_CREDIT` even on a cash election — a passenger cannot
        launder credit into cash by electing cash."

        PRD §3.6: "Step four persists the row with its `gross_entitlement_cents`,
        `headroom_at_creation_cents` and `amount_cents`, with `credit_bonus_cents` at 0 and
        `payable_total_cents` equal to `amount_cents` — the goodwill bonus is added later, at
        election, not now."

        Design: Corner/cross_cutting_complexity_layers/election_not_auto_defaulted_at_the_exact_election_deadline_instant
        """
        world = _pending_election_at_its_deadline(api)
        run_sweep(api, world.profile["id"])
        set_clock(api, "2026-08-15T10:00:01Z")

        swept = run_sweep(api, world.profile["id"])

        assert_sweep_counters(
            swept, election_auto_defaulted_count=1, deadline_breach_flagged_count=0
        )
        defaulted = read_obligation(api, world.obligation["id"])
        assert_obligation_axes(
            defaulted,
            election_status="ELECTED_CASH",
            election_source="AUTO_DEFAULT",
            settlement_method="ORIGINAL_PAYMENT",
            settlement_status="UNSETTLED",
        )
        assert_obligation_amounts(
            defaulted, amount_cents=50000, credit_bonus_cents=0, payable_total_cents=50000
        )

    def test_replaying_the_sweep_at_the_same_instant_changes_nothing(self, api):
        """The second run reports no work and leaves the obligation's version alone.

        PRD §3.9: "The sweep advances the `version` of every obligation and complaint it actually
        mutates, and it is **idempotent**: running it twice at the same logical-clock instant
        produces no additional field changes and no additional `version` increments anywhere."

        PRD §3.9: "For every obligation whose `election_status` still reads `PENDING_ELECTION`
        and whose `election_deadline_utc` the logical clock has strictly passed, the election axis
        advances `PENDING_ELECTION → ELECTED_CASH` with `election_source` recorded as
        `AUTO_DEFAULT` and the `settlement_method` resolved from the booking's `payment_method`
        exactly as in §3.7."

        Design: Corner/cross_cutting_complexity_layers/election_not_auto_defaulted_at_the_exact_election_deadline_instant
        """
        world = _pending_election_at_its_deadline(api)
        set_clock(api, "2026-08-15T10:00:01Z")
        run_sweep(api, world.profile["id"])
        after_first = read_obligation(api, world.obligation["id"])

        replayed = run_sweep(api, world.profile["id"])

        assert_sweep_counters(replayed, election_auto_defaulted_count=0)
        after_replay = read_obligation(api, world.obligation["id"])
        assert after_replay["version"] == after_first["version"], (
            "an idempotent sweep bumps no versions"
        )
        assert_obligation_axes(
            after_replay, election_status="ELECTED_CASH", election_source="AUTO_DEFAULT"
        )


# ─── The complaint auto-close threshold ───────────────


def _answered_complaint_at_its_thirty_day_boundary(api):
    """Answered 2026-08-06T09:00:00Z, with the clock parked exactly 30 days later."""
    world = build_world(api)
    world.complaint = file_complaint(
        api,
        world.booking["id"],
        category="REFUND",
        channel="EMAIL",
        received_at_utc="2026-08-05T09:00:00Z",
        summary="Voucher pushed instead of cash.",
    )
    acknowledge(api, world.complaint["id"], "2026-08-05T10:00:00Z")
    answer(api, world.complaint["id"], "2026-08-06T09:00:00Z", "POLICY_EXPLAINED")
    set_clock(api, "2026-09-05T09:00:00Z")
    return world


class TestComplaintAutoCloseIsStrictlyPastThirtyDays:
    def test_the_sweep_leaves_the_answer_open_at_exactly_thirty_days(self, api):
        """At 2026-09-05T09:00:00Z the reopen window has not yet expired.

        PRD §3.9: "Every complaint sitting in `ANSWERED` whose `answered_at_utc` the logical
        clock has passed by strictly more than 30 days — the statutory reopen window, which the
        carrier cannot tune — moves `ANSWERED → CLOSED`, its terminal state, appending an activity
        row of type `AUTO_CLOSED` and refreshing the passenger's `open_complaint_count`."

        PRD §3.9: "For every complaint in scope, `ack_breached` becomes true when the logical
        clock has strictly passed `ack_due_utc` while `acknowledged_at_utc` is still null, and
        `answer_breached` becomes true when the clock has strictly passed `answer_due_utc` while
        the complaint's `status` is neither `ANSWERED` nor `CLOSED`."

        PRD §3.9: "The profile's `open_violation_count` is rewritten as the sum of three counts in
        scope: tarmac delay events whose `is_violation` is true, refund obligations whose
        `deadline_breached` is true, and consumer complaints whose `ack_breached` or
        `answer_breached` is true."

        Design: Corner/cross_cutting_complexity_layers/answered_complaint_auto_closes_only_past_thirty_days
        """
        world = _answered_complaint_at_its_thirty_day_boundary(api)

        swept = run_sweep(api, world.profile["id"])

        assert_sweep_counters(
            swept,
            complaint_auto_closed_count=0,
            complaint_answer_breach_flagged_count=0,
            open_violation_count=0,
        )
        still_open = read_complaint(api, world.complaint["id"])
        assert still_open["status"] == "ANSWERED", "the reopen window is still running"
        assert still_open["answer_breached"] is False

    def test_one_second_later_it_closes_and_stamps_the_trail(self, api):
        """The fourth activity row is the sweep's own AUTO_CLOSED entry.

        PRD §3.9: "Every complaint sitting in `ANSWERED` whose `answered_at_utc` the logical
        clock has passed by strictly more than 30 days — the statutory reopen window, which the
        carrier cannot tune — moves `ANSWERED → CLOSED`, its terminal state, appending an activity
        row of type `AUTO_CLOSED` and refreshing the passenger's `open_complaint_count`."

        PRD §3.2: "A newly registered passenger starts with `travel_credit_balance_cents` at 0
        and `open_complaint_count` at 0; the latter is maintained as the count of that passenger's
        complaints, across all of their bookings, whose status is `RECEIVED`, `ACKNOWLEDGED` or
        `INFO_REQUESTED`."

        PRD §3.8: "The trail is read in ascending `occurred_at_utc` order, tie-broken by
        ascending `created_at`, and is visible to compliance roles and the regulator auditor but
        not to the passenger."

        Design: Corner/cross_cutting_complexity_layers/answered_complaint_auto_closes_only_past_thirty_days
        """
        world = _answered_complaint_at_its_thirty_day_boundary(api)
        run_sweep(api, world.profile["id"])
        set_clock(api, "2026-09-05T09:00:01Z")

        swept = run_sweep(api, world.profile["id"])

        assert_sweep_counters(swept, complaint_auto_closed_count=1)
        assert read_complaint(api, world.complaint["id"])["status"] == "CLOSED"
        trail, meta = validate_paginated(
            api.list_complaint_activities(world.complaint["id"], OFFICER_HEADERS)
        )
        assert_list_meta(meta, total_count=4, has_more=False)
        assert_activity_types(
            trail, ["RECEIVED", "ACKNOWLEDGED", "ANSWERED", "AUTO_CLOSED"]
        )
        assert read_passenger(api, world.passenger["id"])["open_complaint_count"] == 0

    def test_a_closed_complaint_can_no_longer_be_reopened(self, api):
        """CLOSED is terminal, so the passenger's late letter cannot revive the case.

        PRD §3.9: "Every complaint sitting in `ANSWERED` whose `answered_at_utc` the logical
        clock has passed by strictly more than 30 days — the statutory reopen window, which the
        carrier cannot tune — moves `ANSWERED → CLOSED`, its terminal state, appending an activity
        row of type `AUTO_CLOSED` and refreshing the passenger's `open_complaint_count`."

        PRD §3.8: "Any of these chronology rules being violated is `ERR_ANSWER_BEFORE_RECEIPT`
        (HTTP 422), and an action attempted from the wrong status — acknowledging something not
        `RECEIVED`, requesting information on something not `ACKNOWLEDGED`, answering something
        that is neither `ACKNOWLEDGED` nor `INFO_REQUESTED`, or reopening something not
        `ANSWERED` — is `ERR_COMPLAINT_STATE_INVALID` (HTTP 409)."

        Design: Corner/cross_cutting_complexity_layers/answered_complaint_auto_closes_only_past_thirty_days
        """
        world = _answered_complaint_at_its_thirty_day_boundary(api)
        set_clock(api, "2026-09-05T09:00:01Z")
        run_sweep(api, world.profile["id"])

        refused = api.reopen_complaint(
            world.complaint["id"],
            f.reopen_payload("2026-09-05T10:00:00Z"),
            OFFICER_HEADERS,
        )

        validate_error(refused, ERR_COMPLAINT_STATE_INVALID, 409)
        assert read_complaint(api, world.complaint["id"])["status"] == "CLOSED"
        assert read_complaint(api, world.complaint["id"])["reopen_count"] == 0
