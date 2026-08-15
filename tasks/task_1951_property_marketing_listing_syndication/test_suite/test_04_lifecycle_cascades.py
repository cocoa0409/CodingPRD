"""Listing lifecycle cascades: withdrawal cascade depth, price-change job
regeneration with posture flip, SOLD terminal lockdown, and the
UNDER_CONTRACT fall-through cycle (PRD §3.4, §3.7)."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    create_price_change_payload,
    create_active_listing, create_syndicated_listing, owner_headers,
    get_listing, get_summary, list_jobs_of_subscription, find_job,
    set_clock, run_sweep,
    TEST_USERS,
    ApiErrorId,
)

MC = TEST_USERS["marketing_coordinator_headers"]
PW = TEST_USERS["portal_webhook_headers"]


class TestWithdrawCascade:
    def test_withdraw_pauses_subscriptions_and_cancels_live_jobs(self, api):
        """PRD §3.4: "Both paths stamp `terminal_entered_at` with the current instant
        and freeze `terminal_price_cents` at the listing's then-current
        `list_price_cents`, and both run the same cascade as a closing: subscriptions
        paused to `PAUSED`, live jobs moved to `CANCELLED` with one `TERMINAL_SYNC`
        queued per paused subscription, scheduled showing windows moved to
        `CANCELLED`, posture recomputed to `SUSPENDED`, the `STATUS_CHANGE` event
        appended, and `version` incremented."

        Design: Difficulty/transitive_cascade/withdraw_cascade_subscription_pause_job_cancel_posture
        """
        agent, active, portal, sub = create_syndicated_listing()
        # A price change leaves a second live job (QUEUED PRICE_UPDATE) on the sub.
        validate_success(api.create_price_change(
            active["id"],
            create_price_change_payload(49900000, active["version"]),
            owner_headers(agent)), 201)

        withdrawn = validate_success(api.withdraw_listing(active["id"], owner_headers(agent)), 200)
        assert withdrawn["lifecycle_status"] == "WITHDRAWN"
        # terminal price freezes at the then-current price (after the change to 49900000).
        assert withdrawn["terminal_price_cents"] == 49900000
        assert withdrawn["terminal_entered_at"] is not None

        sub_after = get_success_data(api.get_feed_subscription(sub["id"], MC), 200)
        assert sub_after["status"] == "PAUSED"

        jobs = list_jobs_of_subscription(sub["id"])
        full_sync = find_job(jobs, job_type="FULL_SYNC")
        price_update = find_job(jobs, job_type="PRICE_UPDATE")
        assert full_sync["status"] == "CANCELLED"
        assert price_update["status"] == "CANCELLED"
        terminal_syncs = [j for j in jobs if j["job_type"] == "TERMINAL_SYNC"]
        assert len(terminal_syncs) == 1, "exactly one TERMINAL_SYNC queued per paused subscription"
        assert terminal_syncs[0]["status"] == "QUEUED"

    def test_withdraw_recomputes_posture_to_suspended(self, api):
        """PRD §2.6: "If the listing's `lifecycle_status` is `COMPLIANCE_HOLD`,
        `WITHDRAWN`, `EXPIRED`, or `SOLD`, the posture is `SUSPENDED`. This lifecycle
        override wins over every other rule."
        PRD §3.4: "Withdrawal moves an `ACTIVE` listing to `WITHDRAWN`"

        Design: Difficulty/transitive_cascade/withdraw_cascade_subscription_pause_job_cancel_posture
        """
        agent, active, portal, sub = create_syndicated_listing()
        before = get_summary(active["id"])
        assert before["syndication_posture"] == "SYNDICATING", (
            "a live QUEUED FULL_SYNC job keeps the posture SYNDICATING before withdrawal"
        )

        validate_success(api.withdraw_listing(active["id"], owner_headers(agent)), 200)

        after = get_summary(active["id"])
        assert after["lifecycle_status"] == "WITHDRAWN"
        assert after["syndication_posture"] == "SUSPENDED"


class TestPriceChangeJobRegeneration:
    def _setup_acked_syndicated_listing(self, api):
        """ACTIVE listing whose FULL_SYNC was dispatched at the default clock and
        acked at 00:30 (delay 1800s, within the 3600s SLA): posture SYNDICATED."""
        agent, active, portal, sub = create_syndicated_listing()
        run_sweep()
        set_clock("2026-08-01T00:30:00Z")
        job = find_job(list_jobs_of_subscription(sub["id"]),
                       job_type="FULL_SYNC", status="DISPATCHED")
        validate_success(api.ack_feed_event(job["id"], PW), 200)
        return agent, active, portal, sub, job

    def test_price_change_updates_price_and_appends_event(self, api):
        """PRD §3.7: "An accepted price change updates `list_price_cents`, appends a
        `PRICE_CHANGE` event capturing `old_price_cents` and `new_price_cents`,
        increments the listing's `version`, supersedes any still-`QUEUED`
        `PRICE_UPDATE` job of each `SUBSCRIBED` subscription and queues a fresh
        `PRICE_UPDATE` job per such subscription — each snapshotting the new portal
        display price — and recomputes the posture."

        Design: Difficulty/transitive_cascade/price_change_event_job_regen_posture_flip
        """
        agent, active, portal, sub, _ = self._setup_acked_syndicated_listing(api)
        old_version = active["version"]

        event = validate_success(api.create_price_change(
            active["id"],
            create_price_change_payload(49900000, old_version),
            owner_headers(agent)), 201)
        assert event["event_type"] == "PRICE_CHANGE"
        assert event["old_price_cents"] == 50000000
        assert event["new_price_cents"] == 49900000

        listing = get_listing(active["id"])
        assert listing["list_price_cents"] == 49900000
        assert listing["version"] == old_version + 1

    def test_price_change_flips_posture_back_to_syndicating(self, api):
        """PRD §2.6: "Otherwise, if at least one feed subscription of the listing is
        `SUBSCRIBED`, the posture is `SYNDICATED`."
        PRD §2.6: "Otherwise, if at least one job of the listing is live — in
        `QUEUED`, `RETRY_QUEUED`, or `DISPATCHED` — the posture is `SYNDICATING`."
        PRD §3.7: "An accepted price change updates `list_price_cents`, appends a
        `PRICE_CHANGE` event capturing `old_price_cents` and `new_price_cents`,
        increments the listing's `version`, supersedes any still-`QUEUED`
        `PRICE_UPDATE` job of each `SUBSCRIBED` subscription and queues a fresh
        `PRICE_UPDATE` job per such subscription — each snapshotting the new portal
        display price — and recomputes the posture."

        Design: Difficulty/transitive_cascade/price_change_event_job_regen_posture_flip
        """
        agent, active, portal, sub, full_sync = self._setup_acked_syndicated_listing(api)
        before = get_summary(active["id"])
        assert before["syndication_posture"] == "SYNDICATED", (
            "acked-clean job and one SUBSCRIBED subscription yield SYNDICATED"
        )

        validate_success(api.create_price_change(
            active["id"],
            create_price_change_payload(49900000, active["version"]),
            owner_headers(agent)), 201)

        jobs = list_jobs_of_subscription(sub["id"])
        price_update = find_job(jobs, job_type="PRICE_UPDATE", status="QUEUED")
        # Portal defaults: discount 0, increment 100000 -> 49900000 snapshots as-is.
        assert price_update["payload_display_price_cents"] == 49900000

        full_sync_after = find_job(jobs, job_type="FULL_SYNC")
        assert full_sync_after["id"] == full_sync["id"]
        assert full_sync_after["status"] == "ACKED"
        assert full_sync_after["propagation_delay_seconds"] == 1800

        after = get_summary(active["id"])
        assert after["syndication_posture"] == "SYNDICATING", (
            "the fresh QUEUED PRICE_UPDATE flips the posture back to SYNDICATING"
        )


def test_sold_terminal_lockdown_withdraw_rejected(api):
    """PRD §3.4: "Closing the sale moves the listing from `UNDER_CONTRACT` to `SOLD`,
    the terminal lifecycle state"
    PRD §2.9: "Lifecycle and entity state — the current state permits the operation,
    else `ERR_INVALID_STATE`"

    Design: Corner/state_machines/sold_terminal_lockdown_withdraw_rejected
    """
    agent, active = create_active_listing()
    validate_success(api.mark_under_contract(active["id"], owner_headers(agent)), 200)
    sold = validate_success(api.close_sold(active["id"], owner_headers(agent)), 200)
    assert sold["lifecycle_status"] == "SOLD"

    res = api.withdraw_listing(active["id"], owner_headers(agent))
    validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

    after = get_listing(active["id"])
    assert after["lifecycle_status"] == "SOLD"
    assert after.get("terminal_entered_at") is None, (
        "terminal anchors are stamped by withdrawal/expiry, not by closing a sale"
    )


def test_reactivate_under_contract_cycle_with_status_jobs(api):
    """PRD §3.4: "Once `ACTIVE`, a listing under offer moves to `UNDER_CONTRACT` when
    the agent or coordinator marks it under contract; if the deal falls through,
    reactivation returns it from `UNDER_CONTRACT` to `ACTIVE`. Both transitions
    append a `STATUS_CHANGE` event, increment `version`, and queue a `STATUS_UPDATE`
    syndication job for every feed subscription in `SUBSCRIBED`."
    PRD §3.6: "Creating a newer job of the same `job_type` for the same subscription
    supersedes any still-`QUEUED` job of that type, moving it to `SUPERSEDED` and
    stamping its `completed_at`."

    Design: Corner/state_machines/reactivate_under_contract_cycle_with_status_jobs
    """
    agent, active, portal, sub = create_syndicated_listing()
    validate_success(api.mark_under_contract(active["id"], owner_headers(agent)), 200)
    reactivated = validate_success(api.reactivate_listing(active["id"], owner_headers(agent)), 200)
    assert reactivated["lifecycle_status"] == "ACTIVE"

    jobs = list_jobs_of_subscription(sub["id"])
    status_updates = [j for j in jobs if j["job_type"] == "STATUS_UPDATE"]
    assert len(status_updates) == 2, "one STATUS_UPDATE job per transition"
    by_created = sorted(status_updates, key=lambda j: j["created_at"])
    assert by_created[0]["status"] == "SUPERSEDED", (
        "the first transition's still-QUEUED STATUS_UPDATE is superseded by the second"
    )
    assert by_created[0]["completed_at"] is not None
    assert by_created[1]["status"] == "QUEUED", (
        "the newest STATUS_UPDATE remains QUEUED"
    )
