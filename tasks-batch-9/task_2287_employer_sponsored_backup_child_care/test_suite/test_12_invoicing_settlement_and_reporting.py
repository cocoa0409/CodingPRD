"""Invoice line rounding, the issue/void round trip, exact payment and the utilization report."""

from typing import Any, Dict

import pytest
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_cents_conservation,
    assert_employer_invoice,
    assert_invoice_line,
    assert_invoice_totals,
    assert_lines_sum_to_subtotal,
    assert_utilization_report,
    cancel,
    confirm_reservation,
    create_capacity_block,
    create_employer,
    create_invoice,
    create_reservation,
    drive_to_completed,
    issue_invoice,
    mark_no_show,
    match_reservation,
    payment_payload,
    read_employee_ledger,
    read_employer,
    read_invoice,
    read_invoice_lines,
    read_reservation,
    set_clock,
    setup_matchable_world,
    validate_error,
    validate_success,
    void_invoice,
)

NETWORK_ADMIN = TEST_USERS["network_admin"]
BENEFITS_ADMIN = TEST_USERS["benefits_admin"]

ROUNDING_PLAN = {
    "annual_use_limit_days": 10,
    "copay_in_home_cents_per_hour": 605,
    "in_home_min_billable_hours": 4,
}
CONSERVATION_PLAN = {
    "annual_use_limit_days": 1,
    "copay_center_cents_per_day": 1500,
    "overage_rate_center_cents_per_day": 20000,
    "no_show_charge_cents": 12000,
    "max_dependents_per_reservation": 3,
}
EXACT_CHANGE_PLAN = {"annual_use_limit_days": 10, "copay_center_cents_per_day": 1500}
FEE_EMPLOYER = {"admin_fee_pct": 0.085}


