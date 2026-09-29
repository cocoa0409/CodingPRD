"""Calculation breadth: cohort factors, funded status, the accrual cap, tranche
aggregation and the lump-sum cap waterfall.

Every figure asserted here is re-derived with the pure-Python mirrors of the
PRD's formulas in `test_helpers.constants` rather than hardcoded, so a divergence
points at the implementation and not at a stale literal in the test.
"""

from prd_bench_local_runner.testing import validate_paginated

from test_helpers import administrator_headers, constants, fixtures
from test_helpers.types import (
    AddressStatus,
    BenefitAuditStatus,
    Cohort,
    DataReadinessFlag,
    DataStatus,
    ElectionStatus,
    MortalityStatus,
    ParticipantAuditStatus,
    ParticipantStatus,
    StrategyType,
    TrancheStatus,
    WindowStatus,
)


RETIREE = Cohort.RETIREE_IN_PAY.value
DEFERRED = Cohort.DEFERRED_VESTED.value


class TestCohortLiabilityFactors:
    """Both liability bases key on cohort and both round half up."""

    def test_calc_cohort_factors_round_half_up_on_both_bases(self, api):
        """A retiree whose settlement quotient is an exact half rounds up on both bases.

        Otherwise the effective monthly amount is multiplied by twelve, the annual amount is multiplied by the factor for the participant's `cohort`, and the product is rounded half up over 10,000.
        For `accounting_liability_cents` the factor is 118,000 basis points for `RETIREE_IN_PAY` and 95,500 for `DEFERRED_VESTED`; for `settlement_liability_cents` it is 126,250 for `RETIREE_IN_PAY` and 104,500 for `DEFERRED_VESTED`.
        Wherever this document says an amount is rounded, the method is **round half up on the magnitude**: an exact half rounds away from zero, never toward it.

        Design: Corner/calculations/cohort_factors_diverge_and_half_up_rounding_is_observable
        """
        fixtures.reset_clock(api)
        plan = fixtures.create_plan(api)

        retiree = fixtures.create_participant(
            api,
            plan["id"],
            participant_reference="AC-RET",
            cohort=RETIREE,
            stated_monthly_benefit_cents=250001,
            final_average_monthly_earnings_cents=500000,
            credited_service_months=400,
            date_of_birth="1956-06-06",
        )
        deferred = fixtures.create_participant(
            api,
            plan["id"],
            participant_reference="AC-DEF",
            cohort=DEFERRED,
            stated_monthly_benefit_cents=100000,
            final_average_monthly_earnings_cents=250000,
            credited_service_months=320,
            date_of_birth="1968-04-04",
        )

        # 3000012 * 118000 / 10000 has a .6 quotient; * 126250 / 10000 is exactly .5.
        assert retiree["accounting_liability_cents"] == constants.accounting_liability(
            250001, RETIREE
        )
        assert retiree["accounting_liability_cents"] == 35400142
        assert retiree["settlement_liability_cents"] == constants.settlement_liability(
            250001, RETIREE
        )
        assert retiree["settlement_liability_cents"] == 37875152

        # The deferred-vested factors divide exactly.
        assert deferred["accounting_liability_cents"] == constants.accounting_liability(
            100000, DEFERRED
        )
        assert deferred["accounting_liability_cents"] == 11460000
        assert deferred["settlement_liability_cents"] == constants.settlement_liability(
            100000, DEFERRED
        )
        assert deferred["settlement_liability_cents"] == 12540000

        for participant in (retiree, deferred):
            assert (
                participant["settlement_liability_cents"]
                > participant["accounting_liability_cents"]
            )

    def test_calc_confirmed_death_zeroes_only_that_participant(self, api):
        """Confirming a death zeroes that record's two liabilities and leaves its peer alone.

        If the participant's `mortality_status` is `DECEASED_CONFIRMED`, both liability figures are 0 and no further arithmetic runs.
        A `DEATH_MATCH` is the heaviest of these operations. It is accepted from `UNVERIFIED`, from `ALIVE_CONFIRMED`, or from `DEATH_DISPUTED`, and in every case lands the participant in `DECEASED_CONFIRMED` with an identical set of consequences.

        Design: Corner/calculations/cohort_factors_diverge_and_half_up_rounding_is_observable
        """
        fixtures.reset_clock(api)
        plan = fixtures.create_plan(api)

        retiree = fixtures.create_participant(
            api,
            plan["id"],
            participant_reference="AC-RET",
            cohort=RETIREE,
            stated_monthly_benefit_cents=250001,
            final_average_monthly_earnings_cents=500000,
            credited_service_months=400,
            date_of_birth="1956-06-06",
        )
        deferred = fixtures.create_participant(
            api,
            plan["id"],
            participant_reference="AC-DEF",
            cohort=DEFERRED,
            stated_monthly_benefit_cents=100000,
            final_average_monthly_earnings_cents=250000,
            credited_service_months=320,
            date_of_birth="1968-04-04",
        )

        fixtures.record_mortality(
            api, retiree["id"], "DEATH_MATCH", date_of_death="2026-07-15"
        )

        deceased = fixtures.read_participant(api, retiree["id"])
        assert deceased["mortality_status"] == MortalityStatus.DECEASED_CONFIRMED.value
        assert deceased["accounting_liability_cents"] == 0
        assert deceased["settlement_liability_cents"] == 0

        survivor = fixtures.read_participant(api, deferred["id"])
        assert survivor["mortality_status"] == MortalityStatus.UNVERIFIED.value
        assert survivor["accounting_liability_cents"] == constants.accounting_liability(
            100000, DEFERRED
        )
        assert survivor["settlement_liability_cents"] == constants.settlement_liability(
            100000, DEFERRED
        )


