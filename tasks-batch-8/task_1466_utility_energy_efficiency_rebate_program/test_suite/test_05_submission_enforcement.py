"""Submission enforcement: the program-open gate, ally-standing gate, the
fixed validation order between competing violations, line-item presence, the
invoice eligibility window, the budget cap, and trade-ally ownership."""
from test_helpers import (
    ApiErrorId,
    add_line_item,
    add_measure,
    build_approved_application,
    create_active_ally,
    create_ally,
    create_draft_application,
    create_open_program,
    create_program_year,
    get_application,
    make_trade_ally_headers,
    open_program_year,
    set_clock,
    validate_error,
    validate_success,
)


class TestSubmitRequiresProgramYearOpen:
    def test_submit_on_closed_program_rejected(self, api, admin_headers):
        """PRD §2.9: "Fifth comes the program-open gate: while a program year is
        in any status other than `OPEN`, eleven operations are refused with
        `ERR_PROGRAM_NOT_OPEN` (HTTP 409) — creating an application, adding a
        line item, attaching a savings claim, submitting an application,
        scheduling a pre-installation inspection, completing an inspection,
        verifying, approving, rejecting, paying, and withdrawing."

        Design: Difficulty/cross_entity_state_dependency/application_submit_requires_program_year_open
        """
        set_clock()
        py = create_program_year()
        measure = add_measure(py["id"], base_rate_cents=10_000, deemed_kwh_per_unit=100)
        py = open_program_year(py["id"])
        ally = create_active_ally()
        build_approved_application(py, ally, measure, quantity=1, claim="DEEMED")

        # Second application drafted while the year is still OPEN.
        app_b = create_draft_application(py, ally)
        add_line_item(app_b, measure, quantity=1, ally=ally)

        py = validate_success(api.close_program_year(py["id"], admin_headers), 200)
        assert py["status"] == "CLOSED"

        res = api.submit_application(app_b["id"], make_trade_ally_headers(ally["id"]))
        validate_error(res, ApiErrorId.ERR_PROGRAM_NOT_OPEN, expected_status=409)
        assert get_application(app_b["id"])["status"] == "DRAFT"

    def test_submit_on_reported_program_rejected(self, api, admin_headers):
        """PRD §2.9: "Fifth comes the program-open gate: while a program year is
        in any status other than `OPEN`, eleven operations are refused with
        `ERR_PROGRAM_NOT_OPEN` (HTTP 409) — creating an application, adding a
        line item, attaching a savings claim, submitting an application,
        scheduling a pre-installation inspection, completing an inspection,
        verifying, approving, rejecting, paying, and withdrawing."

        Design: Difficulty/cross_entity_state_dependency/application_submit_requires_program_year_open
        """
        from test_helpers import (
            create_evaluation_adjustment_payload,
            make_regulator_headers,
        )

        set_clock()
        py = create_program_year()
        measure = add_measure(py["id"], base_rate_cents=10_000, deemed_kwh_per_unit=100)
        py = open_program_year(py["id"])
        ally = create_active_ally()
        build_approved_application(py, ally, measure, quantity=1, claim="DEEMED")

        app_b = create_draft_application(py, ally)
        add_line_item(app_b, measure, quantity=1, ally=ally)

        py = validate_success(api.close_program_year(py["id"], admin_headers), 200)
        validate_success(
            api.create_evaluation_adjustment(
                create_evaluation_adjustment_payload(py["id"]),
                make_regulator_headers(),
            ),
            201,
        )
        py = validate_success(
            api.report_program_year(py["id"], make_regulator_headers()), 200
        )
        assert py["status"] == "REPORTED"

        res = api.submit_application(app_b["id"], make_trade_ally_headers(ally["id"]))
        validate_error(res, ApiErrorId.ERR_PROGRAM_NOT_OPEN, expected_status=409)
        assert get_application(app_b["id"])["status"] == "DRAFT"


class TestSubmitRequiresAllyActive:
    def test_submit_with_suspended_ally_rejected(self, api, admin_headers):
        """PRD §3.4: "ally standing, requiring the installing ally to be
        `ACTIVE` (`ERR_ALLY_NOT_ACTIVE`, HTTP 409)"

        Design: Difficulty/cross_entity_state_dependency/application_submit_requires_ally_active
        """
        py, measures = create_open_program()
        ally = create_active_ally()
        app = create_draft_application(py, ally)
        add_line_item(app, measures[0], quantity=1, ally=ally)

        validate_success(api.suspend_trade_ally(ally["id"], admin_headers), 200)

        res = api.submit_application(app["id"], make_trade_ally_headers(ally["id"]))
        validate_error(res, ApiErrorId.ERR_ALLY_NOT_ACTIVE, expected_status=409)
        assert get_application(app["id"])["status"] == "DRAFT"

    def test_submit_with_pending_ally_rejected(self, api, admin_headers):
        """PRD §3.4: "ally standing, requiring the installing ally to be
        `ACTIVE` (`ERR_ALLY_NOT_ACTIVE`, HTTP 409)"
        PRD §3.2: "A new ally starts with `enroll_status` `PENDING`,
        `performance_score` 100, `standing_tier` `STANDARD`, and `version` 1."

        Design: Difficulty/cross_entity_state_dependency/application_submit_requires_ally_active
        """
        py, measures = create_open_program()
        ally = create_ally()  # PENDING — never activated
        app = create_draft_application(py, ally)
        add_line_item(app, measures[0], quantity=1, ally=ally)

        res = api.submit_application(app["id"], make_trade_ally_headers(ally["id"]))
        validate_error(res, ApiErrorId.ERR_ALLY_NOT_ACTIVE, expected_status=409)
        assert get_application(app["id"])["status"] == "DRAFT"


