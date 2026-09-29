"""Rejection paths around cycle posture, the combine week and the medical file.

The cases here cover the hard stop a suspended cycle imposes on the selection
clock, the containment of bookings inside the compressed combine week, the
examiner's requirement that an exam actually happened before it can be
documented, the sealing and confidentiality tiering that gate club access to a
prospect's medical record, and the invitation selector's empty-pool refusal.
Every case builds its own state through published endpoints.
"""

from test_helpers import (
    ADMIN,
    COMBINE_WEEK_START_AT,
    ERR_BOOKING_NOT_MEDICAL_COMPLETED,
    ERR_CONFIDENTIALITY_TIER_VIOLATION,
    ERR_CYCLE_PHASE_INVALID,
    ERR_EVALUATION_SEALED,
    ERR_NO_ELIGIBLE_PROSPECTS,
    ERR_OUTSIDE_COMBINE_WEEK,
    EXAMINER,
    book,
    build_combine_week_with_station,
    build_declaration_open,
    build_draft_live_on_clock,
    build_granted_share,
    build_medical_evaluation,
    clock_action_payload,
    combine_booking_payload,
    decide_share,
    grant_consent,
    invitation_selection_payload,
    make_club_gm_headers,
    medical_evaluation_payload,
    medical_record_share_payload,
    move_phase,
    read_booking,
    read_cycle,
    read_evaluation,
    read_pick,
    read_prospect,
    read_share,
    register_prospect,
    validate_error,
)


class TestSuspendedCyclePosture:
    """The selection clock while the league has the draft suspended."""

    def test_pass_on_the_on_clock_pick_is_refused_while_the_draft_is_suspended(
        self, api
    ):
        """Suspending the draft takes the cycle out of `DRAFT_LIVE`, so the club
        on the clock cannot pass, and its deadline survives the rejection
        unchanged.

        Rule 7 (cycle phase) outranks rule 8 (cycle posture), and a clock action
        is permitted only while the cycle is `DRAFT_LIVE`, so a suspended cycle
        reports the phase guard rather than the posture guard.

        PRD: "Declarations are permitted only while the cycle is
        `DECLARATION_OPEN`; combine bookings only while it is `COMBINE_WEEK`; the
        lottery and the draft-order finalize only while it is `ORDER_PENDING`;
        selections and clock actions only while it is `DRAFT_LIVE`"

        PRD: "Because cycle phase (rule 7) precedes cycle posture (rule 8), an
        operation attempted in the wrong phase reports
        `ERR_CYCLE_PHASE_INVALID` even when the cycle is also frozen."

        Design: Corner/errors/clock_action_on_a_suspended_cycle_is_frozen_out
        """
        state = build_draft_live_on_clock(api)
        elm = state["clubs"]["ELM"]
        on_clock = read_pick(api, state["pick"]["r1p1"]["id"])
        assert on_clock["status"] == "ON_CLOCK"
        deadline_before = on_clock["deadline_at"]

        move_phase(api, state["cycle"]["id"], "DRAFT_SUSPENDED")

        response = api.act_on_pick_clock(
            on_clock["id"],
            clock_action_payload("PASS"),
            make_club_gm_headers(elm["id"]),
        )
        validate_error(response, ERR_CYCLE_PHASE_INVALID, expected_status=409)

        cycle = read_cycle(api, state["cycle"]["id"])
        assert cycle["status"] == "DRAFT_SUSPENDED"
        assert cycle["posture"] == "FROZEN"

        after = read_pick(api, on_clock["id"])
        assert after["status"] == "ON_CLOCK"
        assert after["deadline_at"] == "2027-04-22T18:10:00.000Z"
        assert after["deadline_at"] == deadline_before


class TestMedicalRecordAccessRefusals:
    """Sealing and confidentiality tiering on a prospect's medical file."""

    def test_second_club_cannot_request_a_sealed_evaluation_even_with_a_fresh_version(
        self, api
    ):
        """Revoking the only granted share seals the evaluation, and a brand-new
        request carrying the evaluation's current version is still refused.

        PRD: "A request against an evaluation whose `disclosure_state` is
        `SEALED` is refused with `ERR_EVALUATION_SEALED`, and a `ClubGM` request
        against a `RESTRICTED` evaluation is refused with
        `ERR_CONFIDENTIALITY_TIER_VIOLATION`."

        Design: Corner/errors/share_request_against_a_sealed_evaluation_is_rejected
        """
        state = build_granted_share(api)
        har = state["clubs"]["HAR"]
        decide_share(
            api,
            state["share"],
            "REVOKE",
            denial_reason="Club withdrew its interest",
        )
        sealed = read_evaluation(api, state["evaluation"]["id"])

        response = api.create_medical_record_share(
            medical_record_share_payload(
                sealed["id"], har["id"], sealed["version"], scope="SUMMARY"
            ),
            make_club_gm_headers(har["id"]),
        )
        validate_error(response, ERR_EVALUATION_SEALED, expected_status=409)

        evaluation = read_evaluation(api, sealed["id"])
        assert evaluation["disclosure_state"] == "SEALED"
        assert evaluation["active_share_count"] == 0
        assert read_share(api, state["share"]["id"])["status"] == "REVOKED"

    def test_club_gm_cannot_request_a_restricted_evaluation_despite_full_consent(
        self, api
    ):
        """A RED_FLAG grade makes the evaluation RESTRICTED, so the club's
        general manager is refused even though consent is granted at FULL scope.

        PRD: "A `ClubGM` attempting either step against a `RESTRICTED`
        evaluation is refused with `ERR_CONFIDENTIALITY_TIER_VIOLATION` (HTTP
        403)."

        Design: Corner/errors/club_gm_cannot_request_a_restricted_tier_evaluation
        """
        state = build_medical_evaluation(
            api, findings_code="ORTHO-REDFLAG-01", medical_grade="RED_FLAG"
        )
        elm = state["clubs"]["ELM"]
        state["prospect"] = grant_consent(api, state["prospect"], scope="FULL")
        evaluation = read_evaluation(api, state["evaluation"]["id"])
        assert evaluation["confidentiality_tier"] == "RESTRICTED"

        response = api.create_medical_record_share(
            medical_record_share_payload(
                evaluation["id"], elm["id"], evaluation["version"], scope="FULL"
            ),
            make_club_gm_headers(elm["id"]),
        )
        validate_error(
            response, ERR_CONFIDENTIALITY_TIER_VIOLATION, expected_status=403
        )

        after = read_evaluation(api, evaluation["id"])
        assert after["confidentiality_tier"] == "RESTRICTED"
        assert after["active_share_count"] == 0
        prospect = read_prospect(api, state["prospect"]["id"])
        assert prospect["medical_clearance_status"] == "FAILED"


