"""Comment-period arithmetic, meeting booking gates and comment intake.

The participation plan is where community burden turns into procedural time, so
the window's boundaries, the day cap, the venue gates and the adequacy audit are
all exercised against the clock.
"""

from test_helpers import (
    ADEQUACY_DEFICIENT,
    ADEQUACY_PENDING,
    ADMIN_HEADERS,
    ApiErrorId,
    BASE_COMMENT_DAYS,
    DEFICIENCY_LANGUAGE_ACCESS_GAP,
    LIAISON_HEADERS,
    MAX_COMMENT_DAYS,
    MEETING_CANCELLED,
    PLAN_CLOSED,
    PLAN_EXTENDED,
    PLAN_OPEN,
    PLAN_PLANNED,
    TRACK_ENHANCED,
    VENUE_ACTIVE,
    add_meeting,
    assert_field,
    assert_fields,
    assert_no_updated_at_field,
    assert_no_version_field,
    assert_created,
    assert_rejected,
    build_app_a_screened,
    cancel_meeting_payload,
    extend_plan_payload,
    find_meeting,
    meeting_payload,
    open_plan,
    open_plan_payload,
    public_comment_payload,
    read_application,
    read_area,
    read_plan,
    read_venue,
    resident_headers,
    set_clock,
    translate_plan,
    validate_success,
    venue_payload,
)


class TestCommentPeriodOpening:
    """PRD §3.4 will not let a window start in the past."""

    def test_comment_start_date_before_the_clock_is_rejected(self, api, area_k_screened):
        """A start date one day behind the clock leaves the plan untouched.

        PRD §3.4: "**Opening** the period moves the plan `PLANNED → OPEN`: the
        liaison supplies `comment_start_date`, which must be on or after the clock
        date — an earlier date is refused with `ERR_COMMENT_START_IN_PAST` — and
        the server derives `comment_end_date` as `comment_start_date` plus
        `required_comment_days` plus `granted_extension_days`, minus one day, so
        that the window is a closed interval inclusive of both its first and last
        day."

        Design: Corner/validations/comment_start_date_before_clock_rejected
        """
        state = area_k_screened
        response = api.open_comment_period(
            state["plan_id"], open_plan_payload("2026-07-31"), LIAISON_HEADERS
        )

        assert_rejected(response, ApiErrorId.COMMENT_START_IN_PAST)

        plan = read_plan(api, state["plan_id"])
        assert_fields(
            plan,
            {
                "status": PLAN_PLANNED,
                "required_comment_days": BASE_COMMENT_DAYS,
                "comment_start_date": None,
                "comment_end_date": None,
            },
        )
        assert_field(
            read_application(api, state["app_id"]), "review_track", TRACK_ENHANCED
        )


class TestCommentPeriodClosing:
    """PRD §3.4 requires the clock to be strictly past the final window day."""

    def test_close_on_the_last_window_day_is_rejected(self, api, area_k_screened):
        """2026-08-30 is inside the window, so the period has not elapsed yet.

        PRD §3.4: "**Closing** the period moves the plan `OPEN → CLOSED` or
        `EXTENDED → CLOSED`, and is permitted only once the clock date is strictly
        later than `comment_end_date`; closing on or before the last day of the
        window is refused with `ERR_COMMENT_PERIOD_NOT_ELAPSED`."

        Design: Corner/validations/close_on_the_last_window_day_rejected
        """
        state = area_k_screened
        opened = open_plan(api, state, "2026-08-01")
        assert_field(opened, "comment_end_date", "2026-08-30")
        set_clock(api, "2026-08-30T12:00:00Z")

        response = api.close_comment_period(state["plan_id"], LIAISON_HEADERS)

        assert_rejected(response, ApiErrorId.COMMENT_PERIOD_NOT_ELAPSED)

        plan = read_plan(api, state["plan_id"])
        assert_fields(
            plan,
            {
                "status": PLAN_OPEN,
                "adequacy_status": ADEQUACY_PENDING,
                "deficiency_codes": [],
            },
        )
        assert_field(read_area(api, state["area_id"]), "open_plan_count", 1)


