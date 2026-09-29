"""Dual-variant computed reads: cost per style, and retouch turnaround.

Both concerns report two figures derived from the same instants or the same
snapshot, and the two figures are required to diverge.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import fixtures as fx
from test_helpers.test_users import CONTENT_OPS, QC_REVIEWER


def _wrapped_style_with_one_captured_item(api):
    """Two required ON_MODEL items on one 240-minute session; only one captured."""
    world = fx.build_reference_data(api, with_outsourced=True)
    fx.build_style_on_the_rack(api, world, style_kw={"priority_tier": "A"})
    fx.build_planned_session(
        api,
        world,
        item_specs=[
            {"asset_kind": "ON_MODEL", "angle_code": "FRONT"},
            {"asset_kind": "ON_MODEL", "angle_code": "BACK"},
        ],
        session_kw={"session_label": "TOP1001 day 1"},
    )
    fx.build_shooting_session(api, world)
    fx.build_ingested_asset(api, world, item_index=0)
    fx.set_clock(api, "2026-08-03T11:55:00Z")
    fx.wrap_session(api, world.session_id, world.photographer_id)
    return world


def test_cost_summary_reports_both_variants_from_the_same_snapshot(api):
    """The provisional projection and the finance actual diverge in one response.

    PRD: "`final_cost_cents` is simply the style's persisted `allocated_cost_cents`, which is to say the sum of the per-item allocations already posted at each session wrap."

    Design: Difficulty/dual_variant_calc/cost_per_style_provisional_vs_final_diverge_on_one_snapshot
    """
    world = _wrapped_style_with_one_captured_item(api)

    summary = validate_success(api.get_cost_summary(world.style_id, CONTENT_OPS))

    assert summary["provisional_cost_cents"] == 122000
    assert summary["final_cost_cents"] == 101958


def test_cost_summary_per_asset_figures_use_their_own_denominators(api):
    """The two per-asset figures normalise by different item counts.

    PRD: "Each variant's cost is divided by its denominator, or by 1 when that denominator is zero, and rounded half up to a whole cent, giving `provisional_cost_per_asset_cents` and `final_cost_per_asset_cents` respectively."

    Design: Difficulty/dual_variant_calc/cost_per_style_provisional_vs_final_diverge_on_one_snapshot
    """
    world = _wrapped_style_with_one_captured_item(api)

    summary = validate_success(api.get_cost_summary(world.style_id, CONTENT_OPS))

    assert summary["provisional_cost_per_asset_cents"] == 61000
    assert summary["final_cost_per_asset_cents"] == 101958


def test_cost_summary_variance_and_recommendation_favour_the_building(api):
    """The best outsourced quote, the variance against it, and the recommendation.

    PRD: "`recommended_source` is the string `IN_HOUSE` when there is no quote at all or when the final cost is less than or equal to the quote, and the string `OUTSOURCED` only when the final cost is strictly greater than the quote"

    Design: Difficulty/dual_variant_calc/cost_per_style_provisional_vs_final_diverge_on_one_snapshot
    """
    world = _wrapped_style_with_one_captured_item(api)

    summary = validate_success(api.get_cost_summary(world.style_id, CONTENT_OPS))

    assert summary["style_id"] == world.style_id
    assert summary["outsourced_quote_cents"] == 120000
    assert summary["outsourced_provider_id"] == world.outsourced["id"]
    assert summary["variance_cents"] == -18042
    assert summary["recommended_source"] == "IN_HOUSE"


def test_wrap_allocation_posts_only_to_the_captured_item(api):
    """The wrap-time allocation reaches the captured item and passes the assigned one by.

    PRD: "The system then collects every shot-list item on this session whose `item_state` is `CAPTURED`, ordered by `created_at` ascending — never by identifier — and counts them."

    Design: Difficulty/dual_variant_calc/cost_per_style_provisional_vs_final_diverge_on_one_snapshot
    """
    world = _wrapped_style_with_one_captured_item(api)

    assert world.read_session()["actual_minutes"] == 175
    assert world.read_item(0)["allocated_cost_cents"] == 101958
    assert world.read_item(1)["allocated_cost_cents"] == 0
    assert world.read_style()["allocated_cost_cents"] == 101958


def _approved_task_after_one_rework_loop(api):
    """A tier-A asset ingested at 10:00, rejected at 15:00, resubmitted at 19:00."""
    world = fx.build_reference_data(
        api, profile_kw={"required_angles": ["FRONT"]}
    )
    world.retoucher = fx.create_retoucher(api, minimum_call_hours=0)
    fx.build_style_on_the_rack(api, world, style_kw={"priority_tier": "A"})
    fx.build_planned_session(
        api, world, item_specs=[{"asset_kind": "ON_MODEL", "angle_code": "FRONT"}]
    )
    fx.build_shooting_session(api, world)
    fx.set_clock(api, "2026-08-03T10:00:00Z")
    fx.build_ingested_asset(api, world)
    fx.build_queued_task(api, world)
    claimed = fx.claim_next(api, world.retoucher_id)
    fx.set_clock(api, "2026-08-03T11:00:00Z")
    fx.submit_task(api, claimed["id"], world.retoucher_id)
    fx.set_clock(api, "2026-08-03T15:00:00Z")
    fx.qc_reject(api, claimed["id"])
    fx.set_clock(api, "2026-08-03T19:00:00Z")
    fx.submit_task(api, claimed["id"], world.retoucher_id)
    fx.set_clock(api, "2026-08-03T20:00:00Z")
    world.tasks = [claimed]
    return world


def test_gross_and_net_turnaround_diverge_by_the_banked_rework_hours(api):
    """Ten gross hours less four banked rework hours leaves six net hours.

    PRD: "The net variant, `turnaround_hours_net`, is that gross figure less the accumulated `rework_hours_total`, again rounded half up to two decimals; it is the provider-facing scorecard used in the outsourced comparison, and it deducts producer-side waiting and nothing else."

    Design: Difficulty/dual_variant_calc/retouch_turnaround_gross_breaches_while_net_sits_on_the_sla
    """
    world = _approved_task_after_one_rework_loop(api)

    task = validate_success(
        api.qc_decision(world.task_id, {"decision": "APPROVE"}, QC_REVIEWER)
    )

    assert task["rework_count"] == 1
    assert float(task["rework_hours_total"]) == 4.00
    assert float(task["turnaround_hours_gross"]) == 10.00
    assert float(task["turnaround_hours_net"]) == 6.00


def test_sla_verdict_is_read_from_the_gross_variant_only(api):
    """The task breaches on gross while the net figure sits exactly on the service level.

    PRD: "`sla_state` becomes `BREACHED` when the gross figure is strictly greater than the task's pinned `sla_hours`, otherwise `AT_RISK` when the gross figure is strictly greater than four fifths of that `sla_hours`, and otherwise `IN_SLA`."

    Design: Difficulty/dual_variant_calc/retouch_turnaround_gross_breaches_while_net_sits_on_the_sla
    """
    world = _approved_task_after_one_rework_loop(api)

    task = validate_success(
        api.qc_decision(world.task_id, {"decision": "APPROVE"}, QC_REVIEWER)
    )

    assert task["sla_hours"] == 6
    assert float(task["turnaround_hours_net"]) == 6.00
    assert task["sla_state"] == "BREACHED"


def test_approval_is_terminal_for_the_task_and_moves_the_asset(api):
    """Approval settles both the task and the file it was working on.

    PRD: "Approval moves the task `SUBMITTED → APPROVED`, which is terminal, stamps `approved_at` from the logical clock, moves the asset `QC_PENDING → APPROVED`, and lowers the provider's `assigned_asset_count` by one."

    Design: Difficulty/dual_variant_calc/retouch_turnaround_gross_breaches_while_net_sits_on_the_sla
    """
    world = _approved_task_after_one_rework_loop(api)

    task = validate_success(
        api.qc_decision(world.task_id, {"decision": "APPROVE"}, QC_REVIEWER)
    )

    assert task["task_state"] == "APPROVED"
    assert world.read_asset()["asset_state"] == "APPROVED"
