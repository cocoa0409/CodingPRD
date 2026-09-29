"""Campaign, scrub-job and dialer-profile state transitions.

Every precondition is built from scratch through the documented endpoints, since
each test runs against an empty database and a logical clock that starts at
`2026-08-01T00:00:00Z`.
"""

from test_helpers import (
    ApiErrorId,
    AttemptOutcome,
    CampaignStatus,
    DEFAULT_WAIVER_REFERENCE,
    DialerLockedReason,
    DialerProfileStatus,
    OFFICER_PROFILE_APPROVER_USER_ID,
    OFFICER_SECOND_APPROVER_USER_ID,
    ScrubJobStatus,
    SuspensionReason,
    VoidReason,
    assert_attempt_budget_conserved,
    assert_decimal_equals,
    assert_error,
    assert_fields_equal,
    assert_fields_null,
    assert_ok,
    assert_page,
    assert_status,
    assert_timestamp_equals,
    assert_total_count,
    assert_version_is,
    factories,
    make_compliance_officer_headers,
)


def _breach_the_abandonment_ceiling(world, campaign_id, contact_id):
    """Record one live answer and one abandonment on the same measurement day.

    Two live answers with one abandonment among them puts the campaign's
    regulatory rate at 50.00 percent.
    """
    first = world.create_attempt(campaign_id, contact_id)
    world.record_outcome(
        first["id"], outcome=AttemptOutcome.CONNECTED_LIVE, agent_connect_seconds=1
    )
    world.set_clock("2026-08-03T00:31:00Z")
    second = world.create_attempt(campaign_id, contact_id)
    world.record_outcome(
        second["id"], outcome=AttemptOutcome.ABANDONED, abandon_message_played=True
    )
    return first, second


