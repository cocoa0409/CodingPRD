"""Subscription suspension/resumption cycles and concurrency-guarded renewal."""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    assert_subscription,
    create_publication,
    create_issue,
    create_subscriber,
    create_active_subscription,
    get_subscription,
    setup_subscription_in_grace,
    set_clock,
    CM,
)

CM_H = TEST_USERS["circulation_manager_headers"]


class TestSuspendResumeCycle:
    def test_subscription_suspend_resume_single_cycle(self, api):
        """An ACTIVE subscription survives a suspend/resume round trip: it
        returns to ACTIVE and, with no issue mailed during the suspension,
        issues_suspended_count is unchanged and issues_remaining recomputes to
        the full term.

        PRD §3.6: "Resuming returns the subscription from `SUSPENDED` to `ACTIVE`, again guarded by the publication being `ACTIVE` (`ERR_PUBLICATION_NOT_ACTIVE`) and by the subscriber being deliverable (`ERR_UNDELIVERABLE_ADDRESS`). At resume time the system counts the issues missed during the suspension, increments `issues_suspended_count` by that number, and recomputes `issues_remaining`; missed issues are neither refunded nor credited."
        PRD §3.2: "From these the system derives `issues_remaining` as `term_issues` minus `issues_served` minus `issues_suspended_count`, never below zero."

        Design: Difficulty/non_linear_state_machine/subscription_suspend_resume_cycle
        """
        set_clock()
        pub = create_publication()
        issue = create_issue(pub["id"])
        subscriber = create_subscriber()
        sub = create_active_subscription(pub["id"], subscriber["id"], issue["id"])
        assert sub["status"] == "ACTIVE" and sub["issues_suspended_count"] == 0

        suspended = validate_success(api.suspend_subscription(pub["id"], sub["id"], CM_H))
        assert suspended["status"] == "SUSPENDED"

        resumed = validate_success(api.resume_subscription(pub["id"], sub["id"], CM_H))
        assert resumed["status"] == "ACTIVE"
        assert resumed["issues_suspended_count"] == 0, (
            "no issue was mailed during the suspension, so the missed-issue count stays 0"
        )
        assert resumed["issues_remaining"] == resumed["term_issues"], (
            f"issues_remaining must recompute to the full term, got {resumed['issues_remaining']}"
        )

    def test_subscription_suspend_resume_repeated_cycles(self, api):
        """The ACTIVE ⇄ SUSPENDED cycle is repeatable: two full cycles complete
        without error, each lifecycle action increments version by exactly one,
        and the cumulative suspended count stays zero when no issues mailed
        during either suspension window.

        PRD §3.6: "Between activation and expiry, a subscription may pause. A `CirculationManager` suspends an `ACTIVE` subscription — permitted only while the publication itself is `ACTIVE`, since a suspended publication has already carried its subscriptions down with it."
        PRD §2.5: "`version` (integer): a system-managed integer that increments by exactly one with every modification to the resource. State-transition actions are modifications: every successful lifecycle action on a Publication, Issue, Subscription, MailingBatch, BackIssueOrder, or CirculationAuditRecord refreshes its `updated_at` and increments its `version` by one."

        Design: Difficulty/non_linear_state_machine/subscription_suspend_resume_cycle
        """
        set_clock()
        pub = create_publication()
        issue = create_issue(pub["id"])
        subscriber = create_subscriber()
        sub = create_active_subscription(pub["id"], subscriber["id"], issue["id"])
        v0 = sub["version"]

        s1 = validate_success(api.suspend_subscription(pub["id"], sub["id"], CM_H))
        assert s1["status"] == "SUSPENDED" and s1["version"] == v0 + 1
        r1 = validate_success(api.resume_subscription(pub["id"], sub["id"], CM_H))
        assert r1["status"] == "ACTIVE" and r1["version"] == v0 + 2
        s2 = validate_success(api.suspend_subscription(pub["id"], sub["id"], CM_H))
        assert s2["status"] == "SUSPENDED" and s2["version"] == v0 + 3
        r2 = validate_success(api.resume_subscription(pub["id"], sub["id"], CM_H))
        assert r2["status"] == "ACTIVE" and r2["version"] == v0 + 4

        final = get_subscription(pub["id"], sub["id"])
        assert_subscription(final)
        assert final["status"] == "ACTIVE"
        assert final["issues_suspended_count"] == 0, (
            "no issues mailed during either suspension window, so the cumulative count stays 0"
        )


class TestRenewOptimisticConcurrency:
    def test_renew_with_stale_subscription_version_rejected(self, api):
        """Renewal is one of the three concurrency-guarded writes: submitting
        an expected_subscription_version older than the subscription's current
        version is rejected with ERR_STALE_SUBSCRIPTION_VERSION.

        PRD §2.9: "Renewing a subscription requires the request to carry `expected_subscription_version`, holding the `version` of the Subscription as the client last observed it. If the subscription's current `version` has advanced past what the client observed — because a renewal event or an automatic transition has mutated it in the meantime — the renewal is rejected with `ERR_STALE_SUBSCRIPTION_VERSION` (HTTP 412), preventing the client from overwriting state it has not seen."
        PRD §3.5: "A subscription whose `issues_remaining` reaches zero at mailing arrives at the end of its term. Ordinarily it enters `GRACE`; but when its `auto_renew` flag is true, the grace period is skipped and the subscription moves directly to `RENEWED` through the auto-renew path, with a new SubscriptionTerm created automatically for the next term."

        Design: Corner/errors/err_stale_subscription_version_on_renew_occ_conflict
        """
        ctx = setup_subscription_in_grace()
        pub_id = ctx["publication"]["id"]
        sub = ctx["subscription"]
        assert sub["status"] == "GRACE"

        stale_version = sub["version"] - 1
        resp = api.renew_subscription(
            pub_id,
            sub["id"],
            {
                "expected_subscription_version": stale_version,
                "new_term_issues": 12,
                "new_price_paid_cents": 1200,
            },
            CM_H,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_SUBSCRIPTION_VERSION, 412)
