"""The reported and audited variants of the administrative fee, and their true-up."""

from prd_bench_local_runner.testing import validate_success

from test_helpers import ADMIN_REVIEW, assert_cents, assert_score
from test_helpers.constants import (
    CLOCK_OCT_01,
    PRIMER_QTY_FOR_20000000,
    SEP_PERIOD_END,
    SEP_PERIOD_START,
    SKU_DISPENSER,
    SKU_LINER,
)
from test_helpers.factories import ADJUSTMENT_LINE, DISPENSER_LINE, LINER_LINE
from test_helpers.fixtures import (
    accept_report,
    open_report,
    prime_committed_spend,
    read_report,
    read_supplier,
    read_usage,
    reconcile_report,
    record_confirmed_usage,
    remit_fee,
    set_clock,
    setup_active_contract,
    setup_authorised_member,
    submit_report,
)


def _rounding_only_world(api):
    """Three tier-0 orders of 9015 cents, all confirmed inside one September period."""
    world = setup_active_contract(api, lines=(LINER_LINE, DISPENSER_LINE, ADJUSTMENT_LINE))
    member, analysis = setup_authorised_member(api, world)
    world["member"] = member
    world["usages"] = [
        record_confirmed_usage(
            api,
            world["contract"]["id"],
            member["id"],
            world["lines"][SKU_LINER]["id"],
            analysis["id"],
            quantity=1,
        )
        for _ in range(3)
    ]
    world["report"] = open_report(
        api, world, period_start=SEP_PERIOD_START, period_end=SEP_PERIOD_END
    )
    return world


def _tier_rebate_world(api):
    """One tier-2 order whose frozen fee rate is rebated below the contract rate."""
    world = setup_active_contract(api, lines=(DISPENSER_LINE, ADJUSTMENT_LINE))
    member, analysis = setup_authorised_member(
        api,
        world,
        legal_name="Gulf Coast Regional Purchasing Council",
        state_code="TX",
        member_category="COUNTY",
        annual_spend_ceiling_cents=50000000,
        governing_body_resolution_number="RES-TX-2026-009",
    )
    prime_committed_spend(api, world, member, analysis, PRIMER_QTY_FOR_20000000)
    world["member"] = member
    world["usage"] = record_confirmed_usage(
        api,
        world["contract"]["id"],
        member["id"],
        world["lines"][SKU_DISPENSER]["id"],
        analysis["id"],
        quantity=10,
    )
    world["report"] = open_report(
        api, world, period_start=SEP_PERIOD_START, period_end=SEP_PERIOD_END
    )
    return world


class TestReportedVersusAuditedFee:
    def test_01_submission_rounds_the_period_aggregate_exactly_once(self, api):
        """PRD §3.7: "Submission also computes the *reported* variant of the
        administrative fee: `reported_fee_cents` is `reported_chargeable_cents`
        multiplied by the contract's `admin_fee_rate_bps` and divided by 10,000,
        rounded half up to a whole cent."

        Design: Difficulty/dual_variant_calc/admin_fee_reported_versus_audited_rounding_only_divergence
        """
        world = _rounding_only_world(api)
        set_clock(api, CLOCK_OCT_01)
        report = submit_report(api, world, world["report"]["id"])

        assert report["swept_usage_count"] == 3
        assert_cents(report["reported_chargeable_cents"], 27045, "reported_chargeable_cents")
        assert_cents(report["reported_usage_cents"], 27585, "reported_usage_cents")
        assert_cents(report["reported_fee_cents"], 541, "reported_fee_cents")

    def test_02_reconciliation_sums_the_individually_rounded_order_fees(self, api):
        """PRD §3.7: "The *audited* variant is computed later, at reconciliation:
        `audited_fee_cents` is the plain sum of the swept orders' own
        `admin_fee_cents`, each of which was frozen at that order's tier-rebated
        `effective_fee_rate_bps` and rounded individually."

        Design: Difficulty/dual_variant_calc/admin_fee_reported_versus_audited_rounding_only_divergence
        """
        world = _rounding_only_world(api)
        set_clock(api, CLOCK_OCT_01)
        submit_report(api, world, world["report"]["id"])
        accept_report(api, world["report"]["id"])
        remit_fee(api, world, world["report"]["id"], 541)
        report = reconcile_report(api, world["report"]["id"])

        assert report["status"] == "RECONCILED"
        assert_cents(report["audited_fee_cents"], 540, "audited_fee_cents")
        first_order = read_usage(api, world["usages"][0]["id"])
        assert_cents(first_order["admin_fee_cents"], 180, "admin_fee_cents")
        assert first_order["effective_fee_rate_bps"] == 200

    def test_03_true_up_and_rebate_are_the_signed_difference_between_the_variants(self, api):
        """PRD §3.7: "It computes the audited variant and its consequences:
        `audited_fee_cents` as described above; `fee_true_up_cents` as
        `audited_fee_cents` minus `reported_fee_cents`, a signed figure; and
        `fee_rebate_cents` as `reported_fee_cents` minus `audited_fee_cents`, which
        is the cooperative's tier concession expressed positively and equals the
        negation of `fee_true_up_cents` wherever no rounding divergence exists."

        Design: Difficulty/dual_variant_calc/admin_fee_reported_versus_audited_rounding_only_divergence
        """
        world = _rounding_only_world(api)
        set_clock(api, CLOCK_OCT_01)
        submit_report(api, world, world["report"]["id"])
        accept_report(api, world["report"]["id"])
        remit_fee(api, world, world["report"]["id"], 541)
        report = reconcile_report(api, world["report"]["id"])

        assert_cents(report["fee_true_up_cents"], -1, "fee_true_up_cents")
        assert_cents(report["fee_rebate_cents"], 1, "fee_rebate_cents")

    def test_04_a_rounding_only_divergence_stays_under_the_variance_threshold(self, api):
        """PRD §3.7: "`variance_pct` is one hundred multiplied by the absolute value
        of `fee_true_up_cents` and divided by `audited_fee_cents`, rounded half up to
        two decimals; when `audited_fee_cents` is zero, `variance_pct` is 0.00 rather
        than undefined."

        Design: Difficulty/dual_variant_calc/admin_fee_reported_versus_audited_rounding_only_divergence
        """
        world = _rounding_only_world(api)
        set_clock(api, CLOCK_OCT_01)
        submit_report(api, world, world["report"]["id"])
        accept_report(api, world["report"]["id"])
        remit_fee(api, world, world["report"]["id"], 541)
        report = reconcile_report(api, world["report"]["id"])

        assert_score(report["variance_pct"], 0.19, "variance_pct")
        assert report["variance_flagged"] is False
        supplier = read_supplier(api, world["contract"]["supplier_id"])
        assert_score(supplier["performance_score"], 100.00, "performance_score")


