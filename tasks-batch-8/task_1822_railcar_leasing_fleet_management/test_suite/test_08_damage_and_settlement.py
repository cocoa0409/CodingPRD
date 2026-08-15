"""Damage assessments (per-line rounding, betterment) and assignment
settlement (gates, pinned proration order)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    approve_repair,
    close_open_damage_assessments,
    create_damage_assessment,
    create_repair,
    damage_line_item,
    deliver_assignment,
    finalize_assessment,
    get_assignment,
    get_lessee_balance,
    get_success_data,
    return_assignment,
    set_clock,
    setup_active_lease_scenario,
    submit_assessment,
    validate_error,
    validate_success,
)

PLANNER = TEST_USERS["fleet_planner_headers"]
MAINT = TEST_USERS["maintenance_controller_headers"]
BILLING = TEST_USERS["billing_analyst_headers"]


class TestDamageBillingSchedule:
    def test_damage_totals_sum_per_line_rounded_costs(self, api):
        """PRD §3.10: "For each line: the raw line cost is `parts_cents` plus
        `labor_hours` multiplied by a labor rate of 14,500 cents per hour and
        by the severity multiplier (1.00 for `MINOR`, 1.25 for `MODERATE`,
        1.50 for `SEVERE`), and that raw cost is rounded half-up to a whole
        cent, giving the line cost." and "`total_assessed_cents` is the sum
        of the per-line rounded costs".

        Design: Difficulty/combinatorial_formula/damage_billing_per_line_rounding_order
        """
        scenario = setup_active_lease_scenario(
            car_mark="GATX5001", built_year=1991, window_start="2026-08-01",
            window_end="2026-12-31",
        )
        assessment = create_damage_assessment(
            scenario["assignment"]["id"], scenario["railcar"]["id"]
        )
        submit_assessment(
            assessment["id"],
            [
                damage_line_item(component="WHEEL_SET", severity="MODERATE",
                                 cause="LESSEE_DAMAGE", parts_cents=50000,
                                 labor_hours=2.0, replaced=True),
                damage_line_item(component="BRAKE_BEAM", severity="MINOR",
                                 cause="LESSEE_DAMAGE", parts_cents=9999,
                                 labor_hours=0.5, replaced=True),
                damage_line_item(component="COUPLER_LUBRICATION",
                                 severity="MINOR", cause="WEAR_AND_TEAR",
                                 parts_cents=4000, labor_hours=0.25,
                                 replaced=False),
            ],
        )
        finalized = validate_success(
            api.finalize_damage_assessment(assessment["id"], MAINT)
        )
        # Per-line costs: 86250 + 17249 + 7625.
        assert finalized["total_assessed_cents"] == 111124

    def test_lessee_liable_uses_per_line_betterment_rounding(self, api):
        """PRD §3.10: "if the cause is `LESSEE_DAMAGE`, the line's `replaced`
        flag is true, and the car's `car_age_years` is at least 30, a
        betterment reduction applies — the lessee pays 75 percent of the line
        cost (that is, 100 minus the 25 percent betterment), rounded half-up
        to a whole cent." and "whose rounding order is pinned per line, then
        summed — summing raw values first and rounding once is explicitly
        wrong."

        Design: Difficulty/combinatorial_formula/damage_billing_per_line_rounding_order
        """
        scenario = setup_active_lease_scenario(
            car_mark="GATX5001", built_year=1991, window_start="2026-08-01",
            window_end="2026-12-31",
        )
        assessment = create_damage_assessment(
            scenario["assignment"]["id"], scenario["railcar"]["id"]
        )
        submit_assessment(
            assessment["id"],
            [
                damage_line_item(component="WHEEL_SET", severity="MODERATE",
                                 cause="LESSEE_DAMAGE", parts_cents=50000,
                                 labor_hours=2.0, replaced=True),
                damage_line_item(component="BRAKE_BEAM", severity="MINOR",
                                 cause="LESSEE_DAMAGE", parts_cents=9999,
                                 labor_hours=0.5, replaced=True),
                damage_line_item(component="COUPLER_LUBRICATION",
                                 severity="MINOR", cause="WEAR_AND_TEAR",
                                 parts_cents=4000, labor_hours=0.25,
                                 replaced=False),
            ],
        )
        finalized = validate_success(
            api.finalize_damage_assessment(assessment["id"], MAINT)
        )
        # Car age 2026 - 1991 = 35 >= 30: per-line betterment rounding gives
        # round(86250 x 0.75) = 64688 and round(17249 x 0.75) = 12937.
        assert finalized["lessee_liable_cents"] == 77625
        assert finalized["lessee_liable_cents"] != 77624, (
            "77624 is the forbidden sum-then-round result"
        )

    def test_betterment_waived_below_age_30(self, api):
        """PRD §3.10: "if the cause is `LESSEE_DAMAGE`, the line's `replaced`
        flag is true, and the car's `car_age_years` is at least 30, a
        betterment reduction applies — the lessee pays 75 percent of the line
        cost (that is, 100 minus the 25 percent betterment), rounded half-up
        to a whole cent. If the cause is `LESSEE_DAMAGE` without the
        betterment conditions, the lessee pays the full line cost."

        Design: Corner/calculations/betterment_waived_below_age_30
        """
        scenario = setup_active_lease_scenario(
            car_mark="GATX1305", built_year=2010, window_start="2026-08-01",
            window_end="2026-12-31",
        )
        assessment = create_damage_assessment(
            scenario["assignment"]["id"], scenario["railcar"]["id"]
        )
        submit_assessment(
            assessment["id"],
            [
                damage_line_item(component="DOOR_PANEL", severity="MODERATE",
                                 cause="LESSEE_DAMAGE", parts_cents=10000,
                                 labor_hours=1.0, replaced=True),
            ],
        )
        finalized = validate_success(
            api.finalize_damage_assessment(assessment["id"], MAINT)
        )
        # 10000 + 1.0 x 14500 x 1.25 = 28125; car age 16 < 30, no betterment.
        assert finalized["total_assessed_cents"] == 28125
        assert finalized["lessee_liable_cents"] == 28125


class TestSettleDamageGate:
    def _setup_returned_with_submitted_assessment(self, api):
        scenario = setup_active_lease_scenario(
            car_mark="GATX9202", window_start="2026-08-01",
            window_end="2026-08-31", deliver=True,
        )
        set_clock("2026-08-21T00:00:00Z")
        return_assignment(scenario["assignment"]["id"])
        assessment = create_damage_assessment(
            scenario["assignment"]["id"], scenario["railcar"]["id"]
        )
        submit_assessment(
            assessment["id"],
            [
                damage_line_item(component="LADDER", severity="MINOR",
                                 cause="LESSEE_DAMAGE", parts_cents=6000,
                                 labor_hours=0.5, replaced=False),
            ],
        )
        return scenario, assessment

    def test_settle_rejected_while_assessment_submitted(self, api):
        """PRD §2.7: "Settling an assignment requires ... every damage
        assessment on the assignment in `FINALIZED`, `INVOICED`, or `PAID`
        (`ERR_DAMAGE_ASSESSMENT_OPEN`)."

        Design: Difficulty/cross_entity_state_dependency/settle_blocked_until_damage_finalized
        """
        scenario, _assessment = self._setup_returned_with_submitted_assessment(api)
        resp = api.settle_assignment(scenario["assignment"]["id"], BILLING)
        validate_error(resp, ApiErrorId.ERR_DAMAGE_ASSESSMENT_OPEN, 409)
        after = get_assignment(scenario["assignment"]["id"])
        assert after["status"] == "RETURNED"

    def test_settle_succeeds_after_assessment_finalized(self, api):
        """PRD §3.6: "3. Raw days are the calendar-day difference from
        `actual_on_lease_date` (inclusive) to `actual_off_lease_date`
        (exclusive). 4. `billable_days` is raw days minus excluded days. 5.
        `final_rent_cents` is `billable_days` multiplied by the lease's
        `base_daily_rate_cents` — the first and only multiplication in this
        calculation, exact integer arithmetic with no rounding."
        PRD §3.10: "`total_assessed_cents` is the sum of the per-line rounded
        costs; `lessee_liable_cents` is the sum of the per-line rounded
        lessee amounts."

        Design: Difficulty/cross_entity_state_dependency/settle_blocked_until_damage_finalized
        """
        scenario, assessment = self._setup_returned_with_submitted_assessment(api)
        finalized = finalize_assessment(assessment["id"])
        # 6000 + 0.5 x 14500 = 13250; car age 11 < 30 so no betterment.
        assert finalized["lessee_liable_cents"] == 13250
        # Close the cascade-created DRAFT assessment (§3.4) as well.
        close_open_damage_assessments(scenario["assignment"]["id"])
        settled = validate_success(
            api.settle_assignment(scenario["assignment"]["id"], BILLING)
        )
        assert settled["status"] == "SETTLED"
        # 20 raw days (08-01 .. 08-21 exclusive), no shop exclusions.
        assert settled["billable_days"] == 20
        assert settled["final_rent_cents"] == 100000


class TestSettlePriorityConflict:
    def _setup_on_lease_with_unpaid_invoice(self, api):
        scenario = setup_active_lease_scenario(
            car_mark="GATX9001", window_start="2026-08-01",
            window_end="2026-12-31", deliver=True,
        )
        assessment = create_damage_assessment(
            scenario["assignment"]["id"], scenario["railcar"]["id"]
        )
        submit_assessment(
            assessment["id"],
            [
                damage_line_item(component="GRAB_IRON", severity="MINOR",
                                 cause="LESSEE_DAMAGE", parts_cents=10000,
                                 labor_hours=0.5, replaced=False),
            ],
        )
        finalize_assessment(assessment["id"])
        get_success_data(api.invoice_damage_assessment(assessment["id"], BILLING))
        return scenario, assessment

    def test_settle_on_lease_assignment_returns_state_error(self, api):
        """PRD §2.6: "Because state legality (priority 6) precedes the fiscal
        gates (priority 12), a settle attempted on an assignment that is not
        `RETURNED` surfaces `ERR_ASSIGNMENT_NOT_RETURNED` rather than any
        balance-related error."

        Design: Difficulty/priority_pair_validation_conflict/settle_state_error_beats_fiscal_error
        """
        scenario, _assessment = self._setup_on_lease_with_unpaid_invoice(api)
        # An INVOICED-but-unpaid assessment exists (fiscal violation), and
        # the assignment is still ON_LEASE (state violation): the state
        # error must win.
        resp = api.settle_assignment(scenario["assignment"]["id"], BILLING)
        validate_error(resp, ApiErrorId.ERR_ASSIGNMENT_NOT_RETURNED, 409)

    def test_failed_settle_leaves_assignment_and_assessment_untouched(self, api):
        """PRD §2.6: "Because state legality (priority 6) precedes the fiscal
        gates (priority 12), a settle attempted on an assignment that is not
        `RETURNED` surfaces `ERR_ASSIGNMENT_NOT_RETURNED` rather than any
        balance-related error."

        Design: Difficulty/priority_pair_validation_conflict/settle_state_error_beats_fiscal_error
        """
        scenario, assessment = self._setup_on_lease_with_unpaid_invoice(api)
        resp = api.settle_assignment(scenario["assignment"]["id"], BILLING)
        validate_error(resp, ApiErrorId.ERR_ASSIGNMENT_NOT_RETURNED, 409)
        after_assignment = get_assignment(scenario["assignment"]["id"])
        assert after_assignment["status"] == "ON_LEASE"
        after_assessment = get_success_data(
            api.get_damage_assessment(assessment["id"], BILLING)
        )
        assert after_assessment["status"] == "INVOICED"
        # The invoice billed 10000 + 0.5 x 14500 = 17250 and nothing undid it.
        assert get_lessee_balance(scenario["lessee"]["id"]) == 17250


class TestSettleProrationOrder:
    def _setup(self, api):
        scenario = setup_active_lease_scenario(
            car_mark="GATX6001", repair_cap_cents=100000,
            window_start="2026-08-01", window_end="2026-08-31",
            deliver=True,
        )
        repair = create_repair(
            scenario["railcar"]["id"],
            assignment_id=scenario["assignment"]["id"],
            defect_cause="WEAR_AND_TEAR", estimate_cents=100000,
            requires_shop=True, defect_description="wheel wear",
        )
        approve_repair(repair["id"], 100000)
        set_clock("2026-08-05T00:00:00Z")
        get_success_data(api.start_repair_work(repair["id"], MAINT))
        set_clock("2026-08-09T00:00:00Z")
        get_success_data(api.complete_repair(repair["id"], 100000, MAINT))
        set_clock("2026-08-21T00:00:00Z")
        return_assignment(scenario["assignment"]["id"])
        close_open_damage_assessments(scenario["assignment"]["id"])
        return scenario

    def test_settle_excludes_lessor_responsible_shop_days(self, api):
        """PRD §3.6: "2. Excluded days accumulate across exactly those
        repairs whose `lessor_share_cents` is greater than zero: for each
        such repair, count the days from `shop_entry_date` (inclusive) to
        `completion_date` (exclusive), clipped to the on-lease window, and
        sum them. 3. Raw days are the calendar-day difference from
        `actual_on_lease_date` (inclusive) to `actual_off_lease_date`
        (exclusive). 4. `billable_days` is raw days minus excluded days. 5.
        `final_rent_cents` is `billable_days` multiplied by the lease's
        `base_daily_rate_cents` — the first and only multiplication in this
        calculation, exact integer arithmetic with no rounding. 6.
        `termination_fee_cents` attributed to this settlement equals the
        lease's `early_termination_fee_cents` when the lease is `TERMINATED`,
        and zero otherwise."

        Design: Difficulty/combinatorial_formula/settle_proration_pinned_evaluation_order
        """
        scenario = self._setup(api)
        settled = validate_success(
            api.settle_assignment(scenario["assignment"]["id"], BILLING)
        )
        # FULL_SERVICE + WEAR_AND_TEAR on 100000: lessor share 70000 > 0, so
        # the 4 shop days [08-05, 08-09) are excluded from the 20 raw days.
        assert settled["billable_days"] == 16
        assert settled["final_rent_cents"] == 80000, (
            "16 x 5000; a rent-first reading would bill 20 days (100000)"
        )
        assert settled["termination_fee_cents"] == 0, "The lease is ACTIVE"

    def test_settle_bills_rent_plus_completed_repair_share(self, api):
        """PRD §3.6: "The settle then bills the sum of `final_rent_cents` and
        `termination_fee_cents` onto the lessee's
        `outstanding_balance_cents` and re-evaluates auto-suspension."
        PRD §3.9: "if the repair is assignment-linked with a positive lessee
        share, that share is added to the lessee's
        `outstanding_balance_cents` with auto-suspension re-evaluated."

        Design: Difficulty/combinatorial_formula/settle_proration_pinned_evaluation_order
        """
        scenario = self._setup(api)
        # The completed repair already billed its 30000 lessee share.
        assert get_lessee_balance(scenario["lessee"]["id"]) == 30000
        validate_success(
            api.settle_assignment(scenario["assignment"]["id"], BILLING)
        )
        assert get_lessee_balance(scenario["lessee"]["id"]) == 110000, (
            "30000 repair share + 80000 rent"
        )
