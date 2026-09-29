"""Machines that fork and re-enter: the two obligation axes and the tarmac forks."""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import (
    ADMIN_HEADERS,
    ERR_CORRECTIVE_ACTION_REQUIRED,
    OFFICER_2,
    OFFICER_2_HEADERS,
    OFFICER_3_HEADERS,
    OPS_HEADERS,
    assert_booking_ledger,
    assert_instant,
    assert_null,
    assert_obligation_amounts,
    assert_obligation_axes,
    assert_segment_state,
    assert_sweep_counters,
    build_world,
    cancel_segment,
    complete,
    create_booking,
    create_passenger,
    create_policy_profile,
    factories as f,
    initiate,
    read_booking,
    read_obligation,
    read_profile,
    read_segment,
    read_tarmac_event,
    record_operation,
    run_sweep,
    set_clock,
    sole_obligation,
)

# ─── The two obligation axes ──────────────────────────


def _auto_defaulted_obligation(api):
    """A cancelled 100000-cent booking whose election window has just lapsed."""
    set_clock(api, "2026-08-10T18:00:00Z")
    world = build_world(
        api,
        total_fare_cents=100000,
        segment_fares=[100000],
        record_locator="AXE001",
        email="axes@example.com",
    )
    cancel_segment(api, world.segments[0]["id"], "2026-08-10T18:00:00Z")
    world.obligation = sole_obligation(api, world.booking["id"])
    set_clock(api, "2026-08-15T18:00:01Z")
    world.sweep = run_sweep(api, world.profile["id"])
    return world


class TestObligationAxesAdvanceIndependently:
    def test_auto_default_moves_the_election_axis_and_leaves_settlement_unsettled(
        self, api
    ):
        """The sweep elects cash for the passenger without touching the money track.

        PRD §3.9: "For every obligation whose `election_status` still reads
        `PENDING_ELECTION` and whose `election_deadline_utc` the logical clock has
        strictly passed, the election axis advances `PENDING_ELECTION → ELECTED_CASH`
        with `election_source` recorded as `AUTO_DEFAULT` and the `settlement_method`
        resolved from the booking's `payment_method` exactly as in §3.7."

        PRD §3.9: "The settlement axis is untouched by this phase and stays at
        `UNSETTLED`."

        Design: Difficulty/non_linear_state_machine/obligation_election_and_settlement_axes_advance_independently
        """
        world = _auto_defaulted_obligation(api)

        assert_sweep_counters(
            world.sweep, election_auto_defaulted_count=1, deadline_breach_flagged_count=0
        )
        obligation = read_obligation(api, world.obligation["id"])
        assert_obligation_axes(
            obligation,
            election_status="ELECTED_CASH",
            election_source="AUTO_DEFAULT",
            settlement_method="ORIGINAL_PAYMENT",
            settlement_status="UNSETTLED",
            settlement_attempt_count=0,
        )
        assert_obligation_amounts(
            obligation, credit_bonus_cents=0, payable_total_cents=100000
        )

    def test_failed_settlement_retry_re_enters_initiated_and_leaves_the_election_alone(
        self, api
    ):
        """A processor timeout returns the row to FAILED and the retry counts twice.

        PRD §3.7: "A `FAILED` outcome requires a `failure_reason` of `CARD_DECLINED`,
        `ACCOUNT_CLOSED` or `PROCESSOR_TIMEOUT`, omitting which is
        `ERR_FAILURE_REASON_REQUIRED`; it moves the axis `INITIATED → FAILED`, stores
        the reason as `last_failure_reason`, clears `settlement_initiated_by_user_id`
        back to null so the retry is unblocked for that officer, and advances the
        obligation's `version` by 1."

        PRD §3.7: "The axes move without disturbing each other: the automatic default
        described in §3.9 advances the election axis while the settlement axis stays at
        `UNSETTLED`, and a retry after failure advances the settlement axis while
        leaving `election_status` and `election_source` exactly as they were."

        Design: Difficulty/non_linear_state_machine/obligation_election_and_settlement_axes_advance_independently
        """
        world = _auto_defaulted_obligation(api)
        obligation_id = world.obligation["id"]

        initiate(api, obligation_id, OFFICER_2_HEADERS)
        first = read_obligation(api, obligation_id)
        complete(
            api,
            obligation_id,
            OFFICER_3_HEADERS,
            outcome="FAILED",
            failure_reason="PROCESSOR_TIMEOUT",
        )
        failed = read_obligation(api, obligation_id)
        initiate(api, obligation_id, OFFICER_2_HEADERS)
        retried = read_obligation(api, obligation_id)

        assert_obligation_axes(
            first, settlement_status="INITIATED", settlement_attempt_count=1
        )
        assert_obligation_axes(
            failed, settlement_status="FAILED", settlement_attempt_count=1
        )
        assert failed["last_failure_reason"] == "PROCESSOR_TIMEOUT"
        assert_null(failed["settlement_initiated_by_user_id"], "settlement_initiated_by_user_id")
        assert_obligation_axes(
            retried,
            settlement_status="INITIATED",
            settlement_attempt_count=2,
            election_status="ELECTED_CASH",
            election_source="AUTO_DEFAULT",
        )
        assert retried["settlement_initiated_by_user_id"] == OFFICER_2
        assert_booking_ledger(
            read_booking(api, world.booking["id"]), total_refund_obligated_cents=100000
        )


