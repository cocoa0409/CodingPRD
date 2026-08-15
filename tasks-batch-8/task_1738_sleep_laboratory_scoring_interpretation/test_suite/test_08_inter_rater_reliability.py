"""Inter-rater reliability: case adjudication, per-case agreement metrics,
the pinned rolling-index rounding order, scorer status recompute, and the
REMEDIATION recall cascade."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    adjudicate_case,
    adjudicated_case_for_rescorer,
    assert_inter_rater_case,
    assert_scorer,
    assign_task,
    create_scorer,
    get_scorer,
    get_study,
    get_success_data,
    get_task,
    open_inter_rater_case,
    setup_double_scored_study,
    setup_open_primary_task,
    setup_scoring_queued,
    setup_staff,
    validate_error,
    validate_paginated,
)

SCHED = TEST_USERS["scheduler_headers"]
DIRECTOR = TEST_USERS["lab_director_headers"]


def _three_concordant_cases(staff):
    """Three adjudicated cases for staff's rescorer with per-case agreement
    86.30 (863/1000), 85.67 (257/300), and 87.67 (789/900); the rescore tasks
    carry REI 9.5 against the primary's 10.0 (delta 0.5, always concordant
    on the delta leg)."""
    rescorer = staff["rescorer"]
    case_a = adjudicated_case_for_rescorer(
        staff, rescorer, 863, rescore_epochs=1000)
    case_b = adjudicated_case_for_rescorer(
        staff, rescorer, 257, rescore_epochs=300)
    case_c = adjudicated_case_for_rescorer(
        staff, rescorer, 789, rescore_epochs=900)
    return case_a, case_b, case_c


class TestRollingAgreementRoundingOrder:
    def test_per_case_percent_agreement_rounded(self, api):
        """PRD: "The `percent_agreement` is `epochs_concordant` expressed as a
        percentage of the rescore task's `epochs_total`, rounded half-up to
        two decimals."
        PRD: "**Inter-rater agreement metrics** (`ahi_delta`,
        `percent_agreement`, `rolling_agreement_index`) use 2 decimal places,
        round-half-up."

        Design: Difficulty/combinatorial_formula/rolling_agreement_per_case_then_mean_rounding_order
        """
        staff = setup_staff(with_rescorer=True)
        case_a, case_b, case_c = _three_concordant_cases(staff)

        # 863*100/1000 = 86.30; 257*100/300 = 85.6667 -> 85.67;
        # 789*100/900 = 87.6667 -> 87.67 — each rounded at case level.
        assert case_a["percent_agreement"] == pytest.approx(86.30)
        assert case_b["percent_agreement"] == pytest.approx(85.67)
        assert case_c["percent_agreement"] == pytest.approx(87.67)
        for case in (case_a, case_b, case_c):
            assert_inter_rater_case(case)
            assert case["status"] == "ADJUDICATED"
            assert case["concordant"] is True

    def test_rolling_index_averages_stored_rounded_values(self, api):
        """PRD: "The rounding is applied per case before any rolling mean is
        computed: the rolling index averages the per-case `percent_agreement`
        values exactly as stored (each already rounded to 2 decimals), then
        rounds that mean half-up to 2 decimals. Averaging raw unrounded ratios
        instead is a violation of this contract."
        PRD: "`WATCH` when at least three cases exist, the rolling index is at
        least 80.0 but below 90.0, and the consecutive count is below two"

        Design: Difficulty/combinatorial_formula/rolling_agreement_per_case_then_mean_rounding_order
        """
        staff = setup_staff(with_rescorer=True)
        _three_concordant_cases(staff)

        scorer = get_scorer(staff["rescorer"]["id"])
        assert_scorer(scorer)
        # (86.30 + 85.67 + 87.67) / 3 = 86.54667 -> 86.55; averaging the raw
        # ratios first would yield 86.54 — the pinned order is observable.
        assert scorer["rolling_agreement_index"] == pytest.approx(86.55)
        assert scorer["rolling_agreement_index"] != pytest.approx(86.54)
        assert scorer["consecutive_nonconcordant"] == 0
        assert scorer["reliability_status"] == "WATCH"


class TestRemediationRecallCascade:
    def _remediation_setup(self):
        """Rescorer with one prior non-concordant adjudication, an open
        IN_PROGRESS PRIMARY task on a second study, and a second
        non-concordant case ready to adjudicate."""
        staff = setup_staff(with_rescorer=True)
        rescorer = staff["rescorer"]
        # Non-concordant #1: REI 10.0 primary vs 3.3 rescore, 800/1000 = 80.0.
        adjudicated_case_for_rescorer(
            staff, rescorer, 800, rescore_events=(10, 0, 0, 10))
        # The rescorer's open PRIMARY task (the recall-cascade target).
        open_ws = setup_open_primary_task(rescorer)
        assert open_ws["task"]["status"] == "IN_PROGRESS"
        assert open_ws["study"]["status"] == "SCORING_IN_PROGRESS"
        return staff, rescorer, open_ws

    def test_consecutive_nonconcordant_flips_remediation(self, api):
        """PRD: "A concordant case resets the scorer's
        `consecutive_nonconcordant` to zero; a non-concordant case increments
        it by one."
        PRD: "The case is `concordant` when the delta is at most 2.0 and the
        percent agreement is at least 85.0."
        PRD: "`REMEDIATION` when `consecutive_nonconcordant` has reached two —
        regardless of case count" and "it remains null while the scorer has
        fewer than three adjudicated cases."

        Design: Difficulty/transitive_cascade/adjudication_remediation_recall_depth3
        """
        staff, rescorer, _ = self._remediation_setup()

        case2 = adjudicated_case_for_rescorer(
            staff, rescorer, 800, rescore_events=(10, 0, 0, 10))
        assert case2["percent_agreement"] == pytest.approx(80.0)
        assert case2["ahi_delta"] == pytest.approx(6.7)  # |10.0 - 3.3|
        assert case2["concordant"] is False

        scorer = get_scorer(rescorer["id"])
        assert scorer["consecutive_nonconcordant"] == 2, (
            "Link 1: the second consecutive non-concordant adjudication")
        assert scorer["reliability_status"] == "REMEDIATION", (
            "Link 2: the consecutive threshold flips status regardless of "
            "case count")
        assert scorer["rolling_agreement_index"] is None, (
            "Two adjudicated cases is fewer than three — no rolling index yet")

    def test_remediation_recalls_open_tasks_and_reverts_study(self, api):
        """PRD: "A scorer entering `REMEDIATION` fires the recall cascade:
        every one of that scorer's tasks in `ASSIGNED`, `IN_PROGRESS`, or
        `RETURNED_FOR_REVISION` is recalled to `RECALLED`, and each recalled
        `PRIMARY` task pushes its study back from `SCORING_IN_PROGRESS` to
        `SCORING_QUEUED` for reassignment."

        Design: Difficulty/transitive_cascade/adjudication_remediation_recall_depth3
        """
        staff, rescorer, open_ws = self._remediation_setup()

        adjudicated_case_for_rescorer(
            staff, rescorer, 800, rescore_events=(10, 0, 0, 10))

        task = get_task(open_ws["task"]["id"])
        assert task["status"] == "RECALLED", (
            "Link 3: the open task is recalled when the scorer enters "
            "REMEDIATION")
        study = get_study(open_ws["study"]["id"])
        assert study["status"] == "SCORING_QUEUED", (
            "The recalled PRIMARY's study reverts to the scoring queue")


class TestOpenTaskLedgerConservedAcrossRecall:
    def test_assign_recall_pair_leaves_zero_open_tasks(self, api):
        """PRD: "A scorer entering `REMEDIATION` fires the recall cascade:
        every one of that scorer's tasks in `ASSIGNED`, `IN_PROGRESS`, or
        `RETURNED_FOR_REVISION` is recalled to `RECALLED`, and each recalled
        `PRIMARY` task pushes its study back from `SCORING_IN_PROGRESS` to
        `SCORING_QUEUED` for reassignment."

        Design: Difficulty/compensating_invariant/scorer_open_task_ledger_conserved_across_recall
        """
        staff = setup_staff(with_rescorer=True)
        rescorer = staff["rescorer"]
        adjudicated_case_for_rescorer(
            staff, rescorer, 800, rescore_events=(10, 0, 0, 10))
        open_ws = setup_open_primary_task(rescorer)

        _, meta = validate_paginated(api.list_scoring_tasks(
            DIRECTOR, {"scorer_id": rescorer["id"], "status": "IN_PROGRESS"}))
        assert meta["total_count"] == 1, (
            "Exactly one open task: the PRIMARY just started (rescore tasks "
            "are ACCEPTED and terminal)")

        adjudicated_case_for_rescorer(
            staff, rescorer, 800, rescore_events=(10, 0, 0, 10))

        assert get_task(open_ws["task"]["id"])["status"] == "RECALLED"
        for open_state in ("ASSIGNED", "IN_PROGRESS", "RETURNED_FOR_REVISION"):
            _, meta = validate_paginated(api.list_scoring_tasks(
                DIRECTOR, {"scorer_id": rescorer["id"],
                           "status": open_state}))
            assert meta["total_count"] == 0, (
                f"The assign/recall pair leaves zero tasks in {open_state}")

    def test_recalled_study_accepts_reassignment(self, api):
        """PRD: "A scorer entering `REMEDIATION` fires the recall cascade:
        every one of that scorer's tasks in `ASSIGNED`, `IN_PROGRESS`, or
        `RETURNED_FOR_REVISION` is recalled to `RECALLED`, and each recalled
        `PRIMARY` task pushes its study back from `SCORING_IN_PROGRESS` to
        `SCORING_QUEUED` for reassignment." A primary assignment requires the
        study to be `SCORING_QUEUED`, so the reverted study accepts a fresh
        PRIMARY for another scorer.

        Design: Difficulty/compensating_invariant/scorer_open_task_ledger_conserved_across_recall
        """
        staff = setup_staff(with_rescorer=True)
        rescorer = staff["rescorer"]
        adjudicated_case_for_rescorer(
            staff, rescorer, 800, rescore_events=(10, 0, 0, 10))
        open_ws = setup_open_primary_task(rescorer)

        adjudicated_case_for_rescorer(
            staff, rescorer, 800, rescore_events=(10, 0, 0, 10))
        assert get_study(open_ws["study"]["id"])["status"] == "SCORING_QUEUED"

        replacement = assign_task(open_ws["study"]["id"],
                                  staff["scorer"]["id"], "PRIMARY")
        assert replacement["status"] == "ASSIGNED", (
            "The reverted study is back in the queue and reassignable")


class TestRemediationGuards:
    def test_remediation_blocks_new_assignment(self, api):
        """PRD: "A scorer whose `reliability_status` is `REMEDIATION` may not
        receive new assignments at all (`ERR_SCORER_IN_REMEDIATION`)."

        Design: Corner/errors/remediation_blocks_new_assignment
        """
        staff = setup_staff(with_rescorer=True)
        rescorer = staff["rescorer"]
        adjudicated_case_for_rescorer(
            staff, rescorer, 800, rescore_events=(10, 0, 0, 10))
        adjudicated_case_for_rescorer(
            staff, rescorer, 800, rescore_events=(10, 0, 0, 10))
        assert get_scorer(rescorer["id"])["reliability_status"] == \
            "REMEDIATION"

        ws = setup_scoring_queued(study_type="HST")
        resp = api.create_scoring_task(
            {"study_id": ws["study"]["id"], "scorer_id": rescorer["id"],
             "assignment_kind": "PRIMARY"},
            DIRECTOR,
        )
        validate_error(resp, ApiErrorId.ERR_SCORER_IN_REMEDIATION, 422)

        _, meta = validate_paginated(api.list_scoring_tasks(
            DIRECTOR, {"study_id": ws["study"]["id"]}))
        assert meta["total_count"] == 0

    def test_reinstate_non_remediation_rejected(self, api):
        """PRD: "A scorer may leave remediation only through the
        `LabDirector`'s reinstatement, which requires `reliability_status` of
        `REMEDIATION` (`ERR_SCORER_NOT_REMEDIATION`), returns the scorer to
        `PROVISIONAL`, and resets `consecutive_nonconcordant` to zero."

        Design: Corner/errors/reinstate_non_remediation_rejected
        """
        scorer = create_scorer()
        assert scorer["reliability_status"] == "PROVISIONAL"

        resp = api.reinstate_scorer(scorer["id"], DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_SCORER_NOT_REMEDIATION, 409)

        assert get_scorer(scorer["id"])["reliability_status"] == "PROVISIONAL"


class TestCaseIntegrity:
    def test_duplicate_case_for_rescore_rejected(self, api):
        """PRD: "a rescore task may appear in only one case
        (`ERR_CASE_ALREADY_EXISTS`)."

        Design: Corner/errors/duplicate_case_for_rescore_rejected
        """
        ws = setup_double_scored_study()
        open_inter_rater_case(ws)

        resp = api.create_inter_rater_case(
            {"study_id": ws["study"]["id"],
             "primary_task_id": ws["task"]["id"],
             "rescore_task_id": ws["rescore_task"]["id"]},
            DIRECTOR,
        )
        validate_error(resp, ApiErrorId.ERR_CASE_ALREADY_EXISTS, 409)

        _, meta = validate_paginated(api.list_inter_rater_cases(
            DIRECTOR, {"rescore_task_id": ws["rescore_task"]["id"]}))
        assert meta["total_count"] == 1

    def test_case_with_swapped_kinds_rejected(self, api):
        """PRD: "Both tasks must be `ACCEPTED`, of kinds `PRIMARY` and
        `RELIABILITY_RESCORE` respectively, on the same study, and staged by
        different scorers (`ERR_CASE_TASKS_INVALID`)"

        Design: Corner/errors/case_with_swapped_kinds_rejected
        """
        ws = setup_double_scored_study()

        resp = api.create_inter_rater_case(
            {"study_id": ws["study"]["id"],
             "primary_task_id": ws["rescore_task"]["id"],
             "rescore_task_id": ws["task"]["id"]},
            DIRECTOR,
        )
        validate_error(resp, ApiErrorId.ERR_CASE_TASKS_INVALID, 422)

        _, meta = validate_paginated(api.list_inter_rater_cases(
            DIRECTOR, {"study_id": ws["study"]["id"]}))
        assert meta["total_count"] == 0

    def test_double_adjudication_rejected(self, api):
        """PRD: "Adjudicating an `OPEN` case (`ERR_CASE_INVALID_STATE`
        otherwise) supplies `epochs_concordant`, the number of epochs staged
        identically by both scorers — at least zero and no more than the
        rescore task's `epochs_total` (`ERR_INVALID_REQUEST`)."

        Design: Corner/validations/double_adjudication_rejected
        """
        ws = setup_double_scored_study(
            primary_submit={"obstructive_apneas": 20, "hypopneas": 20,
                            "epochs_total": 1000},
            rescore_submit={"obstructive_apneas": 20, "hypopneas": 20,
                            "epochs_total": 1000})
        case = open_inter_rater_case(ws)
        adjudicated = adjudicate_case(case["id"], 900)
        assert adjudicated["percent_agreement"] == pytest.approx(90.0)
        assert adjudicated["concordant"] is True

        resp = api.adjudicate_inter_rater_case(case["id"], 100, DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_CASE_INVALID_STATE, 409)

        reread = get_success_data(api.get_inter_rater_case(case["id"],
                                                           DIRECTOR))
        assert reread["percent_agreement"] == pytest.approx(90.0), (
            "The rejected re-adjudication does not double-apply")
        assert reread["concordant"] is True
