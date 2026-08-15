"""Issue production pipeline: states, the AD_CLOSED ⇄ EDITORIAL_CLOSED cycle,
validation ordering at close-ads, and print-run computation at ship-to-printer."""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    assert_issue,
    assert_print_run_invariant,
    create_publication,
    create_issue,
    create_subscriber,
    create_active_subscription,
    get_issue,
    close_editorial,
    close_ads_with_occ,
    drive_issue_to_ad_closed,
    drive_issue_to_finalized,
    set_clock,
    PD,
    PM,
    FM,
    PCO,
)

PD_H = TEST_USERS["publishing_director_headers"]
PM_H = TEST_USERS["production_manager_headers"]
FM_H = TEST_USERS["fulfillment_manager_headers"]


class TestIssueStates:
    def test_issue_created_in_planning(self, api):
        """A newly created issue starts in PLANNING.

        PRD §3.1: "An issue is born into `PLANNING` and walks the pipeline `PLANNING → EDITORIAL_CLOSED → AD_CLOSED → AT_PRINTER → MAILED → FINALIZED`, with a single permitted retreat from `AD_CLOSED` back to `EDITORIAL_CLOSED`."

        Design: Corner/state_machines/issue_initial_state_planning
        """
        set_clock()
        pub = create_publication()
        issue = create_issue(pub["id"])
        assert_issue(issue)
        assert issue["status"] == "PLANNING", f"new issue must be PLANNING, got {issue['status']}"

    def test_mark_mailed_from_planning_rejected(self, api):
        """mark-mailed starts from AT_PRINTER only; calling it on a PLANNING
        issue violates lifecycle-state permissibility.

        PRD §2.7: "Fourth, lifecycle-state permissibility — the resource must be in the state the operation starts from (an issue must be `AD_CLOSED` before it can ship to the printer; a subscription must be `ACTIVE` before it can be suspended); violations surface as `ERR_INVALID_STATE` (HTTP 409) unless a more specific state error is defined for the operation."
        PRD §3.5: "Marking an issue mailed — `AT_PRINTER → MAILED`, performed by a `FulfillmentManager` — is the system's pivotal event."

        Design: Corner/state_machines/issue_invalid_transition_from_planning_to_mailed_returns_invalid_state
        """
        set_clock()
        pub = create_publication()
        issue = create_issue(pub["id"])
        assert issue["status"] == "PLANNING"
        resp = api.mark_mailed(pub["id"], issue["id"], FM_H)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)

    def test_finalized_issue_rejects_further_transitions(self, api):
        """FINALIZED is terminal: a lifecycle action on a finalized issue is
        rejected with ERR_INVALID_STATE.

        PRD §3.5: "A finalized issue is locked against any further state change and is terminal."
        PRD §2.7: "Fourth, lifecycle-state permissibility — the resource must be in the state the operation starts from (an issue must be `AD_CLOSED` before it can ship to the printer; a subscription must be `ACTIVE` before it can be suspended); violations surface as `ERR_INVALID_STATE` (HTTP 409) unless a more specific state error is defined for the operation."

        Design: Corner/state_machines/issue_terminal_lockdown_no_transitions_from_finalized
        """
        set_clock()
        pub = create_publication()
        issue = create_issue(pub["id"])
        finalized = drive_issue_to_finalized(pub["id"], issue["id"])
        assert finalized["status"] == "FINALIZED"

        resp = api.close_editorial(pub["id"], issue["id"], PM_H)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)


