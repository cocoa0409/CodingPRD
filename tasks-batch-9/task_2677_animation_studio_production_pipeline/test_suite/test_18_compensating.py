"""Compensating invariants: render capacity restored, and a budget position rewound."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_PACKAGE_STATE_INVALID,
    ERR_RENDER_JOB_STATE_INVALID,
)
from test_helpers.assertions import (
    assert_budget_position,
    assert_cents,
    assert_two_decimal,
)
from test_helpers.constants import (
    JOB_CANCELLED,
    JOB_RESERVED,
    PACKAGE_DELIVERED,
    PACKAGE_RECALLED,
    SHOT_IN_PRODUCTION,
    TASK_APPROVED,
    TASK_RETAKE,
)
from test_helpers.test_users import (
    COORDINATOR_HEADERS,
    PRODUCTION_MANAGER_HEADERS,
    make_partner_representative_headers,
)

JOB_WINDOW_START = "2026-08-10T00:00:00Z"
JOB_WINDOW_END = "2026-08-10T06:00:00Z"


def _active_show(client):
    return fx.active_production(
        client,
        title="Aurora Drift",
        production_code="AD01",
        budget_cents=100000000,
        render_allowance_cents=5000000,
        master_color_space="ACEScg",
        contingency_pct=0.10,
        gate_types=["SCRIPT"],
    )


def _shot_with_assigned_layout(client, production_id):
    shot = fx.create_shot(
        client,
        production_id,
        shot_code="AD01_010_0010",
        sequence_code="010",
        frame_count=120,
        budget_cents=1000000,
        planned_start_at="2026-08-01T00:00:00Z",
        planned_finish_at="2026-09-30T00:00:00Z",
    )
    layout = fx.task_for_stage(client, shot["id"], "LAYOUT")
    fx.assign_task(client, layout["id"])
    return shot, layout


def _sixty_core_reservation(client):
    """A fresh farm carrying one 60-core six-hour reservation against AD01's LAYOUT."""
    production = _active_show(client)
    shot, layout = _shot_with_assigned_layout(client, production["id"])
    pool = fx.create_pool(
        client, name="FARM-A", total_cores=100, cost_per_core_hour_cents=175
    )
    job = validate_success(
        client.create_render_job(
            {
                "render_pool_id": pool["id"],
                "shot_stage_task_id": layout["id"],
                "priority": "NORMAL",
                "requested_cores": 60,
                "window_start": JOB_WINDOW_START,
                "window_end": JOB_WINDOW_END,
                "frame_count": 120,
                "seconds_per_frame": 50,
                "expected_render_pool_version": pool["version"],
            },
            PRODUCTION_MANAGER_HEADERS,
        ),
        201,
    )
    return production, shot, pool, job


