"""Publication suspension guards and cascades, wind-down gating, and role
separation on the publication lifecycle."""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_error_is_one_of,
    ApiErrorId,
    TEST_USERS,
    create_publication,
    create_issue,
    create_subscriber,
    create_active_subscription,
    get_subscription,
    drive_issue_to_ad_closed,
    drive_issue_to_finalized,
    setup_publication_with_pending_renewal_events,
    set_clock,
    PD,
    PM,
    CM,
)

PD_H = TEST_USERS["publishing_director_headers"]
PM_H = TEST_USERS["production_manager_headers"]
CM_H = TEST_USERS["circulation_manager_headers"]


class TestSuspendPreconditions:
    def test_suspend_blocked_by_issue_in_ad_closed(self, api):
        """A publication with an issue mid-flight in AD_CLOSED cannot be
        suspended.

        PRD §3.8: "A `PublishingDirector` suspends an `ACTIVE` publication only when no issue is mid-flight — every issue must be `FINALIZED`, or still early in `PLANNING` or `EDITORIAL_CLOSED`; any issue in `AD_CLOSED`, `AT_PRINTER`, or `MAILED` blocks the suspension with `ERR_ISSUE_PIPELINE_ACTIVE`."

        Design: Corner/state_machines/publication_suspend_precondition_blocked_by_issue_in_ad_closed
        """
        set_clock()
        pub = create_publication()
        issue = create_issue(pub["id"])
        drive_issue_to_ad_closed(pub["id"], issue["id"])

        resp = api.suspend_publication(pub["id"], PD_H)
        validate_error(resp, ApiErrorId.ERR_ISSUE_PIPELINE_ACTIVE, 409)

    def test_production_manager_cannot_suspend_publication(self, api):
        """Publication suspension is exclusive to the PublishingDirector.

        PRD §2.1: "Section 4 lists, per endpoint, which roles are authorized; an authenticated operator attempting an operation outside their role is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."
        PRD §2.1: "`PublishingDirector` is the executive role and owns the publication lifecycle, audit pass/fail adjudication, and clock control."

        Design: Corner/rbac/production_manager_cannot_suspend_publication
        """
        set_clock()
        pub = create_publication()
        resp = api.suspend_publication(pub["id"], PM_H)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, 403)


class TestSuspendCascade:
    def test_suspend_cascades_to_active_subscriptions(self, api):
        """Suspending the publication carries every ACTIVE subscription down
        to SUSPENDED with it.

        PRD §3.8: "Suspension cascades: every `ACTIVE` subscription on the publication moves to `SUSPENDED`, and every `PENDING` renewal event on those subscriptions expires."

        Design: Difficulty/transitive_cascade/publication_suspend_cascades_depth3
        """
        ctx = setup_publication_with_pending_renewal_events(num_subs=2)
        pub_id = ctx["publication"]["id"]
        subs = ctx["subscriptions"]

        suspended = validate_success(api.suspend_publication(pub_id, PD_H))
        assert suspended["status"] == "SUSPENDED"

        for sub in subs:
            current = get_subscription(pub_id, sub["id"])
            assert current["status"] == "SUSPENDED", (
                f"subscription {sub['id']} must cascade to SUSPENDED, got {current['status']}"
            )

    def test_suspend_cascades_expire_pending_renewal_events(self, api):
        """The cascade runs one link deeper: the PENDING renewal events
        attached to the cascaded subscriptions lapse to EXPIRED.

        PRD §3.8: "Suspension cascades: every `ACTIVE` subscription on the publication moves to `SUSPENDED`, and every `PENDING` renewal event on those subscriptions expires."

        Design: Difficulty/transitive_cascade/publication_suspend_cascades_depth3
        """
        ctx = setup_publication_with_pending_renewal_events(num_subs=2)
        pub_id = ctx["publication"]["id"]
        subs = ctx["subscriptions"]
        events = ctx["renewal_events"]
        for ev in events:
            assert ev["response"] == "PENDING", "setup: each fired effort starts PENDING"

        validate_success(api.suspend_publication(pub_id, PD_H))

        for sub, ev in zip(subs, events):
            current = validate_success(api.get_renewal_event(pub_id, sub["id"], ev["id"], CM_H))
            assert current["response"] == "EXPIRED", (
                f"renewal event {ev['id']} must expire with the cascade, got {current['response']}"
            )


class TestCeaseWindDown:
    def test_cease_blocked_by_active_subscriptions_and_deferred_revenue(self, api):
        """Ceasing is gated on both subscription terminality and full revenue
        recognition: with an ACTIVE subscription whose term still holds
        deferred balance, the cease is rejected with one of the two gate
        errors. (The publication's only issue is FINALIZED, so the issue-
        pipeline gate passes and cannot interfere.)

        PRD §3.8: "Ceasing a publication is permanent and therefore gated the hardest: all issues must be `FINALIZED` (`ERR_ISSUE_PIPELINE_ACTIVE` otherwise), all subscriptions must already stand in a terminal state — `EXPIRED`, `CANCELLED`, or `RENEWED` — (`ERR_ACTIVE_SUBSCRIPTIONS_REMAIN` otherwise), and every SubscriptionTerm's `deferred_balance_cents` must be zero, since unrecognized liability may not survive the title (`ERR_UNRECOGNIZED_DEFERRED_REVENUE` otherwise)."

        Design: Corner/errors/err_unrecognized_deferred_revenue_blocks_cease
        """
        set_clock()
        pub = create_publication()
        issue = create_issue(pub["id"])
        subscriber = create_subscriber()
        sub = create_active_subscription(pub["id"], subscriber["id"], issue["id"])
        drive_issue_to_finalized(pub["id"], issue["id"])
        # The subscription was served once and remains ACTIVE with 11 issues
        # remaining; its term still holds unrecognized deferred balance.

        resp = api.cease_publication(pub["id"], PD_H)
        assert resp.status_code == 409, f"cease must be rejected with 409, got {resp.status_code}"
        actual = validate_error_is_one_of(
            resp,
            [
                ApiErrorId.ERR_ACTIVE_SUBSCRIPTIONS_REMAIN.value,
                ApiErrorId.ERR_UNRECOGNIZED_DEFERRED_REVENUE.value,
            ],
        )
        assert actual in (
            "ERR_ACTIVE_SUBSCRIPTIONS_REMAIN",
            "ERR_UNRECOGNIZED_DEFERRED_REVENUE",
        )
