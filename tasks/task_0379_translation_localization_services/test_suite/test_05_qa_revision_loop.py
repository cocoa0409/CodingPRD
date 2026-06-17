"""Translation submission, the cyclic QA revision loop, the QA score and its pass
threshold, and the submit/QA-report preconditions.

Covers difficulty rules `non_linear_state_machine` (QA revision cycle) and
`boundary_precision_check` (QA pass threshold), plus corner `state_machines`,
`calculations`, and `errors` instances.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
    create_client, create_rate_card, create_linguist, create_project, add_job,
    quote_and_approve, assign, accept_as_translator, accept_as_reviewer,
    current_job_version, make_translator_headers, make_reviewer_headers,
    create_qa_report_payload,
    setup_job_in_qa, setup_job_in_progress, setup_foundations,
)

PM = TEST_USERS["pm_headers"]


# ─── non_linear_state_machine: QA fail -> revision -> pass cycle ────────────
def test_qa_fail_then_pass_revision_cycle(api):
    """PRD §3.6: "A `PASS` outcome drives the job from `IN_QA` to `QA_PASSED`; a `FAIL` outcome drives it from `IN_QA` to `REVISION`."
    PRD §3.6: "A job in `REVISION` is reworked by the same active translator, who submits
    again, advancing the job from `REVISION` back to `IN_QA`. ... A revision resubmission
    increments the job's `revision_rounds` by one and increments the job's `version` by
    one."
    PRD §3.6: "A `PASS` outcome drives the job from `IN_QA` to `QA_PASSED`".

    First QA fails (88.5 < 90) -> REVISION; resubmit (revision_rounds=1) -> IN_QA;
    second QA passes (99.6) -> QA_PASSED.

    Design: Difficulty/non_linear_state_machine/nlsm_projectjob_qa_revision_cycle
    """
    ctx = setup_job_in_qa()  # job IN_QA after first submit
    # First QA report: weighted 1*10 + 3*5 + 5*1 = 30 over 2600 -> 88.5 -> FAIL.
    get_success_data(api.create_qa_report(
        ctx["job"]["id"],
        create_qa_report_payload(ctx["reviewer_assignment"]["id"], 2600,
                                 critical_count=1, major_count=3, minor_count=5),
        make_reviewer_headers(ctx["reviewer"]["id"])))
    in_revision = validate_success(api.get_job(ctx["job"]["id"], PM), 200)
    assert in_revision["status"] == "REVISION", f"got {in_revision['status']}"
    # Resubmit from REVISION -> IN_QA (revision_rounds += 1).
    get_success_data(api.submit_translation(
        ctx["job"]["id"], make_translator_headers(ctx["translator"]["id"])))
    # Second QA report: weighted 1 over 2600 -> 99.6 -> PASS.
    get_success_data(api.create_qa_report(
        ctx["job"]["id"],
        create_qa_report_payload(ctx["reviewer_assignment"]["id"], 2600,
                                 critical_count=0, major_count=0, minor_count=1),
        make_reviewer_headers(ctx["reviewer"]["id"])))
    final = validate_success(api.get_job(ctx["job"]["id"], PM), 200)
    assert final["status"] == "QA_PASSED", f"got {final['status']}"
    assert final["revision_rounds"] == 1, f"got {final['revision_rounds']}"
    assert final["latest_qa_score"] == 99.6, f"got {final['latest_qa_score']}"


def test_qa_fail_sets_revision_and_latest_score(api):
    """PRD §3.6: "Filing a report sets the job's `latest_qa_score` to the report's `score`
    and increments the job's `version` by one. ... A `FAIL` outcome drives it from
    `IN_QA` to `REVISION`."

    Second probe of the cycle's failing hop in isolation: a FAIL report (88.5) drives the
    job to REVISION and records latest_qa_score 88.5.

    Design: Difficulty/non_linear_state_machine/nlsm_projectjob_qa_revision_cycle
    """
    ctx = setup_job_in_qa()
    get_success_data(api.create_qa_report(
        ctx["job"]["id"],
        create_qa_report_payload(ctx["reviewer_assignment"]["id"], 2600,
                                 critical_count=1, major_count=3, minor_count=5),
        make_reviewer_headers(ctx["reviewer"]["id"])))
    job = validate_success(api.get_job(ctx["job"]["id"], PM), 200)
    assert job["status"] == "REVISION", f"got {job['status']}"
    assert job["latest_qa_score"] == 88.5, f"got {job['latest_qa_score']}"
    assert job["revision_rounds"] == 0, \
        f"a first QA fail does not count a revision round yet, got {job['revision_rounds']}"


# ─── boundary_precision_check: QA pass threshold at 90.0 ────────────────────
def test_qa_score_at_threshold_passes(api):
    """PRD §3.10: "The `outcome` is `PASS` when the score is at least ninety, and `FAIL`
    otherwise."
    PRD §3.6: "A `PASS` outcome drives the job from `IN_QA` to `QA_PASSED`".

    Boundary X: weighted errors 2*10 + 1*5 + 1*1 = 26 over 2600 -> score exactly 90.0,
    which is the inclusive PASS threshold.

    Design: Difficulty/boundary_precision_check/bpc_qa_pass_threshold_at_90
    """
    ctx = setup_job_in_qa()
    report = validate_success(api.create_qa_report(
        ctx["job"]["id"],
        create_qa_report_payload(ctx["reviewer_assignment"]["id"], 2600,
                                 critical_count=2, major_count=1, minor_count=1),
        make_reviewer_headers(ctx["reviewer"]["id"])), 201)
    assert report["score"] == 90.0, f"expected 90.0, got {report['score']}"
    assert report["outcome"] == "PASS", f"got {report['outcome']}"
    job = validate_success(api.get_job(ctx["job"]["id"], PM), 200)
    assert job["status"] == "QA_PASSED", f"got {job['status']}"


def test_qa_score_just_below_threshold_fails(api):
    """PRD §3.10: "The `outcome` is `PASS` when the score is at least ninety, and `FAIL`
    otherwise."
    PRD §3.6: "A `PASS` outcome drives the job from `IN_QA` to `QA_PASSED`; a `FAIL` outcome drives it from `IN_QA` to `REVISION`."

    Boundary X-side: weighted errors 2*10 + 1*5 + 2*1 = 27 over 2600 -> score 89.6, just
    below the threshold, so the outcome is FAIL.

    Design: Difficulty/boundary_precision_check/bpc_qa_pass_threshold_at_90
    """
    ctx = setup_job_in_qa()
    report = validate_success(api.create_qa_report(
        ctx["job"]["id"],
        create_qa_report_payload(ctx["reviewer_assignment"]["id"], 2600,
                                 critical_count=2, major_count=1, minor_count=2),
        make_reviewer_headers(ctx["reviewer"]["id"])), 201)
    assert report["score"] == 89.6, f"expected 89.6, got {report['score']}"
    assert report["outcome"] == "FAIL", f"got {report['outcome']}"
    job = validate_success(api.get_job(ctx["job"]["id"], PM), 200)
    assert job["status"] == "REVISION", f"got {job['status']}"


# ─── corner calculations: QA score floor at 0.0 ────────────────────────────
def test_qa_score_floor_at_zero(api):
    """PRD §3.10: "The `score` is one hundred minus that penalty, rounded half up to one
    decimal place; if the result is negative it is floored at zero point zero."

    30 critical (weighted 300) over 100 words -> penalty 3000 -> raw -2900 -> floored
    to 0.0, outcome FAIL.

    Design: Corner/calculations/qa_score_floor_at_zero
    """
    ctx = setup_job_in_qa()
    report = validate_success(api.create_qa_report(
        ctx["job"]["id"],
        create_qa_report_payload(ctx["reviewer_assignment"]["id"], 100,
                                 critical_count=30, major_count=0, minor_count=0),
        make_reviewer_headers(ctx["reviewer"]["id"])), 201)
    assert report["score"] == 0.0, f"expected 0.0, got {report['score']}"
    assert report["outcome"] == "FAIL", f"got {report['outcome']}"
    job = validate_success(api.get_job(ctx["job"]["id"], PM), 200)
    assert job["status"] == "REVISION", f"got {job['status']}"


# ─── corner state_machines / errors: submit preconditions ──────────────────
def test_submit_translation_without_reviewer_returns_no_reviewer(api):
    """PRD §3.6: "a reviewer must already be lined up — an `IN_PROGRESS` reviewer
    assignment must exist on the job — otherwise `ERR_NO_REVIEWER_ASSIGNED`."

    Design: Corner/state_machines/submit_translation_without_reviewer_returns_no_reviewer
    """
    client = create_client()
    rate_card = create_rate_card()
    translator = create_linguist()
    project = create_project(client["id"], rate_card["id"])
    job = add_job(project["id"])
    quote_and_approve({"project": project, "client": client})
    ta = assign(job["id"], translator["id"], "TRANSLATOR")
    accept_as_translator(ta["id"], translator["id"])  # job TRANSLATING, no reviewer
    resp = api.submit_translation(job["id"], make_translator_headers(translator["id"]))
    validate_error(resp, ApiErrorId.ERR_NO_REVIEWER_ASSIGNED.value, 409)


def test_submit_translation_by_non_translator_returns_not_assigned(api):
    """PRD §3.6: "Submission may be performed only by the linguist who is the job's
    `ACCEPTED` or `IN_PROGRESS` translator, otherwise `ERR_NOT_ASSIGNED_TRANSLATOR`".

    A different linguist (not the job's active translator) calls submit-translation.

    Design: Corner/errors/error_not_assigned_translator_triggerable
    """
    client = create_client()
    rate_card = create_rate_card()
    translator = create_linguist(full_name="T")
    other = create_linguist(full_name="Other")
    project = create_project(client["id"], rate_card["id"])
    job = add_job(project["id"], bands={"quoted_no_match_words": 1000})
    quote_and_approve({"project": project, "client": client})
    ta = assign(job["id"], translator["id"], "TRANSLATOR")
    accept_as_translator(ta["id"], translator["id"])
    resp = api.submit_translation(job["id"], make_translator_headers(other["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_ASSIGNED_TRANSLATOR.value, 409)
