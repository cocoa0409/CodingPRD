"""Cross-entity preconditions and the two opposite interval geometries.

Advance-to-decision waits on an entity the application does not own, a booking
waits on a venue's status, and the two overlap rules pull in opposite directions:
venue slots are half-open with a turnover buffer, while the area's engagement
windows are closed date intervals in which a shared endpoint day collides.
"""

from test_helpers import (
    ADEQUACY_COMPLIANT,
    ANALYST_HEADERS,
    APP_ENHANCED_REVIEW,
    APP_PENDING_DECISION,
    ApiErrorId,
    ASSESSMENT_ACCEPTED,
    ASSESSMENT_DRAFT,
    AREA_ENGAGEMENT_CAP_SEVERE,
    BASE_COMMENT_DAYS,
    DESIGNATION_SEVERELY_OVERBURDENED,
    HIGH_IMPACT_EXTRA_DAYS,
    LIAISON_HEADERS,
    MEETING_SCHEDULED,
    OVERBURDENED_EXTRA_DAYS,
    PLAN_CLOSED,
    PLAN_OPEN,
    PLAN_PLANNED,
    QA_USER_ID,
    SEVERELY_OVERBURDENED_EXTRA_DAYS,
    TRANSLATION_EXTRA_DAYS,
    VENUE_BUFFER_MINUTES,
    VENUE_DECOMMISSIONED,
    assert_amounts,
    assert_area_scores,
    assert_created,
    assert_empty_listing,
    assert_field,
    assert_fields,
    assert_page,
    assert_rejected,
    close_plan,
    find_assessment,
    find_meeting,
    meeting_payload,
    open_plan,
    open_plan_payload,
    qa_accept_assessment,
    read_application,
    read_area,
    read_plan,
    read_venue,
    set_clock,
    submit_assessment_for_qa,
    validate_success,
)


def _close_the_elapsed_window(api, state):
    """Move the clock past the last day of the window and close the plan."""
    set_clock(api, "2026-09-30T09:00:00Z")
    return close_plan(api, state)


def _book(api, plan_id, venue_id, starts_at, ends_at):
    """Ask the liaison's booking endpoint for one Spanish-interpreted slot."""
    return api.create_public_meeting(
        meeting_payload(
            participation_plan_id=plan_id,
            venue_id=venue_id,
            starts_at=starts_at,
            ends_at=ends_at,
            interpretation_languages=["es"],
        ),
        LIAISON_HEADERS,
    )