class TestFundedStatusRead:
    """The funded-status read carries both measurement bases and re-derives on demand."""

    def test_calc_funded_status_read_reports_both_bases(self, api):
        """Assets of 20,000,000 against a liability of 30,000,000 report 6667 and 6231 basis points.

        Its accounting figure, `accounting_funded_status_bp`, is 0 whenever `total_liability_cents` is 0; otherwise it is `plan_assets_cents` multiplied by 10,000 and rounded half up over `total_liability_cents`, so a fully funded plan reads 10000 basis points.
        Alongside it the system computes a settlement-basis view: `settlement_basis_liability_cents` is `total_liability_cents` multiplied by 10,700 basis points and rounded half up over 10,000 — that is, the accounting obligation uplifted by seven percent to reflect what a carrier would charge to take it on — and `settlement_funded_status_bp` is 0 when that uplifted liability is 0 and otherwise `plan_assets_cents` multiplied by 10,000 and rounded half up over `settlement_basis_liability_cents`.
        Finally `participant_liability_total_cents` is the sum of `accounting_liability_cents` across the plan's participant records whose `participant_status` is `IN_PLAN` or `ASSIGNED`, and is 0 when no participant qualifies.
        A funded-status read returns all of these together with the plan's `cumulative_settlement_charge_cents` and `deferred_settlement_charge_cents`, computes them fresh, and persists nothing.

        Design: Corner/calculations/funded_status_read_reports_both_bases_and_re_derives_after_a_valuation
        """
        fixtures.reset_clock(api)
        plan = fixtures.create_plan(
            api, total_liability_cents=30000000, plan_assets_cents=20000000
        )
        fixtures.create_participant(
            api,
            plan["id"],
            participant_reference="AC-0070",
            cohort=DEFERRED,
            stated_monthly_benefit_cents=100000,
            final_average_monthly_earnings_cents=250000,
            credited_service_months=320,
            date_of_birth="1968-04-04",
        )

        view = fixtures.read_funded_status(api, plan["id"])

        assert view["accounting_funded_status_bp"] == constants.funded_status_bp(
            20000000, 30000000
        )
        assert view["accounting_funded_status_bp"] == 6667
        assert view["settlement_basis_liability_cents"] == constants.settlement_basis_liability(
            30000000
        )
        assert view["settlement_basis_liability_cents"] == 32100000
        assert view["settlement_funded_status_bp"] == constants.settlement_funded_status_bp(
            20000000, 30000000
        )
        assert view["settlement_funded_status_bp"] == 6231
        assert view["unfunded_settlement_gap_cents"] == constants.unfunded_settlement_gap_cents(
            20000000, 30000000
        )
        assert view["unfunded_settlement_gap_cents"] == 12100000
        assert view["participant_liability_total_cents"] == constants.accounting_liability(
            100000, DEFERRED
        )
        assert view["cumulative_settlement_charge_cents"] == 0
        assert view["deferred_settlement_charge_cents"] == 0

    def test_calc_funded_status_re_derives_after_a_valuation_update(self, api):
        """Lifting assets to 33,000,000 re-derives both bases and floors the gap at zero.

        Recording a later actuarial valuation overwrites the same six input figures — `total_liability_cents`, `plan_assets_cents`, `service_cost_cents`, `interest_cost_cents`, `unrecognized_actuarial_loss_cents`, and `discount_rate_bps` — and re-derives funded status.
        The `unfunded_settlement_gap_cents` is the amount by which `settlement_basis_liability_cents` exceeds `plan_assets_cents`, or 0 when assets already reach or exceed the uplifted liability.

        Design: Corner/calculations/funded_status_read_reports_both_bases_and_re_derives_after_a_valuation
        """
        fixtures.reset_clock(api)
        plan = fixtures.create_plan(
            api, total_liability_cents=30000000, plan_assets_cents=20000000
        )

        before = fixtures.read_plan(api, plan["id"])
        updated = fixtures.update_valuation(api, plan["id"], plan_assets_cents=33000000)
        assert updated["version"] == before["version"] + 1

        view = fixtures.read_funded_status(api, plan["id"])
        assert view["accounting_funded_status_bp"] == constants.funded_status_bp(
            33000000, 30000000
        )
        assert view["accounting_funded_status_bp"] == 11000
        assert view["settlement_funded_status_bp"] == constants.settlement_funded_status_bp(
            33000000, 30000000
        )
        assert view["settlement_funded_status_bp"] == 10280
        assert view["unfunded_settlement_gap_cents"] == 0


