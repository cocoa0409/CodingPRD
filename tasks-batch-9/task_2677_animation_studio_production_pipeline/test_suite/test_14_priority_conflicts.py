"""Priority-pair conflicts: state before capacity, and security before referential."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_CROSS_PRODUCTION_REFERENCE,
    ERR_RENDER_CAPACITY_EXCEEDED,
    ERR_SECURITY_TIER_INSUFFICIENT,
    ERR_TASK_STATE_INVALID,
)
from test_helpers.assertions import assert_cents, assert_two_decimal, assert_unchanged
from test_helpers.constants import (
    PACKAGE_DRAFT,
    TASK_IN_PROGRESS,
    TASK_NOT_STARTED,
)
from test_helpers.test_users import COORDINATOR_HEADERS, PRODUCTION_MANAGER_HEADERS

WINDOW_START = "2026-08-10T00:00:00Z"
WINDOW_END = "2026-08-10T06:00:00Z"


def _active_show(client, title, production_code):
    return fx.active_production(
        client,
        title=title,
        production_code=production_code,
        budget_cents=100000000,
        render_allowance_cents=5000000,
        contingency_pct=0.10,
        gate_types=["SCRIPT"],
    )


def _shot_with_layout(client, production_id, shot_code):
    shot = fx.create_shot(
        client,
        production_id,
        shot_code=shot_code,
        sequence_code="010",
        frame_count=120,
        budget_cents=1000000,
        planned_start_at="2026-08-01T00:00:00Z",
        planned_finish_at="2026-09-30T00:00:00Z",
    )
    return shot, fx.task_for_stage(client, shot["id"], "LAYOUT")


def _reservation(pool_id, task_id, version, cores):
    return {
        "render_pool_id": pool_id,
        "shot_stage_task_id": task_id,
        "priority": "NORMAL",
        "requested_cores": cores,
        "window_start": WINDOW_START,
        "window_end": WINDOW_END,
        "frame_count": 120,
        "seconds_per_frame": 50,
        "expected_render_pool_version": version,
    }


def _busy_farm_with_an_unstarted_task(client):
    """One 60-core reservation held against shot A, and shot B's LAYOUT never assigned."""
    production = _active_show(client, "Aurora Drift", "AD01")
    shot_a, task_a = _shot_with_layout(client, production["id"], "AD01_010_0010")
    shot_b, task_b = _shot_with_layout(client, production["id"], "AD01_010_0020")
    fx.assign_task(client, task_a["id"])
    pool = fx.create_pool(
        client, name="FARM-A", total_cores=100, cost_per_core_hour_cents=175
    )
    validate_success(
        client.create_render_job(
            _reservation(pool["id"], task_a["id"], pool["version"], 60),
            PRODUCTION_MANAGER_HEADERS,
        ),
        201,
    )
    return production, pool, task_a, task_b


