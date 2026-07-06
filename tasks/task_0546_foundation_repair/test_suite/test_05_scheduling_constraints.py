"""Install scheduling checks (PRD §3.5) and crew-minute conservation (PRD §3.5/§3.6):
half-open crew overlap, region match, window validity, permit approval, safety-vs-permit
precedence, and the book/release invariant."""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    setup_accepted_job,
    setup_job_ready_to_schedule,
    setup_scheduled_job,
    setup_two_jobs_first_scheduled,
    create_crew,
    schedule_job_payload,
    api_client,
    OPS,
    ApiErrorId,
)


class TestCrewDoubleBooking:
    def test_overlapping_window_rejected(self, api):
        """PRD §3.5: "The chosen crew must not already have a job in `SCHEDULED` or
        `IN_PROGRESS` whose half-open window overlaps the requested
        `[scheduled_start, scheduled_end)` — abutting windows that merely touch at an
        endpoint are allowed, but any true overlap is rejected with
        `ERR_CREW_DOUBLE_BOOKED`."

        Design: Difficulty/resource_temporal_overlap/crew_double_book_halfopen_overlap
        """
        ctx = setup_two_jobs_first_scheduled()  # job1 booked 08:00-12:00
        res = api.schedule_job(
            ctx["job2"]["id"],
            schedule_job_payload(ctx["crew"]["id"],
                                 "2026-06-01T10:00:00Z", "2026-06-01T14:00:00Z"),
            OPS,
        )
        validate_error(res, ApiErrorId.ERR_CREW_DOUBLE_BOOKED.value)

    def test_abutting_window_allowed(self, api):
        """PRD §3.5: "abutting windows that merely touch at an endpoint are allowed, but any
        true overlap is rejected with `ERR_CREW_DOUBLE_BOOKED`."

        Design: Difficulty/resource_temporal_overlap/crew_double_book_halfopen_overlap
        """
        ctx = setup_two_jobs_first_scheduled()  # job1 booked 08:00-12:00
        # [12:00,16:00) touches [08:00,12:00) only at the shared endpoint -> allowed.
        scheduled = validate_success(
            api.schedule_job(
                ctx["job2"]["id"],
                schedule_job_payload(ctx["crew"]["id"],
                                     "2026-06-01T12:00:00Z", "2026-06-01T16:00:00Z"),
                OPS,
            ),
            200,
        )
        assert scheduled["fulfillment_status"] == "SCHEDULED", scheduled


class TestCrewMinutesConservation:
    def test_schedule_books_window_minutes(self, api):
        """PRD §3.5: "On success the server records the `crew_id`, `scheduled_start`, and
        `scheduled_end` on the job and increases the crew's `booked_minutes` by the window's
        minutes."

        Design: Difficulty/compensating_invariant/crew_book_then_release_conserves_minutes
        """
        ctx = setup_scheduled_job()  # 08:00-12:00 = 240 minutes
        crew = validate_success(api.get_crew(ctx["crew"]["id"], OPS), 200)
        assert crew["booked_minutes"] == 240, crew

    def test_cancel_releases_window_minutes(self, api):
        """PRD §3.6: "Cancelling from `SCHEDULED`: the crew's `booked_minutes` is decreased
        by the job's window minutes, and, if the job carries a `quote_id`, the lead's
        `financing_balance_cents` is likewise decreased by the quote's `total_cents`."

        Design: Difficulty/compensating_invariant/crew_book_then_release_conserves_minutes
        """
        ctx = setup_scheduled_job()  # booked 240 minutes
        validate_success(api.cancel_job(ctx["job"]["id"], OPS), 200)
        crew = validate_success(api.get_crew(ctx["crew"]["id"], OPS), 200)
        assert crew["booked_minutes"] == 0, crew


