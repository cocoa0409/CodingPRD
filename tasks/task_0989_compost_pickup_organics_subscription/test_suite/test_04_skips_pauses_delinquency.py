"""Skip cutoff and allowance, lazy quarter reset, pause-window side effects,
and the cross-entity fiscal gates (delinquency, subscription state).

Covers PRD §2.4 (logical clock), §2.10 (validation order), §3.5 (skips,
pauses, resumes), §3.9 (account standing).
"""
from test_helpers import (
    ApiErrorId,
    generate_and_get_pickups,
    get_pickup,
    get_subscription,
    miss_pickup,
    pause_subscription,
    set_clock,
    setup_active_subscription,
    setup_delinquent_subscriber,
    setup_issued_invoice,
    skip_pickup,
    validate_error,
    validate_success,
)


class TestSkipCutoffBoundary:
    def test_skip_exactly_at_cutoff_rejected(self, api):
        """PRD §3.5: "The cutoff: a skip is accepted only while the logical
        clock reads strictly earlier than forty-eight hours before 00:00 UTC on
        the service date — a skip attempted exactly at that cutoff instant, or
        later, is rejected with `ERR_SKIP_CUTOFF_PASSED`."

        Design: Difficulty/boundary_precision_check/skip_cutoff_exactly_at_48h_rejected
        """
        env = setup_active_subscription(bin_count=1)
        pickup = generate_and_get_pickups(
            env["route"]["id"], env["subscription"]["id"], ["2026-06-15"]
        )[0]
        # 2026-06-13T00:00:00Z is exactly service_date 00:00Z minus 48h.
        set_clock("2026-06-13T00:00:00Z")
        resp = api.skip_pickup(
            pickup["id"], _own(env)
        )
        validate_error(resp, ApiErrorId.ERR_SKIP_CUTOFF_PASSED)
        assert get_pickup(pickup["id"])["status"] == "SCHEDULED"

    def test_skip_one_minute_before_cutoff_succeeds(self, api):
        """PRD §3.5: "a skip is accepted only while the logical clock reads
        strictly earlier than forty-eight hours before 00:00 UTC on the service
        date". PRD §3.5: "A successful skip moves the pickup to `SKIPPED`,
        increments `skips_used_this_quarter` by one, and increments the
        pickup's `version`."

        Design: Difficulty/boundary_precision_check/skip_cutoff_exactly_at_48h_rejected
        """
        env = setup_active_subscription(bin_count=1)
        pickup = generate_and_get_pickups(
            env["route"]["id"], env["subscription"]["id"], ["2026-06-15"]
        )[0]
        # One minute inside the window.
        set_clock("2026-06-12T23:59:00Z")
        data = validate_success(api.skip_pickup(pickup["id"], _own(env)))
        assert data["status"] == "SKIPPED"
        sub = get_subscription(env["subscription"]["id"])
        assert sub["skips_used_this_quarter"] == 1


class TestSkipAllowance:
    def test_third_skip_in_quarter_rejected(self, api):
        """PRD §3.5: "A skip is allowed only while `skips_used_this_quarter` is
        strictly below the plan's `skip_allowance_per_quarter`; a subscription
        that has consumed exactly its allowance is rejected with
        `ERR_SKIP_LIMIT_EXCEEDED`."

        Design: Corner/validations/third_skip_in_quarter_returns_limit_exceeded
        """
        env = setup_active_subscription(bin_count=1)
        sub_id = env["subscription"]["id"]
        pickups = generate_and_get_pickups(
            env["route"]["id"], sub_id, ["2026-06-01", "2026-06-08", "2026-06-15"]
        )
        skip_pickup(pickups[0]["id"], env["subscriber"]["id"])
        skip_pickup(pickups[1]["id"], env["subscriber"]["id"])
        resp = api.skip_pickup(pickups[2]["id"], _own(env))
        validate_error(resp, ApiErrorId.ERR_SKIP_LIMIT_EXCEEDED)
        assert get_pickup(pickups[2]["id"])["status"] == "SCHEDULED"

    def test_quarter_boundary_lazily_resets_allowance(self, api):
        """PRD §3.5: "The allowance accounting is lazy — whenever the
        subscription's `current_quarter` differs from the quarter of the
        logical today, `skips_used_this_quarter` is reset to zero and
        `current_quarter` is stamped with today's quarter label."
        PRD §3.5: "calendar quarters run Q1 from January through March, Q2 from
        April through June, Q3 from July through September, and Q4 from October
        through December, labeled as year-and-quarter strings such as
        `2026-Q2`."

        Design: Corner/calculations/quarterly_skip_counter_resets_at_quarter_boundary
        """
        env = setup_active_subscription(bin_count=1)
        sub_id = env["subscription"]["id"]
        pickups = generate_and_get_pickups(
            env["route"]["id"], sub_id,
            ["2026-06-01", "2026-06-08", "2026-06-15", "2026-07-06"],
        )
        skip_pickup(pickups[0]["id"], env["subscriber"]["id"])
        skip_pickup(pickups[1]["id"], env["subscriber"]["id"])
        resp = api.skip_pickup(pickups[2]["id"], _own(env))
        validate_error(resp, ApiErrorId.ERR_SKIP_LIMIT_EXCEEDED)

        # Moving the logical clock into Q3 re-opens the allowance lazily.
        set_clock("2026-07-01T00:00:00Z")
        data = validate_success(api.skip_pickup(pickups[3]["id"], _own(env)))
        assert data["status"] == "SKIPPED"
        sub = get_subscription(sub_id)
        assert sub["skips_used_this_quarter"] == 1
        assert sub["current_quarter"] == "2026-Q3"