class TestAdCloseReopenCycle:
    def test_reopen_ads_returns_issue_to_editorial_closed(self, api):
        """The AD_CLOSED → EDITORIAL_CLOSED retreat restores the issue and
        increments its version by exactly one.

        PRD §3.3: "Should advertising need to reopen — a late insertion order, a correction — a `ProductionManager` may revert the issue from `AD_CLOSED` back to `EDITORIAL_CLOSED`, which unfreezes `ad_pages_sold`."
        PRD §2.5: "`version` (integer): a system-managed integer that increments by exactly one with every modification to the resource. State-transition actions are modifications: every successful lifecycle action on a Publication, Issue, Subscription, MailingBatch, BackIssueOrder, or CirculationAuditRecord refreshes its `updated_at` and increments its `version` by one."

        Design: Difficulty/non_linear_state_machine/issue_ad_close_reopen_cycle
        """
        set_clock()
        pub = create_publication()
        issue = create_issue(pub["id"])
        closed = drive_issue_to_ad_closed(pub["id"], issue["id"])
        assert closed["status"] == "AD_CLOSED"
        v_closed = closed["version"]

        reopened = validate_success(api.reopen_ads(pub["id"], issue["id"], PM_H))
        assert_issue(reopened)
        assert reopened["status"] == "EDITORIAL_CLOSED", (
            f"reopen-ads must return the issue to EDITORIAL_CLOSED, got {reopened['status']}"
        )
        assert reopened["version"] == v_closed + 1, (
            f"reopen must increment version by exactly one: {v_closed} -> {reopened['version']}"
        )

    def test_ad_close_reopen_cycle_is_repeatable(self, api):
        """The EDITORIAL_CLOSED → AD_CLOSED → EDITORIAL_CLOSED cycle runs more
        than once: after a reopen, close-ads (a concurrency-guarded write
        carrying the freshly observed version) succeeds again.

        PRD §3.3: "Should advertising need to reopen — a late insertion order, a correction — a `ProductionManager` may revert the issue from `AD_CLOSED` back to `EDITORIAL_CLOSED`, which unfreezes `ad_pages_sold`."
        PRD §3.3: "Closing advertising moves the issue from `EDITORIAL_CLOSED` to `AD_CLOSED` and is one of the three concurrency-guarded writes: the request must carry `expected_issue_version`, and a stale value is rejected with `ERR_STALE_ISSUE_VERSION` as §2.9 describes."

        Design: Difficulty/non_linear_state_machine/issue_ad_close_reopen_cycle
        """
        set_clock()
        pub = create_publication()
        issue = create_issue(pub["id"])
        closed = drive_issue_to_ad_closed(pub["id"], issue["id"])
        v1 = closed["version"]

        reopened = validate_success(api.reopen_ads(pub["id"], issue["id"], PM_H))
        assert reopened["version"] == v1 + 1

        # Second pass through the cycle, threading the current version.
        reclosed = close_ads_with_occ(pub["id"], issue["id"])
        assert reclosed["status"] == "AD_CLOSED"
        assert reclosed["version"] == v1 + 2

        reopened_again = validate_success(api.reopen_ads(pub["id"], issue["id"], PM_H))
        assert reopened_again["status"] == "EDITORIAL_CLOSED"
        assert reopened_again["version"] == v1 + 3


class TestCloseAdsValidationOrdering:
    def test_close_ads_wrong_state_beats_temporal_rejection(self, api):
        """With an issue in PLANNING (wrong state) AND the ad-close deadline
        still in the future (temporal rule unmet), the lifecycle-state check is
        evaluated fourth and the deadline check sixth, so the response is
        ERR_INVALID_STATE, not ERR_AD_CLOSE_NOT_REACHED.

        PRD §2.7: "Fourth, lifecycle-state permissibility — the resource must be in the state the operation starts from (an issue must be `AD_CLOSED` before it can ship to the printer; a subscription must be `ACTIVE` before it can be suspended); violations surface as `ERR_INVALID_STATE` (HTTP 409) unless a more specific state error is defined for the operation. Fifth, on the three concurrency-guarded writes, the expected-version match described in §2.9. Sixth, date-driven deadline preconditions evaluated against the logical clock."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_temporal_on_close_ads
        """
        set_clock()  # 2026-08-01; the issue's ad_close_date below is later.
        pub = create_publication()
        issue = create_issue(
            pub["id"],
            cover_date="2026-12-01T00:00:00Z",
            editorial_close_date="2026-11-01T00:00:00Z",
            ad_close_date="2026-11-05T00:00:00Z",
            ship_to_printer_date="2026-11-10T00:00:00Z",
            mail_date="2026-12-01T00:00:00Z",
        )
        assert issue["status"] == "PLANNING"
        resp = api.close_ads(
            pub["id"], issue["id"], {"expected_issue_version": issue["version"]}, PM_H
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)

    def test_close_ads_before_ad_close_date_rejected(self, api):
        """With the state precondition satisfied (EDITORIAL_CLOSED) but the
        ad_close_date still ahead of the logical clock, the temporal check
        reports ERR_AD_CLOSE_NOT_REACHED.

        PRD §3.3: "The close is allowed only once the logical clock has reached the `ad_close_date` — earlier attempts fail with `ERR_AD_CLOSE_NOT_REACHED` — and only when the issue has advertising content: `ad_pages_sold` must be greater than zero, except on a `CONTROLLED` publication, which may close with zero ads."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_temporal_on_close_ads
        """
        set_clock()  # 2026-08-01; editorial close is past, ad close is future.
        pub = create_publication()
        issue = create_issue(
            pub["id"],
            cover_date="2026-12-01T00:00:00Z",
            editorial_close_date="2026-07-01T00:00:00Z",
            ad_close_date="2026-11-05T00:00:00Z",
            ship_to_printer_date="2026-11-10T00:00:00Z",
            mail_date="2026-12-01T00:00:00Z",
        )
        closed_editorial = close_editorial(pub["id"], issue["id"])
        assert closed_editorial["status"] == "EDITORIAL_CLOSED"

        resp = api.close_ads(
            pub["id"],
            issue["id"],
            {"expected_issue_version": closed_editorial["version"]},
            PM_H,
        )
        validate_error(resp, ApiErrorId.ERR_AD_CLOSE_NOT_REACHED, 409)


