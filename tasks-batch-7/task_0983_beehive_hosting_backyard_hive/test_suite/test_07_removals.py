"""Removal jobs: cooling-off fees, crew scheduling, cross-entity gates, and
validation-order pairs."""
import pytest

from test_helpers import (
    TEST_USERS,
    api_client,
    create_incident_payload,
    create_removal_job_payload,
    create_subscription_for,
    decide_removal,
    make_host_headers,
    request_removal,
    resolve_incident_payload,
    rollover_payload,
    schedule_removal_payload,
    setup_hive_scenario,
    validate_error,
    validate_success,
)

MGR = TEST_USERS["manager_headers"]
OPS = TEST_USERS["ops_headers"]


class TestCoolingOffBoundary:
    def test_exactly_24h_cancel_is_free(self, api):
        """PRD §3.8: "cancelling within 24 hours of `requested_at` is free,
        with the boundary inclusive so exactly 24 hours is also free."

        Design: Difficulty/boundary_precision_check/removal_cooling_off_exact_24h_free
        """
        ctx = setup_hive_scenario()
        host = ctx["host"]
        # requested at the default logical clock 2026-05-01T00:00:00Z.
        job = request_removal(host, ctx["hive"]["id"])
        api_client.set_clock("2026-05-02T00:00:00Z", OPS)  # exactly +24h
        cancelled = validate_success(
            api.cancel_removal_job(job["id"], make_host_headers(host["id"])),
            200,
        )
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["cancellation_fee_cents"] == 0, (
            "exactly requested_at + 24h is inside the free window (inclusive)"
        )

    def test_24h_1m_cancel_incurs_fee(self, api):
        """PRD §3.8: "cancelling within 24 hours of `requested_at` is free,
        with the boundary inclusive so exactly 24 hours is also free;
        cancelling later sets `cancellation_fee_cents` to 7500."

        Design: Difficulty/boundary_precision_check/removal_cooling_off_exact_24h_free
        """
        ctx = setup_hive_scenario()
        host = ctx["host"]
        first = request_removal(host, ctx["hive"]["id"], reason="RELOCATION")
        api_client.set_clock("2026-05-02T00:00:00Z", OPS)
        validate_success(
            api.cancel_removal_job(first["id"], make_host_headers(host["id"])),
            200,
        )
        # Second job requested at 2026-05-02T00:00:00Z (only possible because
        # the first is already terminal).
        second = validate_success(
            api.create_removal_job(
                create_removal_job_payload(ctx["hive"]["id"], reason="NUISANCE"),
                make_host_headers(host["id"]),
            ),
            201,
        )
        api_client.set_clock("2026-05-03T00:01:00Z", OPS)  # 24h 1m elapsed
        cancelled = validate_success(
            api.cancel_removal_job(second["id"], make_host_headers(host["id"])),
            200,
        )
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["cancellation_fee_cents"] == 7500, (
            "one minute past the boundary flips the fee"
        )


class TestCrewScheduleBuffer:
    def _two_approved_jobs(self):
        ctx = setup_hive_scenario()
        host, site, agreement = ctx["host"], ctx["site"], ctx["agreement"]
        hive2 = validate_success(
            api_client.create_hive(
                {"site_id": site["id"], "agreement_id": agreement["id"]}, MGR,
            ),
            201,
        )
        job1 = request_removal(host, ctx["hive"]["id"])
        decide_removal(job1["id"], "APPROVE")
        job2 = request_removal(host, hive2["id"], reason="EXIT")
        decide_removal(job2["id"], "APPROVE")
        ctx["hive2"] = hive2
        ctx["job1"] = job1
        ctx["job2"] = job2
        return ctx

    def test_thirty_minute_gap_rejected(self, api):
        """PRD §3.8: "each scheduled job occupies a two-hour window starting at
        its `scheduled_start`, and no other `SCHEDULED` job with the same
        `crew_id` may sit closer than two hours to that window — a gap of at
        least two hours between job windows is required, and a gap of exactly
        two hours is allowed. A tighter assignment fails with
        `ERR_CREW_SCHEDULE_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/crew_schedule_buffer_gap_semantics
        """
        ctx = self._two_approved_jobs()
        scheduled = validate_success(
            api.schedule_removal_job(
                ctx["job1"]["id"],
                schedule_removal_payload("2026-06-10T09:00:00Z", "crew-1"),
                MGR,
            ),
            200,
        )
        assert scheduled["status"] == "SCHEDULED", (
            "job1 occupies [09:00, 11:00) for crew-1"
        )
        # 11:30 leaves only a 30-minute gap after job1's window: rejected.
        res = api.schedule_removal_job(
            ctx["job2"]["id"],
            schedule_removal_payload("2026-06-10T11:30:00Z", "crew-1"),
            MGR,
        )
        validate_error(res, "ERR_CREW_SCHEDULE_CONFLICT")

    def test_exactly_two_hour_gap_allowed(self, api):
        """PRD §3.8: "a gap of at least two hours between job windows is
        required, and a gap of exactly two hours is allowed."

        Design: Difficulty/resource_temporal_overlap/crew_schedule_buffer_gap_semantics
        """
        ctx = self._two_approved_jobs()
        validate_success(
            api.schedule_removal_job(
                ctx["job1"]["id"],
                schedule_removal_payload("2026-06-10T09:00:00Z", "crew-1"),
                MGR,
            ),
            200,
        )
        # 13:00 starts exactly 2h after job1's window ends at 11:00.
        scheduled = validate_success(
            api.schedule_removal_job(
                ctx["job2"]["id"],
                schedule_removal_payload("2026-06-10T13:00:00Z", "crew-1"),
                MGR,
            ),
            200,
        )
        assert scheduled["status"] == "SCHEDULED", (
            "a gap of exactly 2h is allowed (inclusive boundary)"
        )