class TestRenderJobCancelCompensation:
    def test_cancelling_a_reservation_returns_every_figure_to_its_prior_value(
        self, client
    ):
        """A 60-core six-hour reservation loads 360.00 core-hours onto the pool and 17520
        cents onto the shot and the show; cancelling it puts all four back to zero while the
        job keeps its historical estimate and a null final cost.

        PRD: "A new pool opens with `committed_core_hours` of 0.00, a `reserved_job_count`
        of 0, and a `version` of 1."
        PRD: "It moves the job `RESERVED → CANCELLED`, leaves `final_cost_cents` null and
        `frames_completed` at 0, adds 1 to the pool's `version`, and restores the pool's
        `committed_core_hours` and `reserved_job_count`, the shot's
        `render_cost_committed_cents` and the production's `render_committed_cents` to
        **exactly** their pre-reservation values."
        PRD: "Cancelled and preempted jobs are never priced."

        Design: Difficulty/compensating_invariant/render_job_cancel_restores_pool_committed_core_hours
        """
        production, shot, pool, job = _sixty_core_reservation(client)
        assert_two_decimal(pool["committed_core_hours"], 0.00, "pool committed_core_hours")
        assert pool["reserved_job_count"] == 0

        assert job["status"] == JOB_RESERVED
        assert_cents(job["estimated_cost_cents"], 17520, "estimated_cost_cents")
        assert_cents(job["cost_per_frame_cents"], 146, "cost_per_frame_cents")
        assert_two_decimal(job["committed_core_hours"], 360.00, "committed_core_hours")

        loaded_pool = fx.read_pool(client, pool["id"])
        assert_two_decimal(
            loaded_pool["committed_core_hours"], 360.00, "pool committed_core_hours"
        )
        assert loaded_pool["reserved_job_count"] == 1
        assert loaded_pool["version"] > pool["version"]
        assert_cents(
            fx.read_shot(client, shot["id"])["render_cost_committed_cents"],
            17520,
            "render_cost_committed_cents",
        )
        assert_cents(
            fx.read_production(client, production["id"])["render_committed_cents"],
            17520,
            "render_committed_cents",
        )

        released = validate_success(
            client.cancel_render_job(job["id"], {}, PRODUCTION_MANAGER_HEADERS)
        )
        assert released["status"] == JOB_CANCELLED
        assert released["final_cost_cents"] is None, "a cancelled job is never priced"
        assert released["frames_completed"] == 0
        assert_cents(
            released["estimated_cost_cents"],
            17520,
            "estimated_cost_cents after the cancel",
        )

        restored_pool = fx.read_pool(client, pool["id"])
        assert_two_decimal(
            restored_pool["committed_core_hours"], 0.00, "pool committed_core_hours"
        )
        assert restored_pool["reserved_job_count"] == 0
        assert restored_pool["version"] > loaded_pool["version"], (
            "compensation still counts as a write on the pool"
        )

        restored_shot = fx.read_shot(client, shot["id"])
        assert_cents(
            restored_shot["render_cost_committed_cents"], 0, "render_cost_committed_cents"
        )
        assert_cents(restored_shot["render_cost_actual_cents"], 0, "render_cost_actual_cents")
        restored_production = fx.read_production(client, production["id"])
        assert_cents(restored_production["render_committed_cents"], 0, "render_committed_cents")
        assert_cents(restored_production["render_actual_cents"], 0, "render_actual_cents")

    def test_a_second_cancel_is_refused_and_cannot_refund_twice(self, client):
        """Cancelling is legal only from RESERVED, so the second attempt on the same job is
        a 409 that leaves the already-restored ledger untouched.

        PRD: "Releasing a reservation before it runs is the compensating operation and is
        legal only from `RESERVED`."
        PRD: "The target row's own state field permits the requested transition."
        PRD: "The error names the target: `ERR_GATE_STATE_INVALID`,
        `ERR_ASSET_BUILD_STATE_INVALID`, `ERR_ASSET_LIBRARY_STATE_INVALID`,
        `ERR_TASK_STATE_INVALID`, `ERR_SESSION_STATE_INVALID`, `ERR_NOTE_STATE_INVALID`,
        `ERR_RENDER_JOB_STATE_INVALID`, `ERR_PARTNER_STATE_INVALID`,
        `ERR_PACKAGE_STATE_INVALID` or `ERR_DELIVERABLE_STATE_INVALID`, each HTTP 409."

        Design: Difficulty/compensating_invariant/render_job_cancel_restores_pool_committed_core_hours
        """
        production, shot, pool, job = _sixty_core_reservation(client)
        validate_success(client.cancel_render_job(job["id"], {}, PRODUCTION_MANAGER_HEADERS))
        after_first = fx.read_pool(client, pool["id"])

        validate_error(
            client.cancel_render_job(job["id"], {}, PRODUCTION_MANAGER_HEADERS),
            ERR_RENDER_JOB_STATE_INVALID,
        )

        unchanged_pool = fx.read_pool(client, pool["id"])
        assert_two_decimal(
            unchanged_pool["committed_core_hours"], 0.00, "pool committed_core_hours"
        )
        assert unchanged_pool["reserved_job_count"] == 0
        assert unchanged_pool["version"] == after_first["version"], (
            "a refused cancel is not a write"
        )
        assert_cents(
            fx.read_shot(client, shot["id"])["render_cost_committed_cents"],
            0,
            "render_cost_committed_cents",
        )
        assert_cents(
            fx.read_production(client, production["id"])["render_committed_cents"],
            0,
            "render_committed_cents",
        )
        assert fx.read_job(client, job["id"])["status"] == JOB_CANCELLED