class TestCommentPeriodExtension:
    """PRD §3.4 caps the total comment window at 120 days."""

    def test_extend_reaches_the_cap_then_rejects_one_more_day(self, api, clock):
        """Sixty extra days land exactly on the ceiling; day 121 is refused.

        PRD §3.4: "The liaison supplies `additional_days` and a `reason`." and
        "The sum of `required_comment_days`, the current `granted_extension_days`
        and the requested `additional_days` may not exceed the 120-day ceiling;
        exceeding it is refused with `ERR_COMMENT_DAYS_CAP_EXCEEDED`." and "A
        permitted extension adds `additional_days` to `granted_extension_days`,
        adds the same number of days to `comment_end_date`, and increments the
        plan's `version` by 1."

        Design: Corner/calculations/plan_extend_reaches_cap_then_rejects_one_more_day
        """
        state = build_app_a_screened(api)
        translate_plan(api, state, languages=["es"], materials_translated=True)
        opened = open_plan(api, state, "2026-08-01")
        assert_field(opened, "required_comment_days", 60)
        assert_field(opened, "comment_end_date", "2026-09-29")

        granted = validate_success(
            api.extend_comment_period(
                state["plan_id"],
                extend_plan_payload(60, "Community requested more time"),
                LIAISON_HEADERS,
            )
        )
        assert_fields(
            granted,
            {
                "status": PLAN_EXTENDED,
                "required_comment_days": 60,
                "granted_extension_days": 60,
                "comment_end_date": "2026-11-28",
            },
        )
        assert granted["required_comment_days"] + granted["granted_extension_days"] == (
            MAX_COMMENT_DAYS
        ), "the plan should sit exactly on the 120-day ceiling"

        response = api.extend_comment_period(
            state["plan_id"],
            extend_plan_payload(1, "One more day of outreach"),
            LIAISON_HEADERS,
        )

        assert_rejected(response, ApiErrorId.COMMENT_DAYS_CAP_EXCEEDED)

        plan = read_plan(api, state["plan_id"])
        assert_fields(
            plan,
            {
                "status": PLAN_EXTENDED,
                "granted_extension_days": 60,
                "comment_end_date": "2026-11-28",
            },
        )


class TestMeetingBookingGates:
    """PRD §3.5 puts four gates in front of every booking."""

    def test_meeting_outside_the_comment_window_is_rejected(
        self, api, area_k_screened_with_venue
    ):
        """A September slot cannot serve a window that closed on 2026-08-30.

        PRD §3.5: "The meeting must sit inside the comment window: both the
        `starts_at` date and the `ends_at` date must fall within the plan's closed
        comment window, inclusive of both ends, or the booking is refused with
        `ERR_MEETING_OUTSIDE_COMMENT_WINDOW`."

        Design: Corner/validations/meeting_outside_comment_window_rejected
        """
        state = area_k_screened_with_venue
        open_plan(api, state, "2026-08-01")

        response = api.create_public_meeting(
            meeting_payload(
                participation_plan_id=state["plan_id"],
                venue_id=state["venue_id"],
                starts_at="2026-09-05T18:00:00Z",
                ends_at="2026-09-05T20:00:00Z",
            ),
            LIAISON_HEADERS,
        )

        assert_rejected(response, ApiErrorId.MEETING_OUTSIDE_COMMENT_WINDOW)

        plan = read_plan(api, state["plan_id"])
        assert_field(plan, "comment_end_date", "2026-08-30")
        assert_field(plan, "meeting_count", 0)
        assert_field(read_venue(api, state["venue_id"]), "booked_meeting_count", 0)

    def test_inaccessible_venue_cannot_host_a_meeting(self, api, area_k_screened):
        """ADA access alone is not enough when the venue has no transit.

        PRD §3.5: "The venue must be genuinely reachable: both `ada_accessible`
        and `transit_accessible` must be true, or the booking is refused with
        `ERR_VENUE_NOT_ACCESSIBLE`."

        Design: Corner/validations/inaccessible_venue_cannot_host_a_meeting
        """
        state = area_k_screened
        open_plan(api, state, "2026-08-01")
        venue = assert_created(
            api.create_venue(
                venue_payload(
                    name="Madera Rural Grange Hall",
                    address="9900 Avenue 12, Madera CA",
                    capacity=80,
                    transit_accessible=False,
                    ada_accessible=True,
                    interpretation_capable=False,
                ),
                ADMIN_HEADERS,
            )
        )

        response = api.create_public_meeting(
            meeting_payload(
                participation_plan_id=state["plan_id"],
                venue_id=venue["id"],
                starts_at="2026-08-20T18:00:00Z",
                ends_at="2026-08-20T20:00:00Z",
            ),
            LIAISON_HEADERS,
        )

        assert_rejected(response, ApiErrorId.VENUE_NOT_ACCESSIBLE)

        stored_venue = read_venue(api, venue["id"])
        assert_field(stored_venue, "status", VENUE_ACTIVE)
        assert_field(stored_venue, "booked_meeting_count", 0)
        assert_field(read_plan(api, state["plan_id"]), "meeting_count", 0)


