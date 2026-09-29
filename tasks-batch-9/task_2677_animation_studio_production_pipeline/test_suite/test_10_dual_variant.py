"""Dual-variant calculations: shot earned value and partner quality scoring."""

from prd_bench_local_runner.testing import get_success_data, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_cents,
    assert_earned_value_report,
    assert_four_decimal,
    assert_two_decimal,
)
from test_helpers.constants import (
    NEUTRAL_QUALITY_SCORE,
    PACKAGE_ISSUED,
    VARIANT_HOURS_PROGRESS,
    VARIANT_STAGE_WEIGHT,
)
from test_helpers.test_users import (
    ARTIST_HEADERS,
    COORDINATOR_HEADERS,
    SUPERVISOR_HEADERS,
)


def _shot_with_layout_approved_at_twelve_hours(client):
    """Aurora Drift with one shot whose LAYOUT stage is approved on 12.0 hours."""
    production = fx.active_production(
        client,
        title="Aurora Drift",
        production_code="AD01",
        budget_cents=100000000,
        render_allowance_cents=5000000,
        contingency_pct=0.10,
        approved_color_spaces=["ACEScg", "Rec709"],
        gate_types=["SCRIPT"],
    )
    shot = fx.create_shot(
        client,
        production["id"],
        shot_code="AD01_010_0010",
        sequence_code="010",
        frame_count=120,
        budget_cents=1000000,
        planned_start_at="2026-08-01T00:00:00Z",
        planned_finish_at="2026-09-30T00:00:00Z",
        difficulty_factor=1.25,
    )
    layout = fx.task_for_stage(client, shot["id"], "LAYOUT")
    fx.assign_task(client, layout["id"])
    get_success_data(
        client.log_hours(layout["id"], f.log_hours_payload(12.0), ARTIST_HEADERS)
    )
    fx.submit_task(client, layout["id"])
    fx.approve_task(client, layout["id"])
    fx.move_clock(client, "2026-08-16T00:00:00Z")
    return production, shot


def _partner_with_two_aged_qc_decisions(client):
    """A TIER3 partner carrying a 100-day-old FAIL and a 10-day-old PASS."""
    production = fx.active_production(
        client,
        title="Aurora Drift",
        production_code="AD01",
        budget_cents=100000000,
        render_allowance_cents=5000000,
        contingency_pct=0.10,
        gate_types=["SCRIPT"],
    )
    shot = fx.create_shot(
        client,
        production["id"],
        shot_code="AD01_010_0010",
        sequence_code="010",
        frame_count=120,
        budget_cents=1000000,
        planned_start_at="2026-08-01T00:00:00Z",
        planned_finish_at="2026-09-30T00:00:00Z",
    )
    layout = fx.task_for_stage(client, shot["id"], "LAYOUT")
    animation = fx.task_for_stage(client, shot["id"], "ANIMATION")

    partner = fx.approved_partner(
        client,
        legal_name="Northwind Animation",
        security_certification_level="TIER3",
        mfa_enforced=True,
        watermark_required=False,
    )
    assert_two_decimal(
        fx.read_partner(client, partner["id"])["quality_score_rolling"],
        NEUTRAL_QUALITY_SCORE,
        "quality_score_rolling",
    )

    failed = fx.draft_package(
        client,
        production["id"],
        partner["id"],
        package_code="AD01-PKG-B",
        security_tier="TIER3",
        fee_cents=100000,
        stage_task_ids=[animation["id"]],
        quality_min_score=45.00,
    )
    fx.issue_package(client, failed["id"])
    fx.accept_package(client, failed["id"], partner["id"])
    fx.deliver_package(client, failed["id"], partner["id"], watermark_applied=False)
    fx.qc_package(client, failed["id"], "FAIL", 40)

    fx.move_clock(client, "2026-10-30T00:00:00Z")

    passed = fx.draft_package(
        client,
        production["id"],
        partner["id"],
        package_code="AD01-PKG-A",
        security_tier="TIER1",
        fee_cents=100000,
        stage_task_ids=[layout["id"]],
        quality_min_score=40.00,
    )
    fx.issue_package(client, passed["id"])
    fx.accept_package(client, passed["id"], partner["id"])
    fx.deliver_package(client, passed["id"], partner["id"], watermark_applied=False)
    fx.qc_package(client, passed["id"], "PASS", 90)

    fx.move_clock(client, "2026-11-09T00:00:00Z")
    return production, shot, partner