class TestTaskStateBeforeRenderCapacity:
    def test_the_unstarted_task_is_reported_and_the_capacity_breach_is_not(self, client):
        """A reservation that is both aimed at a NOT_STARTED task and 65 cores too large
        reports the state error at priority 11, and the pool is left exactly as it was.

        PRD: "The thirty-five checks below are evaluated **strictly in the order listed**, and
        the first one that fails is the one reported; later checks never run."
        PRD: "Applies to every action endpoint, and also to `POST /studio/render-jobs`, where
        the referenced stage task must be in `IN_PROGRESS`, `SUBMITTED`, `IN_REVIEW` or
        `RETAKE`."
        PRD: "Admission is decided in three steps and is **all or nothing** — a request is
        never partially satisfied."

        Design: Difficulty/priority_pair_validation_conflict/task_state_error_precedes_render_capacity_error
        """
        _, pool, _, task_b = _busy_farm_with_an_unstarted_task(client)
        assert fx.read_task(client, task_b["id"])["status"] == TASK_NOT_STARTED
        before = fx.read_pool(client, pool["id"])
        assert before["version"] == 2
        assert_two_decimal(before["committed_core_hours"], 360.00, "committed_core_hours")

        validate_error(
            client.create_render_job(
                _reservation(pool["id"], task_b["id"], before["version"], 95),
                PRODUCTION_MANAGER_HEADERS,
            ),
            ERR_TASK_STATE_INVALID,
            409,
        )

        after = fx.read_pool(client, pool["id"])
        assert_unchanged(
            before,
            after,
            ["committed_core_hours", "reserved_job_count", "version"],
        )
        assert after["reserved_job_count"] == 1
        assert_two_decimal(after["committed_core_hours"], 360.00, "committed_core_hours")

    def test_each_of_the_two_rules_still_fires_when_it_stands_alone(self, client):
        """The state rule refuses a modest request against an unstarted task, and once that
        task is assigned the very same 95-core request is refused for capacity instead.

        PRD: "This ordering is normative, not descriptive — a request that is both
        unauthorized and referencing a missing row reports the authorization failure, and a
        request that would both exceed capacity and exceed the render allowance reports the
        capacity failure."
        PRD: "If not, and the request's `priority` is anything other than `CRITICAL`, the
        reservation is refused with `ERR_RENDER_CAPACITY_EXCEEDED`."

        Design: Difficulty/priority_pair_validation_conflict/task_state_error_precedes_render_capacity_error
        """
        _, pool, _, task_b = _busy_farm_with_an_unstarted_task(client)

        validate_error(
            client.create_render_job(
                _reservation(pool["id"], task_b["id"], 2, 5),
                PRODUCTION_MANAGER_HEADERS,
            ),
            ERR_TASK_STATE_INVALID,
            409,
        )

        assigned = fx.assign_task(client, task_b["id"])
        assert assigned["status"] == TASK_IN_PROGRESS

        validate_error(
            client.create_render_job(
                _reservation(pool["id"], task_b["id"], 2, 95),
                PRODUCTION_MANAGER_HEADERS,
            ),
            ERR_RENDER_CAPACITY_EXCEEDED,
            409,
        )

        modest = validate_success(
            client.create_render_job(
                _reservation(pool["id"], task_b["id"], 2, 30),
                PRODUCTION_MANAGER_HEADERS,
            ),
            201,
        )
        assert modest["requested_cores"] == 30, (
            "30 cores is exactly the NORMAL headroom allowance, so the same task now reserves"
        )
        assert fx.read_pool(client, pool["id"])["reserved_job_count"] == 2


def _two_shows_and_a_tier1_partner(client):
    """AD01 and AD02 both active with one LAYOUT task each, plus a TIER1 vendor."""
    home = _active_show(client, "Aurora Drift", "AD01")
    _, home_task = _shot_with_layout(client, home["id"], "AD01_010_0010")
    foreign = _active_show(client, "Aurora Drift II", "AD02")
    _, foreign_task = _shot_with_layout(client, foreign["id"], "AD02_010_0010")
    partner = fx.approved_partner(
        client,
        legal_name="Northwind Animation",
        security_certification_level="TIER1",
        mfa_enforced=False,
        watermark_required=False,
    )
    return home, home_task, foreign, foreign_task, partner