class TestSkipCrossEntityGates:
    def test_skip_on_paused_subscription_rejected(self, api):
        """PRD §3.5: "The pickup must still be `SCHEDULED`, otherwise
        `ERR_PICKUP_NOT_ACTIONABLE`, and the subscription must be `ACTIVE`,
        otherwise `ERR_SUBSCRIPTION_NOT_ACTIVE`."

        Design: Difficulty/cross_entity_state_dependency/pickup_skip_requires_subscription_active
        """
        env = setup_active_subscription(bin_count=1)
        sub_id = env["subscription"]["id"]
        pickup = generate_and_get_pickups(
            env["route"]["id"], sub_id, ["2026-06-01"]
        )[0]
        # The pause window does not cover 2026-06-01, so the pickup stays
        # SCHEDULED while the subscription is PAUSED.
        pause_subscription(sub_id, "2026-07-06", "2026-07-13")
        resp = api.skip_pickup(pickup["id"], _own(env))
        validate_error(resp, ApiErrorId.ERR_SUBSCRIPTION_NOT_ACTIVE)

    def test_rejected_skip_leaves_pickup_and_allowance_untouched(self, api):
        """PRD §3.5: "the subscription must be `ACTIVE`, otherwise
        `ERR_SUBSCRIPTION_NOT_ACTIVE`." PRD §3.5: "A successful skip moves the
        pickup to `SKIPPED`, increments `skips_used_this_quarter` by one" — a
        rejected skip performs neither mutation.

        Design: Difficulty/cross_entity_state_dependency/pickup_skip_requires_subscription_active
        """
        env = setup_active_subscription(bin_count=1)
        sub_id = env["subscription"]["id"]
        pickup = generate_and_get_pickups(
            env["route"]["id"], sub_id, ["2026-06-01"]
        )[0]
        pause_subscription(sub_id, "2026-07-06", "2026-07-13")
        resp = api.skip_pickup(pickup["id"], _own(env))
        validate_error(resp, ApiErrorId.ERR_SUBSCRIPTION_NOT_ACTIVE)
        assert get_pickup(pickup["id"])["status"] == "SCHEDULED"
        assert get_subscription(sub_id)["skips_used_this_quarter"] == 0