class TestSafetyBeatsPermitPrecedence:
    def test_unsafe_soil_reported_over_permit(self, api):
        """PRD §2.10: "scheduling an install checks legal state, then unstable soil, then
        crew double-booking, then permit approval, then crew-region match, then window
        validity, in exactly that sequence."
        PRD §3.5: "If the job's source inspection recorded a `soil_class` of `UNSTABLE`, then
        the backing scope must have `supplemental_engineering` set to true; unstable soil
        without that mitigation is rejected with `ERR_UNSAFE_SOIL_UNMITIGATED`."

        Design: Difficulty/priority_pair_validation_conflict/unsafe_soil_safety_beats_permit_referential
        """
        # UNSTABLE soil unmitigated AND permit NOT_STARTED (never opened).
        ctx = setup_accepted_job(soil_class="UNSTABLE", supplemental_engineering=False)
        crew = create_crew(region_code="NORTH")
        res = api.schedule_job(
            ctx["job"]["id"], schedule_job_payload(crew["id"]), OPS
        )
        validate_error(res, ApiErrorId.ERR_UNSAFE_SOIL_UNMITIGATED.value)

    def test_soil_error_status_precedes_permit_error(self, api):
        """PRD §2.10: "scheduling an install checks legal state, then unstable soil, then
        crew double-booking, then permit approval, then crew-region match, then window
        validity, in exactly that sequence."

        Design: Difficulty/priority_pair_validation_conflict/unsafe_soil_safety_beats_permit_referential
        """
        ctx = setup_accepted_job(soil_class="UNSTABLE", supplemental_engineering=False)
        crew = create_crew(region_code="NORTH")
        res = api.schedule_job(ctx["job"]["id"], schedule_job_payload(crew["id"]), OPS)
        # Soil check (422) is reported, not the lower-priority permit check (409).
        assert res.status_code == 422, res.text
        assert res.json()["data"]["error_id"] == "ERR_UNSAFE_SOIL_UNMITIGATED", res.text


class TestSchedulingViolations:
    def test_permit_not_approved_rejected(self, api):
        """PRD §3.5: "The job's `permit_status` must be `APPROVED`, or the request is
        rejected with `ERR_PERMIT_NOT_APPROVED`."

        Design: Corner/validations/schedule_permit_not_approved_returns_error
        """
        ctx = setup_accepted_job(soil_class="STABLE")
        # Open a permit but leave it PENDING (never decided).
        get_success_data(
            api.create_permit({"job_id": ctx["job"]["id"], "permit_type": "STANDARD"}, OPS)
        )
        crew = create_crew(region_code="NORTH")
        res = api.schedule_job(ctx["job"]["id"], schedule_job_payload(crew["id"]), OPS)
        validate_error(res, ApiErrorId.ERR_PERMIT_NOT_APPROVED.value)

    def test_crew_region_mismatch_rejected(self, api):
        """PRD §3.5: "And the crew's `region_code` must equal the lead's `region_code`, or
        the request is rejected with `ERR_CREW_REGION_MISMATCH`."

        Design: Corner/validations/schedule_crew_region_mismatch_returns_error
        """
        # Permit approved; crew serves SOUTH while lead is NORTH.
        ctx = setup_job_ready_to_schedule(crew_region="SOUTH", soil_class="STABLE")
        res = api.schedule_job(
            ctx["job"]["id"], schedule_job_payload(ctx["crew"]["id"]), OPS
        )
        validate_error(res, ApiErrorId.ERR_CREW_REGION_MISMATCH.value)

    def test_schedule_window_invalid_rejected(self, api):
        """PRD §3.5: "The window must be valid — `scheduled_end` strictly after
        `scheduled_start` — or the request fails with `ERR_SCHEDULE_WINDOW_INVALID`."

        Design: Corner/validations/schedule_window_invalid_returns_error
        """
        ctx = setup_job_ready_to_schedule(crew_region="NORTH", soil_class="STABLE")
        res = api.schedule_job(
            ctx["job"]["id"],
            schedule_job_payload(ctx["crew"]["id"],
                                 "2026-06-01T08:00:00Z", "2026-06-01T08:00:00Z"),
            OPS,
        )
        validate_error(res, ApiErrorId.ERR_SCHEDULE_WINDOW_INVALID.value)

    def test_pier_count_mismatch_on_complete_rejected(self, api):
        """PRD §3.6: "completion enforces that the actual `piers_installed` deviates from the
        backing scope's `pier_count` by no more than 2 (`PIER_TOLERANCE`); that is, the
        absolute difference between `piers_installed` and `pier_count` must be at most 2, and
        a larger deviation is rejected with `ERR_PIER_COUNT_MISMATCH`."

        Design: Corner/validations/complete_pier_count_mismatch_returns_error
        """
        from test_helpers import setup_in_progress_job, complete_job_payload
        ctx = setup_in_progress_job(soil_class="STABLE", pier_count=8)
        # |20 - 8| = 12 > PIER_TOLERANCE (2).
        res = api.complete_job(ctx["job"]["id"], complete_job_payload(piers_installed=20), OPS)
        validate_error(res, ApiErrorId.ERR_PIER_COUNT_MISMATCH.value)