class TestInvoiceRoundsEachLineBeforeSumming:
    """Two identical 4.25-hour in-home copay lines of 2571.25 cents each."""

    @staticmethod
    def _two_completed_visits(api) -> Dict[str, Any]:
        world = setup_matchable_world(
            api,
            care_start_utc="2026-08-10T09:00:00Z",
            care_end_utc="2026-08-10T13:15:00Z",
            block_start_utc="2026-08-10T08:00:00Z",
            block_end_utc="2026-08-10T19:00:00Z",
            market_code="MKT-BOS",
            total_slots=1,
            provider_care_mode="IN_HOME",
            requested_care_mode="IN_HOME",
            employer_overrides=dict(FEE_EMPLOYER),
            plan_overrides=dict(ROUNDING_PLAN),
        )
        assert world["employer"]["admin_fee_pct"] == pytest.approx(0.085, abs=0.0001)

        second_block = create_capacity_block(
            api,
            world["provider"]["id"],
            "2026-08-11T08:00:00Z",
            "2026-08-11T19:00:00Z",
            total_slots=1,
        )

        match_reservation(api, world["reservation"]["id"])
        confirm_reservation(api, world["reservation"]["id"], world["block"]["id"])
        world["first"] = drive_to_completed(
            api,
            world["reservation"]["id"],
            "2026-08-10T09:00:00Z",
            "2026-08-10T13:15:00Z",
            check_in_clock="2026-08-10T08:30:00Z",
            complete_clock="2026-08-10T14:00:00Z",
        )

        second = create_reservation(
            api,
            world["employee"]["id"],
            world["dependent_ids"],
            "2026-08-11T09:00:00Z",
            "2026-08-11T13:15:00Z",
            market_code="MKT-BOS",
            requested_care_mode="IN_HOME",
        )
        match_reservation(api, second["id"])
        confirm_reservation(api, second["id"], second_block["id"])
        world["second"] = drive_to_completed(
            api,
            second["id"],
            "2026-08-11T09:00:00Z",
            "2026-08-11T13:15:00Z",
            check_in_clock="2026-08-11T08:30:00Z",
            complete_clock="2026-08-11T14:00:00Z",
        )
        return world

    def test_each_visit_bills_four_and_a_quarter_hours_at_2571_cents(self, api):
        """4.25 hours times 605 cents is 2571.25, which each reservation rounds alone.

        PRD 3.6: "`copay_cents` is then the covered hours multiplied by the plan's
        `copay_in_home_cents_per_hour`, rounded to a whole cent; the overage unit rate
        is the plan's `overage_rate_in_home_cents_per_hour` multiplied by
        `overage_tier_multiplier` and rounded to a whole cent"

        Design: Difficulty/combinatorial_formula/invoice_rounds_each_line_then_sums_never_5143
        """
        world = self._two_completed_visits(api)

        for visit in (world["first"], world["second"]):
            assert visit["fulfillment_status"] == "COMPLETED"
            assert visit["billable_hours_final"] == pytest.approx(4.25, abs=0.01)
            assert visit["days_charged_final"] == pytest.approx(1, abs=0.01)
            assert visit["covered_days"] == pytest.approx(1, abs=0.01)
            assert visit["overage_days"] == pytest.approx(0, abs=0.01)
            assert visit["copay_cents"] == 2571
            assert visit["overage_cents"] == 0
            assert visit["billing_status"] == "ACCRUED"

    def test_two_rounded_lines_sum_to_5142_and_never_to_5143(self, api):
        """Rounding each line first loses the half cent that a single sum would keep.

        PRD 3.9: "Each `InvoiceLine` records the `employer_invoice_id` it belongs to,
        the `reservation_id` it bills, a denormalised `employee_id` copied from that
        reservation for per-employee grouping, its `line_type`, its `quantity`, its
        `unit_cents`, and an `amount_cents` that is the quantity multiplied by the unit
        rate and rounded to a whole cent, evaluated independently for that line."

        Design: Difficulty/combinatorial_formula/invoice_rounds_each_line_then_sums_never_5143
        """
        world = self._two_completed_visits(api)

        invoice = create_invoice(api, world["employer"]["id"], "2026-08-01", "2026-08-31")
        assert_employer_invoice(invoice)
        assert invoice["line_count"] == 2
        assert invoice["subtotal_cents"] == 5142
        assert invoice["subtotal_cents"] != 5143

        lines = read_invoice_lines(api, invoice["id"])
        assert len(lines) == 2
        for line in lines:
            assert_invoice_line(line)
            assert line["line_type"] == "CARE_COPAY"
            assert line["quantity"] == pytest.approx(4.25, abs=0.01)
            assert line["unit_cents"] == 605
            assert line["amount_cents"] == 2571
        assert_lines_sum_to_subtotal(lines, invoice["subtotal_cents"])

    def test_the_admin_fee_rounds_a_second_time_off_the_integer_subtotal(self, api):
        """5142 cents at 8.5 percent is 437.07, so the fee is 437 and the total 5579.

        PRD 3.9: "The invoice then totals: `subtotal_cents` is the sum of the
        already-rounded `amount_cents` of every line; `admin_fee_cents` is that integer
        subtotal multiplied by the employer's `admin_fee_pct` and rounded to a whole
        cent; `total_cents` is the subtotal plus the fee."

        Design: Difficulty/combinatorial_formula/invoice_rounds_each_line_then_sums_never_5143
        """
        world = self._two_completed_visits(api)

        invoice = create_invoice(api, world["employer"]["id"], "2026-08-01", "2026-08-31")
        assert invoice["admin_fee_cents"] == 437
        assert invoice["total_cents"] == 5579
        assert_invoice_totals(invoice, 0.085)

        assert invoice["copay_cents"] == 5142
        assert invoice["overage_cents"] == 0
        assert invoice["penalty_cents"] == 0
        assert invoice["reservation_count"] == 2
        assert invoice["invoice_status"] == "DRAFT"
        assert invoice["issued_at"] is None

        for visit in (world["first"], world["second"]):
            assert read_reservation(api, visit["id"])["billing_status"] == "INVOICED"


