"""Critical dates: notification window boundary precision, terminal lockdown,
exercisability, and the fixed default clock."""
from test_helpers import (
    ApiErrorId,
    approve_amendment_on,
    apply_amendment_on,
    create_amendment_on,
    create_critical_date_on,
    set_clock,
    setup_active_lease,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

PM = TEST_USERS["portfolio_manager_headers"]
PROP_MGR = TEST_USERS["property_manager_headers"]


def _three_notice_dates(api):
    """Active lease plus three identical NOTICE_DEADLINE critical dates with
    due_date 2026-06-30 and advance_notice_days 30 (window opens 2026-05-31)."""
    ctx = setup_active_lease()
    cds = [
        create_critical_date_on(
            ctx["lease"]["id"], kind="NOTICE_DEADLINE",
            due_date="2026-06-30", advance_notice_days=30,
        )
        for _ in range(3)
    ]
    return ctx, cds


class TestNotifyWindowBoundary:
    def test_notify_one_day_before_window_rejected_and_on_open_accepted(self, api):
        """PRD §3.7: "Notification marks that the tenant or landlord has been
        reminded ahead of the deadline: a `PropertyManager` notifies a `PENDING`
        date, moving it to `NOTIFIED`, only inside the notification window —
        the current logical date must be at least `advance_notice_days` before
        the `due_date`, else `ERR_NOTIFICATION_NOT_YET_DUE`, and must still be
        earlier than the `due_date` itself, else
        `ERR_NOTIFICATION_WINDOW_MISSED`."

        Design: Difficulty/boundary_precision_check/critical_date_notify_window_start_boundary
        """
        _, cds = _three_notice_dates(api)
        # One day before the window opens (window starts 2026-05-31).
        set_clock("2026-05-30T00:00:00Z")
        resp = api.notify_critical_date(cds[0]["id"], PROP_MGR)
        validate_error(resp, ApiErrorId.ERR_NOTIFICATION_NOT_YET_DUE)
        # Exactly on the first valid day.
        set_clock("2026-05-31T00:00:00Z")
        ok = validate_success(api.notify_critical_date(cds[1]["id"], PROP_MGR))
        assert ok["status"] == "NOTIFIED", (
            f"notify on the exact window start must succeed, got {ok['status']}"
        )

    def test_notify_on_due_date_is_window_missed(self, api):
        """PRD §3.7: "Notification marks that the tenant or landlord has been
        reminded ahead of the deadline: a `PropertyManager` notifies a `PENDING`
        date, moving it to `NOTIFIED`, only inside the notification window —
        the current logical date must be at least `advance_notice_days` before
        the `due_date`, else `ERR_NOTIFICATION_NOT_YET_DUE`, and must still be
        earlier than the `due_date` itself, else
        `ERR_NOTIFICATION_WINDOW_MISSED`."
        (The 'earlier than' check is strict: notifying on the due date itself
        is already too late.)

        Design: Difficulty/boundary_precision_check/critical_date_notify_window_start_boundary
        """
        _, cds = _three_notice_dates(api)
        set_clock("2026-06-30T00:00:00Z")  # exactly on the due date
        resp = api.notify_critical_date(cds[2]["id"], PROP_MGR)
        validate_error(resp, ApiErrorId.ERR_NOTIFICATION_WINDOW_MISSED)


class TestCriticalDateTerminal:
    def test_critical_date_lapsed_is_terminal(self, api):
        """PRD §3.7: "Dates that pass unexercised lapse: when the logical clock
        moves beyond a `PENDING` or `NOTIFIED` date's `due_date`, the system
        transitions it to `LAPSED`, and a `PropertyManager` may also lapse such
        a date manually once its due date has passed. A `PortfolioManager` may
        instead waive a `PENDING` or `NOTIFIED` date, moving it to `WAIVED`.
        `EXERCISED`, `LAPSED`, and `WAIVED` are terminal."
        PRD §2.11: "Sixth, state-machine legality on every state-transition
        endpoint, else `ERR_INVALID_STATE` (HTTP 409)."

        Design: Corner/state_machines/critical_date_lapsed_is_terminal
        """
        ctx = setup_active_lease()
        cd = create_critical_date_on(
            ctx["lease"]["id"], kind="NOTICE_DEADLINE",
            due_date="2026-09-01", advance_notice_days=30,
        )
        # Clock advance past the due date auto-lapses the PENDING date.
        set_clock("2026-10-01T00:00:00Z")
        after_lapse = validate_success(api.get_critical_date(cd["id"], PROP_MGR))
        assert after_lapse["status"] == "LAPSED", (
            f"clock past due_date must lapse the date, got {after_lapse['status']}"
        )
        resp = api.notify_critical_date(cd["id"], PROP_MGR)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_challenge_exercise_nonexercisable_kind(self, api):
        """PRD §3.7: "Exercising is the substantive act and is available from
        either `PENDING` or `NOTIFIED`: only dates of kind `OPTION_EXERCISE`,
        `RENEWAL_WINDOW_OPEN`, or `RENEWAL_WINDOW_CLOSE` are exercisable at all
        (else `ERR_NOT_EXERCISABLE`); the request must carry a
        `linked_amendment_id` referencing an Amendment that has already reached
        `APPLIED` (else `ERR_AMENDMENT_NOT_APPLIED`); and the current logical
        date must not have passed the `due_date` (else `ERR_DATE_PASSED`)."

        Design: Corner/validations/challenge_exercise_nonexercisable_kind
        """
        ctx = setup_active_lease()
        cd = create_critical_date_on(
            ctx["lease"]["id"], kind="NOTICE_DEADLINE",
            due_date="2027-09-01", advance_notice_days=30,
        )
        amendment = create_amendment_on(
            ctx["lease"]["id"], kind="EXTENSION", effective_date="2027-06-01",
            new_expiration_date="2028-12-31",
        )
        approve_amendment_on(amendment["id"], ctx["lease"]["version"])
        apply_amendment_on(amendment["id"])
        resp = api.exercise_critical_date(
            cd["id"], {"linked_amendment_id": amendment["id"]}, PROP_MGR,
        )
        validate_error(resp, ApiErrorId.ERR_NOT_EXERCISABLE)


class TestLogicalClockDefault:
    def test_clock_default_is_fixed(self, api):
        """PRD §2.7: "At server startup the logical clock defaults to
        `2026-05-01T00:00:00Z` and does not fall back to wall-clock time; the
        only way time advances is through an admin-only test-driving capability
        that sets the logical clock to a supplied `to_iso8601` instant and
        reports the resulting `current_utc`."
        PRD §3.7: "a `PropertyManager` notifies a `PENDING` date, moving it to
        `NOTIFIED`, only inside the notification window — the current logical
        date must be at least `advance_notice_days` before the `due_date`, else
        `ERR_NOTIFICATION_NOT_YET_DUE`, and must still be earlier than the
        `due_date` itself, else `ERR_NOTIFICATION_WINDOW_MISSED`."
        (No set_current_utc call is made by this test: at the 2026-05-01
        default, the 2027-05-31 window start has not been reached.)

        Design: Corner/cross_cutting_layers/clock_default_is_fixed
        """
        # Deliberately exercise the default clock: build the arrangement without
        # driving the clock at all (server starts at 2026-05-01T00:00:00Z).
        from test_helpers import (
            add_schedule_line,
            certify_lease,
            create_billing,
            create_lease,
            create_pool,
            create_property,
        )
        prop = create_property()
        lease = create_lease(prop["id"])
        certify_lease(lease["id"])
        add_schedule_line(lease["id"])
        pool = create_pool(prop["id"])
        create_billing(lease["id"], pool["id"])
        ctx_lease = validate_success(api.activate_lease(lease["id"], PM))
        assert ctx_lease["status"] == "ACTIVE"
        ctx = {"lease": ctx_lease}
        cd = create_critical_date_on(
            ctx["lease"]["id"], kind="NOTICE_DEADLINE",
            due_date="2027-06-30", advance_notice_days=30,
        )
        resp = api.notify_critical_date(cd["id"], PROP_MGR)
        validate_error(resp, ApiErrorId.ERR_NOTIFICATION_NOT_YET_DUE)