class TestScheduleValidationOrdering:
    def _conflict_and_short_notice_setup(self):
        """job1 SCHEDULED [2026-06-10 09:00, 11:00) for crew-1; job2 APPROVED;
        logical clock at 2026-06-09T12:00:00Z."""
        ctx = setup_hive_scenario()
        host, site, agreement = ctx["host"], ctx["site"], ctx["agreement"]
        hive2 = validate_success(
            api_client.create_hive(
                {"site_id": site["id"], "agreement_id": agreement["id"]}, MGR,
            ),
            201,
        )
        job1 = request_removal(host, ctx["hive"]["id"])
        decide_removal(job1["id"], "APPROVE")
        validate_success(
            api_client.schedule_removal_job(
                job1["id"],
                schedule_removal_payload("2026-06-10T09:00:00Z", "crew-1"),
                MGR,
            ),
            200,
        )
        job2 = request_removal(host, hive2["id"], reason="HEALTH")
        decide_removal(job2["id"], "APPROVE")
        api_client.set_clock("2026-06-09T12:00:00Z", OPS)
        ctx["job2"] = job2
        return ctx

    def test_crew_conflict_beats_notice_temporal(self, api):
        """PRD §2.12: "Every request passes through a fixed pipeline of checks,
        evaluated in this order, and the first failure determines the error
        returned"
        PRD §2.12 step 8: "site `CLEAR` for installs, splits, and captures;
        occupancy below capacity; agreement term windows; treatment windows;
        crew buffers; one non-terminal subscription per host; course
        prerequisites; surfaced as `ERR_SITE_BLOCKED`,
        `ERR_SITE_CAPACITY_EXCEEDED`, `ERR_AGREEMENT_WINDOW_OVERLAP`,
        `ERR_TREATMENT_WINDOW_OVERLAP`, `ERR_CREW_SCHEDULE_CONFLICT`,
        `ERR_DUPLICATE_SUBSCRIPTION`, or `ERR_COURSE_PREREQUISITE_NOT_MET`
        (409)."
        PRD §2.12 step 10: "harvest freshness (a `VERIFIED` inspection with
        `inspected_at` within the closed window from 30 days before
        `collected_on` through `collected_on`), the 48-hour removal notice, the
        72-hour swarm window, and the requirement that swarm captures and hive
        installs fall within the agreement term; surfaced as
        `ERR_INSPECTION_STALE`, `ERR_REMOVAL_NOTICE_TOO_SHORT`,
        `ERR_SWARM_NOT_ACTIONABLE`, or `ERR_AGREEMENT_NOT_ACTIVE`."

        Design: Difficulty/priority_pair_validation_conflict/schedule_crew_conflict_beats_notice_temporal
        """
        ctx = self._conflict_and_short_notice_setup()
        # 10:30 overlaps job1's [09:00, 11:00) window AND is only ~22.5h
        # ahead of the clock — both rules fail; the constraint error wins.
        res = api.schedule_removal_job(
            ctx["job2"]["id"],
            schedule_removal_payload("2026-06-10T10:30:00Z", "crew-1"),
            MGR,
        )
        validate_error(res, "ERR_CREW_SCHEDULE_CONFLICT")
        job = validate_success(api.get_removal_job(ctx["job2"]["id"], MGR))
        assert job["status"] == "APPROVED", (
            "failed schedule leaves the job schedulable"
        )

    def test_short_notice_fires_alone_without_conflict(self, api):
        """PRD §3.8: "Scheduling an approved job requires a `scheduled_start`
        no earlier than 48 hours after the current logical time — the boundary
        is inclusive, so exactly 48 hours qualifies; shorter notice fails with
        `ERR_REMOVAL_NOTICE_TOO_SHORT`."

        Design: Difficulty/priority_pair_validation_conflict/schedule_crew_conflict_beats_notice_temporal
        """
        ctx = self._conflict_and_short_notice_setup()
        # A different crew removes the constraint failure; only the 48h
        # temporal rule can fail (start ~22.5h ahead of the clock).
        res = api.schedule_removal_job(
            ctx["job2"]["id"],
            schedule_removal_payload("2026-06-10T10:30:00Z", "crew-2"),
            MGR,
        )
        validate_error(res, "ERR_REMOVAL_NOTICE_TOO_SHORT")