class TestAdvanceToDecisionWaitsOnQa:
    """PRD §3.2 makes the advance depend on an entity the file does not own."""

    def test_a_closed_compliant_plan_is_not_enough_without_an_accepted_assessment(
        self, api, app_a_plan_open_draft_assessment
    ):
        """Every local precondition holds, yet the draft assessment blocks the move.

        PRD §3.2: "An `ENHANCED_REVIEW` application moves `ENHANCED_REVIEW →
        PENDING_DECISION` only when its governing cumulative impact assessment exists
        and is `ACCEPTED` — otherwise `ERR_ASSESSMENT_NOT_ACCEPTED` — and only when the
        application's non-cancelled participation plan is `CLOSED` — otherwise
        `ERR_PARTICIPATION_NOT_CLOSED`." and "The enhanced advance recomputes the
        application's `residual_impact_index` before incrementing its `version` by 1."
        PRD §2.10: "Advance-to-decision and permit decision creation: on the enhanced
        track the governing assessment exists and is `ACCEPTED` — otherwise
        `ERR_ASSESSMENT_NOT_ACCEPTED` (409)."
        PRD §3.3: "A `QAReviewer` then records an `outcome` of either `ACCEPT` or
        `RETURN`, optionally with a `note`, and in either case their `X-User-ID` is
        written to `qa_user_id` and the assessment's `version` increments by 1."

        Design: Difficulty/cross_entity_state_dependency/advance_to_decision_requires_accepted_assessment
        """
        state = app_a_plan_open_draft_assessment
        _close_the_elapsed_window(api, state)

        plan = read_plan(api, state["plan_id"])
        assert_fields(
            plan,
            {
                "status": PLAN_CLOSED,
                "comment_end_date": "2026-09-29",
                "adequacy_status": ADEQUACY_COMPLIANT,
                "deficiency_codes": [],
            },
        )
        assert_field(
            read_application(api, state["app_id"]), "status", APP_ENHANCED_REVIEW
        )
        assert_field(
            find_assessment(api, state["app_id"], state["assessment_id"]),
            "status",
            ASSESSMENT_DRAFT,
        )

        refused = api.advance_to_decision(state["app_id"], ANALYST_HEADERS)

        assert_rejected(refused, ApiErrorId.ASSESSMENT_NOT_ACCEPTED)
        assert refused.status_code == 409, (
            "a missing acceptance is an HTTP 409 conflict"
        )
        assert_field(
            read_application(api, state["app_id"]), "status", APP_ENHANCED_REVIEW
        )

        submit_assessment_for_qa(api, state)
        qa_accept_assessment(api, state)
        advanced = validate_success(
            api.advance_to_decision(state["app_id"], ANALYST_HEADERS)
        )

        assert_field(advanced, "status", APP_PENDING_DECISION)
        assert_amounts(
            advanced,
            {
                "pre_mitigation_index": 81.82,
                "residual_impact_index": 81.82,
            },
        )
        accepted = find_assessment(api, state["app_id"], state["assessment_id"])
        assert_field(accepted, "status", ASSESSMENT_ACCEPTED)
        assert_field(accepted, "qa_user_id", QA_USER_ID)

    def test_the_acceptance_recompute_leaves_the_closed_plan_at_sixty_days(
        self, api, app_a_plan_open_draft_assessment
    ):
        """An 81.82 index would have added ten days to a plan that was still open.

        PRD §3.3: "On `ACCEPT`, the assessment moves `SUBMITTED_FOR_QA → ACCEPTED` and
        four further things happen: any other assessment of the same application that
        was `ACCEPTED` moves `ACCEPTED → SUPERSEDED`; the application's
        `pre_mitigation_index` is set to this assessment's `cumulative_impact_index` and
        its `residual_impact_index` is recomputed; the required comment days on the
        application's participation plan are recomputed when that plan's status is
        `PLANNED`, `OPEN` or `EXTENDED`; and the application's `version` increments by
        1 alongside the assessment's."
        PRD §3.4: "Start from a base of **30 days**. Add 15 days when the area's
        `designation` is `OVERBURDENED`. Add 30 days when it is
        `SEVERELY_OVERBURDENED`. Add a further 15 days when the area's
        `translation_required` flag is true. Add 10 more days when a governing
        assessment exists and its `cumulative_impact_index` is at least 70.00."
        PRD §3.4: "A later recomputation of `required_comment_days` — from a screen, a
        designation cascade or an assessment acceptance — rewrites
        `required_comment_days` **only** and never moves an already-set
        `comment_end_date`."
        PRD §3.4: "Closing decrements the area's `open_plan_count` by 1, increments the
        plan's `version` by 1, and — critically — evaluates participation adequacy."

        Design: Difficulty/cross_entity_state_dependency/advance_to_decision_requires_accepted_assessment
        """
        state = app_a_plan_open_draft_assessment
        _close_the_elapsed_window(api, state)
        assert_field(read_plan(api, state["plan_id"]), "required_comment_days", 60)

        submit_assessment_for_qa(api, state)
        qa_accept_assessment(api, state)

        plan = read_plan(api, state["plan_id"])
        # 30 base + 15 designated + 15 translation, with the high-impact days never
        # added because the plan was already CLOSED when the acceptance landed.
        assert_field(plan, "required_comment_days", 60)
        assert plan["required_comment_days"] == (
            BASE_COMMENT_DAYS + OVERBURDENED_EXTRA_DAYS + TRANSLATION_EXTRA_DAYS
        ), "the closed plan should keep the length it was opened on"
        assert plan["required_comment_days"] != 60 + HIGH_IMPACT_EXTRA_DAYS, (
            "a CLOSED plan is outside the acceptance recompute's scope"
        )
        assert_fields(
            plan,
            {
                "status": PLAN_CLOSED,
                "comment_end_date": "2026-09-29",
                "adequacy_status": ADEQUACY_COMPLIANT,
                "deficiency_codes": [],
            },
        )

        validate_success(api.advance_to_decision(state["app_id"], ANALYST_HEADERS))

        assert_field(
            read_application(api, state["app_id"]), "status", APP_PENDING_DECISION
        )
        assert_field(read_area(api, state["area_id"]), "open_plan_count", 0)


