"""Invoicing: provisional vs audited billing, per-line rounding order,
parallel state dimensions, period overlap, void lockdown, and certify gating."""
from test_helpers import (
    ApiErrorId, assert_invoice, assert_invoice_money_invariant, constants,
    create_approved_campaign, make_auditor_headers, make_sales_manager_headers,
    make_theater_ops_headers, setup_played_slot, validate_error,
    validate_success,
)
from test_helpers.factories import (
    create_invoice_payload,
)
from test_helpers.fixtures import (
    AUDITOR_1, SM_APPROVER, SM_CREATOR, create_showtime_with_reel,
    dispatch_and_deliver, lock_reel, record_playlog, reserve_slot, set_clock,
    setup_certified_invoice, setup_confirmed_slot,
    setup_theater_screen_feature, submit_and_accept_attendance,
)


class TestProvisionalVsAuditedBilling:
    def test_invoice_provisional_snapshot_at_creation(self, api):
        """PRD §3.6: "`provisional_impressions` is the sum of those showtimes'
        `forecast_attendance`, and `provisional_amount_cents` sums one line per
        covered slot of `forecast_attendance` multiplied by `cpm_cents` and
        divided by 1000, each line rounded half-up to a whole cent before the
        lines are summed, per the pinned rounding order of §2.9."

        Design: Difficulty/dual_variant_calc/invoice_provisional_vs_audited_billing
        """
        ctx = setup_played_slot(reported_attendance=175, outcome="VERIFIED",
                                campaign_overrides={"contracted_impressions": 100000})
        resp = api.create_invoice(ctx["campaign"]["id"], create_invoice_payload(),
                                  make_sales_manager_headers(SM_CREATOR))
        invoice = validate_success(resp, expected_status=201)
        assert_invoice(invoice)
        assert invoice["provisional_impressions"] == 132
        # round_half_up(132 x 2500 / 1000) == 330
        assert invoice["provisional_amount_cents"] == 330
        assert invoice["billing_status"] == "DRAFT"
        assert invoice["audit_status"] == "UNAUDITED"

    def test_invoice_audited_amounts_at_certification(self, api):
        """PRD §3.6: "the covered lines are now only `PLAYED` slots,
        `audited_impressions` is the sum of their `attributed_impressions`, and
        `audited_amount_cents` sums one line per slot of
        `attributed_impressions` multiplied by `cpm_cents` and divided by 1000,
        each line again rounded half-up before summing."
        PRD §3.6: "Upon certification `final_amount_cents` is set equal to
        `audited_amount_cents`"

        Design: Difficulty/dual_variant_calc/invoice_provisional_vs_audited_billing
        """
        ctx = setup_certified_invoice(reported_attendance=175,
                                      contracted_impressions=100000)
        invoice = ctx["invoice"]
        assert invoice["provisional_impressions"] == 132
        assert invoice["provisional_amount_cents"] == 330
        assert invoice["audited_impressions"] == 175
        # round_half_up(175 x 2500 / 1000) == 438
        assert invoice["audited_amount_cents"] == 438
        assert invoice["final_amount_cents"] == 438
        assert invoice["provisional_amount_cents"] != invoice["audited_amount_cents"]
        assert_invoice_money_invariant(invoice)