class TestValidationOrderPriorityPairs:
    def test_program_not_open_wins_over_cap_exceeded(self, api, admin_headers):
        """PRD §3.4: "After authentication, authorization, and resource
        resolution: the program-open gate (`ERR_PROGRAM_NOT_OPEN`); the `DRAFT`
        state check (`ERR_INVALID_STATE`); ally standing, requiring the
        installing ally to be `ACTIVE` (`ERR_ALLY_NOT_ACTIVE`, HTTP 409);
        catalog currency, requiring every line item's measure to be active
        (`ERR_MEASURE_INACTIVE`, HTTP 409); presence of at least one line item
        (`ERR_NO_LINE_ITEMS`, HTTP 422); the invoice eligibility window; the
        budget-cap check; and only then the ownership comparison
        (`ERR_FORBIDDEN`)."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_fiscal_program_not_open_wins
        """
        # Budget cap 100000; target line would price at 150000 — over the
        # remaining cap — AND the year is CLOSED. The program-open gate (fifth
        # overall) runs before the budget-cap check.
        set_clock()
        py = create_program_year(budget_cap_cents=100_000)
        m_fit = add_measure(py["id"], base_rate_cents=100_000, deemed_kwh_per_unit=100)
        m_over = add_measure(py["id"], base_rate_cents=150_000, deemed_kwh_per_unit=100)
        py = open_program_year(py["id"])
        ally = create_active_ally()
        build_approved_application(py, ally, m_fit, quantity=1, claim="DEEMED")

        app_b = create_draft_application(py, ally)
        add_line_item(app_b, m_over, quantity=1, ally=ally)
        validate_success(api.close_program_year(py["id"], admin_headers), 200)

        res = api.submit_application(app_b["id"], make_trade_ally_headers(ally["id"]))
        validate_error(res, ApiErrorId.ERR_PROGRAM_NOT_OPEN, expected_status=409)
        assert get_application(app_b["id"])["status"] == "DRAFT"

    def test_program_not_open_wins_when_cap_would_fit(self, api, admin_headers):
        """PRD §3.4: "After authentication, authorization, and resource
        resolution: the program-open gate (`ERR_PROGRAM_NOT_OPEN`); the `DRAFT`
        state check (`ERR_INVALID_STATE`); ally standing, requiring the
        installing ally to be `ACTIVE` (`ERR_ALLY_NOT_ACTIVE`, HTTP 409);
        catalog currency, requiring every line item's measure to be active
        (`ERR_MEASURE_INACTIVE`, HTTP 409); presence of at least one line item
        (`ERR_NO_LINE_ITEMS`, HTTP 422); the invoice eligibility window; the
        budget-cap check; and only then the ownership comparison
        (`ERR_FORBIDDEN`)."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_fiscal_program_not_open_wins
        """
        # Same shape, but the target application's incentive would fit the
        # remaining cap exactly — the only outstanding violation is the gate.
        set_clock()
        py = create_program_year(budget_cap_cents=100_000)
        m_fit = add_measure(py["id"], base_rate_cents=100_000, deemed_kwh_per_unit=100)
        py = open_program_year(py["id"])
        ally = create_active_ally()
        build_approved_application(py, ally, m_fit, quantity=1, claim="DEEMED")

        app_b = create_draft_application(py, ally)
        add_line_item(app_b, m_fit, quantity=1, ally=ally)
        validate_success(api.close_program_year(py["id"], admin_headers), 200)

        res = api.submit_application(app_b["id"], make_trade_ally_headers(ally["id"]))
        validate_error(res, ApiErrorId.ERR_PROGRAM_NOT_OPEN, expected_status=409)
        assert get_application(app_b["id"])["status"] == "DRAFT"

    def test_ally_not_active_wins_over_invoice_window(self, api, admin_headers):
        """PRD §3.4: "After authentication, authorization, and resource
        resolution: the program-open gate (`ERR_PROGRAM_NOT_OPEN`); the `DRAFT`
        state check (`ERR_INVALID_STATE`); ally standing, requiring the
        installing ally to be `ACTIVE` (`ERR_ALLY_NOT_ACTIVE`, HTTP 409);
        catalog currency, requiring every line item's measure to be active
        (`ERR_MEASURE_INACTIVE`, HTTP 409); presence of at least one line item
        (`ERR_NO_LINE_ITEMS`, HTTP 422); the invoice eligibility window; the
        budget-cap check; and only then the ownership comparison
        (`ERR_FORBIDDEN`)."

        Design: Difficulty/priority_pair_validation_conflict/business_referential_vs_business_temporal_ally_not_active_wins
        """
        # SUSPENDED ally AND invoice_date outside the eligibility window:
        # ally standing (earlier) is reported, not the temporal error.
        py, measures = create_open_program()
        ally = create_active_ally()
        app = create_draft_application(py, ally, invoice_date="2026-01-01")
        add_line_item(app, measures[0], quantity=1, ally=ally)
        validate_success(api.suspend_trade_ally(ally["id"], admin_headers), 200)

        res = api.submit_application(app["id"], make_trade_ally_headers(ally["id"]))
        validate_error(res, ApiErrorId.ERR_ALLY_NOT_ACTIVE, expected_status=409)
        assert get_application(app["id"])["status"] == "DRAFT"

    def test_ally_not_active_with_valid_invoice(self, api, admin_headers):
        """PRD §3.4: "ally standing, requiring the installing ally to be
        `ACTIVE` (`ERR_ALLY_NOT_ACTIVE`, HTTP 409)"

        Design: Difficulty/priority_pair_validation_conflict/business_referential_vs_business_temporal_ally_not_active_wins
        """
        py, measures = create_open_program()
        ally = create_active_ally()
        app = create_draft_application(py, ally)  # default invoice date in-window
        add_line_item(app, measures[0], quantity=1, ally=ally)
        validate_success(api.suspend_trade_ally(ally["id"], admin_headers), 200)

        res = api.submit_application(app["id"], make_trade_ally_headers(ally["id"]))
        validate_error(res, ApiErrorId.ERR_ALLY_NOT_ACTIVE, expected_status=409)
        assert get_application(app["id"])["status"] == "DRAFT"


