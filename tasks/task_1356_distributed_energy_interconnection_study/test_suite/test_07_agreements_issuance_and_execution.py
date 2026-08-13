"""Agreement issuance gates, OCC, execution deadline, expiry, and re-issuance."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_instant_equal,
    assert_interconnection_agreement,
    create_agreement_payload,
    finalize_study,
    get_project,
    get_study,
    issue_agreement,
    list_project_agreements,
    make_developer_headers,
    publish_results,
    set_clock,
    setup_project_agreement_pending,
    setup_study_scenario,
    validate_error,
    validate_paginated,
    validate_success,
    withdraw_project,
)

ADMIN = TEST_USERS["queue_admin_headers"]

# Issued at the startup default clock 2026-08-01T00:00:00Z plus ninety days.
DEFAULT_ISSUED_DEADLINE = "2026-10-30T00:00:00Z"


class TestIssuanceGates:
    def test_issue_agreement_requires_study_complete(self, api):
        """PRD §3.6: "If the project's state is not `STUDY_COMPLETE` — and the
        re-issuance exception below does not apply — the request is rejected with
        `ERR_PROJECT_NOT_STUDY_COMPLETE`"

        Design: Corner/validations/issue_agreement_requires_study_complete
        """
        scenario = setup_study_scenario([{"capacity_mw": 10}], publish=False)
        project = scenario["projects"][0]
        assert project["status"] == "IN_STUDY"

        fresh = get_project(project["id"])
        resp = api.issue_agreement(
            project["id"],
            create_agreement_payload(fresh["version"], max_injection_mw=10), ADMIN)
        validate_error(resp, ApiErrorId.ERR_PROJECT_NOT_STUDY_COMPLETE)

        agreements, meta = validate_paginated(
            api.list_project_agreements(project["id"], ADMIN))
        assert agreements == [] and meta["total_count"] == 0

    def test_occ_stale_version_rejected(self, api):
        """PRD §2.7: "That request must carry `expected_project_version`, holding
        the client's last observed `version` of the target `Project`. If the value
        does not match the project's current `version` — for example because
        another writer has advanced the project since the client last read it —
        the request is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the
        client from acting on a project state it has not observed."
        PRD §3.6: "A successful issuance creates the agreement in `ISSUED`, stamps
        `issued_at` from the logical clock, computes the read-only
        `execution_deadline` as exactly ninety days after `issued_at`, initializes
        `extension_count` to zero, moves the project from `STUDY_COMPLETE` to
        `AGREEMENT_PENDING`, and increments the project's `version` by one."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_version_rejected
        """
        scenario = setup_project_agreement_pending(finalize=False)
        project = scenario["project"]
        developer = scenario["developer"]
        agreement1 = scenario["agreement"]

        # Expire A1: advance past its 90-day deadline, then a late execute
        # materializes ISSUED -> EXPIRED.
        set_clock("2026-10-31T00:00:00Z")
        resp = api.execute_agreement(agreement1["id"],
                                     make_developer_headers(developer["id"]))
        validate_error(resp, ApiErrorId.ERR_AGREEMENT_EXECUTION_DEADLINE_PASSED)

        # Re-issuance with the fresh version succeeds and bumps the version again.
        version_current = get_project(project["id"])["version"]
        resp = api.issue_agreement(
            project["id"],
            create_agreement_payload(version_current,
                                     target_cod="2028-06-01T00:00:00Z",
                                     max_injection_mw=10), ADMIN)
        agreement2 = validate_success(resp, expected_status=201)
        assert agreement2["status"] == "ISSUED"
        assert agreement2["id"] != agreement1["id"]
        assert get_project(project["id"])["version"] == version_current + 1

        # A second re-issuance carrying the pre-supersede version is stale.
        resp = api.issue_agreement(
            project["id"],
            create_agreement_payload(version_current,
                                     target_cod="2029-06-01T00:00:00Z",
                                     max_injection_mw=10), ADMIN)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


class TestExecutionStudyGate:
    def test_execute_rejected_while_study_results_published(self, api):
        """PRD §3.6: "Execution requires the agreement to be `ISSUED` (otherwise
        `ERR_AGREEMENT_NOT_ISSUED`), requires the acting developer to own the
        parent project, requires the logical clock to be no later than the
        `execution_deadline` — with equality at the exact deadline timestamp
        permitted — and requires the cluster study to be `FINALIZED` (otherwise
        `ERR_STUDY_NOT_FINALIZED`)."

        Design: Difficulty/cross_entity_state_dependency/agreement_execute_requires_study_finalized
        """
        scenario = setup_project_agreement_pending(finalize=False)
        agreement = scenario["agreement"]
        developer = scenario["developer"]
        assert scenario["study"]["status"] == "RESULTS_PUBLISHED"

        resp = api.execute_agreement(agreement["id"],
                                     make_developer_headers(developer["id"]))
        validate_error(resp, ApiErrorId.ERR_STUDY_NOT_FINALIZED)

        agreements = list_project_agreements(scenario["project"]["id"])
        assert agreements[0]["status"] == "ISSUED", "no state change on failed execute"

    def test_execute_succeeds_after_finalize(self, api):
        """PRD §3.5: "A finalized study also unblocks agreement execution"
        PRD §3.6: "A successful execution moves the agreement from `ISSUED` to
        `EXECUTED` and the project from `AGREEMENT_PENDING` to
        `AGREEMENT_EXECUTED`."

        Design: Difficulty/cross_entity_state_dependency/agreement_execute_requires_study_finalized
        """
        scenario = setup_project_agreement_pending(finalize=False)
        agreement = scenario["agreement"]
        developer = scenario["developer"]
        project = scenario["project"]

        finalize_study(scenario["study"]["id"])
        resp = api.execute_agreement(agreement["id"],
                                     make_developer_headers(developer["id"]))
        data = validate_success(resp, expected_status=200)
        assert_interconnection_agreement(data)
        assert data["status"] == "EXECUTED"
        assert get_project(project["id"])["status"] == "AGREEMENT_EXECUTED"


class TestExecutionDeadlineBoundary:
    def test_execute_at_exact_deadline_permitted(self, api):
        """PRD §2.6: "Timestamp comparisons at deadline boundaries are inclusive:
        an execute attempt arriving at the exact deadline timestamp is permitted."
        PRD §3.6: "computes the read-only `execution_deadline` as exactly ninety
        days after `issued_at`"

        Design: Difficulty/boundary_precision_check/execution_deadline_exact_timestamp
        """
        scenario = setup_project_agreement_pending(finalize=True)
        agreement = scenario["agreement"]
        developer = scenario["developer"]
        assert_instant_equal(agreement["execution_deadline"], DEFAULT_ISSUED_DEADLINE)

        set_clock(DEFAULT_ISSUED_DEADLINE)
        resp = api.execute_agreement(agreement["id"],
                                     make_developer_headers(developer["id"]))
        data = validate_success(resp, expected_status=200)
        assert data["status"] == "EXECUTED", "now == execution_deadline is permitted"

    def test_execute_one_second_past_deadline_rejected_and_expires(self, api):
        """PRD §3.6: "A late attempt is doubly consequential: the agreement itself
        transitions from `ISSUED` to `EXPIRED` — this expiry is materialized
        lazily, at the moment the late execute attempt arrives — the attempt is
        rejected with `ERR_AGREEMENT_EXECUTION_DEADLINE_PASSED`, and the project
        remains `AGREEMENT_PENDING`, eligible for the re-issuance path above."

        Design: Difficulty/boundary_precision_check/execution_deadline_exact_timestamp
        """
        scenario = setup_project_agreement_pending(finalize=True)
        agreement = scenario["agreement"]
        developer = scenario["developer"]
        project = scenario["project"]

        set_clock("2026-10-30T00:00:01Z")
        resp = api.execute_agreement(agreement["id"],
                                     make_developer_headers(developer["id"]))
        validate_error(resp, ApiErrorId.ERR_AGREEMENT_EXECUTION_DEADLINE_PASSED)

        agreements = list_project_agreements(project["id"])
        assert agreements[0]["status"] == "EXPIRED", "deadline + 1s expires the agreement"
        assert get_project(project["id"])["status"] == "AGREEMENT_PENDING"


class TestExpiredAgreement:
    def test_execute_expired_agreement_returns_not_issued(self, api):
        """PRD §3.6: "Execution requires the agreement to be `ISSUED` (otherwise
        `ERR_AGREEMENT_NOT_ISSUED`)"
        PRD §3.6: "the agreement itself transitions from `ISSUED` to `EXPIRED` —
        this expiry is materialized lazily, at the moment the late execute attempt
        arrives"

        Design: Corner/state_machines/execute_expired_agreement_returns_not_issued
        """
        scenario = setup_project_agreement_pending(finalize=True)
        agreement = scenario["agreement"]
        developer = scenario["developer"]

        set_clock("2026-10-31T00:00:00Z")
        resp = api.execute_agreement(agreement["id"],
                                     make_developer_headers(developer["id"]))
        validate_error(resp, ApiErrorId.ERR_AGREEMENT_EXECUTION_DEADLINE_PASSED)

        resp = api.execute_agreement(agreement["id"],
                                     make_developer_headers(developer["id"]))
        validate_error(resp, ApiErrorId.ERR_AGREEMENT_NOT_ISSUED)


class TestValidationPriorityOnExecute:
    def _setup_reopened_study_with_pending_agreement(self, api):
        """P1 (10 MW) and P2 (20 MW) STUDY_COMPLETE under a RESULTS_PUBLISHED
        study; agreement issued to P1; P2 withdrawn, reopening the study to
        IN_PROGRESS; clock advanced past P1's execution deadline."""
        scenario = setup_study_scenario(
            [{"capacity_mw": 10, "technology": "SOLAR"},
             {"capacity_mw": 20, "technology": "SOLAR"}],
            total_cost_cents=1000000, publish=True)
        p1, p2 = scenario["projects"]
        developer = scenario["developer"]
        agreement = issue_agreement(p1["id"], max_injection_mw=10)
        withdraw_project(p2["id"], acting_developer_id=developer["id"])
        set_clock("2026-10-31T00:00:00Z")
        return scenario, p1, agreement

    def test_execute_temporal_beats_referential_when_both_fail(self, api):
        """PRD §2.8: "Seventh, clock-relative deadline rules fire
        (`ERR_AGREEMENT_EXECUTION_DEADLINE_PASSED`, `ERR_EXTENSION_WINDOW_MISSED`,
        `ERR_COD_DEADLINE_PASSED`). Eighth, cross-entity state requirements are
        checked — agreement issuance requires the cluster study to be published or
        finalized (`ERR_STUDY_NOT_PUBLISHED`), and agreement execution requires the
        study finalized (`ERR_STUDY_NOT_FINALIZED`)."
        PRD §2.8: "Where two rules from different categories could both fire on the
        same request, the earlier category's error wins."

        Design: Difficulty/priority_pair_validation_conflict/execute_temporal_beats_referential_when_both_fail
        """
        scenario, p1, agreement = self._setup_reopened_study_with_pending_agreement(api)
        developer = scenario["developer"]
        assert scenario["study"]["status"] == "RESULTS_PUBLISHED"
        assert get_study(scenario["study"]["id"])["status"] == "IN_PROGRESS", (
            "setup: sibling withdrawal reopened the study, so the referential "
            "check (study FINALIZED) would also fail"
        )

        resp = api.execute_agreement(agreement["id"],
                                     make_developer_headers(developer["id"]))
        validate_error(resp, ApiErrorId.ERR_AGREEMENT_EXECUTION_DEADLINE_PASSED)

    def test_late_execute_expires_agreement_and_keeps_project_pending(self, api):
        """PRD §3.6: "the agreement itself transitions from `ISSUED` to `EXPIRED`
        — this expiry is materialized lazily, at the moment the late execute
        attempt arrives — the attempt is rejected with
        `ERR_AGREEMENT_EXECUTION_DEADLINE_PASSED`, and the project remains
        `AGREEMENT_PENDING`, eligible for the re-issuance path above."

        Design: Difficulty/priority_pair_validation_conflict/execute_temporal_beats_referential_when_both_fail
        """
        scenario, p1, agreement = self._setup_reopened_study_with_pending_agreement(api)
        developer = scenario["developer"]

        resp = api.execute_agreement(agreement["id"],
                                     make_developer_headers(developer["id"]))
        validate_error(resp, ApiErrorId.ERR_AGREEMENT_EXECUTION_DEADLINE_PASSED)

        agreements = list_project_agreements(p1["id"])
        assert agreements[0]["status"] == "EXPIRED"
        assert get_project(p1["id"])["status"] == "AGREEMENT_PENDING", (
            "expiry does not withdraw the project"
        )


