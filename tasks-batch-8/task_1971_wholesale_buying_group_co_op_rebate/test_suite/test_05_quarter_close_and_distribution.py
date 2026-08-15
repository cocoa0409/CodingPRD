"""Quarter close, distribution calculation, holdback variants, exclusivity
recomputation, disbursement, and distribution OCC.

Quarter cadence (PRD §3.6): a QuarterlyDistribution "arrives in `DRAFT`
status with `quarter_index` set to the co-op's current quarter", and
calculation "aggregates every `RebateAccrual` in `FINALIZED` status whose
`quarter_index` equals the distribution's quarter" — so each scenario
creates the distribution while its target quarter is still current, then
closes the quarter to finalize that quarter's accruals, then calculates.
"""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    api_client,
    bootstrap_coop,
    create_active_member,
    create_onboarded_supplier,
    create_open_program,
    enroll_member,
    submit_report,
    close_quarter,
    current_quarter,
    get_coop,
    get_accrual_for_enrollment,
    list_clawbacks_for_member,
    list_holdback_releases_for_member,
    create_distribution_for_current_quarter,
    calculate_distribution,
    approve_distribution,
    disburse_distribution,
    setup_member_with_open_program,
    setup_report_with_distribution,
    setup_finalized_accrual_scenario,
    setup_disbursed_scenario,
    drive_member_to_material_findings,
    calculate_distribution_payload,
    assert_split_invariant,
    TIER_SCHEDULE_T1,
)

TIER_TWO_BAND = [{"min_qty": 0, "rate_bps": 200}, {"min_qty": 100, "rate_bps": 500}]


class TestExclusivityThresholdBoundary:
    def _two_supplier_scenario(self, threshold_pct, e1_cents, e2_cents):
        bootstrap_coop()
        member = create_active_member()
        s1 = create_onboarded_supplier("S1")
        s2 = create_onboarded_supplier("S2")
        p1 = create_open_program(
            s1,
            program_code="P-EXCL",
            exclusivity_required=True,
            exclusivity_threshold_pct=threshold_pct,
            tier_schedule=[{"min_qty": 0, "rate_bps": 100}],
        )
        p2 = create_open_program(
            s2,
            program_code="P-OTHER",
            exclusivity_required=False,
            exclusivity_threshold_pct=0,
            tier_schedule=[{"min_qty": 0, "rate_bps": 100}],
        )
        e1 = enroll_member(member, p1)
        e2 = enroll_member(member, p2)
        submit_report(e1, member, 0, 100, e1_cents)
        submit_report(e2, member, 0, 100, e2_cents)
        return {"member": member, "e1": e1, "e2": e2}

    def test_exclusivity_at_exact_threshold_is_compliant(self, api, admin_headers):
        """PRD §3.6: "otherwise `COMPLIANT` when the share is at least the
        program's `exclusivity_threshold_pct` — the threshold is inclusive,
        so a share exactly equal to the threshold is compliant — and
        `SHORTFALL` when it falls below."
        PRD §3.6: "otherwise it is the in-program figure multiplied by 100
        and divided by the total wallet, rounded down to a whole percentage
        point."

        In-program 100000 of a 200000 total wallet -> share 50; threshold 50
        -> COMPLIANT (>= boundary).

        Design: Difficulty/boundary_precision_check/exclusivity_at_exact_threshold_is_compliant
        """
        scenario = self._two_supplier_scenario(50, 100000, 100000)
        close_quarter()
        e1_after = get_success_data(api.get_enrollment(scenario["e1"]["id"], admin_headers))
        assert e1_after["exclusivity_share_pct"] == 50
        assert e1_after["exclusivity_status"] == "COMPLIANT"

    def test_exclusivity_one_point_below_threshold_is_shortfall(
        self, api, admin_headers
    ):
        """PRD §3.6: "and `SHORTFALL` when it falls below. When an
        enrollment's status flips to `SHORTFALL` on an exclusivity-requiring
        program, the system automatically opens a clawback case with
        `trigger_reason` of `EXCLUSIVITY_BREACH`."
        PRD §3.6: "The derived `exclusivity_status` is `NOT_APPLICABLE` when
        the program's `exclusivity_required` is false".

        In-program 100000 of a 204000 total wallet -> floor(100000*100 /
        204000) = 49 < 50 -> SHORTFALL, and a clawback case is auto-opened.

        Design: Difficulty/boundary_precision_check/exclusivity_at_exact_threshold_is_compliant
        """
        scenario = self._two_supplier_scenario(50, 100000, 104000)
        close_quarter()
        e1_after = get_success_data(api.get_enrollment(scenario["e1"]["id"], admin_headers))
        assert e1_after["exclusivity_share_pct"] == 49
        assert e1_after["exclusivity_status"] == "SHORTFALL"
        e2_after = get_success_data(api.get_enrollment(scenario["e2"]["id"], admin_headers))
        assert e2_after["exclusivity_status"] == "NOT_APPLICABLE"
        cases = list_clawbacks_for_member(scenario["member"]["id"])
        assert len(cases) == 1
        assert cases[0]["trigger_reason"] == "EXCLUSIVITY_BREACH"

    def test_exclusivity_zero_total_volume_yields_zero_share(self, api, admin_headers):
        """PRD §3.6: "When the total wallet is zero, `exclusivity_share_pct`
        is 0; otherwise it is the in-program figure multiplied by 100 and
        divided by the total wallet, rounded down to a whole percentage
        point."
        PRD §3.6: "The derived `exclusivity_status` is `NOT_APPLICABLE` when
        the program's `exclusivity_required` is false; otherwise `COMPLIANT`
        when the share is at least the program's `exclusivity_threshold_pct`
        — the threshold is inclusive, so a share exactly equal to the
        threshold is compliant — and `SHORTFALL` when it falls below."

        With no purchase reports in the quarter the denominator is zero:
        share is 0, which falls below a threshold of 1 -> SHORTFALL.

        Design: Corner/calculations/exclusivity_zero_total_volume_yields_zero_share
        """
        bootstrap_coop()
        member = create_active_member()
        supplier = create_onboarded_supplier("S1")
        program = create_open_program(
            supplier,
            program_code="P-EX1",
            exclusivity_required=True,
            exclusivity_threshold_pct=1,
            tier_schedule=[{"min_qty": 0, "rate_bps": 100}],
        )
        enrollment = enroll_member(member, program)
        close_quarter()
        after = get_success_data(api.get_enrollment(enrollment["id"], admin_headers))
        assert after["exclusivity_share_pct"] == 0
        assert after["exclusivity_status"] == "SHORTFALL"