class TestCampaignLifecycleTransitions:
    """The five campaign statuses and the triggers that move between them."""

    def test_01_campaign_created_starts_in_draft(self, draft_campaign):
        """A freshly created campaign is DRAFT with every derived figure zeroed.

        PRD §3.7: "A new campaign has `status` `DRAFT`, `latest_scrub_status` and
        `measurement_date` and `suspension_reason` and `launch_certified_by_user_id`
        and `pinned_script_version` all null, `eligible_target_count` 0,
        `live_answer_count_today` and `abandoned_count_today` and
        `machine_count_today` and `no_answer_count_today` all 0,
        `permitted_attempt_count` and `voided_attempt_count` 0,
        `regulatory_abandonment_rate_pct` and `internal_abandonment_rate_pct` and
        `rolling_compliance_rate_pct` all `0.00`, and an empty `daily_rate_history`."

        Design: Corner/state_machines/campaign_created_starts_in_draft
        """
        campaign = draft_campaign["campaign"]

        assert_status(campaign, CampaignStatus.DRAFT)
        assert_fields_null(
            campaign,
            "latest_scrub_status",
            "measurement_date",
            "suspension_reason",
            "launch_certified_by_user_id",
            "pinned_script_version",
        )
        assert_fields_equal(
            campaign,
            eligible_target_count=0,
            live_answer_count_today=0,
            abandoned_count_today=0,
            machine_count_today=0,
            no_answer_count_today=0,
            permitted_attempt_count=0,
            voided_attempt_count=0,
            daily_rate_history=[],
        )
        assert_decimal_equals(campaign["regulatory_abandonment_rate_pct"], 0.00)
        assert_decimal_equals(campaign["internal_abandonment_rate_pct"], 0.00)
        assert_decimal_equals(campaign["rolling_compliance_rate_pct"], 0.00)
        assert_version_is(campaign, 1)

    def test_02_launch_from_draft_rejected_as_campaign_state_invalid(
        self, world, draft_campaign
    ):
        """Certifying a campaign that never had a completed scrub is refused.

        PRD §3.7: "The officer supplies a `certification_note` and the
        `expected_campaign_version` of §2.6, and the campaign must currently be in
        `PENDING_LAUNCH`; certifying a `DRAFT`, `ACTIVE`, `SUSPENDED` or `CLOSED`
        campaign is refused with `ERR_CAMPAIGN_STATE_INVALID`."

        Design: Corner/state_machines/campaign_launch_from_draft_returns_state_invalid
        """
        campaign = draft_campaign["campaign"]

        response = world.api.launch_campaign(
            campaign["id"],
            factories.campaign_launch_payload(
                expected_campaign_version=campaign["version"]
            ),
            world.launcher,
        )
        assert_error(response, ApiErrorId.CAMPAIGN_STATE_INVALID)

        refused = world.read_campaign(campaign["id"])
        assert_status(refused, CampaignStatus.DRAFT)
        assert_fields_null(refused, "launch_certified_by_user_id")
        assert_version_is(refused, 1)

    def test_03_manual_suspension_resumes_to_active(self, world, active_campaign):
        """A manually suspended campaign resumes and dials again.

        PRD §3.7: "Resumption is `SUSPENDED → ACTIVE`, driven by a
        `ComplianceOfficer` with a `resume_note`, and the guard it must pass depends
        on why the campaign went down — in every case on the state of some *other*
        entity."
        PRD §3.7: "A campaign suspended `MANUAL`ly carries no extra guard."
        PRD §3.7: "Where the applicable guard still fails, resumption is refused with
        `ERR_RESUME_BLOCKED`; where it holds, `suspension_reason` is cleared back to
        null and the campaign's `version` increments."

        Design: Corner/state_machines/campaign_suspend_then_resume_returns_to_active
        """
        campaign = active_campaign["campaign"]
        contact = active_campaign["contact"]

        suspended = world.suspend_campaign(
            campaign["id"], suspension_note="Manual pause for QA"
        )
        assert_status(suspended, CampaignStatus.SUSPENDED)
        assert_fields_equal(suspended, suspension_reason=SuspensionReason.MANUAL)

        world.set_clock("2026-08-03T01:00:00Z")
        resumed = world.resume_campaign(campaign["id"], resume_note="QA cleared")
        assert_status(resumed, CampaignStatus.ACTIVE)
        assert_fields_null(resumed, "suspension_reason")

        attempt = world.create_attempt(campaign["id"], contact["id"])
        assert_fields_equal(
            attempt, outcome=AttemptOutcome.PENDING, campaign_id=campaign["id"]
        )

        charged = world.read_contact(contact["id"])
        assert_fields_equal(charged, attempts_charged=1, attempt_budget_remaining=2)
        assert_attempt_budget_conserved(charged)

    def test_04_closed_campaign_rejects_resume(self, world, active_campaign):
        """CLOSED is terminal, so a closed campaign can never be resumed.

        PRD §3.7: "`CLOSED` accepts nothing further, and any trigger against a closed
        campaign is refused with `ERR_CAMPAIGN_STATE_INVALID`."
        PRD §3.7: "Resuming a campaign that is not `SUSPENDED` is refused with
        `ERR_CAMPAIGN_STATE_INVALID`."

        Design: Corner/state_machines/campaign_closed_is_terminal_and_rejects_resume
        """
        campaign = active_campaign["campaign"]

        closed = world.close_campaign(campaign["id"], closure_note="Quarter finished")
        assert_status(closed, CampaignStatus.CLOSED)

        response = world.api.resume_campaign(
            campaign["id"],
            factories.campaign_resume_payload(resume_note="Reopen"),
            world.officer,
        )
        assert_error(response, ApiErrorId.CAMPAIGN_STATE_INVALID)

        assert_status(world.read_campaign(campaign["id"]), CampaignStatus.CLOSED)

    def test_05_close_voids_only_pending_attempts(self, world, active_campaign):
        """Closure voids the pending attempt and leaves the recorded one alone.

        PRD §3.7: "Closing from `ACTIVE` additionally voids the campaign's `PENDING`
        attempts with `void_reason` `CAMPAIGN_SUSPENDED` and credits those consumers'
        attempt budgets, exactly as a suspension would."
        PRD §2.10: "Creating an attempt charges exactly one; voiding an attempt —
        whether an officer voided it by hand or a campaign suspension voided it as a
        cascade — credits exactly one back."

        Design: Corner/state_machines/campaign_close_voids_only_pending_attempts
        """
        campaign = active_campaign["campaign"]
        contact = active_campaign["contact"]

        recorded = world.create_attempt(campaign["id"], contact["id"])
        world.record_outcome(
            recorded["id"],
            outcome=AttemptOutcome.CONNECTED_LIVE,
            agent_connect_seconds=1,
        )

        world.set_clock("2026-08-03T00:31:00Z")
        pending = world.create_attempt(campaign["id"], contact["id"])

        closed = world.close_campaign(campaign["id"], closure_note="Campaign finished")
        assert_status(closed, CampaignStatus.CLOSED)

        survivor = assert_ok(
            world.api.get_contact_attempt(recorded["id"], world.operator)
        )
        assert_fields_equal(survivor, outcome=AttemptOutcome.CONNECTED_LIVE)
        assert_fields_null(survivor, "voided_at")

        voided = assert_ok(world.api.get_contact_attempt(pending["id"], world.operator))
        assert_fields_equal(
            voided,
            outcome=AttemptOutcome.VOIDED,
            void_reason=VoidReason.CAMPAIGN_SUSPENDED,
        )

        credited = world.read_contact(contact["id"])
        assert_fields_equal(credited, attempts_charged=1, attempt_budget_remaining=2)
        assert_attempt_budget_conserved(credited)

        final = world.read_campaign(campaign["id"])
        assert_fields_equal(final, live_answer_count_today=1)
        assert_decimal_equals(final["regulatory_abandonment_rate_pct"], 0.00)


