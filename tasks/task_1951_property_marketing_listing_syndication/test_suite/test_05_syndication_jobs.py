"""Syndication jobs: retry/backoff to dead-letter, breach accounting variants,
portal-active gating, buffered blackout dispatch, SLA strict-greater boundary,
and subscription/job validations (PRD §3.5, §3.6)."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    create_patch_listing_payload,
    create_active_listing, create_syndicated_listing, create_portal,
    subscribe_listing, owner_headers, get_listing, get_summary,
    list_jobs_of_subscription, list_jobs_of_listing, find_job,
    set_clock, run_sweep,
    TEST_USERS,
    ApiErrorId,
)

MC = TEST_USERS["marketing_coordinator_headers"]
MD = TEST_USERS["marketing_director_headers"]
PW = TEST_USERS["portal_webhook_headers"]


def _fail(job_id, code):
    return api_client.fail_feed_event(job_id, {"error_code": code}, PW)


class TestRetryCycleToDeadLetter:
    def test_failures_retry_with_exponential_backoff(self, api):
        """PRD §3.6: "When the job has made fewer than three attempts, it moves from
        `FAILED` to `RETRY_QUEUED` with a new `scheduled_at` set sixty seconds times
        two raised to the power of the job's current `attempt_count` after the
        failure — one minute after the first failure, two after the second."

        Design: Difficulty/non_linear_state_machine/syndication_job_retry_cycle_to_dead_letter
        """
        agent, active, portal, sub = create_syndicated_listing(
            portal_overrides={"sla_seconds": 3600})
        job = dispatch = find_job(list_jobs_of_subscription(sub["id"]), job_type="FULL_SYNC")
        run_sweep()  # dispatch attempt 1 at 2026-08-01T00:00:00Z

        failed = validate_success(_fail(job["id"], "E1"), 200)
        assert failed["status"] == "RETRY_QUEUED"
        assert failed["attempt_count"] == 1
        assert failed["scheduled_at"].startswith("2026-08-01T00:02:00"), (
            "first retry is scheduled 60 * 2^1 seconds after the failure"
        )

        set_clock("2026-08-01T00:02:00Z")
        run_sweep()  # dispatch attempt 2 at 00:02
        job_now = find_job(list_jobs_of_subscription(sub["id"]), job_type="FULL_SYNC")
        assert job_now["status"] == "DISPATCHED" and job_now["attempt_count"] == 2

        failed2 = validate_success(_fail(job["id"], "E2"), 200)
        assert failed2["status"] == "RETRY_QUEUED"
        assert failed2["attempt_count"] == 2
        assert failed2["scheduled_at"].startswith("2026-08-01T00:06:00"), (
            "second retry is scheduled 60 * 2^2 seconds after the failure"
        )

    def test_third_failure_dead_letters_and_degrades_posture(self, api):
        """PRD §3.6: "When the failure is the job's third, the job moves instead from
        `FAILED` to the terminal `DEAD_LETTER` status with `completed_at` stamped,
        the listing's audited breach count increases by one, and the posture
        recomputes — to `DEGRADED`, per the precedence of §2.6."

        Design: Difficulty/non_linear_state_machine/syndication_job_retry_cycle_to_dead_letter
        """
        agent, active, portal, sub = create_syndicated_listing(
            portal_overrides={"sla_seconds": 3600})
        job = find_job(list_jobs_of_subscription(sub["id"]), job_type="FULL_SYNC")

        run_sweep()  # attempt 1 at 00:00
        validate_success(_fail(job["id"], "E1"), 200)
        set_clock("2026-08-01T00:02:00Z")
        run_sweep()  # attempt 2 at 00:02
        validate_success(_fail(job["id"], "E2"), 200)
        set_clock("2026-08-01T00:06:00Z")
        run_sweep()  # attempt 3 at 00:06
        dead = validate_success(_fail(job["id"], "E3"), 200)

        assert dead["status"] == "DEAD_LETTER"
        assert dead["attempt_count"] == 3
        assert dead["completed_at"] is not None
        assert dead["failure_code"] == "E3"

        summary = get_summary(active["id"])
        assert summary["audited_breach_count"] == 1
        assert summary["syndication_posture"] == "DEGRADED"


class TestProvisionalVsAuditedBreachCounts:
    def _setup_in_flight_over_sla(self, api):
        """FULL_SYNC dispatched at 00:00, never acked; clock at 01:10 (4200s in
        flight against a 3600s SLA)."""
        agent, active, portal, sub = create_syndicated_listing(
            portal_overrides={"sla_seconds": 3600})
        run_sweep()  # dispatch at 2026-08-01T00:00:00Z
        set_clock("2026-08-01T01:10:00Z")
        return agent, active, portal, sub

    def test_summary_counts_in_flight_job_provisionally_only(self, api):
        """PRD §3.6: "The `provisional_breach_count` adds a forward-looking term: it
        equals the audited count plus the number of in-flight `DISPATCHED` jobs
        already older than the SLA — jobs for which the seconds between
        `dispatched_at` and now strictly exceed `sla_seconds`."
        PRD §3.6: "The `audited_breach_count` counts terminal evidence only: jobs
        that acknowledged with a `propagation_delay_seconds` strictly greater than
        their portal's `sla_seconds`, plus jobs that died in `DEAD_LETTER`."

        Design: Difficulty/dual_variant_calc/delay_audit_provisional_vs_audited
        """
        agent, active, portal, sub = self._setup_in_flight_over_sla(api)
        summary = get_summary(active["id"])
        assert summary["provisional_breach_count"] == 1
        assert summary["audited_breach_count"] == 0
        assert summary["syndication_posture"] == "SYNDICATING", (
            "DEGRADED keys off terminal evidence only; a live DISPATCHED job is SYNDICATING"
        )

    def test_listing_read_carries_the_same_counters(self, api):
        """PRD §3.6: "Both counters recompute on every job acknowledgement, every
        dead-letter event, every sweep, and every read of the listing or its
        marketing summary."
        PRD §3.6: "The `provisional_breach_count` adds a forward-looking term: it
        equals the audited count plus the number of in-flight `DISPATCHED` jobs
        already older than the SLA"

        Design: Difficulty/dual_variant_calc/delay_audit_provisional_vs_audited
        """
        agent, active, portal, sub = self._setup_in_flight_over_sla(api)
        listing = get_listing(active["id"])
        assert listing["provisional_breach_count"] == 1
        assert listing["audited_breach_count"] == 0
        assert listing["syndication_posture"] == "SYNDICATING"


class TestSubscriptionRequiresPortalActive:
    def test_subscribe_to_suspended_portal_rejected(self, api):
        """PRD §3.5: "A `MarketingCoordinator` or `MarketingDirector` supplies the
        `portal_account_id`; the target portal must be `ACTIVE`, failing with
        `ERR_PORTAL_NOT_ACTIVE` otherwise"

        Design: Difficulty/cross_entity_state_dependency/subscription_requires_portal_active
        """
        agent, active = create_active_listing()
        portal = create_portal()
        validate_success(api.suspend_portal_account(portal["id"], MD), 200)

        res = api.create_feed_subscription(
            active["id"], {"portal_account_id": portal["id"]}, MC)
        validate_error(res, ApiErrorId.ERR_PORTAL_NOT_ACTIVE, expected_status=409)

        subs = get_success_data(api.list_listing_feed_subscriptions(active["id"], MC), 200)
        assert subs == [], "no subscription may be created against a suspended portal"

    def test_resume_with_suspended_portal_rejected(self, api):
        """PRD §3.5: "Resuming moves `PAUSED` back to `SUBSCRIBED` and demands,
        first, that the listing's `lifecycle_status` is `ACTIVE`, failing with
        `ERR_LISTING_NOT_ACTIVE`, and, second, that the portal is `ACTIVE`, failing
        with `ERR_PORTAL_NOT_ACTIVE`"

        Design: Difficulty/cross_entity_state_dependency/subscription_requires_portal_active
        """
        agent, active, portal, sub = create_syndicated_listing()
        validate_success(api.pause_feed_subscription(sub["id"], MC), 200)
        validate_success(api.suspend_portal_account(portal["id"], MD), 200)

        res = api.resume_feed_subscription(sub["id"], MC)
        validate_error(res, ApiErrorId.ERR_PORTAL_NOT_ACTIVE, expected_status=409)

        sub_after = get_success_data(api.get_feed_subscription(sub["id"], MC), 200)
        assert sub_after["status"] == "PAUSED"


class TestBlackoutBufferedDispatch:
    def _setup_blackout(self, api):
        """Syndicated listing; portal blackout [12:00, 13:00] declared, so the
        buffered dispatch exclusion zone is [11:45, 13:15] inclusive."""
        agent, active, portal, sub = create_syndicated_listing()
        validate_success(api.create_blackout_window(
            portal["id"],
            {"starts_at": "2026-08-01T12:00:00Z", "ends_at": "2026-08-01T13:00:00Z"},
            MD), 201)
        job = find_job(list_jobs_of_subscription(sub["id"]), job_type="FULL_SYNC")
        return agent, active, portal, sub, job

    def test_dispatch_deferred_at_buffered_window_edges(self, api):
        """PRD §3.5: "Dispatch respects a buffered form of the window — fifteen
        minutes are added before the start and after the end, both edges inclusive —
        so a job whose dispatch instant falls anywhere in that buffered interval is
        deferred rather than sent."
        PRD §2.4: "`deferred_job_ids` (the due jobs it held back because a blackout
        window or a suspended portal blocked dispatch)"

        Design: Difficulty/resource_temporal_overlap/blackout_closed_interval_with_buffer
        """
        agent, active, portal, sub, job = self._setup_blackout(api)

        set_clock("2026-08-01T11:45:00Z")
        sweep = run_sweep()
        assert job["id"] in sweep["deferred_job_ids"], "buffer start is inside the closed window"
        assert job["id"] not in sweep["dispatched_job_ids"]

        set_clock("2026-08-01T13:15:00Z")
        sweep = run_sweep()
        assert job["id"] in sweep["deferred_job_ids"], "buffer end is inclusive"

        job_now = find_job(list_jobs_of_subscription(sub["id"]), job_type="FULL_SYNC")
        assert job_now["status"] == "QUEUED"
        assert job_now["attempt_count"] == 0

    def test_dispatch_proceeds_after_buffered_window(self, api):
        """PRD §3.5: "Dispatch respects a buffered form of the window — fifteen
        minutes are added before the start and after the end, both edges inclusive —
        so a job whose dispatch instant falls anywhere in that buffered interval is
        deferred rather than sent."
        PRD §3.6: "Dispatch stamps `dispatched_at` and increments `attempt_count` by
        one."

        Design: Difficulty/resource_temporal_overlap/blackout_closed_interval_with_buffer
        """
        agent, active, portal, sub, job = self._setup_blackout(api)
        set_clock("2026-08-01T13:16:00Z")
        sweep = run_sweep()
        assert job["id"] in sweep["dispatched_job_ids"]

        job_now = find_job(list_jobs_of_subscription(sub["id"]), job_type="FULL_SYNC")
        assert job_now["status"] == "DISPATCHED"
        assert job_now["attempt_count"] == 1
        assert job_now["dispatched_at"].startswith("2026-08-01T13:16:00")


class TestSlaBreachStrictGreaterBoundary:
    def test_ack_exactly_at_sla_is_not_a_breach(self, api):
        """PRD §3.6: "The comparison is strict in both counters: a delay exactly
        equal to `sla_seconds` is not a breach."
        PRD §3.6: "An acknowledgement moves the job to `ACKED`, stamps
        `completed_at`, and computes `propagation_delay_seconds` as the exact number
        of seconds between `dispatched_at` and the acknowledgement instant."

        Design: Difficulty/boundary_precision_check/sla_breach_strict_greater_boundary
        """
        agent, active, portal, sub = create_syndicated_listing(
            portal_overrides={"sla_seconds": 3600})
        run_sweep()  # dispatch at 2026-08-01T00:00:00Z
        set_clock("2026-08-01T01:00:00Z")
        job = find_job(list_jobs_of_subscription(sub["id"]), job_type="FULL_SYNC")

        acked = validate_success(api.ack_feed_event(job["id"], PW), 200)
        assert acked["status"] == "ACKED"
        assert acked["propagation_delay_seconds"] == 3600

        summary = get_summary(active["id"])
        assert summary["audited_breach_count"] == 0, "delay == sla_seconds is not a breach"
        assert summary["provisional_breach_count"] == 0
        assert summary["syndication_posture"] == "SYNDICATED"

    def test_ack_one_second_past_sla_is_a_breach(self, api):
        """PRD §3.6: "The `audited_breach_count` counts terminal evidence only: jobs
        that acknowledged with a `propagation_delay_seconds` strictly greater than
        their portal's `sla_seconds`, plus jobs that died in `DEAD_LETTER`."
        PRD §2.6: "Otherwise, if the listing's `audited_breach_count` is greater than
        zero, or any syndication job of the listing has reached `DEAD_LETTER`, the
        posture is `DEGRADED`."

        Design: Difficulty/boundary_precision_check/sla_breach_strict_greater_boundary
        """
        agent, active, portal, sub = create_syndicated_listing(
            portal_overrides={"sla_seconds": 3600})
        run_sweep()  # dispatch FULL_SYNC at 00:00
        set_clock("2026-08-01T01:00:00Z")
        job1 = find_job(list_jobs_of_subscription(sub["id"]), job_type="FULL_SYNC")
        validate_success(api.ack_feed_event(job1["id"], PW), 200)  # exactly at SLA

        # A remarks update on the ACTIVE listing queues a REMARKS_UPDATE job (PRD §3.1).
        listing = get_listing(active["id"])
        validate_success(api.patch_listing(
            active["id"],
            create_patch_listing_payload(listing["version"],
                                         marketing_remarks="Freshly staged photos"),
            owner_headers(agent)), 200)
        run_sweep()  # dispatch REMARKS_UPDATE at 01:00

        set_clock("2026-08-01T02:00:01Z")
        job2 = find_job(list_jobs_of_subscription(sub["id"]),
                        job_type="REMARKS_UPDATE", status="DISPATCHED")
        acked2 = validate_success(api.ack_feed_event(job2["id"], PW), 200)
        assert acked2["propagation_delay_seconds"] == 3601

        summary = get_summary(active["id"])
        assert summary["audited_breach_count"] == 1, "delay 3601 > 3600 is a breach"
        assert summary["syndication_posture"] == "DEGRADED"


def test_ack_on_queued_job_returns_job_not_dispatched(api):
    """PRD §3.6: "Both require the job to be in `DISPATCHED`; a callback against a
    job in any other status is rejected with `ERR_JOB_NOT_DISPATCHED`."

    Design: Corner/validations/ack_on_queued_job_returns_job_not_dispatched
    """
    agent, active, portal, sub = create_syndicated_listing()
    job = find_job(list_jobs_of_subscription(sub["id"]), job_type="FULL_SYNC")
    assert job["status"] == "QUEUED"

    res = api.ack_feed_event(job["id"], PW)
    validate_error(res, ApiErrorId.ERR_JOB_NOT_DISPATCHED, expected_status=409)

    job_after = find_job(list_jobs_of_subscription(sub["id"]), job_type="FULL_SYNC")
    assert job_after["status"] == "QUEUED"
    assert job_after["attempt_count"] == 0


def test_subscription_pause_resume_cycle_queues_full_sync(api):
    """PRD §3.5: "Pausing moves `SUBSCRIBED` to `PAUSED` and moves the subscription's
    live jobs — those `QUEUED`, `RETRY_QUEUED`, or `DISPATCHED` — to `CANCELLED`."
    PRD §3.5: "a successful resume queues a fresh `FULL_SYNC` job with the display
    price recomputed at that moment."

    Design: Corner/state_machines/subscription_pause_resume_cycle_queues_full_sync
    """
    agent, active, portal, sub = create_syndicated_listing()

    paused = validate_success(api.pause_feed_subscription(sub["id"], MC), 200)
    assert paused["status"] == "PAUSED"
    original = find_job(list_jobs_of_subscription(sub["id"]), job_type="FULL_SYNC")
    assert original["status"] == "CANCELLED"

    resumed = validate_success(api.resume_feed_subscription(sub["id"], MC), 200)
    assert resumed["status"] == "SUBSCRIBED"

    full_syncs = [j for j in list_jobs_of_subscription(sub["id"]) if j["job_type"] == "FULL_SYNC"]
    assert len(full_syncs) == 2, "resume queues a second FULL_SYNC job"
    fresh = [j for j in full_syncs if j["status"] == "QUEUED"]
    assert len(fresh) == 1 and fresh[0]["id"] != original["id"]


def test_duplicate_subscription_returns_subscription_exists(api):
    """PRD §3.5: "there must be no other subscription for the same listing and portal
    already in `SUBSCRIBED` or `PAUSED` — the portal-active check is evaluated before
    this duplicate check, so a suspended portal surfaces `ERR_PORTAL_NOT_ACTIVE` even
    when a subscription already exists, while a live duplicate on an active portal
    fails with `ERR_SUBSCRIPTION_EXISTS`."

    Design: Corner/validations/duplicate_subscription_returns_subscription_exists
    """
    agent, active, portal, sub = create_syndicated_listing()
    res = api.create_feed_subscription(active["id"], {"portal_account_id": portal["id"]}, MC)
    validate_error(res, ApiErrorId.ERR_SUBSCRIPTION_EXISTS, expected_status=409)

    subs = get_success_data(api.list_listing_feed_subscriptions(active["id"], MC), 200)
    assert len(subs) == 1