class TestPassThroughSplit:
    def test_pass_through_split_exact_at_builder_rate(self, api, admin_headers):
        """PRD §3.6: "a `BUILDER` member receives 6,500 basis points (65
        percent) with the co-op retaining 3,500 basis points. The member's
        share, `pass_through_cents`, is `final_rebate_cents` multiplied by
        the member's rate and divided by ten thousand, rounded down once to
        a whole cent. The co-op's share, `retained_cents`, is the exact
        complement — `final_rebate_cents` minus `pass_through_cents` — so
        the two shares always sum precisely back to `final_rebate_cents`
        with no cent drift".

        final_rebate = floor(200000 * 500 / 10000) = 10000 over a single
        {0,500} tier; BUILDER pass-through = floor(10000 * 6500 / 10000) =
        6500; retained = 3500.

        Design: Corner/calculations/pass_through_split_exact_at_builder_rate
        """
        scenario = setup_finalized_accrual_scenario(
            qty=100,
            cents=200000,
            commitment_level="BUILDER",
            tier_schedule=[{"min_qty": 0, "rate_bps": 500}],
            program_code="P-BLD",
        )
        accrual = get_accrual_for_enrollment(scenario["enrollment"]["id"])
        assert accrual["status"] == "FINALIZED"
        assert accrual["final_rebate_cents"] == 10000
        assert accrual["pass_through_cents"] == 6500
        assert accrual["retained_cents"] == 3500
        assert_split_invariant(accrual)