class TestEmptyInvoiceIssueGuards:
    """The same empty invoice answers with a fiscal code, then with a terminal one."""

    @staticmethod
    def _empty_invoice(api) -> Dict[str, Any]:
        employer = create_employer(
            api, name="Emptyco Holdings", industry_code="HOLDING", admin_fee_pct=0.085
        )
        invoice = create_invoice(api, employer["id"], "2026-08-01", "2026-08-31")
        return {"employer": employer, "invoice": invoice}

    def test_a_draft_invoice_with_no_lines_is_refused_as_empty(self, api):
        """While the state is still legal, the money band is the one that fires.

        PRD 3.9: "issuance requires at least one line, so an invoice whose `line_count`
        is 0 (equivalently, whose `total_cents` is 0 because the period produced no
        non-zero billable component) is refused with `ERR_INVOICE_EMPTY`"

        Design: Difficulty/priority_pair_validation_conflict/issue_void_empty_invoice_returns_terminal_state_not_invoice_empty
        """
        world = self._empty_invoice(api)
        invoice = world["invoice"]

        assert invoice["invoice_status"] == "DRAFT"
        assert invoice["line_count"] == 0
        assert invoice["subtotal_cents"] == 0
        assert invoice["total_cents"] == 0
        assert read_invoice_lines(api, invoice["id"]) == []

        refused = api.issue_invoice(invoice["id"], NETWORK_ADMIN)
        validate_error(refused, ApiErrorId.ERR_INVOICE_EMPTY.value, 409)

        unchanged = read_invoice(api, invoice["id"])
        assert unchanged["invoice_status"] == "DRAFT"
        assert unchanged["issued_at"] is None

    def test_once_void_the_same_issue_returns_terminal_rather_than_empty(self, api):
        """Two violated rules, one answer: the lifecycle band outranks the money band.

        PRD 2.8: "When a single request violates more than one rule, exactly one error
        is returned, and which one is fully determined."

        PRD 2.8: "The target entity's current state must permit the requested
        transition, yielding that entity's `..._STATE_INVALID` code; when the current
        state is a terminal state of that machine, the terminal code is returned instead
        and the transition-permitted check stands down."

        PRD 3.9: "touching an invoice already `PAID` or `VOID` returns
        `ERR_EMPLOYERINVOICE_TERMINAL`"

        Design: Difficulty/priority_pair_validation_conflict/issue_void_empty_invoice_returns_terminal_state_not_invoice_empty
        """
        world = self._empty_invoice(api)
        invoice_id = world["invoice"]["id"]

        voided = void_invoice(api, invoice_id, void_reason_code="CREATED_IN_ERROR")
        assert voided["invoice_status"] == "VOID"
        assert voided["void_reason_code"] == "CREATED_IN_ERROR"
        assert voided["total_cents"] == 0
        assert voided["line_count"] == 0

        refused = api.issue_invoice(invoice_id, NETWORK_ADMIN)
        validate_error(refused, ApiErrorId.ERR_EMPLOYERINVOICE_TERMINAL.value, 409)
        assert refused.json()["data"]["error_id"] != ApiErrorId.ERR_INVOICE_EMPTY.value

        after = read_invoice(api, invoice_id)
        assert after["invoice_status"] == "VOID"
        assert after["issued_at"] is None


