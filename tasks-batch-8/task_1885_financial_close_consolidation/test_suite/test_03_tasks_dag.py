"""Close task DAG: dependency closure, cascade unblock, waive gates, dangling deps."""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, NON_EXISTENT_UUID,
    create_task_payload,
    set_clock, setup_open_period_with_entity, drive_entity_period_to_reconciled,
    CONTROLLER, PREPARER, PREPARER2, APPROVER,
    make_preparer_headers,
)
from test_helpers import api_client


def _create_task(period_id, entity_period_id, task_key, title, deps=None, assignee="prep-1", due=24):
    payload = {
        "entity_period_id": entity_period_id,
        "task_key": task_key,
        "title": title,
        "assignee_user_id": assignee,
        "due_offset_hours": due,
    }
    if deps is not None:
        payload["depends_on_task_ids"] = deps
    return get_success_data(api_client.create_task(period_id, payload, CONTROLLER))


class TestTaskDagCascade:
    def test_dependent_task_blocked_until_all_deps_done(self, api):
        """PRD §3.2: "A task's initial `status` is `READY` when it declares no
        dependencies and `BLOCKED` otherwise. From then on the system maintains the
        `BLOCKED` → `READY` frontier automatically: the instant every task named in
        `depends_on_task_ids` has reached `DONE` or `WAIVED`, the waiting task flips
        to `READY` without any client action."

        Design: Difficulty/non_linear_state_machine/close_task_dag_dependency_unblock_cascade
        """
        period, entity, ep = setup_open_period_with_entity()
        t1 = _create_task(period["id"], ep["id"], "SL_CUTOFF", "Cut subledgers")
        t2 = _create_task(period["id"], ep["id"], "ACCRUALS", "Book accruals")
        t3 = _create_task(period["id"], ep["id"], "CONSOLIDATE", "Consolidate",
                          deps=[t1["id"], t2["id"]], due=120)
        assert t3["status"] == "BLOCKED"

        # Complete only T1
        get_success_data(api_client.start_task(t1["id"], PREPARER))
        get_success_data(api_client.complete_task(t1["id"], PREPARER))
        mid = validate_success(api.get_task(t3["id"], PREPARER), 200)
        assert mid["status"] == "BLOCKED", "T3 must stay BLOCKED while T2 is still open"

    def test_dependent_task_unblocks_after_last_dependency(self, api):
        """PRD §3.2: "the instant every task named in `depends_on_task_ids` has
        reached `DONE` or `WAIVED`, the waiting task flips to `READY` without any
        client action."
        PRD §3.2: "A successful completion moves the task to `DONE`, stamps
        `completed_at` with the current instant (it remains null in every other
        state), recomputes `is_late`, appends a `TASK_DONE` event, and cascades
        down the graph: every dependent task whose dependencies are now entirely
        `DONE` or `WAIVED` flips from `BLOCKED` to `READY`, fanning out the next
        layer of work."

        Design: Difficulty/non_linear_state_machine/close_task_dag_dependency_unblock_cascade
        """
        period, entity, ep = setup_open_period_with_entity()
        t1 = _create_task(period["id"], ep["id"], "SL_CUTOFF", "Cut subledgers")
        t2 = _create_task(period["id"], ep["id"], "ACCRUALS", "Book accruals")
        t3 = _create_task(period["id"], ep["id"], "CONSOLIDATE", "Consolidate",
                          deps=[t1["id"], t2["id"]], due=120)

        for t in (t1, t2):
            get_success_data(api_client.start_task(t["id"], PREPARER))
            get_success_data(api_client.complete_task(t["id"], PREPARER))

        final = validate_success(api.get_task(t3["id"], PREPARER), 200)
        assert final["status"] == "READY"


