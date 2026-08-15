"""Churn economics: the clawback gross/net waterfall, holdback forfeiture,
enrollment exit cascade, exclusivity-breach clawbacks, reinstatement
blocking, and pool conservation across disburse + clawback resolve.
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
    get_coop,
    get_accrual_for_enrollment,
    list_clawbacks_for_member,
    list_holdback_releases_for_member,
    get_single_clawback_for_member,
    churn_member,
    notify_and_resolve_clawback,
    open_accepted_audit,
    resolve_audit,
    setup_disbursed_scenario,
    current_quarter,
)

TIER_TWO_BAND = [{"min_qty": 0, "rate_bps": 200}, {"min_qty": 100, "rate_bps": 500}]


class TestClawbackGrossVsNet:
    def test_churn_clawback_gross_and_net_diverge_by_forfeited_holdback(
        self, api, admin_headers
    ):
        """PRD §3.7: "First, the gross variant: `gross_clawback_cents` is the
        sum of `pass_through_cents` across that set — the full member-facing
        cash the co-op wants back."
        PRD §3.7: "Third, the net variant: `net_clawback_cents` is
        `gross_clawback_cents` minus the forfeited holdback value, floored
        at zero so the demand can never be negative."

        One DISTRIBUTED accrual with pass_through 7500 and one SCHEDULED
        holdback release of 750 (FLAT ten percent of 7500): gross = 7500,
        net = 7500 - 750 = 6750. The two stored variants diverge.

        Design: Difficulty/dual_variant_calc/clawback_gross_vs_net_diverge_on_churn
        """
        scenario = setup_disbursed_scenario(qty=120, cents=200000, tier_schedule=TIER_TWO_BAND)
        churn_member(scenario["member"]["id"])
        case = get_single_clawback_for_member(scenario["member"]["id"])
        assert case["trigger_reason"] == "CHURN"
        assert case["gross_clawback_cents"] == 7500
        assert case["net_clawback_cents"] == 6750
        assert case["gross_clawback_cents"] != case["net_clawback_cents"]

    def test_churn_forfeits_scheduled_holdback_release(self, api, admin_headers):
        """PRD §3.2: "every holdback release still in `SCHEDULED` moves to
        `FORFEITED`, its cash redirected to offset what the member owes; and
        a clawback case with `trigger_reason` of `CHURN` is created
        automatically, its gross and net amounts computed per the clawback
        waterfall in §3.7."
        PRD §3.7: "`recovered_cents` starts at 0".

        Design: Difficulty/dual_variant_calc/clawback_gross_vs_net_diverge_on_churn
        """
        scenario = setup_disbursed_scenario(qty=120, cents=200000, tier_schedule=TIER_TWO_BAND)
        churn_member(scenario["member"]["id"])
        releases = list_holdback_releases_for_member(scenario["member"]["id"])
        assert len(releases) == 1
        assert releases[0]["status"] == "FORFEITED"
        assert releases[0]["release_cents"] == 750
        case = get_single_clawback_for_member(scenario["member"]["id"])
        assert case["status"] == "OPEN"
        assert case["recovered_cents"] == 0
        # net = gross - forfeited holdback value: 7500 - 750 = 6750
        assert case["net_clawback_cents"] == case["gross_clawback_cents"] - 750


class TestClawbackWaterfallOrder:
    def test_waterfall_forfeits_before_netting(self, api, admin_headers):
        """PRD §3.7: "The waterfall works as follows, and its order is
        load-bearing. The compute set is every `RebateAccrual` belonging to
        the member whose status is `DISTRIBUTED`."
        PRD §3.7: "Second, forfeiture: every `HoldbackRelease` of the member
        still in `SCHEDULED` transitions to `FORFEITED` (each incrementing
        its `version`), and their `release_cents` amounts are summed as the
        forfeited holdback value — value the member will never receive and
        which therefore offsets the debt."
        PRD §3.7: "Third, the net variant: `net_clawback_cents` is
        `gross_clawback_cents` minus the forfeited holdback value, floored
        at zero so the demand can never be negative."
        PRD §3.7: "Forfeiture is applied before netting; reversing that
        order produces a different answer precisely when the forfeited
        holdbacks exceed the gross."

        final = floor(100000*500/10000) = 5000 over a single {0,500} tier;
        STANDARD pass = floor(5000*7500/10000) = 3750; FLAT holdback =
        floor(3750*1000/10000) = 375. On churn: gross = 3750, net =
        max(0, 3750 - 375) = 3375.

        Design: Difficulty/combinatorial_formula/clawback_waterfall_order_sensitivity
        """
        scenario = setup_disbursed_scenario(
            qty=50, cents=100000, tier_schedule=[{"min_qty": 0, "rate_bps": 500}],
            program_code="P-WATER",
        )
        churn_member(scenario["member"]["id"])
        case = get_single_clawback_for_member(scenario["member"]["id"])
        assert case["gross_clawback_cents"] == 3750
        assert case["net_clawback_cents"] == 3375

    def test_waterfall_net_is_floored_at_zero_and_never_negative(
        self, api, admin_headers
    ):
        """PRD §3.7: "`net_clawback_cents` is `gross_clawback_cents` minus
        the forfeited holdback value, floored at zero so the demand can
        never be negative."
        PRD §3.7: "The gross figure is what gets reported to the member; the
        net figure is the actual cash demand. `recovered_cents` starts at
        0".

        The net demand equals gross minus the forfeited release (375),
        stays non-negative, and nothing has been recovered at case creation.

        Design: Difficulty/combinatorial_formula/clawback_waterfall_order_sensitivity
        """
        scenario = setup_disbursed_scenario(
            qty=50, cents=100000, tier_schedule=[{"min_qty": 0, "rate_bps": 500}],
            program_code="P-WAT2",
        )
        churn_member(scenario["member"]["id"])
        case = get_single_clawback_for_member(scenario["member"]["id"])
        forfeited = [
            r for r in list_holdback_releases_for_member(scenario["member"]["id"])
            if r["status"] == "FORFEITED"
        ]
        assert len(forfeited) == 1
        assert case["net_clawback_cents"] == max(
            0, case["gross_clawback_cents"] - forfeited[0]["release_cents"]
        )
        assert case["net_clawback_cents"] >= 0
        assert case["recovered_cents"] == 0


class TestChurnCascade:
    def test_churn_exits_enrollments_and_creates_churn_clawback(
        self, api, admin_headers
    ):
        """PRD §3.2: "Whether the member was active or suspended at the
        time, the churn cascade is identical: `churn_quarter_index` records
        the current quarter; every enrollment still in `ACTIVE` or
        `SUSPENDED` status moves to `EXITED` with `exit_quarter_index` set
        to the current quarter; every holdback release still in `SCHEDULED`
        moves to `FORFEITED`, its cash redirected to offset what the member
        owes; and a clawback case with `trigger_reason` of `CHURN` is
        created automatically".

        Hop 1a: the enrollment exits with the current quarter stamped.
        Hop 1b: the CHURN clawback case appears with gross 7500.

        Design: Difficulty/transitive_cascade/churn_cascades_to_clawback_and_holdback_forfeit
        """
        scenario = setup_disbursed_scenario(qty=120, cents=200000, tier_schedule=TIER_TWO_BAND)
        assert current_quarter() == 1
        churned = churn_member(scenario["member"]["id"])
        assert churned["status"] == "CHURNED"
        assert churned["churn_quarter_index"] == 1

        enrollment_after = get_success_data(
            api.get_enrollment(scenario["enrollment"]["id"], admin_headers)
        )
        assert enrollment_after["status"] == "EXITED"
        assert enrollment_after["exit_quarter_index"] == 1

        case = get_single_clawback_for_member(scenario["member"]["id"])
        assert case["trigger_reason"] == "CHURN"
        assert case["gross_clawback_cents"] == 7500

    def test_churn_forfeits_holdback_and_nets_it_against_clawback(
        self, api, admin_headers
    ):
        """PRD §3.2: "every holdback release still in `SCHEDULED` moves to
        `FORFEITED`, its cash redirected to offset what the member owes".
        PRD §3.7: "`net_clawback_cents` is `gross_clawback_cents` minus the
        forfeited holdback value, floored at zero so the demand can never be
        negative."

        Hop 2: the SCHEDULED release of 750 is FORFEITED. Hop 3: the net
        demand is 7500 - 750 = 6750.

        Design: Difficulty/transitive_cascade/churn_cascades_to_clawback_and_holdback_forfeit
        """
        scenario = setup_disbursed_scenario(qty=120, cents=200000, tier_schedule=TIER_TWO_BAND)
        churn_member(scenario["member"]["id"])
        releases = list_holdback_releases_for_member(scenario["member"]["id"])
        assert len(releases) == 1
        assert releases[0]["status"] == "FORFEITED"
        case = get_single_clawback_for_member(scenario["member"]["id"])
        assert case["net_clawback_cents"] == 6750


class TestExclusivityBreachClawback:
    def _shortfall_scenario(self):
        bootstrap_coop()
        member = create_active_member()
        s1 = create_onboarded_supplier("S1")
        s2 = create_onboarded_supplier("S2")
        p1 = create_open_program(
            s1, program_code="P-EXCL", exclusivity_required=True,
            exclusivity_threshold_pct=80,
            tier_schedule=[{"min_qty": 0, "rate_bps": 200}],
        )
        p2 = create_open_program(
            s2, program_code="P-OTHER", exclusivity_required=False,
            exclusivity_threshold_pct=0,
            tier_schedule=[{"min_qty": 0, "rate_bps": 200}],
        )
        e1 = enroll_member(member, p1)
        e2 = enroll_member(member, p2)
        submit_report(e1, member, 0, 100, 100000)
        submit_report(e2, member, 0, 100, 400000)
        return {"member": member, "e1": e1, "e2": e2}

    def test_close_quarter_marks_shortfall_and_opens_exclusivity_clawback(
        self, api, admin_headers
    ):
        """PRD §3.6: "otherwise it is the in-program figure multiplied by
        100 and divided by the total wallet, rounded down to a whole
        percentage point. The derived `exclusivity_status` is
        `NOT_APPLICABLE` when the program's `exclusivity_required` is false;
        otherwise `COMPLIANT` when the share is at least the program's
        `exclusivity_threshold_pct` — the threshold is inclusive, so a share
        exactly equal to the threshold is compliant — and `SHORTFALL` when
        it falls below. When an enrollment's status flips to `SHORTFALL` on
        an exclusivity-requiring program, the system automatically opens a
        clawback case with `trigger_reason` of `EXCLUSIVITY_BREACH`."

        In-program 100000 of a 500000 total wallet -> share 20 < 80 ->
        SHORTFALL; the non-exclusivity enrollment is NOT_APPLICABLE; and the
        breach clawback is auto-created.

        Design: Difficulty/transitive_cascade/quarter_close_cascades_to_exclusivity_breach_clawback
        """
        scenario = self._shortfall_scenario()
        close_quarter()
        e1_after = get_success_data(api.get_enrollment(scenario["e1"]["id"], admin_headers))
        assert e1_after["exclusivity_share_pct"] == 20
        assert e1_after["exclusivity_status"] == "SHORTFALL"
        e2_after = get_success_data(api.get_enrollment(scenario["e2"]["id"], admin_headers))
        assert e2_after["exclusivity_status"] == "NOT_APPLICABLE"

        cases = list_clawbacks_for_member(scenario["member"]["id"])
        assert len(cases) == 1
        assert cases[0]["trigger_reason"] == "EXCLUSIVITY_BREACH"
        assert cases[0]["member_id"] == scenario["member"]["id"]

    def test_exclusivity_breach_clawback_records_trigger_quarter(
        self, api, admin_headers
    ):
        """PRD §3.7: "a quarter close that flips an exclusivity-requiring
        enrollment to `SHORTFALL` opens one with `EXCLUSIVITY_BREACH`. In
        every case the `member_id` is the affected member,
        `trigger_quarter_index` records the quarter of the triggering event".

        The breach case starts OPEN with nothing recovered.

        Note: the case's trigger_quarter_index is intentionally not asserted —
        PRD §3.7 says it "records the quarter of the triggering event" but
        §3.6 advances the quarter counter before the close cascades run, so a
        faithful implementation may stamp either the closing quarter or the
        newly advanced quarter. (Unique-derivability collapse.)

        Design: Difficulty/transitive_cascade/quarter_close_cascades_to_exclusivity_breach_clawback
        """
        scenario = self._shortfall_scenario()
        close_quarter()
        case = get_single_clawback_for_member(scenario["member"]["id"])
        assert case["trigger_reason"] == "EXCLUSIVITY_BREACH"
        assert case["status"] == "OPEN"
        assert case["recovered_cents"] == 0


class TestReinstateBlockedByOpenClawback:
    def test_member_reinstate_blocked_with_open_clawback(self, api, admin_headers):
        """PRD §3.2: "Reinstatement reverses the journey, moving a
        `SUSPENDED` member back to `ACTIVE` and flipping each of its
        `SUSPENDED` enrollments back to `ACTIVE`, but only while the member
        has no clawback case sitting in `OPEN`, `NOTIFIED`, or `DISPUTED` —
        an unresolved clawback blocks reinstatement with `ERR_OPEN_CLAWBACK`
        (HTTP 409)".
        PRD §3.5: "when the finding is `MATERIAL` and the affected accrual
        had already been `DISTRIBUTED`, the system automatically opens a
        clawback case with `trigger_reason` of `AUDIT_SHORTFALL`".

        After disbursement, a MATERIAL audit resolution opens an
        AUDIT_SHORTFALL case; the member is then suspended and reinstatement
        is rejected while the case sits OPEN.

        Design: Corner/state_machines/member_reinstate_blocked_with_open_clawback
        """
        scenario = setup_disbursed_scenario(qty=120, cents=200000, tier_schedule=TIER_TWO_BAND)
        audit = open_accepted_audit(scenario["report"], scenario["member"])
        # |100000 - 200000| / 200000 = 0.5 > 0.05 -> MATERIAL (PRD §3.5)
        resolve_audit(audit, audited_qty=50, audited_cents=100000)
        cases = list_clawbacks_for_member(scenario["member"]["id"])
        assert len(cases) == 1
        assert cases[0]["trigger_reason"] == "AUDIT_SHORTFALL"
        assert cases[0]["status"] == "OPEN"

        get_success_data(api.suspend_member(scenario["member"]["id"], admin_headers))
        resp = api.reinstate_member(scenario["member"]["id"], admin_headers)
        validate_error(resp, ApiErrorId.ERR_OPEN_CLAWBACK)
        member_after = get_success_data(
            api.get_member(scenario["member"]["id"], admin_headers)
        )
        assert member_after["status"] == "SUSPENDED"


class TestClawbackResolutionAndPoolConservation:
    def _disbursed_then_churned_with_resolved_clawback(self):
        scenario = setup_disbursed_scenario(qty=120, cents=200000, tier_schedule=TIER_TWO_BAND)
        churn_member(scenario["member"]["id"])
        case = get_single_clawback_for_member(scenario["member"]["id"])
        resolved = notify_and_resolve_clawback(case["id"])
        scenario["case"] = resolved
        return scenario

    def test_pool_conservation_across_disburse_and_clawback(
        self, api, admin_headers
    ):
        """PRD §2.7: "When a quarterly distribution is disbursed, its
        `net_disbursed_cents` is subtracted from the pool."
        PRD §2.7: "And when a clawback case is resolved, its
        `recovered_cents` is added back into the pool."
        PRD §3.7: "Resolution is available from either `NOTIFIED` or
        `DISPUTED`, and from either source state it behaves identically:
        `recovered_cents` is set to `net_clawback_cents`, the recovered
        amount is added back into `pool_reserve_cents`".

        Pool ledger: +10000 (finalization) - 6750 (disburse) + 6750
        (clawback resolve) = 10000. The retained share booked at
        disbursement (2500) is unaffected by the recovery.

        Design: Difficulty/compensating_invariant/pool_conservation_across_disburse_and_clawback
        """
        scenario = self._disbursed_then_churned_with_resolved_clawback()
        case = scenario["case"]
        assert case["status"] == "RESOLVED"
        assert case["recovered_cents"] == 6750
        coop = get_coop()
        assert coop["pool_reserve_cents"] == 10000, (
            f"pool after +10000 -6750 +6750 must be 10000, got "
            f"{coop['pool_reserve_cents']}"
        )
        assert coop["retained_revenue_cents"] == 2500

    def test_clawback_resolve_claws_back_accrual_and_updates_member_counters(
        self, api, admin_headers
    ):
        """PRD §3.7: "`recovered_cents` is set to `net_clawback_cents`, the
        recovered amount is added back into `pool_reserve_cents`, the
        member's `lifetime_clawback_cents` grows by the recovered amount,
        every accrual in the clawback's compute set transitions from
        `DISTRIBUTED` to `CLAWED_BACK` (each incrementing its `version`),
        and the case lands in the terminal `RESOLVED` state with its own
        `version` incremented."
        PRD §3.2: "`lifetime_pass_through_cents`, the sum of member-facing
        distribution cash paid across all reconciled quarters;
        `lifetime_clawback_cents`, the sum of clawbacks actually recovered
        from the member".

        The member's pass-through credit from disbursement (7500) is not
        undone by the recovery; the recovery is tracked separately.

        Design: Difficulty/compensating_invariant/pool_conservation_across_disburse_and_clawback
        """
        scenario = self._disbursed_then_churned_with_resolved_clawback()
        accrual = get_accrual_for_enrollment(scenario["enrollment"]["id"])
        assert accrual["status"] == "CLAWED_BACK"
        member_after = get_success_data(
            api.get_member(scenario["member"]["id"], admin_headers)
        )
        assert member_after["lifetime_clawback_cents"] == 6750
        assert member_after["lifetime_pass_through_cents"] == 7500

    def test_derived_member_counters_reconcile_with_lifecycle_events(
        self, api, admin_headers
    ):
        """PRD §3.6: "A successful disbursement subtracts
        `net_disbursed_cents` from `pool_reserve_cents`, adds
        `total_retained_cents` to `retained_revenue_cents`, transitions
        every included accrual from `FINALIZED` to `DISTRIBUTED` (each
        accrual's `version` incrementing), and credits each member's
        `lifetime_pass_through_cents` by that member's share."
        PRD §3.7: "the member's `lifetime_clawback_cents` grows by the
        recovered amount".

        After a disbursement of share 7500 followed by a churn clawback
        resolved at the net amount 6750, the member's two lifetime counters
        read exactly those figures.

        Design: Corner/cross_cutting_complexity_layers/derived_field_reconciliation_member_counters
        """
        scenario = self._disbursed_then_churned_with_resolved_clawback()
        member_after = get_success_data(
            api.get_member(scenario["member"]["id"], admin_headers)
        )
        assert member_after["lifetime_pass_through_cents"] == 7500
        assert member_after["lifetime_clawback_cents"] == 6750
        assert member_after["status"] == "CHURNED"