class TestDecommissionedVenueRefusesTheBooking:
    """PRD §3.5 checks the venue's own status before the slot is even consulted."""

    def test_a_decommissioned_hall_refuses_a_legal_in_window_slot(
        self, api, app_a_screened, venue_pair
    ):
        """An open window and a free evening cannot revive a retired venue.

        PRD §3.5: "The venue's `status` must be `ACTIVE`, or the booking is refused
        with `ERR_VENUE_DECOMMISSIONED`."
        PRD §2.10: "Meeting booking: the venue's `status` is `ACTIVE` — otherwise
        `ERR_VENUE_DECOMMISSIONED` (409)."
        PRD §3.5: "Each venue carries a slot-occupancy ledger, `booked_meeting_count`,
        which starts at 0 and always equals the number of meetings currently
        `SCHEDULED` at that venue."

        Design: Difficulty/cross_entity_state_dependency/meeting_scheduling_blocked_by_decommissioned_venue
        """
        state = app_a_screened
        open_plan(api, state, "2026-08-01")
        plan = read_plan(api, state["plan_id"])
        assert_fields(
            plan,
            {
                "status": PLAN_OPEN,
                "required_comment_days": 60,
                "comment_end_date": "2026-09-29",
                "meeting_count": 0,
            },
        )

        response = _book(
            api,
            state["plan_id"],
            venue_pair["venue_decommissioned_id"],
            "2026-08-20T18:00:00Z",
            "2026-08-20T20:30:00Z",
        )

        assert_rejected(response, ApiErrorId.VENUE_DECOMMISSIONED)
        assert response.status_code == 409, (
            "a retired venue is an HTTP 409 conflict"
        )

        venue = read_venue(api, venue_pair["venue_decommissioned_id"])
        assert_fields(
            venue,
            {
                "status": VENUE_DECOMMISSIONED,
                "booked_meeting_count": 0,
                # Both reachability flags are true, so the later accessibility gate
                # was not the one that answered.
                "ada_accessible": True,
                "transit_accessible": True,
            },
        )
        assert_field(read_plan(api, state["plan_id"]), "meeting_count", 0)
        assert_empty_listing(
            api.list_plan_meetings(state["plan_id"], LIAISON_HEADERS)
        )

    def test_the_identical_request_books_at_the_active_hall(
        self, api, app_a_screened, venue_pair
    ):
        """The same plan, evening and languages succeed once the venue is `ACTIVE`.

        PRD §3.5: "A booked meeting lands in `status` `SCHEDULED` with
        `accessibility_verified` set from the venue's flags — true when the venue had
        both `ada_accessible` and `transit_accessible` true at booking time." and
        "Booking increments the venue's `booked_meeting_count` by 1 and the plan's
        `meeting_count` by 1, and later mutations of the meeting increment its own
        `version` by 1."
        PRD §3.5: "A `CommunityLiaison` books a public meeting by naming the
        `participation_plan_id` whose comment period it serves and the `venue_id`
        reserved, together with `starts_at`, `ends_at` (which must be strictly later
        than `starts_at`) and optionally `interpretation_languages`, the ISO 639-1
        codes to be interpreted live, defaulting to an empty array."

        Design: Difficulty/cross_entity_state_dependency/meeting_scheduling_blocked_by_decommissioned_venue
        """
        state = app_a_screened
        open_plan(api, state, "2026-08-01")
        assert_rejected(
            _book(
                api,
                state["plan_id"],
                venue_pair["venue_decommissioned_id"],
                "2026-08-20T18:00:00Z",
                "2026-08-20T20:30:00Z",
            ),
            ApiErrorId.VENUE_DECOMMISSIONED,
        )

        meeting = assert_created(
            _book(
                api,
                state["plan_id"],
                venue_pair["venue_active_id"],
                "2026-08-20T18:00:00Z",
                "2026-08-20T20:30:00Z",
            )
        )

        assert_fields(
            meeting,
            {
                "status": MEETING_SCHEDULED,
                "accessibility_verified": True,
                "interpretation_languages": ["es"],
            },
        )
        assert meeting["starts_at"].startswith("2026-08-20T18:00"), (
            "the booked instant should be the requested one, to the minute"
        )
        assert_field(
            read_venue(api, venue_pair["venue_active_id"]), "booked_meeting_count", 1
        )
        # The refused booking left no occupancy behind at the retired hall.
        assert_field(
            read_venue(api, venue_pair["venue_decommissioned_id"]),
            "booked_meeting_count",
            0,
        )
        plan = read_plan(api, state["plan_id"])
        assert_fields(
            plan,
            {
                "status": PLAN_OPEN,
                "meeting_count": 1,
                "comment_end_date": "2026-09-29",
            },
        )


