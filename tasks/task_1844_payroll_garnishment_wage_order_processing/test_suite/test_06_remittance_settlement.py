"""Remittance settlement: due-date timing variants, sweep eligibility gates,
late confirmation, duplicate rejection, and segregation of duties."""
from test_helpers import (
    ApiErrorId,
    add_statement,
    api_client,
    create_remittance_payload,
    drive_order_to_active,
    get_order,
    get_remittance,
    get_success_data,
    list_order_events,
    make_open_run,
    pay_run_fresh,
    receive_order,
    set_clock,
    setup_employer_with_employee,
    setup_paid_single_order,
    setup_paid_two_orders,
    setup_pending_remittance,
    suspend_order,
    validate_error,
)
from test_helpers.fixtures import MANAGER, SPECIALIST


class TestRemittanceTimingVariants:
    def test_same_day_due_date_pins_to_pay_date(self, api):
        """PRD §3.7: "The `SAME_DAY` variant pins the due date to the
        `pay_date` itself, whatever weekday it lands on."
        PRD §3.7: "Confirming a `PENDING` remittance on or before its
        `due_date` lands it in `CONFIRMED`; confirming after the `due_date`
        lands it in `LATE_CONFIRMED` instead, with the lateness recorded."
        pay_date Friday 2026-08-14 under SAME_DAY: due 2026-08-14; confirming
        on Saturday 2026-08-15 is already late.

        Design: Difficulty/dual_variant_calc/remittance_timing_same_day_vs_next_business_day
        """
        base = setup_pending_remittance(
            employer_overrides={"remittance_timing": "SAME_DAY"},
            order_overrides={"amount_value": 10000, "total_balance_cents": 100000},
            statement_overrides={
                "gross_earnings_cents": 100000,
                "mandatory_deductions_cents": 20000,
            },
            run_kwargs={
                "period_start": "2026-08-01",
                "period_end": "2026-08-14",
                "pay_date": "2026-08-14",
            },
        )
        rem = base["remittance"]
        assert rem["due_date"] == "2026-08-14"
        set_clock("2026-08-15T09:00:00Z")
        confirmed = get_success_data(
            api_client.confirm_remittance(rem["id"], MANAGER)
        )
        assert confirmed["status"] == "LATE_CONFIRMED"

    def test_next_business_day_skips_weekend(self, api):
        """PRD §3.7: "The employer's `remittance_timing` contributes an offset
        — zero days for `SAME_DAY`, one business day for `NEXT_BUSINESS_DAY`,
        three business days for `THREE_BUSINESS_DAYS` — and the `due_date` is
        the run's `pay_date` advanced by that many business days, skipping
        Saturdays and Sundays with no holiday calendar."
        Identical pay_date Friday 2026-08-14 under NEXT_BUSINESS_DAY: due
        Monday 2026-08-17, so confirming on 2026-08-15 is on time.

        Design: Difficulty/dual_variant_calc/remittance_timing_same_day_vs_next_business_day
        """
        base = setup_pending_remittance(
            employer_overrides={"remittance_timing": "NEXT_BUSINESS_DAY"},
            order_overrides={"amount_value": 10000, "total_balance_cents": 100000},
            statement_overrides={
                "gross_earnings_cents": 100000,
                "mandatory_deductions_cents": 20000,
            },
            run_kwargs={
                "period_start": "2026-08-01",
                "period_end": "2026-08-14",
                "pay_date": "2026-08-14",
            },
        )
        rem = base["remittance"]
        assert rem["due_date"] == "2026-08-17"
        set_clock("2026-08-15T09:00:00Z")
        confirmed = get_success_data(
            api_client.confirm_remittance(rem["id"], MANAGER)
        )
        assert confirmed["status"] == "CONFIRMED"
        assert confirmed["confirmed_at"] is not None


