"""Reversals that must put every incremented counter back where it was.

Rescission has to unwind a permit's paired emissions ledgers and reopen the
participation plan, and a meeting cancellation has to give back both occupancy
counters and the buffer-expanded interval the booking had reserved.
"""

from test_helpers import (
    ADEQUACY_COMPLIANT,
    ADEQUACY_PENDING,
    APP_ENHANCED_REVIEW,
    APP_ISSUED,
    ApiErrorId,
    ASSESSMENT_ACCEPTED,
    ASSESSMENT_INVALIDATED,
    CONDITION_ACTIVE,
    DECISION_ISSUED,
    DECISION_RESCINDED,
    LIAISON_HEADERS,
    MANAGER_HEADERS,
    MAX_COMMENT_DAYS,
    MEETING_CANCELLED,
    MEETING_SCHEDULED,
    PLAN_CLOSED,
    PLAN_OPEN,
    REOPEN_MAX_ADDED_DAYS,
    assert_amount,
    assert_created,
    assert_field,
    assert_fields,
    assert_ledgers,
    assert_page,
    assert_rejected,
    cancel_meeting_payload,
    find_assessment,
    find_condition,
    find_decision,
    find_meeting,
    meeting_payload,
    read_application,
    read_area,
    read_facility,
    read_plan,
    read_venue,
    rescind_payload,
    validate_success,
)

RESCISSION_REASON = "Monitoring data contradicts the accepted cumulative impact assessment"


def _rescind(api, state):
    """The deciding manager withdraws the issued permit."""
    return validate_success(
        api.rescind_permit_decision(
            state["decision_id"], rescind_payload(RESCISSION_REASON), MANAGER_HEADERS
        )
    )


def _book_the_contested_slot(api, state):
    """Ask for 19:00-20:00, which the stored 18:00-20:30 meeting occupies."""
    return api.create_public_meeting(
        meeting_payload(
            participation_plan_id=state["plan_id"],
            venue_id=state["venue_id"],
            starts_at="2026-08-20T19:00:00Z",
            ends_at="2026-08-20T20:00:00Z",
            interpretation_languages=["es"],
        ),
        LIAISON_HEADERS,
    )