class TestSubmissionContentGates:
    def test_submit_with_no_line_items_returns_error(self, api, admin_headers):
        """PRD §3.4: "presence of at least one line item (`ERR_NO_LINE_ITEMS`,
        HTTP 422)"

        Design: Corner/validations/submit_with_no_line_items_returns_no_line_items
        """
        py, _measures = create_open_program()
        ally = create_active_ally()
        app = create_draft_application(py, ally)

        res = api.submit_application(app["id"], make_trade_ally_headers(ally["id"]))
        validate_error(res, ApiErrorId.ERR_NO_LINE_ITEMS, expected_status=422)

    def test_invoice_date_out_of_range_returns_error(self, api, admin_headers):
        """PRD §3.4: "`invoice_date` must fall no earlier than ninety days
        before the date component of the year's `opened_at` and no later than
        the current logical-clock date, inclusive on both ends. Anything outside
        the window is refused with `ERR_INVOICE_DATE_OUT_OF_RANGE` (HTTP 422)."

        Design: Corner/validations/invoice_date_out_of_range_returns_error
        """
        # Year opens at the logical clock 2026-08-13, so the earliest eligible
        # invoice date is 2026-05-15; 2026-01-01 is far outside.
        py, measures = create_open_program()
        ally = create_active_ally()
        app = create_draft_application(py, ally, invoice_date="2026-01-01")
        add_line_item(app, measures[0], quantity=1, ally=ally)

        res = api.submit_application(app["id"], make_trade_ally_headers(ally["id"]))
        validate_error(res, ApiErrorId.ERR_INVOICE_DATE_OUT_OF_RANGE, expected_status=422)

    def test_program_cap_exceeded_returns_error(self, api, admin_headers):
        """PRD §3.4: "A submission that would push committed spending past the
        cap fails with `ERR_PROGRAM_CAP_EXCEEDED` (HTTP 402)."

        Design: Corner/validations/program_cap_exceeded_returns_error
        """
        py, measures = create_open_program(
            budget_cap_cents=10_000,
            measure_specs=[{"base_rate_cents": 20_000, "deemed_kwh_per_unit": 200}],
        )
        ally = create_active_ally()
        app = create_draft_application(py, ally)
        add_line_item(app, measures[0], quantity=1, ally=ally)

        res = api.submit_application(app["id"], make_trade_ally_headers(ally["id"]))
        validate_error(res, ApiErrorId.ERR_PROGRAM_CAP_EXCEEDED, expected_status=402)

    def test_trade_ally_cannot_submit_other_ally_application(self, api, admin_headers):
        """PRD §2.1: "When `X-User-Role` is `TradeAlly`, `X-User-ID` is the `id`
        of the acting trade-ally record; ownership checks on any resource that
        references a trade ally compare the resource's `trade_ally_id` field to
        `X-User-ID`, and a mismatch is rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/validations/trade_ally_cannot_act_on_other_ally_resource
        """
        py, measures = create_open_program()
        ally_a = create_active_ally(ally_name="Ally A")
        ally_b = create_active_ally(ally_name="Ally B")
        app = create_draft_application(py, ally_b)
        add_line_item(app, measures[0], quantity=1, ally=ally_b)

        res = api.submit_application(app["id"], make_trade_ally_headers(ally_a["id"]))
        validate_error(res, ApiErrorId.ERR_FORBIDDEN, expected_status=403)
        assert get_application(app["id"])["status"] == "DRAFT"