class TestMeetingCancellation:
    """PRD §3.5 releases the slot once and refuses a second cancellation."""

    def test_cancelling_an_already_cancelled_meeting_is_rejected(self, api, clock):
        """The venue ledger must not be decremented twice for one meeting.

        PRD §3.5: "The liaison may cancel a scheduled meeting, optionally
        supplying a `reason`; the meeting moves `SCHEDULED → CANCELLED`, the
        venue's `booked_meeting_count` and the plan's `meeting_count` are each
        decremented by 1, and the buffer-expanded interval is released immediately
        so a previously conflicting booking now succeeds." and "Cancelling an
        already-cancelled meeting is refused with `ERR_INVALID_MEETING_STATE`."

        Design: Corner/state_machines/meeting_cancel_twice_rejected
        """
        state = build_app_a_screened(api, with_venue=True)
        translate_plan(api, state, languages=["es"], materials_translated=True)
        open_plan(api, state, "2026-08-01")
        meeting = add_meeting(
            api, state, "2026-08-20T18:00:00Z", "2026-08-20T20:30:00Z", ["es"]
        )
        first = validate_success(
            api.cancel_public_meeting(
                meeting["id"], cancel_meeting_payload("Venue flooded"), LIAISON_HEADERS
            )
        )
        assert_field(first, "status", MEETING_CANCELLED)

        response = api.cancel_public_meeting(
            meeting["id"], cancel_meeting_payload("Cancelled again by mistake"), LIAISON_HEADERS
        )

        assert_rejected(response, ApiErrorId.INVALID_MEETING_STATE)

        assert_field(
            find_meeting(api, state["plan_id"], meeting["id"]), "status", MEETING_CANCELLED
        )
        assert_field(read_venue(api, state["venue_id"]), "booked_meeting_count", 0)
        assert_field(read_plan(api, state["plan_id"]), "meeting_count", 0)


class TestPublicCommentIntake:
    """PRD §3.5 files comments as immutable records."""

    def test_public_comment_is_immutable_and_carries_no_version_field(self, api, clock):
        """A comment is a write-once record with no mutable bookkeeping.

        PRD §3.5: "Public comments are immutable records: like applicability
        determinations, they carry only `id` and `created_at`."
        PRD §3.5: "On acceptance the server computes `in_required_language`, which
        is true when the comment's `language` is `"en"` or is one of the plan's
        `translated_languages` at filing time, and false otherwise; the default
        for the field is true." and "Filing increments the plan's `comment_count`
        by 1."

        Design: Corner/entities/public_comment_is_immutable_and_carries_no_version_field
        """
        state = build_app_a_screened(api)
        translate_plan(api, state, languages=["es"], materials_translated=True)
        open_plan(api, state, "2026-08-01")

        response = api.create_public_comment(
            public_comment_payload(
                participation_plan_id=state["plan_id"],
                submitter_name="Maria Solis",
                language="es",
                body="El polvo del sitio entra en las casas cada tarde.",
            ),
            resident_headers(7),
        )

        comment = assert_created(response)
        assert_no_version_field(comment, "public comment")
        assert_no_updated_at_field(comment, "public comment")
        assert_fields(
            comment,
            {
                "participation_plan_id": state["plan_id"],
                "submitter_name": "Maria Solis",
                "language": "es",
                "in_required_language": True,
                "requires_response": False,
            },
        )

        assert_field(read_plan(api, state["plan_id"]), "comment_count", 1)


class TestParticipationAdequacy:
    """PRD §3.4 audits the closed window in a fixed four-part order."""

    def test_comment_in_untranslated_language_marks_the_plan_deficient(
        self, api, area_l_comment_scenario
    ):
        """A Vietnamese comment against a Spanish-only plan is a language gap.

        PRD §3.4: "Fourth, if any public comment filed against this plan has
        `in_required_language` false, `LANGUAGE_ACCESS_GAP` is appended." and "If
        `deficiency_codes` ends up empty, `adequacy_status` is `COMPLIANT`;
        otherwise it is `DEFICIENT`."
        PRD §3.4: "Add a further 15 days when the area's `translation_required`
        flag is true."

        Design: Corner/endpoints/comment_in_untranslated_language_marks_plan_deficient
        """
        state = area_l_comment_scenario
        set_clock(api, "2026-09-15T09:00:00Z")

        response = api.close_comment_period(state["plan_id"], LIAISON_HEADERS)

        closed = validate_success(response)
        assert_fields(
            closed,
            {
                "status": PLAN_CLOSED,
                "required_comment_days": 45,
                "comment_end_date": "2026-09-14",
                "comment_count": 1,
                "adequacy_status": ADEQUACY_DEFICIENT,
                "deficiency_codes": [DEFICIENCY_LANGUAGE_ACCESS_GAP],
            },
        )

        assert_field(
            find_meeting(api, state["plan_id"], state["meeting_id"]),
            "accessibility_verified",
            True,
        )
        area = read_area(api, state["area_id"])
        assert_field(area, "translation_required", True)
        assert_field(area, "open_plan_count", 0)