class TestRescissionRestoresBothLedgers:
    """PRD §3.7 subtracts exactly what issuance added, on both books."""

    def test_the_fifty_tons_come_off_the_facility_and_the_area_together(
        self, api, app_a_issued
    ):
        """Both ledgers return to 0.00 and the application's own figure is zeroed.

        PRD §3.7: "Rescission requires a `reason`, moves the decision `ISSUED →
        RESCINDED`, and reverses both emissions ledgers: the facility's
        `existing_load_tpy` and the area's `permitted_load_tpy` are each decreased by
        the application's `approved_net_emissions_tpy`, which is then set to 0.00."
        PRD §2.12: "Both start at 0.00, both move only on permit issuance and permit
        rescission, and both are maintained by increment and decrement rather than by
        recomputation from scratch: issuance adds the application's
        `approved_net_emissions_tpy` to both ledgers, and rescission subtracts the same
        amount from both before zeroing the application's own
        `approved_net_emissions_tpy`."
        PRD §3.7: "The application returns to review along the track it was on: an
        `ENHANCED` application moves `ISSUED → ENHANCED_REVIEW` and a `STANDARD` one
        moves `ISSUED → STANDARD_REVIEW`."

        Design: Difficulty/compensating_invariant/permitted_load_ledger_restored_after_decision_rescission
        """
        state = app_a_issued
        issued = read_application(api, state["app_id"])
        assert_field(issued, "status", APP_ISSUED)
        assert_amount(
            issued.get("approved_net_emissions_tpy"), 50.00, "approved_net_emissions_tpy"
        )
        assert_ledgers(
            area=read_area(api, state["area_id"]),
            facility=read_facility(api, state["facility_id"]),
            permitted_load_tpy=50.00,
            existing_load_tpy=50.00,
        )
        assert_field(
            find_decision(api, state["app_id"], state["decision_id"]),
            "status",
            DECISION_ISSUED,
        )

        rescinded = _rescind(api, state)

        assert_field(rescinded, "status", DECISION_RESCINDED)
        application = read_application(api, state["app_id"])
        assert_field(application, "status", APP_ENHANCED_REVIEW)
        assert_amount(
            application.get("approved_net_emissions_tpy"),
            0.00,
            "approved_net_emissions_tpy",
        )
        assert_ledgers(
            area=read_area(api, state["area_id"]),
            facility=read_facility(api, state["facility_id"]),
            permitted_load_tpy=0.00,
            existing_load_tpy=0.00,
        )

    def test_the_reversal_keeps_the_money_and_reopens_the_closed_plan(
        self, api, app_a_issued
    ):
        """The historical benefit amounts stay on the row while the plan reopens.

        PRD §3.7: "On the enhanced track only, two further cascades fire: the governing
        assessment moves `ACCEPTED → INVALIDATED`, and the application's `CLOSED`
        participation plan reopens to `OPEN` under the headroom-limited reopen rule of
        §3.4."
        PRD §3.7: "A cleared issuance moves the application `PENDING_DECISION → ISSUED`
        and writes a decision in `status` `ISSUED` carrying the approved net emissions,
        both benefit amounts and the residual snapshot."
        PRD §3.4: "Compute the remaining headroom as 120 minus the sum of
        `required_comment_days` and `granted_extension_days`; the days added are the
        smaller of **15** and that headroom, floored at zero so headroom can never
        subtract. Those added days are added to `granted_extension_days`, and the new
        `comment_end_date` is the later of the current clock date and the existing
        `comment_end_date`, plus the added days." and "Reopening also resets
        `adequacy_status` to `PENDING` and `deficiency_codes` to an empty array,
        increments the area's `open_plan_count` by 1, and increments the plan's
        `version` by 1 — the `OPEN → CLOSED → OPEN` cycle is a normal part of a
        contested file's life."
        PRD §3.6: "A condition lands in `status` `ACTIVE` and stamps
        `application_version_after`."

        Design: Difficulty/compensating_invariant/permitted_load_ledger_restored_after_decision_rescission
        """
        state = app_a_issued
        closed = read_plan(api, state["plan_id"])
        assert_fields(
            closed,
            {
                "status": PLAN_CLOSED,
                "required_comment_days": 70,
                "granted_extension_days": 0,
                "comment_end_date": "2026-10-09",
                "adequacy_status": ADEQUACY_COMPLIANT,
            },
        )
        headroom = MAX_COMMENT_DAYS - (
            closed["required_comment_days"] + closed["granted_extension_days"]
        )
        assert headroom >= REOPEN_MAX_ADDED_DAYS, (
            "50 days of headroom should let the reopen grant its full 15 days"
        )
        assert_field(
            find_assessment(api, state["app_id"], state["assessment_id"]),
            "status",
            ASSESSMENT_ACCEPTED,
        )

        _rescind(api, state)

        decision = find_decision(api, state["app_id"], state["decision_id"])
        assert_field(decision, "status", DECISION_RESCINDED)
        # The reversal is a ledger reversal, not an erasure of the record.
        assert_amount(
            decision.get("community_benefit_surcharge_usd"),
            5225.00,
            "community_benefit_surcharge_usd",
        )
        assert_amount(
            decision.get("community_benefit_total_usd"),
            100225.00,
            "community_benefit_total_usd",
        )

        assert_field(
            find_assessment(api, state["app_id"], state["assessment_id"]),
            "status",
            ASSESSMENT_INVALIDATED,
        )
        assert_field(
            find_condition(api, state["app_id"], state["condition_id"]),
            "status",
            CONDITION_ACTIVE,
        )
        reopened = read_plan(api, state["plan_id"])
        assert_fields(
            reopened,
            {
                "status": PLAN_OPEN,
                "required_comment_days": 70,
                "granted_extension_days": REOPEN_MAX_ADDED_DAYS,
                # The clock stands at 2026-10-10, later than the 2026-10-09 end date.
                "comment_end_date": "2026-10-25",
                "adequacy_status": ADEQUACY_PENDING,
                "deficiency_codes": [],
            },
        )
        assert_field(read_area(api, state["area_id"]), "open_plan_count", 1)