class TestImmediateConsistency:
    def test_accrual_visible_as_finalized_immediately_after_close(
        self, api, admin_headers
    ):
        """PRD §3.6: "Every `RebateAccrual` still in `OPEN` status whose
        `quarter_index` matches the closing quarter is examined, and each is
        finalized — but only if every purchase report for that enrollment
        and quarter rests in `ADJUDICATED` or `SUBMITTED`; a report still
        `FLAGGED` holds its accrual open."
        PRD §3.6: "The accrual moves from `OPEN` to `FINALIZED`, its
        `version` increments, and the co-op's `pool_reserve_cents` grows by
        the accrual's `final_rebate_cents`, booking the supplier's rebate
        obligation into escrow."

        A read issued immediately after close_quarter returns shows the
        accrual FINALIZED with the computed final amount — no lag.

        Design: Corner/consistency_model/immediate_consistency_accrual_visible_after_finalize
        """
        scenario = setup_report_with_distribution(
            qty=100,
            cents=200000,
            tier_schedule=[{"min_qty": 0, "rate_bps": 500}],
            program_code="P-IMM",
        )
        validate_success(api.close_quarter(admin_headers), 200)
        accrual = get_accrual_for_enrollment(scenario["enrollment"]["id"])
        assert accrual["status"] == "FINALIZED"
        assert accrual["final_rebate_cents"] == 10000
        assert accrual["pass_through_cents"] == 7500
        assert accrual["retained_cents"] == 2500
        coop = get_coop()
        assert coop["pool_reserve_cents"] == 10000


class TestDisbursement:
    def test_disburse_succeeds_when_pool_covers_net_disbursed(
        self, api, admin_headers
    ):
        """PRD §3.6: "Disbursement moves an `APPROVED` distribution to
        `DISBURSED`, but only if the pool can cover it: when
        `pool_reserve_cents` falls short of `net_disbursed_cents`,
        disbursement is refused with `ERR_INSUFFICIENT_POOL` (HTTP 409) and
        nothing moves. A successful disbursement subtracts
        `net_disbursed_cents` from `pool_reserve_cents`".

        final 10000 (floor(200000*500/10000), qty 120 over tiers
        [{0,200},{100,500}]) -> pass 7500, holdback 750 (FLAT ten percent),
        net 6750. The pool holds 10000 from finalization, covering 6750;
        after disbursement the pool stands at 3250.

        Design: Difficulty/resource_temporal_overlap/disburse_blocked_when_pool_insufficient
        """
        scenario = setup_disbursed_scenario(qty=120, cents=200000, tier_schedule=TIER_TWO_BAND)
        distribution = scenario["distribution"]
        assert distribution["status"] == "DISBURSED"
        assert distribution["net_disbursed_cents"] == 6750
        coop = get_coop()
        assert coop["pool_reserve_cents"] == 10000 - 6750 == 3250

    def test_disburse_moves_money_to_pool_retained_member_and_accrual(
        self, api, admin_headers
    ):
        """PRD §3.6: "A successful disbursement subtracts
        `net_disbursed_cents` from `pool_reserve_cents`, adds
        `total_retained_cents` to `retained_revenue_cents`, transitions every
        included accrual from `FINALIZED` to `DISTRIBUTED` (each accrual's
        `version` incrementing), and credits each member's
        `lifetime_pass_through_cents` by that member's share."
        PRD §2.7: "This counter starts at 0 and grows by a distribution's
        `total_retained_cents` at the moment that distribution is disbursed."

        Design: Difficulty/resource_temporal_overlap/disburse_blocked_when_pool_insufficient
        """
        scenario = setup_disbursed_scenario(qty=120, cents=200000, tier_schedule=TIER_TWO_BAND)
        assert scenario["accrual"]["status"] == "DISTRIBUTED"
        assert scenario["member"]["lifetime_pass_through_cents"] == 7500
        coop = get_coop()
        assert coop["retained_revenue_cents"] == 2500
        assert scenario["distribution"]["total_pass_through_cents"] == 7500
        assert scenario["distribution"]["total_retained_cents"] == 2500
        assert scenario["distribution"]["holdback_cents"] == 750

    def test_disburse_schedules_holdback_release_with_withheld_amount(
        self, api, admin_headers, finance_headers
    ):
        """PRD §3.6: "For every included accrual whose program's holdback
        policy caused an amount to be withheld, the disbursement also
        schedules a `HoldbackRelease`: it is created in `SCHEDULED` status
        against the member, its `source_distribution_id` pointing at the
        distribution just disbursed, its `release_cents` carrying the
        withheld cash amount destined for that member".
        PRD §3.6: "Under the `FLAT` variant, `holdback_cents` is a single
        withholding: `total_pass_through_cents` multiplied by 1,000 basis
        points — ten percent — and divided by ten thousand, rounded down to
        a whole cent."

        final 5000 (floor(100000*500/10000)) -> pass 3750 -> holdback
        floor(3750*1000/10000) = 375.

        Design: Corner/state_machines/distribution_disburse_from_approved_requires_pool
        """
        scenario = setup_disbursed_scenario(
            qty=50,
            cents=100000,
            tier_schedule=[{"min_qty": 0, "rate_bps": 500}],
            program_code="P-DISB",
        )
        assert scenario["distribution"]["status"] == "DISBURSED"
        releases = list_holdback_releases_for_member(scenario["member"]["id"])
        assert len(releases) == 1
        release = releases[0]
        assert release["status"] == "SCHEDULED"
        assert release["release_cents"] == 375
        assert release["member_id"] == scenario["member"]["id"]
        assert release["source_distribution_id"] == scenario["distribution"]["id"]