class TestSecurityTierBeforeCrossProduction:
    def test_the_under_certified_partner_is_reported_and_the_foreign_scope_is_not(self, client):
        """A TIER3 package aimed at a TIER1 vendor and scoped onto another show's task reports
        the security error at priority 14, leaving the package DRAFT with nothing committed.

        PRD: "The partner's `security_certification_level` is at least the package's
        `security_tier` on the ordered scale where `NONE` is lowest, then `TIER1`, then
        `TIER2`, then `TIER3` — otherwise `ERR_SECURITY_TIER_INSUFFICIENT` (422)."
        PRD: "A drafted package may legally hold a foreign scope; the check fires at issue
        time."
        PRD: "The stage tasks are **not** linked at draft time, and a draft may legally hold a
        scope that crosses production boundaries — that particular sin is caught later."

        Design: Difficulty/priority_pair_validation_conflict/partner_security_tier_error_precedes_cross_production_error
        """
        home, _, _, foreign_task, partner = _two_shows_and_a_tier1_partner(client)
        assert_two_decimal(
            fx.read_partner(client, partner["id"])["quality_score_rolling"],
            50.00,
            "quality_score_rolling",
        )

        package = fx.draft_package(
            client,
            home["id"],
            partner["id"],
            package_code="AD01-PKG-A",
            security_tier="TIER3",
            fee_cents=500000,
            stage_task_ids=[foreign_task["id"]],
            quality_min_score=50.00,
        )
        assert package["status"] == PACKAGE_DRAFT
        assert_cents(package["fee_committed_cents"], 0, "fee_committed_cents")

        validate_error(
            client.issue_package(package["id"], {}, COORDINATOR_HEADERS),
            ERR_SECURITY_TIER_INSUFFICIENT,
            422,
        )

        after = fx.read_package(client, package["id"])
        assert after["status"] == PACKAGE_DRAFT
        assert_cents(after["fee_committed_cents"], 0, "fee_committed_cents")
        assert_unchanged(package, after, ["status", "fee_committed_cents", "version"])
        assert fx.read_task(client, foreign_task["id"])["outsource_package_id"] is None
        assert_cents(
            fx.read_production(client, home["id"])["direct_committed_cents"],
            0,
            "direct_committed_cents",
        )

    def test_the_foreign_scope_surfaces_once_the_certification_is_high_enough(self, client):
        """A TIER3 vendor issued the same foreign-scoped package hits the referential rule at
        priority 21, while the TIER1 vendor issued a home-scoped TIER3 package still hits the
        security rule — both checks are live.

        PRD: "Cross-aggregate references stay inside one production: a director note's target
        task belongs to a shot of the session's production, a package's `stage_task_ids` all
        belong to shots of the package's production, an asset's `derived_from_asset_id` belongs
        to the same production, and a deliverable's `shot_id` belongs to its production —
        otherwise `ERR_CROSS_PRODUCTION_REFERENCE` (422)."
        PRD: "Every element of `stage_task_ids` must belong to a shot of this package's
        `production_id`, otherwise `ERR_CROSS_PRODUCTION_REFERENCE`."

        Design: Difficulty/priority_pair_validation_conflict/partner_security_tier_error_precedes_cross_production_error
        """
        home, home_task, _, foreign_task, weak_partner = _two_shows_and_a_tier1_partner(client)
        strong_partner = fx.approved_partner(
            client,
            legal_name="Southwind Animation",
            security_certification_level="TIER3",
            mfa_enforced=True,
            watermark_required=False,
        )

        cleared = fx.draft_package(
            client,
            home["id"],
            strong_partner["id"],
            package_code="AD01-PKG-B",
            security_tier="TIER3",
            fee_cents=500000,
            stage_task_ids=[foreign_task["id"]],
            quality_min_score=50.00,
        )
        validate_error(
            client.issue_package(cleared["id"], {}, COORDINATOR_HEADERS),
            ERR_CROSS_PRODUCTION_REFERENCE,
            422,
        )
        assert fx.read_package(client, cleared["id"])["status"] == PACKAGE_DRAFT

        home_scoped = fx.draft_package(
            client,
            home["id"],
            weak_partner["id"],
            package_code="AD01-PKG-C",
            security_tier="TIER3",
            fee_cents=500000,
            stage_task_ids=[home_task["id"]],
            quality_min_score=50.00,
        )
        validate_error(
            client.issue_package(home_scoped["id"], {}, COORDINATOR_HEADERS),
            ERR_SECURITY_TIER_INSUFFICIENT,
            422,
        )
        assert fx.read_package(client, home_scoped["id"])["status"] == PACKAGE_DRAFT
        assert fx.read_task(client, home_task["id"])["outsource_package_id"] is None
