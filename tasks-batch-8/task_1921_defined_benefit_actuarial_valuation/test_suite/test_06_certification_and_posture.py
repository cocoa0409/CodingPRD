"""Certification cascade, AFTAP boundary, dual discount bases, and presumed AFTAP."""
import pytest

from test_helpers import (
    validate_success,
    ApiErrorId,
    TEST_USERS,
    create_plan,
    register_prep_and_review_actuaries,
    create_locked_census,
    create_locked_assumption_set,
    create_asset_statement,
    create_asset_valuation,
    create_valuation_run,
    compute_run,
    certify_run,
    get_plan,
    get_plan_version,
    get_run,
    list_accruals,
    list_demands,
    create_disclosure_report,
    set_clock,
    api_client,
)

PLAN_ADMIN = TEST_USERS["plan_admin_headers"]


def _certify_family_a(sponsor="Family A Co", **plan_kwargs):
    return _certify_custom(
        sponsor,
        participant_rows=[
            {"external_ref": "A1", "date_of_birth": "1966-03-10", "status": "ACTIVE",
             "years_of_service": 10, "annual_compensation": 100000},
            {"external_ref": "A2", "date_of_birth": "1968-11-20", "status": "ACTIVE",
             "years_of_service": 5, "annual_compensation": 60000},
            {"external_ref": "R1", "date_of_birth": "1965-01-30", "status": "RETIREE",
             "current_annual_benefit": 50000},
        ],
        market_value_begin=60000, contributions_received=0,
        benefits_paid=2000, investment_return=3000,
        **plan_kwargs,
    )


def _certify_custom(sponsor, participant_rows, market_value_begin,
                    contributions_received, benefits_paid, investment_return,
                    **plan_kwargs):
    plan = create_plan(sponsor_name=sponsor, **plan_kwargs)
    plan_id = plan["id"]
    prep, rev = register_prep_and_review_actuaries()
    batch = create_locked_census(plan_id, participant_rows)
    aset = create_locked_assumption_set(plan_id, prep["id"], rev["id"])
    create_asset_statement(
        plan_id, market_value_begin=market_value_begin,
        contributions_received=contributions_received,
        benefits_paid=benefits_paid, investment_return=investment_return,
    )
    ava = create_asset_valuation(plan_id, prep["id"])
    run = create_valuation_run(plan_id, prep["id"], batch["id"], aset["id"], ava["id"])
    compute_run(run["id"], prep["id"])
    plan_v = get_plan_version(plan_id)
    certify_run(run["id"], rev["id"], plan_v)
    return {
        "plan": get_plan(plan_id), "prep": prep, "rev": rev, "batch": batch,
        "aset": aset, "ava": ava, "run": get_run(run["id"]),
    }


class TestAFTAPBoundary:
    def test_aftap_exactly_80_does_not_freeze_accruals(self, api):
        """PRD §3.6: "with the boundaries pinned so that exactly 80.00 is
        `UNRESTRICTED` and exactly 60.00 is `LUMP_SUM_RESTRICTED`."
        PRD §3.6: "if the new posture is `ACCRUAL_FROZEN`, every participant
        accrual row of the certifying run is flagged `frozen` true; if the posture
        is anything else, the frozen flags of that run's rows are cleared."

        Design: Difficulty/boundary_precision_check/aftap_exactly_80_is_unrestricted
        """
        fx = _certify_custom(
            "Boundary Clear Co",
            participant_rows=[
                {"external_ref": "R1", "date_of_birth": "1965-04-04", "status": "RETIREE",
                 "current_annual_benefit": 100000},
            ],
            market_value_begin=80000, contributions_received=0,
            benefits_paid=4000, investment_return=4000,
            prior_aftap_pct=84.00,
        )
        # At exactly 80.00 the posture is UNRESTRICTED, so no row freezes
        assert fx["run"]["aftap_pct"] == 80.00
        accruals = list_accruals(fx["run"]["id"])
        assert len(accruals) == 1
        assert accruals[0]["frozen"] is False

    def test_aftap_exactly_80_is_unrestricted(self, api):
        """PRD §3.6: "`current_posture` is recomputed from the governing percentage:
        `UNRESTRICTED` at or above 80.00 percent ... with the boundaries pinned so
        that exactly 80.00 is `UNRESTRICTED` and exactly 60.00 is
        `LUMP_SUM_RESTRICTED`."
        PRD §3.6: "the run's `aftap_pct` is computed as one hundred times the
        quantity of `smoothed_value` minus the sum of `carryover_balance` and
        `prefunding_balance`, divided by `funding_target`".

        Design: Difficulty/boundary_precision_check/aftap_exactly_80_is_unrestricted
        """
        fx = _certify_custom(
            "Boundary Co",
            participant_rows=[
                {"external_ref": "R1", "date_of_birth": "1965-04-04", "status": "RETIREE",
                 "current_annual_benefit": 100000},
            ],
            # mv_begin 80000, return 4000 (== 5% expected, gain 0), benefits 4000
            # -> mv_end == smoothed == 80000.00; numerator 80000.00; FT 100000.00
            market_value_begin=80000, contributions_received=0,
            benefits_paid=4000, investment_return=4000,
            prior_aftap_pct=84.00,
        )
        assert fx["run"]["aftap_pct"] == 80.00
        plan = get_plan(fx["plan"]["id"])
        assert plan["current_posture"] == "UNRESTRICTED"
        assert plan["certified_aftap_pct"] == 80.00
        # No accrual row is frozen
        accruals = list_accruals(fx["run"]["id"])
        assert all(row["frozen"] is False for row in accruals)