class TestShotEarnedValueVariants:
    def test_stage_weight_and_hours_progress_disagree_on_identical_data(self, client):
        """One approved stage on 12.0 of 50.0 budgeted hours earns 100000 cents under the
        default variant and 240000 under HOURS_PROGRESS, so cpi moves from 0.9259 to
        2.2222 while bcws and acwp stay put.

        PRD: "Under it, credit is earned only in discrete stage-sized jumps: the system
        sums `stage_weight_pct` over exactly those stage tasks of the shot whose `status`
        is `APPROVED`, multiplies the shot's `budget_cents` by that sum, and rounds
        half-up to a whole cent."
        PRD: "Under it, the system divides the sum of `actual_hours` over the shot's five
        tasks by the sum of `budgeted_hours` over the same five tasks, clamps that ratio
        so it is never below 0.0 and never above 1.0, multiplies the shot's `budget_cents`
        by it, and rounds half-up to a whole cent."
        PRD: "The cost performance index `cpi` is `bcwp_cents` divided by `acwp_cents`,
        rounded half-up to four decimal places, and is **null** when `acwp_cents` is 0."

        Design: Difficulty/dual_variant_calc/shot_bcwp_stage_weight_vs_hours_progress
        """
        _, shot = _shot_with_layout_approved_at_twelve_hours(client)

        default_report = validate_success(
            client.get_shot_earned_value(shot["id"], SUPERVISOR_HEADERS)
        )
        assert_earned_value_report(
            default_report,
            VARIANT_STAGE_WEIGHT,
            bcws_cents=250000,
            bcwp_cents=100000,
            acwp_cents=108000,
            cpi=0.9259,
            spi=0.4000,
        )

        hours_report = validate_success(
            client.get_shot_earned_value(
                shot["id"], SUPERVISOR_HEADERS, {"variant": VARIANT_HOURS_PROGRESS}
            )
        )
        assert_earned_value_report(
            hours_report,
            VARIANT_HOURS_PROGRESS,
            bcws_cents=250000,
            bcwp_cents=240000,
            acwp_cents=108000,
            cpi=2.2222,
        )

        assert hours_report["bcwp_cents"] != default_report["bcwp_cents"], (
            "the two variants must disagree on identical data"
        )
        assert_cents(hours_report["bcws_cents"], default_report["bcws_cents"], "bcws_cents")
        assert_cents(hours_report["acwp_cents"], default_report["acwp_cents"], "acwp_cents")

    def test_only_the_stage_weight_figures_are_persisted_on_the_shot(self, client):
        """The row itself carries the STAGE_WEIGHT numbers, so the shot reads 100000 rather
        than the 240000 the hours view reports for the same data.

        PRD: "The `STAGE_WEIGHT` variant is the default, and it is the variant persisted
        into the shot's own `bcwp_cents`, `cpi` and `spi` fields and rolled up into the
        production."
        PRD: "This variant credits partial work on unapproved stages, which is precisely
        why it is never persisted and never rolled up."

        Design: Difficulty/dual_variant_calc/shot_bcwp_stage_weight_vs_hours_progress
        """
        production, shot = _shot_with_layout_approved_at_twelve_hours(client)

        stored = fx.read_shot(client, shot["id"])
        assert_cents(stored["bcwp_cents"], 100000, "Shot.bcwp_cents")
        assert_four_decimal(stored["cpi"], 0.9259, "Shot.cpi")
        assert_four_decimal(stored["spi"], 0.4000, "Shot.spi")
        assert_cents(stored["bcws_cents"], 250000, "Shot.bcws_cents")
        assert_cents(stored["acwp_cents"], 108000, "Shot.acwp_cents")
        assert_cents(stored["labor_cost_cents"], 108000, "Shot.labor_cost_cents")

        rolled_up = fx.read_production(client, production["id"])
        assert_cents(rolled_up["bcwp_cents"], 100000, "Production.bcwp_cents")
        assert_cents(rolled_up["bcws_cents"], 250000, "Production.bcws_cents")
        assert_cents(rolled_up["acwp_cents"], 108000, "Production.acwp_cents")
        assert_four_decimal(rolled_up["cpi"], 0.9259, "Production.cpi")
        assert_four_decimal(rolled_up["spi"], 0.4000, "Production.spi")

        hours_report = validate_success(
            client.get_shot_earned_value(
                shot["id"], SUPERVISOR_HEADERS, {"variant": VARIANT_HOURS_PROGRESS}
            )
        )
        assert_cents(hours_report["bcwp_cents"], 240000, "HOURS_PROGRESS bcwp_cents")
        assert_cents(
            fx.read_shot(client, shot["id"])["bcwp_cents"],
            100000,
            "Shot.bcwp_cents after the hours read",
        )


