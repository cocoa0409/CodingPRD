"""Additional-service billing: dual variants, horizon boundary, freezing, lifecycle."""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    create_active_project,
    create_report_issued_visit,
    create_owner_accepted_change_order,
    create_draft_invoice,
    setup_extended_duration_project,
    set_clock,
    make_firm_admin_headers,
    make_architect_headers,
    make_owner_headers,
)

SOV_AB = [
    {"line_code": "A", "description": "Concrete", "scheduled_value_cents": 6000000},
    {"line_code": "B", "description": "Metals", "scheduled_value_cents": 4000000},
]
SOV_A_ONLY = [{"line_code": "A", "description": "Concrete",
               "scheduled_value_cents": 10000000}]


class TestBillingPerDiemVsWholeMonthDivergence:
    def _invoice_for_billing_method(self, api, billing_method):
        project = create_active_project(
            sov_lines=SOV_AB, grace_days=5, billing_method=billing_method,
        )
        set_clock("2026-11-05T09:00:00Z")
        resp = api.create_additional_service_invoice(
            {"project_id": project["id"], "period_start": "2026-10-01",
             "period_end": "2026-11-30"},
            make_firm_admin_headers(),
        )
        return validate_success(resp, 201)

    def test_per_diem_prorated_bills_exact_days(self, api):
        """PRD 3.8: "under `PER_DIEM_PRORATED` the amount is `billable_days`
        times `daily_extension_rate_cents`" and "`billable_days` counts the
        calendar dates that fall within the invoice period, are strictly later
        than `horizon_start_date`, and are no later than `horizon_end_date`."

        Design: Difficulty/dual_variant_calc/invoice_billing_per_diem_vs_whole_month_divergence
        """
        invoice = self._invoice_for_billing_method(api, "PER_DIEM_PRORATED")
        # horizon_start 2026-10-05, horizon_end = clock 2026-11-05
        # dates 2026-10-06..2026-11-05 -> 31 days
        assert invoice["billable_days"] == 31
        assert invoice["amount_cents"] == 3720000
        assert invoice["status"] == "DRAFT"

    def test_whole_month_bills_started_months(self, api):
        """PRD 3.8: "under `WHOLE_MONTH` each started thirty-day month bills as a
        whole month — the billable days are divided by thirty and rounded up to a
        whole number of months, then multiplied by `monthly_extension_rate_cents`."

        Design: Difficulty/dual_variant_calc/invoice_billing_per_diem_vs_whole_month_divergence
        """
        invoice = self._invoice_for_billing_method(api, "WHOLE_MONTH")
        assert invoice["billable_days"] == 31
        # ceil(31 / 30) = 2 -> 2 x 3000000
        assert invoice["amount_cents"] == 6000000
        assert invoice["status"] == "DRAFT"


class TestBillingHorizonGraceBoundary:
    def _project_at_horizon(self, api, clock_date):
        project = create_active_project(sov_lines=SOV_AB, grace_days=5)
        set_clock(clock_date)
        return project

    def test_clock_on_horizon_start_yields_no_billable_days(self, api):
        """PRD 3.8: "`billable_days` counts the calendar dates that fall within
        the invoice period, are strictly later than `horizon_start_date`, and are
        no later than `horizon_end_date`. Creation requires at least one billable
        day; a period that yields none is rejected with `ERR_NO_BILLABLE_EXTENSION`
        (HTTP 422)."

        Design: Difficulty/boundary_precision_check/billing_horizon_grace_boundary_strictly_after
        """
        project = self._project_at_horizon(api, "2026-10-05T09:00:00Z")
        # horizon_start = 2026-09-30 + 0 + 5 = 2026-10-05; horizon_end = clock 2026-10-05
        resp = api.create_additional_service_invoice(
            {"project_id": project["id"], "period_start": "2026-10-01",
             "period_end": "2026-10-31"},
            make_firm_admin_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_NO_BILLABLE_EXTENSION, 422)

    def test_one_day_past_horizon_yields_exactly_one_billable_day(self, api):
        """PRD 3.8: "The gate is the project's derived `ca_posture`: it is
        `EXTENDED_DURATION` exactly when the project's `status` is `ACTIVE` and
        the logical-clock date is strictly later than
        `adjusted_substantial_completion_date` plus `excusable_delay_days` plus
        `grace_days`; otherwise it is `NORMAL`. The comparison is strict — when
        the clock date lands exactly on the adjusted date plus delay plus grace,
        the posture stays `NORMAL`."

        Design: Difficulty/boundary_precision_check/billing_horizon_grace_boundary_strictly_after
        """
        project = self._project_at_horizon(api, "2026-10-05T09:00:00Z")
        current = get_success_data(api.get_project(project["id"], make_firm_admin_headers()))
        # equality on the horizon date is not extended duration
        assert current["ca_posture"] == "NORMAL"
        set_clock("2026-10-06T09:00:00Z")
        resp = api.create_additional_service_invoice(
            {"project_id": project["id"], "period_start": "2026-10-01",
             "period_end": "2026-10-31"},
            make_firm_admin_headers(),
        )
        invoice = validate_success(resp, 201)
        # only 2026-10-06 is strictly after horizon_start 2026-10-05 and <= clock
        assert invoice["billable_days"] == 1
        assert invoice["amount_cents"] == 120000