class TestTierRebateDivergence:
    def test_05_the_bulk_reported_fee_ignores_every_order_level_tier_rebate(self, api):
        """PRD §3.7: "This is one bulk application of the contract's base rate to the
        period aggregate, with a single rounding at the end; it ignores every order's
        tier rebate entirely, and it is the amount printed on the supplier's
        remittance advice and the amount actually invoiced and remitted."

        Design: Difficulty/dual_variant_calc/admin_fee_reported_versus_audited_tier_rebate_divergence
        """
        world = _tier_rebate_world(api)
        set_clock(api, CLOCK_OCT_01)
        report = submit_report(api, world, world["report"]["id"])

        assert report["swept_usage_count"] == 1
        assert_cents(report["reported_chargeable_cents"], 102500, "reported_chargeable_cents")
        assert_cents(report["reported_fee_cents"], 2050, "reported_fee_cents")
        order = read_usage(api, world["usage"]["id"])
        assert order["discount_tier_index"] == 2
        assert order["effective_fee_rate_bps"] == 150
        assert_cents(order["admin_fee_cents"], 1538, "admin_fee_cents")

    def test_06_the_audited_variant_keeps_the_rebated_rate_and_yields_a_negative_true_up(self, api):
        """PRD §3.7: "The two figures diverge for two independent reasons — tier
        rebates present on some orders, and per-order rounding — so the same swept set
        genuinely yields two different totals."

        Design: Difficulty/dual_variant_calc/admin_fee_reported_versus_audited_tier_rebate_divergence
        """
        world = _tier_rebate_world(api)
        set_clock(api, CLOCK_OCT_01)
        submit_report(api, world, world["report"]["id"])
        accept_report(api, world["report"]["id"])
        remit_fee(api, world, world["report"]["id"], 2050)
        report = reconcile_report(api, world["report"]["id"])

        assert_cents(report["audited_fee_cents"], 1538, "audited_fee_cents")
        assert_cents(report["fee_true_up_cents"], -512, "fee_true_up_cents")
        assert_cents(report["fee_rebate_cents"], 512, "fee_rebate_cents")

    def test_07_a_variance_above_fifteen_percent_flags_the_report_and_charges_points(self, api):
        """PRD §3.7: "When `variance_pct` is strictly greater than fifteen percent,
        `variance_flagged` is set to true and five performance points are added to the
        supplier's `deduction_points_total`."

        Design: Difficulty/dual_variant_calc/admin_fee_reported_versus_audited_tier_rebate_divergence
        """
        world = _tier_rebate_world(api)
        set_clock(api, CLOCK_OCT_01)
        submit_report(api, world, world["report"]["id"])
        accept_report(api, world["report"]["id"])
        remit_fee(api, world, world["report"]["id"], 2050)
        report = reconcile_report(api, world["report"]["id"])

        assert_score(report["variance_pct"], 33.29, "variance_pct")
        assert report["variance_flagged"] is True
        supplier = read_supplier(api, world["contract"]["supplier_id"])
        assert_score(supplier["deduction_points_total"], 5.00, "deduction_points_total")
        assert_score(supplier["performance_score"], 95.00, "performance_score")
        assert supplier["performance_tier"] == "PREFERRED"

    def test_08_the_reconciled_report_is_readable_with_both_fee_variants(self, api):
        """PRD §3.7: "`fee_true_up_cents` is then applied to both the contract's and
        the supplier's `fee_assessed_cents_total`, and the contract's
        `fee_outstanding_cents` is recomputed."

        Design: Difficulty/dual_variant_calc/admin_fee_reported_versus_audited_tier_rebate_divergence
        """
        world = _tier_rebate_world(api)
        set_clock(api, CLOCK_OCT_01)
        submit_report(api, world, world["report"]["id"])
        accept_report(api, world["report"]["id"])
        remit_fee(api, world, world["report"]["id"], 2050)
        reconcile_report(api, world["report"]["id"])

        stored = read_report(api, world["report"]["id"])
        assert stored["status"] == "RECONCILED"
        assert_cents(stored["reported_fee_cents"], 2050, "reported_fee_cents")
        assert_cents(stored["audited_fee_cents"], 1538, "audited_fee_cents")
        contract = validate_success(api.get_master_contract(world["contract"]["id"], ADMIN_REVIEW))
        assert_cents(
            contract["fee_assessed_cents_total"], 2050 - 512, "fee_assessed_cents_total"
        )