class TestBenefitRecomputationCap:
    """The accrual formula is flat above 420 credited months."""

    def test_calc_benefit_recomputation_caps_service_at_420_months(self, api):
        """480 credited months recompute against 420, matching a stated benefit of 52,500.

        **The recomputation** first caps service: the `credited_service_months` are capped at 420 months — thirty-five years, the plan's maximum credited service — before any multiplication happens.
        The `recomputed_monthly_benefit_cents` is then the `final_average_monthly_earnings_cents` multiplied by an accrual rate of 150 basis points and by the capped service months, with that product rounded half up over 120,000 — the divisor being 10,000 basis points times the twelve months of a year, because the accrual rate is expressed per year of service while the result is a monthly benefit.
        Accepting a `PASSED` audit as it stands moves it `PASSED → PASSED_CLOSED`: the participant's `audited_monthly_benefit_cents` is set to the audit's `stated_monthly_benefit_cents`, the participant's `benefit_audit_status` becomes `PASSED_CLOSED`, and the participant's `accounting_liability_cents`, `settlement_liability_cents`, `data_confidence_score`, and `data_status` are all recomputed before the audit's `version` is bumped.

        Design: Corner/calculations/benefit_recomputation_caps_credited_service_at_420_months
        """
        fixtures.reset_clock(api)
        plan = fixtures.create_plan(api)
        participant = fixtures.create_participant(
            api,
            plan["id"],
            participant_reference="AC-LONG",
            cohort=DEFERRED,
            stated_monthly_benefit_cents=52500,
            final_average_monthly_earnings_cents=100000,
            credited_service_months=480,
            date_of_birth="1958-09-09",
        )

        audit = fixtures.open_benefit_audit(api, participant["id"])

        expected = constants.recomputed_monthly_benefit(100000, 480)
        assert expected == 52500
        assert audit["recomputed_monthly_benefit_cents"] == expected
        assert audit["variance_cents"] == 0
        assert audit["audit_status"] == BenefitAuditStatus.PASSED.value
        assert audit["audit_sequence"] == 1

        fixtures.resolve_audit(api, audit["id"], "ACCEPT_AS_IS")

        closed = fixtures.read_participant(api, participant["id"])
        assert closed["audited_monthly_benefit_cents"] == 52500
        assert closed["benefit_audit_status"] == ParticipantAuditStatus.PASSED_CLOSED.value
        assert closed["accounting_liability_cents"] == constants.accounting_liability(
            52500, DEFERRED
        )
        assert closed["accounting_liability_cents"] == 6016500

    def test_calc_second_audit_above_the_cap_recomputes_the_same_benefit(self, api):
        """A revised 600 months yields the identical 52,500 and supersedes the first audit.

        The audit request carries `expected_participant_version` under the stale-version rule of §2.9, an optional `audit_basis` of `PLAN_DOCUMENT`, `COLLECTIVE_AGREEMENT`, or `PRIOR_ADMINISTRATOR_FILE` (defaulting to `PLAN_DOCUMENT` when omitted, and naming the source document the recomputation was performed against), and optionally revised `final_average_monthly_earnings_cents` and `credited_service_months` figures to recompute from.
        **The recomputation** first caps service: the `credited_service_months` are capped at 420 months — thirty-five years, the plan's maximum credited service — before any multiplication happens.
        Before the new audit exists, every non-superseded audit of that participant transitions to `SUPERSEDED`, each bumping its own `version`; this create-with-supersede pattern is exactly what the stale-participant guard protects.
        The new audit is assigned an `audit_sequence` equal to the participant's prior audit count plus one, a 1-based ordinal that serves as the deterministic tie-break whenever "the latest audit" must be identified, and it snapshots the participant's `stated_monthly_benefit_cents` as it stood at audit creation.

        Design: Corner/calculations/benefit_recomputation_caps_credited_service_at_420_months
        """
        fixtures.reset_clock(api)
        plan = fixtures.create_plan(api)
        participant = fixtures.create_participant(
            api,
            plan["id"],
            participant_reference="AC-LONG",
            cohort=DEFERRED,
            stated_monthly_benefit_cents=52500,
            final_average_monthly_earnings_cents=100000,
            credited_service_months=480,
            date_of_birth="1958-09-09",
        )
        first = fixtures.open_benefit_audit(api, participant["id"])
        fixtures.resolve_audit(api, first["id"], "ACCEPT_AS_IS")

        second = fixtures.open_benefit_audit(
            api, participant["id"], credited_service_months=600
        )

        assert second["recomputed_monthly_benefit_cents"] == constants.recomputed_monthly_benefit(
            100000, 600
        )
        assert second["recomputed_monthly_benefit_cents"] == 52500
        assert second["variance_cents"] == 0
        assert second["audit_sequence"] == 2

        rows = fixtures.list_benefit_audits(api, participant["id"])
        superseded = [row for row in rows if row["id"] == first["id"]]
        assert len(superseded) == 1
        assert superseded[0]["audit_status"] == BenefitAuditStatus.SUPERSEDED.value