class TestVenueBufferHalfOpenGeometry:
    """PRD §3.5 buffers the candidate only, and lets endpoints touch."""

    def test_an_hour_after_the_stored_meeting_still_collides(
        self, api, app_a_plan_open_draft_assessment
    ):
        """A 21:00 start buffers back to 20:00 and lands inside 18:00 to 20:30.

        PRD §3.5: "Slot conflict uses a **half-open** interval geometry with a
        symmetric turnover buffer of **60 minutes**." and "The candidate interval runs
        from 60 minutes before the requested `starts_at` up to, but not including, 60
        minutes after the requested `ends_at`." and "Each existing meeting at the same
        venue whose `status` is `SCHEDULED` occupies the interval from its own
        `starts_at` up to, but not including, its own `ends_at` — no buffer is added on
        the stored side." and "If the candidate interval and any occupied interval
        overlap on a non-empty span, the booking is refused with
        `ERR_VENUE_SLOT_CONFLICT`."
        PRD §2.10: "Meeting booking: the buffered candidate interval of §3.5 does not
        overlap a scheduled meeting at that venue — otherwise
        `ERR_VENUE_SLOT_CONFLICT` (409)."

        Design: Difficulty/resource_temporal_overlap/venue_buffer_expanded_halfopen_slot_conflict
        """
        state = app_a_plan_open_draft_assessment
        assert_field(read_venue(api, state["venue_id"]), "booked_meeting_count", 1)
        assert VENUE_BUFFER_MINUTES == 60, (
            "the turnover buffer either side of the candidate is 60 minutes"
        )

        response = _book(
            api,
            state["plan_id"],
            state["venue_id"],
            "2026-08-20T21:00:00Z",
            "2026-08-20T22:30:00Z",
        )

        assert_rejected(response, ApiErrorId.VENUE_SLOT_CONFLICT)
        assert response.status_code == 409, (
            "an occupied slot is an HTTP 409 conflict"
        )

        assert_field(read_venue(api, state["venue_id"]), "booked_meeting_count", 1)
        assert_field(read_plan(api, state["plan_id"]), "meeting_count", 1)
        rows = assert_page(
            api.list_venue_meetings(state["venue_id"], LIAISON_HEADERS),
            expected_rows=1,
            expected_total=1,
            expected_has_more=False,
        )
        assert_field(rows[0], "status", MEETING_SCHEDULED)

    def test_a_buffered_start_exactly_on_the_stored_end_is_accepted(
        self, api, app_a_plan_open_draft_assessment
    ):
        """A 21:30 start buffers back to precisely 20:30, so the intervals only touch.

        PRD §3.5: "Because the intervals are half-open, touching endpoints do not
        collide: a candidate whose buffered start falls exactly on an existing
        meeting's `ends_at` is accepted, so a gap of exactly 60 minutes between two
        meetings is legal."
        PRD §3.5: "Booking increments the venue's `booked_meeting_count` by 1 and the
        plan's `meeting_count` by 1, and later mutations of the meeting increment its
        own `version` by 1."
        PRD §3.5: "A booked meeting lands in `status` `SCHEDULED` with
        `accessibility_verified` set from the venue's flags — true when the venue had
        both `ada_accessible` and `transit_accessible` true at booking time."

        Design: Difficulty/resource_temporal_overlap/venue_buffer_expanded_halfopen_slot_conflict
        """
        state = app_a_plan_open_draft_assessment
        first_meeting_id = state["meeting_id"]
        assert_rejected(
            _book(
                api,
                state["plan_id"],
                state["venue_id"],
                "2026-08-20T21:00:00Z",
                "2026-08-20T22:30:00Z",
            ),
            ApiErrorId.VENUE_SLOT_CONFLICT,
        )

        second = assert_created(
            _book(
                api,
                state["plan_id"],
                state["venue_id"],
                "2026-08-20T21:30:00Z",
                "2026-08-20T23:00:00Z",
            )
        )

        assert_fields(
            second,
            {
                "status": MEETING_SCHEDULED,
                "accessibility_verified": True,
            },
        )
        assert second["starts_at"].startswith("2026-08-20T21:30"), (
            "the accepted slot should start exactly one hour after 20:30"
        )
        assert_field(
            find_meeting(api, state["plan_id"], first_meeting_id),
            "status",
            MEETING_SCHEDULED,
        )
        assert_field(read_venue(api, state["venue_id"]), "booked_meeting_count", 2)
        assert_field(read_plan(api, state["plan_id"]), "meeting_count", 2)
        assert_page(
            api.list_venue_meetings(state["venue_id"], LIAISON_HEADERS),
            expected_rows=2,
            expected_total=2,
            expected_has_more=False,
        )


