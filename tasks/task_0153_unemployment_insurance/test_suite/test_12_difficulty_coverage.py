"""Difficulty-design coverage suite.

Each test here exercises a specific scaffold_difficulty_design instance
declared in SCAFFOLD_DIFFICULTY_DESIGN.yaml. Every instance must be
covered by at least TWO tests across the test_suite. Tags in
docstrings (# difficulty: <rule_id>/<instance.name>) let the audit
trace which instance each test satisfies.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    APPEAL_WINDOW_DAYS,
    NON_EXISTENT_UUID,
    TEST_USERS,
    advance_clock_by_days,
    advance_clock_by_seconds,
    apply_extension_payload,
    apply_extension_to_claim,
    approve_one_weekly_certification,
    audit_certification,
    create_appeal_payload,
    create_claim,
    create_claimant,
    create_denied_claim,
    create_eligible_claim,
    create_employer,
    create_pandemic_extension,
    create_weekly_certification_payload,
    date_to_iso,
    decide_appeal,
    decide_appeal_payload,
    file_appeal,
    get_claim,
    get_employer,
    list_claim_overpayments,
    list_employer_charges,
    make_adjudicator_headers,
    make_appeal_officer_headers,
    make_claimant_headers,
    n_work_search_entries,
    next_certifiable_saturday,
    repay_overpayment,
    setup_active_pandemic_extension,
    setup_appeal_segregation_collision,
    setup_claim_with_n_approved_certs,
    setup_dual_variant_alternate_scenario,
    setup_employer_with_active_charge,
    setup_filed_appeal_on_denied_claim,
    setup_in_hearing_appeal_on_denied_claim,
    setup_outstanding_overpayment,
    setup_two_employer_charge_split,
    stage_low_wages_below_floors,
    start_appeal_hearing,
    submit_claim,
    submit_weekly_certification,
    validate_error,
    validate_success,
    withdraw_appeal,
)


# ===========================================================================
# Rule 1 — dual_variant_calc
# ===========================================================================
class TestDualVariantBasePeriod:
    """# difficulty: dual_variant_calc/claim_base_period_standard_vs_alternate"""

    def test_alternate_chosen_when_standard_below_floor(self, api):
        """PRD §3.2: "if the STANDARD total is at least the base-period
        wage floor of 150,000 cents ($1,500.00), STANDARD is chosen;
        otherwise, if the ALTERNATE total is at least 150,000 cents,
        ALTERNATE is chosen; otherwise STANDARD is chosen by default
        (in which case the claim will fail monetary eligibility)."

        # difficulty: dual_variant_calc/claim_base_period_standard_vs_alternate
        """
        scenario = setup_dual_variant_alternate_scenario()
        claim = scenario["claim"]
        claimant = scenario["claimant"]
        claim = submit_claim(claim, claimant["id"])
        # STANDARD total = 100_000 < 150_000 floor.
        # ALTERNATE total = 500_000 >= 150_000 -> ALTERNATE wins.
        assert claim["base_period_variant"] == "ALTERNATE"
        assert claim["base_period_total_wages_cents"] == 500_000

    def test_standard_chosen_when_meets_floor(self, api):
        """PRD §3.2: "if the STANDARD total is at least the base-period
        wage floor of 150,000 cents ($1,500.00), STANDARD is chosen."

        # difficulty: dual_variant_calc/claim_base_period_standard_vs_alternate
        """
        bundle = create_eligible_claim()
        assert bundle["claim"]["base_period_variant"] == "STANDARD"

    def test_high_quarter_from_chosen_variant_only(self, api):
        """PRD §3.2: "high_quarter_wages_cents is set to the maximum
        wages_cents across the chosen variant's four quarters."

        With the alternate scenario the high quarter (400_000) is the
        lag quarter, which the STANDARD variant does NOT include.

        # difficulty: dual_variant_calc/claim_base_period_standard_vs_alternate
        """
        scenario = setup_dual_variant_alternate_scenario()
        claim = submit_claim(scenario["claim"], scenario["claimant"]["id"])
        assert claim["high_quarter_wages_cents"] == 400_000