class TestSkipPriorityPair:
    def test_skip_missed_pickup_reports_state_error_not_fiscal(self, api):
        """PRD §2.10: "When several checks apply to one request, the server
        evaluates them in a fixed order, so an earlier failure masks every
        later one." State gates are sixth: "Sixth, state gates: the target
        resource must be in a valid from-state for the operation, otherwise the
        operation-specific conflict — `ERR_SUBSCRIPTION_STATE_CONFLICT`,
        `ERR_SUBSCRIPTION_NOT_ACTIVE`, `ERR_PICKUP_NOT_ACTIONABLE`,
        `ERR_TAG_NOT_RESOLVABLE`, `ERR_REDEMPTION_NOT_FULFILLABLE`,
        `ERR_INVOICE_NOT_PAYABLE`, or `ERR_INVALID_STATE`." Fiscal gates are
        eighth: "Eighth, fiscal gates — account delinquency, credit
        sufficiency, and the quarterly skip allowance — otherwise
        `ERR_ACCOUNT_DELINQUENT`, `ERR_INSUFFICIENT_CREDIT`, or
        `ERR_SKIP_LIMIT_EXCEEDED`; this tier guards pause, resume, redemption
        creation and fulfillment, credit adjustments, and pickup skips."

        Design: Difficulty/priority_pair_validation_conflict/skip_terminal_pickup_with_exhausted_allowance_state_beats_fiscal
        """
        env = setup_active_subscription(bin_count=1)
        sub_id = env["subscription"]["id"]
        pickups = generate_and_get_pickups(
            env["route"]["id"], sub_id, ["2026-06-01", "2026-06-08", "2026-06-15"]
        )
        # Exhaust the Q2 allowance (2/2), then make P3 terminal via MISSED.
        skip_pickup(pickups[0]["id"], env["subscriber"]["id"])
        skip_pickup(pickups[1]["id"], env["subscriber"]["id"])
        miss_pickup(pickups[2]["id"])
        resp = api.skip_pickup(pickups[2]["id"], _own(env))
        validate_error(resp, ApiErrorId.ERR_PICKUP_NOT_ACTIONABLE)

    def test_failed_skip_does_not_consume_allowance(self, api):
        """PRD §2.10: "an earlier failure masks every later one." PRD §3.5:
        "A successful skip moves the pickup to `SKIPPED`, increments
        `skips_used_this_quarter` by one" — the failed skip increments nothing.

        Design: Difficulty/priority_pair_validation_conflict/skip_terminal_pickup_with_exhausted_allowance_state_beats_fiscal
        """
        env = setup_active_subscription(bin_count=1)
        sub_id = env["subscription"]["id"]
        pickups = generate_and_get_pickups(
            env["route"]["id"], sub_id, ["2026-06-01", "2026-06-08", "2026-06-15"]
        )
        skip_pickup(pickups[0]["id"], env["subscriber"]["id"])
        skip_pickup(pickups[1]["id"], env["subscriber"]["id"])
        miss_pickup(pickups[2]["id"])
        api.skip_pickup(pickups[2]["id"], _own(env))
        assert get_subscription(sub_id)["skips_used_this_quarter"] == 2


class TestResumeGates:
    def test_resume_from_active_returns_state_conflict(self, api, ops_headers):
        """PRD §3.5: "Resuming reverses the status half: from `PAUSED` —
        otherwise `ERR_SUBSCRIPTION_STATE_CONFLICT` — and only while the
        subscriber is in `GOOD_STANDING`, otherwise `ERR_ACCOUNT_DELINQUENT`;
        resuming returns the subscription to `ACTIVE` and increments its
        `version`."

        Design: Corner/state_machines/resume_from_active_returns_state_conflict
        """
        env = setup_active_subscription(bin_count=1)
        resp = api.resume_subscription(env["subscription"]["id"], ops_headers)
        validate_error(resp, ApiErrorId.ERR_SUBSCRIPTION_STATE_CONFLICT)

    def test_resume_while_delinquent_rejected(self, api, ops_headers):
        """PRD §3.5: "Resuming reverses the status half: from `PAUSED` —
        otherwise `ERR_SUBSCRIPTION_STATE_CONFLICT` — and only while the
        subscriber is in `GOOD_STANDING`, otherwise `ERR_ACCOUNT_DELINQUENT`;
        resuming returns the subscription to `ACTIVE` and increments its
        `version`."
        PRD §3.9: "Delinquency is the fiscal brake of §2.10: it blocks pausing
        and resuming a subscription and opening a redemption request, each
        rejected with `ERR_ACCOUNT_DELINQUENT`, until the overdue invoice is
        paid or voided."

        Design: Difficulty/cross_entity_state_dependency/subscription_resume_requires_good_standing
        """
        env = setup_issued_invoice(week_start="2026-05-04")
        sub_id = env["subscription"]["id"]
        # Pause while still in good standing (invoice due 2026-05-18).
        pause_subscription(sub_id, "2026-06-01", "2026-06-08")
        set_clock("2026-05-20T00:00:00Z")
        resp = api.resume_subscription(sub_id, ops_headers)
        validate_error(resp, ApiErrorId.ERR_ACCOUNT_DELINQUENT)

    def test_rejected_resume_keeps_paused_state(self, api, ops_headers):
        """PRD §3.5: "Resuming reverses the status half: from `PAUSED` —
        otherwise `ERR_SUBSCRIPTION_STATE_CONFLICT` — and only while the
        subscriber is in `GOOD_STANDING`, otherwise `ERR_ACCOUNT_DELINQUENT`;
        resuming returns the subscription to `ACTIVE` and increments its
        `version`." The rejected resume performs no transition.

        Design: Difficulty/cross_entity_state_dependency/subscription_resume_requires_good_standing
        """
        env = setup_issued_invoice(week_start="2026-05-04")
        sub_id = env["subscription"]["id"]
        pause_subscription(sub_id, "2026-06-01", "2026-06-08")
        set_clock("2026-05-20T00:00:00Z")
        api.resume_subscription(sub_id, ops_headers)
        assert get_subscription(sub_id)["service_status"] == "PAUSED"