class TestTaskCompleteCascadeFeedsReadiness:
    def test_completing_last_open_task_flips_dependent_to_ready(self, api):
        """PRD §3.2: "A successful completion moves the task to `DONE`, ... and
        cascades down the graph: every dependent task whose dependencies are now
        entirely `DONE` or `WAIVED` flips from `BLOCKED` to `READY`, fanning out
        the next layer of work."
        PRD §3.9: "When a `Preparer` advances an entity-period from `RECONCILED` to
        `READY_FOR_CONSOL`, three gates hold: every close task on the entity-period
        must be `DONE` or `WAIVED` (`ERR_OPEN_CLOSE_TASKS`); ..."

        Design: Difficulty/transitive_cascade/task_complete_to_dependent_ready_to_period_lock_eligibility
        """
        period, entity, ep = setup_open_period_with_entity()
        drive_entity_period_to_reconciled(period["id"], ep["id"], fx_currency="USD")
        t = _create_task(period["id"], ep["id"], "SL_CUTOFF", "Cut")
        d = _create_task(period["id"], ep["id"], "REVIEW", "Review", deps=[t["id"]], due=96)
        assert d["status"] == "BLOCKED"

        get_success_data(api_client.start_task(t["id"], PREPARER))
        get_success_data(api_client.complete_task(t["id"], PREPARER))

        d_after = validate_success(api.get_task(d["id"], PREPARER), 200)
        assert d_after["status"] == "READY"

    def test_readiness_gate_blocked_by_open_dependent_task(self, api):
        """PRD §3.9: "every close task on the entity-period must be `DONE` or
        `WAIVED` (`ERR_OPEN_CLOSE_TASKS`)".

        Design: Difficulty/transitive_cascade/task_complete_to_dependent_ready_to_period_lock_eligibility
        """
        period, entity, ep = setup_open_period_with_entity()
        drive_entity_period_to_reconciled(period["id"], ep["id"], fx_currency="USD")
        t = _create_task(period["id"], ep["id"], "SL_CUTOFF", "Cut")
        d = _create_task(period["id"], ep["id"], "REVIEW", "Review", deps=[t["id"]], due=96)
        get_success_data(api_client.start_task(t["id"], PREPARER))
        get_success_data(api_client.complete_task(t["id"], PREPARER))
        # D is READY but not yet DONE — readiness must fail on ERR_OPEN_CLOSE_TASKS
        res = api.mark_entity_period_ready(ep["id"], PREPARER)
        validate_error(res, ApiErrorId.ERR_OPEN_CLOSE_TASKS, expected_status=409)


class TestWaiveTask:
    def test_waive_critical_task_returns_task_not_waivable(self, api):
        """PRD §3.2: "A `READY` task may be moved to `WAIVED` only while the
        posture is `OPEN` or `REOPENED`, and only when its `task_key` is not one of
        the critical-path keys `TRANSLATE`, `ELIMINATE`, or `CONSOLIDATE` — waiving
        a critical task is rejected with `ERR_TASK_NOT_WAIVABLE`."

        Design: Corner/state_machines/waive_critical_task_returns_task_not_waivable
        """
        period, entity, ep = setup_open_period_with_entity()
        t = _create_task(period["id"], ep["id"], "TRANSLATE", "Run translation", due=72)
        assert t["status"] == "READY"
        res = api.waive_task(t["id"], CONTROLLER)
        validate_error(res, ApiErrorId.ERR_TASK_NOT_WAIVABLE, expected_status=409)
        after = validate_success(api.get_task(t["id"], CONTROLLER), 200)
        assert after["status"] == "READY"

    def test_preparer_cannot_waive_task(self, api):
        """PRD §2.1: "A `Controller` is the corporate controller: owner of the
        close calendar, close periods, legal-entity registrations, FX rates, locks
        and reopens, finalization, flux adjudication, and task waivers".
        PRD §2.1: "A request whose role is not permitted on the target endpoint is
        rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/preparer_cannot_waive_task
        """
        period, entity, ep = setup_open_period_with_entity()
        t = _create_task(period["id"], ep["id"], "SL_CUTOFF", "Cut subledgers")
        res = api.waive_task(t["id"], PREPARER)
        validate_error(res, ApiErrorId.ERR_FORBIDDEN, expected_status=403)


class TestTaskDependencyValidation:
    def test_task_dependency_dangling_reference_rejected(self, api):
        """PRD §3.2: "Dependencies must form a DAG: any `depends_on_task_ids` set
        that introduces a cycle into the period's task graph is rejected with
        `ERR_TASK_DEPENDENCY_CYCLE`."
        PRD §2.9: "the request is rejected with `ERR_NOT_FOUND` (HTTP 404) at the
        first identifier that does not exist or does not belong to the declared
        parent."

        Design: Corner/state_machines/task_dependency_dangling_reference_rejected
        """
        period, entity, ep = setup_open_period_with_entity()
        t1 = _create_task(period["id"], ep["id"], "SL_CUTOFF", "T1")
        res = api.create_task(period["id"],
                               {"entity_period_id": ep["id"],
                                "task_key": "ACCRUALS",
                                "title": "T2 dangling dep",
                                "depends_on_task_ids": [NON_EXISTENT_UUID],
                                "assignee_user_id": "prep-1",
                                "due_offset_hours": 48},
                               CONTROLLER)
        validate_error(res, ApiErrorId.ERR_NOT_FOUND, expected_status=404)
        # t1 still exists
        fetched = validate_success(api.get_task(t1["id"], CONTROLLER), 200)
        assert fetched["id"] == t1["id"]
