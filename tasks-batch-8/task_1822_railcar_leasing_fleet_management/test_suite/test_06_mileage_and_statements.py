"""Mileage reporting and car-hire statements: conservation, provisional vs
final pricing variants, dispute loop, finalize/settle gates, tier boundary,
credit cap."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_active_lease,
    create_assignment,
    create_lessee,
    create_railcar,
    create_tariff,
    deliver_assignment,
    generate_statements,
    get_lessee_balance,
    get_railcar,
    get_statement,
    get_success_data,
    make_lessee_rep_headers,
    set_clock,
    setup_active_lease_scenario,
    setup_provisional_statement,
    submit_mileage_report,
    validate_error,
    validate_report,
    validate_success,
)

LEASE_ADMIN = TEST_USERS["lease_admin_headers"]
PLANNER = TEST_USERS["fleet_planner_headers"]
BILLING = TEST_USERS["billing_analyst_headers"]


def _setup_dual_variant(api):
    """Tariffs start at 9000/55 (pinned at assignment creation) and are
    amended to 10000/60 before the August report; the report is validated
    with corrected miles 950/200."""
    hire = create_tariff("COVERED_HOPPER", "CAR_HIRE_BASE", 9000)
    mileage = create_tariff("COVERED_HOPPER", "MILEAGE_CREDIT", 55)
    lessee = create_lessee(company_name="Acme Grain Co",
                           credit_limit_cents=100000000)
    car = create_railcar(car_mark="GATX2001", built_year=2015)
    lease = create_active_lease(
        lessee["id"], lease_type="FULL_SERVICE", base_daily_rate_cents=5000,
        car_hire_lessor_share_pct=100, authorized_repair_cap_cents=20000,
        start_date="2026-08-01", end_date="2027-07-31",
    )
    assignment = create_assignment(
        lease["id"], car["id"], planned_commodity="GRAIN",
        scheduled_start="2026-08-01", scheduled_end="2027-06-30",
    )
    deliver_assignment(assignment["id"])
    # Amend the live grid AFTER the assignment pinned its snapshot.
    get_success_data(
        api.amend_tariff_rate(
            hire["id"],
            {"unit_rate_cents": 10000,
             "expected_tariff_version": hire["version"]},
            LEASE_ADMIN,
        )
    )
    get_success_data(
        api.amend_tariff_rate(
            mileage["id"],
            {"unit_rate_cents": 60,
             "expected_tariff_version": mileage["version"]},
            LEASE_ADMIN,
        )
    )
    report = submit_mileage_report(car["id"], assignment["id"], lessee["id"],
                                   "2026-08", 1000, 200)
    statement = generate_statements("2026-08")[0]
    report = validate_report(report["id"], validated_loaded_miles=950,
                             validated_empty_miles=200)
    return {"lessee": lessee, "railcar": car, "lease": lease,
            "assignment": assignment, "report": report,
            "statement": statement}


class TestProvisionalVsFinalVariants:
    def test_provisional_reprices_on_current_tariff_after_validation(self, api):
        """PRD §3.7: "The **provisional** variant — used at generation, at
        validation-triggered recompute, and at dispute recompute — prices the
        daily rate and the mileage credit rate off the tariffs effective on
        the first day of the statement month at compute time (`tariff_source`
        `CURRENT`), and takes its loaded miles from the latest reported
        figures (the validated loaded miles once the report is `VALIDATED`)."
        PRD §3.5: "every `PROVISIONAL` car-hire statement for the report's
        `(lease_assignment_id, report_month)` is recomputed under the
        provisional variant using the now-validated miles (§3.7)."

        Design: Difficulty/dual_variant_calc/car_hire_provisional_current_vs_final_pinned
        """
        env = _setup_dual_variant(api)
        stmt = get_statement(env["statement"]["id"])
        # Current tariff 10000/day x 31 days, validated 950 miles x 60.
        assert stmt["gross_car_hire_cents"] == 310000
        assert stmt["mileage_credit_cents"] == 57000
        assert stmt["provisional_net_cents"] == 253000
        assert stmt["tariff_source"] == "CURRENT"
        assert stmt["loaded_miles_used"] == 950
        assert stmt["status"] == "PROVISIONAL"

    def test_finalize_reprices_on_pinned_tariff_and_bills_lessee(self, api):
        """PRD §3.7: "The **final** variant — used only at finalize — prices
        off the assignment's `pinned_car_hire_daily_cents` and
        `pinned_mileage_credit_cents` snapshotted at creation
        (`tariff_source` `PINNED`), takes its loaded miles from
        `validated_loaded_miles`, rewrites the same measured fields, and
        writes `final_net_cents`."
        PRD §3.7: "Finalize (`PROVISIONAL → FINALIZED`) requires the month's
        mileage report to exist and be `VALIDATED` ... runs the final
        variant, then adds `final_net_cents` to the lessee's
        `outstanding_balance_cents` and re-evaluates auto-suspension."

        Design: Difficulty/dual_variant_calc/car_hire_provisional_current_vs_final_pinned
        """
        env = _setup_dual_variant(api)
        finalized = validate_success(
            api.finalize_statement(env["statement"]["id"], BILLING)
        )
        # Pinned 9000/day x 31 = 279000 gross; 950 x 55 = 52250 credit.
        assert finalized["gross_car_hire_cents"] == 279000
        assert finalized["mileage_credit_cents"] == 52250
        assert finalized["final_net_cents"] == 226750
        assert finalized["tariff_source"] == "PINNED"
        assert finalized["loaded_miles_used"] == 950
        assert finalized["provisional_net_cents"] == 253000, (
            "The final variant writes final_net_cents and rewrites the "
            "measured fields; the last provisional figure stays distinct"
        )
        assert finalized["final_net_cents"] != finalized["provisional_net_cents"]
        assert get_lessee_balance(env["lessee"]["id"]) == 226750


class TestMileageConservation:
    def test_first_validation_adds_validated_miles(self, api):
        """PRD §3.8: "The car's `cumulative_miles` is defined as the exact
        sum, over all of the car's mileage reports in `VALIDATED` or
        `DISPUTED` status, of validated loaded miles plus validated empty
        miles."
        PRD §3.5: "The analyst may supply corrected `validated_loaded_miles`
        and `validated_empty_miles`; where either is omitted, the reported
        value stands."

        Design: Difficulty/compensating_invariant/miles_revalidation_delta_conservation
        """
        scenario = setup_active_lease_scenario(car_mark="GATX9402",
                                               deliver=True)
        report = submit_mileage_report(
            scenario["railcar"]["id"], scenario["assignment"]["id"],
            scenario["lessee"]["id"], "2026-08", 1000, 200,
        )
        validate_report(report["id"])
        car = get_railcar(scenario["railcar"]["id"])
        assert car["cumulative_miles"] == 1200

    def test_revalidation_applies_only_the_delta(self, api):
        """PRD §3.8: "Revalidation after a resubmit therefore contributes
        only the delta between the new validated total and the previously
        counted validated total — never the full new amount on top of the
        old."
        PRD §3.8: "The conservation invariant the system maintains: a
        validate → dispute → resubmit → validate round trip leaves
        `cumulative_miles` equal to the sum over the current validated
        values, with no double counting."

        Design: Difficulty/compensating_invariant/miles_revalidation_delta_conservation
        """
        scenario = setup_active_lease_scenario(car_mark="GATX9402",
                                               deliver=True)
        lessee = scenario["lessee"]
        report = submit_mileage_report(
            scenario["railcar"]["id"], scenario["assignment"]["id"],
            lessee["id"], "2026-08", 1000, 200,
        )
        validate_report(report["id"])
        get_success_data(
            api.dispute_mileage_report(report["id"], {"reason": "odometer audit"},
                                       BILLING)
        )
        get_success_data(
            api.resubmit_mileage_report(
                report["id"], {"loaded_miles": 950, "empty_miles": 200},
                make_lessee_rep_headers(lessee["id"]),
            )
        )
        revalidated = validate_report(report["id"])
        assert revalidated["status"] == "VALIDATED"
        assert revalidated["validated_loaded_miles"] == 950
        car = get_railcar(scenario["railcar"]["id"])
        assert car["cumulative_miles"] == 1150, (
            "Delta 1150 - 1200 = -50 applied exactly once; double counting "
            "would read 2350"
        )


class TestStatementDisputeCycle:
    def _setup(self, api):
        return setup_provisional_statement(
            car_mark="GATX7003", credit_limit_cents=10000000,
        )

    def test_dispute_and_recompute_leave_balance_untouched(self, api):
        """PRD §3.7: "A `LesseeRep` whose `X-User-ID` equals the statement's
        `lessee_id` may dispute a provisional statement (`PROVISIONAL →
        DISPUTED`) with a mandatory `dispute_reason`; a representative of any
        other lessee is refused with `ERR_FORBIDDEN_ROLE` (403). A
        `BillingAnalyst` recomputes a disputed statement (`DISPUTED →
        PROVISIONAL`) under the provisional variant against the latest
        miles."
        PRD §3.1: the balance "rises when a car-hire statement is finalized,
        when a shop repair completes with a positive lessee share on an
        assignment-linked repair" — the dispute loop runs entirely before
        finalize.

        Design: Difficulty/non_linear_state_machine/statement_dispute_recompute_cycle
        """
        env = self._setup(api)
        stmt = env["statement"]
        lessee = env["lessee"]
        disputed = validate_success(
            api.dispute_statement(stmt["id"], "mileage mismatch claim",
                                  make_lessee_rep_headers(lessee["id"]))
        )
        assert disputed["status"] == "DISPUTED"
        assert get_lessee_balance(lessee["id"]) == 0, (
            "No balance movement during the dispute loop"
        )
        recomputed = validate_success(api.recompute_statement(stmt["id"], BILLING))
        assert recomputed["status"] == "PROVISIONAL"
        assert recomputed["provisional_net_cents"] == 224000, (
            "279000 gross - 1000 x 55 credit, unchanged inputs"
        )
        assert get_lessee_balance(lessee["id"]) == 0

    def test_finalize_after_recompute_bills_final_net(self, api):
        """PRD §3.7: "Finalize (`PROVISIONAL → FINALIZED`) requires the
        month's mileage report to exist and be `VALIDATED`
        (`ERR_REPORT_NOT_VALIDATED`, 409; the state gate itself carries
        `ERR_STATEMENT_NOT_PROVISIONAL`, 409), runs the final variant, then
        adds `final_net_cents` to the lessee's `outstanding_balance_cents`
        and re-evaluates auto-suspension."

        Design: Difficulty/non_linear_state_machine/statement_dispute_recompute_cycle
        """
        env = self._setup(api)
        stmt = env["statement"]
        lessee = env["lessee"]
        get_success_data(
            api.dispute_statement(stmt["id"], "mileage mismatch claim",
                                  make_lessee_rep_headers(lessee["id"]))
        )
        get_success_data(api.recompute_statement(stmt["id"], BILLING))
        finalized = validate_success(api.finalize_statement(stmt["id"], BILLING))
        assert finalized["status"] == "FINALIZED"
        # Pinned rates equal current rates here (9000/55), so final matches
        # the last provisional: 279000 - 1000 x 55 = 224000.
        assert finalized["final_net_cents"] == 224000
        assert get_lessee_balance(lessee["id"]) == 224000


class TestFinalizeSuspensionCascade:
    def _setup(self, api):
        return setup_provisional_statement(
            car_mark="GATX8002", credit_limit_cents=200000, credit_tier="TIER_C",
        )

    def test_finalize_debits_lessee_balance(self, api):
        """PRD §3.7: "Finalize (`PROVISIONAL → FINALIZED`) ... runs the final
        variant, then adds `final_net_cents` to the lessee's
        `outstanding_balance_cents` and re-evaluates auto-suspension."

        Design: Difficulty/transitive_cascade/statement_finalize_three_hop_suspension_cascade
        """
        env = self._setup(api)
        finalized = validate_success(
            api.finalize_statement(env["statement"]["id"], BILLING)
        )
        assert finalized["status"] == "FINALIZED"
        assert finalized["final_net_cents"] == 224000
        assert get_lessee_balance(env["lessee"]["id"]) == 224000

    def test_balance_over_credit_limit_auto_suspends(self, api):
        """PRD §3.1: "After any mutation of `outstanding_balance_cents`, the
        system re-evaluates the credit rule: if the balance now exceeds the
        lessee's `credit_limit_cents`, the lessee is automatically
        transitioned from `ACTIVE` to `SUSPENDED`, and while suspended, new
        lease submissions and new assignment creations for that lessee are
        blocked (surfacing `ERR_LESSEE_NOT_ACTIVE` per §2.7)."

        Design: Difficulty/transitive_cascade/statement_finalize_three_hop_suspension_cascade
        """
        env = self._setup(api)
        get_success_data(api.finalize_statement(env["statement"]["id"], BILLING))
        lessee = get_success_data(api.get_lessee(env["lessee"]["id"], BILLING))
        assert lessee["outstanding_balance_cents"] == 224000
        assert lessee["status"] == "SUSPENDED", (
            "224000 exceeds the 200000 credit limit, so the balance mutation "
            "fired by finalize must suspend the lessee"
        )


class TestFinalizeSettleRoundTrip:
    def _setup(self, api):
        return setup_provisional_statement(
            car_mark="GATX9401", credit_limit_cents=10000000,
        )

    def test_finalize_adds_final_net_to_balance(self, api):
        """PRD §3.7: "Finalize (`PROVISIONAL → FINALIZED`) ... runs the final
        variant, then adds `final_net_cents` to the lessee's
        `outstanding_balance_cents` and re-evaluates auto-suspension."

        Design: Difficulty/compensating_invariant/lessee_balance_finalize_settle_round_trip
        """
        env = self._setup(api)
        assert get_lessee_balance(env["lessee"]["id"]) == 0
        get_success_data(api.finalize_statement(env["statement"]["id"], BILLING))
        assert get_lessee_balance(env["lessee"]["id"]) == 224000

    def test_settle_subtracts_payment_and_restores_balance(self, api):
        """PRD §3.7: "Settlement (`FINALIZED → SETTLED`) records an exact
        payment: `amount_cents` must equal `final_net_cents` to the cent
        (`ERR_PAYMENT_MISMATCH`, 422), and the paid amount is subtracted from
        the lessee's balance with auto-suspension re-evaluated. `SETTLED` is
        terminal."

        Design: Difficulty/compensating_invariant/lessee_balance_finalize_settle_round_trip
        """
        env = self._setup(api)
        get_success_data(api.finalize_statement(env["statement"]["id"], BILLING))
        settled = validate_success(
            api.settle_statement(env["statement"]["id"], 224000, BILLING)
        )
        assert settled["status"] == "SETTLED"
        assert get_lessee_balance(env["lessee"]["id"]) == 0, (
            "finalize(+224000)/settle(224000) returns the balance exactly to "
            "its pre-finalize value"
        )
        lessee = get_success_data(api.get_lessee(env["lessee"]["id"], BILLING))
        assert lessee["status"] == "ACTIVE", (
            "224000 <= 10000000, so no suspension fired at any point"
        )


class TestMileageTierBoundary:
    def _setup(self, api):
        """July 119000 + August 1000 validated miles land the lease-year
        accumulation exactly on 120000; September adds the 120001st mile."""
        set_clock("2026-07-01T00:00:00Z")
        scenario = setup_active_lease_scenario(
            car_mark="GATX9103", lease_start="2026-07-01",
            lease_end="2027-06-30", window_start="2026-07-01",
            window_end="2026-12-31", deliver=True,
        )
        lessee = scenario["lessee"]
        car = scenario["railcar"]
        asg = scenario["assignment"]
        for month, loaded in (("2026-07", 119000), ("2026-08", 1000),
                              ("2026-09", 1)):
            report = submit_mileage_report(car["id"], asg["id"], lessee["id"],
                                           month, loaded, 0)
            validate_report(report["id"])
        return scenario

    def test_cumulative_miles_exactly_at_threshold_have_no_excess(self, api):
        """PRD §3.7: "The full-rate miles are the lesser of the loaded miles
        used and the remaining room under the 120,000-mile high-mileage
        threshold (that is, the threshold minus the prior accumulation,
        floored at zero); the excess miles are the remainder of the loaded
        miles used above that full-rate portion. When the prior accumulation
        plus the current miles lands exactly on 120,000, the excess is zero —
        the threshold reads as miles strictly beyond 120,000."

        Design: Difficulty/boundary_precision_check/mileage_tier_exact_threshold_vs_beyond
        """
        self._setup(api)
        stmt = generate_statements("2026-08")[0]
        # Cumulative lands exactly on 120000: all 1000 miles earn full rate.
        assert stmt["tier_excess_miles"] == 0
        assert stmt["mileage_credit_cents"] == 55000
        assert stmt["days_on_lease"] == 31
        assert stmt["provisional_net_cents"] == 224000

    def test_first_mile_beyond_threshold_prices_at_excess_rate(self, api):
        """PRD §3.7: "The uncapped credit is the full-rate miles multiplied
        by the mileage credit rate, plus the excess miles multiplied by the
        rate and by 80 percent, the excess term divided by 100 and rounded
        half-up to a whole cent. The excess miles figure is persisted on the
        statement as `tier_excess_miles`."

        Design: Difficulty/boundary_precision_check/mileage_tier_exact_threshold_vs_beyond
        """
        self._setup(api)
        generate_statements("2026-08")
        stmt = generate_statements("2026-09")[0]
        # The 120001st mile: 0 full-rate miles, 1 excess mile at 55 x 80%.
        assert stmt["tier_excess_miles"] == 1
        assert stmt["mileage_credit_cents"] == 44
        assert stmt["days_on_lease"] == 30
        assert stmt["provisional_net_cents"] == 269956


class TestCreditComputation:
    def test_mileage_credit_capped_at_eighty_pct_of_gross(self, api):
        """PRD §3.7: "The credit is then capped: the cap is the gross car
        hire multiplied by 80 percent and divided by 100, rounded half-up,
        and the credited amount (`mileage_credit_cents`) is the lesser of the
        uncapped credit and the cap."

        Design: Corner/calculations/mileage_credit_capped_at_eighty_pct_of_gross
        """
        env = setup_provisional_statement(
            car_mark="GATX1303", loaded_miles=5000, empty_miles=0,
        )
        stmt = env["statement"]
        # Raw credit 5000 x 55 = 275000 exceeds the cap
        # round(279000 x 0.8) = 223200, so the cap binds.
        assert stmt["mileage_credit_cents"] == 223200
        assert stmt["provisional_net_cents"] == 55800

    def test_empty_miles_earn_zero_credit(self, api):
        """PRD §3.7: "The mileage credit uses only loaded miles — empty miles
        never earn credit."

        Design: Corner/calculations/empty_miles_earn_zero_credit
        """
        env = setup_provisional_statement(
            car_mark="GATX1304", loaded_miles=0, empty_miles=500,
        )
        stmt = env["statement"]
        assert stmt["mileage_credit_cents"] == 0
        assert stmt["tier_excess_miles"] == 0
        assert stmt["provisional_net_cents"] == 279000


class TestMileageReportGates:
    def test_report_month_outside_on_lease_window_rejected(self, api):
        """PRD §3.5: "The report must name a month in which the assignment
        was actually on lease (`ERR_REPORT_MONTH_MISMATCH`, 422)".

        Design: Corner/validations/report_month_outside_on_lease_window_rejected
        """
        scenario = setup_active_lease_scenario(car_mark="GATX1404",
                                               deliver=True)
        resp = api.create_mileage_report(
            {
                "railcar_id": scenario["railcar"]["id"],
                "lease_assignment_id": scenario["assignment"]["id"],
                "report_month": "2026-07",
                "loaded_miles": 100,
                "empty_miles": 0,
            },
            make_lessee_rep_headers(scenario["lessee"]["id"]),
        )
        # Delivered 2026-08-01: 2026-07 is not an on-lease month.
        validate_error(resp, ApiErrorId.ERR_REPORT_MONTH_MISMATCH, 422)

    def test_duplicate_report_month_rejected(self, api):
        """PRD §3.5: "only one non-`DISPUTED` report may exist per car per
        month: submitting a report for a `(railcar_id, report_month)` pair
        that already has a report in any status other than `DISPUTED` fails
        with `ERR_DUPLICATE_REPORT_MONTH` (409) — a `DISPUTED` report is
        considered superseded by its resubmission and does not block the
        pair."

        Design: Corner/validations/duplicate_report_month_rejected
        """
        scenario = setup_active_lease_scenario(car_mark="GATX1405",
                                               deliver=True)
        lessee_id = scenario["lessee"]["id"]
        first = submit_mileage_report(
            scenario["railcar"]["id"], scenario["assignment"]["id"],
            lessee_id, "2026-08", 100, 0,
        )
        resp = api.create_mileage_report(
            {
                "railcar_id": scenario["railcar"]["id"],
                "lease_assignment_id": scenario["assignment"]["id"],
                "report_month": "2026-08",
                "loaded_miles": 200,
                "empty_miles": 0,
            },
            make_lessee_rep_headers(lessee_id),
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_REPORT_MONTH, 409)
        after = get_success_data(api.get_mileage_report(first["id"], BILLING))
        assert after["loaded_miles"] == 100, "The first report is untouched"


class TestStatementFinalizeGate:
    def test_finalize_without_validated_report_rejected(self, api):
        """PRD §3.7: "Finalize (`PROVISIONAL → FINALIZED`) requires the
        month's mileage report to exist and be `VALIDATED`
        (`ERR_REPORT_NOT_VALIDATED`, 409; the state gate itself carries
        `ERR_STATEMENT_NOT_PROVISIONAL`, 409)".

        Design: Corner/validations/finalize_without_validated_report_rejected
        """
        env = setup_provisional_statement(
            car_mark="GATX1410", loaded_miles=100, empty_miles=0,
            validate=False,
        )
        stmt = env["statement"]
        resp = api.finalize_statement(stmt["id"], BILLING)
        validate_error(resp, ApiErrorId.ERR_REPORT_NOT_VALIDATED, 409)
        after = get_statement(stmt["id"])
        assert after["status"] == "PROVISIONAL"

    def test_statement_settle_amount_mismatch_rejected(self, api):
        """PRD §3.7: "Settlement (`FINALIZED → SETTLED`) records an exact
        payment: `amount_cents` must equal `final_net_cents` to the cent
        (`ERR_PAYMENT_MISMATCH`, 422), and the paid amount is subtracted from
        the lessee's balance with auto-suspension re-evaluated."

        Design: Corner/state_machines/statement_settle_amount_mismatch_rejected
        """
        env = setup_provisional_statement(
            car_mark="GATX1207", credit_limit_cents=10000000,
        )
        stmt = env["statement"]
        get_success_data(api.finalize_statement(stmt["id"], BILLING))
        resp = api.settle_statement(stmt["id"], 223999, BILLING)
        validate_error(resp, ApiErrorId.ERR_PAYMENT_MISMATCH, 422)
        after = get_statement(stmt["id"])
        assert after["status"] == "FINALIZED"
        assert get_lessee_balance(env["lessee"]["id"]) == 224000, (
            "A rejected payment must not move the balance"
        )


class TestStatementGeneration:
    def test_generate_is_idempotent_per_assignment_month(self, api):
        """PRD §3.7: "the system produces one `PROVISIONAL` statement per
        assignment that was on lease at any point in that month — assignments
        in `ON_LEASE`, `RETURNED`, or `SETTLED` overlapping the month —
        walking assignments in `created_at` ascending order, and skipping any
        `(lease_assignment_id, statement_month)` pair that already has a
        statement."

        Design: Corner/endpoints/generate_is_idempotent_per_assignment_month
        """
        env = setup_provisional_statement(
            car_mark="GATX1503", credit_limit_cents=10000000,
        )
        stmt = env["statement"]
        second = get_success_data(
            api.generate_car_hire_statements("2026-08", BILLING)
        )
        assert second == [], (
            "The existing (assignment, month) pair is skipped: an empty "
            "array comes back"
        )
        after = get_statement(stmt["id"])
        assert after["provisional_net_cents"] == 224000
        assert after["version"] == stmt["version"], (
            "A skipped statement is not mutated at all"
        )