class TestInvoicePeriodOverlap:
    def _project_with_first_invoice(self, api):
        project = create_active_project(sov_lines=SOV_AB, grace_days=5)
        set_clock("2026-11-05T09:00:00Z")
        invoice1 = create_draft_invoice(project["id"], "2026-10-01", "2026-10-31")
        return project, invoice1

    def test_adjacent_period_allowed_overlap_rejected(self, api):
        """PRD 3.8: "the closed interval from `period_start` through `period_end`
        must not overlap any other non-cancelled invoice's period on the project,
        where overlap means the requested start is earlier than the other
        period's end and the other period's start is earlier than the requested
        end — two periods sharing a single boundary date are adjacent and
        allowed. Overlap is rejected with `ERR_INVOICE_PERIOD_OVERLAP` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/invoice_period_half_open_overlap
        """
        project, invoice1 = self._project_with_first_invoice(api)
        adjacent = api.create_additional_service_invoice(
            {"project_id": project["id"], "period_start": "2026-10-31",
             "period_end": "2026-11-30"},
            make_firm_admin_headers(),
        )
        invoice2 = validate_success(adjacent, 201)
        assert invoice2["status"] == "DRAFT"
        overlapping = api.create_additional_service_invoice(
            {"project_id": project["id"], "period_start": "2026-10-15",
             "period_end": "2026-11-15"},
            make_firm_admin_headers(),
        )
        validate_error(overlapping, ApiErrorId.ERR_INVOICE_PERIOD_OVERLAP, 409)

    def test_first_invoice_billable_days(self, api):
        """PRD 3.8: "`billable_days` counts the calendar dates that fall within
        the invoice period, are strictly later than `horizon_start_date`, and are
        no later than `horizon_end_date`."

        Design: Difficulty/resource_temporal_overlap/invoice_period_half_open_overlap
        """
        project, invoice1 = self._project_with_first_invoice(api)
        # horizon_start 2026-10-05, horizon_end = clock 2026-11-05;
        # period 2026-10-01..2026-10-31 -> dates 2026-10-06..2026-10-31 -> 26 days
        assert invoice1["billable_days"] == 26


class TestInvoicePeriodShape:
    def test_invoice_period_start_after_end_returns_400(self, api):
        """PRD 3.8: "the start must be strictly before the end or the request
        fails body-shape validation with `ERR_INVALID_REQUEST`." PRD 2.7 stage 3:
        "`period_start` strictly before `period_end` where both appear".

        Design: Corner/validations/invoice_period_start_after_end_returns_400
        """
        from test_helpers import create_project
        project = create_project(sov_lines=SOV_A_ONLY)
        resp = api.create_additional_service_invoice(
            {"project_id": project["id"], "period_start": "2026-11-01",
             "period_end": "2026-10-01"},
            make_firm_admin_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)


class TestIssuedInvoiceFrozen:
    def _issued_invoice_then_incorporation(self, api):
        """DRAFT invoice (31 days, 3720000) ISSUED; then a 20-day time-only
        change order is incorporated, moving the horizon out."""
        project = create_active_project(sov_lines=SOV_A_ONLY, grace_days=5)
        set_clock("2026-11-05T09:00:00Z")
        invoice = create_draft_invoice(project["id"], "2026-10-01", "2026-11-30")
        resp = api.issue_additional_service_invoice(invoice["id"], make_firm_admin_headers())
        invoice = get_success_data(resp)
        change_order = create_owner_accepted_change_order(
            project, title="Weather extension",
            net_cost_change_cents=0, time_extension_days=20,
        )
        project = get_success_data(api.get_project(project["id"], make_firm_admin_headers()))
        owner_headers = make_owner_headers(project["owner_user_id"])
        api.incorporate_change_order(
            change_order["id"], {"expected_project_version": project["version"]},
            owner_headers,
        )
        project = get_success_data(api.get_project(project["id"], make_firm_admin_headers()))
        invoice = get_success_data(
            api.get_additional_service_invoice(invoice["id"], make_firm_admin_headers()))
        return project, invoice

    def test_incorporation_landed_but_invoice_stays_issued(self, api):
        """PRD 3.8: "Issuance freezes everything: once an invoice leaves `DRAFT`,
        its `billable_days`, both horizon dates, and `amount_cents` are never
        recomputed by any subsequent project mutation."

        Design: Corner/calculations/issued_invoice_frozen_on_later_incorporation
        """
        project, invoice = self._issued_invoice_then_incorporation(api)
        assert project["adjusted_substantial_completion_date"] == "2026-10-20"
        assert invoice["status"] == "ISSUED"

    def test_issued_invoice_amounts_frozen(self, api):
        """PRD 3.8: "Issuance freezes everything: once an invoice leaves `DRAFT`,
        its `billable_days`, both horizon dates, and `amount_cents` are never
        recomputed by any subsequent project mutation."

        Design: Corner/calculations/issued_invoice_frozen_on_later_incorporation
        """
        project, invoice = self._issued_invoice_then_incorporation(api)
        assert invoice["billable_days"] == 31
        assert invoice["amount_cents"] == 3720000
        assert invoice["horizon_start_date"] == "2026-10-05"


