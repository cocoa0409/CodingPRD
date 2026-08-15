"""Improvement goals, interim reports, and the renewal cascade (PRD §3.5, §3.7, §3.2)."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    LATE_REPORT_PENALTY_CENTS,
    api_client,
    create_annual_invoice,
    create_fee_schedule,
    create_goal_payload,
    create_indicator,
    create_interim_report_payload,
    create_standard,
    create_system,
    create_campus,
    create_term,
    get_success_data,
    set_clock,
    setup_accepted_interim_report,
    setup_adopted_goal,
    setup_self_study_term,
    setup_term_active,
    validate_error,
    validate_success,
)

OFFICER = TEST_USERS["officer_headers"]
LEADER = TEST_USERS["leader_headers"]
COMMISSION = TEST_USERS["commission_headers"]


class TestGoalCreationDefaults:
    def test_goal_created_with_computed_defaults(self, api):
        """PRD §3.5: "The new goal starts `PROPOSED`, with `current_value`
        initialized to `baseline_value` and `attainment_pct` at 0.00."

        Design: Corner/entities/computed_field_input_ignored
        """
        ctx = setup_self_study_term(system_name="Computed School", advance=False)
        payload = create_goal_payload(
            ctx["standards"][0]["id"], title="Raise proficiency",
            baseline_value=50, target_value=80, direction="INCREASE",
            campus_id=ctx["campuses"][0]["id"])
        # Client noise on server-computed fields must not take effect.
        payload["attainment_pct"] = 99.99
        payload["current_value"] = 999
        goal = validate_success(
            api_client.create_goal(ctx["term"]["id"], payload, LEADER),
            expected_status=201)
        assert goal["status"] == "PROPOSED"
        assert goal["attainment_pct"] == pytest.approx(0.00, abs=0.001)
        assert goal["current_value"] == pytest.approx(50, abs=0.001)

    def test_goal_with_campus_of_other_system_rejected(self, api):
        """PRD §3.5: "The named campus must belong to the same system as the
        term, else `ERR_REFERENTIAL_INTEGRITY`."

        Design: Corner/validations/cross_entity_validation_goal_campus_mismatch
        """
        standard = create_standard(code="L1", title="Leadership 1",
                                   domain="LEADERSHIP", weight_pct=100,
                                   evidence_min_items=0)
        system_1 = create_system(name="S1", system_type="DISTRICT")
        create_campus(system_1["id"], name="S1 Campus", enrollment=100)
        term_1 = create_term(system_1["id"])
        system_2 = create_system(name="S2", system_type="DISTRICT")
        campus_s2 = create_campus(system_2["id"], name="S2 Campus", enrollment=200)

        payload = create_goal_payload(
            standard["id"], title="Bad goal", baseline_value=1, target_value=2,
            direction="INCREASE", campus_id=campus_s2["id"])
        resp = api_client.create_goal(term_1["id"], payload, LEADER)
        validate_error(resp, ApiErrorId.ERR_REFERENTIAL_INTEGRITY)


class TestGoalAttainment:
    def test_increase_direction_attainment_halfway(self, api):
        """PRD §3.5: "for an `INCREASE` goal, progress is the difference between
        `current_value` and `baseline_value` divided by the difference between
        `target_value` and `baseline_value`".
        PRD §3.5: "In both directions the progress fraction is clamped to the
        range from 0 to 1 inclusive, multiplied by 100, and rounded half-up to 2
        decimal places."
        PRD §3.5: "The first indicator posted under an `ADOPTED` goal moves the
        goal `ADOPTED` → `MONITORING`."

        Design: Corner/calculations/goal_attainment_increase_direction
        """
        ctx, goal = setup_adopted_goal(baseline_value=50, target_value=80,
                                       direction="INCREASE")
        create_indicator(goal["id"], measured_at="2027-01-15T00:00:00Z", value=65)
        after = get_success_data(api_client.get_goal(goal["id"], OFFICER))
        # (65 - 50) / (80 - 50) = 0.5 -> 50.00
        assert after["attainment_pct"] == pytest.approx(50.00, abs=0.001)
        assert after["current_value"] == pytest.approx(65, abs=0.001)
        assert after["status"] == "MONITORING"

    def test_mark_achieved_below_threshold_rejected(self, api):
        """PRD §3.5: "Marking a goal achieved (`MONITORING` → `ACHIEVED`)
        requires `attainment_pct` of at least 100.00, failing with
        `ERR_THRESHOLD_NOT_MET` below that bar."

        Design: Corner/endpoints/conditional_action_mark_achieved_requires_100
        """
        ctx, goal = setup_adopted_goal(baseline_value=50, target_value=80,
                                       direction="INCREASE")
        create_indicator(goal["id"], measured_at="2027-01-15T00:00:00Z", value=65)
        after = get_success_data(api_client.get_goal(goal["id"], OFFICER))
        assert after["attainment_pct"] == pytest.approx(50.00, abs=0.001)

        resp = api_client.mark_goal_achieved(goal["id"], OFFICER)
        validate_error(resp, ApiErrorId.ERR_THRESHOLD_NOT_MET)


class TestInterimReports:
    def test_due_date_sixty_days_before_anniversary(self, api):
        """PRD §3.7: "The server computes the report's `due_date` as the term's
        `term_start` advanced by `report_year` calendar years — calendar-year
        addition clamps February 29 to February 28 in non-leap years — and then
        moved earlier by 60 days of advance notice; the submission window closes
        at that due date."
        PRD §3.7: "The report begins `DRAFT` with `submitted_at` null."

        Design: Corner/calculations/interim_report_due_date_sixty_days_before_anniversary
        """
        system = create_system(name="DueDate County", system_type="SINGLE_SCHOOL")
        create_campus(system["id"], name="Main", enrollment=100)
        term = create_term(system["id"], term_start="2026-09-01T00:00:00Z",
                           term_length_years=5)
        report = validate_success(
            api_client.create_interim_report(
                term["id"], create_interim_report_payload(report_year=1,
                                                          narrative="Year one."),
                LEADER),
            expected_status=201)
        # 2026-09-01 + 1 year = 2027-09-01; minus 60 days = 2027-07-03
        assert report["due_date"].startswith("2027-07-03"), \
            f"expected due_date 2027-07-03, got {report['due_date']!r}"
        assert report["status"] == "DRAFT"
        assert report["submitted_at"] is None


class TestLateReportPenaltyCascade:
    def _setup_late_report(self):
        """TERM_ACTIVE context plus one report driven to LATE (clock past due)."""
        ctx = setup_term_active(system_name="Penalty County")
        report = get_success_data(api_client.create_interim_report(
            ctx["term"]["id"],
            create_interim_report_payload(report_year=1,
                                          narrative="Year one progress."),
            LEADER))
        # due_date is 2027-07-03; move past it so the submission lands LATE.
        set_clock("2027-07-10T00:00:00Z")
        late = get_success_data(api_client.submit_interim_report(report["id"], LEADER))
        assert late["status"] == "LATE"
        return ctx, late

    def test_late_accept_debits_penalty_into_next_annual_invoice(self, api):
        """PRD §3.7: "When an officer accepts a report whose status is `LATE`,
        the system's `fee_credit_cents` ledger is debited by a flat late-report
        penalty of 25000 cents (250 dollars); the ledger may go negative".
        PRD §3.8: "when the ledger is negative (for instance, from a late-report
        penalty), the magnitude of the negative balance is added to the invoice
        amount and the ledger is reset to zero."

        Design: Difficulty/transitive_cascade/late_report_accept_cascade_penalty_invoice
        """
        create_fee_schedule()
        ctx, late = self._setup_late_report()

        accepted = validate_success(
            api_client.accept_interim_report(late["id"], OFFICER))
        assert accepted["status"] == "ACCEPTED"

        system = get_success_data(api_client.get_system(ctx["system"]["id"], OFFICER))
        assert system["fee_credit_cents"] == -LATE_REPORT_PENALTY_CENTS

        # One IN_SCOPE campus (300 < 1000): 500000 + 1*120000, plus the 25000
        # negative-credit reversal -> 645000.
        invoice = create_annual_invoice(ctx["system"]["id"], billing_year=2027)
        assert invoice["amount_cents"] == 645000

    def test_negative_ledger_reset_after_first_invoice(self, api):
        """PRD §3.8: "when the ledger is negative (for instance, from a
        late-report penalty), the magnitude of the negative balance is added to
        the invoice amount and the ledger is reset to zero."
        PRD §3.8: "For an `ANNUAL_FEE` invoice, the billable campus count is the
        number of the system's campuses with `campus_status` of `IN_SCOPE`."

        Design: Difficulty/transitive_cascade/late_report_accept_cascade_penalty_invoice
        """
        create_fee_schedule()
        ctx, late = self._setup_late_report()
        get_success_data(api_client.accept_interim_report(late["id"], OFFICER))

        first = create_annual_invoice(ctx["system"]["id"], billing_year=2027)
        assert first["amount_cents"] == 645000

        system = get_success_data(api_client.get_system(ctx["system"]["id"], OFFICER))
        assert system["fee_credit_cents"] == 0, \
            "the negative balance is consumed by the first invoice issuance"

        second = create_annual_invoice(ctx["system"]["id"], billing_year=2028)
        # ledger already reset: 500000 + 1*120000 with no penalty carry-over
        assert second["amount_cents"] == 620000


class TestRenewalCascade:
    def test_clock_at_renewal_window_issues_renewal_invoice(self, api,
                                                            bursar_headers):
        """PRD §2.8: "a term in `INTERIM_MONITORING` whose renewal window has
        opened (current time at or after 180 days before `term_end`) moves to
        `RENEWAL`, issuing a renewal-fee invoice as it does so."
        PRD §3.2: "once the current time reaches 180 days before `term_end`, the
        term moves `INTERIM_MONITORING` → `RENEWAL` automatically, and entering
        `RENEWAL` issues a `RENEWAL_FEE` invoice for the owning system per the
        fee rules of §3.8."

        Design: Corner/cross_cutting_layers/cascading_side_effect_renewal_invoice_on_term_end_approach
        """
        create_fee_schedule()
        ctx, report = setup_accepted_interim_report()
        term = get_success_data(api_client.get_term(ctx["term"]["id"], OFFICER))
        assert term["status"] == "INTERIM_MONITORING"

        # term_start 2026-09-01 + 5 years = term_end 2031-09-01 (exclusive);
        # 180 days before term_end is 2031-03-05.
        set_clock("2031-03-05T00:00:00Z")

        term = get_success_data(api_client.get_term(ctx["term"]["id"], OFFICER))
        assert term["status"] == "RENEWAL"

        invoices = get_success_data(api_client.list_system_invoices(
            ctx["system"]["id"], bursar_headers))
        assert isinstance(invoices, list)
        renewal_invoices = [i for i in invoices
                            if i["invoice_type"] == "RENEWAL_FEE"]
        assert len(renewal_invoices) == 1, \
            "entering RENEWAL must issue exactly one RENEWAL_FEE invoice"