class TestPerLineThenSumRounding:
    def _setup_two_played_slots(self, api, outcome2):
        """One STRICT campaign with slots on two opening-week-evening showtimes,
        both reporting 175 ACCEPTED; slot1 VERIFIED, slot2 per outcome2."""
        theater, screen, feature = setup_theater_screen_feature()
        st1, r1 = create_showtime_with_reel(screen["id"], feature["id"], "2026-08-14T19:00:00Z")
        st2, r2 = create_showtime_with_reel(screen["id"], feature["id"], "2026-08-15T19:00:00Z")
        campaign = create_approved_campaign()
        sl1 = reserve_slot(r1["id"], campaign["id"], reel_version=r1["version"])
        sl2 = reserve_slot(r2["id"], campaign["id"], reel_version=r2["version"])
        lock_reel(r1["id"])
        lock_reel(r2["id"])
        dispatch_and_deliver(r1["id"], theater["id"])
        dispatch_and_deliver(r2["id"], theater["id"])
        set_clock(constants.AFTER_SHOW_CLOCK_DAY2)
        submit_and_accept_attendance(st1["id"], theater["id"], 175)
        submit_and_accept_attendance(st2["id"], theater["id"], 175)
        record_playlog(sl1["id"], theater["id"], outcome="VERIFIED")
        record_playlog(sl2["id"], theater["id"], outcome=outcome2)
        return {"theater": theater, "campaign": campaign, "sl1": sl1, "sl2": sl2,
                "st1": st1, "st2": st2}

    def test_invoice_per_line_then_sum_rounding(self, api):
        """PRD §2.9: "Invoice amounts observe a pinned rounding order: each
        covered slot's line amount is rounded half-up first and the rounded line
        amounts are then summed — the system never sums unrounded lines and
        rounds once at the end."

        Design: Difficulty/combinatorial_formula/invoice_per_line_then_sum_rounding
        """
        ctx = self._setup_two_played_slots(api, "PARTIAL")
        resp = api.create_invoice(ctx["campaign"]["id"], create_invoice_payload(),
                                  make_sales_manager_headers(SM_CREATOR))
        invoice = validate_success(resp, expected_status=201)
        api.issue_invoice(invoice["id"], make_sales_manager_headers(SM_APPROVER))
        resp = api.certify_invoice(invoice["id"], make_auditor_headers(AUDITOR_1))
        certified = validate_success(resp)
        # STRICT campaign: PARTIAL at 175 attributes floor(175 x 0.5) == 87.
        # Per-line: round_half_up(175 x 2.5) = 438; round_half_up(87 x 2.5) = 218.
        assert certified["audited_impressions"] == 262
        assert certified["audited_amount_cents"] == 656
        # Sum-then-round would have produced round_half_up(262 x 2.5) == 655.
        assert certified["audited_amount_cents"] != 655

    def test_invoice_provisional_two_lines(self, api):
        """PRD §3.6: "`provisional_amount_cents` sums one line per covered slot
        of `forecast_attendance` multiplied by `cpm_cents` and divided by 1000,
        each line rounded half-up to a whole cent before the lines are summed"

        Design: Difficulty/combinatorial_formula/invoice_per_line_then_sum_rounding
        """
        ctx = self._setup_two_played_slots(api, "PARTIAL")
        resp = api.create_invoice(ctx["campaign"]["id"], create_invoice_payload(),
                                  make_sales_manager_headers(SM_CREATOR))
        invoice = validate_success(resp, expected_status=201)
        # Two forecast lines of 132: 330 + 330.
        assert invoice["provisional_impressions"] == 264
        assert invoice["provisional_amount_cents"] == 660


class TestInvoiceParallelDimensions:
    def test_settle_blocked_until_certified(self, api):
        """PRD §3.6: "Settling requires the audit dimension to be `CERTIFIED`
        and no make-good credit of this invoice to be open in `PROPOSED` or
        `APPROVED`; either shortfall is rejected as
        `ERR_INVOICE_NOT_SETTLABLE`."

        Design: Difficulty/non_linear_state_machine/invoice_parallel_dimensions
        """
        ctx = setup_played_slot(reported_attendance=175, outcome="VERIFIED")
        resp = api.create_invoice(ctx["campaign"]["id"], create_invoice_payload(),
                                  make_sales_manager_headers(SM_CREATOR))
        invoice = validate_success(resp, expected_status=201)
        resp = api.issue_invoice(invoice["id"], make_sales_manager_headers(SM_APPROVER))
        issued = validate_success(resp)
        assert issued["billing_status"] == "ISSUED"
        assert issued["audit_status"] == "UNAUDITED"
        resp = api.settle_invoice(invoice["id"], make_sales_manager_headers(SM_CREATOR))
        validate_error(resp, ApiErrorId.ERR_INVOICE_NOT_SETTLABLE)

    def test_settle_succeeds_after_certification(self, api):
        """PRD §3.6: "A successful settle moves the billing dimension `ISSUED →
        SETTLED`."

        Design: Difficulty/non_linear_state_machine/invoice_parallel_dimensions
        """
        ctx = setup_certified_invoice(reported_attendance=175,
                                      contracted_impressions=10000)
        resp = api.settle_invoice(ctx["invoice"]["id"], make_sales_manager_headers(SM_CREATOR))
        settled = validate_success(resp)
        assert settled["billing_status"] == "SETTLED"
        assert settled["audit_status"] == "CERTIFIED"


