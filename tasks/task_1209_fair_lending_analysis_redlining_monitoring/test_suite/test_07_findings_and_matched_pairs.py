"""Matched-pair review cycle and the substantiation evidence gate."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_analysis_run,
    create_application,
    create_finding_under_review,
    create_matched_pair,
    make_loan_officer_headers,
    make_officer_headers,
    setup_market_branch_officer,
    submit_initial,
    validate_applications,
    validate_error,
    validate_success,
)


def _setup_denial_review(api):
    """Computed run over (CONTROL ORIGINATED credit 700, PROTECTED_1 DENIED
    credit 720); DENIAL_DISPARITY finding UNDER_REVIEW; matched-pair review
    INITIAL_REVIEWED with outcome DIFFERENTIAL_TREATMENT by analyst-1."""
    market, branch, officer = setup_market_branch_officer()
    control_app = create_application(
        market["id"], branch["id"], officer["id"],
        applicant_group="CONTROL", outcome="ORIGINATED", credit_score=700,
        dti_pct=36.0, application_date="2026-01-05", decision_date="2026-01-20",
    )
    target_app = create_application(
        market["id"], branch["id"], officer["id"],
        applicant_group="PROTECTED_1", outcome="DENIED", credit_score=720,
        dti_pct=40.0, application_date="2026-02-01", decision_date="2026-02-10",
    )
    validate_applications([control_app["id"], target_app["id"]])
    run = create_analysis_run(market["id"])
    validate_success(
        api.lock_analysis_run(run["id"], TEST_USERS["analyst_headers"])
    )
    validate_success(
        api.compute_analysis_run(run["id"], TEST_USERS["analyst_headers"])
    )
    finding = create_finding_under_review(run["id"], kind="DENIAL_DISPARITY")
    review = create_matched_pair(finding, target_app["id"], control_app["id"])
    return {
        "market": market, "branch": branch, "officer": officer,
        "control_app": control_app, "target_app": target_app,
        "run": run, "finding": finding, "review": review,
    }


def test_matched_pair_dispute_rereview_cycle_overwrites_initial_record(api):
    """PRD §3.5: "A disputed pair is re-reviewed by a fresh initial
    submission, which overwrites `initial_outcome` and
    `initial_reviewer_user_id` as the cycle repeats."
    PRD §3.5: "Dispute is the owning loan officer's channel: the officer
    whose `X-User-ID` equals the target application's `loan_officer_id`
    (else `ERR_OWNERSHIP_MISMATCH`) moves `INITIAL_REVIEWED` → `DISPUTED`
    with the supplied `reason` stored as `dispute_reason`."

    Design: Difficulty/non_linear_state_machine/matched_pair_dispute_rereview_cycle
    """
    ctx = _setup_denial_review(api)
    review = ctx["review"]
    first = submit_initial(
        review["id"], outcome="DIFFERENTIAL_TREATMENT",
        notes="file shows weaker documentation accepted for control",
        reviewer_user_id="analyst-1",
    )
    assert first["status"] == "INITIAL_REVIEWED"
    assert first["initial_reviewer_user_id"] == "analyst-1"
    disputed = validate_success(
        api.dispute_matched_pair_review(
            review["id"],
            {"reason": "officer contests comparability of documentation standard"},
            make_loan_officer_headers(ctx["officer"]["id"]),
        )
    )
    assert disputed["status"] == "DISPUTED"
    assert disputed["dispute_reason"] == (
        "officer contests comparability of documentation standard"
    )
    reseen = submit_initial(
        review["id"], outcome="COMPARABLE_TREATMENT",
        notes="second look: documentation equivalent",
        reviewer_user_id="analyst-2",
    )
    assert reseen["status"] == "INITIAL_REVIEWED", (
        "cycle edge DISPUTED -> INITIAL_REVIEWED"
    )
    assert reseen["initial_outcome"] == "COMPARABLE_TREATMENT", (
        "re-review overwrites initial_outcome"
    )
    assert reseen["initial_reviewer_user_id"] == "analyst-2", (
        "re-review overwrites initial_reviewer_user_id"
    )
    assert reseen["dispute_reason"] == (
        "officer contests comparability of documentation standard"
    ), "dispute record is preserved through the cycle"


def test_matched_pair_dispute_rereview_cycle_reaches_confirmed(api):
    """PRD §3.5: "Confirmation by a `FairLendingOfficer` moves
    `INITIAL_REVIEWED` → `CONFIRMED` with `confirmed_by_user_id` recorded,
    subject to segregation of duties: the confirmer must differ from the
    initial reviewer, else `ERR_SOD_VIOLATION`."
    PRD §3.5: "`CONFIRMED` and `SUPERSEDED` are terminal."

    Design: Difficulty/non_linear_state_machine/matched_pair_dispute_rereview_cycle
    """
    ctx = _setup_denial_review(api)
    review = ctx["review"]
    submit_initial(review["id"], outcome="DIFFERENTIAL_TREATMENT",
                   notes="worse outcome", reviewer_user_id="analyst-1")
    validate_success(
        api.dispute_matched_pair_review(
            review["id"], {"reason": "contest comparability"},
            make_loan_officer_headers(ctx["officer"]["id"]),
        )
    )
    submit_initial(review["id"], outcome="COMPARABLE_TREATMENT",
                   notes="second look", reviewer_user_id="analyst-2")
    confirmed = validate_success(
        api.confirm_matched_pair_review(
            review["id"], make_officer_headers("officer-1")
        )
    )
    assert confirmed["status"] == "CONFIRMED"
    assert confirmed["confirmed_by_user_id"] == "officer-1"


def test_substantiation_blocked_without_confirmed_matched_pair(api):
    """PRD §3.4: "For findings of kind `DENIAL_DISPARITY` or
    `OVERRIDE_ASYMMETRY`, at least one linked matched-pair review must
    already be in `CONFIRMED` status, else
    `ERR_NO_CONFIRMED_MATCHED_PAIR` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/substantiation_requires_confirmed_matched_pair
    """
    ctx = _setup_denial_review(api)
    review = ctx["review"]
    submit_initial(review["id"], outcome="DIFFERENTIAL_TREATMENT",
                   notes="comparable file, worse outcome",
                   reviewer_user_id="analyst-1")
    resp = api.substantiate_finding(
        ctx["finding"]["id"],
        {"harmed_application_ids": [ctx["target_app"]["id"]]},
        make_officer_headers("officer-sub"),
    )
    validate_error(resp, ApiErrorId.ERR_NO_CONFIRMED_MATCHED_PAIR,
                   expected_status=409)


def test_substantiation_succeeds_once_pair_confirmed(api):
    """PRD §3.4: "The officer supplies `harmed_application_ids` — an ordered
    list of harmed application ids whose order is client-pinned and later
    drives remediation allocation — and the finding moves to
    `SUBSTANTIATED` with `substantiated_by_user_id` recorded."

    Design: Difficulty/cross_entity_state_dependency/substantiation_requires_confirmed_matched_pair
    """
    ctx = _setup_denial_review(api)
    review = ctx["review"]
    submit_initial(review["id"], outcome="DIFFERENTIAL_TREATMENT",
                   notes="comparable file, worse outcome",
                   reviewer_user_id="analyst-1")
    validate_error(
        api.substantiate_finding(
            ctx["finding"]["id"],
            {"harmed_application_ids": [ctx["target_app"]["id"]]},
            make_officer_headers("officer-sub"),
        ),
        ApiErrorId.ERR_NO_CONFIRMED_MATCHED_PAIR,
        expected_status=409,
    )
    validate_success(
        api.confirm_matched_pair_review(review["id"], make_officer_headers("officer-1"))
    )
    done = validate_success(
        api.substantiate_finding(
            ctx["finding"]["id"],
            {"harmed_application_ids": [ctx["target_app"]["id"]]},
            make_officer_headers("officer-sub"),
        )
    )
    assert done["status"] == "SUBSTANTIATED"
    assert done["harmed_application_ids"] == [ctx["target_app"]["id"]]
    assert done["substantiated_by_user_id"] == "officer-sub"
