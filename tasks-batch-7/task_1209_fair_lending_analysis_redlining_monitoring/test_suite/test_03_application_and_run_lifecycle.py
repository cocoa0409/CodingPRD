"""Application intake states and analysis-run lifecycle gates."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_analysis_run,
    create_application,
    create_computed_run,
    make_director_headers,
    make_loan_officer_headers,
    setup_adverse_run,
    setup_market_branch_officer,
    validate_applications,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)


def test_validate_excluded_application_returns_already_terminal(
    api, bank_admin_headers, data_ops_headers
):
    """PRD §3.2: "Exclusion moves an application from either `RECEIVED` or
    `VALIDATED` to the terminal `EXCLUDED` state".
    PRD §2.8: "(`ERR_INVALID_STATE`, or `ERR_ALREADY_TERMINAL` when the
    target is already in a terminal state)".

    Design: Corner/state_machines/validate_excluded_application_returns_already_terminal
    """
    market, branch, officer = setup_market_branch_officer()
    app = create_application(market["id"], branch["id"], officer["id"])
    validate_success(api.exclude_application(app["id"], data_ops_headers))
    resp = api.validate_application(app["id"], data_ops_headers)
    validate_error(resp, ApiErrorId.ERR_ALREADY_TERMINAL, expected_status=409)
    current = validate_success(api.get_application(app["id"], data_ops_headers))
    assert current["status"] == "EXCLUDED"


def test_unlock_from_draft_returns_invalid_state(api, analyst_headers):
    """PRD §3.3: "Unlocking returns the run to `DRAFT`, clears `locked_at`,
    and discards the snapshot — but only while the run has no linked
    findings in any status".
    PRD §5: "ERR_INVALID_STATE | 409".

    Design: Corner/state_machines/unlock_from_draft_returns_invalid_state
    """
    market = validate_success(
        api.create_market(
            {"name": "Metro One", "msa_code": "M001",
             "protected_group_population_share": 0.40, "peer_group_code": "PG7"},
            TEST_USERS["bank_admin_headers"],
        ),
        expected_status=201,
    )
    run = create_analysis_run(market["id"])
    resp = api.unlock_analysis_run(run["id"], analyst_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
    current = validate_success(api.get_analysis_run(run["id"], analyst_headers))
    assert current["status"] == "DRAFT"


def test_unlock_blocked_when_findings_exist(api, analyst_headers):
    """PRD §3.3: "Unlocking returns the run to `DRAFT`, clears `locked_at`,
    and discards the snapshot — but only while the run has no linked
    findings in any status; once any finding exists, unlock is rejected
    with `ERR_RUN_HAS_OPEN_FINDINGS` (HTTP 409)."

    Design: Corner/state_machines/unlock_blocked_when_findings_exist
    """
    _market, _branch, _officer, run, findings = setup_adverse_run()
    assert run["status"] == "COMPUTED"
    assert len(findings) == 1, f"expected the auto finding, got {len(findings)}"
    assert run["open_finding_count"] == 1
    resp = api.unlock_analysis_run(run["id"], analyst_headers)
    # PRD names ERR_RUN_HAS_OPEN_FINDINGS once any finding exists, but does
    # not state that the findings gate pre-empts the lifecycle-state check
    # (§2.8 orders ERR_INVALID_STATE before business rules) — accept either.
    validate_error_is_one_of(
        resp,
        [ApiErrorId.ERR_RUN_HAS_OPEN_FINDINGS, ApiErrorId.ERR_INVALID_STATE],
    )
    assert resp.status_code == 409
    current = validate_success(api.get_analysis_run(run["id"], analyst_headers))
    assert current["status"] == "COMPUTED"


def test_lock_empty_scope_rejected(api, analyst_headers):
    """PRD §3.3: "Locking requires at least one in-scope application —
    otherwise `ERR_NO_IN_SCOPE_APPLICATIONS` (HTTP 422)".

    Design: Corner/state_machines/lock_empty_scope_rejected
    """
    market = validate_success(
        api.create_market(
            {"name": "Metro One", "msa_code": "M001",
             "protected_group_population_share": 0.40, "peer_group_code": "PG7"},
            TEST_USERS["bank_admin_headers"],
        ),
        expected_status=201,
    )
    run = create_analysis_run(market["id"], product_type="FHA")
    resp = api.lock_analysis_run(run["id"], analyst_headers)
    validate_error(resp, ApiErrorId.ERR_NO_IN_SCOPE_APPLICATIONS, expected_status=422)
    current = validate_success(api.get_analysis_run(run["id"], analyst_headers))
    assert current["status"] == "DRAFT"


def test_finalize_blocked_by_open_findings(api, analyst_headers, officer_headers):
    """PRD §3.3: "From `UNDER_REVIEW`, finalize additionally requires every
    linked finding to be in a terminal state (`REFUTED`, `CLOSED`, or
    `SUPERSEDED`), else `ERR_FINDINGS_OPEN` (HTTP 409)."

    Design: Corner/state_machines/finalize_blocked_by_open_findings
    """
    _market, _branch, _officer, run, findings = setup_adverse_run()
    finding = findings[0]
    validate_success(api.begin_review_finding(finding["id"], analyst_headers))
    resp = api.finalize_analysis_run(run["id"], officer_headers)
    validate_error(resp, ApiErrorId.ERR_FINDINGS_OPEN, expected_status=409)
    validate_success(
        api.refute_finding(finding["id"], {"reason": "sample error in withdrawal coding"},
                           officer_headers)
    )
    done = validate_success(api.finalize_analysis_run(run["id"], officer_headers))
    assert done["status"] == "FINALIZED"


def test_run_unlock_cycle_restores_draft(api, analyst_headers, data_ops_headers,
                                         bank_admin_headers):
    """PRD §3.3: "Unlocking returns the run to `DRAFT`, clears `locked_at`,
    and discards the snapshot".
    PRD §3.3: "On a successful lock the run moves `DRAFT` → `DATA_LOCKED`,
    `locked_at` is stamped from the logical clock, `snapshot_application_count`
    records the in-scope count, and the frozen id list is retained."

    Design: Corner/state_machines/run_unlock_cycle_restores_draft
    """
    market, branch, officer = setup_market_branch_officer()
    app = create_application(market["id"], branch["id"], officer["id"])
    validate_applications([app["id"]])
    run = create_analysis_run(market["id"])
    validate_success(api.lock_analysis_run(run["id"], analyst_headers))
    unlocked = validate_success(api.unlock_analysis_run(run["id"], analyst_headers))
    assert unlocked["status"] == "DRAFT"
    assert unlocked.get("locked_at") is None, (
        f"unlock clears locked_at, got {unlocked.get('locked_at')!r}"
    )
    relocked = validate_success(api.lock_analysis_run(run["id"], analyst_headers))
    assert relocked["status"] == "DATA_LOCKED"
    assert relocked["snapshot_application_count"] == 1


def test_archive_releases_scope_overlap(api, analyst_headers, officer_headers,
                                        data_ops_headers):
    """PRD §3.3: "Creation is rejected with `ERR_SCOPE_OVERLAP` (HTTP 409)
    when another run with the same market, product, and basis already exists
    with an overlapping half-open period — unless that other run is
    `ARCHIVED`, which releases the block."

    Design: Corner/state_machines/archive_releases_scope_overlap
    """
    market, branch, officer = setup_market_branch_officer()
    app = create_application(market["id"], branch["id"], officer["id"])
    validate_applications([app["id"]])
    run = create_analysis_run(market["id"])
    validate_success(api.lock_analysis_run(run["id"], analyst_headers))
    validate_success(api.compute_analysis_run(run["id"], analyst_headers))
    validate_success(api.finalize_analysis_run(run["id"], officer_headers))
    payload = {
        "market_id": market["id"],
        "product_type": "CONVENTIONAL",
        "prohibited_basis": "RACE",
        "period_start": "2026-02-01",
        "period_end": "2026-05-01",
    }
    resp = api.create_analysis_run(payload, analyst_headers)
    validate_error(resp, ApiErrorId.ERR_SCOPE_OVERLAP, expected_status=409)
    archived = validate_success(api.archive_analysis_run(run["id"], officer_headers))
    assert archived["status"] == "ARCHIVED"
    created = validate_success(api.create_analysis_run(payload, analyst_headers),
                               expected_status=201)
    assert created["status"] == "DRAFT"


def test_branch_close_cascades_officers_suspended(api, bank_admin_headers):
    """PRD §3.1: "When a `BankAdmin` closes a branch, its `status` moves to
    `CLOSED` and, in the same breath, every `ACTIVE` loan officer employed
    there is cascaded to `SUSPENDED`."

    Design: Corner/state_machines/branch_close_cascades_officers_suspended
    """
    market = validate_success(
        api.create_market(
            {"name": "Metro One", "msa_code": "M001",
             "protected_group_population_share": 0.40, "peer_group_code": "PG7"},
            bank_admin_headers,
        ),
        expected_status=201,
    )
    branch1 = validate_success(
        api.create_branch(
            {"market_id": market["id"], "name": "Main", "tract_minority_pct": 55.0,
             "opened_on": "2020-01-15"},
            bank_admin_headers,
        ),
        expected_status=201,
    )
    branch2 = validate_success(
        api.create_branch(
            {"market_id": market["id"], "name": "West", "tract_minority_pct": 20.0,
             "opened_on": "2021-03-01"},
            bank_admin_headers,
        ),
        expected_status=201,
    )
    officer1 = validate_success(
        api.create_loan_officer({"branch_id": branch1["id"], "full_name": "Officer One"},
                                bank_admin_headers),
        expected_status=201,
    )
    officer2 = validate_success(
        api.create_loan_officer({"branch_id": branch1["id"], "full_name": "Officer Two"},
                                bank_admin_headers),
        expected_status=201,
    )
    officer3 = validate_success(
        api.create_loan_officer({"branch_id": branch2["id"], "full_name": "Officer Three"},
                                bank_admin_headers),
        expected_status=201,
    )
    closed = validate_success(api.close_branch(branch1["id"], bank_admin_headers))
    assert closed["status"] == "CLOSED"
    o1 = validate_success(api.get_loan_officer(officer1["id"], bank_admin_headers))
    o2 = validate_success(api.get_loan_officer(officer2["id"], bank_admin_headers))
    o3 = validate_success(api.get_loan_officer(officer3["id"], bank_admin_headers))
    assert o1["status"] == "SUSPENDED", "branch cascade suspends officer 1"
    assert o2["status"] == "SUSPENDED", "branch cascade suspends officer 2"
    assert o3["status"] == "ACTIVE", "other branch untouched"


def test_loan_officer_suspend_reinstate_cycle(api, bank_admin_headers, data_ops_headers,
                                              director_headers):
    """PRD §3.1: "A `ComplianceDirector` may suspend an officer, moving
    `status` to `SUSPENDED`, which blocks that officer from creating new
    pricing exceptions or underwriting overrides; reinstatement returns the
    officer to `ACTIVE`. The suspension block surfaces as
    `ERR_OFFICER_SUSPENDED` (HTTP 409) at creation time for either resource."

    Design: Corner/state_machines/loan_officer_suspend_reinstate_cycle
    """
    market, branch, officer = setup_market_branch_officer()
    app = create_application(market["id"], branch["id"], officer["id"])
    validate_applications([app["id"]])
    validate_success(api.suspend_loan_officer(officer["id"], director_headers))
    payload = {
        "application_id": app["id"],
        "kind": "FEE_WAIVER",
        "requested_rate_bps": 700,
        "justification": "fee",
    }
    resp = api.create_pricing_exception(payload, make_loan_officer_headers(officer["id"]))
    validate_error(resp, ApiErrorId.ERR_OFFICER_SUSPENDED, expected_status=409)
    reinstated = validate_success(
        api.reinstate_loan_officer(officer["id"], director_headers)
    )
    assert reinstated["status"] == "ACTIVE"
    created = validate_success(
        api.create_pricing_exception(payload, make_loan_officer_headers(officer["id"])),
        expected_status=201,
    )
    assert created["status"] == "REQUESTED"


def test_run_lock_requires_all_applications_validated(
    api, analyst_headers, data_ops_headers
):
    """PRD §3.3: "and requires every in-scope application to be `VALIDATED`,
    else `ERR_APPLICATIONS_NOT_VALIDATED` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/run_lock_requires_all_applications_validated
    """
    market, branch, officer = setup_market_branch_officer()
    app1 = create_application(
        market["id"], branch["id"], officer["id"],
        applicant_group="CONTROL", outcome="ORIGINATED", credit_score=720,
        application_date="2026-01-05", decision_date="2026-01-20",
    )
    app2 = create_application(
        market["id"], branch["id"], officer["id"],
        applicant_group="PROTECTED_1", outcome="DENIED", credit_score=640,
        dti_pct=44.0, application_date="2026-02-01", decision_date="2026-02-10",
    )
    validate_applications([app1["id"]])
    run = create_analysis_run(market["id"])
    resp = api.lock_analysis_run(run["id"], analyst_headers)
    validate_error(resp, ApiErrorId.ERR_APPLICATIONS_NOT_VALIDATED, expected_status=409)
    current = validate_success(api.get_analysis_run(run["id"], analyst_headers))
    assert current["status"] == "DRAFT", "rejected lock leaves the run in DRAFT"


def test_run_lock_succeeds_once_every_in_scope_application_validated(
    api, analyst_headers, data_ops_headers
):
    """PRD §3.3: "and requires every in-scope application to be `VALIDATED`,
    else `ERR_APPLICATIONS_NOT_VALIDATED` (HTTP 409)."
    PRD §3.3: "On a successful lock the run moves `DRAFT` → `DATA_LOCKED`,
    `locked_at` is stamped from the logical clock, `snapshot_application_count`
    records the in-scope count, and the frozen id list is retained."

    Design: Difficulty/cross_entity_state_dependency/run_lock_requires_all_applications_validated
    """
    market, branch, officer = setup_market_branch_officer()
    app1 = create_application(
        market["id"], branch["id"], officer["id"],
        applicant_group="CONTROL", outcome="ORIGINATED", credit_score=720,
        application_date="2026-01-05", decision_date="2026-01-20",
    )
    app2 = create_application(
        market["id"], branch["id"], officer["id"],
        applicant_group="PROTECTED_1", outcome="DENIED", credit_score=640,
        dti_pct=44.0, application_date="2026-02-01", decision_date="2026-02-10",
    )
    validate_applications([app1["id"]])
    run = create_analysis_run(market["id"])
    validate_error(
        api.lock_analysis_run(run["id"], analyst_headers),
        ApiErrorId.ERR_APPLICATIONS_NOT_VALIDATED,
        expected_status=409,
    )
    validate_applications([app2["id"]])
    locked = validate_success(api.lock_analysis_run(run["id"], analyst_headers))
    assert locked["status"] == "DATA_LOCKED"
    assert locked["snapshot_application_count"] == 2, (
        f"snapshot covers both in-scope applications, got "
        f"{locked['snapshot_application_count']}"
    )
    assert locked.get("locked_at"), "locked_at stamped on successful lock"
