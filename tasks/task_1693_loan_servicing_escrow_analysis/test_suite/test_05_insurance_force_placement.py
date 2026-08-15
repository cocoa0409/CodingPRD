"""Insurance lapse lifecycle, force-placement windows, refund proration."""
from test_helpers import (
    DP2,
    EA1,
    IS1,
    ApiErrorId,
    charge_force_placement,
    charge_force_placement_payload,
    create_active_bare_loan,
    create_policy,
    get_account,
    get_ledger,
    get_success_data,
    make_borrower_headers,
    release_disbursement,
    reinstate_policy,
    schedule_disbursement,
    set_clock,
    setup_active_account,
    setup_lapsed_policy_with_notice1,
    setup_policy_notice2,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestLapseReinstatementCycle:
    def test_reinstate_returns_to_active_and_resets_notices(self, api):
        """PRD: "Reinstatement returns the policy to `ACTIVE`, replaces its
        coverage dates and — when supplied — its premium, and resets both
        notice timestamps to null."

        Design: Difficulty/non_linear_state_machine/insurance_policy_lapse_reinstatement_cycle
        """
        loan = create_active_bare_loan(loan_number="LN-CYC-1",
                                       borrower_name="Cy Clist",
                                       closing_date="2026-01-01")
        policy = create_policy(loan["id"], policy_number="POL-1")

        set_clock("2027-01-02T00:00:00Z")
        lapsed = validate_success(api.get_insurance_policy(policy["id"], IS1), 200)
        assert lapsed["status"] == "LAPSED", (
            "coverage end passed with no other ACTIVE same-type coverage")
        get_success_data(api.send_first_notice(policy["id"], IS1))
        set_clock("2027-02-05T00:00:00Z")
        get_success_data(api.send_reminder_notice(policy["id"], IS1))

        reinstated = reinstate_policy(
            policy["id"], "2027-02-05", "2028-02-05",
            new_annual_premium_cents=126_000,
            headers=make_borrower_headers(loan["id"]))
        assert reinstated["status"] == "ACTIVE", "the cycle closes to the initial state"
        assert reinstated["notice_1_sent_at"] is None
        assert reinstated["notice_2_sent_at"] is None
        assert reinstated["annual_premium_cents"] == 126_000
        assert reinstated["coverage_start_date"] == "2027-02-05"
        assert reinstated["coverage_end_date"] == "2028-02-05"

    def test_policy_lapses_a_second_time_after_reinstatement(self, api):
        """PRD: "The clock sweep moves `ACTIVE` → `LAPSED` when the coverage
        end has passed and no other `ACTIVE` same-type policy on the loan
        covers the current date"

        Design: Difficulty/non_linear_state_machine/insurance_policy_lapse_reinstatement_cycle
        """
        loan = create_active_bare_loan(loan_number="LN-CYC-1",
                                       borrower_name="Cy Clist",
                                       closing_date="2026-01-01")
        policy = create_policy(loan["id"], policy_number="POL-1")
        set_clock("2027-01-02T00:00:00Z")
        get_success_data(api.send_first_notice(policy["id"], IS1))
        set_clock("2027-02-05T00:00:00Z")
        get_success_data(api.send_reminder_notice(policy["id"], IS1))
        reinstate_policy(policy["id"], "2027-02-05", "2028-02-05",
                         new_annual_premium_cents=126_000,
                         headers=make_borrower_headers(loan["id"]))

        set_clock("2028-02-06T00:00:00Z")
        relapsed = validate_success(api.get_insurance_policy(policy["id"], IS1), 200)
        assert relapsed["status"] == "LAPSED", (
            "the reinstated policy lapses again when its new coverage expires — "
            "the cycle is traversable repeatedly")


class TestCoverageOverlap:
    def test_interior_overlap_rejected(self, api):
        """PRD: "a new policy whose half-open interval intersects another's is
        rejected with `ERR_COVERAGE_OVERLAP`"

        Design: Difficulty/resource_temporal_overlap/insurance_coverage_half_open_adjacency
        """
        loan = create_active_bare_loan(loan_number="LN-OVL-1",
                                       borrower_name="Olive Lap")
        create_policy(loan["id"], policy_number="POL-A",
                      coverage_start_date="2026-08-01",
                      coverage_end_date="2027-08-01")

        resp = api.create_insurance_policy(
            loan["id"],
            {"policy_type": "HAZARD", "carrier_name": "Carrier B",
             "policy_number": "POL-B", "coverage_start_date": "2027-01-01",
             "coverage_end_date": "2028-01-01", "annual_premium_cents": 130_000},
            IS1)
        validate_error(resp, ApiErrorId.ERR_COVERAGE_OVERLAP)

    def test_pure_adjacency_is_not_overlap(self, api):
        """PRD: "while pure adjacency — one policy's start date equal to the
        other's end date — is not an overlap."

        Design: Difficulty/resource_temporal_overlap/insurance_coverage_half_open_adjacency
        """
        loan = create_active_bare_loan(loan_number="LN-OVL-1",
                                       borrower_name="Olive Lap")
        create_policy(loan["id"], policy_number="POL-A",
                      coverage_start_date="2026-08-01",
                      coverage_end_date="2027-08-01")

        resp = api.create_insurance_policy(
            loan["id"],
            {"policy_type": "HAZARD", "carrier_name": "Carrier C",
             "policy_number": "POL-C", "coverage_start_date": "2027-08-01",
             "coverage_end_date": "2028-08-01", "annual_premium_cents": 130_000},
            IS1)
        adjacent = validate_success(resp, 201)
        assert adjacent["status"] == "ACTIVE", (
            "start == existing end is allowed under half-open semantics")


class TestForcePlacementNoticeWindows:
    def test_charge_at_exactly_45_and_15_days_succeeds(self, api):
        """PRD: "Charging the force-placement premium (`NOTICE_2_SENT` →
        `FORCE_PLACED`) requires both windows to have elapsed — the current
        date must be at least 45 days after the first notice's date and at
        least 15 days after the reminder's date, else
        `ERR_NOTICE_WINDOW_NOT_MET`"
        PRD: "The charge stamps `force_placed_at` and sets `fp_coverage_end` to
        the force-placement date plus 365 days"

        Design: Difficulty/boundary_precision_check/force_placement_exactly_45_days
        """
        ctx = setup_active_account(loan_number="LN-FP-1",
                                   deposits=[(200_000, "2026-08-02")])
        policy = create_policy(ctx["loan"]["id"], policy_number="POL-FP-1",
                               carrier_name="Carrier C")
        # First notice at the default clock 2026-08-01.
        get_success_data(api.report_lapse(policy["id"], IS1))
        get_success_data(api.send_first_notice(policy["id"], IS1))
        set_clock("2026-08-31T00:00:00Z")
        get_success_data(api.send_reminder_notice(policy["id"], IS1))

        # 2026-09-15 is exactly notice_1 + 45 days and notice_2 + 15 days.
        set_clock("2026-09-15T00:00:00Z")
        charged = charge_force_placement(policy["id"], fp_premium_cents=182_500,
                                         day_count_convention="ACT_365")
        assert charged["status"] == "FORCE_PLACED"
        assert charged["fp_premium_cents"] == 182_500
        assert charged["fp_coverage_end"] == "2027-09-15"
        assert charged["force_placed_at"] is not None

        entries = get_ledger(ctx["account"]["id"])
        charges = [e for e in entries if e["entry_type"] == "FORCE_PLACEMENT_CHARGE"]
        assert len(charges) == 1 and charges[0]["amount_cents"] == -182_500
        account = get_account(ctx["account"]["id"])
        assert account["balance_cents"] == 17_500, "200000 minus the 182500 premium"

    def test_charge_at_44_days_rejected(self, api):
        """PRD: "the current date must be at least 45 days after the first
        notice's date and at least 15 days after the reminder's date, else
        `ERR_NOTICE_WINDOW_NOT_MET`"

        Design: Difficulty/boundary_precision_check/force_placement_exactly_45_days
        """
        loan, policy = setup_policy_notice2(loan_number="LN-FP-2",
                                            policy_number="POL-FP-2")
        # 2026-09-14 is only notice_1 + 44 days.
        set_clock("2026-09-14T00:00:00Z")
        resp = api.charge_force_placement(
            policy["id"], charge_force_placement_payload(), IS1)
        validate_error(resp, ApiErrorId.ERR_NOTICE_WINDOW_NOT_MET)

        policy_after = validate_success(api.get_insurance_policy(policy["id"], IS1), 200)
        assert policy_after["status"] == "NOTICE_2_SENT", "rejected charge changes nothing"


class TestReminderWindow:
    def test_reminder_at_29_days_rejected_at_30_succeeds(self, api):
        """PRD: "The reminder (`NOTICE_1_SENT` → `NOTICE_2_SENT`, stamping
        `notice_2_sent_at`) may not be sent until the current date is at least
        30 days after the date of `notice_1_sent_at`, else
        `ERR_REMINDER_TOO_EARLY`."

        Design: Corner/validations/reminder_notice_before_30_days_rejected
        """
        # notice_1 sent at the default clock 2026-08-01.
        loan, policy = setup_lapsed_policy_with_notice1(loan_number="LN-VAL-18",
                                                        policy_number="POL-REM")

        set_clock("2026-08-30T00:00:00Z")
        resp = api.send_reminder_notice(policy["id"], IS1)
        validate_error(resp, ApiErrorId.ERR_REMINDER_TOO_EARLY)

        set_clock("2026-08-31T00:00:00Z")
        reminded = validate_success(api.send_reminder_notice(policy["id"], IS1), 200)
        assert reminded["status"] == "NOTICE_2_SENT", (
            "at exactly notice_1 + 30 days the reminder is allowed")
        assert reminded["notice_2_sent_at"] is not None


class TestForceChargeSafetyVsCap:
    def _setup_account_with_cap_pressure(self, api, loan_number):
        """ACTIVE account, zero balance, one OUTSTANDING advance of 990000
        created by a fully shortfalled release; plus a policy in NOTICE_2_SENT
        with notice_1 at 2026-08-06 and reminder at 2026-09-05."""
        ctx = setup_active_account(loan_number=loan_number)
        acct_id = ctx["account"]["id"]
        disb = schedule_disbursement(
            acct_id, ctx["line_items"][0]["id"], ctx["payee"]["id"],
            amount_cents=990_000, due_date="2026-08-20",
            scheduled_release_date="2026-08-05")
        set_clock("2026-08-05T00:00:00Z")
        release_disbursement(disb["id"], DP2)
        advances, _ = validate_paginated(api.list_advances(acct_id, EA1))
        assert advances[0]["outstanding_cents"] == 990_000

        policy = create_policy(ctx["loan"]["id"], policy_number="POL-CAP",
                               carrier_name="Carrier B")
        set_clock("2026-08-06T00:00:00Z")
        get_success_data(api.report_lapse(policy["id"], IS1))
        get_success_data(api.send_first_notice(policy["id"], IS1))
        set_clock("2026-09-05T00:00:00Z")
        get_success_data(api.send_reminder_notice(policy["id"], IS1))
        return ctx, policy

    def test_unmet_notice_window_beats_advance_cap(self, api):
        """PRD: "When several checks could reject the same request, they are
        evaluated in a fixed priority order so the surfaced error is
        deterministic:"
        PRD: "then segregation of duties (`ERR_SOD_VIOLATION`); then the
        force-placement notice windows (`ERR_NOTICE_WINDOW_NOT_MET`,
        `ERR_REMINDER_TOO_EARLY`); then the active-coverage bar
        (`ERR_ACTIVE_COVERAGE_EXISTS`); then the remaining temporal gates
        (`ERR_RELEASE_TOO_EARLY`, `ERR_EFFECTIVE_DATE_NOT_REACHED`,
        `ERR_EXTENSION_WINDOW_PASSED`, `ERR_PROJECTION_START_INVALID`); then
        uniqueness and duplicate constraints; then cross-entity state
        requirements; and finally amount rules."

        Design: Difficulty/priority_pair_validation_conflict/force_charge_safety_beats_fiscal_cap
        """
        ctx, policy = self._setup_account_with_cap_pressure(api, "LN-CAP-1")
        # 2026-09-19 is notice_1 + 44 days: the RESPA window is unmet AND a
        # 182500 charge would push 990000 + 182500 over the 1000000 cap.
        set_clock("2026-09-19T00:00:00Z")
        resp = api.charge_force_placement(
            policy["id"], charge_force_placement_payload(), IS1)
        validate_error(resp, ApiErrorId.ERR_NOTICE_WINDOW_NOT_MET)

        policy_after = validate_success(api.get_insurance_policy(policy["id"], IS1), 200)
        assert policy_after["status"] == "NOTICE_2_SENT", "no charge posted"
        account = get_account(ctx["account"]["id"])
        assert account["balance_cents"] == 0

    def test_met_window_exposes_advance_cap_breach(self, api):
        """PRD: "when the balance is insufficient, an advance with `reason`
        `FORCE_PLACEMENT_PREMIUM` is created (subject to the same advance cap,
        `ERR_ADVANCE_CAP_EXCEEDED`)"

        Design: Difficulty/priority_pair_validation_conflict/force_charge_safety_beats_fiscal_cap
        """
        ctx, policy = self._setup_account_with_cap_pressure(api, "LN-CAP-1T")
        # 2026-09-20 is notice_1 + 45 and notice_2 + 15: both windows met, so
        # the fiscal cap rule surfaces on its own.
        set_clock("2026-09-20T00:00:00Z")
        resp = api.charge_force_placement(
            policy["id"], charge_force_placement_payload(), IS1)
        validate_error(resp, ApiErrorId.ERR_ADVANCE_CAP_EXCEEDED)

        policy_after = validate_success(api.get_insurance_policy(policy["id"], IS1), 200)
        assert policy_after["status"] == "NOTICE_2_SENT"


class TestForceChargeActiveCoverage:
    def test_charge_blocked_while_other_active_coverage_exists(self, api):
        """PRD: "and is barred while any other `ACTIVE` same-type policy exists
        on the loan (`ERR_ACTIVE_COVERAGE_EXISTS`)."

        Design: Corner/validations/force_charge_blocked_by_active_coverage
        """
        loan, policy = setup_policy_notice2(loan_number="LN-VAL-19",
                                            policy_number="POL-OLD")
        set_clock("2026-09-15T00:00:00Z")
        # Borrower produces new ACTIVE coverage before the charge.
        create_policy(loan["id"], policy_number="POL-NEW", carrier_name="Carrier G",
                      coverage_start_date="2026-09-15",
                      coverage_end_date="2027-09-15", annual_premium_cents=121_000,
                      headers=make_borrower_headers(loan["id"]))

        resp = api.charge_force_placement(
            policy["id"], charge_force_placement_payload(), IS1)
        validate_error(resp, ApiErrorId.ERR_ACTIVE_COVERAGE_EXISTS)

        policy_after = validate_success(api.get_insurance_policy(policy["id"], IS1), 200)
        assert policy_after["status"] == "NOTICE_2_SENT", "no charge posted"


class TestForcePlacementRefundProration:
    def test_act365_and_30360_refunds_diverge(self, api):
        """PRD: "Under `ACT_365`, the used days are the calendar days from the
        force-placement date to the evidence policy's creation date, exclusive,
        and the refund is the premium multiplied by the remaining days out of
        365 — that is, 365 minus the used days — rounded half-up to whole
        cents. Under `CONTRACT_30_360`, the used days are computed on the
        30/360 convention over a 360-day term, and the refund is the premium
        multiplied by 360 minus the used days, divided by 360, rounded half-up;
        the two conventions yield different refunds for the same dates."
        PRD: "`refund_timeliness` is computed as `ON_TIME` when the refund date
        is on or before the evidence policy's creation date plus 15 days, else
        `LATE`."

        Design: Corner/calculations/force_placement_refund_day_count_variants
        """
        # Twin funded accounts; identical policies and dates; the only
        # difference is the day-count convention pinned at charge time.
        # Clock moves are interleaved so the logical clock only advances.
        ctx_a = setup_active_account(loan_number="LN-CAL-5A",
                                     borrower_name="Act ThreeSixtyFive",
                                     deposits=[(200_000, "2026-08-05")])
        pol_a = create_policy(ctx_a["loan"]["id"], policy_number="POL-ACT",
                              carrier_name="Carrier D")
        ctx_b = setup_active_account(loan_number="LN-CAL-5B",
                                     borrower_name="Thirty ThreeSixty",
                                     deposits=[(200_000, "2026-08-05")])
        pol_b = create_policy(ctx_b["loan"]["id"], policy_number="POL-360",
                              carrier_name="Carrier D")

        set_clock("2026-08-10T00:00:00Z")
        for pol in (pol_a, pol_b):
            get_success_data(api.report_lapse(pol["id"], IS1))
            get_success_data(api.send_first_notice(pol["id"], IS1))
        set_clock("2026-09-09T00:00:00Z")
        for pol in (pol_a, pol_b):
            get_success_data(api.send_reminder_notice(pol["id"], IS1))
        # 2026-09-24 is exactly notice_1 + 45 days and notice_2 + 15 days.
        set_clock("2026-09-24T00:00:00Z")
        pol_a = charge_force_placement(pol_a["id"], fp_premium_cents=182_500,
                                       day_count_convention="ACT_365")
        pol_b = charge_force_placement(pol_b["id"], fp_premium_cents=182_500,
                                       day_count_convention="CONTRACT_30_360")

        # Evidence coverage created 2026-11-08 (borrower-submitted) on each loan.
        set_clock("2026-11-08T00:00:00Z")
        for ctx in (ctx_a, ctx_b):
            create_policy(ctx["loan"]["id"], carrier_name="Carrier E",
                          coverage_start_date="2026-11-08",
                          coverage_end_date="2027-11-08",
                          annual_premium_cents=121_000,
                          headers=make_borrower_headers(ctx["loan"]["id"]))

        refunded_a = validate_success(api.refund_force_placement(pol_a["id"], IS1), 200)
        refunded_b = validate_success(api.refund_force_placement(pol_b["id"], IS1), 200)

        assert refunded_a["fp_refund_cents"] == 160_000, (
            "ACT_365: 45 actual days used of a 365-day term")
        assert refunded_b["fp_refund_cents"] == 160_194, (
            "CONTRACT_30_360: 44 thirty-day-convention days used of a 360-day term")
        assert refunded_a["fp_refund_cents"] != refunded_b["fp_refund_cents"]
        assert refunded_a["status"] == "REFUNDED"
        assert refunded_b["status"] == "REFUNDED"
        assert refunded_a["refund_timeliness"] == "ON_TIME", (
            "refund same day as the evidence policy's creation (<= +15 days)")
        assert refunded_b["refund_timeliness"] == "ON_TIME"

        account_a = get_account(ctx_a["account"]["id"])
        assert account_a["balance_cents"] == 177_500, "200000 - 182500 + 160000"
        refunds_a = [e for e in get_ledger(ctx_a["account"]["id"])
                     if e["entry_type"] == "FORCE_PLACEMENT_REFUND"]
        assert len(refunds_a) == 1 and refunds_a[0]["amount_cents"] == 160_000
