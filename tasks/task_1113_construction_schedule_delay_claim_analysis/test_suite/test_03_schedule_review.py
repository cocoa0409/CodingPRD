"""Schedule review workflow: submission, acceptance preconditions, OCC on the
project, the revision cycle, and the reject compensating action (PRD §3.3)."""
from datetime import datetime

from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    accept_schedule_payload,
    create_project,
    create_schedule_version,
    create_draft_schedule_with_activities,
    add_activity,
    submit_schedule,
    accept_schedule,
    reject_schedule,
    revise_schedule,
    get_project,
    get_project_version,
    get_activity,
)


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


class TestSubmissionPreconditions:
    def test_empty_schedule_submit_rejected(self, api, contractor_headers):
        """PRD §3.3: "A version may be submitted only from `DRAFT`
        (`ERR_INVALID_STATE`), must contain at least one activity
        (`ERR_EMPTY_SCHEDULE`), and its network must be acyclic
        (`ERR_CYCLE_DETECTED`)."

        Design: Corner/validations/empty_schedule_submit_rejected
        """
        project = create_project()
        version = create_schedule_version(project["id"], kind="BASELINE")
        resp = api.submit_schedule_version(project["id"], version["id"], contractor_headers)
        validate_error(resp, ApiErrorId.ERR_EMPTY_SCHEDULE)

    def test_schedule_submit_from_accepted_fails_invalid_state(
        self, api, contractor_headers, pce_headers
    ):
        """PRD §3.3: "A version may be submitted only from `DRAFT`
        (`ERR_INVALID_STATE`), must contain at least one activity
        (`ERR_EMPTY_SCHEDULE`), and its network must be acyclic
        (`ERR_CYCLE_DETECTED`)."

        Design: Corner/state_machines/schedule_submit_from_accepted_fails_invalid_state
        """
        project = create_project()
        version, _ids = create_draft_schedule_with_activities(
            project["id"], activity_durations=[("A", 5)]
        )
        submit_schedule(project["id"], version["id"])
        accept_schedule(project["id"], version["id"])
        resp = api.submit_schedule_version(project["id"], version["id"], contractor_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestUpdateAcceptRequiresBaseline:
    def test_update_accept_without_any_baseline_rejected(self, api, pce_headers):
        """PRD §3.3: "while an `UPDATE` acceptance requires that an accepted baseline
        already exist (`ERR_BASELINE_NOT_ACCEPTED`)".

        Design: Difficulty/cross_entity_state_dependency/update_accept_requires_baseline_accepted_pair_scheduleversion_scheduleversion
        """
        project = create_project()
        update, _ids = create_draft_schedule_with_activities(
            project["id"],
            kind="UPDATE",
            data_date="2026-05-08T00:00:00Z",
            activity_durations=[("A", 5)],
        )
        submit_schedule(project["id"], update["id"])
        resp = api.accept_schedule_version(
            project["id"],
            update["id"],
            accept_schedule_payload(get_project_version(project["id"])),
            pce_headers,
        )
        validate_error(resp, ApiErrorId.ERR_BASELINE_NOT_ACCEPTED)

    def test_update_accept_with_unaccepted_baseline_rejected(self, api, pce_headers):
        """PRD §3.3: "while an `UPDATE` acceptance requires that an accepted baseline
        already exist (`ERR_BASELINE_NOT_ACCEPTED`)". A merely SUBMITTED baseline is
        not an accepted one, so the UPDATE acceptance still fails.

        Design: Difficulty/cross_entity_state_dependency/update_accept_requires_baseline_accepted_pair_scheduleversion_scheduleversion
        """
        project = create_project()
        baseline, _ids = create_draft_schedule_with_activities(
            project["id"], kind="BASELINE", activity_durations=[("A", 5)]
        )
        submit_schedule(project["id"], baseline["id"])  # SUBMITTED, never ACCEPTED
        update, _uids = create_draft_schedule_with_activities(
            project["id"],
            kind="UPDATE",
            data_date="2026-05-08T00:00:00Z",
            activity_durations=[("A", 5)],
        )
        submit_schedule(project["id"], update["id"])
        resp = api.accept_schedule_version(
            project["id"],
            update["id"],
            accept_schedule_payload(get_project_version(project["id"])),
            pce_headers,
        )
        validate_error(resp, ApiErrorId.ERR_BASELINE_NOT_ACCEPTED)


class TestBaselineAcceptCascade:
    def test_baseline_accept_activates_project_and_bumps_version(
        self, api, pce_headers
    ):
        """PRD §3.3: "Accepting a `BASELINE` while the project is still in
        `PRECONSTRUCTION` fires the activation chain of §3.1."
        PRD §3.3: "Either acceptance advances the project `version` by exactly one."
        PRD §3.1: "Activation is the transition from `PRECONSTRUCTION` to `ACTIVE`."

        Design: Difficulty/transitive_cascade/baseline_accept_cascades_project_activation_then_eot_offset
        """
        project = create_project()
        version_before = project["version"]
        baseline, _ids = create_draft_schedule_with_activities(
            project["id"], activity_durations=[("A1", 30)]
        )
        submit_schedule(project["id"], baseline["id"])
        accepted = accept_schedule(project["id"], baseline["id"])
        assert accepted["status"] == "ACCEPTED"
        after = get_project(project["id"])
        assert after["status"] == "ACTIVE", (
            "baseline acceptance while PRECONSTRUCTION must fire the activation chain"
        )
        assert after["version"] == version_before + 1, (
            "acceptance must advance the project version by exactly one"
        )

    def test_baseline_accept_sets_current_completion_date(self, api, pce_headers):
        """PRD §3.1: "Its derived `current_completion_date` — the date against which
        all drift, entitlement, and damages arithmetic is performed — starts equal
        to `contract_completion_date`."
        PRD §3.1: "either path sets `current_completion_date` to
        `contract_completion_date`".

        Design: Difficulty/transitive_cascade/baseline_accept_cascades_project_activation_then_eot_offset
        """
        project = create_project(contract_completion_date="2026-06-30T00:00:00Z")
        baseline, _ids = create_draft_schedule_with_activities(
            project["id"], activity_durations=[("A1", 30)]
        )
        submit_schedule(project["id"], baseline["id"])
        accept_schedule(project["id"], baseline["id"])
        after = get_project(project["id"])
        assert _parse(after["current_completion_date"]) == _parse(
            "2026-06-30T00:00:00Z"
        ), "current_completion_date must equal contract_completion_date after activation"


class TestOptimisticConcurrency:
    def test_occ_stale_version_on_schedule_accept(self, api, pce_headers):
        """PRD §2.9: "Each requires a non-optional `expected_project_version` field
        in the request payload, carrying the project `version` the client last
        observed. If the supplied value does not match the project's current
        `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_stale_version_on_schedule_accept
        """
        project = create_project()
        stale_version = project["version"]
        baseline, _ids = create_draft_schedule_with_activities(
            project["id"], activity_durations=[("A", 5)]
        )
        submit_schedule(project["id"], baseline["id"])
        accept_schedule(project["id"], baseline["id"])  # advances project.version
        update, _uids = create_draft_schedule_with_activities(
            project["id"],
            kind="UPDATE",
            data_date="2026-05-08T00:00:00Z",
            activity_durations=[("A", 5)],
        )
        submit_schedule(project["id"], update["id"])
        resp = api.accept_schedule_version(
            project["id"],
            update["id"],
            accept_schedule_payload(stale_version),  # stale: project moved on
            pce_headers,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    def test_immediate_consistency_on_project_version_after_accept(
        self, api, pce_headers
    ):
        """PRD §2.7: "The system performs these reconciliations automatically at the
        moment the triggering transition occurs, without requiring a separate client
        call". PRD §2.7: "Accepting a schedule version advances the owning project's
        `version` by one".

        Design: Corner/consistency_model/immediate_consistency_on_project_version_after_accept
        """
        project = create_project()
        version_before = project["version"]
        baseline, _ids = create_draft_schedule_with_activities(
            project["id"], activity_durations=[("A", 5)]
        )
        submit_schedule(project["id"], baseline["id"])
        resp = api.accept_schedule_version(
            project["id"],
            baseline["id"],
            accept_schedule_payload(version_before),
            pce_headers,
        )
        validate_success(resp, expected_status=200)
        after = get_project(project["id"])  # the very next read sees the increment
        assert after["version"] == version_before + 1
        assert after["status"] == "ACTIVE"


class TestRevisionCycle:
    def test_rejected_version_returns_to_draft_with_incremented_revision(
        self, api, contractor_headers, pce_headers
    ):
        """PRD §3.3: "The contractor may then bring the version back from `REJECTED`
        to `DRAFT` for rework, which increments `revision_number` by one."
        PRD §3.2: "Each version is numbered by a per-kind, monotonically increasing
        `revision_number` that starts at 1, and every version begins life in
        `DRAFT`."

        Design: Difficulty/non_linear_state_machine/schedule_version_rejected_to_draft_cycle
        """
        project = create_project()
        version, _ids = create_draft_schedule_with_activities(
            project["id"], activity_durations=[("X", 5)]
        )
        assert version["revision_number"] == 1
        submit_schedule(project["id"], version["id"])
        reject_schedule(project["id"], version["id"])
        revised = revise_schedule(project["id"], version["id"])
        assert revised["status"] == "DRAFT", "cycle REJECTED → DRAFT"
        assert revised["revision_number"] == 2, "revision_number increments by one per loop"

    def test_second_revision_cycle_increments_revision_again(
        self, api, contractor_headers, pce_headers
    ):
        """PRD §3.3: "The contractor may then bring the version back from `REJECTED`
        to `DRAFT` for rework, which increments `revision_number` by one."

        Design: Difficulty/non_linear_state_machine/schedule_version_rejected_to_draft_cycle
        """
        project = create_project()
        version, _ids = create_draft_schedule_with_activities(
            project["id"], activity_durations=[("X", 5)]
        )
        submit_schedule(project["id"], version["id"])
        reject_schedule(project["id"], version["id"])
        revise_schedule(project["id"], version["id"])
        submit_schedule(project["id"], version["id"])
        reject_schedule(project["id"], version["id"])
        revised = revise_schedule(project["id"], version["id"])
        assert revised["status"] == "DRAFT"
        assert revised["revision_number"] == 3, (
            "two REJECTED → DRAFT loops must move revision_number 1 → 3"
        )


class TestRejectClearsComputedFields:
    def test_reject_clears_computed_float_and_dates(self, api, pce_headers):
        """PRD §3.3: "Rejection by the `ProjectControlsEngineer` moves the version
        from `SUBMITTED` to `REJECTED` and clears every computed date and float
        field on its activities, so that a later resubmission recomputes from a
        clean slate."

        Design: Difficulty/compensating_invariant/schedule_reject_clears_computed_float_invariant
        """
        project = create_project()
        version, ids = create_draft_schedule_with_activities(
            project["id"], activity_durations=[("A", 5)]
        )
        submit_schedule(project["id"], version["id"])
        computed = get_activity(project["id"], version["id"], ids[0])
        assert computed["total_float_days"] is not None  # populated by submission
        reject_schedule(project["id"], version["id"])
        cleared = get_activity(project["id"], version["id"], ids[0])
        for field in (
            "early_start",
            "early_finish",
            "late_start",
            "late_finish",
            "total_float_days",
        ):
            assert cleared.get(field) is None, (
                f"{field} must be cleared after rejection, got {cleared.get(field)!r}"
            )

    def test_resubmission_after_reject_recomputes_cleanly(self, api, pce_headers):
        """PRD §3.3: "Rejection by the `ProjectControlsEngineer` moves the version
        from `SUBMITTED` to `REJECTED` and clears every computed date and float
        field on its activities, so that a later resubmission recomputes from a
        clean slate."

        Design: Difficulty/compensating_invariant/schedule_reject_clears_computed_float_invariant
        """
        project = create_project()
        version, ids = create_draft_schedule_with_activities(
            project["id"], activity_durations=[("A", 5)]
        )
        submit_schedule(project["id"], version["id"])
        reject_schedule(project["id"], version["id"])
        revise_schedule(project["id"], version["id"])
        resubmitted = submit_schedule(project["id"], version["id"])
        assert resubmitted["status"] == "SUBMITTED"
        recomputed = get_activity(project["id"], version["id"], ids[0])
        assert recomputed["total_float_days"] == 0, (
            "a single-activity network must recompute to zero total float"
        )
        assert recomputed["early_start"] is not None
        assert recomputed["is_critical"] is True