def _delivered_and_approved_package(client):
    """AD01 carrying a 4,900,000-cent TIER1 package delivered and approved on LAYOUT."""
    production = _active_show(client)
    opening_available = production["available_cents"]
    shot, layout = _shot_with_assigned_layout(client, production["id"])
    partner = fx.approved_partner(
        client,
        legal_name="Northwind Animation",
        security_certification_level="TIER1",
        mfa_enforced=False,
        watermark_required=False,
    )
    package = fx.draft_package(
        client,
        production["id"],
        partner["id"],
        package_code="AD01-PKG-A",
        security_tier="TIER1",
        fee_cents=4900000,
        stage_task_ids=[layout["id"]],
        quality_min_score=50.00,
    )
    fx.issue_package(client, package["id"])
    accepted = fx.accept_package(client, package["id"], partner["id"])
    delivered = fx.deliver_package(
        client, package["id"], partner["id"], watermark_applied=False
    )
    approved = fx.approve_task(client, layout["id"])
    return {
        "production": production,
        "opening_available": opening_available,
        "shot": shot,
        "layout": layout,
        "partner": partner,
        "package": package,
        "accepted": accepted,
        "delivered": delivered,
        "approved": approved,
    }


def _suspend(client, partner_id):
    return validate_success(
        client.set_partner_status(
            partner_id, f.partner_status_payload("SUSPENDED"), COORDINATOR_HEADERS
        )
    )


def _reinstate(client, partner_id):
    return validate_success(
        client.set_partner_status(
            partner_id, f.partner_status_payload("APPROVED"), COORDINATOR_HEADERS
        )
    )