class TestHoldbackVariants:
    def _flat_vs_risk_scenario(self, api):
        """Two suppliers' programs, one FLAT and one RISK_ADJUSTED; M2 is
        driven to exactly 2 prior MATERIAL findings (the inclusive threshold)
        across quarters 0 and 1; in quarter 2 three accruals of
        final 10000 / pass 7500 / retained 2500 each are finalized and
        calculated into a single distribution."""
        bootstrap_coop()
        m1 = create_active_member("Member One", "STANDARD")
        m2 = create_active_member("Member Two", "STANDARD")
        supplier = create_onboarded_supplier("Supplier S")
        p1 = create_open_program(
            supplier, program_code="P-FLAT", holdback_policy="FLAT",
            tier_schedule=TIER_SCHEDULE_T1,
        )
        p2 = create_open_program(
            supplier, program_code="P-RISK", holdback_policy="RISK_ADJUSTED",
            tier_schedule=TIER_SCHEDULE_T1,
        )
        e1a = enroll_member(m1, p1)
        e1b = enroll_member(m1, p2)
        e2 = enroll_member(m2, p2)
        # Drive M2's prior_audit_findings_count to exactly 2 (quarters 0, 1).
        m2 = drive_member_to_material_findings(m2, p2, e2, target_count=2)
        assert current_quarter() == 2
        # Quarter 2 reports -> three accruals.
        submit_report(e1a, m1, 2, 120, 200000)
        submit_report(e1b, m1, 2, 120, 200000)
        submit_report(e2, m2, 2, 120, 200000)
        distribution = create_distribution_for_current_quarter()
        close_quarter()
        distribution = calculate_distribution(distribution)
        return {
            "m1": m1, "m2": m2, "distribution": distribution,
            "e1a": e1a, "e1b": e1b, "e2": e2,
        }

    def test_holdback_flat_and_risk_adjusted_variants_compose(
        self, api, admin_headers
    ):
        """PRD §3.6: "Under the `FLAT` variant, `holdback_cents` is a single
        withholding: `total_pass_through_cents` multiplied by 1,000 basis
        points — ten percent — and divided by ten thousand, rounded down to
        a whole cent. Under the `RISK_ADJUSTED` variant, the withholding is
        computed per contributing member: for each member, the member's
        pass-through contribution is multiplied by 2,500 basis points when
        that member's `prior_audit_findings_count` is at least 2, and by
        1,000 basis points otherwise — the threshold is inclusive, so
        exactly two prior material findings triggers the elevated rate".

        FLAT program (M1 only): floor(7500 * 1000 / 10000) = 750.
        RISK program: M1 (0 findings) floor(7500 * 1000 / 10000) = 750;
        M2 (exactly 2 findings) floor(7500 * 2500 / 10000) = 1875.
        Total holdback = 750 + 750 + 1875 = 3375 — the two variants diverge.

        Design: Difficulty/dual_variant_calc/holdback_flat_vs_risk_adjusted_diverge_on_findings
        """
        scenario = self._flat_vs_risk_scenario(api)
        distribution = scenario["distribution"]
        assert distribution["total_pass_through_cents"] == 22500  # 3 x 7500
        assert distribution["gross_rebate_cents"] == 30000        # 3 x 10000
        assert distribution["total_retained_cents"] == 7500       # 3 x 2500
        assert distribution["holdback_cents"] == 3375, (
            f"per-variant composition: expected 3375, got "
            f"{distribution['holdback_cents']}"
        )
        # The variants diverge: a hypothetical all-FLAT withholding would be
        # floor(22500 * 1000 / 10000) = 2250.
        assert distribution["holdback_cents"] != 2250

    def test_risk_adjusted_rate_applies_at_exactly_two_findings(
        self, api, admin_headers
    ):
        """PRD §3.6: "the member's pass-through contribution is multiplied
        by 2,500 basis points when that member's `prior_audit_findings_count`
        is at least 2, and by 1,000 basis points otherwise — the threshold
        is inclusive, so exactly two prior material findings triggers the
        elevated rate — each per-member product is divided by ten thousand
        and rounded down to a whole cent, and `holdback_cents` is the sum of
        those per-member withholdings."
        PRD §3.6: "`net_disbursed_cents` is what remains:
        `total_pass_through_cents` minus `holdback_cents` minus
        `clawback_offset_cents`."

        M2 sits at exactly the inclusive threshold of 2, so M2's share is
        withheld at 2500 bps; with no open or notified clawbacks the offset
        is 0 and net = 22500 - 3375 = 19125.

        Design: Difficulty/dual_variant_calc/holdback_flat_vs_risk_adjusted_diverge_on_findings
        """
        scenario = self._flat_vs_risk_scenario(api)
        m2_after = get_success_data(api.get_member(scenario["m2"]["id"], admin_headers))
        assert m2_after["prior_audit_findings_count"] == 2
        distribution = scenario["distribution"]
        assert distribution["clawback_offset_cents"] == 0
        assert distribution["net_disbursed_cents"] == 22500 - 3375 == 19125