class TestMoneyLedgerSurvivesIssueAndVoid:
    """One overage accrual and one no-show charge, watched across a whole round trip."""

    LEDGER_CENTS_TOTAL = 52000

    @staticmethod
    def _accrued_month(api) -> Dict[str, Any]:
        world = setup_matchable_world(
            api,
            care_start_utc="2026-08-10T09:00:00Z",
            care_end_utc="2026-08-10T15:00:00Z",
            block_start_utc="2026-08-10T08:00:00Z",
            block_end_utc="2026-08-10T18:00:00Z",
            market_code="MKT-MSP",
            total_slots=6,
            dependent_count=3,
            employer_overrides=dict(FEE_EMPLOYER),
            plan_overrides=dict(CONSERVATION_PLAN),
        )
        assert read_employer(api, world["employer"]["id"])["ytd_billed_cents"] == 0

        second_block = create_capacity_block(
            api,
            world["provider"]["id"],
            "2026-08-11T08:00:00Z",
            "2026-08-11T18:00:00Z",
            total_slots=6,
        )

        match_reservation(api, world["reservation"]["id"])
        confirmed = confirm_reservation(api, world["reservation"]["id"], world["block"]["id"])
        assert confirmed["covered_days"] == pytest.approx(1, abs=0.01)
        assert confirmed["overage_days"] == pytest.approx(2, abs=0.01)
        assert confirmed["overage_tier_multiplier"] == pytest.approx(1.00, abs=0.01)
        world["completed"] = drive_to_completed(
            api,
            world["reservation"]["id"],
            "2026-08-10T09:00:00Z",
            "2026-08-10T15:00:00Z",
            check_in_clock="2026-08-10T09:00:00Z",
            complete_clock="2026-08-10T15:00:00Z",
        )

        second = create_reservation(
            api,
            world["employee"]["id"],
            world["dependent_ids"][:1],
            "2026-08-11T09:00:00Z",
            "2026-08-11T15:00:00Z",
            market_code="MKT-MSP",
        )
        match_reservation(api, second["id"])
        second = confirm_reservation(api, second["id"], second_block["id"])
        assert second["covered_days"] == pytest.approx(0, abs=0.01)
        assert second["overage_cents"] == 20000

        set_clock(api, "2026-08-11T09:00:00Z")
        world["no_showed"] = mark_no_show(api, second["id"], reason_code="FAMILY_DID_NOT_ARRIVE")
        return world

    def test_the_sweep_bills_four_lines_and_leaves_the_ledger_alone(self, api):
        """A zero-quantity copay line is suppressed while the overage line survives.

        PRD 3.9: "A `COMPLETED` or `NO_SHOW` reservation emits a `CARE_COPAY` line whose
        `quantity` is its covered billed quantity (covered days for centre-based care,
        covered hours for in-home) and whose `unit_cents` is the corresponding pinned
        copay rate, plus a `CARE_OVERAGE` line whose `quantity` is its overage billed
        quantity and whose `unit_cents` is the tier-multiplied overage unit rate already
        rounded during stage four."

        PRD 3.9: "A line whose computed amount would be zero is not written at all."

        Design: Difficulty/compensating_invariant/employer_money_ledger_survives_invoice_issue_and_void
        """
        world = self._accrued_month(api)

        assert world["completed"]["copay_cents"] == 1500
        assert world["completed"]["overage_cents"] == 40000
        assert world["no_showed"]["penalty_cents"] == 12000

        invoice = create_invoice(api, world["employer"]["id"], "2026-08-01", "2026-08-31")
        assert invoice["line_count"] == 4
        assert invoice["reservation_count"] == 2
        assert invoice["copay_cents"] == 1500
        assert invoice["overage_cents"] == 60000
        assert invoice["penalty_cents"] == 12000
        assert invoice["subtotal_cents"] == 73500
        assert invoice["admin_fee_cents"] == 6248
        assert invoice["total_cents"] == 79748
        assert invoice["invoice_status"] == "DRAFT"

        lines = read_invoice_lines(api, invoice["id"])
        assert sorted(line["line_type"] for line in lines) == [
            "CARE_COPAY",
            "CARE_OVERAGE",
            "CARE_OVERAGE",
            "NO_SHOW_CHARGE",
        ]
        assert_lines_sum_to_subtotal(lines, 73500)

        entries = read_employee_ledger(api, world["employee"]["id"])
        assert_cents_conservation(entries, self.LEDGER_CENTS_TOTAL)
        assert read_employer(api, world["employer"]["id"])[
            "accrued_overage_cents_current_period"
        ] == 40000

    def test_issuing_moves_the_year_to_date_total_but_no_ledger_row(self, api):
        """ytd_billed_cents becomes the invoice total; the money ledger stays at 52000.

        PRD 2.2: "`ytd_billed_cents` is the sum of `total_cents` over this employer's
        invoices whose `invoice_status` is `ISSUED` or `PAID`."

        Design: Difficulty/compensating_invariant/employer_money_ledger_survives_invoice_issue_and_void
        """
        world = self._accrued_month(api)
        invoice = create_invoice(api, world["employer"]["id"], "2026-08-01", "2026-08-31")

        issued = issue_invoice(api, invoice["id"])
        assert issued["invoice_status"] == "ISSUED"
        assert issued["total_cents"] == 79748

        employer = read_employer(api, world["employer"]["id"])
        assert employer["ytd_billed_cents"] == 79748
        assert employer["accrued_overage_cents_current_period"] == 40000

        for reservation_id in (world["completed"]["id"], world["no_showed"]["id"]):
            assert read_reservation(api, reservation_id)["billing_status"] == "INVOICED"

        entries = read_employee_ledger(api, world["employee"]["id"])
        assert_cents_conservation(entries, self.LEDGER_CENTS_TOTAL)
        money_rows = [row for row in entries if row["cents_delta"] != 0]
        assert [row["entry_type"] for row in money_rows] == [
            "OVERAGE_ACCRUE",
            "NO_SHOW_CHARGE",
        ]
        assert [row["cents_delta"] for row in money_rows] == [40000, 12000]

    def test_voiding_restores_the_sweep_without_disturbing_a_single_entry(self, api):
        """The void zeroes the invoice, returns both rows to ACCRUED and re-sweeps identically.

        PRD 3.9: "It records the reason code, deletes every line of the invoice, zeroes
        `copay_cents`, `overage_cents`, `penalty_cents`, `subtotal_cents`,
        `admin_fee_cents`, `total_cents`, `line_count` and `reservation_count`, and
        returns every billed reservation's `billing_status` from `INVOICED` to `ACCRUED`
        so it can be swept into a corrected invoice."

        PRD 3.9: "Critically, voiding appends no ledger entry and removes none, which is
        exactly why the employer money-conservation invariant survives a
        draft-issue-void round trip."

        Design: Difficulty/compensating_invariant/employer_money_ledger_survives_invoice_issue_and_void
        """
        world = self._accrued_month(api)
        invoice = create_invoice(api, world["employer"]["id"], "2026-08-01", "2026-08-31")
        issue_invoice(api, invoice["id"])

        voided = void_invoice(api, invoice["id"], void_reason_code="PERIOD_RESTATED")
        assert voided["invoice_status"] == "VOID"
        assert voided["void_reason_code"] == "PERIOD_RESTATED"
        for field in (
            "copay_cents",
            "overage_cents",
            "penalty_cents",
            "subtotal_cents",
            "admin_fee_cents",
            "total_cents",
            "line_count",
            "reservation_count",
        ):
            assert voided[field] == 0, field
        assert read_invoice_lines(api, invoice["id"]) == []

        employer = read_employer(api, world["employer"]["id"])
        assert employer["ytd_billed_cents"] == 0
        assert employer["accrued_overage_cents_current_period"] == 40000

        for reservation_id in (world["completed"]["id"], world["no_showed"]["id"]):
            assert read_reservation(api, reservation_id)["billing_status"] == "ACCRUED"

        entries = read_employee_ledger(api, world["employee"]["id"])
        assert_cents_conservation(entries, self.LEDGER_CENTS_TOTAL)
        assert len([row for row in entries if row["cents_delta"] != 0]) == 2

        corrected = create_invoice(api, world["employer"]["id"], "2026-08-01", "2026-08-31")
        assert corrected["id"] != invoice["id"]
        assert corrected["line_count"] == 4
        assert corrected["subtotal_cents"] == 73500
        assert corrected["admin_fee_cents"] == 6248
        assert corrected["total_cents"] == 79748


