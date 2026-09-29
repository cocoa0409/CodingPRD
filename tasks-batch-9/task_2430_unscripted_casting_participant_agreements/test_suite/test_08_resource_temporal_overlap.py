"""Three different occupancy semantics on three different resources: the venue
under half-open buffered intervals, the minor under an aggregate cap bucketed by
UTC calendar date, and the venue again under closed intake windows with an
aggregate head capacity.
"""

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_money,
    get_shoot_block,
    setup_active_welfare_protocol,
    setup_casting_call,
    setup_cleared_applicant,
    setup_docusoap_production,
    setup_executed_agreement,
    setup_location,
    setup_minor_protection,
    setup_open_call,
    setup_production,
    setup_published_casting_call,
    setup_shoot_block,
    validate_error,
    validate_paginated,
    validate_success,
)

PA = TEST_USERS["production_admin_headers"]
CD = TEST_USERS["casting_director_headers"]

SEASON_COVERAGE = {
    "coverage_start_utc": "2026-09-15T00:00:00Z",
    "coverage_end_utc": "2026-12-15T00:00:00Z",
}

FOUR_EPISODE_DOCUSOAP = {
    "format_type": "DOCUSOAP",
    "jurisdiction_code": "CA",
    "episode_order": 4,
    "stipend_pool_cents": 10_000_000,
    "welfare_budget_cents": 10_000_000,
    "minor_participant_cap": 0,
}


class TestShootBlockTrailingBufferIsHalfOpen:
    """A venue is occupied from a block's start_utc up to but not including its
    buffered end."""

    def _stage_with_a_block_buffered_to_1230(self, title: str, season_number: int):
        production = setup_production(
            title=title, season_number=season_number, minor_participant_cap=0
        )
        stage = setup_location(
            name="Stage A",
            capacity=500,
            turnaround_buffer_minutes=60,
            filming_permit_number="PRM-1001",
        )
        base = setup_shoot_block(
            production["id"],
            stage["id"],
            block_kind="STUDIO",
            start_utc="2026-10-05T08:00:00Z",
            end_utc="2026-10-05T11:30:00Z",
            participant_agreement_ids=[],
            expected_crowd_headcount=0,
            onset_minor_hours=0,
        )
        assert base["status"] == "SCHEDULED"
        return production, stage, base

    def _payload(self, production_id, location_id, start_utc):
        return {
            "production_id": production_id,
            "location_id": location_id,
            "block_kind": "STUDIO",
            "start_utc": start_utc,
            "end_utc": "2026-10-05T14:00:00Z",
            "participant_agreement_ids": [],
            "expected_crowd_headcount": 0,
            "onset_minor_hours": 0,
        }

    def test_a_start_inside_the_trailing_buffer_collides(self, api):
        """PRD §3.8: "And the block must not collide with another block at the
        same venue: each block occupies the half-open interval that begins at its
        `start_utc` and ends at its `end_utc` extended by the venue's
        `turnaround_buffer_minutes`, and if that extended interval intersects the
        extended interval of any other block at the same location whose `status`
        is `SCHEDULED` or `ROLLING`, the scheduling is refused with
        `ERR_LOCATION_BLOCK_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/shoot_block_halfopen_interval_with_trailing_turnaround_buffer
        """
        production, stage, base = self._stage_with_a_block_buffered_to_1230(
            "Island Trials S11", 11
        )

        validate_error(
            api.create_shoot_block(
                self._payload(production["id"], stage["id"], "2026-10-05T12:00:00Z"),
                PA,
            ),
            ApiErrorId.ERR_LOCATION_BLOCK_CONFLICT.value,
            409,
        )

        rows, meta = validate_paginated(
            api.list_shoot_blocks(PA, {"location_id": stage["id"]})
        )
        assert meta["total_count"] == 1, "the colliding block was never created"
        assert rows[0]["id"] == base["id"]
        assert get_shoot_block(base["id"])["status"] == "SCHEDULED"

    def test_a_start_exactly_when_the_buffer_ends_is_accepted(self, api):
        """PRD §3.8: "Because the interval is half-open, a block beginning
        exactly when the previous block's buffer ends does not collide."
        PRD §3.8: "A newly scheduled block opens at `status` `SCHEDULED`, with
        `minor_participant_count` computed as the number of called agreements
        whose applicant is a minor, `covered_head_count` at 0 and
        `release_coverage_complete` false."

        Design: Difficulty/resource_temporal_overlap/shoot_block_halfopen_interval_with_trailing_turnaround_buffer
        """
        production, stage, base = self._stage_with_a_block_buffered_to_1230(
            "Island Trials S11 Adjacent", 12
        )

        # 11:30Z plus a 60-minute buffer is 12:30Z, and the right endpoint is
        # exclusive.
        adjacent = validate_success(
            api.create_shoot_block(
                self._payload(production["id"], stage["id"], "2026-10-05T12:30:00Z"),
                PA,
            ),
            201,
        )
        assert adjacent["status"] == "SCHEDULED"
        assert adjacent["start_utc"].startswith("2026-10-05T12:30")
        assert adjacent["minor_participant_count"] == 0
        assert adjacent["covered_head_count"] == 0
        assert adjacent["release_coverage_complete"] is False

        _rows, meta = validate_paginated(
            api.list_shoot_blocks(PA, {"location_id": stage["id"]})
        )
        assert meta["total_count"] == 2
        assert get_shoot_block(base["id"])["status"] == "SCHEDULED"