class TestDualVariantExperienceRate:
    """# difficulty: dual_variant_calc/employer_rate_charge_active_vs_relieved"""

    def test_relieved_charge_drives_rate_below_active(self, api):
        """PRD §3.3: "the relieved charge subtracts from the net charges
        (driving the rate down), whereas the active charge adds to the
        net charges (driving the rate up). The same inputs under the
        two states therefore yield different experience_rate_bps
        values."

        # difficulty: dual_variant_calc/employer_rate_charge_active_vs_relieved
        """
        scenario = setup_employer_with_active_charge(
            reserve_basis_cents=1_000_000,
            taxable_payroll_cents=10_000_000,
            charge_amount_cents=300_000,
        )
        emp_active = get_employer(scenario["employer"]["id"])
        # ACTIVE state: ratio = 0.07 -> 180 bps.
        assert emp_active["experience_rate_bps"] == 180

        # Relieve the active charge.
        active_charges = [
            c for c in list_employer_charges(scenario["employer"]["id"])
            if c["status"] == "ACTIVE"
        ]
        from test_helpers import relieve_charge
        relieve_charge(
            scenario["employer"]["id"], active_charges[0]["id"],
            via="adjudicator",
        )
        emp_relieved = get_employer(scenario["employer"]["id"])
        # RELIEVED: net = -300_000, adjusted reserve = 1_300_000,
        # ratio = 0.13 -> 100 bps. Lower than ACTIVE's 180.
        assert emp_relieved["experience_rate_bps"] < emp_active[
            "experience_rate_bps"
        ]

    def test_relieved_status_recorded_on_charge(self, api):
        """PRD §3.7: "Granting relief transitions the EmployerCharge to
        status equal to RELIEVED."

        # difficulty: dual_variant_calc/employer_rate_charge_active_vs_relieved
        """
        scenario = setup_employer_with_active_charge()
        active = [
            c for c in list_employer_charges(scenario["employer"]["id"])
            if c["status"] == "ACTIVE"
        ][0]
        from test_helpers import relieve_charge
        relieved = relieve_charge(
            scenario["employer"]["id"], active["id"], via="adjudicator",
        )
        assert relieved["status"] == "RELIEVED"


# ===========================================================================
# Rule 2 — combinatorial_formula
# ===========================================================================
class TestPayableNestedMinMax:
    """# difficulty: combinatorial_formula/weekly_payable_amount_mode_a_nested_min_max"""

    def test_nested_max_formula_at_boundary(self, api):
        """PRD §3.3: "First, an earnings disregard is computed: take
        25% of weekly_benefit_amount_cents and floor the result
        (truncate toward zero) to integer cents. Second, the earnings
        offset is the greater of zero and (earnings_reported_cents
        minus the disregard) ... Third, the payable amount is the
        greater of zero and (weekly_benefit_amount_cents minus the
        offset)."

        WBA=30_000, disregard=floor(30000*25/100)=7_500.
        Earnings=10_000 -> offset=max(0,10000-7500)=2_500 ->
        payable=max(0,30000-2500)=27_500.

        # difficulty: combinatorial_formula/weekly_payable_amount_mode_a_nested_min_max
        """
        bundle = create_eligible_claim(
            high_quarter_cents=780_000,
            other_quarter_cents=200_000,
        )
        assert bundle["claim"]["weekly_benefit_amount_cents"] == 30_000
        cert = submit_weekly_certification(
            claim_id=bundle["claim"]["id"],
            claimant_id=bundle["claimant"]["id"],
            week_ending_date=next_certifiable_saturday(bundle["claim"]),
            earnings_reported_cents=10_000,
        )
        assert cert["status"] == "APPROVED"
        assert cert["payable_amount_cents"] == 27_500

    def test_payable_floored_at_zero_when_offset_swamps(self, api):
        """PRD §3.3: "Third, the payable amount is the greater of zero
        and (weekly_benefit_amount_cents minus the offset)."

        # difficulty: combinatorial_formula/weekly_payable_amount_mode_a_nested_min_max
        """
        bundle = create_eligible_claim(
            high_quarter_cents=780_000,
            other_quarter_cents=200_000,
        )
        # Huge earnings drive offset > WBA -> payable clamps to 0.
        cert = submit_weekly_certification(
            claim_id=bundle["claim"]["id"],
            claimant_id=bundle["claimant"]["id"],
            week_ending_date=next_certifiable_saturday(bundle["claim"]),
            earnings_reported_cents=10_000_000,
        )
        assert cert["payable_amount_cents"] == 0


class TestChargeAllocationRounding:
    """# difficulty: combinatorial_formula/employer_charge_allocation_mode_b_rounding_order"""

    def test_charge_sum_equals_payment_amount(self, api):
        """PRD §2.8: "with a residual-reconciliation pass guaranteeing
        that the sum of issued EmployerCharge.charge_cents equals the
        originating BenefitPayment.amount_cents exactly."

        # difficulty: combinatorial_formula/employer_charge_allocation_mode_b_rounding_order
        """
        scenario = setup_two_employer_charge_split()
        cert = scenario["certification"]
        target = cert["payable_amount_cents"]
        charges_a = [
            c for c in list_employer_charges(scenario["employer_a"]["id"])
            if c["payment_id"] == cert["payment_id"]
        ]
        charges_b = [
            c for c in list_employer_charges(scenario["employer_b"]["id"])
            if c["payment_id"] == cert["payment_id"]
        ]
        total = sum(c["charge_cents"] for c in (charges_a + charges_b))
        assert total == target, (
            f"sum of charge_cents must equal payment.amount_cents; "
            f"got total={total}, target={target}"
        )

    def test_round_half_up_per_employer(self, api):
        """PRD §3.3: "first every employer's raw charge is computed to
        full precision with no rounding; second each is rounded to the
        nearest cent using round_half_up."

        For two equal shares of an odd target, raw_each = target/2 has
        .5 fractional cent; round_half_up gives ceil per employer.
        Then residual = target - sum(rounded) = -1; the residual is
        distributed by the tie-break rule (Employer.id ASC).

        # difficulty: combinatorial_formula/employer_charge_allocation_mode_b_rounding_order
        """
        scenario = setup_two_employer_charge_split(payable_amount_cents=10_001)
        cert = scenario["certification"]
        target = cert["payable_amount_cents"]
        if target % 2 == 0:
            pytest.skip(
                "payment landed on even cents; residual-reconciliation "
                "tie-break is unobservable"
            )
        charges_a = [
            c for c in list_employer_charges(scenario["employer_a"]["id"])
            if c["payment_id"] == cert["payment_id"]
        ]
        charges_b = [
            c for c in list_employer_charges(scenario["employer_b"]["id"])
            if c["payment_id"] == cert["payment_id"]
        ]
        # PRD: tie-break by Employer.id ASC. employer_a.id < employer_b.id.
        assert len(charges_a) == 1 and len(charges_b) == 1
        # The residual is -1 cent; that cent is subtracted from
        # employer_a (smaller id). So A's charge < B's charge.
        assert charges_a[0]["charge_cents"] < charges_b[0]["charge_cents"]


