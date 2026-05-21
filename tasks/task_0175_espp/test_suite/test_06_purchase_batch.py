"""Purchase batch: state preconditions, segregation of duties,
calculation correctness, cascade side effects, next-period creation.

References PRD §3.5, §2.4.
"""
from __future__ import annotations

from test_helpers import (
    ApiErrorId,
    add_days,
    advance_clock_to,
    assert_purchase,
    assert_purchase_invariants,
    enroll_participant,
    get_success_data,
    list_offering_periods,
    make_participant_headers,
    make_payroll_agent_headers,
    make_plan_admin_headers,
    new_participant_id,
    post_contribution,
    purchase_fmv_payload,
    run_sweep,
    setup_active_plan_with_open_period,
    setup_enrollment_with_contributions,
    setup_period_at_closed_state,
    setup_purchase_after_run,
    TEST_USERS,
    validate_error,
    validate_success,
)


# ===========================================================================
# Run-purchase state preconditions
# ===========================================================================
class TestRunPurchasePreconditions:

    def test_run_purchase_on_open_period_rejected(self, api):
        """PRD §3.5: "the period's `status` must be exactly `CLOSED`
        (an `OPEN` or `PURCHASED` period is rejected with
        `ERR_INVALID_PERIOD_STATE`)".

        Claim: run-purchase on OPEN period -> ERR_INVALID_PERIOD_STATE.
        """
        plan, op1 = setup_active_plan_with_open_period(
            initial_clock_iso="2023-12-01T00:00:00.000Z",
            effective_date="2024-01-01T00:00:00.000Z",
            grant_date_fmv_cents=1000,
        )
        resp = api.run_purchase(op1["id"], TEST_USERS["plan_admin_headers"])
        validate_error(resp, ApiErrorId.ERR_INVALID_PERIOD_STATE.value)

    def test_run_purchase_on_already_purchased_period_rejected(self, api):
        """PRD §3.5: "Two concurrent invocations on the same `CLOSED`
        period serialize so that exactly one batch executes; the loser
        observes the period now in `PURCHASED` and is rejected with
        `ERR_INVALID_PERIOD_STATE`."

        Claim: second run-purchase on now-PURCHASED period ->
        ERR_INVALID_PERIOD_STATE.
        """
        # Drive through to PURCHASED via the fixture.
        plan, op_after, _pid, _purchase = setup_purchase_after_run(
            grant_date_fmv_cents=1000,
            purchase_date_fmv_cents=2000,
            contribution_amount_cents=8500,
            contribution_rate_bp=1500,
        )
        assert op_after["status"] == "PURCHASED"
        # Re-invoke.
        resp = api.run_purchase(
            op_after["id"], TEST_USERS["plan_admin_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_PERIOD_STATE.value)


# ===========================================================================
# Segregation of duties — PRD §2.4
# ===========================================================================
class TestSegregationOfDuties:

    def test_sod_violation_when_same_user_posts_and_runs(self, api):
        """PRD §2.4: "the `X-User-ID` invoking the run-purchase
        operation on an offering period MUST NOT appear as the poster
        of any `Contribution` whose `enrollment_id` points at an
        `Enrollment` belonging to that period. ... A violation is
        rejected with `ERR_SOD_VIOLATION`."

        Claim: same X-User-ID posts a Contribution and later attempts
        run-purchase on the same period -> ERR_SOD_VIOLATION.
        """
        plan, op1 = setup_active_plan_with_open_period(
            initial_clock_iso="2023-12-01T00:00:00.000Z",
            effective_date="2024-01-01T00:00:00.000Z",
            grant_date_fmv_cents=1000,
        )
        pid, enr = enroll_participant(
            offering_period_id=op1["id"], contribution_rate_bp=1500,
        )
        # Single colliding operator id (acts as both PayrollAgent and
        # PlanAdministrator across requests).
        colliding_id = "colliding-op-001"
        # Contribution posted by colliding_id (PayrollAgent).
        post_contribution(
            enrollment_id=enr["id"],
            pay_period_end=op1["start_date"],
            gross_pay_cents=10_000,
            payroll_headers=make_payroll_agent_headers(colliding_id),
        )
        # Drive period to CLOSED using a different plan-admin id so the
        # FMV PATCH doesn't establish another collision.
        advance_clock_to(add_days(op1["end_date"], 1))
        get_success_data(
            api.record_purchase_fmv(
                op1["id"],
                purchase_fmv_payload(
                    purchase_date_fmv_cents=2000,
                    version=op1["version"],
                ),
                TEST_USERS["plan_admin_headers"],
            )
        )
        run_sweep()
        # Now colliding_id tries to run-purchase as PlanAdministrator.
        resp = api.run_purchase(
            op1["id"], make_plan_admin_headers(colliding_id),
        )
        validate_error(resp, ApiErrorId.ERR_SOD_VIOLATION.value)


# ===========================================================================
# Purchase calculation — PRD §3.5
# ===========================================================================
class TestPurchaseCalculationLookback:

    def test_lookback_grant_lower_anchors_to_grant_fmv(self, api):
        """PRD §3.5: "when the plan has `lookback_enabled` equal to
        true, the chosen per-share fair-market value `chosen_fmv_cents`
        is the smaller of the period's `grant_date_fmv_cents` and
        `purchase_date_fmv_cents`".

        Claim: lookback=true, grant=1000, purchase=2000 ->
        chosen_fmv_cents=1000, purchase_price_cents=850 (round_half_up
        of 1000*0.85=850), shares=floor(17000/850)=20, refund=0.
        """
        # difficulty: dual_variant_calc/purchase_settlement_lookback_vs_no_lookback
        plan, op_after, _pid, purchase = setup_purchase_after_run(
            lookback_enabled=True,
            discount_bp=1500,
            grant_date_fmv_cents=1000,
            purchase_date_fmv_cents=2000,
            contribution_amount_cents=17_000,
            contribution_rate_bp=1500,
        )
        assert_purchase(purchase)
        assert_purchase_invariants(purchase)
        assert purchase["chosen_fmv_cents"] == 1000
        assert purchase["purchase_price_cents"] == 850
        assert purchase["shares_purchased"] == 20
        assert purchase["refund_cents"] == 0

    def test_lookback_purchase_lower_drops_with_stock(self, api):
        """PRD §3.5: "with lookback enabled and the purchase FMV
        strictly below the grant FMV, the price drops with the stock".

        Claim: lookback=true, grant=2000, purchase=1000 ->
        chosen_fmv_cents=1000, purchase_price_cents=850.
        """
        plan, op_after, _pid, purchase = setup_purchase_after_run(
            lookback_enabled=True,
            discount_bp=1500,
            grant_date_fmv_cents=2000,
            purchase_date_fmv_cents=1000,
            contribution_amount_cents=17_000,
            contribution_rate_bp=1500,
        )
        assert purchase["chosen_fmv_cents"] == 1000
        assert purchase["purchase_price_cents"] == 850

    def test_no_lookback_uses_purchase_fmv(self, api):
        """PRD §3.5: "when the plan has `lookback_enabled` equal to
        false, the chosen value is simply `purchase_date_fmv_cents`."

        Claim: lookback=false, grant=1000, purchase=2000 ->
        chosen_fmv_cents=2000, purchase_price_cents=1700,
        shares=floor(17000/1700)=10, refund=0.
        """
        plan, op_after, _pid, purchase = setup_purchase_after_run(
            lookback_enabled=False,
            discount_bp=1500,
            grant_date_fmv_cents=1000,
            purchase_date_fmv_cents=2000,
            contribution_amount_cents=17_000,
            contribution_rate_bp=1500,
        )
        assert purchase["chosen_fmv_cents"] == 2000
        assert purchase["purchase_price_cents"] == 1700
        assert purchase["shares_purchased"] == 10
        assert purchase["refund_cents"] == 0


# ===========================================================================
# Cascade side effects — PRD §3.5
# ===========================================================================
class TestRunPurchaseCascade:

    def test_run_purchase_sets_op_purchased_and_creates_next_op(self, api):
        """PRD §3.5: "The batch also performs the period-rollover side
        effect: the current period's `status` is set to `PURCHASED`
        (terminal), and a new `OfferingPeriod` is created with
        `sequence_number` equal to the predecessor's plus one,
        `start_date` equal to the predecessor's `end_date`, `end_date`
        computed as the new `start_date` plus `Plan.offering_period_months`
        months, and `status` equal to `OPEN`."

        Claim: after run-purchase, plan has TWO offering periods:
        op1.status==PURCHASED AND op2.sequence_number==2 AND
        op2.start_date==op1.end_date AND op2.status==OPEN.
        """
        plan, op_after, _pid, _purchase = setup_purchase_after_run(
            grant_date_fmv_cents=1000,
            purchase_date_fmv_cents=2000,
            contribution_amount_cents=8500,
            contribution_rate_bp=1500,
        )
        periods = list_offering_periods(plan["id"])
        # Find op1 and op2 by sequence_number.
        by_seq = {p["sequence_number"]: p for p in periods}
        assert 1 in by_seq and 2 in by_seq, (
            f"Expected sequence_numbers 1 and 2, got {sorted(by_seq.keys())}"
        )
        op1 = by_seq[1]
        op2 = by_seq[2]
        assert op1["status"] == "PURCHASED"
        assert op2["status"] == "OPEN"
        assert op2["start_date"] == op1["end_date"]

    def test_run_purchase_completes_enrollment_and_consumes_contribs(
        self, api,
    ):
        """PRD §3.5: "Each consumed `Contribution` is flipped from
        `POSTED` to `CONSUMED`. Each processed `Enrollment` is flipped
        from `ACTIVE` to `COMPLETED`."

        Claim: post-batch enrollment.status==COMPLETED AND all funding
        contributions have status==CONSUMED.
        """
        plan, op1, pid, enrollment = setup_enrollment_with_contributions(
            grant_date_fmv_cents=1000,
            contribution_amount_cents=8500,
            contribution_rate_bp=1500,
        )
        # Add a second contribution to verify ALL get consumed.
        post_contribution(
            enrollment_id=enrollment["id"],
            pay_period_end=op1["start_date"],
            gross_pay_cents=10_000,
        )
        # Drive to PURCHASED.
        advance_clock_to(add_days(op1["end_date"], 1))
        get_success_data(
            api.record_purchase_fmv(
                op1["id"],
                purchase_fmv_payload(
                    purchase_date_fmv_cents=2000,
                    version=op1["version"],
                ),
                TEST_USERS["plan_admin_headers"],
            )
        )
        run_sweep()
        get_success_data(
            api.run_purchase(op1["id"], TEST_USERS["plan_admin_headers"])
        )
        # Verify enrollment.
        enr_after = get_success_data(
            api.get_enrollment(
                enrollment["id"], TEST_USERS["plan_admin_headers"],
            )
        )
        assert enr_after["status"] == "COMPLETED"
        # Verify contributions all CONSUMED.
        clist = api.list_contributions(
            enrollment["id"], TEST_USERS["plan_admin_headers"],
            params={"limit": 100, "offset": 0},
        )
        items = clist.json()["data"]
        assert len(items) >= 2
        for c in items:
            assert c["status"] == "CONSUMED", (
                f"After run-purchase, every funding contribution must "
                f"be CONSUMED; got {c['status']!r}"
            )

    def test_withdrawn_enrollment_excluded_from_batch(self, api):
        """PRD §3.5: "(Enrollments already `WITHDRAWN` are skipped,
        consistent with §3.3.)"
        PRD §3.3: "the participant is excluded from this period's
        purchase batch when it eventually runs."

        Claim: WITHDRAWN enrollment receives NO Purchase row.
        """
        plan, op1, pid, enrollment = setup_enrollment_with_contributions(
            grant_date_fmv_cents=1000,
            contribution_amount_cents=8500,
            contribution_rate_bp=1500,
        )
        # Withdraw before batch.
        get_success_data(
            api.withdraw_enrollment(
                enrollment["id"], make_participant_headers(pid),
            )
        )
        # Drive period through to PURCHASED.
        advance_clock_to(add_days(op1["end_date"], 1))
        get_success_data(
            api.record_purchase_fmv(
                op1["id"],
                purchase_fmv_payload(
                    purchase_date_fmv_cents=2000,
                    version=op1["version"],
                ),
                TEST_USERS["plan_admin_headers"],
            )
        )
        run_sweep()
        get_success_data(
            api.run_purchase(op1["id"], TEST_USERS["plan_admin_headers"])
        )
        # Participant must have zero purchases.
        plist = api.list_purchases(
            pid, make_participant_headers(pid),
            params={"limit": 100, "offset": 0},
        )
        items = plist.json()["data"]
        assert items == [], (
            f"Withdrawn enrollment must yield no Purchase rows; got "
            f"{len(items)} items"
        )

    def test_run_purchase_issues_form_3922(self, api):
        """PRD §3.5: "A Form 3922 record is issued immutably per
        `Purchase`, with its fields mirroring the purchase as described
        in §2.8: `purchase_id` and `participant_id` from the purchase
        row; `grant_date` from the period's `start_date`; `purchase_date`
        from the period's `end_date`; `fmv_grant_date_cents` and
        `fmv_purchase_date_cents` snapshotted from the period's two FMV
        fields at issuance; `exercise_price_per_share_cents` snapshotted
        from `purchase_price_cents` at issuance; `shares_transferred`
        from `shares_purchased`; `legal_title_date` equal to
        `purchase_date`; and a server-assigned `issuance_timestamp`."

        Claim: post-batch, exactly one Form3922 exists for the new
        Purchase with all fields mirrored as specified.
        """
        plan, op_after, pid, purchase = setup_purchase_after_run(
            grant_date_fmv_cents=1000,
            purchase_date_fmv_cents=2000,
            contribution_amount_cents=8500,
            contribution_rate_bp=1500,
        )
        # List the participant's Form 3922 for the calendar year of
        # purchase_date.
        from test_helpers import parse_iso
        year = parse_iso(purchase["purchase_date"]).year
        resp = api.list_form_3922(
            pid, make_participant_headers(pid),
            params={"calendar_year": year, "limit": 100, "offset": 0},
        )
        items = resp.json()["data"]
        forms_for_purchase = [
            f for f in items if f["purchase_id"] == purchase["id"]
        ]
        assert len(forms_for_purchase) == 1, (
            f"Expected exactly one Form3922 for purchase {purchase['id']}, "
            f"got {len(forms_for_purchase)}"
        )
        form = forms_for_purchase[0]
        # PRD §2.8 field mirroring:
        assert form["participant_id"] == pid
        assert form["fmv_grant_date_cents"] == 1000
        assert form["fmv_purchase_date_cents"] == 2000
        assert form["exercise_price_per_share_cents"] == \
            purchase["purchase_price_cents"]
        assert form["shares_transferred"] == purchase["shares_purchased"]
        assert form["legal_title_date"] == form["purchase_date"]
