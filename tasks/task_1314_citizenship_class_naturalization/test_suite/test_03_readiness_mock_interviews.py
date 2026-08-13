"""Readiness scoring and mock interview practice (PRD §3.3)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_mock_interview,
    assert_readiness_report,
    book_mock_interview,
    create_general_volunteer,
    create_program,
    create_screened_applicant,
    create_section,
    enroll,
    make_volunteer_headers,
    setup_mock_booking_context,
    validate_error,
    validate_success,
)

COORD = TEST_USERS["intake_coordinator_headers"]


class TestReadinessVariants:
    def test_readiness_attained_and_projected_diverge_with_forward_evidence(self, api):
        """PRD §3.3: "The **attained** variant counts realized evidence: the English
        level used is the active screening's `english_level`, and the civics best is
        the larger of the screening's `civics_practice_pct` and the highest
        `overall_score` across the applicant's `COMPLETED` mock interviews, defaulting
        to 0 when none exist."
        PRD §3.3: "The **projected** variant is forward-looking: when the applicant
        holds any enrollment in `ENROLLED` status, the English level used is the
        screening's level plus one, capped at 4, and otherwise the screening's level
        unchanged; when the applicant has any mock interview in `SCHEDULED` status,
        the civics best is floored at 70 — the larger of the attained civics best and
        70 — and otherwise the attained civics best unchanged."

        Design: Difficulty/dual_variant_calc/readiness_attained_vs_projected
        """
        create_program()
        applicant, _ = create_screened_applicant()  # eng 3, civics 25, no legal flag
        instructor = create_general_volunteer(full_name="Instructor")
        section = create_section(instructor["id"], capacity=2, total_sessions=10)
        enroll(applicant["id"], section["id"])
        book_mock_interview(applicant["id"], instructor["id"],
                            scheduled_start="2026-08-10T15:00:00Z")

        attained = validate_success(
            api.get_readiness(applicant["id"], COORD, params={"variant": "attained"}), 200
        )
        assert_readiness_report(attained)
        assert attained["variant"] == "attained"
        # 25 residence + 25 presence + 20*3/4 english + 20*25/100 civics + 10 legal
        assert attained["residence_points"] == 25
        assert attained["presence_points"] == 25
        assert attained["english_points"] == 15
        assert attained["civics_points"] == 5
        assert attained["legal_points"] == 10
        assert attained["score"] == 80

        projected = validate_success(
            api.get_readiness(applicant["id"], COORD, params={"variant": "projected"}), 200
        )
        assert_readiness_report(projected)
        assert projected["variant"] == "projected"
        # english level bumped 3 -> 4 (20 points); civics floored at 70 (14 points)
        assert projected["english_points"] == 20
        assert projected["civics_points"] == 14
        assert projected["score"] == 94
        assert attained["score"] != projected["score"], (
            "identical underlying rows must still diverge across the two variants"
        )

    def test_readiness_variants_agree_without_forward_evidence(self, api):
        """PRD §3.3: "The **projected** variant is forward-looking: when the applicant
        holds any enrollment in `ENROLLED` status, the English level used is the
        screening's level plus one, capped at 4, and otherwise the screening's level
        unchanged; when the applicant has any mock interview in `SCHEDULED` status,
        the civics best is floored at 70 — the larger of the attained civics best and
        70 — and otherwise the attained civics best unchanged."
        PRD §3.3: "The final `score` is the sum of the five components, rounded half
        up exactly once to a whole number between 0 and 100."

        Design: Difficulty/dual_variant_calc/readiness_attained_vs_projected
        """
        create_program()
        applicant, _ = create_screened_applicant()  # no enrollment, no mock interview

        attained = validate_success(
            api.get_readiness(applicant["id"], COORD, params={"variant": "attained"}), 200
        )
        projected = validate_success(
            api.get_readiness(applicant["id"], COORD, params={"variant": "projected"}), 200
        )
        assert attained["score"] == 80
        assert projected["score"] == 80, (
            "with no ENROLLED enrollment and no SCHEDULED mock, projected falls back "
            "to the attained inputs unchanged"
        )
        assert projected["english_points"] == attained["english_points"] == 15
        assert projected["civics_points"] == attained["civics_points"] == 5


class TestMockInterviewScoring:
    def test_mock_score_civics_floor_gate(self, api):
        """PRD §3.3: "The `overall_score` is forty times the English percentage plus
        forty times the civics percentage plus twenty times the N-400 familiarity
        percentage, the total divided by one hundred and truncated to a whole number.
        The `outcome` is `PASS` when the overall score is at least 70 and the civics
        percentage is at least 60, and `NEEDS_RETRY` otherwise"

        Design: Corner/calculations/mock_score_civics_floor_gate
        """
        context = setup_mock_booking_context()
        applicant = context["applicant"]
        volunteer = context["volunteer"]
        first = book_mock_interview(applicant["id"], volunteer["id"],
                                    scheduled_start="2026-08-10T10:00:00Z")
        second = book_mock_interview(applicant["id"], volunteer["id"],
                                     scheduled_start="2026-08-10T11:00:00Z")

        scored_first = validate_success(
            api.score_mock_interview(
                first["id"], {"english_pct": 90, "civics_pct": 55, "n400_pct": 80},
                make_volunteer_headers(volunteer["id"]),
            ),
            200,
        )
        assert_mock_interview(scored_first)
        assert scored_first["overall_score"] == 74, "truncation of (3600+2200+1600)/100"
        assert scored_first["outcome"] == "NEEDS_RETRY", (
            "civics 55 fails the 60-point floor even though overall 74 >= 70"
        )
        assert scored_first["status"] == "COMPLETED"

        scored_second = validate_success(
            api.score_mock_interview(
                second["id"], {"english_pct": 80, "civics_pct": 65, "n400_pct": 60},
                make_volunteer_headers(volunteer["id"]),
            ),
            200,
        )
        assert scored_second["overall_score"] == 70
        assert scored_second["outcome"] == "PASS", "both thresholds are inclusive"


class TestMockInterviewBookingGates:
    def test_mock_eligibility_low_readiness_rejected(self, api):
        """PRD §3.3: "Eligibility comes first among the threshold checks: the
        applicant must hold a `COMPLETED` enrollment or an attained readiness score of
        at least 40, otherwise the booking is rejected with `ERR_MOCK_ELIGIBILITY`."

        Design: Corner/endpoints/mock_eligibility_low_readiness_rejected
        """
        create_program()
        # Screening leaves residence and presence unmet with english/civics at zero:
        # attained readiness is 10 (legal-clear only), and there is no COMPLETED
        # enrollment.
        applicant, _ = create_screened_applicant(
            lpr_months=30, continuous_residence_months=30, physical_presence_days=100,
            age_years=31, english_level=0, civics_practice_pct=0,
        )
        readiness = validate_success(api.get_readiness(applicant["id"], COORD), 200)
        assert readiness["score"] == 10
        volunteer = create_general_volunteer(full_name="Interviewer")

        response = api.create_mock_interview(
            {"applicant_id": applicant["id"], "volunteer_id": volunteer["id"],
             "scheduled_start": "2026-08-10T10:00:00Z", "duration_minutes": 30},
            COORD,
        )
        validate_error(response, ApiErrorId.ERR_MOCK_ELIGIBILITY)

    def test_mock_attempts_exhausted_rejected(self, api):
        """PRD §3.3: "Finally, an applicant who already has `mock_max_attempts`
        non-cancelled mock interviews cannot book another
        (`ERR_MOCK_ATTEMPTS_EXHAUSTED`). Cancelled interviews count toward neither the
        buffer nor the attempt cap."

        Design: Corner/endpoints/mock_attempts_exhausted_rejected
        """
        context = setup_mock_booking_context()
        applicant = context["applicant"]
        volunteer = context["volunteer"]

        cancelled = book_mock_interview(applicant["id"], volunteer["id"],
                                        scheduled_start="2026-08-10T09:00:00Z")
        validate_success(api.cancel_mock_interview(cancelled["id"], COORD), 200)

        for day in ("2026-08-11", "2026-08-12", "2026-08-13"):
            booking = book_mock_interview(applicant["id"], volunteer["id"],
                                          scheduled_start=f"{day}T10:00:00Z")
            assert booking["status"] == "SCHEDULED"

        response = api.create_mock_interview(
            {"applicant_id": applicant["id"], "volunteer_id": volunteer["id"],
             "scheduled_start": "2026-08-14T10:00:00Z", "duration_minutes": 30},
            COORD,
        )
        validate_error(response, ApiErrorId.ERR_MOCK_ATTEMPTS_EXHAUSTED)


class TestMockInterviewBufferGap:
    def test_mock_interview_volunteer_buffer_gap_rejects_fourteen_allows_fifteen(self, api):
        """PRD §3.3: "The volunteer's calendar then enforces a turnaround buffer: the
        new interview must leave a gap of at least `mock_buffer_minutes` from every
        other non-cancelled interview of that volunteer — with the default buffer, a
        gap of exactly fifteen minutes is allowed and one of fourteen minutes is
        rejected with `ERR_INTERVIEW_SLOT_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/mock_interview_volunteer_buffer_gap
        """
        context = setup_mock_booking_context()
        applicant = context["applicant"]
        volunteer = context["volunteer"]
        # Existing interview 10:00 + 30 minutes ends 10:30.
        book_mock_interview(applicant["id"], volunteer["id"],
                            scheduled_start="2026-08-10T10:00:00Z")

        too_close = api.create_mock_interview(
            {"applicant_id": applicant["id"], "volunteer_id": volunteer["id"],
             "scheduled_start": "2026-08-10T10:44:00Z", "duration_minutes": 30},
            COORD,
        )
        validate_error(too_close, ApiErrorId.ERR_INTERVIEW_SLOT_CONFLICT)

        exactly_buffer = validate_success(
            api.create_mock_interview(
                {"applicant_id": applicant["id"], "volunteer_id": volunteer["id"],
                 "scheduled_start": "2026-08-10T10:45:00Z", "duration_minutes": 30},
                COORD,
            ),
            201,
        )
        assert_mock_interview(exactly_buffer)
        assert exactly_buffer["status"] == "SCHEDULED", (
            "a gap of exactly mock_buffer_minutes (15) is allowed"
        )

    def test_mock_interview_buffer_gap_applies_symmetric_and_cancelled_frees(self, api):
        """PRD §3.3: "The volunteer's calendar then enforces a turnaround buffer: the
        new interview must leave a gap of at least `mock_buffer_minutes` from every
        other non-cancelled interview of that volunteer — with the default buffer, a
        gap of exactly fifteen minutes is allowed and one of fourteen minutes is
        rejected with `ERR_INTERVIEW_SLOT_CONFLICT`."
        PRD §3.3: "the applicant or an `IntakeCoordinator` may cancel a scheduled
        interview outright — a cancellation frees the slot, removing it from both the
        buffer check and the attempt cap."

        Design: Difficulty/resource_temporal_overlap/mock_interview_volunteer_buffer_gap
        """
        context = setup_mock_booking_context()
        applicant = context["applicant"]
        volunteer = context["volunteer"]
        first = book_mock_interview(applicant["id"], volunteer["id"],
                                    scheduled_start="2026-08-10T10:00:00Z")

        # A 30-minute interview starting 09:16 ends 09:46: gap of 14 before the
        # existing 10:00 interview — rejected (buffer is symmetric).
        before_too_close = api.create_mock_interview(
            {"applicant_id": applicant["id"], "volunteer_id": volunteer["id"],
             "scheduled_start": "2026-08-10T09:16:00Z", "duration_minutes": 30},
            COORD,
        )
        validate_error(before_too_close, ApiErrorId.ERR_INTERVIEW_SLOT_CONFLICT)

        # Cancelling the existing interview removes it from the buffer check.
        validate_success(api.cancel_mock_interview(first["id"], COORD), 200)
        rebooked = validate_success(
            api.create_mock_interview(
                {"applicant_id": applicant["id"], "volunteer_id": volunteer["id"],
                 "scheduled_start": "2026-08-10T09:16:00Z", "duration_minutes": 30},
                COORD,
            ),
            201,
        )
        assert rebooked["status"] == "SCHEDULED"