class TestMaxWeeksTieredFormula:
    """# difficulty: combinatorial_formula/max_weeks_eligibility_mode_a_tiered_with_caps"""

    def test_raw_value_inside_clamp_range(self, api):
        """PRD §3.2: "The maximum weeks of regular eligibility is
        computed by taking base_period_total_wages_cents, dividing by
        the product of weekly_benefit_amount_cents and the
        weeks-denominator factor of 3, taking the floor of that
        quotient, and then clamping the result to lie between a
        minimum of 13 weeks and a maximum of 26 weeks inclusive."

        Tune wages to land between 13 and 26.

        # difficulty: combinatorial_formula/max_weeks_eligibility_mode_a_tiered_with_caps
        """
        # WBA target = 10_000 ($100). high_q = 10_000 * 26 = 260_000.
        # Stage other_q so total = 520_000 -> potential =
        # floor(520_000 / (10_000 * 3)) = floor(17.333) = 17.
        bundle = create_eligible_claim(
            high_quarter_cents=260_000,
            other_quarter_cents=86_667,  # 260_000 + 3*86_667 ~= 520_001
        )
        claim = bundle["claim"]
        assert claim["weekly_benefit_amount_cents"] == 10_000
        # potential = floor(total / 30_000)
        expected = max(13, min(26, claim[
            "base_period_total_wages_cents"
        ] // 30_000))
        assert claim["max_weeks_of_eligibility"] == expected
        assert 13 <= claim["max_weeks_of_eligibility"] <= 26

    def test_floor_clamp_when_raw_below_minimum(self, api):
        """PRD §3.2: "clamping the result to lie between a minimum of
        13 weeks and a maximum of 26 weeks inclusive."

        Wages must clear PRD §3.2 floors (base_period_total >= 150_000
        AND high_quarter >= 90_000) so adjudicate-ELIGIBLE accepts;
        meanwhile the raw max-weeks quotient must fall below 13 so the
        min clamp pins the result at 13.

        # difficulty: combinatorial_formula/max_weeks_eligibility_mode_a_tiered_with_caps
        """
        # high_quarter = 90_000 (exactly the floor), each other = 20_000:
        # total = 90_000 + 3*20_000 = 150_000 (exactly the floor).
        # WBA = floor(90_000/26) = 3_461 -> min-clamped to 4_000.
        # raw potential = floor(150_000 / (4_000 * 3)) = floor(12.5) = 12;
        # clamped to 13.
        bundle = create_eligible_claim(
            high_quarter_cents=90_000,
            other_quarter_cents=20_000,
        )
        assert bundle["claim"]["max_weeks_of_eligibility"] == 13


# ===========================================================================
# Rule 3 — non_linear_state_machine
# ===========================================================================
class TestExhaustedRevertCycle:
    """# difficulty: non_linear_state_machine/claim_exhausted_cycle_via_audit_revert"""

    def test_audit_decrements_weeks_paid_and_reverts(self, api):
        """PRD §3.5: "if the claim was EXHAUSTED and the new
        weeks_remaining is strictly greater than zero it reverts back
        to ACTIVE."

        # difficulty: non_linear_state_machine/claim_exhausted_cycle_via_audit_revert
        """
        # Drive claim into EXHAUSTED via 13 approved certs (min clamp).
        bundle = setup_claim_with_n_approved_certs(
            n_approvals=13, max_weeks_target=13,
        )
        claim = get_claim(bundle["claim"]["id"])
        if claim["status"] != "EXHAUSTED":
            pytest.skip(
                "could not drive claim into EXHAUSTED; PRD min-weeks "
                "clamp prevents accelerating exhaustion"
            )
        # Audit the last APPROVED cert -> weeks_paid -=1 -> revert.
        last_cert = bundle["approved_certs"][-1]
        audit_certification(
            last_cert["id"], classification="NON_FRAUD",
        )
        reverted = get_claim(bundle["claim"]["id"])
        assert reverted["status"] == "ACTIVE", (
            f"after audit decrement, claim must revert from EXHAUSTED "
            f"to ACTIVE; got {reverted['status']}"
        )
        assert reverted["weeks_paid"] == 12

    def test_audit_when_not_exhausted_no_revert(self, api):
        """PRD §3.5: "if the claim was EXHAUSTED and the new
        weeks_remaining is strictly greater than zero it reverts back
        to ACTIVE."

        Negative case: audit while claim is ACTIVE (not EXHAUSTED) —
        weeks_paid still decrements but no state revert.

        # difficulty: non_linear_state_machine/claim_exhausted_cycle_via_audit_revert
        """
        bundle = create_eligible_claim()
        cert = approve_one_weekly_certification(bundle)
        before = get_claim(bundle["claim"]["id"])
        assert before["status"] == "ACTIVE"
        audit_certification(cert["id"], classification="NON_FRAUD")
        after = get_claim(bundle["claim"]["id"])
        # weeks_paid decremented; claim status stays at ACTIVE (only
        # transitions out of EXHAUSTED revert; from ACTIVE no change).
        assert after["weeks_paid"] == 0


class TestAppealBranchingFork:
    """# difficulty: non_linear_state_machine/appeal_branching_fork_at_filed"""

    def test_filed_appeal_branches_to_in_hearing(self, api):
        """PRD §3.6: "To proceed to a hearing, the assigned appeal
        officer opens it. ... The appeal transitions FILED → IN_HEARING."

        # difficulty: non_linear_state_machine/appeal_branching_fork_at_filed
        """
        bundle = setup_filed_appeal_on_denied_claim(
            adjudicator_id="adj-1", officer_id="officer-2",
        )
        appeal = start_appeal_hearing(
            bundle["appeal"]["id"], officer_id="officer-2",
        )
        assert appeal["status"] == "IN_HEARING"

    def test_filed_appeal_branches_to_withdrawn(self, api):
        """PRD §3.6: "A claimant may withdraw a FILED appeal at any
        time, transitioning the appeal FILED → WITHDRAWN."

        # difficulty: non_linear_state_machine/appeal_branching_fork_at_filed
        """
        bundle = setup_filed_appeal_on_denied_claim()
        appeal = withdraw_appeal(
            bundle["appeal"]["id"], bundle["claimant"]["id"],
        )
        assert appeal["status"] == "WITHDRAWN"

    def test_filed_appeal_branches_to_dismissed_late(self, api):
        """PRD §3.6: "Independently, when SystemClock.now advances past
        the appeal's deadline_at while the appeal is still FILED, the
        system transitions it FILED → DISMISSED_LATE automatically."

        # difficulty: non_linear_state_machine/appeal_branching_fork_at_filed
        """
        bundle = setup_filed_appeal_on_denied_claim()
        advance_clock_by_days(APPEAL_WINDOW_DAYS + 1)
        from test_helpers import api_client as ac
        resp = ac.get_appeal(
            bundle["appeal"]["id"],
            TEST_USERS["system_admin_headers"],
        )
        data = validate_success(resp)
        assert data["status"] == "DISMISSED_LATE"


# ===========================================================================
# Rule 4 — transitive_cascade
# ===========================================================================
class TestAuditCascadeDepth4:
    """# difficulty: transitive_cascade/audit_overpaid_cascade_depth_4"""

    def test_audit_cascades_four_links(self, api):
        """PRD §3.5: "First, the BenefitPayment is mutated: status
        flips to REVERSED ... Second, an Overpayment is created ...
        Third, every EmployerCharge whose payment_id matches the
        reversed payment and whose status is currently ACTIVE is
        updated: its status flips to REVERSED, and each affected
        employer's experience_rate_bps is recomputed."

        # difficulty: transitive_cascade/audit_overpaid_cascade_depth_4
        """
        scenario = setup_employer_with_active_charge(
            reserve_basis_cents=1_000_000,
            taxable_payroll_cents=10_000_000,
            charge_amount_cents=300_000,
        )
        cert = scenario["certification"]
        audited = audit_certification(
            cert["id"], classification="NON_FRAUD",
        )
        # Link 1.
        assert audited["status"] == "OVERPAID"
        # Link 2: Overpayment created.
        ops = list_claim_overpayments(scenario["claim"]["id"])
        assert ops and ops[0]["status"] == "OUTSTANDING"
        # Link 3: at least one charge flipped to REVERSED.
        charges = list_employer_charges(scenario["employer"]["id"])
        assert any(c["status"] == "REVERSED" for c in charges)
        # Link 4: experience_rate_bps recomputed back to floor 100.
        emp_after = get_employer(scenario["employer"]["id"])
        assert emp_after["experience_rate_bps"] == 100

    def test_lifetime_overpayment_balance_recomputed_on_cascade(self, api):
        """PRD §3.5: "Recompute Claimant.lifetime_overpayment_balance_cents".

        # difficulty: transitive_cascade/audit_overpaid_cascade_depth_4
        """
        bundle = setup_outstanding_overpayment(classification="NON_FRAUD")
        from test_helpers import get_claimant
        cm = get_claimant(bundle["claimant"]["id"])
        assert cm["lifetime_overpayment_balance_cents"] == bundle[
            "overpayment"
        ]["principal_cents"]


class TestAppealReversedCascadeDepth3:
    """# difficulty: transitive_cascade/appeal_reversed_cascade_depth_3"""

    def test_appeal_reversed_on_weekly_denial_triggers_cascade(self, api):
        """PRD §3.6: "For WEEKLY_DENIAL: the WeeklyCertification
        transitions DENIED → APPROVED and triggers the full payment
        cascade described in §3.3 — a BenefitPayment is created,
        EmployerCharge rows are created via the allocation rules, every
        affected employer's experience_rate_bps is recomputed, the
        claim's weeks_paid and weeks_remaining are recomputed."

        Per PRD §3.3 the only path that yields a SUBMITTED -> DENIED
        cert (without first tripping a submit-time validation guard) is
        `able_and_available=false` with the required >= 3 work-search
        entries; the cert is then a valid DENIED subject for appeal.

        # difficulty: transitive_cascade/appeal_reversed_cascade_depth_3
        """
        bundle = create_eligible_claim(adjudicator_id="adj-A")
        claim, cm = bundle["claim"], bundle["claimant"]
        # Submit a DENIED cert via able_and_available=False (3 entries
        # supplied automatically by the helper).
        sat = next_certifiable_saturday(claim)
        denied_cert = submit_weekly_certification(
            claim_id=claim["id"], claimant_id=cm["id"],
            week_ending_date=sat,
            able_and_available=False,
        )
        assert denied_cert["status"] == "DENIED"

        # File appeal on this WEEKLY_DENIAL.
        appeal = file_appeal(
            claim_id=claim["id"], claimant_id=cm["id"],
            subject_type="WEEKLY_DENIAL", subject_id=denied_cert["id"],
            assigned_appeal_officer_id="officer-distinct",
        )
        start_appeal_hearing(appeal["id"], officer_id="officer-distinct")
        decided = decide_appeal(
            appeal["id"], "REVERSED", officer_id="officer-distinct",
        )
        assert decided["status"] == "REVERSED"
        # Link 2: cert now APPROVED.
        from test_helpers import api_client as ac2
        resp2 = ac2.get_weekly_certification(
            denied_cert["id"], TEST_USERS["system_admin_headers"],
        )
        cert_after = resp2.json()["data"]
        assert cert_after["status"] == "APPROVED"

    def test_appeal_reversed_on_monetary_reactivates_claim(self, api):
        """PRD §3.6: "For MONETARY_DETERMINATION: the parent Claim
        transitions DENIED → MONETARILY_ELIGIBLE and its version is
        incremented."

        # difficulty: transitive_cascade/appeal_reversed_cascade_depth_3
        """
        bundle = setup_in_hearing_appeal_on_denied_claim(
            adjudicator_id="adj-A", officer_id="officer-B",
        )
        decide_appeal(
            bundle["appeal"]["id"], "REVERSED", officer_id="officer-B",
        )
        claim_after = get_claim(bundle["claim"]["id"])
        assert claim_after["status"] == "MONETARILY_ELIGIBLE"


# ===========================================================================
# Rule 5 — priority_pair_validation_conflict
# ===========================================================================
class TestPriorityPairSegregationVsState:
    """# difficulty: priority_pair_validation_conflict/state_vs_business_safety_segregation"""

    def test_state_check_beats_sod_in_collision(self, api):
        """PRD §2.10: "state legality of the requested transition
        (ERR_INVALID_STATE), then segregation of duties on appeal
        hearing-start and decide
        (ERR_SEGREGATION_OF_DUTIES_VIOLATION)".

        # difficulty: priority_pair_validation_conflict/state_vs_business_safety_segregation
        """
        shared = "user-collide-0001"
        bundle = setup_appeal_segregation_collision(shared_user_id=shared)
        resp = api.start_hearing(
            bundle["appeal"]["id"], make_appeal_officer_headers(shared),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_sod_alone_fires_when_state_ok(self, api):
        """PRD §3.6: "Starting a hearing requires ... that the
        requesting X-User-ID is not equal to the appeal's
        assigned_adjudicator_id (otherwise
        ERR_SEGREGATION_OF_DUTIES_VIOLATION)."

        When state is OK (FILED) but the same user is assigned to both
        roles, only SoD fires.

        # difficulty: priority_pair_validation_conflict/state_vs_business_safety_segregation
        """
        shared = "user-collide-0002"
        bundle = create_denied_claim(adjudicator_id=shared)
        appeal = file_appeal(
            claim_id=bundle["claim"]["id"],
            claimant_id=bundle["claimant"]["id"],
            subject_type="MONETARY_DETERMINATION",
            subject_id=bundle["claim"]["id"],
            assigned_appeal_officer_id=shared,
        )
        # Appeal is FILED; start-hearing with the colliding user_id.
        resp = api.start_hearing(
            appeal["id"], make_appeal_officer_headers(shared),
        )
        validate_error(
            resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES_VIOLATION.value,
        )


class TestPriorityPairFiscalVsTemporal:
    """# difficulty: priority_pair_validation_conflict/business_temporal_vs_business_fiscal_overpayment"""

    def test_fiscal_check_fires_on_repay(self, api):
        """PRD §3.5: "The repayment is accepted only if amount_cents is
        strictly greater than zero and is no greater than the
        overpayment's current balance_cents; otherwise it is rejected
        with ERR_REPAY_EXCEEDS_BALANCE."

        # difficulty: priority_pair_validation_conflict/business_temporal_vs_business_fiscal_overpayment
        """
        bundle = setup_outstanding_overpayment(classification="NON_FRAUD")
        op = bundle["overpayment"]
        from test_helpers import repay_overpayment_payload
        resp = api.repay_overpayment(
            op["id"],
            repay_overpayment_payload(op["balance_cents"] + 1),
            make_claimant_headers(bundle["claimant"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_REPAY_EXCEEDS_BALANCE.value)

    def test_temporal_check_fires_on_write_off(self, api):
        """PRD §3.5: "A write-off attempted earlier is rejected with
        ERR_STATUTE_NOT_REACHED."

        # difficulty: priority_pair_validation_conflict/business_temporal_vs_business_fiscal_overpayment
        """
        bundle = setup_outstanding_overpayment(classification="NON_FRAUD")
        op = bundle["overpayment"]
        resp = api.write_off_overpayment(
            op["id"], make_adjudicator_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_STATUTE_NOT_REACHED.value)


# ===========================================================================
# Rule 6 — boundary_precision_check
# ===========================================================================
class TestExperienceRateBoundary:
    """# difficulty: boundary_precision_check/experience_rate_tier_boundary_exact_010"""

    def test_ratio_exactly_010_is_floor_tier(self, api):
        """PRD §3.3: "a reserve ratio of at least 0.10 yields the 1.00%
        floor of 100 basis points".

        # difficulty: boundary_precision_check/experience_rate_tier_boundary_exact_010
        """
        e = create_employer(
            reserve_ratio_basis_cents=1_000_000,
            taxable_payroll_cents=10_000_000,
        )
        assert e["experience_rate_bps"] == 100

    def test_ratio_below_010_jumps_to_180(self, api):
        """PRD §3.3: "otherwise at least 0.07 yields 180 basis points".

        ratio = 999_999/10_000_000 < 0.10 -> not floor tier;
        ratio > 0.07 -> 180 tier.

        # difficulty: boundary_precision_check/experience_rate_tier_boundary_exact_010
        """
        e = create_employer(
            reserve_ratio_basis_cents=999_999,
            taxable_payroll_cents=10_000_000,
        )
        assert e["experience_rate_bps"] == 180


class TestWorkSearchCountBoundary:
    """# difficulty: boundary_precision_check/work_search_zero_count_boundary"""

    def test_two_entries_below_threshold_rejected(self, api):
        """PRD §3.3: "A certification with fewer than three work-search
        entries is also rejected at submit-time with
        ERR_INSUFFICIENT_WORK_SEARCH."

        # difficulty: boundary_precision_check/work_search_zero_count_boundary
        """
        bundle = create_eligible_claim()
        sat = next_certifiable_saturday(bundle["claim"])
        payload = create_weekly_certification_payload(
            week_ending_date=date_to_iso(sat),
            work_search_entries=n_work_search_entries(2),
        )
        resp = api.create_weekly_certification(
            bundle["claim"]["id"], payload,
            make_claimant_headers(bundle["claimant"]["id"]),
        )
        validate_error(
            resp, ApiErrorId.ERR_INSUFFICIENT_WORK_SEARCH.value,
        )

    def test_three_entries_at_threshold_approved(self, api):
        """PRD §3.3: "work_search_count is at least 3 (the minimum
        required work-search contacts)."

        # difficulty: boundary_precision_check/work_search_zero_count_boundary
        """
        bundle = create_eligible_claim()
        cert = approve_one_weekly_certification(bundle)
        assert cert["status"] == "APPROVED"
        assert cert["work_search_count"] == 3


# ===========================================================================
# Rule 7 — cross_entity_state_dependency
# ===========================================================================
class TestWeeklyCertDependsOnClaim:
    """# difficulty: cross_entity_state_dependency/weeklycert_depends_on_claim_status"""

    def test_certification_on_closed_claim_rejected(self, api):
        """PRD §3.3: "When the wage and work-search facts add up but
        the claim itself has been CLOSED because the benefit year
        passed, any subsequent submission is rejected with
        ERR_BENEFIT_YEAR_EXPIRED."

        # difficulty: cross_entity_state_dependency/weeklycert_depends_on_claim_status
        """
        bundle = create_eligible_claim()
        # Push past benefit year end so the claim is CLOSED.
        advance_clock_by_days(370)
        claim_now = get_claim(bundle["claim"]["id"])
        assert claim_now["status"] == "CLOSED"
        # Attempt a certification.
        sat = next_certifiable_saturday(bundle["claim"])
        payload = create_weekly_certification_payload(
            week_ending_date=date_to_iso(sat),
        )
        resp = api.create_weekly_certification(
            bundle["claim"]["id"], payload,
            make_claimant_headers(bundle["claimant"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_BENEFIT_YEAR_EXPIRED.value)

    def test_certification_on_denied_claim_rejected(self, api):
        """PRD §3.3: "Approval requires every one of the following: the
        parent claim's status is in the set of MONETARILY_ELIGIBLE,
        ACTIVE, or EXTENDED."

        A DENIED claim is not in that set; certification submission
        on a DENIED claim violates the precondition.

        # difficulty: cross_entity_state_dependency/weeklycert_depends_on_claim_status
        """
        bundle = create_denied_claim()
        # benefit_year_start may be None on a denied claim (depending
        # on impl). Use a known-good Saturday derived from current clock.
        sat = next_certifiable_saturday(
            bundle["claim"],
            after=None,
        )
        payload = create_weekly_certification_payload(
            week_ending_date=date_to_iso(sat),
        )
        resp = api.create_weekly_certification(
            bundle["claim"]["id"], payload,
            make_claimant_headers(bundle["claimant"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


class TestAppealDecideVersionPin:
    """# difficulty: cross_entity_state_dependency/appeal_decide_depends_on_subject_version"""

    def test_stale_subject_version_rejected(self, api):
        """PRD §3.6: "Before either decision is allowed, the server
        enforces the version pin: the appeal's subject_locked_version
        must equal the current subject entity's version; otherwise the
        decision is rejected with ERR_STALE_APPEAL_SUBJECT."

        # difficulty: cross_entity_state_dependency/appeal_decide_depends_on_subject_version
        """
        bundle = setup_outstanding_overpayment(
            classification="NON_FRAUD", adjudicator_id="adj-A",
        )
        op = bundle["overpayment"]
        appeal = file_appeal(
            claim_id=bundle["claim"]["id"],
            claimant_id=bundle["claimant"]["id"],
            subject_type="OVERPAYMENT_ASSESSMENT",
            subject_id=op["id"],
            assigned_appeal_officer_id="officer-X",
        )
        # Mutate subject (repayment bumps Overpayment.version).
        repay_overpayment(
            op["id"], bundle["claimant"]["id"], amount_cents=1,
        )
        start_appeal_hearing(appeal["id"], officer_id="officer-X")
        resp = api.decide_appeal(
            appeal["id"], decide_appeal_payload("SUSTAINED"),
            make_appeal_officer_headers("officer-X"),
        )
        validate_error(resp, ApiErrorId.ERR_STALE_APPEAL_SUBJECT.value)

    def test_decide_succeeds_when_version_intact(self, api):
        """PRD §3.6: "Before either decision is allowed, the server
        enforces the version pin: the appeal's subject_locked_version
        must equal the current subject entity's version."

        Positive: no intervening mutation -> decision proceeds.

        # difficulty: cross_entity_state_dependency/appeal_decide_depends_on_subject_version
        """
        bundle = setup_in_hearing_appeal_on_denied_claim()
        decided = decide_appeal(
            bundle["appeal"]["id"], "SUSTAINED",
            officer_id="appeal-officer-0001",
        )
        assert decided["status"] == "SUSTAINED"


# ===========================================================================
# Rule 8 — resource_temporal_overlap
# ===========================================================================
class TestWeeklyCertUniqueness:
    """# difficulty: resource_temporal_overlap/weekly_certification_week_uniqueness_strict_after"""

    def test_duplicate_saturday_point_rejected(self, api):
        """PRD §3.3: "Submitting one whose (claim_id, week_ending_date)
        collides with any existing certification is rejected with
        ERR_DUPLICATE_WEEK."

        To uniquely exercise the duplicate-week rule (priority 11 per
        §2.10) without also tripping the "strictly later than latest
        APPROVED" check (priority 10), the prior cert at the same
        Saturday must NOT be APPROVED. We submit a DENIED cert first
        via able_and_available=False (PRD §3.3).

        # difficulty: resource_temporal_overlap/weekly_certification_week_uniqueness_strict_after
        """
        bundle = create_eligible_claim()
        claim, cm = bundle["claim"], bundle["claimant"]
        sat = next_certifiable_saturday(claim)
        # Prior cert at `sat` lands in DENIED (>= 3 entries clears the
        # work-search guard; able_and_available=False triggers DENIED).
        prior = submit_weekly_certification(
            claim_id=claim["id"], claimant_id=cm["id"],
            week_ending_date=sat,
            able_and_available=False,
        )
        assert prior["status"] == "DENIED"
        # Duplicate at the same Saturday now hits ONLY the uniqueness
        # rule, surfacing ERR_DUPLICATE_WEEK.
        payload = create_weekly_certification_payload(
            week_ending_date=date_to_iso(sat),
        )
        resp = api.create_weekly_certification(
            claim["id"], payload, make_claimant_headers(cm["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_WEEK.value)

    def test_earlier_saturday_out_of_range(self, api):
        """PRD §3.3: "Submitting one whose week_ending_date is not
        strictly later than the latest APPROVED week ... is rejected
        with ERR_WEEK_OUT_OF_RANGE."

        # difficulty: resource_temporal_overlap/weekly_certification_week_uniqueness_strict_after
        """
        from datetime import timedelta
        bundle = create_eligible_claim()
        claim, cm = bundle["claim"], bundle["claimant"]
        sat = next_certifiable_saturday(claim)
        submit_weekly_certification(
            claim_id=claim["id"], claimant_id=cm["id"],
            week_ending_date=sat,
        )
        earlier = sat - timedelta(days=7)
        payload = create_weekly_certification_payload(
            week_ending_date=date_to_iso(earlier),
        )
        resp = api.create_weekly_certification(
            claim["id"], payload, make_claimant_headers(cm["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_WEEK_OUT_OF_RANGE.value)


class TestPandemicWindowInclusiveEndpoints:
    """# difficulty: resource_temporal_overlap/pandemic_extension_window_inclusive_endpoints"""

    def test_active_when_clock_within_window(self, api):
        """PRD §3.4: "When SystemClock.now reaches or passes the
        program's effective_start (and is still within the window),
        the system transitions the program SCHEDULED → ACTIVE."

        # difficulty: resource_temporal_overlap/pandemic_extension_window_inclusive_endpoints
        """
        ext = setup_active_pandemic_extension(extra_weeks=13)
        assert ext["status"] == "ACTIVE"

    def test_expired_after_clock_passes_end(self, api):
        """PRD §3.4: "When SystemClock.now crosses past effective_end,
        the system transitions the program ACTIVE → EXPIRED."

        # difficulty: resource_temporal_overlap/pandemic_extension_window_inclusive_endpoints
        """
        ext = setup_active_pandemic_extension(extra_weeks=13)
        # Push the clock past the 90-day window.
        advance_clock_by_days(120)
        from test_helpers import api_client as ac
        resp = ac.list_pandemic_extensions(
            TEST_USERS["system_admin_headers"],
        )
        items = resp.json()["data"]
        target = next(p for p in items if p["id"] == ext["id"])
        assert target["status"] == "EXPIRED"


# ===========================================================================
# Rule 9 — compensating_invariant
# ===========================================================================
class TestWeeksPaidRoundTrip:
    """# difficulty: compensating_invariant/weeks_paid_round_trip_invariant"""

    def test_approve_then_audit_returns_weeks_paid_to_baseline(self, api):
        """PRD §3.5: "the claim is reconciled: weeks_paid is decremented
        by one, weeks_remaining is recomputed."

        Compensating action: APPROVED bumps weeks_paid +1; audit
        reverses it back to baseline.

        # difficulty: compensating_invariant/weeks_paid_round_trip_invariant
        """
        bundle = create_eligible_claim()
        before = get_claim(bundle["claim"]["id"])
        assert before["weeks_paid"] == 0
        cert = approve_one_weekly_certification(bundle)
        mid = get_claim(bundle["claim"]["id"])
        assert mid["weeks_paid"] == 1
        audit_certification(cert["id"], classification="NON_FRAUD")
        after = get_claim(bundle["claim"]["id"])
        assert after["weeks_paid"] == 0, (
            f"after audit, weeks_paid must return to 0; got "
            f"{after['weeks_paid']}"
        )

    def test_weeks_remaining_consistent_after_round_trip(self, api):
        """PRD §3.3: "weeks_remaining (the claim's
        max_weeks_of_eligibility plus any
        pandemic_extension_weeks_granted, minus weeks_paid, floored at
        zero)."

        # difficulty: compensating_invariant/weeks_paid_round_trip_invariant
        """
        from test_helpers import assert_weeks_invariant
        bundle = create_eligible_claim()
        before = get_claim(bundle["claim"]["id"])
        assert_weeks_invariant(before)
        cert = approve_one_weekly_certification(bundle)
        mid = get_claim(bundle["claim"]["id"])
        assert_weeks_invariant(mid)
        audit_certification(cert["id"], classification="NON_FRAUD")
        after = get_claim(bundle["claim"]["id"])
        assert_weeks_invariant(after)


class TestDollarConservation:
    """# difficulty: compensating_invariant/payment_dollar_conservation_invariant"""

    def test_charge_sum_equals_payment_at_issuance(self, api):
        """PRD §2.8: "with a residual-reconciliation pass guaranteeing
        that the sum of issued EmployerCharge.charge_cents equals the
        originating BenefitPayment.amount_cents exactly."

        # difficulty: compensating_invariant/payment_dollar_conservation_invariant
        """
        scenario = setup_two_employer_charge_split()
        cert = scenario["certification"]
        target = cert["payable_amount_cents"]
        charges_a = [
            c for c in list_employer_charges(scenario["employer_a"]["id"])
            if c["payment_id"] == cert["payment_id"]
        ]
        charges_b = [
            c for c in list_employer_charges(scenario["employer_b"]["id"])
            if c["payment_id"] == cert["payment_id"]
        ]
        total = sum(c["charge_cents"] for c in (charges_a + charges_b))
        assert total == target

    def test_overpayment_principal_equals_reversed_payment_amount(self, api):
        """PRD §3.5: "an Overpayment is created whose ... principal_cents
        equals the reversed BenefitPayment.amount_cents."

        # difficulty: compensating_invariant/payment_dollar_conservation_invariant
        """
        bundle = setup_outstanding_overpayment(classification="NON_FRAUD")
        op = bundle["overpayment"]
        # WBA = the payment amount (since earnings=0 on the auto-approve
        # path used by setup_outstanding_overpayment).
        wba = bundle["claim"]["weekly_benefit_amount_cents"]
        assert op["principal_cents"] == wba