class TestCombineWeekBookingWindow:
    """Bookings must sit wholly inside the cycle's compressed week."""

    def test_exam_booked_the_day_before_the_week_opens_is_refused(self, api):
        """An interval one day ahead of the combine week start is outside the
        window, so the booking is refused and the cycle window is untouched.

        PRD: "The interval must sit wholly inside the cycle's compressed week:
        `starts_at` at or after `combine_week_start_at` and `ends_at` at or
        before `combine_week_end_at`, else `ERR_OUTSIDE_COMBINE_WEEK`."

        Design: Corner/errors/booking_the_day_before_the_combine_week_opens_is_rejected
        """
        state = build_combine_week_with_station(api)

        response = api.create_combine_booking(
            combine_booking_payload(
                state["prospect"]["id"],
                "MEDICAL_EXAM",
                "2027-02-21T09:00:00.000Z",
                "2027-02-21T09:45:00.000Z",
                medical_station_id=state["station"]["id"],
            ),
            ADMIN,
        )
        validate_error(response, ERR_OUTSIDE_COMBINE_WEEK, expected_status=422)

        cycle = read_cycle(api, state["cycle"]["id"])
        assert cycle["combine_week_start_at"] == COMBINE_WEEK_START_AT


class TestEvaluationSourceBooking:
    """An examiner may only document an exam that actually happened."""

    def test_evaluation_against_a_still_scheduled_exam_is_refused(self, api):
        """Filing findings against a booking that was never checked in is
        refused, and the prospect's clearance stays PENDING rather than CLEARED.

        PRD: "The referenced booking must have `booking_type` `MEDICAL_EXAM`,
        `status` `COMPLETED`, and a `prospect_id` equal to the one supplied; any
        deviation is refused with `ERR_BOOKING_NOT_MEDICAL_COMPLETED`."

        Design: Corner/errors/evaluation_cannot_be_filed_against_a_scheduled_booking
        """
        state = build_combine_week_with_station(api)
        booking = book(
            api,
            state["prospect"],
            "MEDICAL_EXAM",
            "2027-02-22T09:00:00.000Z",
            "2027-02-22T09:45:00.000Z",
            medical_station_id=state["station"]["id"],
        )
        assert booking["status"] == "SCHEDULED"

        response = api.create_medical_evaluation(
            medical_evaluation_payload(booking["id"], state["prospect"]["id"]),
            EXAMINER,
        )
        validate_error(
            response, ERR_BOOKING_NOT_MEDICAL_COMPLETED, expected_status=422
        )

        assert read_booking(api, booking["id"])["status"] == "SCHEDULED"
        prospect = read_prospect(api, state["prospect"]["id"])
        assert prospect["medical_clearance_status"] == "PENDING"


class TestInvitationSelectorPool:
    """The bulk combine invitation selector needs a non-empty pool."""

    def test_selector_over_a_cycle_whose_only_prospect_never_declared_is_refused(
        self, api
    ):
        """With nobody declared the candidate pool is empty, so the selector
        refuses the run instead of reporting that it invited nobody.

        PRD: "If the pool is empty the whole call is refused with
        `ERR_NO_ELIGIBLE_PROSPECTS`."

        Design: Corner/errors/invitation_selector_with_an_empty_pool_is_rejected
        """
        state = build_declaration_open(api)
        prospect = register_prospect(api, state["cycle"]["id"])

        response = api.select_combine_invitations(
            state["cycle"]["id"], invitation_selection_payload(5), ADMIN
        )
        validate_error(response, ERR_NO_ELIGIBLE_PROSPECTS, expected_status=422)

        after = read_prospect(api, prospect["id"])
        assert after["invitation_status"] == "NOT_INVITED"
        assert after["declaration_status"] == "UNDECLARED"
