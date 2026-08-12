"""Authentication, role authorization, segregation of duties, ownership."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_analysis_run,
    create_board_report,
    create_finding_under_review,
    create_manual_finding,
    create_matched_pair,
    get_payment_for_application,
    make_analyst_headers,
    make_director_headers,
    make_loan_officer_headers,
    make_officer_headers,
    make_specialist_headers,
    setup_executing_cap,
    setup_market_branch_officer,
    submit_initial,
    validate_error,
    validate_success,
    create_application,
    validate_applications,
)


def test_unauthenticated_missing_auth_headers(api):
    """PRD §2.1: "A request missing either header, or carrying a role value
    the server does not declare, is rejected with `ERR_UNAUTHENTICATED`
    (HTTP 401)."

    Design: Corner/validations/unauthenticated_missing_auth_headers
    """
    headers = {"X-User-ID": "someone", "Content-Type": "application/json"}
    resp = api.get_application(
        "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2", headers
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)


def test_rbac_role_denial_samples(api, bank_admin_headers, data_ops_headers):
    """PRD §2.1: "Once authenticated, the role is checked against the
    endpoint's permitted-role list; a mismatch is rejected with
    `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
    PRD §2.8: "then role authorization (`ERR_UNAUTHORIZED_ROLE`), then
    identity-level checks — segregation of duties and loan-officer ownership
    (`ERR_SOD_VIOLATION`, `ERR_OWNERSHIP_MISMATCH`). Only then are resource
    existence checks performed left to right (`ERR_NOT_FOUND`)".

    Design: Corner/rbac/rbac_role_denial_samples
    """
    market = validate_success(
        api.create_market(
            {"name": "Metro One", "msa_code": "M001",
             "protected_group_population_share": 0.40, "peer_group_code": "PG7"},
            bank_admin_headers,
        ),
        expected_status=201,
    )
    branch = validate_success(
        api.create_branch(
            {"market_id": market["id"], "name": "Main", "tract_minority_pct": 55.0,
             "opened_on": "2020-01-15"},
            bank_admin_headers,
        ),
        expected_status=201,
    )
    officer = validate_success(
        api.create_loan_officer(
            {"branch_id": branch["id"], "full_name": "Officer One"}, bank_admin_headers
        ),
        expected_status=201,
    )
    # LendingDataOps is not permitted to create analysis runs.
    resp1 = api.create_analysis_run(
        {"market_id": market["id"], "product_type": "CONVENTIONAL",
         "prohibited_basis": "RACE", "period_start": "2026-01-01",
         "period_end": "2026-04-01"},
        data_ops_headers,
    )
    validate_error(resp1, ApiErrorId.ERR_UNAUTHORIZED_ROLE, expected_status=403)
    # LoanOfficer is not permitted to create markets.
    resp2 = api.create_market(
        {"name": "Rogue", "msa_code": "M999", "protected_group_population_share": 0.10,
         "peer_group_code": "PG1"},
        make_loan_officer_headers(officer["id"]),
    )
    validate_error(resp2, ApiErrorId.ERR_UNAUTHORIZED_ROLE, expected_status=403)
    # RemediationSpecialist is not permitted to create findings — role check
    # fires even against a non-existent run id (authz precedes existence).
    resp3 = api.create_finding(
        {"analysis_run_id": "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2",
         "kind": "MANUAL", "notes": "x"},
        make_specialist_headers("specialist-1"),
    )
    validate_error(resp3, ApiErrorId.ERR_UNAUTHORIZED_ROLE, expected_status=403)


def test_rbac_loan_officer_entity_backed_ownership(api, bank_admin_headers, data_ops_headers):
    """PRD §2.1: "When `X-User-Role` is `LoanOfficer`, `X-User-ID` is the
    `id` of the acting `LoanOfficer` entity; ownership checks on any
    resource that references a `LoanOfficer` compare the resource's
    foreign-key field (for example, a pricing exception's `loan_officer_id`,
    or the target application's `loan_officer_id` behind a matched-pair
    dispute) to `X-User-ID`. A breach of that ownership check is rejected
    with `ERR_OWNERSHIP_MISMATCH` (HTTP 403)."

    Design: Corner/rbac/rbac_loan_officer_entity_backed_ownership
    """
    market, branch, officer1 = setup_market_branch_officer()
    officer2 = validate_success(
        api.create_loan_officer(
            {"branch_id": branch["id"], "full_name": "Officer Two"}, bank_admin_headers
        ),
        expected_status=201,
    )
    app = create_application(
        market["id"], branch["id"], officer2["id"],
        applicant_group="CONTROL", outcome="ORIGINATED", credit_score=720,
    )
    validate_applications([app["id"]])
    payload = {
        "application_id": app["id"],
        "kind": "FEE_WAIVER",
        "requested_rate_bps": 700,
        "justification": "fee",
    }
    resp = api.create_pricing_exception(
        payload, make_loan_officer_headers(officer1["id"])
    )
    validate_error(resp, ApiErrorId.ERR_OWNERSHIP_MISMATCH, expected_status=403)
    ok = api.create_pricing_exception(
        payload, make_loan_officer_headers(officer2["id"])
    )
    data = validate_success(ok, expected_status=201)
    assert data["status"] == "REQUESTED"


def test_sod_matched_pair_confirm_same_user(api, bank_admin_headers, data_ops_headers,
                                            analyst_headers, officer_headers):
    """PRD §2.9: "The confirming officer on a matched-pair review must
    differ from the `initial_reviewer_user_id`."

    Design: Corner/rbac/sod_matched_pair_confirm_same_user
    """
    market, branch, officer = setup_market_branch_officer()
    control_app = create_application(
        market["id"], branch["id"], officer["id"],
        applicant_group="CONTROL", outcome="ORIGINATED", credit_score=700,
        application_date="2026-01-05", decision_date="2026-01-20",
    )
    target_app = create_application(
        market["id"], branch["id"], officer["id"],
        applicant_group="PROTECTED_1", outcome="DENIED", credit_score=720,
        dti_pct=40.0, application_date="2026-02-01", decision_date="2026-02-10",
    )
    validate_applications([control_app["id"], target_app["id"]])
    run = create_analysis_run(market["id"])
    validate_success(api.lock_analysis_run(run["id"], analyst_headers))
    validate_success(api.compute_analysis_run(run["id"], analyst_headers))
    finding = create_finding_under_review(run["id"], kind="DENIAL_DISPARITY")
    review = create_matched_pair(finding, target_app["id"], control_app["id"])
    submit_initial(review["id"], outcome="DIFFERENTIAL_TREATMENT",
                   notes="worse outcome on comparable file",
                   reviewer_user_id="shared-1")
    resp = api.confirm_matched_pair_review(
        review["id"], make_officer_headers("shared-1")
    )
    validate_error(resp, ApiErrorId.ERR_SOD_VIOLATION, expected_status=403)
    ok = api.confirm_matched_pair_review(
        review["id"], make_officer_headers("officer-1")
    )
    data = validate_success(ok)
    assert data["status"] == "CONFIRMED"


def test_sod_disburse_by_cap_approver(api, specialist_headers):
    """PRD §2.9: "The specialist disbursing a remediation payment must
    differ from the plan's `approved_by_user_id`."

    Design: Corner/rbac/sod_disburse_by_cap_approver
    """
    ctx = setup_executing_cap(harmed_keys=("p1",), pool_cents=1_000,
                              approver_user_id="user-77")
    payment = get_payment_for_application(ctx["cap"]["id"], ctx["apps"]["p1"]["id"])
    resp = api.disburse_remediation_payment(
        payment["id"], make_specialist_headers("user-77")
    )
    validate_error(resp, ApiErrorId.ERR_SOD_VIOLATION, expected_status=403)
    ok = api.disburse_remediation_payment(
        payment["id"], make_specialist_headers("specialist-1")
    )
    data = validate_success(ok)
    assert data["status"] == "DISBURSED"


def test_sod_substantiate_by_finding_creator(api, analyst_headers):
    """PRD §2.9: "And when a finding was created manually, the
    substantiating officer must differ from its `created_by_user_id`."
    PRD §2.9: "Each breach is rejected with `ERR_SOD_VIOLATION` (HTTP 403)."

    Design: Corner/rbac/sod_substantiate_by_finding_creator
    """
    market, branch, officer = setup_market_branch_officer()
    app = create_application(
        market["id"], branch["id"], officer["id"],
        applicant_group="CONTROL", outcome="ORIGINATED", credit_score=720,
    )
    validate_applications([app["id"]])
    run = create_analysis_run(market["id"])
    validate_success(api.lock_analysis_run(run["id"], analyst_headers))
    validate_success(api.compute_analysis_run(run["id"], analyst_headers))
    finding = create_manual_finding(run["id"], kind="PRICING_DISPARITY",
                                    creator_user_id="user-x")
    validate_success(
        api.begin_review_finding(finding["id"], make_analyst_headers("user-x"))
    )
    resp = api.substantiate_finding(
        finding["id"], {"harmed_application_ids": [app["id"]]},
        make_officer_headers("user-x"),
    )
    validate_error(resp, ApiErrorId.ERR_SOD_VIOLATION, expected_status=403)
    ok = api.substantiate_finding(
        finding["id"], {"harmed_application_ids": [app["id"]]},
        make_officer_headers("officer-2"),
    )
    data = validate_success(ok)
    assert data["status"] == "SUBSTANTIATED"


def test_sod_board_report_approve_by_submitter(api, analyst_headers, officer_headers):
    """PRD §2.9: "The director approving a board report must differ from its
    `submitted_by_user_id`."

    Design: Corner/rbac/sod_board_report_approve_by_submitter
    """
    report = create_board_report()
    validate_success(api.submit_board_report(report["id"], make_officer_headers("user-9")))
    resp = api.approve_board_report(report["id"], make_director_headers("user-9"))
    validate_error(resp, ApiErrorId.ERR_SOD_VIOLATION, expected_status=403)
    ok = api.approve_board_report(report["id"], make_director_headers("director-3"))
    data = validate_success(ok)
    assert data["status"] == "APPROVED"


def test_ownership_mismatch_dispute_other_officer(
    api, bank_admin_headers, analyst_headers
):
    """PRD §3.5: "Dispute is the owning loan officer's channel: the officer
    whose `X-User-ID` equals the target application's `loan_officer_id`
    (else `ERR_OWNERSHIP_MISMATCH`) moves `INITIAL_REVIEWED` → `DISPUTED`
    with the supplied `reason` stored as `dispute_reason`."

    Design: Corner/rbac/ownership_mismatch_dispute_other_officer
    """
    market, branch, officer1 = setup_market_branch_officer()
    officer2 = validate_success(
        api.create_loan_officer(
            {"branch_id": branch["id"], "full_name": "Officer Two"}, bank_admin_headers
        ),
        expected_status=201,
    )
    control_app = create_application(
        market["id"], branch["id"], officer1["id"],
        applicant_group="CONTROL", outcome="ORIGINATED", credit_score=700,
        application_date="2026-01-05", decision_date="2026-01-20",
    )
    target_app = create_application(
        market["id"], branch["id"], officer1["id"],
        applicant_group="PROTECTED_1", outcome="DENIED", credit_score=720,
        dti_pct=40.0, application_date="2026-02-01", decision_date="2026-02-10",
    )
    validate_applications([control_app["id"], target_app["id"]])
    run = create_analysis_run(market["id"])
    validate_success(api.lock_analysis_run(run["id"], analyst_headers))
    validate_success(api.compute_analysis_run(run["id"], analyst_headers))
    finding = create_finding_under_review(run["id"], kind="DENIAL_DISPARITY")
    review = create_matched_pair(finding, target_app["id"], control_app["id"])
    submit_initial(review["id"], outcome="DIFFERENTIAL_TREATMENT",
                   notes="worse outcome", reviewer_user_id="analyst-1")
    resp = api.dispute_matched_pair_review(
        review["id"], {"reason": "not my file"},
        make_loan_officer_headers(officer2["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_OWNERSHIP_MISMATCH, expected_status=403)
    ok = api.dispute_matched_pair_review(
        review["id"], {"reason": "contest comparability"},
        make_loan_officer_headers(officer1["id"]),
    )
    data = validate_success(ok)
    assert data["status"] == "DISPUTED"