class TestTrancheLiabilityAggregation:
    """A tranche sums only the participants standing in its assigned population."""

    @staticmethod
    def _plan_with_three_deferred(api):
        fixtures.reset_clock(api)
        plan = fixtures.create_plan(api)
        participants = [
            fixtures.create_participant(
                api,
                plan["id"],
                participant_reference=reference,
                cohort=DEFERRED,
                stated_monthly_benefit_cents=100000,
                final_average_monthly_earnings_cents=250000,
                credited_service_months=320,
                date_of_birth=date_of_birth,
            )
            for reference, date_of_birth in (
                ("AC-0081", "1968-04-04"),
                ("AC-0082", "1969-05-05"),
                ("AC-0083", "1970-06-06"),
            )
        ]
        tranche = fixtures.create_tranche(
            api, plan["id"], DEFERRED, tranche_name="Ashcroft Tranche"
        )
        return plan, participants, tranche

    def test_calc_tranche_liability_excludes_unassigned_participants(self, api):
        """Two assignments sum to 22,920,000 and 25,080,000 while the third participant is ignored.

        **Tranche liability and readiness** are always derived from the tranche's currently assigned population — every participant whose `tranche_id` is this tranche and whose `participant_status` is `ASSIGNED`.
        The tranche's `accounting_liability_cents` is the sum of those participants' `accounting_liability_cents` and its `settlement_liability_cents` is the sum of their `settlement_liability_cents`, both 0 when the population is empty; because the per-participant amounts are already rounded, no further rounding happens at the tranche level.
        A `PlanAdministrator` then assigns participants one at a time by supplying a `participant_id`, moving that participant `IN_PLAN → ASSIGNED` and setting its `tranche_id`.

        Design: Corner/calculations/tranche_liability_sums_only_the_participants_actually_assigned
        """
        _plan, participants, tranche = self._plan_with_three_deferred(api)
        first, second, third = participants

        assert tranche["accounting_liability_cents"] == 0
        assert tranche["settlement_liability_cents"] == 0
        assert tranche["assigned_participant_count"] == 0

        fixtures.assign_participant(api, tranche["id"], first["id"])
        after_one = fixtures.read_tranche(api, tranche["id"])
        assert after_one["accounting_liability_cents"] == constants.accounting_liability(
            100000, DEFERRED
        )
        assert after_one["assigned_participant_count"] == 1

        fixtures.assign_participant(api, tranche["id"], second["id"])
        after_two = fixtures.read_tranche(api, tranche["id"])
        assert after_two["accounting_liability_cents"] == 2 * constants.accounting_liability(
            100000, DEFERRED
        )
        assert after_two["accounting_liability_cents"] == 22920000
        assert after_two["settlement_liability_cents"] == 2 * constants.settlement_liability(
            100000, DEFERRED
        )
        assert after_two["settlement_liability_cents"] == 25080000
        assert after_two["assigned_participant_count"] == 2

        untouched = fixtures.read_participant(api, third["id"])
        assert untouched["participant_status"] == ParticipantStatus.IN_PLAN.value
        assert untouched["tranche_id"] is None

        rows, meta = validate_paginated(
            api.list_participants(administrator_headers(), {"tranche_id": tranche["id"]})
        )
        assert meta["total_count"] == 2
        assert sorted(row["id"] for row in rows) == sorted([first["id"], second["id"]])

    def test_calc_tranche_readiness_flag_stays_blocked_while_sums_grow(self, api):
        """The readiness flag is BLOCKED empty and still BLOCKED once uncleansed members are assigned.

        The `data_readiness_flag` is `BLOCKED` if the population is empty, `BLOCKED` if any assigned participant's `data_status` is anything other than `CLEAN`, `BLOCKED` if any assigned participant's `mortality_status` is anything other than `ALIVE_CONFIRMED`, `BLOCKED` if any assigned participant's `benefit_audit_status` is outside `PASSED_CLOSED` and `CORRECTED`, and `READY` only when none of those conditions holds.

        Design: Corner/calculations/tranche_liability_sums_only_the_participants_actually_assigned
        """
        _plan, participants, tranche = self._plan_with_three_deferred(api)
        first, second, _third = participants

        assert tranche["tranche_status"] == TrancheStatus.DRAFT.value
        assert tranche["data_readiness_flag"] == DataReadinessFlag.BLOCKED.value

        fixtures.assign_participant(api, tranche["id"], first["id"])
        fixtures.assign_participant(api, tranche["id"], second["id"])

        after_two = fixtures.read_tranche(api, tranche["id"])
        assert after_two["data_readiness_flag"] == DataReadinessFlag.BLOCKED.value

        for participant_id in (first["id"], second["id"]):
            assigned = fixtures.read_participant(api, participant_id)
            assert assigned["participant_status"] == ParticipantStatus.ASSIGNED.value
            assert assigned["data_status"] == DataStatus.NEEDS_REVIEW.value
            assert assigned["mortality_status"] == MortalityStatus.UNVERIFIED.value
            assert assigned["address_status"] == AddressStatus.UNCONFIRMED.value
            assert assigned["benefit_audit_status"] == ParticipantAuditStatus.NOT_AUDITED.value