class TestMinorDailyHoursBucketByUtcDate:
    """Three time-disjoint, buffer-compliant blocks on one UTC date still share
    a single daily budget for the minor they all call."""

    def _three_blocks_on_one_date(self, title: str, season_number: int):
        production = setup_production(
            title=title,
            season_number=season_number,
            minor_participant_cap=2,
        )
        stage = setup_location(
            name="Stage A",
            capacity=500,
            turnaround_buffer_minutes=60,
            filming_permit_number="PRM-1001",
        )
        setup_active_welfare_protocol(
            production["id"],
            kind="DUTY_OF_CARE_OFFICER",
            cost_cents=1_000_000,
            **SEASON_COVERAGE,
        )
        call = setup_published_casting_call(
            production["id"], min_age=13, max_age=45, exclusivity_window_days=0
        )
        applicant = setup_cleared_applicant(
            call["id"],
            minor=True,
            legal_name="Rae Solis",
            date_of_birth="2011-05-20",
            guardian_name="Sam Solis",
        )
        setup_minor_protection(
            applicant["id"],
            work_permit_number="CA-WP-90210",
            permit_expires_on="2027-03-31",
            education_hours_scheduled_weekly=15,
            trust_deposit_pct=0.15,
        )
        agreement = setup_executed_agreement(applicant["id"], production["id"])
        assert_money(
            agreement["total_stipend_commitment_cents"], 220_000, "final stipend"
        )

        windows = (
            ("2026-10-06T06:00:00Z", "2026-10-06T08:00:00Z", 2.5),
            ("2026-10-06T09:30:00Z", "2026-10-06T11:00:00Z", 2.5),
            ("2026-10-06T12:30:00Z", "2026-10-06T13:30:00Z", 0.1),
        )
        blocks = [
            setup_shoot_block(
                production["id"],
                stage["id"],
                block_kind="STUDIO",
                start_utc=start,
                end_utc=end,
                participant_agreement_ids=[agreement["id"]],
                expected_crowd_headcount=0,
                onset_minor_hours=hours,
            )
            for start, end, hours in windows
        ]
        assert all(block["status"] == "SCHEDULED" for block in blocks)
        return production, blocks

    def test_a_bucket_total_of_exactly_eight_hours_is_admitted(self, api):
        """PRD §3.8: "The minor's on-set hours for that bucket are this block's
        `onset_minor_hours` plus the `onset_minor_hours` of every other shoot
        block of the same production whose `status` is `ROLLING` or `WRAPPED`,
        that lists the same agreement in its `participant_agreement_ids`, and
        whose `start_utc` falls on the same UTC calendar date; blocks still
        `SCHEDULED` and blocks already `CANCELLED` are excluded from that sum."
        PRD §3.8: "The minor's education hours for the day are their packet's
        `education_hours_scheduled_weekly` divided by 5, the number of tutoring
        days in a week."
        PRD §3.8: "If the sum of on-set hours and education hours for any called
        minor exceeds a total daily cap of 8.0 hours, the roll is refused with
        `ERR_MINOR_DAILY_HOURS_EXCEEDED`; a total of exactly 8.0 hours is
        permitted, since only a total above the cap is a violation."

        Design: Difficulty/resource_temporal_overlap/minor_daily_onset_hours_aggregate_over_utc_date_bucket
        """
        _production, blocks = self._three_blocks_on_one_date("Teen Trials S3", 3)

        first = validate_success(api.roll_shoot_block(blocks[0]["id"], PA))
        assert first["status"] == "ROLLING"
        assert first["minor_participant_count"] == 1

        # 2.5 already rolling plus this block's 2.5 plus 15 / 5 education hours
        # is exactly 8.0, and the comparison is strictly greater-than.
        second = validate_success(api.roll_shoot_block(blocks[1]["id"], PA))
        assert second["status"] == "ROLLING"

    def test_one_tenth_of_an_hour_past_the_cap_refuses_the_roll(self, api):
        """PRD §3.8: "If the sum of on-set hours and education hours for any
        called minor exceeds a total daily cap of 8.0 hours, the roll is refused
        with `ERR_MINOR_DAILY_HOURS_EXCEEDED`; a total of exactly 8.0 hours is
        permitted, since only a total above the cap is a violation."
        PRD §3.8: "The minor daily-hours rule deserves care, because it is
        aggregate-capacity semantics over a calendar-date bucket rather than a
        pairwise interval intersection: two blocks falling on the same UTC
        calendar date collide on the cap even when their clock intervals do not
        overlap at all."
        PRD §2.8: "On-set hours are carried to one decimal place, and the
        daily-hours violation test is a strict comparison: a total of exactly the
        cap is permitted, only a total above it is a violation."

        Design: Difficulty/resource_temporal_overlap/minor_daily_onset_hours_aggregate_over_utc_date_bucket
        """
        _production, blocks = self._three_blocks_on_one_date("Teen Trials S3 Over", 4)
        validate_success(api.roll_shoot_block(blocks[0]["id"], PA))
        validate_success(api.roll_shoot_block(blocks[1]["id"], PA))

        # The bucket already stands at 8.0; a further 0.1 takes it to 8.1, even
        # though 12:30Z..13:30Z overlaps neither earlier interval.
        validate_error(
            api.roll_shoot_block(blocks[2]["id"], PA),
            ApiErrorId.ERR_MINOR_DAILY_HOURS_EXCEEDED.value,
            422,
        )
        assert get_shoot_block(blocks[2]["id"])["status"] == "SCHEDULED"
        assert get_shoot_block(blocks[0]["id"])["status"] == "ROLLING"
        assert get_shoot_block(blocks[1]["id"])["status"] == "ROLLING"