class TestAreaEngagementClosedIntervals:
    """PRD §3.4 uses the opposite geometry: a shared endpoint day collides."""

    def test_a_second_window_starting_on_the_first_ones_last_day_collides(
        self, api, area_b_two_applications
    ):
        """One severely overburdened area allows one live window, and 2026-10-14 is it.

        PRD §3.4: "The cap is **two** concurrent periods normally and drops to **one**
        when the area's `designation` is `SEVERELY_OVERBURDENED`." and "The count is
        taken over other participation plans — excluding the plan being opened or
        extended — whose `status` is `OPEN` or `EXTENDED` and whose application's
        facility sits in the same screening area, and whose own closed comment window
        intersects the candidate window." and "This geometry is a **closed** date
        interval on both sides, so two windows that merely share a single endpoint day
        **do** collide." and "If the count of intersecting concurrent plans plus one
        would exceed the cap, the request is refused with
        `ERR_AREA_ENGAGEMENT_CAPACITY`."
        PRD §3.4: "**Opening** the period moves the plan `PLANNED → OPEN`: the liaison
        supplies `comment_start_date`, which must be on or after the clock date — an
        earlier date is refused with `ERR_COMMENT_START_IN_PAST` — and the server
        derives `comment_end_date` as `comment_start_date` plus `required_comment_days`
        plus `granted_extension_days`, minus one day, so that the window is a closed
        interval inclusive of both its first and last day."
        PRD §3.1: "A score of **at least 80.00** designates the area
        `SEVERELY_OVERBURDENED`; otherwise a score of **at least 65.00** designates it
        `OVERBURDENED`; otherwise it is `UNDESIGNATED`."

        Design: Difficulty/resource_temporal_overlap/area_engagement_capacity_closed_interval_touching_endpoints_collide
        """
        state = area_b_two_applications
        area = read_area(api, state["area_id"])
        assert_area_scores(area, statewide=88.51, county=82.91)
        assert_fields(
            area,
            {
                "designation": DESIGNATION_SEVERELY_OVERBURDENED,
                "translation_required": True,
            },
        )
        assert AREA_ENGAGEMENT_CAP_SEVERE == 1, (
            "a severely overburdened area runs one comment period at a time"
        )

        opened = open_plan(api, state, "2026-08-01", plan_key="plan_b1_id")
        assert_fields(
            opened,
            {
                "status": PLAN_OPEN,
                # 30 base + 30 severe + 15 translation.
                "required_comment_days": (
                    BASE_COMMENT_DAYS
                    + SEVERELY_OVERBURDENED_EXTRA_DAYS
                    + TRANSLATION_EXTRA_DAYS
                ),
                "comment_start_date": "2026-08-01",
                "comment_end_date": "2026-10-14",
            },
        )
        assert_field(read_area(api, state["area_id"]), "open_plan_count", 1)

        response = api.open_comment_period(
            state["plan_b2_id"], open_plan_payload("2026-10-14"), LIAISON_HEADERS
        )

        assert_rejected(response, ApiErrorId.AREA_ENGAGEMENT_CAPACITY)
        assert response.status_code == 409, (
            "an exhausted engagement cap is an HTTP 409 conflict"
        )
        assert_field(read_plan(api, state["plan_b2_id"]), "status", PLAN_PLANNED)
        assert_field(read_area(api, state["area_id"]), "open_plan_count", 1)

    def test_starting_one_day_later_clears_the_shared_endpoint(
        self, api, area_b_two_applications
    ):
        """2026-10-15 begins after the first window's last day, so both may run.

        PRD §3.4: "This geometry is a **closed** date interval on both sides, so two
        windows that merely share a single endpoint day **do** collide."
        PRD §3.4: "Opening increments the area's `open_plan_count` by 1 and the plan's
        `version` by 1."
        PRD §3.4: "The plan's `required_comment_days` is where community burden turns
        into procedural time."
        PRD §3.4: "Add 30 days when it is `SEVERELY_OVERBURDENED`. Add a further 15
        days when the area's `translation_required` flag is true."

        Design: Difficulty/resource_temporal_overlap/area_engagement_capacity_closed_interval_touching_endpoints_collide
        """
        state = area_b_two_applications
        open_plan(api, state, "2026-08-01", plan_key="plan_b1_id")
        assert_rejected(
            api.open_comment_period(
                state["plan_b2_id"], open_plan_payload("2026-10-14"), LIAISON_HEADERS
            ),
            ApiErrorId.AREA_ENGAGEMENT_CAPACITY,
        )

        second = validate_success(
            api.open_comment_period(
                state["plan_b2_id"], open_plan_payload("2026-10-15"), LIAISON_HEADERS
            )
        )

        assert_fields(
            second,
            {
                "status": PLAN_OPEN,
                "required_comment_days": 75,
                "granted_extension_days": 0,
                "comment_start_date": "2026-10-15",
                # 2026-10-15 plus 75 days minus one day.
                "comment_end_date": "2026-12-28",
            },
        )
        first = read_plan(api, state["plan_b1_id"])
        assert_fields(
            first,
            {
                "status": PLAN_OPEN,
                "required_comment_days": 75,
                "comment_end_date": "2026-10-14",
            },
        )
        assert_field(read_area(api, state["area_id"]), "open_plan_count", 2)
