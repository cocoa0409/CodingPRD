"""Combinatorial formulas: per-frame render cost, tiered admission, overhead tiers."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import fixtures as fx
from test_helpers.api_errors import ERR_RENDER_CAPACITY_EXCEEDED
from test_helpers.assertions import (
    assert_budget_position,
    assert_cents,
    assert_two_decimal,
)
from test_helpers.constants import JOB_RESERVED, PACKAGE_IN_PROGRESS
from test_helpers.test_users import PRODUCTION_MANAGER_HEADERS

WINDOW_START = "2026-08-10T00:00:00Z"
WINDOW_END = "2026-08-10T06:00:00Z"


def _show_with_pool_and_layout(client, render_allowance_cents=5000000):
    """Aurora Drift active, one shot with LAYOUT IN_PROGRESS, and a 100-core farm."""
    production = fx.active_production(
        client,
        title="Aurora Drift",
        production_code="AD01",
        budget_cents=100000000,
        render_allowance_cents=render_allowance_cents,
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
    fx.assign_task(client, layout["id"])
    pool = fx.create_pool(
        client, name="FARM-A", total_cores=100, cost_per_core_hour_cents=175
    )
    return production, shot, layout, pool


def _reservation(pool_id, task_id, version, cores, priority="NORMAL",
                 window_start=WINDOW_START, window_end=WINDOW_END):
    return {
        "render_pool_id": pool_id,
        "shot_stage_task_id": task_id,
        "priority": priority,
        "requested_cores": cores,
        "window_start": window_start,
        "window_end": window_end,
        "frame_count": 120,
        "seconds_per_frame": 50,
        "expected_render_pool_version": version,
    }


class TestRenderCostRoundingOrder:
    def test_the_per_frame_cent_is_rounded_before_the_frame_count_multiplies_it(self, client):
        """Three cores at 175 cents per core-hour and 50 seconds a frame price a raw
        7.291666 cents, so the reservation bills 7 times 120 frames and not the 875 cents a
        trailing rounding would produce.

        PRD: "The raw per-frame cost in cents is the pool's `cost_per_core_hour_cents`,
        multiplied by those core-seconds per frame, divided by the 3,600 seconds in an
        hour, and then multiplied by the priority multiplier — 0.80 for `LOW`, 1.00 for
        `NORMAL`, 1.35 for `HIGH` and 1.75 for `CRITICAL`."
        PRD: "Summing unrounded per-frame values and rounding only the total is wrong:
        three cores at 175 cents per core-hour, 50 seconds per frame at `NORMAL` priority
        over 120 frames yields 7 cents per frame and therefore 840 cents in total, not the
        875 that rounding at the end would produce."

        Design: Difficulty/combinatorial_formula/render_cost_rounds_per_frame_before_multiplying
        """
        _, _, layout, pool = _show_with_pool_and_layout(client)

        job = validate_success(
            client.create_render_job(
                _reservation(pool["id"], layout["id"], pool["version"], 3),
                PRODUCTION_MANAGER_HEADERS,
            ),
            201,
        )
        assert_cents(job["cost_per_frame_cents"], 7, "cost_per_frame_cents")
        assert_cents(job["estimated_cost_cents"], 840, "estimated_cost_cents")
        assert job["estimated_cost_cents"] != 875, (
            "summing unrounded per-frame values and rounding once is the forbidden order"
        )
        assert_two_decimal(job["committed_core_hours"], 18.00, "committed_core_hours")
        assert job["status"] == JOB_RESERVED
        assert job["final_cost_cents"] is None
        assert job["actual_seconds_per_frame"] is None
        assert job["frames_completed"] is None or job["frames_completed"] == 0

    def test_the_rounded_estimate_propagates_down_the_pool_shot_production_chain(self, client):
        """The single 840-cent estimate is the figure the pool, the shot and the show all
        report after the reservation is accepted.

        PRD: "Accepting the reservation sets `status` to `RESERVED`, adds 1 to the pool's
        `version`, recomputes the pool's `committed_core_hours` and `reserved_job_count`,
        and then recomputes the shot's `render_cost_committed_cents` followed by the
        production's `render_committed_cents` — in that order, so the ledger above always
        agrees with the ledger below."
        PRD: "Both computed figures are derived from the pool's reservations:
        `committed_core_hours` is the sum of `committed_core_hours` over the pool's jobs
        whose `status` is `RESERVED`, carried to two decimal places, and
        `reserved_job_count` is the count of those same jobs."

        Design: Difficulty/combinatorial_formula/render_cost_rounds_per_frame_before_multiplying
        """
        production, shot, layout, pool = _show_with_pool_and_layout(client)
        assert pool["version"] == 1, "a new pool opens at version 1"

        validate_success(
            client.create_render_job(
                _reservation(pool["id"], layout["id"], pool["version"], 3),
                PRODUCTION_MANAGER_HEADERS,
            ),
            201,
        )

        after_pool = fx.read_pool(client, pool["id"])
        assert_two_decimal(after_pool["committed_core_hours"], 18.00, "committed_core_hours")
        assert after_pool["reserved_job_count"] == 1
        assert after_pool["version"] == 2, "the accepted reservation advanced the pool"

        after_shot = fx.read_shot(client, shot["id"])
        assert_cents(after_shot["render_cost_committed_cents"], 840, "render_cost_committed_cents")
        assert_cents(after_shot["render_cost_actual_cents"], 0, "render_cost_actual_cents")

        after_production = fx.read_production(client, production["id"])
        assert_cents(after_production["render_committed_cents"], 840, "render_committed_cents")
        assert_cents(after_production["render_actual_cents"], 0, "render_actual_cents")


class TestRenderAdmissionTieredHeadroom:
    def test_the_same_sixty_core_pool_caps_normal_at_thirty_and_high_at_forty(self, client):
        """With 60 of 100 cores held over the window a NORMAL request for 31 and a HIGH
        request for 41 are both refused, yet 40 HIGH fits — the headroom is keyed on
        priority, not on a single linear allowance.

        PRD: "First the pool's usable ceiling is established, and the headroom the studio
        keeps free is deliberately **not** linear in priority: the reserved headroom fraction
        is 0.20 for a `LOW` request, 0.10 for `NORMAL`, and 0.00 for both `HIGH` and
        `CRITICAL`."
        PRD: "The headroom core count is `total_cores` multiplied by that fraction and
        rounded **up** to a whole core — always up, never rounded to nearest and never down
        — and the usable ceiling is `total_cores` minus that headroom."
        PRD: "Third, available capacity is the usable ceiling minus that peak usage."

        Design: Difficulty/combinatorial_formula/render_admission_tiered_headroom_nonlinear
        """
        production, shot, layout, pool = _show_with_pool_and_layout(client)
        validate_success(
            client.create_render_job(
                _reservation(pool["id"], layout["id"], pool["version"], 60),
                PRODUCTION_MANAGER_HEADERS,
            ),
            201,
        )
        held = fx.read_pool(client, pool["id"])
        assert held["version"] == 2
        assert_two_decimal(held["committed_core_hours"], 360.00, "committed_core_hours")

        validate_error(
            client.create_render_job(
                _reservation(pool["id"], layout["id"], 2, 31, priority="NORMAL"),
                PRODUCTION_MANAGER_HEADERS,
            ),
            ERR_RENDER_CAPACITY_EXCEEDED,
            409,
        )
        validate_error(
            client.create_render_job(
                _reservation(pool["id"], layout["id"], 2, 41, priority="HIGH"),
                PRODUCTION_MANAGER_HEADERS,
            ),
            ERR_RENDER_CAPACITY_EXCEEDED,
            409,
        )

        after_rejects = fx.read_pool(client, pool["id"])
        assert after_rejects["version"] == 2, "a refused admission must not touch the pool"
        assert after_rejects["reserved_job_count"] == 1
        assert_two_decimal(
            after_rejects["committed_core_hours"], 360.00, "committed_core_hours"
        )

        admitted = validate_success(
            client.create_render_job(
                _reservation(pool["id"], layout["id"], 2, 40, priority="HIGH"),
                PRODUCTION_MANAGER_HEADERS,
            ),
            201,
        )
        assert admitted["status"] == JOB_RESERVED
        assert admitted["requested_cores"] == 40

        settled_pool = fx.read_pool(client, pool["id"])
        assert settled_pool["version"] == 3
        assert settled_pool["reserved_job_count"] == 2
        assert_two_decimal(
            settled_pool["committed_core_hours"], 600.00, "committed_core_hours"
        )

    def test_low_normal_and_critical_read_three_different_ceilings_on_one_pool(self, client):
        """The identical 60-core occupancy leaves a LOW request 20 cores, a NORMAL request
        30 and a CRITICAL request the full 40, so 21 LOW and 31 NORMAL are refused while 40
        CRITICAL is admitted without preempting anybody.

        PRD: "A hundred-core pool therefore keeps 10 cores free from a `NORMAL` request and
        20 from a `LOW` one, while a `HIGH` or `CRITICAL` request may use all 100."
        PRD: "If not, and the request's `priority` is anything other than `CRITICAL`, the
        reservation is refused with `ERR_RENDER_CAPACITY_EXCEEDED`."
        PRD: "When no candidate job intersects at all, peak usage is 0."

        Design: Difficulty/combinatorial_formula/render_admission_tiered_headroom_nonlinear
        """
        production, shot, layout, pool = _show_with_pool_and_layout(client)
        incumbent = validate_success(
            client.create_render_job(
                _reservation(pool["id"], layout["id"], pool["version"], 60),
                PRODUCTION_MANAGER_HEADERS,
            ),
            201,
        )

        validate_error(
            client.create_render_job(
                _reservation(pool["id"], layout["id"], 2, 21, priority="LOW"),
                PRODUCTION_MANAGER_HEADERS,
            ),
            ERR_RENDER_CAPACITY_EXCEEDED,
            409,
        )
        validate_error(
            client.create_render_job(
                _reservation(pool["id"], layout["id"], 2, 31, priority="NORMAL"),
                PRODUCTION_MANAGER_HEADERS,
            ),
            ERR_RENDER_CAPACITY_EXCEEDED,
            409,
        )

        urgent = validate_success(
            client.create_render_job(
                _reservation(pool["id"], layout["id"], 2, 40, priority="CRITICAL"),
                PRODUCTION_MANAGER_HEADERS,
            ),
            201,
        )
        assert urgent["status"] == JOB_RESERVED
        assert urgent["preempted_by_render_job_id"] is None
        assert fx.read_job(client, incumbent["id"])["status"] == JOB_RESERVED, (
            "40 CRITICAL cores fit inside the zero-headroom ceiling, so nothing is preempted"
        )
        assert fx.read_pool(client, pool["id"])["reserved_job_count"] == 2


def _show_with_layout_task(client, title, production_code):
    """An active show carrying one shot whose LAYOUT task can be packaged out."""
    production = fx.active_production(
        client,
        title=title,
        production_code=production_code,
        budget_cents=100000000,
        render_allowance_cents=5000000,
        contingency_pct=0.10,
        gate_types=["SCRIPT"],
    )
    shot = fx.create_shot(
        client,
        production["id"],
        shot_code=production_code + "_010_0010",
        sequence_code="010",
        frame_count=120,
        budget_cents=1000000,
        planned_start_at="2026-08-01T00:00:00Z",
        planned_finish_at="2026-09-30T00:00:00Z",
    )
    return production, fx.task_for_stage(client, shot["id"], "LAYOUT")


def _accept_fee(client, production, partner, layout, package_code, fee_cents):
    """Draft, issue and accept one package so its fee becomes committed direct cost."""
    package = fx.draft_package(
        client,
        production["id"],
        partner["id"],
        package_code=package_code,
        security_tier="TIER1",
        fee_cents=fee_cents,
        stage_task_ids=[layout["id"]],
        quality_min_score=50.00,
    )
    fx.issue_package(client, package["id"])
    return fx.accept_package(client, package["id"], partner["id"])


class TestOverheadTierPinnedToDirect:
    def test_a_direct_commitment_of_4_900_000_takes_the_fifteen_percent_rate(self, client):
        """Accepting a 4,900,000-cent package commits 735,000 of overhead for a total of
        5,635,000 — not the 5,488,000 that keying the tier on the post-overhead total would
        produce.

        PRD: "**Step two** applies studio overhead, and the tier is keyed on the pre-overhead
        direct figure only — never on the grand total."
        PRD: "Because the tier is keyed on the direct figure, a direct commitment of
        4,900,000 cents takes the 15 percent rate and yields a total of 5,635,000 cents;
        keying the tier on the resulting total, which lands above the first ceiling, would
        produce the wrong 5,488,000 and is not what this system does."
        PRD: "Acceptance is the money event: `fee_committed_cents` is set to `fee_cents`, and
        the production's `direct_committed_cents`, `overhead_fee_cents`,
        `total_committed_cents` and `available_cents` are recomputed."

        Design: Difficulty/combinatorial_formula/production_overhead_tier_pinned_to_direct_committed
        """
        production, layout = _show_with_layout_task(client, "Aurora Drift", "AD01")
        partner = fx.approved_partner(
            client,
            legal_name="Northwind Animation",
            security_certification_level="TIER1",
            mfa_enforced=False,
            watermark_required=False,
        )

        opening = fx.read_production(client, production["id"])
        assert_budget_position(opening, 0, 0)
        assert_cents(opening["available_cents"], 110000000, "available_cents")

        accepted = _accept_fee(client, production, partner, layout, "AD01-PKG-A", 4900000)
        assert accepted["status"] == PACKAGE_IN_PROGRESS
        assert_cents(accepted["fee_committed_cents"], 4900000, "fee_committed_cents")

        after = fx.read_production(client, production["id"])
        assert_budget_position(after, 4900000, 735000)
        assert_cents(after["total_committed_cents"], 5635000, "total_committed_cents")
        assert after["total_committed_cents"] != 5488000, (
            "keying the overhead tier on the post-overhead total is the forbidden order"
        )
        assert_cents(after["available_cents"], 104365000, "available_cents")

    def test_crossing_the_first_ceiling_lowers_the_rate_and_the_grand_total(self, client):
        """A direct commitment of exactly 5,000,000 sits at or above the first ceiling and so
        takes 12 percent, giving a smaller grand total than the 4,900,000 commitment does.

        PRD: "When `direct_committed_cents` is strictly below 5,000,000 cents (50,000
        dollars) the overhead rate is 15 percent; when it is strictly below 20,000,000 cents
        (200,000 dollars) the rate is 12 percent; at or above that second ceiling the rate is
        10 percent."
        PRD: "**Step three** sets `total_committed_cents` to the sum of
        `direct_committed_cents` and `overhead_fee_cents`, computes the spending ceiling as
        the production's `budget_cents` multiplied by one plus its `contingency_pct` and
        rounded to a whole cent, and sets `available_cents` to that ceiling minus
        `total_committed_cents`."

        Design: Difficulty/combinatorial_formula/production_overhead_tier_pinned_to_direct_committed
        """
        partner = fx.approved_partner(
            client,
            legal_name="Northwind Animation",
            security_certification_level="TIER1",
            mfa_enforced=False,
            watermark_required=False,
        )

        below, below_layout = _show_with_layout_task(client, "Aurora Drift", "AD01")
        _accept_fee(client, below, partner, below_layout, "AD01-PKG-A", 4900000)
        below_after = fx.read_production(client, below["id"])
        assert_budget_position(below_after, 4900000, 735000)

        at_ceiling, at_ceiling_layout = _show_with_layout_task(
            client, "Aurora Drift II", "AD02"
        )
        _accept_fee(client, at_ceiling, partner, at_ceiling_layout, "AD02-PKG-A", 5000000)
        at_ceiling_after = fx.read_production(client, at_ceiling["id"])
        assert_budget_position(at_ceiling_after, 5000000, 600000)
        assert_cents(
            at_ceiling_after["total_committed_cents"], 5600000, "total_committed_cents"
        )
        assert_cents(at_ceiling_after["available_cents"], 104400000, "available_cents")

        assert (
            at_ceiling_after["total_committed_cents"]
            < below_after["total_committed_cents"]
        ), "the larger direct commitment carries the smaller grand total across the tier edge"