class TestPackageRecallCompensation:
    def test_suspending_the_partner_rewinds_the_fee_the_overhead_and_the_earned_value(
        self, client
    ):
        """A delivered and approved 4,900,000-cent package holds the show at 5,635,000
        committed with 104,365,000 available and 100000 of BCWP; suspending the vendor
        recalls the package, zeroes its fee and returns the show to 110,000,000 available
        with no earned credit at all.

        PRD: "On suspension, every package of that partner whose `status` is `ISSUED`,
        `IN_PROGRESS` or `DELIVERED` is processed in `created_at` ascending order and moved
        to `RECALLED`."
        PRD: "Each recalled package has its `fee_committed_cents` reset to 0, which
        recomputes the owning production's `direct_committed_cents`, `overhead_fee_cents`,
        `total_committed_cents` and `available_cents` — the show drops back to exactly the
        position it held before the partner accepted the work."
        PRD: "Every stage task whose `outsource_package_id` names one of those recalled
        packages has that link cleared, and those tasks whose `status` is `SUBMITTED`,
        `IN_REVIEW` or `APPROVED` are additionally driven to `RETAKE` with `revision_count`
        increased by 1; tasks that are `NOT_STARTED` or `IN_PROGRESS` are left in place and
        are not retaken, though their `outsource_package_id` is still cleared."
        PRD: "Affected shots recompute `retake_count`, `escalation_flag` and `status`, and
        the production recomputes `total_retake_count`, `at_risk_shot_count` and
        `completed_shot_count`."

        Design: Difficulty/compensating_invariant/package_recall_restores_production_committed_cents
        """
        state = _delivered_and_approved_package(client)
        assert_cents(state["opening_available"], 110000000, "opening available_cents")
        assert_cents(state["accepted"]["fee_committed_cents"], 4900000, "fee_committed_cents")
        assert state["delivered"]["status"] == PACKAGE_DELIVERED
        assert state["delivered"]["delivery_count"] == 1
        assert state["approved"]["status"] == TASK_APPROVED
        assert state["approved"]["outsource_package_id"] == state["package"]["id"]

        committed = fx.read_production(client, state["production"]["id"])
        assert_budget_position(committed, 4900000, 735000)
        assert_cents(committed["total_committed_cents"], 5635000, "total_committed_cents")
        assert_cents(committed["available_cents"], 104365000, "available_cents")
        assert_cents(committed["bcwp_cents"], 100000, "bcwp_cents")

        suspended = _suspend(client, state["partner"]["id"])
        assert suspended["status"] == "SUSPENDED"

        recalled = fx.read_package(client, state["package"]["id"])
        assert recalled["status"] == PACKAGE_RECALLED
        assert_cents(recalled["fee_committed_cents"], 0, "fee_committed_cents")

        retaken = fx.read_task(client, state["layout"]["id"])
        assert retaken["status"] == TASK_RETAKE
        assert retaken["outsource_package_id"] is None, "the recalled link is cleared"
        assert retaken["revision_count"] == 1

        rewound_shot = fx.read_shot(client, state["shot"]["id"])
        assert_cents(rewound_shot["bcwp_cents"], 0, "Shot.bcwp_cents")
        assert rewound_shot["status"] == SHOT_IN_PRODUCTION
        assert rewound_shot["retake_count"] == 1

        rewound = fx.read_production(client, state["production"]["id"])
        assert_budget_position(rewound, 0, 0)
        assert_cents(rewound["total_committed_cents"], 0, "total_committed_cents")
        assert_cents(rewound["available_cents"], 110000000, "available_cents")
        assert_cents(rewound["bcwp_cents"], 0, "Production.bcwp_cents")
        assert rewound["total_retake_count"] == 1

    def test_reinstatement_recommits_nothing_and_the_recalled_package_cannot_redeliver(
        self, client
    ):
        """Bringing the vendor back to APPROVED leaves the package RECALLED with a zero fee
        and the show at its full 110,000,000, and a delivery attempt on the recalled package
        is refused outright.

        PRD: "`SUSPENDED → APPROVED` is reinstatement."
        PRD: "Reinstating the partner afterwards restores none of it: recalled packages stay
        `RECALLED`, issued retakes are not reverted, and the only effect is that new packages
        may be issued again."
        PRD: "It is legal from two states: `IN_PROGRESS → DELIVERED` for a first delivery,
        and `QC_FAILED → DELIVERED` for a redelivery after a failed QC; from anywhere else it
        is `ERR_PACKAGE_STATE_INVALID`."

        Design: Difficulty/compensating_invariant/package_recall_restores_production_committed_cents
        """
        state = _delivered_and_approved_package(client)
        _suspend(client, state["partner"]["id"])

        reinstated = _reinstate(client, state["partner"]["id"])
        assert reinstated["status"] == "APPROVED"

        still_recalled = fx.read_package(client, state["package"]["id"])
        assert still_recalled["status"] == PACKAGE_RECALLED
        assert_cents(still_recalled["fee_committed_cents"], 0, "fee_committed_cents")
        assert fx.read_task(client, state["layout"]["id"])["status"] == TASK_RETAKE, (
            "issued retakes are not reverted by reinstatement"
        )

        after = fx.read_production(client, state["production"]["id"])
        assert_cents(after["available_cents"], 110000000, "available_cents")
        assert_cents(after["total_committed_cents"], 0, "total_committed_cents")

        validate_error(
            client.deliver_package(
                state["package"]["id"],
                f.package_deliver_payload(False),
                make_partner_representative_headers(state["partner"]["id"]),
            ),
            ERR_PACKAGE_STATE_INVALID,
        )
        assert_cents(
            fx.read_production(client, state["production"]["id"])["available_cents"],
            110000000,
            "available_cents",
        )