class TestPaymentMustMatchTheInvoiceTotal:
    def test_only_the_exact_1628_cents_settles_a_1628_cent_invoice(self, api):
        """Underpayment and overpayment are refused with the same fiscal code.

        PRD 3.9: "A `network_admin` or `benefits_admin` then records payment by
        supplying `paid_amount_cents`, which must equal `total_cents` exactly
        (`ERR_PAYMENT_AMOUNT_MISMATCH`); payment records that amount, moves every billed
        reservation's `billing_status` from `INVOICED` to `PAID`, and recomputes
        `ytd_billed_cents`."

        Design: Corner/endpoints/corner_payment_amount_must_equal_invoice_total
        """
        world = setup_matchable_world(
            api,
            care_start_utc="2026-08-05T09:00:00Z",
            care_end_utc="2026-08-05T15:00:00Z",
            block_start_utc="2026-08-05T08:00:00Z",
            block_end_utc="2026-08-05T18:00:00Z",
            market_code="MKT-DTW",
            total_slots=4,
            employer_overrides=dict(FEE_EMPLOYER),
            plan_overrides=dict(EXACT_CHANGE_PLAN),
        )
        match_reservation(api, world["reservation"]["id"])
        confirm_reservation(api, world["reservation"]["id"], world["block"]["id"])
        completed = drive_to_completed(
            api,
            world["reservation"]["id"],
            "2026-08-05T09:00:00Z",
            "2026-08-05T15:00:00Z",
            check_in_clock="2026-08-05T08:30:00Z",
            complete_clock="2026-08-05T15:00:00Z",
        )
        assert completed["copay_cents"] == 1500
        assert completed["billing_status"] == "ACCRUED"

        invoice = create_invoice(api, world["employer"]["id"], "2026-08-01", "2026-08-31")
        assert invoice["line_count"] == 1
        assert invoice["subtotal_cents"] == 1500
        assert invoice["admin_fee_cents"] == 128
        assert invoice["total_cents"] == 1628

        issued = issue_invoice(api, invoice["id"])
        assert issued["invoice_status"] == "ISSUED"
        assert str(issued["issued_at"]).startswith("2026-08-05T15:00:00")

        too_little = api.pay_invoice(invoice["id"], payment_payload(1500), BENEFITS_ADMIN)
        validate_error(too_little, ApiErrorId.ERR_PAYMENT_AMOUNT_MISMATCH.value, 409)

        too_much = api.pay_invoice(invoice["id"], payment_payload(1629), BENEFITS_ADMIN)
        validate_error(too_much, ApiErrorId.ERR_PAYMENT_AMOUNT_MISMATCH.value, 409)

        still_issued = read_invoice(api, invoice["id"])
        assert still_issued["invoice_status"] == "ISSUED"
        assert still_issued["paid_amount_cents"] == 0

        settled = validate_success(
            api.pay_invoice(invoice["id"], payment_payload(1628), BENEFITS_ADMIN)
        )
        assert settled["invoice_status"] == "PAID"
        assert settled["paid_amount_cents"] == 1628

        assert read_reservation(api, completed["id"])["billing_status"] == "PAID"
        assert read_employer(api, world["employer"]["id"])["ytd_billed_cents"] == 1628