class TestCancellationRestoresVenueOccupancy:
    """PRD §3.5 gives back both counters and the buffered interval at once."""

    def test_cancelling_the_meeting_decrements_both_occupancy_counters(
        self, api, app_a_plan_open_draft_assessment
    ):
        """The venue ledger and the plan's meeting count both fall back to 0.

        PRD §3.5: "The liaison may cancel a scheduled meeting, optionally supplying a
        `reason`; the meeting moves `SCHEDULED → CANCELLED`, the venue's
        `booked_meeting_count` and the plan's `meeting_count` are each decremented by 1,
        and the buffer-expanded interval is released immediately so a previously
        conflicting booking now succeeds."
        PRD §3.5: "Each venue carries a slot-occupancy ledger, `booked_meeting_count`,
        which starts at 0 and always equals the number of meetings currently
        `SCHEDULED` at that venue." and "A venue's meetings can be listed and filtered
        by meeting `status`."

        Design: Difficulty/compensating_invariant/venue_slot_occupancy_restored_after_meeting_cancellation
        """
        state = app_a_plan_open_draft_assessment
        meeting_id = state["meeting_id"]
        assert_field(read_venue(api, state["venue_id"]), "booked_meeting_count", 1)
        assert_field(read_plan(api, state["plan_id"]), "meeting_count", 1)

        cancelled = validate_success(
            api.cancel_public_meeting(
                meeting_id,
                cancel_meeting_payload("Hall closed for emergency repairs"),
                LIAISON_HEADERS,
            )
        )

        assert_field(cancelled, "status", MEETING_CANCELLED)
        assert_field(read_venue(api, state["venue_id"]), "booked_meeting_count", 0)
        plan = read_plan(api, state["plan_id"])
        assert_fields(plan, {"status": PLAN_OPEN, "meeting_count": 0})
        # The row survives the cancellation; only the SCHEDULED occupancy is released.
        assert_page(
            api.list_venue_meetings(state["venue_id"], LIAISON_HEADERS),
            expected_rows=1,
            expected_total=1,
            expected_has_more=False,
        )
        assert_page(
            api.list_venue_meetings(
                state["venue_id"], LIAISON_HEADERS, params={"status": MEETING_CANCELLED}
            ),
            expected_rows=1,
            expected_total=1,
            expected_has_more=False,
        )

    def test_the_freed_interval_accepts_the_booking_it_had_just_refused(
        self, api, app_a_plan_open_draft_assessment
    ):
        """The identical 19:00 request fails, then succeeds after the cancellation.

        PRD §3.5: "If the candidate interval and any occupied interval overlap on a
        non-empty span, the booking is refused with `ERR_VENUE_SLOT_CONFLICT`."
        PRD §3.5: "The liaison may cancel a scheduled meeting, optionally supplying a
        `reason`; the meeting moves `SCHEDULED → CANCELLED`, the venue's
        `booked_meeting_count` and the plan's `meeting_count` are each decremented by 1,
        and the buffer-expanded interval is released immediately so a previously
        conflicting booking now succeeds."
        PRD §3.5: "Booking increments the venue's `booked_meeting_count` by 1 and the
        plan's `meeting_count` by 1, and later mutations of the meeting increment its
        own `version` by 1."

        Design: Difficulty/compensating_invariant/venue_slot_occupancy_restored_after_meeting_cancellation
        """
        state = app_a_plan_open_draft_assessment
        first_meeting_id = state["meeting_id"]

        refused = _book_the_contested_slot(api, state)
        assert_rejected(refused, ApiErrorId.VENUE_SLOT_CONFLICT)
        assert refused.status_code == 409, (
            "an occupied slot is an HTTP 409 conflict"
        )

        validate_success(
            api.cancel_public_meeting(
                first_meeting_id,
                cancel_meeting_payload("Hall closed for emergency repairs"),
                LIAISON_HEADERS,
            )
        )

        replacement = assert_created(_book_the_contested_slot(api, state))

        assert_field(replacement, "status", MEETING_SCHEDULED)
        assert replacement["starts_at"].startswith("2026-08-20T19:00"), (
            "the replacement should take the slot the cancellation freed"
        )
        assert_field(
            find_meeting(api, state["plan_id"], first_meeting_id),
            "status",
            MEETING_CANCELLED,
        )
        # One meeting in, one meeting out: both counters end where they started.
        assert_field(read_venue(api, state["venue_id"]), "booked_meeting_count", 1)
        plan = read_plan(api, state["plan_id"])
        assert_fields(plan, {"status": PLAN_OPEN, "meeting_count": 1})