class TestPrintRunInvariant:
    def _setup_three_qualified_subs(self):
        set_clock()
        pub = create_publication()
        issue_start = create_issue(pub["id"], issue_number=1)
        subs = []
        for _ in range(3):
            subscriber = create_subscriber()
            subs.append(create_active_subscription(pub["id"], subscriber["id"], issue_start["id"]))
        return pub, subs

    def test_print_run_equals_qualified_plus_newsstand_buffer(self, api):
        """With no override, ship-to-printer fixes print_run at the qualified
        subscriber count plus the newsstand buffer: 3 qualified subscriptions
        and a buffer of 10 produce a print run of exactly 13.

        PRD §3.3: "The system computes `qualified_subscriber_count` as the number of subscriptions on the publication that are `ACTIVE`, belong to a deliverable subscriber, started no later than this issue in the publication's sequence, and still have issues remaining. The final `print_run` is then either the `print_run_override`, when one was set — an override smaller than the qualified count is rejected with `ERR_PRINT_RUN_TOO_SMALL` — or, with no override, the `qualified_subscriber_count` plus the issue's `newsstand_buffer_copies`."

        Design: Difficulty/compensating_invariant/print_run_equals_qualified_plus_newsstand_buffer
        """
        pub, subs = self._setup_three_qualified_subs()
        issue = create_issue(pub["id"], issue_number=2, newsstand_buffer_copies=10)
        drive_issue_to_ad_closed(pub["id"], issue["id"])

        shipped = validate_success(api.ship_to_printer(pub["id"], issue["id"], PM_H))
        assert_issue(shipped)
        assert shipped["status"] == "AT_PRINTER"
        assert shipped["qualified_subscriber_count"] == 3, (
            f"3 ACTIVE deliverable subscriptions with issues remaining must qualify, "
            f"got {shipped['qualified_subscriber_count']}"
        )
        assert shipped["newsstand_buffer_copies"] == 10
        assert shipped["print_run"] == 13, (
            f"print_run must be 3 + 10 = 13, got {shipped['print_run']}"
        )
        assert_print_run_invariant(shipped)

    def test_print_run_override_below_qualified_count_rejected(self, api):
        """An override smaller than the qualified subscriber count is rejected
        at ship-to-printer with ERR_PRINT_RUN_TOO_SMALL.

        PRD §3.3: "The system computes `qualified_subscriber_count` as the number of subscriptions on the publication that are `ACTIVE`, belong to a deliverable subscriber, started no later than this issue in the publication's sequence, and still have issues remaining. The final `print_run` is then either the `print_run_override`, when one was set — an override smaller than the qualified count is rejected with `ERR_PRINT_RUN_TOO_SMALL` — or, with no override, the `qualified_subscriber_count` plus the issue's `newsstand_buffer_copies`."

        Design: Difficulty/compensating_invariant/print_run_equals_qualified_plus_newsstand_buffer
        """
        pub, subs = self._setup_three_qualified_subs()
        issue = create_issue(pub["id"], issue_number=2, print_run_override=2)
        drive_issue_to_ad_closed(pub["id"], issue["id"])

        resp = api.ship_to_printer(pub["id"], issue["id"], PM_H)
        validate_error(resp, ApiErrorId.ERR_PRINT_RUN_TOO_SMALL, 422)

        after = get_issue(pub["id"], issue["id"])
        assert after["status"] == "AD_CLOSED", (
            "a rejected ship-to-printer must not move the issue out of AD_CLOSED"
        )

    def test_print_run_override_equal_to_qualified_count_accepted(self, api):
        """The override floor is inclusive: an override exactly equal to the
        qualified subscriber count is accepted and pins the print run.

        PRD §3.3: "The system computes `qualified_subscriber_count` as the number of subscriptions on the publication that are `ACTIVE`, belong to a deliverable subscriber, started no later than this issue in the publication's sequence, and still have issues remaining. The final `print_run` is then either the `print_run_override`, when one was set — an override smaller than the qualified count is rejected with `ERR_PRINT_RUN_TOO_SMALL` — or, with no override, the `qualified_subscriber_count` plus the issue's `newsstand_buffer_copies`."

        Design: Difficulty/compensating_invariant/print_run_equals_qualified_plus_newsstand_buffer
        """
        pub, subs = self._setup_three_qualified_subs()
        issue = create_issue(pub["id"], issue_number=2, print_run_override=3)
        drive_issue_to_ad_closed(pub["id"], issue["id"])

        shipped = validate_success(api.ship_to_printer(pub["id"], issue["id"], PM_H))
        assert shipped["status"] == "AT_PRINTER"
        assert shipped["qualified_subscriber_count"] == 3
        assert shipped["print_run"] == 3, (
            f"an override equal to the qualified count pins print_run to 3, got {shipped['print_run']}"
        )