# ─── The tarmac fork and its join ─────────────────────


def _two_tarmac_events(api):
    """One occupation closed by exemption, one closed by deplaning, on two legs."""
    set_clock(api, "2026-08-10T23:00:00Z")
    profile = create_policy_profile(api, "ZQ")
    passenger = create_passenger(api, "tarmac@example.com", "Tam Arnac")
    booking = create_booking(
        api, passenger["id"], profile["id"], "TAR001", 60000, "CREDIT_CARD"
    )
    seg1 = validate_success(
        api.create_flight_segment(
            booking["id"],
            f.flight_segment_payload(
                sequence_index=1,
                flight_number="ZQ101",
                origin_iata="LAX",
                destination_iata="DEN",
                scheduled_departure_utc="2026-08-10T14:00:00Z",
                scheduled_arrival_utc="2026-08-10T17:00:00Z",
                segment_fare_cents=30000,
            ),
            OPS_HEADERS,
        ),
        201,
    )
    seg2 = validate_success(
        api.create_flight_segment(
            booking["id"],
            f.flight_segment_payload(
                sequence_index=2,
                flight_number="ZQ202",
                origin_iata="DEN",
                destination_iata="ORD",
                scheduled_departure_utc="2026-08-10T18:30:00Z",
                scheduled_arrival_utc="2026-08-10T21:00:00Z",
                segment_fare_cents=30000,
            ),
            OPS_HEADERS,
        ),
        201,
    )
    exempted = validate_success(
        api.create_tarmac_delay_event(
            f.tarmac_event_payload(seg1["id"], "2026-08-10T14:10:00Z", "DEPARTURE"),
            OPS_HEADERS,
        ),
        201,
    )
    deplaned = validate_success(
        api.create_tarmac_delay_event(
            f.tarmac_event_payload(seg2["id"], "2026-08-10T18:40:00Z", "DEPARTURE"),
            OPS_HEADERS,
        ),
        201,
    )
    validate_success(
        api.claim_tarmac_exemption(
            exempted["id"],
            f.exemption_payload("2026-08-10T14:40:00Z", "SAFETY"),
            OPS_HEADERS,
        )
    )
    validate_success(
        api.deplane_tarmac_event(
            deplaned["id"], f.deplane_payload("2026-08-10T22:00:00Z"), OPS_HEADERS
        )
    )
    record_operation(api, seg1["id"], "DEPARTED", "2026-08-10T15:00:00Z")
    record_operation(api, seg2["id"], "DEPARTED", "2026-08-10T22:30:00Z")
    return profile, seg1, seg2, exempted, deplaned