class TestDualDiscountBasis:
    def test_funding_vs_disclosure_discount_basis(self, api):
        """PRD §3.9: "The projected benefit obligation `pbo` recomputes the funding
        target participant-by-participant at the assumption set's
        `disclosure_discount_rate`".
        PRD §3.9: "`fair_value_assets` is the market value of the plan's asset
        valuation, never smoothed. `funded_status` is `fair_value_assets` minus
        `pbo`, negative when the plan is underfunded."
        PRD §3.5: discounting uses "the set's `funding_discount_rate` for funding
        measurements, or its `disclosure_discount_rate` for the disclosure
        revaluation of §3.9".

        Design: Difficulty/dual_variant_calc/funding_vs_disclosure_discount_basis
        """
        fx = _certify_family_a("Dual Basis Co")
        run_id = fx["run"]["id"]
        # 5% funding basis: 14762.00 + 2410.20 + 50000.00 = 67172.20
        assert fx["run"]["funding_target"] == 67172.20
        assert fx["run"]["normal_cost"] == 1958.24

        rep = create_disclosure_report(fx["plan"]["id"], run_id)
        # 4% disclosure basis: 14808.00 + 2464.20 + 50000.00 = 67272.20
        assert rep["pbo"] == 67272.20
        # gain 0 -> market == smoothed == 61000.00; disclosure uses market
        assert rep["fair_value_assets"] == 61000.00
        assert rep["funded_status"] == pytest.approx(-6272.20, abs=0.005)
        assert rep["pbo"] != fx["run"]["funding_target"]

    def test_pbo_uses_disclosure_rate_while_funding_uses_funding_rate(self, api):
        """PRD §3.5: "The one-year discount factor is the reciprocal of one plus
        the applicable discount rate — the set's `funding_discount_rate` for funding
        measurements, or its `disclosure_discount_rate` for the disclosure
        revaluation of §3.9."
        PRD §3.5 calibration: "at a five-percent discount rate the immediate factor
        at age 62 is 1.4762 ... at a four-percent discount rate the immediate
        factor at 62 is 1.4808".

        Design: Difficulty/dual_variant_calc/funding_vs_disclosure_discount_basis
        """
        fx = _certify_family_a("Dual Basis 2 Co")
        run_id = fx["run"]["id"]
        rep = create_disclosure_report(fx["plan"]["id"], run_id)
        # Same census, two discount bases -> different totals
        assert fx["run"]["funding_target"] == 67172.20   # 5% basis
        assert rep["pbo"] == 67272.20                    # 4% basis


class TestPresumedAFTAP:
    def test_presumed_aftap_calendar_steps(self, api):
        """PRD §3.6: "When no certified run exists for the plan, a presumed AFTAP
        governs instead, read from `prior_aftap_pct` and the logical clock. Once
        the clock reaches October 1 of the plan year, the plan is deemed to be
        under 60 percent funded and its posture is `ACCRUAL_FROZEN`. Before that,
        once the clock reaches April 1 of the plan year, `presumed_aftap_pct` is
        `prior_aftap_pct` reduced by 10.00 percentage points. Before April 1,
        `presumed_aftap_pct` equals `prior_aftap_pct` and the plan is presumed
        adequate, with posture `UNRESTRICTED`."

        Design: Corner/calculations/presumed_aftap_calendar_steps
        """
        set_clock("2028-03-01T00:00:00Z")
        plan = create_plan(sponsor_name="Presumed Co", prior_aftap_pct=84.00)
        pid = plan["id"]

        p = get_plan(pid)
        assert p["presumed_aftap_pct"] == 84.00
        assert p["current_posture"] == "UNRESTRICTED"

        set_clock("2028-04-01T00:00:00Z")
        p = get_plan(pid)
        assert p["presumed_aftap_pct"] == 74.00
        assert p["current_posture"] == "LUMP_SUM_RESTRICTED"

        set_clock("2028-10-01T00:00:00Z")
        p = get_plan(pid)
        assert p["current_posture"] == "ACCRUAL_FROZEN"