class TestScrubJobExecutionTransitions:
    """Scrub jobs are dated evidence: they execute once and are superseded."""

    def test_06_execute_completed_job_rejected(self, world, scrubbed_campaign):
        """A completed scrub job cannot be executed a second time.

        PRD §3.4: "The job must still be `PENDING` — a `COMPLETED`, `FAILED`,
        `SUPERSEDED` or `INVALIDATED` job cannot be executed again, and the attempt is
        refused with `ERR_SCRUB_JOB_STATE_INVALID` — and the owning campaign must
        still be in `DRAFT` or `PENDING_LAUNCH`."
        PRD §3.4: "The job's `completed_at` is stamped at the current clock instant and
        `expires_at` is set to 31 days after `completed_at`."

        Design: Corner/state_machines/scrub_job_execute_twice_returns_state_invalid
        """
        job = scrubbed_campaign["scrub_job"]
        assert_status(job, ScrubJobStatus.COMPLETED)

        world.set_clock("2026-08-03T02:00:00Z")
        response = world.api.execute_scrub_job(job["id"], world.manager)
        assert_error(response, ApiErrorId.SCRUB_JOB_STATE_INVALID)

        unchanged = assert_ok(world.api.get_scrub_job(job["id"], world.manager))
        assert_status(unchanged, ScrubJobStatus.COMPLETED)
        assert_timestamp_equals(unchanged["completed_at"], "2026-08-03T00:00:00.000Z")
        assert_timestamp_equals(unchanged["expires_at"], "2026-09-03T00:00:00.000Z")

    def test_07_newer_completed_scrub_supersedes_previous(
        self, world, scrubbed_campaign
    ):
        """A second completed scrub flips the first to SUPERSEDED.

        PRD §3.4: "Every other scrub job of the same campaign that was sitting in
        `COMPLETED` moves `COMPLETED → SUPERSEDED`."
        PRD §3.4: "A campaign's `latest_scrub_status` always reflects the newest job of
        that campaign ordered by `requested_at` descending with ties broken by
        `created_at` ascending, and takes one of `PENDING`, `COMPLETED`, `FAILED`,
        `SUPERSEDED` or `INVALIDATED`."

        Design: Corner/state_machines/newer_completed_scrub_supersedes_the_previous_one
        """
        campaign = scrubbed_campaign["campaign"]
        first_job = scrubbed_campaign["scrub_job"]

        world.set_clock("2026-08-03T04:00:00Z")
        second_job = world.scrub_campaign(campaign["id"])

        superseded = assert_ok(world.api.get_scrub_job(first_job["id"], world.manager))
        assert_status(superseded, ScrubJobStatus.SUPERSEDED)
        assert_fields_null(superseded, "invalidation_reason")
        assert_timestamp_equals(superseded["completed_at"], "2026-08-03T00:00:00.000Z")

        assert_status(second_job, ScrubJobStatus.COMPLETED)
        assert_timestamp_equals(second_job["completed_at"], "2026-08-03T04:00:00.000Z")
        assert_timestamp_equals(second_job["expires_at"], "2026-09-03T04:00:00.000Z")
        assert_fields_equal(second_job, eligible_target_count=1)

        promoted = world.read_campaign(campaign["id"])
        assert_status(promoted, CampaignStatus.PENDING_LAUNCH)
        assert_fields_equal(promoted, latest_scrub_status=ScrubJobStatus.COMPLETED)

        _rows, meta = assert_page(
            world.api.list_campaign_scrub_jobs(campaign["id"], world.manager)
        )
        assert_total_count(meta, 2)