class TestHoldbackPerMemberRounding:
    def _three_member_risk_scenario(self, api):
        """Three STANDARD members in one RISK_ADJUSTED program; each accrual
        finalizes to 4444 -> pass floor(4444 * 7500 / 10000) = 3333. All
        members have 0 prior findings, so each per-member withholding is
        floor(3333 * 1000 / 10000) = 333 and the distribution holdback is
        the sum 999."""
        bootstrap_coop()
        supplier = create_onboarded_supplier("S")
        program = create_open_program(
            supplier,
            program_code="P-ROUND",
            holdback_policy="RISK_ADJUSTED",
            tier_schedule=[{"min_qty": 0, "rate_bps": 4444}],
        )
        members = []
        for name in ("M1", "M2", "M3"):
            member = create_active_member(name, "STANDARD")
            enrollment = enroll_member(member, program)
            submit_report(enrollment, member, 0, 10, 10000)
            members.append(member)
        distribution = create_distribution_for_current_quarter()
        close_quarter()
        distribution = calculate_distribution(distribution)
        return {"members": members, "distribution": distribution}

    def test_holdback_rounds_per_member_then_sums(self, api, admin_headers):
        """PRD §3.6: "Under the `RISK_ADJUSTED` variant, the withholding is
        computed per contributing member: for each member, the member's
        pass-through contribution is multiplied by 2,500 basis points when
        that member's `prior_audit_findings_count` is at least 2, and by
        1,000 basis points otherwise — the threshold is inclusive, so
        exactly two prior material findings triggers the elevated rate —
        each per-member product is divided by ten thousand and rounded down
        to a whole cent, and `holdback_cents` is the sum of those per-member
        withholdings."

        Per-member floor: floor(3333 * 1000 / 10000) = 333 per member, and
        333 + 333 + 333 = 999 — each member contributes a whole-cent
        withholding with no fractional accumulation.

        Design: Difficulty/combinatorial_formula/holdback_per_member_rounding_vs_aggregate
        """
        scenario = self._three_member_risk_scenario(api)
        distribution = scenario["distribution"]
        assert distribution["total_pass_through_cents"] == 9999  # 3 x 3333
        assert distribution["holdback_cents"] == 999, (
            f"sum of per-member floors (3 x 333): expected 999, got "
            f"{distribution['holdback_cents']}"
        )

    def test_risk_rate_stays_flat_for_members_below_findings_threshold(
        self, api, admin_headers
    ):
        """PRD §3.6: "for each member, the member's pass-through
        contribution is multiplied by 2,500 basis points when that member's
        `prior_audit_findings_count` is at least 2, and by 1,000 basis
        points otherwise".
        PRD §3.6: "`net_disbursed_cents` is what remains:
        `total_pass_through_cents` minus `holdback_cents` minus
        `clawback_offset_cents`."

        All three members sit below the inclusive threshold of 2, so every
        contribution is withheld at 1,000 bps and net = 9999 - 999 = 9000.

        Design: Difficulty/combinatorial_formula/holdback_per_member_rounding_vs_aggregate
        """
        scenario = self._three_member_risk_scenario(api)
        for member in scenario["members"]:
            after = get_success_data(api.get_member(member["id"], admin_headers))
            assert after["prior_audit_findings_count"] == 0
        distribution = scenario["distribution"]
        assert distribution["gross_rebate_cents"] == 13332  # 3 x 4444
        assert distribution["net_disbursed_cents"] == 9999 - 999 == 9000