class TestInvoiceVoidLockdown:
    def test_invoice_void_from_draft_succeeds(self, api):
        """PRD §3.6: "voiding is defined while billing is `DRAFT` or `ISSUED`,
        but only while the audit dimension is still `UNAUDITED`"

        Design: Corner/state_machines/invoice_void_blocked_once_certified
        """
        ctx = setup_played_slot(reported_attendance=175, outcome="VERIFIED")
        resp = api.create_invoice(ctx["campaign"]["id"], create_invoice_payload(),
                                  make_sales_manager_headers(SM_CREATOR))
        invoice = validate_success(resp, expected_status=201)
        resp = api.void_invoice(invoice["id"], make_sales_manager_headers(SM_CREATOR))
        assert validate_success(resp)["billing_status"] == "VOID"

    def test_invoice_void_after_certify_rejected(self, api):
        """PRD §3.6: "voiding a certified invoice is rejected with
        `ERR_INVALID_STATE_TRANSITION`"

        Design: Corner/state_machines/invoice_void_blocked_once_certified
        """
        ctx = setup_certified_invoice(reported_attendance=175,
                                      contracted_impressions=10000)
        resp = api.void_invoice(ctx["invoice"]["id"], make_sales_manager_headers(SM_CREATOR))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)


class TestInvoicePeriodOverlap:
    def test_invoice_period_overlap_rejected(self, api):
        """PRD §3.6: "The new period must not overlap the period of any
        existing non-`VOID` invoice of the same campaign, or creation is
        rejected with `ERR_INVOICE_PERIOD_OVERLAP`."

        Design: Corner/errors/invoice_period_overlap_rejected
        """
        ctx = setup_played_slot(reported_attendance=175, outcome="VERIFIED")
        api.create_invoice(ctx["campaign"]["id"], create_invoice_payload(),
                           make_sales_manager_headers(SM_CREATOR))
        resp = api.create_invoice(ctx["campaign"]["id"],
                                  create_invoice_payload(period_start_date="2026-08-15",
                                                         period_end_date="2026-08-25"),
                                  make_sales_manager_headers(SM_CREATOR))
        validate_error(resp, ApiErrorId.ERR_INVOICE_PERIOD_OVERLAP)

    def test_invoice_disjoint_period_accepted(self, api):
        """PRD §3.6: "The new period must not overlap the period of any
        existing non-`VOID` invoice of the same campaign, or creation is
        rejected with `ERR_INVOICE_PERIOD_OVERLAP`."

        Design: Corner/errors/invoice_period_overlap_rejected
        """
        ctx = setup_played_slot(reported_attendance=175, outcome="VERIFIED")
        api.create_invoice(ctx["campaign"]["id"], create_invoice_payload(),
                           make_sales_manager_headers(SM_CREATOR))
        resp = api.create_invoice(ctx["campaign"]["id"],
                                  create_invoice_payload(period_start_date="2026-08-21",
                                                         period_end_date="2026-08-31"),
                                  make_sales_manager_headers(SM_CREATOR))
        invoice = validate_success(resp, expected_status=201)
        # The campaign's only slot airs 2026-08-14, outside the new period.
        assert invoice["provisional_impressions"] == 0
        assert invoice["provisional_amount_cents"] == 0


class TestCertifyGating:
    def test_certify_requires_attendance_accepted(self, api):
        """PRD §3.6: "every showtime carrying an in-period slot must have its
        latest attendance report in `ACCEPTED` or `AUDITED`. Any shortfall in
        those conditions is rejected with `ERR_INVOICE_NOT_CERTIFIABLE`."

        Design: Difficulty/cross_entity_state_dependency/certify_requires_attendance_accepted
        """
        # Aired chain with the attendance report left SUBMITTED.
        ctx = setup_confirmed_slot()
        dispatch_and_deliver(ctx["reel"]["id"], ctx["theater"]["id"])
        set_clock(constants.AFTER_SHOW_CLOCK)
        # File the report but never review it.
        resp = api.create_attendance_report(
            ctx["showtime"]["id"], {"reported_attendance": 175},
            make_theater_ops_headers(ctx["theater"]["id"]))
        validate_success(resp, expected_status=201)
        record_playlog(ctx["slot"]["id"], ctx["theater"]["id"], outcome="VERIFIED")
        resp = api.create_invoice(ctx["campaign"]["id"], create_invoice_payload(),
                                  make_sales_manager_headers(SM_CREATOR))
        invoice = validate_success(resp, expected_status=201)
        api.issue_invoice(invoice["id"], make_sales_manager_headers(SM_APPROVER))
        resp = api.certify_invoice(invoice["id"], make_auditor_headers(AUDITOR_1))
        validate_error(resp, ApiErrorId.ERR_INVOICE_NOT_CERTIFIABLE)

    def test_certify_succeeds_after_accept(self, api):
        """PRD §3.6: "Upon certification `final_amount_cents` is set equal to
        `audited_amount_cents`, `certified_by_user_id` is stamped, and the audit
        dimension moves `UNAUDITED → CERTIFIED`."

        Design: Difficulty/cross_entity_state_dependency/certify_requires_attendance_accepted
        """
        ctx = setup_confirmed_slot()
        dispatch_and_deliver(ctx["reel"]["id"], ctx["theater"]["id"])
        set_clock(constants.AFTER_SHOW_CLOCK)
        submit_and_accept_attendance(ctx["showtime"]["id"], ctx["theater"]["id"], 175)
        record_playlog(ctx["slot"]["id"], ctx["theater"]["id"], outcome="VERIFIED")
        resp = api.create_invoice(ctx["campaign"]["id"], create_invoice_payload(),
                                  make_sales_manager_headers(SM_CREATOR))
        invoice = validate_success(resp, expected_status=201)
        api.issue_invoice(invoice["id"], make_sales_manager_headers(SM_APPROVER))
        resp = api.certify_invoice(invoice["id"], make_auditor_headers(AUDITOR_1))
        certified = validate_success(resp)
        assert certified["audit_status"] == "CERTIFIED"
        assert certified["certified_by_user_id"] == AUDITOR_1