class TestCapWaterfall:
    """A breach defers one election and the walk carries on to the next."""

    def test_calc_cap_waterfall_defers_one_election_and_keeps_walking(self, api):
        """A 2,858,400 election is deferred yet a later 1,200,000 election is still honoured.

        **The cap waterfall** visits every election of the window whose `election_status` is `ELECTED_LUMP_SUM`, in `elected_at` ascending order, ties broken by the election's participant's `created_at` ascending and then by the election's own `created_at` ascending; the elections' identifiers are never used as an ordering key.
        If the candidate total exceeds the cap, the election transitions `ELECTED_LUMP_SUM → CAP_DEFERRED`, the running total is left unchanged, and **the walk continues to the next election** — it does not stop.
        When the walk finishes, the running total is stored as `approved_lump_sum_total_cents`.
        A `raw_pv_cents` above 2,400,000 and at most 12,000,000 sets `admin_fee_bp` to 75.

        Design: Corner/calculations/cap_waterfall_defers_one_election_and_keeps_walking
        """
        fixtures.reset_clock(api)
        plan = fixtures.create_plan(api)

        first = fixtures.create_clean_participant(
            api,
            plan["id"],
            participant_reference="AC-A",
            cohort=DEFERRED,
            stated_monthly_benefit_cents=20000,
            final_average_monthly_earnings_cents=100000,
            credited_service_months=160,
            date_of_birth="1967-01-01",
        )
        second = fixtures.create_clean_participant(
            api,
            plan["id"],
            participant_reference="AC-B",
            cohort=DEFERRED,
            stated_monthly_benefit_cents=24000,
            final_average_monthly_earnings_cents=100000,
            credited_service_months=192,
            date_of_birth="1966-02-02",
        )
        third = fixtures.create_clean_participant(
            api,
            plan["id"],
            participant_reference="AC-C",
            cohort=DEFERRED,
            stated_monthly_benefit_cents=10000,
            final_average_monthly_earnings_cents=100000,
            credited_service_months=80,
            date_of_birth="1965-03-03",
        )

        fixtures.create_approved_strategy(
            api, plan["id"], StrategyType.LUMP_SUM_WINDOW.value
        )
        fixtures.adopt_amendment(
            api, plan["id"], "LUMP_SUM_ONLY", "2026-08-01T00:00:00Z"
        )

        window = fixtures.create_window(
            api,
            plan["id"],
            opens_at="2026-08-01T00:00:00Z",
            closes_at="2026-09-30T00:00:00Z",
            window_name="Ashcroft Window One",
            lump_sum_cap_cents=5000000,
            eligibility_max_lump_sum_cents=3000000,
        )
        opened = fixtures.open_window(api, window["id"])
        assert opened["notice_count"] == 3

        elections = {}
        for elected_at, participant in (
            ("2026-08-02T00:00:00Z", first),
            ("2026-08-03T00:00:00Z", second),
            ("2026-08-04T00:00:00Z", third),
        ):
            election = fixtures.election_for(api, window["id"], participant["id"])
            fixtures.set_clock(api, elected_at)
            elections[participant["id"]] = fixtures.elect(
                api, election["id"], participant["id"], "LUMP_SUM"
            )

        # 2,400,000 sits on the inclusive zero-fee ceiling; 2,880,000 pays 75 bp.
        expected_nets = {}
        for participant, monthly in ((first, 20000), (second, 24000), (third, 10000)):
            raw_pv = constants.raw_lump_sum_pv(monthly, DEFERRED)
            expected_nets[participant["id"]] = constants.net_lump_sum_cents_for(raw_pv)
            priced = elections[participant["id"]]
            assert priced["raw_pv_cents"] == raw_pv
            assert priced["admin_fee_bp"] == constants.admin_fee_bp_for(raw_pv)
            assert priced["net_lump_sum_cents"] == expected_nets[participant["id"]]

        assert expected_nets[first["id"]] == 2400000
        assert expected_nets[second["id"]] == 2858400
        assert expected_nets[third["id"]] == 1200000

        fixtures.set_clock(api, "2026-09-30T00:00:00Z")
        closed = fixtures.close_window(api, window["id"])

        assert closed["window_status"] == WindowStatus.CLOSED.value
        assert closed["notice_count"] == 3
        assert closed["approved_lump_sum_total_cents"] == (
            expected_nets[first["id"]] + expected_nets[third["id"]]
        )
        assert closed["approved_lump_sum_total_cents"] == 3600000

        assert (
            fixtures.read_election(api, elections[first["id"]]["id"])["election_status"]
            == ElectionStatus.ELECTED_LUMP_SUM.value
        )
        assert (
            fixtures.read_election(api, elections[second["id"]]["id"])["election_status"]
            == ElectionStatus.CAP_DEFERRED.value
        )
        assert (
            fixtures.read_election(api, elections[third["id"]]["id"])["election_status"]
            == ElectionStatus.ELECTED_LUMP_SUM.value
        )
