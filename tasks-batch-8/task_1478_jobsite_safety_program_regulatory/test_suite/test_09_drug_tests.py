"""Drug-free workplace program: the 32-hour post-incident window (both bounds
inclusive, rejection outside), and the POSITIVE/NEGATIVE result fork with its
three-link cascade (PRD §3.8, §2.7)."""
from test_helpers import (
    ApiErrorId, api_client,
    validate_error, validate_success, validate_paginated,
    create_project, create_project_with_active_plan, create_worker,
    create_cleared_worker, create_incident, create_drug_test,
    record_drug_result, get_worker, get_permit, get_jha, get_project,
    setup_jobsite_with_issued_permit, set_clock,
    make_safety_manager_headers,
)

SM = make_safety_manager_headers()


def _project_worker_incident(name="Site", hours=70000,
                             occurred_at="2026-08-02T08:00:00Z"):
    set_clock("2026-08-01T08:00:00Z")
    project = create_project(name=name, annual_hours_worked=hours)
    worker = create_worker(project["id"], full_name="H Ibarra")
    incident = create_incident(
        project["id"], worker_id=worker["id"], incident_type="INJURY",
        severity="SERIOUS", occurred_at=occurred_at, work_related=True,
        description="ladder fall",
    )
    return project, worker, incident


class TestPostIncidentWindow:

    def test_collection_exactly_at_32h_is_compliant(self, api):
        """PRD §3.8: "The window opens at the incident's `occurred_at` and closes
        32 hours later, both bounds inclusive: a collection exactly at the
        incident moment or exactly at the 32-hour mark is compliant."
        PRD §3.8: "consequently the computed `window_compliant` field is always
        true on persisted `POST_INCIDENT` records and remains null on records of
        the other two test types."

        Design: Difficulty/boundary_precision_check/drug_test_window_exactly_32h_compliant
        """
        _project, worker, incident = _project_worker_incident("Fremont Cut")
        # occurred 2026-08-02T08:00:00Z + 32h == 2026-08-03T16:00:00Z exactly.
        resp = api.create_drug_test(
            {"worker_id": worker["id"], "test_type": "POST_INCIDENT",
             "incident_id": incident["id"],
             "collected_at": "2026-08-03T16:00:00Z"}, SM,
        )
        record = validate_success(resp, 201)
        assert record["window_compliant"] is True, (
            f"exact-32h collection is compliant: {record['window_compliant']}"
        )

    def test_collection_exactly_at_incident_moment_is_compliant(self, api):
        """PRD §3.8: "The window opens at the incident's `occurred_at` and closes
        32 hours later, both bounds inclusive: a collection exactly at the
        incident moment or exactly at the 32-hour mark is compliant."

        Design: Difficulty/boundary_precision_check/drug_test_window_exactly_32h_compliant
        """
        _project, worker, incident = _project_worker_incident("Fremont Cut 2")
        resp = api.create_drug_test(
            {"worker_id": worker["id"], "test_type": "POST_INCIDENT",
             "incident_id": incident["id"],
             "collected_at": "2026-08-02T08:00:00Z"}, SM,
        )
        record = validate_success(resp, 201)
        assert record["window_compliant"] is True

    def test_collection_past_32h_rejected_and_not_persisted(self, api):
        """PRD §3.8: "A collection outside the window is rejected with
        `ERR_DRUG_TEST_WINDOW_VIOLATION` (HTTP 422) and the record is never
        persisted"

        Design: Corner/errors/drug_test_window_past_32h_rejected
        """
        _project, worker, incident = _project_worker_incident("Riverton", 27000)
        # occurred 2026-08-02T08:00:00Z; +33h == 2026-08-03T17:00:00Z is outside.
        resp = api.create_drug_test(
            {"worker_id": worker["id"], "test_type": "POST_INCIDENT",
             "incident_id": incident["id"],
             "collected_at": "2026-08-03T17:00:00Z"}, SM,
        )
        validate_error(resp, ApiErrorId.ERR_DRUG_TEST_WINDOW_VIOLATION)

        data, meta = validate_paginated(
            api.list_drug_tests(SM, params={"incident_id": incident["id"]})
        )
        assert meta["total_count"] == 0, (
            f"rejected collection must not persist a record, got {meta['total_count']}"
        )
        assert data == []