class TestProvisionalExcludesMissedSlots:
    def _setup_slot2_missed(self, api):
        """Two slots of one campaign on two showtimes; slot2 goes MISSED before
        invoice creation."""
        theater, screen, feature = setup_theater_screen_feature()
        st1, r1 = create_showtime_with_reel(screen["id"], feature["id"], "2026-08-14T19:00:00Z")
        st2, r2 = create_showtime_with_reel(screen["id"], feature["id"], "2026-08-15T19:00:00Z")
        campaign = create_approved_campaign()
        sl1 = reserve_slot(r1["id"], campaign["id"], reel_version=r1["version"])
        sl2 = reserve_slot(r2["id"], campaign["id"], reel_version=r2["version"])
        lock_reel(r1["id"])
        lock_reel(r2["id"])
        dispatch_and_deliver(r1["id"], theater["id"])
        dispatch_and_deliver(r2["id"], theater["id"])
        set_clock(constants.AFTER_SHOW_CLOCK_DAY2)
        record_playlog(sl2["id"], theater["id"], outcome="FAILED")
        return {"theater": theater, "campaign": campaign, "sl1": sl1, "sl2": sl2}

    def test_provisional_invoice_excludes_missed_slots(self, api):
        """PRD §3.6: "the covered lines are the campaign's slots in `RESERVED`,
        `CONFIRMED`, or `PLAYED` whose showtime's calendar date falls within the
        period, endpoints inclusive, with `MISSED` and `CANCELED` slots
        contributing nothing."

        Design: Corner/calculations/provisional_invoice_excludes_missed_slots
        """
        ctx = self._setup_slot2_missed(api)
        resp = api.create_invoice(ctx["campaign"]["id"], create_invoice_payload(),
                                  make_sales_manager_headers(SM_CREATOR))
        invoice = validate_success(resp, expected_status=201)
        # Only the surviving CONFIRMED slot's forecast counts.
        assert invoice["provisional_impressions"] == 132
        assert invoice["provisional_amount_cents"] == 330


class TestZeroAttendance:
    def test_zero_attendance_yields_zero_audited_amount(self, api):
        """PRD §3.4: "whenever the showtime's `actual_attendance` is already
        known, sets `attributed_impressions` to the floor of
        `actual_attendance` multiplied by `play_factor`"

        Design: Corner/calculations/zero_attendance_yields_zero_audited_amount
        """
        ctx = setup_certified_invoice(reported_attendance=0, contracted_impressions=1000)
        resp = api.get_slot(ctx["slot"]["id"], make_sales_manager_headers(SM_CREATOR))
        assert validate_success(resp)["attributed_impressions"] == 0
        resp = api.get_campaign(ctx["campaign"]["id"], make_sales_manager_headers(SM_CREATOR))
        assert validate_success(resp)["delivered_impressions"] == 0
        invoice = ctx["invoice"]
        assert invoice["audited_impressions"] == 0
        assert invoice["audited_amount_cents"] == 0
        assert invoice["final_amount_cents"] == 0