class TestRemovalNoticeBoundary:
    def test_notice_boundary_inclusive(self, api):
        """PRD §3.8: "Scheduling an approved job requires a `scheduled_start`
        no earlier than 48 hours after the current logical time — the boundary
        is inclusive, so exactly 48 hours qualifies; shorter notice fails with
        `ERR_REMOVAL_NOTICE_TOO_SHORT`."

        Design: Corner/validations/removal_schedule_notice_boundary
        """
        ctx = setup_hive_scenario()
        job = request_removal(ctx["host"], ctx["hive"]["id"])
        decide_removal(job["id"], "APPROVE")
        # Clock is the default 2026-05-01T00:00:00Z.
        res = api.schedule_removal_job(
            job["id"],
            schedule_removal_payload("2026-05-02T12:00:00Z", "crew-1"),
            MGR,
        )
        validate_error(res, "ERR_REMOVAL_NOTICE_TOO_SHORT")  # +36h
        scheduled = validate_success(
            api.schedule_removal_job(
                job["id"],
                schedule_removal_payload("2026-05-03T00:00:00Z", "crew-1"),
                MGR,
            ),
            200,
        )
        assert scheduled["status"] == "SCHEDULED", "+48h qualifies (inclusive)"


class TestIncidentGate:
    def _setup_with_open_incident(self):
        ctx = setup_hive_scenario()
        host, site = ctx["host"], ctx["site"]
        job = request_removal(host, ctx["hive"]["id"], reason="NUISANCE")
        incident = validate_success(
            api_client.create_incident(
                create_incident_payload(site["id"], severity="MINOR"),
                make_host_headers(host["id"]),
            ),
            201,
        )
        ctx["job"] = job
        ctx["incident"] = incident
        return ctx

    def test_approve_blocked_by_open_incident(self, api, ops_headers):
        """PRD §3.8: "Approval is referentially gated: if any incident on the
        hive's site is still `REPORTED`, the decision is rejected with
        `ERR_SITE_HAS_OPEN_INCIDENTS`."

        Design: Difficulty/cross_entity_state_dependency/removal_approve_blocked_by_open_incident
        """
        ctx = self._setup_with_open_incident()
        res = api.decide_removal_job(
            ctx["job"]["id"], {"decision": "APPROVE"}, MGR,
        )
        validate_error(res, "ERR_SITE_HAS_OPEN_INCIDENTS")
        # One MINOR report does not block the site itself.
        site = validate_success(api.get_site(ctx["site"]["id"], ops_headers))
        assert site["status"] == "CLEAR", (
            "the removal gate is a separate cross-entity rule"
        )

    def test_approve_succeeds_after_incident_dismissed(self, api):
        """PRD §3.8: "Approval is referentially gated: if any incident on the
        hive's site is still `REPORTED`, the decision is rejected with
        `ERR_SITE_HAS_OPEN_INCIDENTS`; otherwise the job becomes `APPROVED`."

        Design: Difficulty/cross_entity_state_dependency/removal_approve_blocked_by_open_incident
        """
        ctx = self._setup_with_open_incident()
        validate_success(
            api.resolve_incident(
                ctx["incident"]["id"], resolve_incident_payload("DISMISSED"),
                MGR,
            ),
            200,
        )
        approved = validate_success(
            api.decide_removal_job(
                ctx["job"]["id"], {"decision": "APPROVE"}, MGR,
            ),
            200,
        )
        assert approved["status"] == "APPROVED"