class TestDraftInvoiceRefrozenOnSubstantialCompletion:
    def _setup(self, api):
        """ACTIVE project; DRAFT invoice created at clock 2026-10-20 (horizon_end
        = clock); punch inspection reported; clock moves to 2026-10-25."""
        project = create_active_project(sov_lines=SOV_A_ONLY, grace_days=5)
        set_clock("2026-10-20T09:00:00Z")
        invoice = create_draft_invoice(project["id"], "2026-10-01", "2026-10-31")
        set_clock("2026-10-21T09:00:00Z")
        visit, _ = create_report_issued_visit(
            project["id"], visit_date="2026-10-21", purpose="PUNCH_INSPECTION",
            conformance_summary="MINOR_DEVIATIONS",
        )
        set_clock("2026-10-25T09:00:00Z")
        return project, invoice

    def test_substantial_completion_fixes_horizon_end(self, api):
        """PRD 3.7: "On determination the project's
        `substantial_completion_actual_date` is set to the logical-clock date,
        the project moves to `SUBSTANTIAL_COMPLETION_ACHIEVED`, its posture is
        recomputed, and every `DRAFT` additional-service invoice is recomputed
        with its horizon end fixed to the actual substantial-completion date".

        Design: Corner/calculations/draft_invoice_refrozen_on_substantial_completion
        """
        project, invoice = self._setup(api)
        # before: horizon_end was the creation-time clock date 2026-10-20
        assert invoice["billable_days"] == 15
        assert invoice["amount_cents"] == 1800000
        resp = api.achieve_substantial_completion(project["id"], make_architect_headers())
        project = validate_success(resp, 200)
        assert project["status"] == "SUBSTANTIAL_COMPLETION_ACHIEVED"
        assert project["substantial_completion_actual_date"] == "2026-10-25"
        invoice = get_success_data(
            api.get_additional_service_invoice(invoice["id"], make_firm_admin_headers()))
        assert invoice["horizon_end_date"] == "2026-10-25"

    def test_substantial_completion_recomputes_billable_days_and_amount(self, api):
        """PRD 3.8: "On any change to the project's `excusable_delay_days` or
        `adjusted_substantial_completion_date`, and again when substantial
        completion is achieved (which fixes the horizon end to
        `substantial_completion_actual_date`), every invoice of the project still
        in `DRAFT` recomputes its `horizon_start_date`, `horizon_end_date`,
        `billable_days`, and `amount_cents`".

        Design: Corner/calculations/draft_invoice_refrozen_on_substantial_completion
        """
        project, invoice = self._setup(api)
        api.achieve_substantial_completion(project["id"], make_architect_headers())
        invoice = get_success_data(
            api.get_additional_service_invoice(invoice["id"], make_firm_admin_headers()))
        # dates 2026-10-06..2026-10-25 within the period -> 20 billable days
        assert invoice["billable_days"] == 20
        assert invoice["amount_cents"] == 2400000
        assert invoice["status"] == "DRAFT"


class TestCancelPaidInvoice:
    def test_cancel_paid_invoice_returns_invalid_state(self, api):
        """PRD 3.8: "Issuing or cancelling from a state other than those named,
        deciding an invoice not in `ISSUED`, or recording payment for one not in
        `OWNER_APPROVED` fails with `ERR_INVOICE_INVALID_STATE` (HTTP 409)." and
        "A `FirmAdmin` records payment of an `OWNER_APPROVED` invoice, moving it
        to `PAID` (terminal)".

        Design: Corner/state_machines/cancel_paid_invoice_returns_invalid_state
        """
        project = create_active_project(sov_lines=SOV_A_ONLY, grace_days=5)
        set_clock("2026-11-05T09:00:00Z")
        invoice = create_draft_invoice(project["id"], "2026-10-01", "2026-10-31")
        # 26 billable days x 120000
        assert invoice["billable_days"] == 26
        assert invoice["amount_cents"] == 3120000
        api.issue_additional_service_invoice(invoice["id"], make_firm_admin_headers())
        api.decide_additional_service_invoice(
            invoice["id"], {"decision": "APPROVE"},
            make_owner_headers(project["owner_user_id"]),
        )
        paid = validate_success(
            api.record_invoice_payment(invoice["id"], make_firm_admin_headers()), 200)
        assert paid["status"] == "PAID"
        resp = api.cancel_additional_service_invoice(invoice["id"], make_firm_admin_headers())
        validate_error(resp, ApiErrorId.ERR_INVOICE_INVALID_STATE, 409)
        current = get_success_data(
            api.get_additional_service_invoice(invoice["id"], make_firm_admin_headers()))
        assert current["status"] == "PAID"
        assert current["amount_cents"] == 3120000