class TestTarmacForkAndJoin:
    def test_exemption_branch_cures_the_breach_while_deplaning_records_it(self, api):
        """Thirty exempted minutes stay off the leg's clock; two hundred deplaned do not.

        PRD §3.5: "The event moves `DELAY_ACTIVE → EXEMPTION_INVOKED`, its
        `interval_end_utc` is set to the declaration instant, its `tarmac_minutes` is
        computed the same way as on the deplaning branch, and its `is_violation` is
        forced to **false** regardless of how many minutes elapsed, because a valid
        safety, security or air-traffic-control ground cures the breach."

        PRD §3.5: "The leg-level accounting differs from the deplaning branch in a way
        worth stating twice: the leg's `exempted_tarmac_event_count` grows by 1 — it
        counts every event on the leg carrying a non-null `exemption_reason` — while the
        leg's `cumulative_tarmac_minutes` is **not** increased, because exemption-closed
        minutes are excluded from the leg's accumulated tarmac time even after the event
        is later reported."

        Design: Difficulty/non_linear_state_machine/tarmac_event_fork_join_exemption_versus_deplane_branches
        """
        _, seg1, seg2, exempted, deplaned = _two_tarmac_events(api)

        exempted_row = read_tarmac_event(api, exempted["id"], seg1["id"])
        deplaned_row = read_tarmac_event(api, deplaned["id"], seg2["id"])

        assert exempted_row["status"] == "EXEMPTION_INVOKED"
        assert_instant(exempted_row["interval_end_utc"], "2026-08-10T14:40:00Z")
        assert exempted_row["tarmac_minutes"] == 30
        assert exempted_row["is_violation"] is False
        assert deplaned_row["status"] == "DEPLANED"
        assert_instant(deplaned_row["interval_end_utc"], "2026-08-10T22:00:00Z")
        assert deplaned_row["tarmac_minutes"] == 200
        assert deplaned_row["deadline_minutes"] == 180
        assert deplaned_row["is_violation"] is True
        assert_segment_state(
            read_segment(api, seg1["id"]),
            cumulative_tarmac_minutes=0,
            exempted_tarmac_event_count=1,
        )
        assert_segment_state(
            read_segment(api, seg2["id"]),
            cumulative_tarmac_minutes=200,
            exempted_tarmac_event_count=0,
        )

    def test_both_forks_join_at_report_filed_but_only_the_violation_needs_a_narrative(
        self, api
    ):
        """The exempted event files bare; the violating one must explain itself first.

        PRD §3.5: "On the deplaning branch, an event whose `is_violation` is true
        requires a narrative `corrective_action_summary`, and omitting it is
        `ERR_CORRECTIVE_ACTION_REQUIRED`; a compliant deplaned event needs no
        narrative."

        PRD §3.5: "Filing moves the event to `REPORT_FILED` — its terminal state,
        reached from either fork — storing `report_reference`, the
        `corrective_action_summary` when one was supplied, and `report_filed_at_utc`
        from the supplied `filed_at_utc`, and advancing the event's `version` by 1."

        Design: Difficulty/non_linear_state_machine/tarmac_event_fork_join_exemption_versus_deplane_branches
        """
        profile, seg1, seg2, exempted, deplaned = _two_tarmac_events(api)

        validate_success(
            api.file_tarmac_report(
                exempted["id"],
                f.file_report_payload("TDR-EXEMPT-1", "2026-08-10T23:00:00Z"),
                ADMIN_HEADERS,
            )
        )
        refused = api.file_tarmac_report(
            deplaned["id"],
            f.file_report_payload("TDR-DEPLANE-1", "2026-08-10T23:00:00Z"),
            ADMIN_HEADERS,
        )
        validate_error(refused, ERR_CORRECTIVE_ACTION_REQUIRED, 422)
        assert read_tarmac_event(api, deplaned["id"], seg2["id"])["status"] == "DEPLANED"

        validate_success(
            api.file_tarmac_report(
                deplaned["id"],
                f.file_report_payload(
                    "TDR-DEPLANE-1",
                    "2026-08-10T23:00:00Z",
                    corrective_action_summary="Crew retrained on the two-hour water rule.",
                ),
                ADMIN_HEADERS,
            )
        )

        exempted_row = read_tarmac_event(api, exempted["id"], seg1["id"])
        deplaned_row = read_tarmac_event(api, deplaned["id"], seg2["id"])
        assert exempted_row["status"] == "REPORT_FILED"
        assert deplaned_row["status"] == "REPORT_FILED"
        assert_null(exempted_row["corrective_action_summary"], "corrective_action_summary")
        assert read_profile(api, profile["id"])["open_violation_count"] == 0, (
            "the rollup only moves when the sweep runs"
        )

    def test_the_leg_keeps_a_tarmac_event_per_occupation(self, api):
        """Each leg carries exactly the one occupation recorded against it.

        PRD §3.5: "A tarmac delay event records one occurrence of an aircraft holding
        passengers on the ground on one leg."

        Design: Difficulty/non_linear_state_machine/tarmac_event_fork_join_exemption_versus_deplane_branches
        """
        _, seg1, seg2, _, _ = _two_tarmac_events(api)

        _, first_meta = validate_paginated(
            api.list_segment_tarmac_events(seg1["id"], ADMIN_HEADERS)
        )
        _, second_meta = validate_paginated(
            api.list_segment_tarmac_events(seg2["id"], ADMIN_HEADERS)
        )

        assert first_meta["total_count"] == 1
        assert second_meta["total_count"] == 1
