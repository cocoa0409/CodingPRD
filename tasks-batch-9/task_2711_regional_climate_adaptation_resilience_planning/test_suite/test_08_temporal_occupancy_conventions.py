"""Closed buffered session windows collide on touch; half-open aid windows do not."""

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_all_null,
    assert_fields,
    assert_pact_conservation,
    commit_aid,
    commitment_payload,
    create_asset,
    create_harbor,
    create_pact,
    create_plan_cycle,
    create_ridge,
    create_session,
    engagement_session_payload,
    make_jurisdiction_delegate_headers,
    pact_version,
    read_commitment,
    read_pact,
    read_session,
    release_commitment,
    validate_error,
    validate_success,
)


class TestSessionBufferIsClosedAndPerHost:
    """A 24-hour buffer on each side, compared inclusively, and scoped per host."""

    @staticmethod
    def _cycle_with_one_scheduled_harbor_session():
        harbor = create_harbor()
        ridge = create_ridge()
        cycle = create_plan_cycle(
            quorum_weight_bps=6600, max_revision_rounds=1, required_session_count=1
        )
        session = create_session(
            cycle["id"],
            harbor["id"],
            modality="IN_PERSON",
            window_start="2026-09-10T17:00:00Z",
            window_end="2026-09-10T20:00:00Z",
        )
        return {"harbor": harbor, "ridge": ridge, "cycle": cycle, "session": session}

    def test_a_booking_exactly_24_hours_after_the_incumbent_ends_still_conflicts(self):
        """Equality in the buffered comparison rejects the booking.

        PRD 3.8: "a candidate conflicts with an existing session when the candidate's
        `window_start` is at or before the existing session's `window_end` extended
        forward by 24 hours **and** the existing session's `window_start` is at or
        before the candidate's `window_end` extended forward by 24 hours. Because both
        comparisons are inclusive, touching endpoints do conflict, and a booking that
        starts *exactly* 24 hours after another session ends still conflicts. Any
        conflict rejects the booking with `ERR_SESSION_WINDOW_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/session_closed_interval_plus_buffer_blocks_a_host_jurisdiction
        """
        context = self._cycle_with_one_scheduled_harbor_session()

        response = api_client.create_engagement_session(
            context["cycle"]["id"],
            engagement_session_payload(
                context["harbor"]["id"],
                modality="HYBRID",
                window_start="2026-09-11T20:00:00Z",
                window_end="2026-09-11T22:00:00Z",
            ),
            make_jurisdiction_delegate_headers(context["harbor"]["id"]),
        )

        validate_error(response, ApiErrorId.ERR_SESSION_WINDOW_CONFLICT.value, 409)
        assert_fields(
            read_session(context["session"]["id"]),
            {"status": "SCHEDULED"},
            "the incumbent session a refused booking must not disturb",
        )

    def test_the_identical_window_is_free_for_another_host_and_past_the_buffer(self):
        """Occupancy is per host, and a start past the buffered end is admitted.

        PRD 3.8: "Occupancy is strictly per host: the identical window hosted by a
        different member jurisdiction is admitted, and once a conflicting session has
        been cancelled by a failed cycle the previously blocked candidate becomes
        admissible."  A fresh booking carries no attendance yet, since PRD 3.8 says "A
        newly scheduled session reads `status` `SCHEDULED` with `attendee_count`,
        `disadvantaged_attendee_count`, `equity_reach_bps` and
        `preferred_strategy_type` all null."

        Design: Difficulty/resource_temporal_overlap/session_closed_interval_plus_buffer_blocks_a_host_jurisdiction
        """
        context = self._cycle_with_one_scheduled_harbor_session()

        ridge_response = api_client.create_engagement_session(
            context["cycle"]["id"],
            engagement_session_payload(
                context["ridge"]["id"],
                modality="HYBRID",
                window_start="2026-09-11T20:00:00Z",
                window_end="2026-09-11T22:00:00Z",
            ),
            make_jurisdiction_delegate_headers(context["ridge"]["id"]),
        )
        ridge_session = validate_success(ridge_response, 201)
        assert_fields(
            ridge_session,
            {"host_jurisdiction_id": context["ridge"]["id"], "status": "SCHEDULED"},
            "the identical window under a different host",
        )

        later_response = api_client.create_engagement_session(
            context["cycle"]["id"],
            engagement_session_payload(
                context["harbor"]["id"],
                modality="VIRTUAL",
                window_start="2026-09-12T00:00:00Z",
                window_end="2026-09-12T02:00:00Z",
            ),
            make_jurisdiction_delegate_headers(context["harbor"]["id"]),
        )
        later_session = validate_success(later_response, 201)
        assert_fields(later_session, {"status": "SCHEDULED"}, "the booking past the buffer")
        assert_all_null(
            later_session,
            [
                "attendee_count",
                "disadvantaged_attendee_count",
                "equity_reach_bps",
                "preferred_strategy_type",
            ],
            "a session that has not been held yet",
        )
        assert_fields(
            read_session(context["session"]["id"]),
            {"status": "SCHEDULED"},
            "the incumbent session, untouched by either booking",
        )


