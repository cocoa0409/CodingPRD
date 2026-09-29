"""The role model from four angles: the exclusive operations that answer 403 before any
state rule runs, the one mutating capability two roles share, the reads every role holds,
and the two duty checks that compare the acting identity rather than the role.
"""

from __future__ import annotations

import pytest

from test_helpers import (
    ALL_ROLES,
    ApiClient,
    ApiErrorId,
    BoardLineStatus,
    DispositionAction,
    LoadOrderStatus,
    OutageStatus,
    ProductionPosture,
    QualityState,
    Role,
    RunStatus,
    SaleableGrade,
    assert_plant,
    factories,
    fixtures,
    test_users,
    validate_error,
    validate_success,
)


def _line_status(api: ApiClient, line_id: str) -> str:
    return validate_success(api.get_board_line(line_id, test_users.PLANT_ADMIN))["status"]


class TestExclusiveOperationsRejectOtherRoles:
    """Four calls that each had a state error waiting behind the role check, and the role
    check answers first in every one."""

    def test_four_cross_role_attempts_all_answer_unauthorized(self, api: ApiClient) -> None:
        """A held run, a proposed outage and a loaded trailer are all left exactly as they were.

        PRD: "A request that is authenticated but whose role is not listed for the target endpoint in §4 is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

        Design: Corner/rbac/each_exclusive_operation_rejects_every_other_role
        """
        world = fixtures.completed_run(api)
        world.load = fixtures.stage_load(api, world, bundles_count=5)
        fixtures.record_load(api, world.load_id, 5)
        fixtures.record_passing_specimens(api, world.run_id, 2)
        fixtures.record_specimen(
            api, world.run_id, factories.board_test_payload(3, 16.0, 70.0, 38.0, 105.0, 0.58)
        )
        world.run = fixtures.evaluate(api, world.run_id)
        assert world.run["quality_state"] == QualityState.HELD.value
        outage = fixtures.propose_outage(api, world.line_id)

        specimen = validate_error(
            api.create_board_test(
                world.run_id,
                factories.board_test_payload(4, 17.0, 82.0, 39.0, 110.0, 0.55),
                test_users.PRODUCTION_SCHEDULER,
            ),
            ApiErrorId.UNAUTHORIZED.value,
            403,
        )
        disposition = validate_error(
            api.disposition_quality(
                world.run_id,
                factories.disposition_payload(
                    action=DispositionAction.DOWNGRADE.value,
                    disposition_note="inspector overreach",
                ),
                test_users.QUALITY_INSPECTOR_2,
            ),
            ApiErrorId.UNAUTHORIZED.value,
            403,
        )
        approve = validate_error(
            api.approve_outage(outage["id"], {}, test_users.MAINTENANCE_PLANNER),
            ApiErrorId.UNAUTHORIZED.value,
            403,
        )
        ship = validate_error(
            api.ship_load_order(
                world.load_id, factories.ship_payload(False), test_users.PRODUCTION_SCHEDULER
            ),
            ApiErrorId.UNAUTHORIZED.value,
            403,
        )

        assert approve["error_id"] != ApiErrorId.SEGREGATION_OF_DUTIES.value, (
            "the role check precedes the duty check, even though the planner proposed this outage"
        )
        assert ship["error_id"] != ApiErrorId.RUN_QUALITY_NOT_RELEASED.value, (
            "the role check precedes the source run's quality state"
        )
        assert specimen["error_id"] == disposition["error_id"]

        run = world.read_run()
        assert run["specimen_count"] == 3, "the refused specimen was not appended"
        assert run["quality_state"] == QualityState.HELD.value
        assert fixtures.read_outage(api, outage["id"])["status"] == OutageStatus.PROPOSED.value
        assert world.read_load()["status"] == LoadOrderStatus.LOADED.value


class TestSharedCancelCapability:
    """Two runs, two roles, one identical release of committed stucco."""

    def test_the_scheduler_and_the_plant_manager_both_cancel_and_both_release(
        self, api: ApiClient
    ) -> None:
        """135.000 committed tons return to the silo one 67.500-ton reservation at a time.

        PRD: "It is the one mutating capability open to two roles, either a `ProductionScheduler` or a `PlantManager`, and it records a free-text `cancel_reason`."

        Design: Corner/rbac/run_cancel_is_shared_between_scheduler_and_plant_manager
        """
        world = fixtures.scheduled_run(api, requested_planned_msf=100.0)
        run_b = fixtures.draft_run(
            api,
            world,
            window_start="2026-08-04T06:00:00Z",
            window_end="2026-08-04T10:00:00Z",
            requested_planned_msf=100.0,
        )
        run_b = fixtures.schedule(api, run_b["id"], world.plant_id)
        assert run_b["stucco_reserved_tons"] == pytest.approx(67.500, abs=0.0005)

        before = world.read_plant()
        assert before["stucco_committed_tons"] == pytest.approx(135.000, abs=0.0005)
        assert before["stucco_available_tons"] == pytest.approx(69.530, abs=0.0005)

        by_scheduler = validate_success(
            api.cancel_run(
                world.run_id,
                factories.cancel_run_payload(cancel_reason="cancelled by the scheduler"),
                test_users.PRODUCTION_SCHEDULER,
            ),
            200,
        )
        by_manager = validate_success(
            api.cancel_run(
                run_b["id"],
                factories.cancel_run_payload(cancel_reason="cancelled by the plant manager"),
                test_users.PLANT_MANAGER,
            ),
            200,
        )

        assert by_scheduler["status"] == RunStatus.CANCELLED.value
        assert by_scheduler["cancel_reason"] == "cancelled by the scheduler"
        assert by_manager["status"] == RunStatus.CANCELLED.value
        assert by_manager["cancel_reason"] == "cancelled by the plant manager"
        for cancelled in (by_scheduler, by_manager):
            assert cancelled["stucco_reserved_tons"] == pytest.approx(0.000, abs=0.0005)

        plant = world.read_plant()
        assert plant["stucco_committed_tons"] == pytest.approx(0.000, abs=0.0005)
        assert plant["stucco_available_tons"] == pytest.approx(204.530, abs=0.0005)
        assert plant["production_posture"] == ProductionPosture.OPEN.value
        assert _line_status(api, world.line_id) == BoardLineStatus.AVAILABLE.value