class TestUtilizationReportScope:
    def test_intake_and_cancelled_rows_feed_none_of_the_counters(self, api):
        """Three reservations inside the window, one visible to the analytics.

        PRD 3.9: "though rows sitting in `INTAKE`, `MATCHING`, `OFFERED`, `CANCELLED` or
        `UNFULFILLED` contribute to none of the counters"

        PRD 3.9: "`min_provider_lifetime_score` is the smallest `lifetime_quality_score`
        among the providers matched to the `COMPLETED` and `NO_SHOW` rows, and is null
        when that set is empty."

        Design: Corner/calculations/corner_utilization_report_ignores_intake_and_cancelled_rows
        """
        world = setup_matchable_world(
            api,
            care_start_utc="2026-08-05T09:00:00Z",
            care_end_utc="2026-08-05T15:00:00Z",
            block_start_utc="2026-08-05T08:00:00Z",
            block_end_utc="2026-08-05T18:00:00Z",
            market_code="MKT-BOS",
            total_slots=4,
            employer_overrides=dict(FEE_EMPLOYER),
            plan_overrides=dict(EXACT_CHANGE_PLAN),
        )
        employer_id = world["employer"]["id"]

        left_in_intake = create_reservation(
            api,
            world["employee"]["id"],
            world["dependent_ids"],
            "2026-08-06T09:00:00Z",
            "2026-08-06T15:00:00Z",
            market_code="MKT-BOS",
        )
        cancelled_from_intake = create_reservation(
            api,
            world["employee"]["id"],
            world["dependent_ids"],
            "2026-08-07T09:00:00Z",
            "2026-08-07T15:00:00Z",
            market_code="MKT-BOS",
        )
        cancel(api, cancelled_from_intake["id"], cancel_reason_code="SCHOOL_REOPENED")

        match_reservation(api, world["reservation"]["id"])
        confirm_reservation(api, world["reservation"]["id"], world["block"]["id"])
        completed = drive_to_completed(
            api,
            world["reservation"]["id"],
            "2026-08-05T09:00:00Z",
            "2026-08-05T15:00:00Z",
            check_in_clock="2026-08-05T08:30:00Z",
            complete_clock="2026-08-05T15:00:00Z",
        )
        assert completed["fulfillment_status"] == "COMPLETED"
        assert completed["covered_days"] == pytest.approx(1, abs=0.01)
        assert read_reservation(api, left_in_intake["id"])["fulfillment_status"] == "INTAKE"
        assert (
            read_reservation(api, cancelled_from_intake["id"])["fulfillment_status"]
            == "CANCELLED"
        )

        report = validate_success(
            api.get_utilization_report(
                employer_id,
                NETWORK_ADMIN,
                {"period_start": "2026-08-01", "period_end": "2026-08-31"},
            )
        )
        assert_utilization_report(report)
        assert report["reservations_confirmed"] == 1
        assert report["reservations_completed"] == 1
        assert report["no_show_count"] == 0
        assert report["no_show_rate_pct"] == pytest.approx(0, abs=0.01)
        assert report["days_used"] == pytest.approx(1, abs=0.01)
        assert report["days_overage"] == pytest.approx(0, abs=0.01)
        assert report["unique_employees_served"] == 1
        assert report["center_share_pct"] == pytest.approx(100.00, abs=0.01)
        assert report["in_home_share_pct"] == pytest.approx(0.00, abs=0.01)
        assert report["min_provider_lifetime_score"] == pytest.approx(100, abs=0.0001)
        assert report["renewal_risk_band"] == "LOW"

        later = validate_success(
            api.get_utilization_report(
                employer_id,
                NETWORK_ADMIN,
                {"period_start": "2026-08-06", "period_end": "2026-08-31"},
            )
        )
        assert later["reservations_confirmed"] == 0
        assert later["reservations_completed"] == 0
        assert later["days_used"] == pytest.approx(0, abs=0.01)
        assert later["min_provider_lifetime_score"] is None
        assert later["renewal_risk_band"] == "LOW"