class TestPausePriorityPair:
    def test_pause_while_delinquent_reports_fiscal_not_temporal(self, api, ops_headers):
        """PRD §2.10: "When several checks apply to one request, the server
        evaluates them in a fixed order, so an earlier failure masks every
        later one." Fiscal gates are eighth: "Eighth, fiscal gates — account
        delinquency, credit sufficiency, and the quarterly skip allowance —
        otherwise `ERR_ACCOUNT_DELINQUENT`, `ERR_INSUFFICIENT_CREDIT`, or
        `ERR_SKIP_LIMIT_EXCEEDED`; this tier guards pause, resume, redemption
        creation and fulfillment, credit adjustments, and pickup skips."
        Temporal rules are tenth: "Tenth, temporal rules — the skip cutoff,
        pause-window overlap, the generate-stops weekday match, and the
        commercial weigh-ticket billing gate — otherwise
        `ERR_SKIP_CUTOFF_PASSED`, `ERR_PAUSE_WINDOW_OVERLAP`,
        `ERR_SERVICE_DATE_WEEKDAY_MISMATCH`, or `ERR_WEIGH_TICKET_PENDING`;
        this tier guards skips, pauses, stop generation, and the billing run."

        Design: Difficulty/priority_pair_validation_conflict/pause_while_delinquent_with_overlapping_window_fiscal_beats_temporal
        """
        env = setup_issued_invoice(week_start="2026-05-04")
        sub_id = env["subscription"]["id"]
        # Record one window while still in good standing, then resume.
        pause_subscription(sub_id, "2026-06-01", "2026-06-08")
        from test_helpers import resume_subscription
        resume_subscription(sub_id)
        set_clock("2026-05-20T00:00:00Z")  # past the 2026-05-18 due date
        resp = api.pause_subscription(
            sub_id, {"pause_start": "2026-06-05", "pause_end": "2026-06-12"},
            ops_headers,
        )
        validate_error(resp, ApiErrorId.ERR_ACCOUNT_DELINQUENT)

    def test_rejected_pause_leaves_windows_untouched(self, api, ops_headers):
        """PRD §3.5: "The subscriber must be in `GOOD_STANDING`, otherwise
        `ERR_ACCOUNT_DELINQUENT`." A rejected pause appends no window and
        performs no transition.

        Design: Difficulty/priority_pair_validation_conflict/pause_while_delinquent_with_overlapping_window_fiscal_beats_temporal
        """
        env = setup_issued_invoice(week_start="2026-05-04")
        sub_id = env["subscription"]["id"]
        pause_subscription(sub_id, "2026-06-01", "2026-06-08")
        from test_helpers import resume_subscription
        resume_subscription(sub_id)
        set_clock("2026-05-20T00:00:00Z")
        api.pause_subscription(
            sub_id, {"pause_start": "2026-06-05", "pause_end": "2026-06-12"},
            ops_headers,
        )
        sub = get_subscription(sub_id)
        assert sub["service_status"] == "ACTIVE"
        assert len(sub["pause_windows"]) == 1


class TestPauseSideEffects:
    def test_pause_cancels_only_pickups_inside_window(self, api):
        """PRD §3.5: "every `SCHEDULED` pickup of the subscription whose
        `service_date` falls inside the window transitions to
        `CANCELLED_SYSTEM`" — the window is half-open, inclusive of its start
        and exclusive of its end.

        Design: Corner/state_machines/pause_cancels_only_pickups_inside_window
        """
        env = setup_active_subscription(bin_count=1)
        sub_id = env["subscription"]["id"]
        pickups = generate_and_get_pickups(
            env["route"]["id"], sub_id, ["2026-06-01", "2026-06-08"]
        )
        pause_subscription(sub_id, "2026-06-08", "2026-06-15")
        assert get_pickup(pickups[1]["id"])["status"] == "CANCELLED_SYSTEM"
        assert get_pickup(pickups[0]["id"])["status"] == "SCHEDULED"


def _own(env):
    """Ownership-gated Subscriber headers for the environment's subscriber."""
    from test_helpers import make_subscriber_headers
    return make_subscriber_headers(env["subscriber"]["id"])
