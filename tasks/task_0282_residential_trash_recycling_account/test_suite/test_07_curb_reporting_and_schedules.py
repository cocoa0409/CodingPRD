"""Curb outcome reporting, contamination-notice branching, holiday shift, cross-entity
state dependencies, and immediate-consistency of derived balances. Covers difficulty
rules non_linear_state_machine (contamination notice) and cross_entity_state_dependency,
plus the related state_machines / validations / consistency corner instances.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    TEST_USERS, make_account_holder_headers,
    ApiErrorId,
    create_active_account, create_plan, create_zone, set_clock,
    create_account, add_standard_carts,
    setup_account_with_n_contamination_notices,
    setup_account_with_requested_extra_pickup,
)

DISP = TEST_USERS["dispatcher_headers"]
CREW = TEST_USERS["crew_lead_headers"]


class TestContaminationNoticeBranching:
    def test_acknowledge_preserves_fee(self, api):
        """PRD §3.9: "The owning AccountHolder may acknowledge an OPEN notice, moving it
        OPEN → ACKNOWLEDGED; acknowledgement is a record-keeping step that leaves the fee
        in place."

        Design: Difficulty/non_linear_state_machine/contamination_notice_branching_acknowledge_or_waive
        """
        s = setup_account_with_n_contamination_notices(2, last_severity="MINOR", address="20 Oak St")
        acct = s["account"]
        notice = s["notices"][1]  # second notice, fee 1500
        assert notice["fee_cents"] == 1500
        holder = make_account_holder_headers(acct["id"])
        acked = validate_success(api.acknowledge_contamination_notice(notice["id"], holder), 200)
        assert acked["status"] == "ACKNOWLEDGED"
        assert acked["fee_cents"] == 1500

    def test_waive_zeroes_fee(self, api):
        """PRD §3.9: "A Dispatcher may waive a notice from either OPEN or ACKNOWLEDGED,
        moving it to the terminal WAIVED state; waiving sets fee_cents to 0, which reverses
        the posting to the next invoice gross."

        Design: Difficulty/non_linear_state_machine/contamination_notice_branching_acknowledge_or_waive
        """
        s = setup_account_with_n_contamination_notices(2, last_severity="MINOR", address="21 Oak St")
        notice = s["notices"][1]
        waived = validate_success(api.waive_contamination_notice(notice["id"], DISP), 200)
        assert waived["status"] == "WAIVED"
        assert waived["fee_cents"] == 0


class TestContaminationWaiveConservesFeeTotal:
    def test_waive_returns_invoice_contamination_contribution_to_zero(self, api):
        """PRD §3.9: "waiving sets fee_cents to 0, which reverses the posting to the next
        invoice gross."
        PRD §3.11: "Part four is the sum of fee_cents over every ContaminationNotice on the
        account whose status is OPEN or ACKNOWLEDGED and whose linked recycling pickup ...
        has a service_date on or after period_start and strictly before period_end."

        Design: Difficulty/compensating_invariant/contamination_waive_conserves_invoiceable_fee_total
        """
        s = setup_account_with_n_contamination_notices(2, last_severity="MINOR", address="44 Oak St")
        acct = s["account"]
        second = s["notices"][1]
        waived = validate_success(api.waive_contamination_notice(second["id"], DISP), 200)
        assert waived["fee_cents"] == 0
        v = validate_success(api.get_account(acct["id"], DISP), 200)["version"]
        inv = validate_success(api.generate_invoice(acct["id"], {
            "expected_account_version": v,
            "period_start": "2026-03-01T00:00:00Z", "period_end": "2026-04-01T00:00:00Z",
            "due_date": "2026-04-15T00:00:00Z"}, DISP), 201)
        # base 4000 only; both notices contribute 0 (first free, second waived)
        assert inv["gross_amount_cents"] == 4000

    def test_waive_zeroes_fee_conserved_quantity(self, api):
        """PRD §3.9: "waiving sets fee_cents to 0, which reverses the posting to the next
        invoice gross."

        Design: Difficulty/compensating_invariant/contamination_waive_conserves_invoiceable_fee_total
        """
        s = setup_account_with_n_contamination_notices(2, last_severity="MINOR", address="45 Oak St")
        second = s["notices"][1]
        waived = validate_success(api.waive_contamination_notice(second["id"], DISP), 200)
        assert waived["fee_cents"] == 0


class TestHolidayShift:
    def test_pickup_on_holiday_slips_one_day(self, api):
        """PRD §3.6: "If such a holiday exists and its shift_direction is DELAY_ONE_DAY, the
        effective_pickup_date is the service_date advanced by exactly one day."

        Design: Corner/state_machines/holiday_shift_delay_one_day_effective_date
        """
        plan = create_plan()
        zone = create_zone()
        get_success_data(api.create_holiday(
            zone["id"], {"holiday_date": "2026-03-02T00:00:00Z", "shift_direction": "DELAY_ONE_DAY"}, DISP))
        set_clock("2026-02-26T00:00:00Z")
        acct = create_account(plan["id"], zone["id"], address="64 Oak St")
        add_standard_carts(acct["id"])
        acct = get_success_data(api.activate_start(acct["id"], DISP))
        rows = get_success_data(api.list_pickup_schedules(acct["id"], DISP, {"stream": "TRASH"}))
        s0 = rows[0]
        assert s0["service_date"] == "2026-03-02T00:00:00Z"
        assert s0["effective_pickup_date"] == "2026-03-03T00:00:00Z"


class TestEventIdempotency:
    def test_second_event_on_completed_schedule_invalid_state(self, api):
        """PRD §3.7: "A report is only accepted while the schedule row is PLANNED and its
        parent account is ACTIVE; reporting against a row in any other state is an illegal
        transition."

        Design: Corner/state_machines/collect_event_after_completed_returns_invalid_state
        """
        _, _, acct = create_active_account(clock="2026-03-02T00:00:00Z", address="62 Oak St")
        rows = get_success_data(api.list_pickup_schedules(acct["id"], DISP, {"stream": "TRASH"}))
        s0 = rows[0]
        validate_success(api.report_event(
            s0["id"], {"outcome": "COLLECTED", "reported_at": s0["effective_pickup_date"]}, CREW), 201)
        validate_error(api.report_event(
            s0["id"], {"outcome": "COLLECTED", "reported_at": s0["effective_pickup_date"]}, CREW),
            ApiErrorId.ERR_INVALID_STATE.value)


class TestCrossEntityStateDependency:
    def test_schedule_extra_pickup_blocked_when_account_suspended(self, api):
        """PRD §3.10: "A Dispatcher schedules a REQUESTED request, advancing it
        REQUESTED → SCHEDULED, but only when the parent account is ACTIVE."

        Design: Difficulty/cross_entity_state_dependency/extra_pickup_schedule_requires_account_active
        """
        s = setup_account_with_requested_extra_pickup(
            "2026-03-26T00:00:00Z", 1, address="32 Oak St")
        acct = s["account"]
        validate_success(api.suspend_account(acct["id"], DISP), 200)
        validate_error(api.schedule_extra_pickup(s["request"]["id"], DISP),
                       ApiErrorId.ERR_INVALID_STATE.value)

    def test_schedule_extra_pickup_succeeds_while_account_active(self, api):
        """PRD §3.10: "A Dispatcher schedules a REQUESTED request, advancing it
        REQUESTED → SCHEDULED, but only when the parent account is ACTIVE."

        The complement: while the parent account IS ACTIVE the same scheduling transition
        is accepted, confirming the dependency is on the account's status.

        Design: Difficulty/cross_entity_state_dependency/extra_pickup_schedule_requires_account_active
        """
        s = setup_account_with_requested_extra_pickup(
            "2026-03-26T00:00:00Z", 1, address="35 Oak St")
        scheduled = validate_success(api.schedule_extra_pickup(s["request"]["id"], DISP), 200)
        assert scheduled["status"] == "SCHEDULED"

    def test_report_event_blocked_when_account_suspended(self, api):
        """PRD §3.7: "A report is only accepted while the schedule row is PLANNED and its
        parent account is ACTIVE; reporting against a row in any other state is an illegal
        transition."
        PRD §3.3: "every PLANNED schedule row whose effective pickup date is on or after
        the current clock date is cancelled."

        Design: Difficulty/cross_entity_state_dependency/pickup_event_requires_account_active
        """
        plan = create_plan()
        zone = create_zone()
        set_clock("2026-03-02T00:00:00Z")
        acct = create_account(plan["id"], zone["id"], address="34 Oak St")
        add_standard_carts(acct["id"])
        acct = get_success_data(api.activate_start(acct["id"], DISP))
        rows = get_success_data(api.list_pickup_schedules(acct["id"], DISP, {"stream": "TRASH"}))
        s0 = rows[0]  # effective 2026-03-02, will stay PLANNED after the clock advance
        # advance clock so s0 is in the past, then suspend: suspend only cancels rows
        # with effective_pickup_date >= clock, so s0 stays PLANNED while account SUSPENDED
        get_success_data(api.set_clock({"to_iso8601": "2026-03-25T00:00:00Z"}, DISP))
        validate_success(api.suspend_account(acct["id"], DISP), 200)
        row = validate_success(api.get_pickup_schedule(s0["id"], DISP), 200)
        assert row["status"] == "PLANNED", "the past-dated row must remain PLANNED"
        validate_error(api.report_event(
            s0["id"], {"outcome": "COLLECTED", "reported_at": s0["effective_pickup_date"]}, CREW),
            ApiErrorId.ERR_INVALID_STATE.value)

    def test_report_event_succeeds_while_account_active(self, api):
        """PRD §3.7: "A report is only accepted while the schedule row is PLANNED and its
        parent account is ACTIVE."
        PRD §3.7: "A COLLECTED outcome simply advances the row PLANNED → COMPLETED."

        The complement: a PLANNED row on an ACTIVE account accepts the COLLECTED report and
        advances to COMPLETED, confirming the transition depends on the account's status.

        Design: Difficulty/cross_entity_state_dependency/pickup_event_requires_account_active
        """
        _, _, acct = create_active_account(clock="2026-03-02T00:00:00Z", address="35 Maple St")
        rows = get_success_data(api.list_pickup_schedules(acct["id"], DISP, {"stream": "TRASH"}))
        s0 = rows[0]
        validate_success(api.report_event(
            s0["id"], {"outcome": "COLLECTED", "reported_at": s0["effective_pickup_date"]}, CREW), 201)
        row = validate_success(api.get_pickup_schedule(s0["id"], DISP), 200)
        assert row["status"] == "COMPLETED"


class TestImmediateConsistency:
    def test_credit_balance_visible_immediately_after_missed(self, api):
        """PRD §2.9: "The system's consistency model is immediate — all cascades complete
        within the triggering request, and a subsequent read reflects them."
        PRD §3.8: "Issuing a credit raises the account's credit_balance_cents and
        re-derives its account_balance_cents immediately."

        Design: Corner/consistency_model/credit_balance_visible_immediately_after_missed_event
        """
        _, _, acct = create_active_account(clock="2026-03-02T00:00:00Z", address="98 Oak St")
        rows = get_success_data(api.list_pickup_schedules(acct["id"], DISP, {"stream": "TRASH"}))
        s0 = rows[0]
        get_success_data(api.report_event(
            s0["id"], {"outcome": "MISSED", "reported_at": s0["effective_pickup_date"]}, CREW))
        acct_after = validate_success(api.get_account(acct["id"], DISP), 200)
        assert acct_after["credit_balance_cents"] == 300