class TestReadsAreOpenToEveryRole:
    """Seven roles, one plant, seven identical bodies and no version movement."""

    def test_all_seven_roles_read_the_same_plant_body(self, api: ApiClient) -> None:
        """Read access is never the axis this role model segregates.

        PRD: "Cancelling a production run is the one mutating capability shared by two roles: both `ProductionScheduler` and `PlantManager` may perform it. Every read endpoint is open to all seven roles."

        Design: Corner/rbac/every_role_may_read_but_only_reads
        """
        plant = fixtures.create_plant(api)
        assert len(ALL_ROLES) == 7

        bodies = [
            validate_success(api.get_plant(plant["id"], test_users.HEADERS_BY_ROLE[role]), 200)
            for role in ALL_ROLES
        ]

        for body in bodies:
            assert_plant(body)
            assert body["code"] == "GYP-1"
            assert body["production_posture"] == ProductionPosture.RESTRICTED.value
            assert body["version"] == 1
            assert body == bodies[0], "every role sees the same projection"

        assert fixtures.read_plant(api, plant["id"])["version"] == 1, "no read was a mutation"


class TestOutageDutySegregation:
    """The comparison is against `proposed_by_user_id`, so the role is not what saves the
    proposer."""

    def test_the_proposer_wearing_the_manager_role_is_still_refused(
        self, api: ApiClient
    ) -> None:
        """A different identity in the same role approves the very same outage immediately after.

        PRD: "A maintenance outage may not be approved by the operator who proposed it: the `X-User-ID` presented at approval is compared with `proposed_by_user_id`, and equality is rejected with `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/rbac/outage_proposer_may_not_approve_its_own_outage
        """
        world = fixtures.baseline(api)
        outage = fixtures.propose_outage(api, world.line_id)
        assert outage["proposed_by_user_id"] == test_users.USER_PLANNER
        assert outage["seasonality_index"] == pytest.approx(0.90, abs=0.005)

        validate_error(
            api.approve_outage(
                outage["id"],
                {},
                test_users.headers_for(Role.PLANT_MANAGER.value, test_users.USER_PLANNER),
            ),
            ApiErrorId.SEGREGATION_OF_DUTIES.value,
            403,
        )

        refused = fixtures.read_outage(api, outage["id"])
        assert refused["status"] == OutageStatus.PROPOSED.value
        assert refused["approved_by_user_id"] is None
        assert _line_status(api, world.line_id) == BoardLineStatus.AVAILABLE.value, (
            "the line follows the approval, and no approval has happened yet"
        )

        approved = validate_success(
            api.approve_outage(outage["id"], {}, test_users.PLANT_MANAGER), 200
        )
        assert approved["status"] == OutageStatus.APPROVED.value
        assert approved["approved_by_user_id"] == test_users.USER_MANAGER
        assert _line_status(api, world.line_id) == BoardLineStatus.MAINTENANCE_SCHEDULED.value


class TestDispositionDutySegregation:
    """The comparison is against `last_failing_test_recorded_by_user_id`, and it applies to
    the downgrade branch as much as to the release branch."""

    def test_the_inspector_behind_the_hold_cannot_downgrade_it(self, api: ApiClient) -> None:
        """The same DOWNGRADE payload is refused for one identity and accepted for another.

        PRD: "Likewise, a held production run may not be dispositioned by the inspector who recorded the specimen that caused the hold: the `X-User-ID` presented at disposition is compared with `last_failing_test_recorded_by_user_id`, and equality is rejected with the same code, on all three disposition branches without exception."

        Design: Corner/rbac/inspector_who_recorded_the_failing_specimen_may_not_disposition_the_hold
        """
        world = fixtures.held_run(api)
        held = world.read_run()
        assert held["last_failing_test_recorded_by_user_id"] == test_users.USER_INSPECTOR_1
        assert world.read_plant()["held_run_count"] == 1

        validate_error(
            api.disposition_quality(
                world.run_id,
                factories.disposition_payload(
                    action=DispositionAction.DOWNGRADE.value, disposition_note="self review"
                ),
                test_users.headers_for(Role.QUALITY_MANAGER.value, test_users.USER_INSPECTOR_1),
            ),
            ApiErrorId.SEGREGATION_OF_DUTIES.value,
            403,
        )
        assert world.read_run()["quality_state"] == QualityState.HELD.value

        dispositioned = validate_success(
            api.disposition_quality(
                world.run_id,
                factories.disposition_payload(
                    action=DispositionAction.DOWNGRADE.value,
                    disposition_note="independent review",
                ),
                test_users.QUALITY_MANAGER,
            ),
            200,
        )
        assert dispositioned["quality_state"] == QualityState.DOWNGRADED.value
        assert dispositioned["saleable_grade"] == SaleableGrade.SECONDS.value
        assert world.read_plant()["held_run_count"] == 0