class TestSweepEligibility:
    def test_suspended_order_posts_nothing_and_sweep_fails(self, api):
        """PRD §3.4: "The two interact at exactly one point: withholding may
        post for an order only while its `remit_posture` is `REMITTING`, and
        terminal states always carry a `CLOSED` posture."
        PRD §3.7: "A sweep that finds nothing is rejected with
        `ERR_NO_REMITTABLE_EVENTS` (HTTP 409)"
        The only order is SUSPENDED (posture HELD) at pay time, so no events
        post and create-remittance finds an empty sweep.

        Design: Difficulty/boundary_precision_check/empty_sweep_no_remittable_events
        """
        base = setup_employer_with_employee()
        order = receive_order(
            base["employee"]["id"], base["authority"]["id"],
            case_number="CS-G", amount_value=5000,
        )
        drive_order_to_active(order["id"])
        suspend_order(order["id"], "DISPUTED")
        run = make_open_run(base["employer"]["id"])
        add_statement(
            run["id"], base["employee"]["id"],
            gross_earnings_cents=100000, mandatory_deductions_cents=20000,
        )
        pay_run_fresh(base["employer"]["id"], run["id"])
        assert get_order(order["id"])["withheld_cents"] == 0
        assert list_order_events(order["id"]) == []
        resp = api_client.create_remittance(
            create_remittance_payload(
                base["employer"]["id"], base["authority"]["id"], run["id"]
            ),
            SPECIALIST,
        )
        validate_error(resp, ApiErrorId.ERR_NO_REMITTABLE_EVENTS)

    def test_active_order_sweep_creates_remittance(self, api):
        """PRD §3.7: "Creation sweeps up every still-unassigned `WITHHOLD`
        event posted against that run for orders of that authority whose
        `processing_status` is `ACTIVE` or `ANSWER_FILED`; the remittance's
        `amount_due_cents` is the sum of the swept events, and the swept event
        ids are recorded in its `member_event_ids`."
        Control for the empty sweep: the same fixture with the order left
        ACTIVE sweeps its 5000 award into a PENDING remittance.

        Design: Difficulty/boundary_precision_check/empty_sweep_no_remittable_events
        """
        base = setup_paid_single_order(
            order_overrides={"case_number": "CS-G", "amount_value": 5000},
        )
        rem = get_success_data(
            api_client.create_remittance(
                create_remittance_payload(
                    base["employer"]["id"], base["authority"]["id"], base["run"]["id"]
                ),
                SPECIALIST,
            )
        )
        assert rem["status"] == "PENDING"
        assert rem["amount_due_cents"] == 5000
        assert len(rem["member_event_ids"]) == 1


class TestSweepGatedByOrderState:
    def test_sweep_excludes_events_of_suspended_order(self, api):
        """PRD §3.7: "Creation sweeps up every still-unassigned `WITHHOLD`
        event posted against that run for orders of that authority whose
        `processing_status` is `ACTIVE` or `ANSWER_FILED`; the remittance's
        `amount_due_cents` is the sum of the swept events, and the swept event
        ids are recorded in its `member_event_ids`."
        Order C (4000) is suspended after pay but before remittance creation,
        so its event is not assignable; the remittance covers only order D's
        6000.

        Design: Difficulty/cross_entity_state_dependency/remittance_sweep_gated_by_order_remit_posture
        """
        base = setup_paid_two_orders(
            order_a_overrides={"case_number": "CS-I", "amount_value": 4000},
            order_b_overrides={"case_number": "CS-J", "amount_value": 6000},
            statement_overrides={
                "gross_earnings_cents": 100000,
                "mandatory_deductions_cents": 20000,
            },
        )
        assert base["statement"]["total_withheld_cents"] == 10000
        suspend_order(base["order_a"]["id"], "DISPUTED")
        rem = get_success_data(
            api_client.create_remittance(
                create_remittance_payload(
                    base["employer"]["id"], base["authority"]["id"], base["run"]["id"]
                ),
                SPECIALIST,
            )
        )
        assert rem["amount_due_cents"] == 6000
        d_event = list_order_events(base["order_b"]["id"])[0]
        c_events = list_order_events(base["order_a"]["id"])
        assert rem["member_event_ids"] == [d_event["id"]]
        assert all(e["id"] not in rem["member_event_ids"] for e in c_events)

    def test_sweep_includes_all_active_order_events(self, api):
        """PRD §3.7: "Creation sweeps up every still-unassigned `WITHHOLD`
        event posted against that run for orders of that authority whose
        `processing_status` is `ACTIVE` or `ANSWER_FILED`; the remittance's
        `amount_due_cents` is the sum of the swept events, and the swept event
        ids are recorded in its `member_event_ids`."
        Control: with both orders ACTIVE, the sweep sums both events
        (4000 + 6000 = 10000).

        Design: Difficulty/cross_entity_state_dependency/remittance_sweep_gated_by_order_remit_posture
        """
        base = setup_paid_two_orders(
            order_a_overrides={"case_number": "CS-I", "amount_value": 4000},
            order_b_overrides={"case_number": "CS-J", "amount_value": 6000},
            statement_overrides={
                "gross_earnings_cents": 100000,
                "mandatory_deductions_cents": 20000,
            },
        )
        rem = get_success_data(
            api_client.create_remittance(
                create_remittance_payload(
                    base["employer"]["id"], base["authority"]["id"], base["run"]["id"]
                ),
                SPECIALIST,
            )
        )
        assert rem["amount_due_cents"] == 10000
        assert len(rem["member_event_ids"]) == 2