class TestRemovalRequestGates:
    def _expired_waiver_with_balance(self):
        """Host signed waiver at the default clock 2026-05-01; BASIC
        subscription invoice left UNPAID; clock advanced to 2027-05-02
        (waiver age 366 days)."""
        ctx = setup_hive_scenario()
        create_subscription_for(ctx["host"], "BASIC")  # invoice unpaid
        api_client.set_clock("2027-05-02T00:00:00Z", OPS)
        return ctx

    def test_waiver_safety_beats_balance_fiscal(self, api, ops_headers):
        """PRD §2.12: "Every request passes through a fixed pipeline of checks,
        evaluated in this order, and the first failure determines the error
        returned"
        PRD §2.12 step 7: "waiver currency where required (agreement signing,
        hive installation, removal requests, enrollment), segregation of
        duties, hive not quarantined for harvest or split, no treatment
        withdrawal window covering `collected_on`; surfaced as
        `ERR_WAIVER_CURRENT_REQUIRED`, `ERR_SEGREGATION_OF_DUTIES`,
        `ERR_HIVE_QUARANTINED`, or `ERR_WITHDRAWAL_WINDOW_ACTIVE`."
        PRD §2.12 step 11: "host `ACTIVE` where required (agreement creation,
        hive installation, enrollment), `balance_due_cents` equal to zero for
        removal requests, agreement termination, subscription cancellation, and
        host reactivation, and `reputation_score` of at least 50 for agreement
        creation; surfaced as `ERR_HOST_NOT_ACTIVE`, `ERR_OUTSTANDING_BALANCE`,
        or `ERR_HOST_REPUTATION_TOO_LOW`."
        PRD §3.1: "A waiver is current only while `waiver_signed_at` is set and
        the present logical time is no later than 365 days after it."

        Design: Difficulty/priority_pair_validation_conflict/removal_waiver_safety_beats_balance_fiscal
        """
        ctx = self._expired_waiver_with_balance()
        host = validate_success(
            api.get_host(ctx["host"]["id"], ops_headers),
        )
        assert host["balance_due_cents"] == 2999, (
            "the fiscal rule also fails at trigger time"
        )
        res = api.create_removal_job(
            create_removal_job_payload(ctx["hive"]["id"], reason="NUISANCE"),
            make_host_headers(ctx["host"]["id"]),
        )
        validate_error(res, "ERR_WAIVER_CURRENT_REQUIRED")

    def test_balance_fiscal_fires_alone_when_waiver_current(self, api):
        """PRD §3.8: "The request requires a current waiver, a zero
        `balance_due_cents` (`ERR_OUTSTANDING_BALANCE` otherwise)."

        Design: Difficulty/priority_pair_validation_conflict/removal_waiver_safety_beats_balance_fiscal
        """
        ctx = setup_hive_scenario()
        create_subscription_for(ctx["host"], "BASIC")  # invoice unpaid
        res = api.create_removal_job(
            create_removal_job_payload(ctx["hive"]["id"], reason="NUISANCE"),
            make_host_headers(ctx["host"]["id"]),
        )
        validate_error(res, "ERR_OUTSTANDING_BALANCE")

    def test_waiver_exactly_365_days_still_current(self, api):
        """PRD §3.1: "A waiver is current only while `waiver_signed_at` is set
        and the present logical time is no later than 365 days after it."

        Design: Corner/validations/waiver_boundary_365d_satisfaction
        """
        ctx = setup_hive_scenario()
        # Signed at the default clock 2026-05-01T00:00:00Z; exactly +365 days.
        api_client.set_clock("2027-05-01T00:00:00Z", OPS)
        job = validate_success(
            api.create_removal_job(
                create_removal_job_payload(ctx["hive"]["id"], reason="EXIT"),
                make_host_headers(ctx["host"]["id"]),
            ),
            201,
        )
        assert job["status"] == "REQUESTED", "365-day boundary is inclusive"

    def test_second_open_removal_job_rejected(self, api):
        """PRD §3.8: "at most one non-terminal removal job per hive — a second
        open job for the same hive fails with `ERR_REMOVAL_NOT_ACTIONABLE`."

        Design: Corner/errors/duplicate_removal_job_rejected
        """
        ctx = setup_hive_scenario()
        host = ctx["host"]
        first = request_removal(host, ctx["hive"]["id"], reason="NUISANCE")
        res = api.create_removal_job(
            create_removal_job_payload(ctx["hive"]["id"], reason="EXIT"),
            make_host_headers(host["id"]),
        )
        validate_error(res, "ERR_REMOVAL_NOT_ACTIONABLE")
        current = validate_success(api.get_removal_job(first["id"], MGR))
        assert current["status"] == "REQUESTED"