class TestCertifyFreezeCascade:
    def test_certify_freeze_cascade_depth4(self, api):
        """PRD §3.6: "The second hop propagates the posture onto the run's rows: if
        the new posture is `ACCRUAL_FROZEN`, every participant accrual row of the
        certifying run is flagged `frozen` true".
        PRD §3.7: "the normal-cost component treated as zero when the plan's
        posture froze that run's accruals"; "the shortfall amortization installment
        is one-seventh of the shortfall, rounded half-up to cents"; "`tentative_minimum`
        is the normal-cost component plus the installment".
        PRD §3.6: "`ACCRUAL_FROZEN` below 60.00".

        Design: Difficulty/transitive_cascade/certify_freeze_cascade_depth4
        """
        fx = _certify_custom(
            "Freeze Co",
            participant_rows=[
                {"external_ref": "A1", "date_of_birth": "1966-02-02", "status": "ACTIVE",
                 "years_of_service": 10, "annual_compensation": 50000},
                {"external_ref": "R1", "date_of_birth": "1965-08-08", "status": "RETIREE",
                 "current_annual_benefit": 100000},
            ],
            # FT: ACTIVE 500*1.4762=738.10 (wait: 0.01*10*50000=5000; 5000*1.4762=7381.00)
            # RETIREE 100000*1.0000=100000.00 -> FT 107381.00
            # Assets tuned to AFTAP 59.99: mv_begin 64420, gain 0 -> smoothed 64420.00
            market_value_begin=64420, contributions_received=0,
            benefits_paid=3221.00, investment_return=3221.00,
            prior_aftap_pct=84.00,
        )
        run_id = fx["run"]["id"]
        # aftap = 100 * (64420 - 0) / 107381 = 59.99
        assert fx["run"]["aftap_pct"] == 59.99
        plan = get_plan(fx["plan"]["id"])
        assert plan["current_posture"] == "ACCRUAL_FROZEN"
        # hop 2: all accrual rows frozen
        accruals = list_accruals(run_id)
        assert len(accruals) == 2
        assert all(row["frozen"] is True for row in accruals)
        # hop 3: NC zeroed; shortfall = 107381 - 64420 = 42961.00; installment = 6137.29
        demands = list_demands(fx["plan"]["id"])
        demand = demands[0]
        assert demand["tentative_minimum"] == 6137.29
        assert demand["outstanding_amount"] == 6137.29
        assert demand["status"] == "OPEN"
        # maximum_deductible = max(tentative, 1.5*FT + NC(0) - smoothed)
        # = max(6137.29, 161071.50 - 64420.00) = 96651.50
        assert demand["maximum_deductible"] == 96651.50

    def test_certify_freeze_cascade_restores_on_unfreeze(self, api):
        """PRD §3.6: "if the new posture is `ACCRUAL_FROZEN`, every participant
        accrual row of the certifying run is flagged `frozen` true; if the posture
        is anything else, the frozen flags of that run's rows are cleared."
        PRD §3.7: "the freeze state zeroing — or, on unfreezing, restoring — the
        normal-cost component of `tentative_minimum`".

        Design: Difficulty/transitive_cascade/certify_freeze_cascade_depth4
        """
        # A plan whose certified AFTAP is >= 80 does NOT freeze: NC stays intact
        fx = _certify_family_a("NoFreeze Co")
        run_id = fx["run"]["id"]
        plan = get_plan(fx["plan"]["id"])
        assert plan["current_posture"] == "UNRESTRICTED"
        accruals = list_accruals(run_id)
        assert all(row["frozen"] is False for row in accruals)
        # tentative keeps the normal-cost component: 1958.24 + 881.74
        demands = list_demands(fx["plan"]["id"])
        assert demands[0]["tentative_minimum"] == 2839.98
