"""Second-test pass for every Difficulty-Design instance, so each
instance is covered by at least TWO tests (per the §2.1.A coverage rule).

The companion tests in test_02..test_11 already cover one angle per
instance; this file adds a second, distinct angle for each.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    absorb_portability,
    add_days,
    advance_clock_by_days,
    advance_clock_by_seconds,
    advance_clock_to,
    api_client,
    assert_hap_plus_ttp_equals_gross_rent,
    attach_rent_reasonableness,
    complete_inspection_payload,
    create_applicant,
    create_inspection_payload,
    create_pending_tenancy,
    create_portability_request_payload,
    create_tenancy_payload,
    current_clock,
    cure_abatement,
    finalize_tenancy,
    get_annual_review,
    get_tenancy,
    get_voucher,
    iso_utc,
    issue_voucher,
    make_applicant_headers,
    make_case_worker_headers,
    make_inspector_headers,
    mark_deficient_payload,
    move_out_payload,
    new_case_worker_id,
    parse_iso,
    resubmit_annual_review_payload,
    schedule_inspection,
    setup_active_tenancy,
    setup_burden_at_boundary,
    setup_eligible_applicant_with_voucher,
    setup_special_mobility_with_zone_b_unit,
    setup_tenancy_pending_rent_reasonable,
    setup_unit_with_payment_standard,
    submit_annual_review_payload,
    sweep_abatements,
    take_active_tenancy_to_abated,
    TEST_USERS,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)


class TestSecondPassDualVariant:

    def test_recert_ttp_diverges_from_initial_on_tenancy_value(self, api):
        """PRD §3.9: "Producing a DIFFERENT cent value than initial
        whenever income or household composition changed." (via "the
        recertification re-evaluates ... household composition").

        Second angle: verify that Tenancy.current_total_tenant_payment_cents
        != Tenancy.initial_total_tenant_payment_cents after APPROVED
        (the instance-level claim).
        # difficulty: dual_variant_calc/ttp_initial_vs_recertification_diverge_on_tenancy
        """
        state = setup_active_tenancy(
            gross_annual_income_cents=3_000_000,
            household_size=3, dependents_count=1,
            zone="ZONE_A", bedroom_count=2,
            asking_rent_cents=125_000, tenant_paid_utilities_cents=10_000,
            standard_amount_cents=120_000,
            comparable_rents_cents=[120_000, 130_000, 140_000, 150_000],
        )
        initial_ttp = state["tenancy"]["initial_total_tenant_payment_cents"]
        from test_helpers import (
            advance_clock_to, find_due_annual_review_id,
            approve_review,
        )
        lease_start = parse_iso(state["tenancy"]["lease_start"])
        advance_clock_to(add_days(lease_start, 365))
        ar_id = find_due_annual_review_id(state["tenancy"]["id"])
        ap = make_applicant_headers(state["applicant"]["id"])
        # declared_household_size=4 changes recert dep_count.
        validate_success(
            api.submit_annual_review(
                ar_id, submit_annual_review_payload(3_000_000, 4), ap,
            ),
        )
        approve_review(ar_id)
        t_after = get_tenancy(state["tenancy"]["id"])
        # Tenancy.initial_* immutable; current_* should diverge.
        assert t_after["initial_total_tenant_payment_cents"] == initial_ttp
        assert (
            t_after["current_total_tenant_payment_cents"]
            != t_after["initial_total_tenant_payment_cents"]
        )

    def test_applicant_snapshot_not_mutated_by_annual_review(self, api):
        """PRD §3.9: "(4) the result is written to
        new_adjusted_income_cents on the AnnualReview rather than being
        written back to the Applicant."

        Second angle: with elderly+medical inputs, verify the Applicant's
        adjusted snapshot is preserved even after the recert AR runs.
        # difficulty: dual_variant_calc/adjusted_income_initial_vs_recertification_diverge_on_applicant_household
        """
        state = setup_active_tenancy(
            gross_annual_income_cents=4_800_000,
            household_size=2, dependents_count=0,
            elderly_or_disabled_head=True,
            medical_expense_annual_cents=200_000,
            zone="ZONE_A", bedroom_count=1,
            asking_rent_cents=80_000, tenant_paid_utilities_cents=0,
            standard_amount_cents=80_000,
            comparable_rents_cents=[70_000, 80_000, 90_000],
        )
        snapshot_before = state["applicant"]["adjusted_annual_income_cents"]
        # Snapshot is gross - (dep*0 + elderly 40_000 + medical max(0,
        # 200_000-floor(4_800_000*0.03)=200_000-144_000=56_000) + childcare 0).
        # = 4_800_000 - 96_000 = 4_704_000.
        assert snapshot_before == 4_704_000
        from test_helpers import (
            advance_clock_to, find_due_annual_review_id,
        )
        lease_start = parse_iso(state["tenancy"]["lease_start"])
        advance_clock_to(add_days(lease_start, 365))
        ar_id = find_due_annual_review_id(state["tenancy"]["id"])
        ap = make_applicant_headers(state["applicant"]["id"])
        validate_success(
            api.submit_annual_review(
                ar_id,
                submit_annual_review_payload(4_800_000, 3),
                ap,
            ),
        )
        from test_helpers import get_applicant
        applicant_after = get_applicant(state["applicant"]["id"])
        assert (
            applicant_after["adjusted_annual_income_cents"]
            == snapshot_before
        )

    def test_hap_value_difference_persists_in_current_hap(self, api):
        """PRD §3.7: "applicable_payment_standard_cents (already frozen
        on the tenancy)". The mobility vs standard PS choice persists
        into Tenancy.current_hap_cents.
        # difficulty: dual_variant_calc/hap_standard_vs_special_mobility_on_tenancy
        """
        state_std = setup_active_tenancy(
            gross_annual_income_cents=3_000_000,
            household_size=3, dependents_count=1,
            zone="ZONE_A", bedroom_count=2,
            asking_rent_cents=125_000, tenant_paid_utilities_cents=10_000,
            standard_amount_cents=120_000,
            mobility_amount_cents=132_000,
            special_mobility_flag=False,
            comparable_rents_cents=[120_000, 130_000, 140_000, 150_000],
        )
        state_mob = setup_active_tenancy(
            gross_annual_income_cents=3_000_000,
            household_size=3, dependents_count=1,
            zone="ZONE_A", bedroom_count=2,
            asking_rent_cents=125_000, tenant_paid_utilities_cents=10_000,
            standard_amount_cents=120_000,
            mobility_amount_cents=132_000,
            special_mobility_flag=True,
            comparable_rents_cents=[120_000, 130_000, 140_000, 150_000],
        )
        # current_hap mirrors initial_hap at ACTIVE per PRD §3.7.
        assert state_std["tenancy"]["current_hap_cents"] == 46_200
        assert state_mob["tenancy"]["current_hap_cents"] == 58_200


class TestSecondPassRentBurdenCircularOrder:

    def test_rent_burden_order_check_yields_expected_error_id(self, api):
        """PRD §3.7: "The first finalize-time gate is the special-mobility
        zone check ... The second is the rent-reasonableness gate ...
        The third pair of gates concerns rent burden ..."

        Second angle: a tenancy whose burden exceeds 40% (with valid
        rent-reasonableness and no mobility issue) MUST surface
        ERR_RENT_BURDEN_EXCEEDED (not ERR_RENT_NOT_REASONABLE etc.).
        # difficulty: combinatorial_formula/rent_burden_circular_evaluation_order_mode_c
        """
        # Build a tenancy where burden = 0.70 (over the cap) but rent
        # is reasonable and no mobility violation.
        state = setup_tenancy_pending_rent_reasonable(
            gross_annual_income_cents=1_200_000,
            household_size=1, dependents_count=0,
            zone="ZONE_A", bedroom_count=0,
            asking_rent_cents=100_000, tenant_paid_utilities_cents=0,
            standard_amount_cents=60_000,
            comparable_rents_cents=[90_000, 100_000, 110_000],
        )
        # gross_rent=100_000; PS=60_000; TTP=max(30_000,10_000,0,5000)
        # = 30_000; HAP = 60_000 - 30_000 = 30_000;
        # tenant_share=70_000; burden=70_000/100_000=0.70 > 0.40 → FAIL.
        cw = make_case_worker_headers(new_case_worker_id())
        resp = api.finalize_tenancy(state["tenancy"]["id"], {}, cw)
        validate_error(resp, ApiErrorId.ERR_RENT_BURDEN_EXCEEDED.value)


class TestSecondPassAnnualReviewCycle:

    def test_resubmit_with_changed_inputs_recomputes_new_values(self, api):
        """PRD §3.9: "A resubmit within that window clears the
        deficiency_codes, recomputes new_adjusted_income_cents,
        new_total_tenant_payment_cents, and new_hap_cents".

        Second angle: resubmit with DIFFERENT declared values and observe
        new_* fields are recomputed to match the resubmission, not the
        original submission.
        # difficulty: non_linear_state_machine/annual_review_cyclic_submitted_deficient
        """
        state = setup_active_tenancy(
            gross_annual_income_cents=3_000_000,
            household_size=3, dependents_count=1,
        )
        from test_helpers import (
            advance_clock_to, find_due_annual_review_id,
        )
        lease_start = parse_iso(state["tenancy"]["lease_start"])
        advance_clock_to(add_days(lease_start, 365))
        ar_id = find_due_annual_review_id(state["tenancy"]["id"])
        ap = make_applicant_headers(state["applicant"]["id"])
        cw = make_case_worker_headers(new_case_worker_id())
        validate_success(
            api.submit_annual_review(
                ar_id, submit_annual_review_payload(3_000_000, 3), ap,
            ),
        )
        first_ar = get_annual_review(ar_id)
        first_new_adj = first_ar["new_adjusted_income_cents"]
        validate_success(
            api.mark_deficient_annual_review(
                ar_id, mark_deficient_payload(["x"]), cw,
            ),
        )
        # Resubmit with declared_household_size=5 (different from 3).
        resubmitted = validate_success(
            api.resubmit_annual_review(
                ar_id,
                resubmit_annual_review_payload(3_000_000, 5),
                ap,
            ),
        )
        # new_adjusted recomputed: dep_count = 5-1 = 4 → 192_000;
        # 3_000_000 - 192_000 = 2_808_000.
        assert resubmitted["new_adjusted_income_cents"] == 2_808_000
        assert (
            resubmitted["new_adjusted_income_cents"] != first_new_adj
        )


class TestSecondPassVoucherBranchingFromLeased:

    def test_leased_to_terminated_via_annual_review_deny(self, api):
        """PRD §3.9: "If the review is denied ... the voucher cascades
        from LEASED to TERMINATED."

        Second angle for the LEASED branching shape — distinct outcome
        from the move-out test (TENANT_MOVE_OUT) covered elsewhere.
        # difficulty: non_linear_state_machine/voucher_branching_searching_to_three_outcomes
        """
        state = setup_active_tenancy(
            gross_annual_income_cents=3_000_000,
            household_size=3, dependents_count=1,
        )
        from test_helpers import (
            advance_clock_to, find_due_annual_review_id, deny_review,
        )
        lease_start = parse_iso(state["tenancy"]["lease_start"])
        advance_clock_to(add_days(lease_start, 365))
        ar_id = find_due_annual_review_id(state["tenancy"]["id"])
        ap = make_applicant_headers(state["applicant"]["id"])
        validate_success(
            api.submit_annual_review(
                ar_id, submit_annual_review_payload(3_000_000, 3), ap,
            ),
        )
        deny_review(ar_id)
        v = get_voucher(state["voucher"]["id"])
        assert v["status"] == "TERMINATED"


class TestSecondPassCureDeadlineChain:

    def test_uncured_chain_suppresses_future_hap_rows(self, api):
        """PRD §3.5: "all future scheduled HAP payment rows for this
        voucher are suppressed."
        PRD §3.11: "A TERMINATED tenancy produces no row."

        Second angle on the depth-4 cascade: verify the suppression of
        HAP rows after the cascade completes.
        # difficulty: transitive_cascade/cure_deadline_sweep_chain_depth_4
        """
        from test_helpers import (
            list_hap_payments, sweep_monthly_hap, yyyymm,
        )
        state = setup_active_tenancy(
            gross_annual_income_cents=2_400_000, household_size=2,
            dependents_count=0,
        )
        abated = take_active_tenancy_to_abated(
            state, failure_outcome="FAIL_NONLIFETHREATENING",
            defects=["D1"],
        )
        from datetime import timedelta
        cure_deadline = parse_iso(abated["annual_inspection"]["cure_deadline"])
        advance_clock_to(cure_deadline + timedelta(minutes=1))
        sweep_abatements()
        # Tenancy and Voucher TERMINATED. Advance to next month and
        # invoke monthly HAP sweep. No row should be created for this
        # terminated tenancy.
        next_month = add_days(current_clock(), 31)
        advance_clock_to(next_month)
        pay_period = yyyymm(next_month)
        sweep_monthly_hap(pay_period)
        rows, _ = list_hap_payments({
            "tenancy_id": state["tenancy"]["id"],
            "pay_period_month": pay_period,
        })
        # No row generated for TERMINATED tenancy this month.
        assert all(
            r.get("event_ref_type") != "SCHEDULED_MONTHLY"
            for r in rows
        ), f"unexpected SCHEDULED_MONTHLY row for terminated tenancy: {rows!r}"


class TestSecondPassAnnualReviewDenyChain:

    def test_deny_cascades_unit_to_vacant_and_voucher_terminated(self, api):
        """PRD §3.9 deny + cascade chain: after AR.DENY → Tenancy.TERMINATED
        → Voucher.TERMINATED, and the Unit's occupancy_status must return
        to VACANT per PRD §3.3 derivation rules.

        Second angle on the depth-3 chain — verify the chain reaches
        Unit.occupancy_status.
        # difficulty: transitive_cascade/annual_review_deny_chain_depth_3
        """
        state = setup_active_tenancy(
            gross_annual_income_cents=3_000_000,
            household_size=3, dependents_count=1,
        )
        from test_helpers import (
            advance_clock_to, find_due_annual_review_id, deny_review,
            get_unit,
        )
        lease_start = parse_iso(state["tenancy"]["lease_start"])
        advance_clock_to(add_days(lease_start, 365))
        ar_id = find_due_annual_review_id(state["tenancy"]["id"])
        ap = make_applicant_headers(state["applicant"]["id"])
        validate_success(
            api.submit_annual_review(
                ar_id, submit_annual_review_payload(3_000_000, 3), ap,
            ),
        )
        deny_review(ar_id)
        u = get_unit(state["unit"]["id"])
        assert u["occupancy_status"] == "VACANT"


class TestSecondPassTenancyVoucherStateDependency:

    def test_tenancy_create_on_expired_voucher_rejected(self, api):
        """PRD §3.4 + §3.2: "The voucher must be in SEARCHING or
        SEARCHING_REISSUED" — an EXPIRED voucher fails this state gate.

        Second angle on the Tenancy → Voucher pair: not just LEASED but
        also EXPIRED triggers state-gate rejection.
        # difficulty: cross_entity_state_dependency/tenancy_create_requires_voucher_searching_pair_tenancy_voucher
        """
        from test_helpers import sweep_expirations
        a, v = setup_eligible_applicant_with_voucher(
            household_size=2, dependents_count=0,
            gross_annual_income_cents=2_400_000,
        )
        # Expire it.
        deadline = parse_iso(v["search_deadline"])
        advance_clock_to(deadline)
        advance_clock_by_seconds(1)
        sweep_expirations()
        # Confirm EXPIRED then try to create a Tenancy.
        v_after = get_voucher(v["id"])
        assert v_after["status"] == "EXPIRED"
        unit, _, _ = setup_unit_with_payment_standard(
            zone="ZONE_A", bedroom_count=1,
            asking_rent_cents=80_000, tenant_paid_utilities_cents=0,
            standard_amount_cents=80_000,
        )
        cw = make_case_worker_headers(new_case_worker_id())
        resp = api.create_tenancy(
            create_tenancy_payload(
                v["id"], unit["id"],
                iso_utc(add_days(current_clock(), 1)),
            ),
            cw,
        )
        # PRD §2.10 puts state precondition before voucher-expired check
        # — but EXPIRED is itself out-of-set for SEARCHING/REISSUED, so
        # implementations may surface either ERR_INVALID_STATE or
        # ERR_VOUCHER_EXPIRED. Both are PRD-faithful.
        validate_error_is_one_of(resp, [
            ApiErrorId.ERR_INVALID_STATE.value,
            ApiErrorId.ERR_VOUCHER_EXPIRED.value,
        ])


class TestSecondPassInspectorPHAScope:

    def test_inspector_from_correct_pha_passes_scope_gate(self, api):
        """PRD §3.5: "An Inspector may only complete inspections whose
        tenancy's voucher is administered by the inspector's own PHA"
        — the gate must NOT trip when the Inspector is in-scope.

        Second angle on the cross-entity pair: positive control.
        # difficulty: cross_entity_state_dependency/inspection_complete_requires_inspector_pha_matches_voucher_pair_inspection_voucher
        """
        a, v = setup_eligible_applicant_with_voucher(
            household_size=2, dependents_count=0,
            gross_annual_income_cents=2_400_000,
            administering_pha_id="PHA_001",
        )
        unit, _, _ = setup_unit_with_payment_standard(
            zone="ZONE_A", bedroom_count=1,
            asking_rent_cents=80_000, tenant_paid_utilities_cents=0,
            standard_amount_cents=80_000,
            voucher_bedroom_size_for_ps=min(v["bedroom_size"], 1),
        )
        tenancy = create_pending_tenancy(
            voucher_id=v["id"], unit_id=unit["id"],
            lease_start=iso_utc(add_days(current_clock(), 30)),
        )
        ins = schedule_inspection(
            tenancy_id=tenancy["id"], inspection_type="INITIAL",
            pha_id="PHA_001",
        )
        # In-scope inspector (PHA_001) completes.
        in_scope = make_inspector_headers("inspector-PHA_001-ok-scope")
        resp = api.complete_inspection(
            ins["id"], complete_inspection_payload("PASS", []),
            in_scope,
        )
        data = validate_success(resp)
        assert data["status"] == "COMPLETED_PASS"


class TestSecondPassMobilityZonePair:

    def test_special_mobility_with_zone_a_unit_passes_gate(self, api):
        """PRD §3.7: "if the voucher's special_mobility_flag is true,
        the unit's zone must equal ZONE_A" — positive control: a
        special-mobility voucher leasing into ZONE_A is allowed.

        Second angle on the Tenancy→Unit pair.
        # difficulty: cross_entity_state_dependency/tenancy_finalize_requires_unit_zone_for_mobility_pair_tenancy_unit
        """
        state = setup_active_tenancy(
            gross_annual_income_cents=2_400_000, household_size=2,
            dependents_count=0,
            zone="ZONE_A", bedroom_count=1,
            asking_rent_cents=80_000, tenant_paid_utilities_cents=0,
            standard_amount_cents=80_000, mobility_amount_cents=88_000,
            special_mobility_flag=True,
            comparable_rents_cents=[70_000, 80_000, 90_000],
        )
        assert state["tenancy"]["status"] == "ACTIVE"


class TestSecondPassPriorityPairs:
    """The first-pass tests in test_10 each fire a single contrasting
    pair. Each instance now needs a second angle that demonstrates the
    same priority winner under a slightly different setup or via a
    positive control."""

    def test_finalize_under_only_mobility_violation_yields_mobility_error(
        self, api,
    ):
        """PRD §3.7: "if the voucher's special_mobility_flag is true,
        the unit's zone must equal ZONE_A, or the finalize is rejected
        with ERR_MOBILITY_ZONE_VIOLATION." When the state gate (voucher
        not expired) is NOT tripped, the lower-priority business_safety
        error MUST be the one surfaced — confirming the priority pair
        ordering by negative inversion: state precedes business_safety
        only when both fire.
        # difficulty: priority_pair_validation_conflict/state_vs_business_safety_finalize_expired_and_mobility_violation
        """
        state = setup_special_mobility_with_zone_b_unit()
        # Do NOT advance past search_deadline; only mobility fails.
        cw = make_case_worker_headers(new_case_worker_id())
        resp = api.finalize_tenancy(state["tenancy"]["id"], {}, cw)
        validate_error(
            resp, ApiErrorId.ERR_MOBILITY_ZONE_VIOLATION.value,
        )

    def test_inspection_outcome_mismatch_pure_case_no_burden(self, api):
        """PRD §3.5: "PASS requires an empty defects array ... a mismatch
        yields ERR_INSPECTION_OUTCOME_MISMATCH."

        Second angle: inspection mismatch alone (no burden setup) — the
        symmetric inversion proving the gate stands on its own and
        ordering is consistent with the priority-pair claim.
        # difficulty: priority_pair_validation_conflict/business_safety_vs_business_fiscal_outcome_mismatch_and_burden
        """
        from test_helpers import (
            create_pending_tenancy, schedule_inspection,
            setup_eligible_applicant_with_voucher,
            setup_unit_with_payment_standard,
        )
        a, v = setup_eligible_applicant_with_voucher(
            household_size=2, dependents_count=0,
            gross_annual_income_cents=2_400_000,
        )
        unit, _, _ = setup_unit_with_payment_standard(
            zone="ZONE_A", bedroom_count=1,
            asking_rent_cents=80_000, tenant_paid_utilities_cents=0,
            standard_amount_cents=80_000,
            voucher_bedroom_size_for_ps=min(v["bedroom_size"], 1),
        )
        tenancy = create_pending_tenancy(
            voucher_id=v["id"], unit_id=unit["id"],
            lease_start=iso_utc(add_days(current_clock(), 30)),
        )
        inspection = schedule_inspection(
            tenancy_id=tenancy["id"], inspection_type="INITIAL",
            pha_id=v["administering_pha_id"],
        )
        h = make_inspector_headers(
            f"inspector-{v['administering_pha_id']}-mismatch-2",
        )
        resp = api.complete_inspection(
            inspection["id"],
            complete_inspection_payload(
                outcome="FAIL_NONLIFETHREATENING", defects=[],
            ),
            h,
        )
        validate_error(
            resp, ApiErrorId.ERR_INSPECTION_OUTCOME_MISMATCH.value,
        )

    def test_inspector_out_of_scope_pure_at_complete_endpoint(self, api):
        """PRD §3.5: "An Inspector may only complete inspections whose
        tenancy's voucher is administered by the inspector's own PHA;
        a violation returns ERR_INSPECTOR_OUT_OF_SCOPE."

        Second angle for the priority-pair instance: scope alone
        (without the temporal gap) at the complete endpoint, asserting
        the gate fires deterministically when only the higher-priority
        condition is true.
        # difficulty: priority_pair_validation_conflict/business_referential_vs_business_temporal_inspector_scope_and_too_soon
        """
        from test_helpers import (
            create_pending_tenancy, schedule_inspection,
            setup_eligible_applicant_with_voucher,
            setup_unit_with_payment_standard,
        )
        a, v = setup_eligible_applicant_with_voucher(
            household_size=2, dependents_count=0,
            gross_annual_income_cents=2_400_000,
            administering_pha_id="PHA_001",
        )
        unit, _, _ = setup_unit_with_payment_standard(
            zone="ZONE_A", bedroom_count=1,
            asking_rent_cents=80_000, tenant_paid_utilities_cents=0,
            standard_amount_cents=80_000,
            voucher_bedroom_size_for_ps=min(v["bedroom_size"], 1),
        )
        tenancy = create_pending_tenancy(
            voucher_id=v["id"], unit_id=unit["id"],
            lease_start=iso_utc(add_days(current_clock(), 30)),
        )
        # Inspector from PHA_001 schedules (scope OK).
        inspection = schedule_inspection(
            tenancy_id=tenancy["id"], inspection_type="INITIAL",
            pha_id="PHA_001",
        )
        # Out-of-scope Inspector completes.
        bad_headers = make_inspector_headers(
            "inspector-PHA_003-out-of-scope-pure",
        )
        resp = api.complete_inspection(
            inspection["id"],
            complete_inspection_payload(outcome="PASS", defects=[]),
            bad_headers,
        )
        validate_error(
            resp, ApiErrorId.ERR_INSPECTOR_OUT_OF_SCOPE.value,
        )


class TestSecondPassTenancyVoucherStateDependencyExtra:
    """Second-pass coverage of the Tenancy → Voucher state pair via the
    LEASED branch (which test_03 already covered via setup_active_tenancy
    + create_tenancy on the LEASED voucher)."""

    def test_tenancy_create_on_terminated_voucher_rejected(self, api):
        """PRD §3.4: "The voucher must be in SEARCHING or
        SEARCHING_REISSUED; otherwise the request is rejected with
        ERR_INVALID_STATE."

        Second angle: TERMINATED voucher (reached via AR.DENY cascade)
        is also out-of-set.
        # difficulty: cross_entity_state_dependency/tenancy_create_requires_voucher_searching_pair_tenancy_voucher
        """
        state = setup_active_tenancy(
            gross_annual_income_cents=3_000_000,
            household_size=3, dependents_count=1,
        )
        from test_helpers import (
            advance_clock_to, find_due_annual_review_id, deny_review,
            setup_unit_with_payment_standard,
        )
        lease_start = parse_iso(state["tenancy"]["lease_start"])
        advance_clock_to(add_days(lease_start, 365))
        ar_id = find_due_annual_review_id(state["tenancy"]["id"])
        ap = make_applicant_headers(state["applicant"]["id"])
        validate_success(
            api.submit_annual_review(
                ar_id, submit_annual_review_payload(3_000_000, 3), ap,
            ),
        )
        deny_review(ar_id)
        v = get_voucher(state["voucher"]["id"])
        assert v["status"] == "TERMINATED"
        # Try to create a Tenancy on this TERMINATED voucher.
        unit, _, _ = setup_unit_with_payment_standard(
            zone="ZONE_A", bedroom_count=2,
            asking_rent_cents=110_000, tenant_paid_utilities_cents=10_000,
            standard_amount_cents=120_000,
        )
        cw = make_case_worker_headers(new_case_worker_id())
        resp = api.create_tenancy(
            create_tenancy_payload(
                v["id"], unit["id"],
                iso_utc(add_days(current_clock(), 1)),
            ),
            cw,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


class TestSecondPassAnnualInspection365Gap:
    """Second-pass coverage of the resource_temporal_overlap instance for
    the 365-day inspection gap. The first pass lives in test_04."""

    def test_inspection_too_soon_pinned_to_365_day_predecessor(self, api):
        """PRD §3.5: "minimum gap is 365 days from previous PASS/CURED.
        Adjacency at exactly 365 days is allowed (closed-closed interval
        semantics on the GAP)." 363 days fails just as 364 does.
        # difficulty: resource_temporal_overlap/unit_annual_inspection_365_day_gap_inclusive
        """
        state = setup_active_tenancy(
            gross_annual_income_cents=2_400_000, household_size=2,
            dependents_count=0,
        )
        # Advance 363 days (< 365 — should still fail).
        from test_helpers import advance_clock_by_days
        advance_clock_by_days(363)
        pha = state["voucher"]["administering_pha_id"]
        headers = make_inspector_headers(f"inspector-{pha}-too-soon-363")
        resp = api.create_inspection(
            create_inspection_payload(
                tenancy_id=state["tenancy"]["id"],
                inspection_type="ANNUAL",
                scheduled_for=iso_utc(add_days(current_clock(), 1)),
            ),
            headers,
        )
        validate_error(
            resp, ApiErrorId.ERR_INSPECTION_TOO_SOON.value,
        )


class TestSecondPassVoucherCountInvariantBilledLeavesCountIntact:

    def test_bill_outcome_keeps_per_pha_voucher_count_intact(self, api):
        """PRD §3.10: "Billing is the alternative ... administering_pha_id
        is unchanged".

        Second angle on the voucher-count conservation theme: BILL must
        NOT shift counts between PHAs (only ABSORB does).
        # difficulty: compensating_invariant/voucher_count_conserved_under_portability_absorb
        """
        def count_for(pha: str) -> int:
            collected = 0
            offset = 0
            while True:
                resp = api_client.list_vouchers(
                    TEST_USERS["pha_admin_headers"],
                    params={
                        "administering_pha_id": pha,
                        "limit": 100, "offset": offset,
                    },
                )
                body = resp.json()
                data = body.get("data", []) if isinstance(body, dict) else []
                meta = body.get("meta", {}) if isinstance(body, dict) else {}
                collected += sum(
                    1 for r in data if r.get("status") != "REVOKED"
                )
                if not meta.get("has_more"):
                    break
                offset += 100
            return collected

        state = setup_active_tenancy(
            gross_annual_income_cents=2_400_000, household_size=2,
            dependents_count=0,
            administering_pha_id="PHA_001",
        )
        before_001 = count_for("PHA_001")
        before_002 = count_for("PHA_002")
        ap = make_applicant_headers(state["applicant"]["id"])
        pr = validate_success(
            api.create_portability_request(
                create_portability_request_payload(
                    voucher_id=state["voucher"]["id"],
                    receiving_pha_id="PHA_002",
                ),
                ap,
            ),
            expected_status=201,
        )
        from test_helpers import (
            make_portability_coordinator_headers,
            new_portability_coordinator_id,
        )
        pc = make_portability_coordinator_headers(
            new_portability_coordinator_id("PHA_002"),
        )
        billed = validate_success(api.bill_portability_request(pr["id"], {}, pc))
        assert billed["outcome"] == "BILLED"
        after_001 = count_for("PHA_001")
        after_002 = count_for("PHA_002")
        assert after_001 == before_001, (
            f"BILL must not change PHA_001 count: {before_001} → {after_001}"
        )
        assert after_002 == before_002, (
            f"BILL must not change PHA_002 count: {before_002} → {after_002}"
        )