class TestOpenCallWindowsAreClosedIntervals:
    """Intake windows are inclusive at both ends, so two windows that share only
    a single endpoint still contend for the same seats."""

    def _venue_with_a_live_three_hundred_seat_call(self, title: str, season_number: int):
        production = setup_docusoap_production(
            title=title, season_number=season_number, **FOUR_EPISODE_DOCUSOAP
        )
        venue = setup_location(
            name="Venue C", capacity=500, filming_permit_number="PRM-3003"
        )
        live = setup_open_call(
            production["id"],
            venue["id"],
            min_age=18,
            max_age=60,
            exclusivity_window_days=0,
            open_call_window_start_utc="2026-08-05T00:00:00Z",
            open_call_window_end_utc="2026-08-10T00:00:00Z",
            expected_attendance=300,
        )
        assert live["status"] == "PUBLISHED"
        return production, venue, live

    def _draft_two_fifty(self, production_id, venue_id, start_utc):
        return setup_casting_call(
            production_id,
            channel="OPEN_CALL",
            min_age=18,
            max_age=60,
            exclusivity_window_days=0,
            venue_location_id=venue_id,
            open_call_window_start_utc=start_utc,
            open_call_window_end_utc="2026-08-15T00:00:00Z",
            expected_attendance=250,
        )

    def test_windows_sharing_one_endpoint_still_contend_for_capacity(self, api):
        """PRD §3.2: "The venue capacity check then runs: the expected
        attendances of every other casting call at the same venue that is already
        `PUBLISHED`, has channel `OPEN_CALL`, and whose inclusive intake window
        intersects this one, are summed together with this call's own
        `expected_attendance`, and if that aggregate exceeds the venue's
        `capacity` the publication is refused with
        `ERR_VENUE_CAPACITY_EXCEEDED`."
        PRD §3.2: "Two inclusive windows intersect when neither one's start falls
        after the other's end."

        Design: Difficulty/resource_temporal_overlap/open_call_venue_attendance_aggregate_over_closed_windows
        """
        production, venue, live = self._venue_with_a_live_three_hundred_seat_call(
            "Harbour Lives Venue", 6
        )
        touching = self._draft_two_fifty(
            production["id"], venue["id"], "2026-08-10T00:00:00Z"
        )

        # 2026-08-10 is the live call's end and the draft's start, so neither
        # start falls after the other's end: 300 + 250 = 550 against 500 seats.
        validate_error(
            api.publish_casting_call(touching["id"], CD),
            ApiErrorId.ERR_VENUE_CAPACITY_EXCEEDED.value,
            409,
        )
        refused = validate_success(api.get_casting_call(touching["id"], CD))
        assert refused["status"] == "DRAFT"
        assert refused["published_at"] is None
        assert validate_success(api.get_casting_call(live["id"], CD))[
            "status"
        ] == "PUBLISHED"

    def test_a_window_starting_one_day_later_is_disjoint_and_publishes(self, api):
        """PRD §3.2: "Two inclusive windows intersect when neither one's start
        falls after the other's end."
        PRD §3.2: "On success the call's status becomes `PUBLISHED` and
        `published_at` is stamped with the logical clock's current instant."

        Design: Difficulty/resource_temporal_overlap/open_call_venue_attendance_aggregate_over_closed_windows
        """
        production, venue, live = self._venue_with_a_live_three_hundred_seat_call(
            "Harbour Lives Venue Disjoint", 7
        )
        disjoint = self._draft_two_fifty(
            production["id"], venue["id"], "2026-08-11T00:00:00Z"
        )

        # 2026-08-11 falls after the live call's 2026-08-10 end, so the windows
        # are disjoint and only this call's own 250 seats are counted.
        published = validate_success(api.publish_casting_call(disjoint["id"], CD))
        assert published["status"] == "PUBLISHED"
        assert published["published_at"] is not None
        assert validate_success(api.get_casting_call(live["id"], CD))[
            "status"
        ] == "PUBLISHED"