class TestLateConfirm:
    def test_confirm_after_due_date_lands_late_confirmed(self, api):
        """PRD §3.7: "Confirming a `PENDING` remittance on or before its
        `due_date` lands it in `CONFIRMED`; confirming after the `due_date`
        lands it in `LATE_CONFIRMED` instead, with the lateness recorded.
        Either way `confirmed_at` is stamped from the logical clock and an
        audit entry (action `remittance.confirm`) is appended."
        NEXT_BUSINESS_DAY with pay_date Thursday 2026-08-13: due Friday
        2026-08-14; confirming on Monday 2026-08-17 is late.

        Design: Corner/calculations/due_date_late_confirm_flagged
        """
        base = setup_pending_remittance(
            employer_overrides={"remittance_timing": "NEXT_BUSINESS_DAY"},
            order_overrides={"amount_value": 10000},
            statement_overrides={
                "gross_earnings_cents": 100000,
                "mandatory_deductions_cents": 20000,
            },
            run_kwargs={
                "period_start": "2026-08-01",
                "period_end": "2026-08-13",
                "pay_date": "2026-08-13",
            },
        )
        rem = base["remittance"]
        assert rem["due_date"] == "2026-08-14"
        set_clock("2026-08-17T09:00:00Z")
        confirmed = get_success_data(
            api_client.confirm_remittance(rem["id"], MANAGER)
        )
        assert confirmed["status"] == "LATE_CONFIRMED"
        assert confirmed["confirmed_at"] is not None


class TestDuplicateAndSoD:
    def test_duplicate_remittance_rejected(self, api):
        """PRD §3.7: "because there is at most one remittance per authority per
        run, a second create for the same pairing of `authority_id` and
        `payroll_run_id` is rejected with `ERR_DUPLICATE_REMITTANCE`
        (HTTP 409)."

        Design: Corner/validations/duplicate_remittance_rejected
        """
        base = setup_pending_remittance()
        resp = api_client.create_remittance(
            create_remittance_payload(
                base["employer"]["id"], base["authority"]["id"], base["run"]["id"]
            ),
            SPECIALIST,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_REMITTANCE)

    def test_specialist_cannot_confirm_remittance(self, api):
        """PRD §2.10: "A `payroll_specialist` pays runs and creates
        remittances, but only a `payroll_manager` may confirm or cancel those
        remittances, file answers, suspend or terminate orders, or issue
        refunds."
        PRD §2.1: "Attempting an operation outside one's role is rejected with
        `ERR_FORBIDDEN_ROLE` (HTTP 403)."

        Design: Corner/rbac/specialist_cannot_confirm_remittance
        """
        base = setup_pending_remittance()
        resp = api_client.confirm_remittance(base["remittance"]["id"], SPECIALIST)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
        assert get_remittance(base["remittance"]["id"])["status"] == "PENDING"