class TestReissuanceStudyGate:
    def test_reissue_blocked_while_study_reopened(self, api):
        """PRD §3.6: "If the project is already `AGREEMENT_PENDING` and every
        agreement it has ever received has reached `EXPIRED`, a `QueueAdministrator`
        may issue a fresh agreement under the same OCC guard and the same
        study-state requirement"
        PRD §3.6: "if the study has not reached `RESULTS_PUBLISHED` or `FINALIZED`,
        with `ERR_STUDY_NOT_PUBLISHED`"

        Design: Corner/validations/reissue_blocked_while_study_reopened
        """
        scenario = setup_study_scenario(
            [{"capacity_mw": 10, "technology": "SOLAR"},
             {"capacity_mw": 20, "technology": "SOLAR"}],
            total_cost_cents=1000000, publish=True)
        p1, p2 = scenario["projects"]
        developer = scenario["developer"]
        agreement = issue_agreement(p1["id"], max_injection_mw=10)

        # Sibling withdrawal reopens the study; a late execute expires A1.
        withdraw_project(p2["id"], acting_developer_id=developer["id"])
        set_clock("2026-10-31T00:00:00Z")
        resp = api.execute_agreement(agreement["id"],
                                     make_developer_headers(developer["id"]))
        validate_error(resp, ApiErrorId.ERR_AGREEMENT_EXECUTION_DEADLINE_PASSED)

        fresh = get_project(p1["id"])
        assert fresh["status"] == "AGREEMENT_PENDING"
        resp = api.issue_agreement(
            p1["id"],
            create_agreement_payload(fresh["version"],
                                     target_cod="2028-06-01T00:00:00Z",
                                     max_injection_mw=10), ADMIN)
        validate_error(resp, ApiErrorId.ERR_STUDY_NOT_PUBLISHED)