class TestResultFork:

    def _two_cleared_workers(self, name="Harbor Steps"):
        set_clock("2026-08-01T08:00:00Z")
        project, _plan = create_project_with_active_plan(name=name,
                                                         annual_hours_worked=90000)
        w1 = create_cleared_worker(project["id"], full_name="C Diaz")
        w2 = create_cleared_worker(project["id"], full_name="D Novak")
        return project, w1, w2

    def test_positive_result_suspends_worker(self, api):
        """PRD §3.8: "A positive result fires the full §2.7 cascade from link 1:
        the worker is suspended with `suspension_reason` `POSITIVE_DRUG_TEST`
        (from `ORIENTED` or `CLEARED`), every issued permit listing the worker is
        suspended with reason `CREW_MEMBER_SUSPENDED`, and each affected JHA
        returns to `RE_REVIEW_REQUIRED`."

        Design: Difficulty/non_linear_state_machine/drug_test_branching_fork_divergent_effects
        """
        _project, w1, _w2 = self._two_cleared_workers()
        record = create_drug_test(w1["id"], test_type="RANDOM",
                                  collected_at="2026-08-05T09:00:00Z")
        resulted = record_drug_result(record["id"], "POSITIVE")
        assert resulted["status"] == "POSITIVE"

        worker = get_worker(w1["id"])
        assert worker["status"] == "SUSPENDED", (
            f"POSITIVE branch must suspend the worker, got {worker['status']}"
        )
        assert worker["suspension_reason"] == "POSITIVE_DRUG_TEST"

    def test_negative_result_leaves_worker_cleared(self, api):
        """PRD §3.8: "A negative result closes the matter."
        PRD §3.8: "A record begins `PENDING_RESULT`, and recording the laboratory
        outcome with `result` moves it to `NEGATIVE` or `POSITIVE`"

        Design: Difficulty/non_linear_state_machine/drug_test_branching_fork_divergent_effects
        """
        _project, _w1, w2 = self._two_cleared_workers("Harbor Steps 2")
        record = create_drug_test(w2["id"], test_type="RANDOM",
                                  collected_at="2026-08-05T09:30:00Z")
        resulted = record_drug_result(record["id"], "NEGATIVE")
        assert resulted["status"] == "NEGATIVE"

        worker = get_worker(w2["id"])
        assert worker["status"] == "CLEARED", (
            f"NEGATIVE branch has no worker side effect, got {worker['status']}"
        )


class TestPositiveResultCascade:

    def _issued_permit_jobsite(self, name):
        return setup_jobsite_with_issued_permit(
            project_name=name, annual_hours=60000,
            permit_type="FALL_PROTECTION",
        )

    def test_positive_result_suspends_worker_and_permits(self, api):
        """PRD §3.8: "A positive result fires the full §2.7 cascade from link 1:
        the worker is suspended with `suspension_reason` `POSITIVE_DRUG_TEST`
        (from `ORIENTED` or `CLEARED`), every issued permit listing the worker is
        suspended with reason `CREW_MEMBER_SUSPENDED`, and each affected JHA
        returns to `RE_REVIEW_REQUIRED`."
        PRD §2.7: "Link 2 is the permit effect: every permit in status `ISSUED`
        whose `authorized_worker_ids` contains that worker is suspended, with
        `suspension_reason` recording the cause — `CREW_MEMBER_SUSPENDED` for a
        suspension, `CREW_MEMBER_REMOVED` for a removal."

        Design: Difficulty/transitive_cascade/positive_drug_test_suspension_cascade
        """
        setup = self._issued_permit_jobsite("Skyline Deck")
        worker = setup["worker"]

        record = create_drug_test(worker["id"], test_type="RANDOM",
                                  collected_at="2026-08-02T11:00:00Z")
        record_drug_result(record["id"], "POSITIVE")

        worker_after = get_worker(worker["id"])
        assert worker_after["status"] == "SUSPENDED"
        assert worker_after["suspension_reason"] == "POSITIVE_DRUG_TEST"

        permit = get_permit(setup["permit"]["id"])
        assert permit["status"] == "SUSPENDED"
        assert permit["suspension_reason"] == "CREW_MEMBER_SUSPENDED"

    def test_positive_result_demotes_jha_without_touching_posture(self, api):
        """PRD §2.7: "Link 3 is the analysis effect: each permit suspended in
        link 2 drives its linked job hazard analysis from `APPROVED` back to
        `RE_REVIEW_REQUIRED`, forcing a fresh safety review before that task's
        permits can be issued or reinstated again."
        PRD §3.4: "suspension also decrements `issued_permit_count`, increments
        the project's `version`, and demotes the linked JHA."

        Design: Difficulty/transitive_cascade/positive_drug_test_suspension_cascade
        """
        setup = self._issued_permit_jobsite("Skyline Deck 2")
        worker = setup["worker"]
        project_id = setup["project"]["id"]

        record = create_drug_test(worker["id"], test_type="RANDOM",
                                  collected_at="2026-08-02T11:00:00Z")
        record_drug_result(record["id"], "POSITIVE")

        assert get_jha(setup["jha"]["id"])["status"] == "RE_REVIEW_REQUIRED"
        project = get_project(project_id)
        # This cascade does not route through posture: no FROZEN cause exists.
        assert project["safety_posture"] == "NORMAL"
        assert project["issued_permit_count"] == 0