class TestDialerProfileApprovalTrack:
    """The dialer profile's DRAFT / APPROVED / LOCKED cycle."""

    def test_08_approve_already_approved_profile_rejected(self, world):
        """Re-approving an approved profile is refused and keeps the first approver.

        PRD §3.6: "A `ComplianceOfficer` approves a profile from either `DRAFT` or
        `LOCKED`, so both `DRAFT → APPROVED` and `LOCKED → APPROVED` are admissible
        and behave identically; approving one that is already `APPROVED` is refused
        with `ERR_DIALER_PROFILE_STATE_INVALID`."
        PRD §3.6: "Approval moves the profile to `APPROVED`, records the approving
        officer's `X-User-ID` in `approved_by_user_id`, clears `locked_reason` back to
        null, stores the supplied `waiver_reference` (which stays null when
        `requires_waiver` is false), and recomputes `max_lines_last_computed` treating
        the campaign's regulatory abandonment rate as `0.00`, since at approval time
        the profile may have no campaign at all."

        Design: Corner/state_machines/dialer_profile_approve_twice_returns_state_invalid
        """
        world.set_clock("2026-08-03T00:00:00Z")
        profile = world.create_dialer_profile()
        approved = world.approve_dialer_profile(profile["id"], DEFAULT_WAIVER_REFERENCE)
        assert_status(approved, DialerProfileStatus.APPROVED)

        response = world.api.approve_dialer_profile(
            profile["id"],
            factories.dialer_profile_approve_payload(
                waiver_reference="WVR-2026-0999"
            ),
            make_compliance_officer_headers(OFFICER_SECOND_APPROVER_USER_ID),
        )
        assert_error(response, ApiErrorId.DIALER_PROFILE_STATE_INVALID)

        unchanged = assert_ok(world.api.get_dialer_profile(profile["id"], world.officer))
        assert_status(unchanged, DialerProfileStatus.APPROVED)
        assert_fields_equal(
            unchanged,
            approved_by_user_id=OFFICER_PROFILE_APPROVER_USER_ID,
            waiver_reference=DEFAULT_WAIVER_REFERENCE,
            max_lines_last_computed=7,
        )

    def test_09_locked_profile_returns_to_approved_on_fresh_approval(self, world):
        """A profile locked by an abandonment breach is unlocked by a fresh approval.

        PRD §3.6: "The reverse move, `APPROVED → LOCKED`, is never requested by a
        client: it is the second hop of the abandonment cascade in §3.8, sets
        `locked_reason` to `ABANDONMENT_BREACH`, and is undone only by a fresh approval
        — which is exactly what makes a campaign suspended for a locked profile
        resumable again."
        PRD §3.6: "Approval moves the profile to `APPROVED`, records the approving
        officer's `X-User-ID` in `approved_by_user_id`, clears `locked_reason` back to
        null, stores the supplied `waiver_reference` (which stays null when
        `requires_waiver` is false), and recomputes `max_lines_last_computed` treating
        the campaign's regulatory abandonment rate as `0.00`, since at approval time
        the profile may have no campaign at all."

        Design: Corner/state_machines/locked_dialer_profile_can_be_reapproved_back_to_approved
        """
        built = world.build(abandonment_limit_pct=40.0)
        campaign = built["campaign"]
        contact = built["contact"]
        profile = built["profile"]

        _breach_the_abandonment_ceiling(world, campaign["id"], contact["id"])

        locked = assert_ok(world.api.get_dialer_profile(profile["id"], world.officer))
        assert_status(locked, DialerProfileStatus.LOCKED)
        assert_fields_equal(
            locked, locked_reason=DialerLockedReason.ABANDONMENT_BREACH
        )

        reapproved = world.approve_dialer_profile(
            profile["id"], DEFAULT_WAIVER_REFERENCE
        )
        assert_status(reapproved, DialerProfileStatus.APPROVED)
        assert_fields_null(reapproved, "locked_reason")
        assert_fields_equal(reapproved, max_lines_last_computed=7)

        still_down = world.read_campaign(campaign["id"])
        assert_status(still_down, CampaignStatus.SUSPENDED)
        assert_fields_equal(
            still_down, suspension_reason=SuspensionReason.ABANDONMENT_BREACH
        )