class TestPartnerQualityVariants:
    def test_the_rolling_window_drops_the_hundred_day_old_failure(self, client):
        """A TIER3 failure aged 100 days falls out of the rolling window entirely, leaving
        the rolling score at the surviving pass while the lifetime score keeps the failure
        at tier weight 2.0.

        PRD: "The `ROLLING_90D` variant, stored in `quality_score_rolling`, applies a step
        decay on top of the tier weight: the full factor of 1.00 when the age is at most 30
        days, 0.75 when the age is above 30 and at most 60 days, 0.50 when the age is above
        60 and at most 90 days, and exclusion from the input set altogether once the age
        exceeds 90 days."
        PRD: "The `LIFETIME` variant, stored in `quality_score_lifetime`, is the same
        computation with **no** decay factor and **no** age cut-off: each package's weight
        is its tier weight alone, so every QC decision the vendor has ever received counts
        at full strength forever."
        PRD: "Each also has a tier weight taken from its `security_tier`: 1.0 for `TIER1`,
        1.5 for `TIER2` and 2.0 for `TIER3` — harder work counts for more."

        Design: Difficulty/dual_variant_calc/partner_quality_rolling_window_vs_lifetime
        """
        _, _, partner = _partner_with_two_aged_qc_decisions(client)

        scored = fx.read_partner(client, partner["id"])
        assert_two_decimal(scored["quality_score_rolling"], 90.00, "quality_score_rolling")
        assert_two_decimal(scored["quality_score_lifetime"], 56.67, "quality_score_lifetime")
        assert scored["qc_decided_package_count"] == 2, (
            "both QC decisions counted toward qc_decided_package_count"
        )
        assert scored["quality_score_rolling"] != scored["quality_score_lifetime"], (
            "the two variants must disagree on identical decision history"
        )

    def test_the_issue_gate_reads_the_rolling_score_not_the_lifetime_one(self, client):
        """A package demanding a minimum of 60.00 issues against the rolling 90.00 even
        though the lifetime 56.67 would fail the same floor.

        PRD: "For any partner with a decision older than 30 days the two variants therefore
        return different numbers, and it is the rolling variant — never the lifetime one —
        that the issue-time quality gate consults."
        PRD: "The partner's `quality_score_rolling` must be at least the package's
        `quality_min_score`, otherwise `ERR_PARTNER_QUALITY_BELOW_STANDARD`."

        Design: Difficulty/dual_variant_calc/partner_quality_rolling_window_vs_lifetime
        """
        production, shot, partner = _partner_with_two_aged_qc_decisions(client)

        scored = fx.read_partner(client, partner["id"])
        assert_two_decimal(scored["quality_score_rolling"], 90.00, "quality_score_rolling")
        assert_two_decimal(scored["quality_score_lifetime"], 56.67, "quality_score_lifetime")
        assert scored["quality_score_lifetime"] < 60.00 <= scored["quality_score_rolling"], (
            "the floor of 60.00 must sit between the two variants for this test to bite"
        )

        effects = fx.task_for_stage(client, shot["id"], "EFFECTS")
        demanding = fx.draft_package(
            client,
            production["id"],
            partner["id"],
            package_code="AD01-PKG-C",
            security_tier="TIER1",
            fee_cents=100000,
            stage_task_ids=[effects["id"]],
            quality_min_score=60.00,
        )
        issued = validate_success(
            client.issue_package(demanding["id"], {}, COORDINATOR_HEADERS)
        )
        assert issued["status"] == PACKAGE_ISSUED
        assert_cents(issued["fee_committed_cents"], 0, "fee_committed_cents")
        assert_two_decimal(
            fx.read_partner(client, partner["id"])["quality_score_rolling"],
            90.00,
            "quality_score_rolling after the issue",
        )
