"""Subawards and invoice monitoring: review cycle, MTDC cap, overlap
semantics, cumulative ceiling, audit reference, and the prime mirror (PRD §3.5)."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    api_client, TEST_USERS,
    setup_prime_with_subaward, record_invoice,
    ApiErrorId,
)

SPO = TEST_USERS["spo_headers"]
GC = TEST_USERS["coordinator_headers"]
GA = TEST_USERS["accountant_headers"]


class TestSubawardInvoiceClosedIntervalSharedDay:
    """Difficulty instance: closed-interval overlap on invoice periods."""

    def _setup(self, api):
        (_sp, _pi, award, _lines, sb) = setup_prime_with_subaward(
            "PW-001", 9_000_000, 2_500_000, 500_000, 11_000_000, 9_000_000)
        record_invoice(sb["id"], "INV-1", "2026-01-01T00:00:00Z",
                       "2026-03-31T00:00:00Z", 1000, 0)
        record_invoice(sb["id"], "INV-2", "2026-04-01T00:00:00Z",
                       "2026-06-30T00:00:00Z", 1000, 0)
        return sb

    def test_back_to_back_periods_accepted(self, api):
        """PRD §3.5: "Invoice windows are closed intervals — both endpoints
        included — so two invoices sharing even a boundary day overlap; a new
        invoice's window must not overlap any non-`REJECTED` invoice of the
        same subaward (`ERR_INVOICE_PERIOD_OVERLAP`) and must lie fully within
        the subaward's closed period (`ERR_INVOICE_PERIOD_OUT_OF_RANGE`)."

        Design: Difficulty/resource_temporal_overlap/subaward_invoice_closed_interval_shared_day
        """
        sb = self._setup(api)
        invoices = validate_success(api.list_subaward_invoices(
            GA, params={"subaward_id": sb["id"]}), 200)
        # [01-01,03-31] and [04-01,06-30] share no day -> both recorded.
        assert len(invoices) == 2

    def test_shared_boundary_day_rejected(self, api):
        """PRD §3.5: "Invoice windows are closed intervals — both endpoints
        included — so two invoices sharing even a boundary day overlap; a new
        invoice's window must not overlap any non-`REJECTED` invoice of the
        same subaward (`ERR_INVOICE_PERIOD_OVERLAP`) and must lie fully within
        the subaward's closed period (`ERR_INVOICE_PERIOD_OUT_OF_RANGE`)."

        Design: Difficulty/resource_temporal_overlap/subaward_invoice_closed_interval_shared_day
        """
        sb = self._setup(api)
        res = api.create_subaward_invoice(
            {"subaward_id": sb["id"], "invoice_number": "INV-3",
             "period_start": "2026-03-31T00:00:00Z",
             "period_end": "2026-04-01T00:00:00Z",
             "current_period_direct_cents": 1000,
             "current_period_f_and_a_cents": 0}, GC)
        validate_error(res, ApiErrorId.ERR_INVOICE_PERIOD_OVERLAP.value)


class TestTemporalBeatsConstraintOnInvoiceCreate:
    """Difficulty instance: temporal range error beats the overlap error."""

    def _setup(self, api):
        (_sp, _pi, award, _lines, sb) = setup_prime_with_subaward(
            "P2-001", 9_000_000, 2_500_000, 500_000, 11_000_000, 9_000_000)
        record_invoice(sb["id"], "INV-1", "2026-11-01T00:00:00Z",
                       "2026-12-31T00:00:00Z", 1_000_000, 50_000)
        return sb

    def test_out_of_range_beats_overlap(self, api):
        """PRD §2.7: "(9) temporal rules (period-of-performance, invoice
        period range, NCE timing, closeout timing, cycle openability)" precede
        "(10) structural constraints (window overlaps, uniqueness, zero-sum
        rebudget, system-managed lines and types, variance note, effort
        totals)".
        PRD §3.5: "a new invoice's window must not overlap any non-`REJECTED`
        invoice of the same subaward (`ERR_INVOICE_PERIOD_OVERLAP`) and must
        lie fully within the subaward's closed period
        (`ERR_INVOICE_PERIOD_OUT_OF_RANGE`)."

        Design: Difficulty/priority_pair_validation_conflict/temporal_beats_constraint_on_invoice_create
        """
        sb = self._setup(api)
        res = api.create_subaward_invoice(
            {"subaward_id": sb["id"], "invoice_number": "INV-2",
             "period_start": "2026-12-15T00:00:00Z",
             "period_end": "2027-02-15T00:00:00Z",
             "current_period_direct_cents": 500_000,
             "current_period_f_and_a_cents": 25_000}, GC)
        validate_error(res, ApiErrorId.ERR_INVOICE_PERIOD_OUT_OF_RANGE.value)

    def test_in_range_overlap_returns_overlap_error(self, api):
        """PRD §3.5: "a new invoice's window must not overlap any
        non-`REJECTED` invoice of the same subaward
        (`ERR_INVOICE_PERIOD_OVERLAP`) and must lie fully within the
        subaward's closed period (`ERR_INVOICE_PERIOD_OUT_OF_RANGE`)."

        Design: Difficulty/priority_pair_validation_conflict/temporal_beats_constraint_on_invoice_create
        """
        sb = self._setup(api)
        # Fully inside the subaward period but overlapping INV-1: only the
        # overlap rule can fire.
        res = api.create_subaward_invoice(
            {"subaward_id": sb["id"], "invoice_number": "INV-2",
             "period_start": "2026-12-15T00:00:00Z",
             "period_end": "2026-12-31T00:00:00Z",
             "current_period_direct_cents": 500_000,
             "current_period_f_and_a_cents": 25_000}, GC)
        validate_error(res, ApiErrorId.ERR_INVOICE_PERIOD_OVERLAP.value)


class TestSubawardInvoiceReturnResubmitCycle:
    """Difficulty instance: UNDER_REVIEW -> RETURNED_FOR_REVISION ->
    UNDER_REVIEW loop with chronological MTDC recomputation."""

    def _setup(self, api):
        (_sp, _pi, award, lines, sb) = setup_prime_with_subaward(
            "P-001", 4_000_000, 2_500_000, 1_000_000, 6_750_000, 4_000_000)
        inv = record_invoice(sb["id"], "INV-1", "2026-02-01T00:00:00Z",
                             "2026-04-30T00:00:00Z", 3_000_000, 150_000)
        get_success_data(api.begin_review_invoice(inv["id"], SPO))
        return award, lines, sb, inv

    def test_return_and_resubmit_states_and_recompute(self, api):
        """PRD §3.5: "From there the officer may reject the invoice —
        terminal, setting `return_reason`, decrementing
        `invoiced_to_date_cents`, and excluding the invoice from cumulative and
        overlap checks — or return it for revision, also setting
        `return_reason`, which lets a coordinator resubmit with revised
        `current_period_direct_cents` and `current_period_f_and_a_cents` and
        optionally revised `period_start` and `period_end`."
        PRD §3.5: "Resubmission re-checks the overlap and cumulative-ceiling
        rules against the revised figures (`ERR_INVOICE_PERIOD_OVERLAP`,
        `ERR_SUBAWARD_BUDGET_EXCEEDED`), recomputes `cumulative_direct_cents`
        and `mtdc_portion_cents`, refreshes `invoiced_to_date_cents`, and moves
        the invoice back to `UNDER_REVIEW`."

        Design: Difficulty/non_linear_state_machine/subaward_invoice_return_resubmit_cycle
        """
        award, lines, sb, inv = self._setup(api)
        returned = validate_success(api.return_invoice_for_revision(
            inv["id"], {"return_reason": "backup documentation incomplete"}, SPO), 200)
        assert returned["status"] == "RETURNED_FOR_REVISION"
        resubmitted = validate_success(api.resubmit_invoice(
            inv["id"], {"current_period_direct_cents": 2_900_000,
                        "current_period_f_and_a_cents": 145_000}, GC), 200)
        assert resubmitted["status"] == "UNDER_REVIEW"
        assert resubmitted["cumulative_direct_cents"] == 2_900_000
        # min(2900000, 2500000) - min(0, 2500000) = 2500000: cap still binds.
        assert resubmitted["mtdc_portion_cents"] == 2_500_000

    def test_approve_after_resubmit_posts_prime_mirror(self, api):
        """PRD §3.5: "On success the system creates a prime expenditure of type
        `SUBAWARD_PAYMENT` with `amount_cents` equal to direct plus sub-F&A,
        `mtdc_eligible_cents` equal to the invoice's `mtdc_portion_cents`,
        status `POSTED`, and `cash_disbursed` true; debits the prime
        `SUBAWARDS` line; recomputes the prime award's MTDC, F&A accrual, and
        draw pools; updates the subaward's `invoiced_to_date_cents` and
        `mtdc_consumed_cents`; stamps the invoice's `prime_expenditure_id` with
        the mirror's id; and moves the invoice to `PAID`."

        Design: Difficulty/non_linear_state_machine/subaward_invoice_return_resubmit_cycle
        """
        award, lines, sb, inv = self._setup(api)
        api.return_invoice_for_revision(inv["id"], {"return_reason": "backup documentation incomplete"}, SPO)
        api.resubmit_invoice(inv["id"], {"current_period_direct_cents": 2_900_000,
                                         "current_period_f_and_a_cents": 145_000}, GC)
        paid = validate_success(api.approve_invoice(inv["id"], {}, SPO), 200)
        assert paid["status"] == "PAID"
        sub_line = validate_success(api.get_budget_line(lines["SUBAWARDS"]["id"], GA), 200)
        assert sub_line["spent_cents"] == 3_045_000     # 2900000 + 145000
        award_after = validate_success(api.get_award(award["id"], GA), 200)
        assert award_after["mtdc_spent_cents"] == 2_500_000
        assert award_after["f_and_a_accrued_cents"] == 1_250_000  # round(0.5*2500000)


class TestSubawardMtdcCapSecondInvoiceZero:
    def test_mtdc_cap_chronological_exhaustion(self, api):
        """PRD §3.5: "Two computed fields track the federal MTDC cap on
        subawards, and they are computed chronologically: order the subaward's
        non-`REJECTED` invoices by `period_start` ascending, breaking ties by
        `created_at` ascending — never by id. Each invoice's
        `cumulative_direct_cents` is the sum of `current_period_direct_cents`
        over invoices up to and including itself in that order. Its
        `mtdc_portion_cents` is the slice of this invoice's direct that still
        fits under the 2,500,000-cent cap: the cumulative direct capped at
        2,500,000, minus the cumulative direct excluding this invoice similarly
        capped."

        Design: Corner/calculations/subaward_mtdc_cap_second_invoice_zero
        """
        (_sp, _pi, award, _lines, sb) = setup_prime_with_subaward(
            "MC-001", 4_000_000, 2_500_000, 1_000_000, 6_750_000, 4_000_000)
        i1 = record_invoice(sb["id"], "INV-1", "2026-02-01T00:00:00Z",
                            "2026-04-30T00:00:00Z", 3_000_000, 150_000)
        i2 = record_invoice(sb["id"], "INV-2", "2026-05-01T00:00:00Z",
                            "2026-07-31T00:00:00Z", 800_000, 40_000)
        assert i1["mtdc_portion_cents"] == 2_500_000    # min(3000000, cap) - 0
        assert i2["cumulative_direct_cents"] == 3_800_000
        assert i2["mtdc_portion_cents"] == 0            # cap already exhausted


class TestInvoiceApproveRequiresSubawardActive:
    """Difficulty instance: invoice approve gated on the parent subaward."""

    def _setup(self, api):
        (_sp, _pi, award, _lines, sb) = setup_prime_with_subaward(
            "PB-001", 500_000, 250_000, 500_000, 1_375_000, 500_000,
            activate_subaward=False)
        inv = record_invoice(sb["id"], "INV-1", "2026-02-01T00:00:00Z",
                             "2026-03-31T00:00:00Z", 100_000, 5_000)
        get_success_data(api.begin_review_invoice(inv["id"], SPO))
        return sb, inv

    def test_approve_rejected_while_subaward_draft(self, api):
        """PRD §3.5: "Approval pays the invoice and posts the cost onto the
        prime award in one atomic step."
        PRD §3.5: "The subaward must be `ACTIVE` (`ERR_SUBAWARD_NOT_ACTIVE`);
        the prime award must be `ACTIVE` (`ERR_AWARD_NOT_ACTIVE`) with posture
        other than `FROZEN` (`ERR_AWARD_FROZEN`); a `HIGH`-risk subaward
        requires `audit_reference` at approval time
        (`ERR_AUDIT_REFERENCE_REQUIRED`); and the prime award's `SUBAWARDS`
        line must fit — its `spent_cents` plus the invoice's direct plus
        sub-F&A must not exceed `authorized_cents`
        (`ERR_BUDGET_LINE_EXCEEDED`)."

        Design: Difficulty/cross_entity_state_dependency/invoice_approve_requires_subaward_active
        """
        sb, inv = self._setup(api)
        res = api.approve_invoice(inv["id"], {}, SPO)
        validate_error(res, ApiErrorId.ERR_SUBAWARD_NOT_ACTIVE.value)

    def test_approve_succeeds_after_subaward_activation(self, api):
        """PRD §3.5: "Activation requires the prime award to be `ACTIVE`
        (`ERR_AWARD_NOT_ACTIVE`) and moves the subaward `DRAFT → ACTIVE`.";
        "On success ... moves the invoice to `PAID`."

        Design: Difficulty/cross_entity_state_dependency/invoice_approve_requires_subaward_active
        """
        sb, inv = self._setup(api)
        validate_success(api.activate_subaward(sb["id"], SPO), 200)
        paid = validate_success(api.approve_invoice(inv["id"], {}, SPO), 200)
        assert paid["status"] == "PAID"


class TestDuplicateInvoiceNumber:
    def test_duplicate_invoice_number_within_subaward(self, api):
        """PRD §3.5: "Invoices arrive from the subrecipient and are
        recorded by a coordinator with `subaward_id`, an `invoice_number`
        unique within the subaward among non-`REJECTED` invoices
        (`ERR_DUPLICATE_INVOICE_NUMBER`), a billing window `period_start` to
        `period_end` (end at or after start), `current_period_direct_cents` and
        `current_period_f_and_a_cents` (both zero or more), and optionally
        `audit_reference`."

        Design: Corner/errors/duplicate_invoice_number_within_subaward
        """
        (_sp, _pi, award, _lines, sb1) = setup_prime_with_subaward(
            "DN-001", 9_000_000, 2_500_000, 500_000, 11_000_000, 4_000_000)
        sb2 = get_success_data(api.create_subaward(
            {"award_id": award["id"], "subrecipient_name": "Sub Two",
             "total_subaward_cents": 4_000_000, "risk_rating": "LOW",
             "start_date": "2026-01-01T00:00:00Z",
             "end_date": "2026-12-31T00:00:00Z"}, SPO))
        record_invoice(sb1["id"], "INV-1", "2026-02-01T00:00:00Z",
                       "2026-03-31T00:00:00Z", 1000, 0)
        res = api.create_subaward_invoice(
            {"subaward_id": sb1["id"], "invoice_number": "INV-1",
             "period_start": "2026-04-01T00:00:00Z",
             "period_end": "2026-05-31T00:00:00Z",
             "current_period_direct_cents": 1000,
             "current_period_f_and_a_cents": 0}, GC)
        validate_error(res, ApiErrorId.ERR_DUPLICATE_INVOICE_NUMBER.value)
        ok = validate_success(api.create_subaward_invoice(
            {"subaward_id": sb2["id"], "invoice_number": "INV-1",
             "period_start": "2026-02-01T00:00:00Z",
             "period_end": "2026-03-31T00:00:00Z",
             "current_period_direct_cents": 1000,
             "current_period_f_and_a_cents": 0}, GC), 201)
        assert ok["invoice_number"] == "INV-1"


class TestHighRiskAuditReference:
    def _setup(self, api):
        (_sp, _pi, award, _lines, sbh) = setup_prime_with_subaward(
            "HR-001", 9_000_000, 2_500_000, 500_000, 11_000_000, 2_000_000,
            risk_rating="HIGH")
        sbm = get_success_data(api.create_subaward(
            {"award_id": award["id"], "subrecipient_name": "Calm U",
             "total_subaward_cents": 2_000_000, "risk_rating": "MEDIUM",
             "start_date": "2026-01-01T00:00:00Z",
             "end_date": "2026-12-31T00:00:00Z"}, SPO))
        get_success_data(api.activate_subaward(sbm["id"], SPO))
        ih = record_invoice(sbh["id"], "H-1", "2026-02-01T00:00:00Z",
                            "2026-03-31T00:00:00Z", 100_000, 5_000)
        get_success_data(api.begin_review_invoice(ih["id"], SPO))
        im = record_invoice(sbm["id"], "M-1", "2026-02-01T00:00:00Z",
                            "2026-03-31T00:00:00Z", 100_000, 5_000)
        get_success_data(api.begin_review_invoice(im["id"], SPO))
        return ih, im

    def test_high_risk_approve_requires_audit_reference(self, api):
        """PRD §3.5: "a `HIGH`-risk subaward requires `audit_reference` at
        approval time (`ERR_AUDIT_REFERENCE_REQUIRED`); and the prime award's
        `SUBAWARDS` line must fit — its `spent_cents` plus the invoice's direct
        plus sub-F&A must not exceed `authorized_cents`
        (`ERR_BUDGET_LINE_EXCEEDED`)."

        Design: Corner/errors/high_risk_subaward_approve_requires_audit_reference
        """
        ih, _im = self._setup(api)
        res = api.approve_invoice(ih["id"], {}, SPO)
        validate_error(res, ApiErrorId.ERR_AUDIT_REFERENCE_REQUIRED.value)

    def test_medium_risk_approves_without_and_high_risk_with_reference(self, api):
        """PRD §3.5: "a `HIGH`-risk subaward requires `audit_reference` at
        approval time (`ERR_AUDIT_REFERENCE_REQUIRED`); and the prime award's
        `SUBAWARDS` line must fit — its `spent_cents` plus the invoice's direct
        plus sub-F&A must not exceed `authorized_cents`
        (`ERR_BUDGET_LINE_EXCEEDED`)."
        PRD §3.5: "On success the system creates a prime expenditure of type
        `SUBAWARD_PAYMENT` with `amount_cents` equal to direct plus sub-F&A,
        `mtdc_eligible_cents` equal to the invoice's `mtdc_portion_cents`,
        status `POSTED`, and `cash_disbursed` true; debits the prime
        `SUBAWARDS` line; recomputes the prime award's MTDC, F&A accrual, and
        draw pools; updates the subaward's `invoiced_to_date_cents` and
        `mtdc_consumed_cents`; stamps the invoice's `prime_expenditure_id` with
        the mirror's id; and moves the invoice to `PAID`."

        Design: Corner/errors/high_risk_subaward_approve_requires_audit_reference
        """
        ih, im = self._setup(api)
        paid_m = validate_success(api.approve_invoice(im["id"], {}, SPO), 200)
        assert paid_m["status"] == "PAID"
        paid_h = validate_success(api.approve_invoice(
            ih["id"], {"audit_reference": "FY26-single-audit-44"}, SPO), 200)
        assert paid_h["status"] == "PAID"
