"""Scoring assignments, the AHI/RDI/REI computation variants, the task
revision cycle, and the assignment guards (pool, segregation, terminality)."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    accept_task,
    assert_scoring_task,
    assign_task,
    create_physician,
    create_report,
    create_scorer,
    create_technologist,
    get_study,
    get_task,
    make_physician_headers,
    make_scorer_headers,
    return_task,
    setup_finalized_report,
    setup_scored_study,
    setup_scoring_queued,
    sign_report,
    start_task,
    submit_task,
    validate_error,
    validate_paginated,
)

SCHED = TEST_USERS["scheduler_headers"]
DIRECTOR = TEST_USERS["lab_director_headers"]


class TestDualVariantIndexComputation:
    def test_ahi_inlab_psg_indexes(self, api):
        """PRD: "For in-lab studies, `ahi` is the event total multiplied by 60
        and divided by `total_sleep_time_minutes`, rounded half-up to one
        decimal place; `rdi` repeats the same computation with the `reras`
        added to the event total; `rei` is null."
        PRD: "The `index_at_interpretation` is the study's `accepted_rei` for
        `HST` and its `accepted_ahi` otherwise. The `severity` bands against
        that index are: `NORMAL` below 5.0, `MILD` at least 5.0 but below
        15.0, `MODERATE` at least 15.0 but below 30.0, and `SEVERE` at least
        30.0"

        Design: Difficulty/dual_variant_calc/ahi_inlab_vs_rei_hst_identical_event_counts
        """
        ws = setup_scored_study(
            study_type="PSG_DIAGNOSTIC",
            submit_overrides={
                "obstructive_apneas": 30, "central_apneas": 0,
                "mixed_apneas": 0, "hypopneas": 60, "reras": 30,
                "epochs_total": 720, "total_sleep_time_minutes": 360,
                "total_recording_time_minutes": 420,
            })
        task = ws["task"]
        # 90 events * 60 / 360 TST; RDI adds the 30 RERAs to the numerator.
        assert task["ahi"] == pytest.approx(15.0)
        assert task["rdi"] == pytest.approx(20.0)
        assert task["rei"] is None

        study = ws["study"]
        assert study["accepted_ahi"] == pytest.approx(15.0)
        assert study["accepted_rdi"] == pytest.approx(20.0)
        assert study["accepted_rei"] is None

        create_report(ws)
        report = sign_report(ws)
        assert report["index_at_interpretation"] == pytest.approx(15.0)
        assert report["severity"] == "MODERATE"

    def test_rei_hst_index_round_half_up(self, api):
        """PRD: "For `HST`, `rei` is the event total multiplied by 60 and
        divided by `total_recording_time_minutes`, rounded half-up to one
        decimal place, and both `ahi` and `rdi` are null. Because the home
        variant divides by recording time rather than sleep time, identical
        event counts yield a strictly smaller index whenever recording time
        exceeds sleep time."
        PRD: "rounded to exactly 1 decimal place using round-half-up — so
        11.25 becomes 11.3, and banker's rounding is never used."

        Design: Difficulty/dual_variant_calc/ahi_inlab_vs_rei_hst_identical_event_counts
        """
        ws = setup_scored_study(
            study_type="HST",
            submit_overrides={
                "obstructive_apneas": 30, "central_apneas": 0,
                "mixed_apneas": 0, "hypopneas": 60, "reras": 30,
                "epochs_total": 960, "total_recording_time_minutes": 480,
            })
        task = ws["task"]
        # 90 events * 60 / 480 TRT = 11.25 -> 11.3 (round-half-up, never 11.2).
        assert task["rei"] == pytest.approx(11.3)
        assert task["ahi"] is None
        assert task["rdi"] is None

        study = ws["study"]
        assert study["accepted_rei"] == pytest.approx(11.3)
        assert study["accepted_ahi"] is None
        assert study["accepted_rdi"] is None

        create_report(ws)
        report = sign_report(ws)
        assert report["index_at_interpretation"] == pytest.approx(11.3)
        assert report["severity"] == "MILD"


class TestScoringTaskRevisionCycle:
    def test_return_stores_reason_and_study_stays_in_scoring(self, api):
        """PRD: "Alternatively the physician returns a `SUBMITTED` task with a
        `reason` of at least ten characters (shorter reasons are rejected with
        `ERR_INSUFFICIENT_REASON`); the task moves to `RETURNED_FOR_REVISION`,
        the reason is stored on `returned_reason` (null unless the task has
        been returned), and the scorer may resume the revision loop by starting
        the task again."
        PRD: "a returned task being resumed finds its study already there" —
        the study stays in `SCORING_IN_PROGRESS` throughout the loop.

        Design: Difficulty/non_linear_state_machine/scoring_task_revision_cycle
        """
        ws = setup_scoring_queued(study_type="HST")
        task = assign_task(ws["study"]["id"], ws["scorer"]["id"])
        start_task(task["id"], ws["scorer"]["id"])
        submit_task(task["id"], ws["scorer"]["id"], obstructive_apneas=10,
                    hypopneas=10)

        returned = return_task(task["id"], ws["physician"]["id"],
                               reason="staging needs revision")
        assert_scoring_task(returned)
        assert returned["status"] == "RETURNED_FOR_REVISION"
        assert returned["returned_reason"] == "staging needs revision"
        assert get_study(ws["study"]["id"])["status"] == \
            "SCORING_IN_PROGRESS"

    def test_revision_cycle_completes_with_recomputed_index(self, api):
        """PRD: "the scorer may resume the revision loop by starting the task
        again."
        PRD: "Submission stamps `submitted_at` from the logical clock — it
        always reflects the latest submission — moves the task to `SUBMITTED`,
        and computes the respiratory indexes."
        PRD: "Accepting a `PRIMARY` additionally moves the study from
        `SCORING_IN_PROGRESS` to `SCORED` and snapshots the indexes onto it"

        Design: Difficulty/non_linear_state_machine/scoring_task_revision_cycle
        """
        ws = setup_scoring_queued(study_type="HST")
        task = assign_task(ws["study"]["id"], ws["scorer"]["id"])
        start_task(task["id"], ws["scorer"]["id"])
        submit_task(task["id"], ws["scorer"]["id"], obstructive_apneas=10,
                    hypopneas=10)
        return_task(task["id"], ws["physician"]["id"],
                    reason="staging needs revision")

        # Resume the loop: RETURNED_FOR_REVISION -> IN_PROGRESS -> SUBMITTED.
        start_task(task["id"], ws["scorer"]["id"])
        resubmitted = submit_task(task["id"], ws["scorer"]["id"],
                                  obstructive_apneas=12, hypopneas=10)
        # 22 events * 60 / 480 TRT = 2.75 -> 2.8 (round-half-up).
        assert resubmitted["rei"] == pytest.approx(2.8)

        accepted = accept_task(task["id"], ws["physician"]["id"])
        assert accepted["status"] == "ACCEPTED"
        assert accepted["rei"] == pytest.approx(2.8)

        study = get_study(ws["study"]["id"])
        assert study["status"] == "SCORED"
        assert study["accepted_rei"] == pytest.approx(2.8)


class TestAssignmentGuards:
    def test_create_task_on_terminal_study_rejected(self, api):
        """PRD: "A primary assignment requires the study to be
        `SCORING_QUEUED`; a reliability rescore requires the study to be
        `SCORED` or beyond — otherwise `ERR_STUDY_NOT_SCORABLE`."

        Design: Corner/state_machines/create_task_on_terminal_study_returns_invalid_state
        """
        ws = setup_finalized_report(study_type="HST")
        assert ws["study"]["status"] == "REPORT_FINALIZED"

        resp = api.create_scoring_task(
            {"study_id": ws["study"]["id"], "scorer_id": ws["scorer"]["id"],
             "assignment_kind": "PRIMARY"},
            DIRECTOR,
        )
        validate_error(resp, ApiErrorId.ERR_STUDY_NOT_SCORABLE, 409)

        assert get_study(ws["study"]["id"])["status"] == "REPORT_FINALIZED"

    def test_rescore_on_unscored_study_rejected(self, api):
        """PRD: "A primary assignment requires the study to be
        `SCORING_QUEUED`; a reliability rescore requires the study to be
        `SCORED` or beyond — otherwise `ERR_STUDY_NOT_SCORABLE`."

        Design: Corner/state_machines/rescore_on_unscored_study_rejected
        """
        ws = setup_scoring_queued(study_type="HST")
        pool_scorer = create_scorer(credential="RST", reliability_pool=True)

        resp = api.create_scoring_task(
            {"study_id": ws["study"]["id"], "scorer_id": pool_scorer["id"],
             "assignment_kind": "RELIABILITY_RESCORE"},
            DIRECTOR,
        )
        validate_error(resp, ApiErrorId.ERR_STUDY_NOT_SCORABLE, 409)

        _, meta = validate_paginated(api.list_scoring_tasks(
            DIRECTOR, {"study_id": ws["study"]["id"]}))
        assert meta["total_count"] == 0

    def test_scorer_not_in_pool_rescore_rejected(self, api):
        """PRD: "a `RELIABILITY_RESCORE` additionally requires a scorer
        enrolled in the reliability pool (`ERR_SCORER_NOT_IN_POOL`)"

        Design: Corner/errors/scorer_not_in_pool_rescore_rejected
        """
        ws = setup_scored_study(study_type="HST")
        outsider = create_scorer(credential="RST")  # pool flag defaults false

        resp = api.create_scoring_task(
            {"study_id": ws["study"]["id"], "scorer_id": outsider["id"],
             "assignment_kind": "RELIABILITY_RESCORE"},
            DIRECTOR,
        )
        validate_error(resp, ApiErrorId.ERR_SCORER_NOT_IN_POOL, 422)

    def test_rescore_same_scorer_rejected(self, api):
        """PRD: "the rescorer must not be the scorer of the study's accepted
        primary task (`ERR_SOD_PRIMARY_SCORER`)."

        Design: Corner/errors/rescore_same_scorer_rejected
        """
        # The primary scorer is pool-enrolled, so the pool-membership rule
        # passes and only the segregation-of-duties rule can fire.
        staff = {
            "technologist": create_technologist(),
            "scorer": create_scorer(reliability_pool=True),
            "physician": create_physician(),
        }
        ws = setup_scored_study(study_type="HST", staff=staff)

        resp = api.create_scoring_task(
            {"study_id": ws["study"]["id"],
             "scorer_id": ws["scorer"]["id"],
             "assignment_kind": "RELIABILITY_RESCORE"},
            DIRECTOR,
        )
        validate_error(resp, ApiErrorId.ERR_SOD_PRIMARY_SCORER, 422)

    def test_second_primary_task_rejected(self, api):
        """PRD: "A study may hold only one non-terminal `PRIMARY` task at a
        time (`ERR_PRIMARY_TASK_EXISTS`)."

        Design: Corner/validations/second_primary_task_rejected
        """
        ws = setup_scoring_queued(study_type="HST")
        assign_task(ws["study"]["id"], ws["scorer"]["id"], "PRIMARY")

        resp = api.create_scoring_task(
            {"study_id": ws["study"]["id"], "scorer_id": ws["scorer"]["id"],
             "assignment_kind": "PRIMARY"},
            DIRECTOR,
        )
        validate_error(resp, ApiErrorId.ERR_PRIMARY_TASK_EXISTS, 409)

        _, meta = validate_paginated(api.list_scoring_tasks(
            DIRECTOR, {"study_id": ws["study"]["id"]}))
        assert meta["total_count"] == 1


class TestTaskOwnershipAndLifecycle:
    def test_scorer_cannot_start_others_task(self, api):
        """PRD: "Work on a task is personal to its scorer: starting or
        submitting requires `X-User-ID` to equal the task's `scorer_id`
        (`ERR_NOT_TASK_OWNER`)."

        Design: Corner/state_machines/scorer_cannot_start_others_task
        """
        ws = setup_scoring_queued(study_type="HST")
        task = assign_task(ws["study"]["id"], ws["scorer"]["id"])
        other = create_scorer(credential="RST")

        resp = api.start_scoring_task(
            task["id"], make_scorer_headers(other["id"]))
        validate_error(resp, ApiErrorId.ERR_NOT_TASK_OWNER, 403)

        assert get_task(task["id"])["status"] == "ASSIGNED"

    def test_action_on_accepted_task_rejected(self, api):
        """PRD: "Once a task reaches `ACCEPTED` or `RECALLED` it is terminal,
        and any further action on it is rejected with `ERR_TASK_TERMINAL`, a
        guard that fires ahead of the more specific startable, submittable,
        and submitted checks."

        Design: Corner/errors/action_on_accepted_task_rejected
        """
        ws = setup_scored_study(study_type="HST")
        task = ws["task"]  # ACCEPTED; REI 5.0 (40 events * 60 / 480)
        assert task["rei"] == pytest.approx(5.0)

        resp = api.submit_scoring_task(
            task["id"],
            {"obstructive_apneas": 99, "central_apneas": 0,
             "mixed_apneas": 0, "hypopneas": 99, "reras": 0,
             "epochs_total": 960, "total_recording_time_minutes": 480},
            make_scorer_headers(ws["scorer"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_TASK_TERMINAL, 409)

        reread = get_task(task["id"])
        assert reread["status"] == "ACCEPTED"
        assert reread["rei"] == pytest.approx(5.0), (
            "The terminal task's stored indexes are immutable")

    def test_return_with_short_reason_rejected(self, api):
        """PRD: "Alternatively the physician returns a `SUBMITTED` task with a
        `reason` of at least ten characters (shorter reasons are rejected with
        `ERR_INSUFFICIENT_REASON`)"

        Design: Corner/errors/return_with_short_reason_rejected
        """
        ws = setup_scoring_queued(study_type="HST")
        task = assign_task(ws["study"]["id"], ws["scorer"]["id"])
        start_task(task["id"], ws["scorer"]["id"])
        submit_task(task["id"], ws["scorer"]["id"])

        resp = api.return_scoring_task(
            task["id"], "short",
            make_physician_headers(ws["physician"]["id"]))
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_REASON, 400)

        assert get_task(task["id"])["status"] == "SUBMITTED"

    def test_start_on_in_progress_task_rejected(self, api):
        """PRD: "Starting is permitted from `ASSIGNED` and from
        `RETURNED_FOR_REVISION` (`ERR_TASK_NOT_STARTABLE` otherwise) and moves
        the task to `IN_PROGRESS`."

        Design: Corner/validations/start_on_in_progress_task_rejected
        """
        ws = setup_scoring_queued(study_type="HST")
        task = assign_task(ws["study"]["id"], ws["scorer"]["id"])
        start_task(task["id"], ws["scorer"]["id"])

        resp = api.start_scoring_task(
            task["id"], make_scorer_headers(ws["scorer"]["id"]))
        validate_error(resp, ApiErrorId.ERR_TASK_NOT_STARTABLE, 409)

    def test_submit_on_assigned_task_rejected(self, api):
        """PRD: "Submitting requires the task to be `IN_PROGRESS`
        (`ERR_TASK_NOT_SUBMITTABLE`)."

        Design: Corner/validations/submit_on_assigned_task_rejected
        """
        ws = setup_scoring_queued(study_type="HST")
        task = assign_task(ws["study"]["id"], ws["scorer"]["id"])

        resp = api.submit_scoring_task(
            task["id"],
            {"obstructive_apneas": 20, "central_apneas": 0,
             "mixed_apneas": 0, "hypopneas": 20, "reras": 0,
             "epochs_total": 960, "total_recording_time_minutes": 480},
            make_scorer_headers(ws["scorer"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_TASK_NOT_SUBMITTABLE, 409)

    def test_accept_on_unsubmitted_task_rejected(self, api):
        """PRD: "Accepting a `SUBMITTED` task (`ERR_TASK_NOT_SUBMITTED`
        otherwise) moves it to `ACCEPTED`"

        Design: Corner/validations/accept_on_unsubmitted_task_rejected
        """
        ws = setup_scoring_queued(study_type="HST")
        task = assign_task(ws["study"]["id"], ws["scorer"]["id"])
        start_task(task["id"], ws["scorer"]["id"])

        resp = api.accept_scoring_task(
            task["id"], make_physician_headers(create_physician()["id"]))
        validate_error(resp, ApiErrorId.ERR_TASK_NOT_SUBMITTED, 409)