class TestAidCapacityIsAnAggregatePeak:
    """Peak load over half-open windows, where exact adjacency does not overlap."""

    @staticmethod
    def _pact_reserving_eight_of_ten_units():
        harbor = create_harbor()
        ridge = create_ridge()
        asset = create_asset(harbor["id"], is_shared=True)
        pact = create_pact(harbor["id"], pledged_units=10, max_concurrent_commitments=4)
        first = commit_aid(
            pact["id"], ridge["id"], asset["id"], 4,
            "2026-09-05T00:00:00Z", "2026-09-15T00:00:00Z",
        )
        second = commit_aid(
            pact["id"], ridge["id"], asset["id"], 4,
            "2026-09-10T00:00:00Z", "2026-09-20T00:00:00Z",
        )
        return {
            "harbor": harbor,
            "ridge": ridge,
            "asset": asset,
            "pact": pact,
            "first": first,
            "second": second,
        }

    def test_a_third_overlapping_window_breaches_the_pledge_not_the_count(self):
        """Load 4 plus 4 plus 3 at one instant exceeds a pledge of 10.

        PRD 3.9: "The peak **unit load** must be less than or equal to the pact's
        `pledged_units`; a peak that exceeds the pledge yields
        `ERR_AID_CAPACITY_EXCEEDED`."  PRD 3.9 also warns that the check is
        collective: "Note carefully that **aggregate** capacity is checked, not
        pairwise overlap: three commitments that are each individually admissible can
        collectively breach the pledge at a single instant, and the third one is the
        one rejected."  With `max_concurrent_commitments` 4 the count gate cannot fire.

        Design: Difficulty/resource_temporal_overlap/aid_commitment_half_open_windows_admit_exact_adjacency_at_the_pledge
        """
        context = self._pact_reserving_eight_of_ten_units()
        pact_id = context["pact"]["id"]

        response = api_client.create_commitment(
            pact_id,
            commitment_payload(
                context["ridge"]["id"],
                context["asset"]["id"],
                3,
                "2026-09-12T00:00:00Z",
                "2026-09-14T00:00:00Z",
                pact_version(pact_id),
            ),
            make_jurisdiction_delegate_headers(context["ridge"]["id"]),
        )

        validate_error(response, ApiErrorId.ERR_AID_CAPACITY_EXCEEDED.value, 409)
        pact = read_pact(pact_id)
        assert_fields(
            pact,
            {"reserved_units": 8, "free_units": 2, "status": "OPEN", "version": 3},
            "the pact a refused commitment must leave untouched",
        )
        assert_pact_conservation(pact)

    def test_after_a_release_a_window_starting_on_the_hour_another_ends_fills_the_pledge(self):
        """Release restores the ledger, then exact adjacency admits a peak of exactly 10.

        PRD 3.9: "Occupation intervals are **half-open**: a commitment occupies its
        `window_start` and every instant up to but not including its `window_end`, so
        a commitment that ends at exactly the instant another one begins does **not**
        overlap it."  PRD 3.9 admits the boundary — "A peak landing exactly on
        `pledged_units` is admitted." — and re-derives the pact status: "then
        `EXHAUSTED` when `free_units` is exactly 0; then `OPEN` otherwise."

        Design: Difficulty/resource_temporal_overlap/aid_commitment_half_open_windows_admit_exact_adjacency_at_the_pledge
        """
        context = self._pact_reserving_eight_of_ten_units()
        pact_id = context["pact"]["id"]

        release_commitment(context["second"]["id"], context["ridge"]["id"])

        released = read_commitment(context["second"]["id"])
        assert_fields(released, {"status": "RELEASED"}, "the released commitment")
        assert released["released_at"] is not None, (
            "PRD 3.9 stamps `released_at` from the logical clock on release, "
            f"found {released['released_at']}"
        )
        pact_after_release = read_pact(pact_id)
        assert_fields(
            pact_after_release,
            {"reserved_units": 4, "free_units": 6, "status": "OPEN"},
            "the pact after the peak was recomputed over the survivors",
        )
        assert_pact_conservation(pact_after_release)

        response = api_client.create_commitment(
            pact_id,
            commitment_payload(
                context["ridge"]["id"],
                context["asset"]["id"],
                10,
                "2026-09-15T00:00:00Z",
                "2026-09-18T00:00:00Z",
                pact_after_release["version"],
            ),
            make_jurisdiction_delegate_headers(context["ridge"]["id"]),
        )

        commitment = validate_success(response, 201)
        assert_fields(
            commitment,
            {"committed_units": 10, "status": "COMMITTED"},
            "the commitment that starts exactly when the earlier one ends",
        )
        pact = read_pact(pact_id)
        assert_fields(
            pact,
            {"reserved_units": 10, "free_units": 0, "status": "EXHAUSTED", "version": 5},
            "the pact filled exactly to its pledge",
        )
        assert_pact_conservation(pact)
