"""Approval, payment, rejection, withdrawal, program close-out, and the
evaluation-adjustment reporting pipeline — including the compensating ledger
invariants (budget cents, reported kWh) and the SUBMITTED-state branch fork."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    add_line_item,
    approve_application,
    assert_program_ledger_invariants,
    attach_savings_claim,
    build_approved_application,
    build_closed_program_with_paid_app,
    build_paid_application,
    build_submitted_application,
    build_verified_application,
    create_active_ally,
    create_draft_application,
    create_evaluation_adjustment_payload,
    create_open_program,
    get_application,
    get_line_item,
    get_program_year,
    make_admin_headers,
    make_inspector_headers,
    make_trade_ally_headers,
    pay_application,
    submit_application,
    validate_error,
    validate_success,
    verify_application,
)


class TestApplicationStateMachineEdges:
    def test_submit_twice_returns_invalid_state(self, api, admin_headers):
        """PRD §3.4: "After authentication, authorization, and resource
        resolution: the program-open gate (`ERR_PROGRAM_NOT_OPEN`); the `DRAFT`
        state check (`ERR_INVALID_STATE`); ally standing, requiring the
        installing ally to be `ACTIVE` (`ERR_ALLY_NOT_ACTIVE`, HTTP 409);
        catalog currency, requiring every line item's measure to be active
        (`ERR_MEASURE_INACTIVE`, HTTP 409); presence of at least one line item
        (`ERR_NO_LINE_ITEMS`, HTTP 422); the invoice eligibility window; the
        budget-cap check; and only then the ownership comparison
        (`ERR_FORBIDDEN`)."

        Design: Corner/state_machines/application_submit_twice_returns_invalid_state
        """
        py, measures = create_open_program()
        ally = create_active_ally()
        app, _line = build_submitted_application(py, ally, measures[0])
        assert app["status"] == "SUBMITTED"

        res = api.submit_application(app["id"], make_trade_ally_headers(ally["id"]))
        validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

    def test_approve_from_draft_returns_invalid_state(self, api, admin_headers):
        """PRD §3.6: "Approval's checks run in order — the program-open gate,
        the `VERIFIED` state check, then the fraud hold, then segregation of
        duties — so a `SUSPECT` application is refused with
        `ERR_FRAUD_SUSPECT_HOLD` (HTTP 409) even when the approver would also
        trip the segregation rule."

        Design: Corner/state_machines/application_approve_from_draft_returns_invalid_state
        """
        py, measures = create_open_program()
        ally = create_active_ally()
        app = create_draft_application(py, ally)
        assert app["status"] == "DRAFT"

        res = api.approve_application(app["id"], admin_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

    def test_paid_is_terminal(self, api, admin_headers):
        """PRD §3.6: "Payment is the finance step, performed by a
        `PaymentProcessor` on an `APPROVED` application: the application moves
        `APPROVED` → `PAID`, its `incentive_total_cents` leaves the year's
        `committed_cents` and lands in `paid_cents`, and both resources'
        versions increment. `PAID` is terminal."
        PRD §3.6: "Rejection by a `ProgramAdministrator` is available from
        `SUBMITTED` or `VERIFIED` — any other state yields `ERR_INVALID_STATE`."

        Design: Corner/state_machines/application_paid_is_terminal
        """
        py, measures = create_open_program()
        ally = create_active_ally()
        app, _line = build_paid_application(py, ally, measures[0], claim="DEEMED")
        assert app["status"] == "PAID"

        res = api.reject_application(app["id"], admin_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

    def test_approve_by_verifier_returns_segregation_error(self, api, admin_headers):
        """PRD §3.6: "Segregation of duties forbids self-approval across the
        verification boundary: the approver's `X-User-ID` must differ from the
        application's `verified_by`, or the approval is refused with
        `ERR_SEGREGATION_OF_DUTIES` (HTTP 409)."

        Design: Corner/validations/approve_by_same_user_as_verifier_returns_segregation_error
        """
        py, measures = create_open_program()
        ally = create_active_ally()
        app, _line = build_verified_application(
            py, ally, measures[0], claim="DEEMED",
            inspector_user_id="shared-ops-user",
        )
        assert app["verified_by"] == "shared-ops-user"

        res = api.approve_application(app["id"], make_admin_headers("shared-ops-user"))
        validate_error(res, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, expected_status=409)
        assert get_application(app["id"])["status"] == "VERIFIED"


class TestSubmittedBranching:
    def test_submitted_can_verify_withdraw_or_reject(self, api, admin_headers):
        """PRD §2.5: "an application's `status` runs `DRAFT` → `SUBMITTED` →
        `PRE_INSPECTION` → `POST_INSPECTION` → `VERIFIED` → `APPROVED` → `PAID`,
        with `REJECTED` and `WITHDRAWN` reachable from several states as §3
        details."
        PRD §3.6: "Rejection by a `ProgramAdministrator` is available from
        `SUBMITTED` or `VERIFIED` — any other state yields `ERR_INVALID_STATE`."
        PRD §3.6: "Withdrawal is the owning trade ally's escape hatch, available
        from `DRAFT` or `SUBMITTED`; the acting ally's `X-User-ID` must equal
        the application's `trade_ally_id`, or the call is refused with
        `ERR_FORBIDDEN`."

        Design: Difficulty/non_linear_state_machine/rebate_application_branching_withdraw_vs_verify_vs_reject
        """
        py, measures = create_open_program()
        ally = create_active_ally()
        app_a, _ = build_submitted_application(py, ally, measures[0])
        app_b, _ = build_submitted_application(py, ally, measures[0])
        app_c, _ = build_submitted_application(py, ally, measures[0])

        app_a = verify_application(app_a)
        assert app_a["status"] == "VERIFIED"

        res_b = api.withdraw_application(
            app_b["id"], make_trade_ally_headers(ally["id"])
        )
        assert validate_success(res_b, 200)["status"] == "WITHDRAWN"

        res_c = api.reject_application(app_c["id"], admin_headers)
        assert validate_success(res_c, 200)["status"] == "REJECTED"

    def test_withdraw_and_reject_release_committed_incentive(self, api, admin_headers):
        """PRD §3.6: "Withdrawing from `DRAFT` touches no ledger, since nothing
        was ever committed; withdrawing from `SUBMITTED` releases the committed
        incentive exactly as a rejection does, and the year's `version`
        increments alongside the application's."
        PRD §3.6: "Either way, the application's `incentive_total_cents` is
        released from the year's `committed_cents`."

        Design: Difficulty/non_linear_state_machine/rebate_application_branching_withdraw_vs_verify_vs_reject
        """
        py, measures = create_open_program()
        ally = create_active_ally()
        app_a, _ = build_submitted_application(py, ally, measures[0])
        app_b, _ = build_submitted_application(py, ally, measures[0])
        app_c, _ = build_submitted_application(py, ally, measures[0])
        assert get_program_year(py["id"])["committed_cents"] == 30_000

        verify_application(app_a)  # stays committed; adds reported_kwh
        api.withdraw_application(app_b["id"], make_trade_ally_headers(ally["id"]))
        api.reject_application(app_c["id"], admin_headers)

        py_after = get_program_year(py["id"])
        assert py_after["committed_cents"] == 10_000
        assert py_after["reported_kwh"] == 100
        assert_program_ledger_invariants(py_after)


class TestBudgetCentsConservation:
    def test_pay_moves_incentive_from_committed_to_paid(self, api, admin_headers):
        """PRD §3.6: "Payment is the finance step, performed by a
        `PaymentProcessor` on an `APPROVED` application: the application moves
        `APPROVED` → `PAID`, its `incentive_total_cents` leaves the year's
        `committed_cents` and lands in `paid_cents`, and both resources'
        versions increment."
        PRD §2.6: "`committed_cents` is the sum of `incentive_total_cents` over
        the year's applications currently in `SUBMITTED`, `PRE_INSPECTION`,
        `POST_INSPECTION`, `VERIFIED`, or `APPROVED`; it rises at submission and
        is released when an application is rejected, withdrawn, or paid.
        `paid_cents` is the sum of `incentive_total_cents` over the year's
        applications in `PAID`."

        Design: Difficulty/compensating_invariant/budget_cents_conservation_through_pay
        """
        py, measures = create_open_program()
        ally = create_active_ally()
        app, _line = build_approved_application(py, ally, measures[0], claim="DEEMED")

        py_before = get_program_year(py["id"])
        assert py_before["committed_cents"] == 10_000
        assert py_before["paid_cents"] == 0
        total_before = py_before["committed_cents"] + py_before["paid_cents"]

        app = pay_application(app)
        assert app["status"] == "PAID"

        py_after = get_program_year(py["id"])
        assert py_after["committed_cents"] == 0
        assert py_after["paid_cents"] == 10_000
        # Conserved: pay only moves the money between buckets.
        assert py_after["committed_cents"] + py_after["paid_cents"] == total_before
        assert_program_ledger_invariants(py_after)

    def test_conservation_holds_across_sequential_payments(self, api, admin_headers):
        """PRD §2.6: "`committed_cents` is the sum of `incentive_total_cents`
        over the year's applications currently in `SUBMITTED`,
        `PRE_INSPECTION`, `POST_INSPECTION`, `VERIFIED`, or `APPROVED`; it rises
        at submission and is released when an application is rejected,
        withdrawn, or paid. `paid_cents` is the sum of `incentive_total_cents`
        over the year's applications in `PAID`."

        Design: Difficulty/compensating_invariant/budget_cents_conservation_through_pay
        """
        py, measures = create_open_program(
            measure_specs=[
                {"measure_code": "M-A", "base_rate_cents": 10_000,
                 "deemed_kwh_per_unit": 100},
                {"measure_code": "M-B", "base_rate_cents": 20_000,
                 "deemed_kwh_per_unit": 100},
            ]
        )
        ally = create_active_ally()
        app_a, _ = build_approved_application(py, ally, measures[0], claim="DEEMED")
        app_b, _ = build_approved_application(py, ally, measures[1], claim="DEEMED")

        py_mid = get_program_year(py["id"])
        assert py_mid["committed_cents"] == 30_000
        assert py_mid["paid_cents"] == 0

        pay_application(app_a)
        py_mid = get_program_year(py["id"])
        assert py_mid["committed_cents"] + py_mid["paid_cents"] == 30_000
        assert py_mid["committed_cents"] == 20_000
        assert py_mid["paid_cents"] == 10_000

        pay_application(app_b)
        py_end = get_program_year(py["id"])
        assert py_end["committed_cents"] == 0
        assert py_end["paid_cents"] == 30_000
        assert py_end["committed_cents"] + py_end["paid_cents"] == 30_000


class TestReportedKwhConservation:
    def test_reject_verified_application_restores_reported_kwh(self, api, admin_headers):
        """PRD §3.6: "Rejecting a previously verified application additionally
        subtracts its `final_kwh` from the year's `reported_kwh` and recomputes
        `adjusted_kwh` and `goal_attainment_pct`."
        PRD §2.6: "`reported_kwh` is the sum of `final_kwh` over the year's
        applications in `VERIFIED`, `APPROVED`, or `PAID`."

        Design: Difficulty/compensating_invariant/reported_kwh_conservation_through_reject
        """
        py, measures = create_open_program()
        ally = create_active_ally()
        app_a, _ = build_verified_application(py, ally, measures[0], claim="DEEMED")
        app_b, _ = build_verified_application(py, ally, measures[0], claim="DEEMED")
        assert get_program_year(py["id"])["reported_kwh"] == 200

        res = api.reject_application(app_b["id"], admin_headers)
        assert validate_success(res, 200)["status"] == "REJECTED"

        py_after = get_program_year(py["id"])
        assert py_after["reported_kwh"] == 100
        assert get_application(app_a["id"])["status"] == "VERIFIED"

    def test_reject_verified_recomputes_adjusted_and_attainment(self, api, admin_headers):
        """PRD §3.6: "Rejecting a previously verified application additionally
        subtracts its `final_kwh` from the year's `reported_kwh` and recomputes
        `adjusted_kwh` and `goal_attainment_pct`."
        PRD §3.7: "With no adjustment at all, `adjusted_kwh` simply equals
        `reported_kwh`"
        PRD §3.7: "`goal_attainment_pct` is one hundred times `adjusted_kwh`
        divided by `savings_goal_kwh`, rounded half-up to a whole percent."

        Design: Difficulty/compensating_invariant/reported_kwh_conservation_through_reject
        """
        py, measures = create_open_program(savings_goal_kwh=200)
        ally = create_active_ally()
        build_verified_application(py, ally, measures[0], claim="DEEMED")
        app_b, _ = build_verified_application(py, ally, measures[0], claim="DEEMED")

        py_mid = get_program_year(py["id"])
        assert py_mid["reported_kwh"] == 200
        assert py_mid["adjusted_kwh"] == 200
        assert py_mid["goal_attainment_pct"] == 100

        api.reject_application(app_b["id"], admin_headers)
        py_after = get_program_year(py["id"])
        assert py_after["reported_kwh"] == 100
        assert py_after["adjusted_kwh"] == 100
        assert py_after["goal_attainment_pct"] == 50


class TestProgramCloseOut:
    def test_close_with_submitted_application_returns_error(self, api, admin_headers):
        """PRD §3.7: "Closing requires the `OPEN` state — the state check runs
        first — and a quiet pipeline: no application of the year may remain in
        `SUBMITTED`, `PRE_INSPECTION`, `POST_INSPECTION`, or `VERIFIED`, or the
        close is refused with `ERR_OPEN_APPLICATIONS_REMAIN` (HTTP 409)."

        Design: Corner/validations/close_program_with_submitted_application_returns_error
        """
        py, measures = create_open_program()
        ally = create_active_ally()
        build_submitted_application(py, ally, measures[0])

        res = api.close_program_year(py["id"], admin_headers)
        validate_error(res, ApiErrorId.ERR_OPEN_APPLICATIONS_REMAIN, expected_status=409)
        assert get_program_year(py["id"])["status"] == "OPEN"

    def test_close_auto_pays_single_approved_application(self, api, admin_headers):
        """PRD §3.7: "Closing settles every still-`APPROVED` application
        automatically, in `created_at` ascending order: each moves to `PAID`,
        its `incentive_total_cents` shifting from `committed_cents` to
        `paid_cents` exactly as a manual payment would. The year's `status`
        becomes `CLOSED` and its `version` increments."

        Design: Difficulty/transitive_cascade/program_year_close_auto_pays_cascade
        """
        py, measures = create_open_program()
        ally = create_active_ally()
        app, _line = build_approved_application(py, ally, measures[0], claim="DEEMED")
        assert get_program_year(py["id"])["committed_cents"] == 10_000

        py = validate_success(api.close_program_year(py["id"], admin_headers), 200)
        assert py["status"] == "CLOSED"

        app_after = get_application(app["id"])
        assert app_after["status"] == "PAID"
        assert py["committed_cents"] == 0
        assert py["paid_cents"] == 10_000

    def test_close_auto_pays_every_approved_application(self, api, admin_headers):
        """PRD §3.7: "Closing settles every still-`APPROVED` application
        automatically, in `created_at` ascending order: each moves to `PAID`,
        its `incentive_total_cents` shifting from `committed_cents` to
        `paid_cents` exactly as a manual payment would."

        Design: Difficulty/transitive_cascade/program_year_close_auto_pays_cascade
        """
        py, measures = create_open_program(
            measure_specs=[
                {"measure_code": "M-A", "base_rate_cents": 10_000,
                 "deemed_kwh_per_unit": 100},
                {"measure_code": "M-B", "base_rate_cents": 20_000,
                 "deemed_kwh_per_unit": 100},
            ]
        )
        ally = create_active_ally()
        app_a, _ = build_approved_application(py, ally, measures[0], claim="DEEMED")
        app_b, _ = build_approved_application(py, ally, measures[1], claim="DEEMED")

        py = validate_success(api.close_program_year(py["id"], admin_headers), 200)
        assert py["status"] == "CLOSED"
        assert get_application(app_a["id"])["status"] == "PAID"
        assert get_application(app_b["id"])["status"] == "PAID"
        assert py["committed_cents"] == 0
        assert py["paid_cents"] == 30_000

    def test_report_without_evaluation_adjustment_returns_error(
        self, api, admin_headers, regulator_headers
    ):
        """PRD §3.7: "The state check runs first, then the evidentiary check —
        at least one evaluation adjustment must exist for the year, else the
        transition is refused with `ERR_NO_EVALUATION_ADJUSTMENT` (HTTP 422)."

        Design: Corner/validations/report_without_evaluation_adjustment_returns_error
        """
        py, measures = create_open_program()
        py = validate_success(api.close_program_year(py["id"], admin_headers), 200)
        assert py["status"] == "CLOSED"

        res = api.report_program_year(py["id"], regulator_headers)
        validate_error(res, ApiErrorId.ERR_NO_EVALUATION_ADJUSTMENT, expected_status=422)

    def test_evaluation_adjustment_not_found_returns_404(self, api, regulator_headers):
        """PRD §2.9: "`ERR_INSPECTION_NOT_FOUND`, `ERR_LINE_ITEM_NOT_FOUND`,
        `ERR_SAVINGS_CLAIM_NOT_FOUND`, or `ERR_ADJUSTMENT_NOT_FOUND` (all HTTP
        404)."

        Design: Corner/entities/evaluation_adjustment_not_found_returns_404
        """
        res = api.get_evaluation_adjustment(NON_EXISTENT_UUID, regulator_headers)
        validate_error(res, ApiErrorId.ERR_ADJUSTMENT_NOT_FOUND, expected_status=404)


class TestEvaluationAdjustedKwh:
    def test_adjustment_diverges_adjusted_from_reported(self, api, regulator_headers):
        """PRD §3.7: "With no adjustment at all, `adjusted_kwh` simply equals
        `reported_kwh`; otherwise `adjusted_kwh` is `reported_kwh` multiplied by
        the latest adjustment's `realization_rate_pct`, divided by one hundred,
        and rounded down to a whole kilowatt-hour."
        PRD §3.7: "Creating an adjustment triggers this recomputation
        immediately — and a newly created row governs only if its `effective_on`
        makes it the latest under the rule above."

        Design: Difficulty/dual_variant_calc/evaluation_adjusted_vs_unadjusted_on_program_year
        """
        # One deemed application (400 * 5 = 2000 kWh) verified, approved, and
        # auto-paid at close; reported_kwh == 2000.
        py, measures, ally, app, line = build_closed_program_with_paid_app(
            measure_specs=[{"base_rate_cents": 10_000, "deemed_kwh_per_unit": 400}],
            quantity=5,
        )
        assert py["status"] == "CLOSED"
        assert py["reported_kwh"] == 2_000

        res = api.create_evaluation_adjustment(
            create_evaluation_adjustment_payload(
                py["id"], realization_rate_pct=80, effective_on="2026-08-13"
            ),
            regulator_headers,
        )
        validate_success(res, 201)

        py_after = get_program_year(py["id"])
        assert py_after["reported_kwh"] == 2_000
        # floor(2000 * 80 / 100) == 1600.
        assert py_after["adjusted_kwh"] == 1_600
        assert py_after["adjusted_kwh"] != py_after["reported_kwh"]

    def test_without_adjustment_adjusted_equals_reported(self, api, admin_headers):
        """PRD §3.7: "With no adjustment at all, `adjusted_kwh` simply equals
        `reported_kwh`; otherwise `adjusted_kwh` is `reported_kwh` multiplied by
        the latest adjustment's `realization_rate_pct`, divided by one hundred,
        and rounded down to a whole kilowatt-hour."

        Design: Difficulty/dual_variant_calc/evaluation_adjusted_vs_unadjusted_on_program_year
        """
        py, measures, ally, app, line = build_closed_program_with_paid_app(
            measure_specs=[{"base_rate_cents": 10_000, "deemed_kwh_per_unit": 400}],
            quantity=5,
        )
        assert py["reported_kwh"] == 2_000
        assert py["adjusted_kwh"] == 2_000
        assert py["adjusted_kwh"] == py["reported_kwh"]

    def test_latest_effective_on_governs(self, api, regulator_headers):
        """PRD §3.7: "The year's evaluated savings derive from the *latest*
        adjustment: the one with the greatest `effective_on`, with ties on
        `effective_on` broken in favor of the earliest-created row."
        PRD §3.7: "Creating an adjustment triggers this recomputation
        immediately — and a newly created row governs only if its `effective_on`
        makes it the latest under the rule above."

        Design: Difficulty/dual_variant_calc/evaluation_adjusted_vs_unadjusted_on_program_year
        """
        py, measures, ally, app, line = build_closed_program_with_paid_app(
            measure_specs=[{"base_rate_cents": 10_000, "deemed_kwh_per_unit": 400}],
            quantity=5,
        )
        # Newest adjustment: 80% -> adjusted 1600.
        validate_success(
            api.create_evaluation_adjustment(
                create_evaluation_adjustment_payload(
                    py["id"], realization_rate_pct=80, effective_on="2026-08-13"
                ),
                regulator_headers,
            ),
            201,
        )
        # An older-dated adjustment (50%) does not govern.
        validate_success(
            api.create_evaluation_adjustment(
                create_evaluation_adjustment_payload(
                    py["id"], realization_rate_pct=50, effective_on="2026-08-01"
                ),
                regulator_headers,
            ),
            201,
        )
        py_after = get_program_year(py["id"])
        assert py_after["adjusted_kwh"] == 1_600

        # A tie on effective_on: the earliest-created row wins, so a second
        # same-date 50% row must not displace the 80% row.
        validate_success(
            api.create_evaluation_adjustment(
                create_evaluation_adjustment_payload(
                    py["id"], realization_rate_pct=50, effective_on="2026-08-13"
                ),
                regulator_headers,
            ),
            201,
        )
        py_final = get_program_year(py["id"])
        assert py_final["adjusted_kwh"] == 1_600
