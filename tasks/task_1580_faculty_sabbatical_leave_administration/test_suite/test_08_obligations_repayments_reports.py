"""Service obligations, repayment collection, and accomplishment reports."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    activate_grant_at,
    complete_grant_at,
    create_payment_payload,
    get_success_data,
    make_faculty_headers,
    run_accruals,
    separate_faculty,
    set_clock,
    setup_breached_repayment,
    setup_full_award,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
PROVOST = TEST_USERS["provost_headers"]


class TestReportResubmissionCycle:
    def test_report_resubmission_cycle_to_accepted(self, api):
        """PRD 3.9: "Submitting is the faculty member's act, supplying the
        `report_text`; only the owner may submit (`ERR_NOT_RESOURCE_OWNER`),
        and only from `DUE`, `OVERDUE`, or `REVISION_REQUIRED`
        (`ERR_INVALID_REPORT_STATE`)."
        PRD 3.9: "submitting from `DUE` leaves `submitted_late` false"
        PRD 3.9: "A decision of `ACCEPTED` moves the report to `ACCEPTED`,
        terminal. A decision of `REJECTED` moves it to `REVISION_REQUIRED` and
        records the `decision_comments`, inviting another submission."

        Design: Corner/state_machines/report_resubmission_cycle_to_accepted
        """
        ctx = setup_full_award(courses_to_cover=3, award_quota=1)
        faculty, grant = ctx["faculty"], ctx["grant"]
        activate_grant_at(grant["id"], grant["start_date"])
        complete_grant_at(grant["id"], grant["end_date"])

        reports, _ = validate_paginated(
            api.list_accomplishment_reports(ADMIN, params={"faculty_id": faculty["id"]})
        )
        assert len(reports) == 1
        report = reports[0]
        assert report["status"] == "DUE"
        # end_date 2027-07-01 + 90 days = 2027-09-29.
        assert report["due_date"].startswith("2027-09-29")

        first = validate_success(
            api.submit_accomplishment_report(
                report["id"], {"report_text": "Draft accomplishments."},
                make_faculty_headers(faculty["id"]),
            )
        )
        assert first["status"] == "SUBMITTED"
        assert first["submitted_late"] is False

        rejected = validate_success(
            api.review_accomplishment_report(
                report["id"],
                {"decision": "REJECTED", "comments": "Insufficient detail on publications."},
                PROVOST,
            )
        )
        assert rejected["status"] == "REVISION_REQUIRED"

        resubmitted = validate_success(
            api.submit_accomplishment_report(
                report["id"],
                {"report_text": "Revised accomplishments with publication list."},
                make_faculty_headers(faculty["id"]),
            )
        )
        assert resubmitted["status"] == "SUBMITTED"

        accepted = validate_success(
            api.review_accomplishment_report(report["id"], {"decision": "ACCEPTED"}, PROVOST)
        )
        assert accepted["status"] == "ACCEPTED"

        third = api.submit_accomplishment_report(
            report["id"], {"report_text": "Third attempt."},
            make_faculty_headers(faculty["id"]),
        )
        validate_error(third, ApiErrorId.ERR_INVALID_REPORT_STATE)


class TestPaymentBoundary:
    def test_payment_exceeds_outstanding_then_exact_settle(self, api):
        """PRD 3.9: "A `LeaveAdministrator` records a payment with an `amount`
        that must be strictly positive and no greater than the current
        `amount_outstanding` (`ERR_PAYMENT_EXCEEDS_OUTSTANDING`)"
        PRD 3.9: "a payment that brings the outstanding balance to zero moves
        the obligation to `SETTLED`, terminal."

        Design: Corner/validations/payment_exceeds_outstanding_then_exact_settle
        """
        ctx = setup_breached_repayment()
        repayment = ctx["repayment"]
        # Base 60000.00 (net salary; professional leave carries no coverage
        # plan), required 6, fulfilled 0 -> amount_owed 60000.00.
        assert repayment["amount_owed"] == pytest.approx(60000.00, abs=0.005)
        assert repayment["monthly_forgiveness"] == pytest.approx(10000.00, abs=0.005)

        pay1 = validate_success(
            api.create_repayment_payment(
                repayment["id"],
                create_payment_payload(20000.00, repayment["version"]),
                ADMIN,
            ),
            expected_status=201,
        )
        assert pay1["resulting_outstanding"] == pytest.approx(40000.00, abs=0.005)

        fresh = validate_success(api.get_repayment_obligation(repayment["id"], ADMIN))

        over = api.create_repayment_payment(
            repayment["id"],
            create_payment_payload(40000.01, fresh["version"]),
            ADMIN,
        )
        validate_error(over, ApiErrorId.ERR_PAYMENT_EXCEEDS_OUTSTANDING)

        exact = validate_success(
            api.create_repayment_payment(
                repayment["id"],
                create_payment_payload(40000.00, fresh["version"]),
                ADMIN,
            ),
            expected_status=201,
        )
        assert exact["resulting_outstanding"] == pytest.approx(0.00, abs=0.005)

        settled = validate_success(api.get_repayment_obligation(repayment["id"], ADMIN))
        assert settled["status"] == "SETTLED"
        assert settled["amount_outstanding"] == pytest.approx(0.00, abs=0.005)


class TestRepaymentTerminalLockdown:
    def test_repayment_terminal_lockdown(self, api):
        """PRD 3.9: "The obligation must be `ACTIVE` or `DEFAULTED`; paying
        against a terminal one is `ERR_INVALID_REPAYMENT_STATE`."
        PRD 3.9: "waiving moves `ACTIVE` or `DEFAULTED` to `WAIVED` (terminal;
        any other from-state is `ERR_INVALID_REPAYMENT_STATE`)"

        Design: Corner/validations/repayment_terminal_lockdown
        """
        ctx = setup_breached_repayment()
        repayment = ctx["repayment"]
        get_success_data(
            api.create_repayment_payment(
                repayment["id"],
                create_payment_payload(60000.00, repayment["version"]),
                ADMIN,
            )
        )
        settled = validate_success(api.get_repayment_obligation(repayment["id"], ADMIN))
        assert settled["status"] == "SETTLED"

        pay_after = api.create_repayment_payment(
            repayment["id"],
            create_payment_payload(1.00, settled["version"]),
            ADMIN,
        )
        validate_error(pay_after, ApiErrorId.ERR_INVALID_REPAYMENT_STATE)

        waive_after = api.waive_repayment_obligation(repayment["id"], {}, PROVOST)
        validate_error(waive_after, ApiErrorId.ERR_INVALID_REPAYMENT_STATE)

        payments, _ = validate_paginated(
            api.list_repayment_payments(repayment["id"], ADMIN)
        )
        assert len(payments) == 1
        assert payments[0]["amount"] == pytest.approx(60000.00, abs=0.005)


class TestRepaymentOcc:
    def test_occ_repayment_payment_stale_version(self, api):
        """PRD 2.8: "Recording a payment against a repayment obligation
        requires the request to carry `expected_repayment_version`, holding the
        obligation's `version` as the caller last observed it. Because every
        posted payment reduces `amount_outstanding` and increments the
        obligation's `version`, a payment issued against a version that has
        since advanced is rejected with `ERR_STALE_VERSION` (HTTP 412)"

        Design: Corner/cross_cutting_layers/occ_repayment_payment_stale_version
        """
        ctx = setup_breached_repayment()
        repayment = ctx["repayment"]
        stale_version = repayment["version"]

        first = validate_success(
            api.create_repayment_payment(
                repayment["id"], create_payment_payload(5000.00, stale_version), ADMIN
            ),
            expected_status=201,
        )
        assert first["resulting_outstanding"] == pytest.approx(55000.00, abs=0.005)

        stale = api.create_repayment_payment(
            repayment["id"], create_payment_payload(5000.00, stale_version), ADMIN
        )
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)

        after = validate_success(api.get_repayment_obligation(repayment["id"], ADMIN))
        assert after["amount_outstanding"] == pytest.approx(55000.00, abs=0.005)


class TestRepaymentFormulaDivergence:
    def _setup_obligation_with_two_months_fulfilled(self, api):
        """Sabbatical award (salary 120000.00, 1 semester at 100%, 5-course
        plan): net 60000.00, plan final 40000.00 -> base 100000.00 over 6
        required months. An accrual run at 2027-09-15 credits 2027-07 and
        2027-08 -> 2 fulfilled."""
        ctx = setup_full_award(courses_to_cover=5, award_quota=1)
        grant = ctx["grant"]
        activate_grant_at(grant["id"], "2027-01-01T00:00:00Z")
        complete_grant_at(grant["id"], "2027-07-01T00:00:00Z")
        set_clock("2027-09-15T00:00:00Z")
        run_accruals()
        obligations, _ = validate_paginated(
            api.list_service_obligations(
                ADMIN, params={"faculty_id": ctx["faculty"]["id"]}
            )
        )
        assert len(obligations) == 1
        ctx["obligation"] = obligations[0]
        return ctx

    def test_projected_liability_uses_proportional_variant(self, api):
        """PRD 3.9: "It takes a base equal to the grant's `net_salary` plus the
        coverage plan's `final_cost`, multiplies by the unfulfilled share — the
        required months minus the fulfilled months, over the required months —
        and rounds half-up to two decimal places. This proportional estimate
        deliberately diverges from the chronological breach formula below
        whenever the base does not divide evenly by the required months: on a
        base of 100,000.00 over six required months with two months fulfilled,
        the breach formula yields 66,666.66 while the projection reads
        66,666.67."

        Design: Difficulty/dual_variant_calc/repayment_chronological_vs_proportional_diverge
        """
        ctx = self._setup_obligation_with_two_months_fulfilled(api)
        obligation = ctx["obligation"]
        assert obligation["required_months"] == 6
        assert obligation["fulfilled_months"] == 2
        # Proportional read-time estimate: round(100000.00 * 4/6, 2).
        assert obligation["projected_liability"] == pytest.approx(66666.67, abs=0.001)

    def test_breach_uses_chronological_amortization(self, api):
        """PRD 3.9: "a `monthly_forgiveness` equal to the base divided by the
        required months, rounded half-up to two decimal places — the per-month
        amortization unit; and an `amount_owed` equal to the base minus the
        monthly forgiveness times the fulfilled-months snapshot."
        PRD 3.9: "on a base of 100,000.00 over six required months with two
        months fulfilled, the breach formula yields 66,666.66 while the
        projection reads 66,666.67."

        Design: Difficulty/dual_variant_calc/repayment_chronological_vs_proportional_diverge
        """
        ctx = self._setup_obligation_with_two_months_fulfilled(api)
        # Pre-breach read confirms the divergent projection.
        assert ctx["obligation"]["projected_liability"] == pytest.approx(66666.67, abs=0.001)

        separate_faculty(ctx["faculty"]["id"], "2027-09-15T00:00:00Z")
        repayments, _ = validate_paginated(
            api.list_repayment_obligations(
                ADMIN, params={"faculty_id": ctx["faculty"]["id"]}
            )
        )
        assert len(repayments) == 1
        repayment = repayments[0]
        # base = net 60000.00 + final 40000.00 = 100000.00
        assert repayment["base_amount"] == pytest.approx(100000.00, abs=0.005)
        # monthly = round(100000.00 / 6, 2) = 16666.67
        assert repayment["monthly_forgiveness"] == pytest.approx(16666.67, abs=0.001)
        assert repayment["fulfilled_months_at_breach"] == 2
        # Chronological: 100000.00 - 16666.67 * 2 = 66666.66 (one cent below
        # the proportional projection).
        assert repayment["amount_owed"] == pytest.approx(66666.66, abs=0.001)