class TestDistributionCalculateOcc:
    def test_distribution_calculate_with_future_expected_version_rejected(
        self, api, admin_headers, finance_headers
    ):
        """PRD §2.9: "21. **Distribution recalculation freshness.**
        `expected_distribution_version` must equal the distribution's
        current `version`. Applies to distribution calculation only.
        Failure: `ERR_STALE_DISTRIBUTION_VERSION` (HTTP 412)."
        PRD §2.8: "the recalculation is rejected with
        `ERR_STALE_DISTRIBUTION_VERSION` (HTTP 412), and nothing is written."

        An expected version far above the distribution's current version
        cannot equal it, so the calculation is rejected and the distribution
        stays DRAFT.

        Design: Corner/endpoints/distribution_calculate_stale_version_rejected
        """
        bootstrap_coop()
        distribution = create_distribution_for_current_quarter()
        observed = distribution["version"]
        resp = api.calculate_distribution(
            distribution["id"],
            calculate_distribution_payload(observed + 999),
            finance_headers,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_DISTRIBUTION_VERSION)
        after = get_success_data(api.get_distribution(distribution["id"], finance_headers))
        assert after["status"] == "DRAFT"
        assert after["version"] == observed

    def test_distribution_calculate_with_previous_version_rejected(
        self, api, admin_headers, finance_headers
    ):
        """PRD §2.8: "Recalculating a quarterly distribution — the `POST
        /coop/distributions/{id}/calculate` operation — likewise requires
        `expected_distribution_version`, holding the client's last observed
        `version` of the `QuarterlyDistribution`. If the distribution's
        version has advanced since that observation — for instance because a
        prior calculation already ran — the recalculation is rejected with
        `ERR_STALE_DISTRIBUTION_VERSION` (HTTP 412), and nothing is
        written."

        An expected version one below the current version is deterministically
        stale (the version only ever increments), so the calculation is
        rejected and the distribution stays DRAFT.

        Design: Corner/endpoints/distribution_calculate_deliberate_stale_version
        """
        bootstrap_coop()
        distribution = create_distribution_for_current_quarter()
        observed = distribution["version"]
        resp = api.calculate_distribution(
            distribution["id"],
            calculate_distribution_payload(observed - 1),
            finance_headers,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_DISTRIBUTION_VERSION)
        after = get_success_data(api.get_distribution(distribution["id"], finance_headers))
        assert after["status"] == "DRAFT"
        assert after["version"] == observed
