"""Composite setup helpers.

Every test runs against a freshly restarted server with an empty database, so
each fixture builds its preconditions from scratch using only PRD-declared
endpoints. Fixtures use get_success_data() internally so a setup failure
surfaces as a clear setup error rather than a confusing assertion failure.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import Q1_2026_END, Q1_2026_START
from .test_users import TEST_USERS, make_loan_officer_headers


# ---------------------------------------------------------------------------
# Tier 1: reference-data spine (market -> branch -> officer)
# ---------------------------------------------------------------------------

def create_market(**overrides):
    payload = {
        "name": "Metro One",
        "msa_code": "M001",
        "protected_group_population_share": 0.40,
        "peer_group_code": "PG7",
    }
    payload.update(overrides)
    return get_success_data(
        api_client.create_market(payload, TEST_USERS["bank_admin_headers"])
    )


def create_branch(market_id, **overrides):
    payload = {
        "market_id": market_id,
        "name": "Main",
        "tract_minority_pct": 55.0,
        "opened_on": "2020-01-15",
    }
    payload.update(overrides)
    return get_success_data(
        api_client.create_branch(payload, TEST_USERS["bank_admin_headers"])
    )


def create_officer(branch_id, **overrides):
    payload = {"branch_id": branch_id, "full_name": "Officer One"}
    payload.update(overrides)
    return get_success_data(
        api_client.create_loan_officer(payload, TEST_USERS["bank_admin_headers"])
    )


def setup_market_branch_officer(market_name="Metro One", msa_code="M001"):
    """Market + branch + officer. Returns (market, branch, officer)."""
    market = create_market(name=market_name, msa_code=msa_code)
    branch = create_branch(market["id"])
    officer = create_officer(branch["id"])
    return market, branch, officer


# ---------------------------------------------------------------------------
# Tier 1b: applications
# ---------------------------------------------------------------------------

_APP_SEQ = {"n": 0}


def create_application(market_id, branch_id, officer_id, **overrides):
    """Create one application with sensible defaults; override any field."""
    _APP_SEQ["n"] += 1
    seq = _APP_SEQ["n"]
    payload = {
        "market_id": market_id,
        "branch_id": branch_id,
        "loan_officer_id": officer_id,
        "product_type": "CONVENTIONAL",
        "applicant_group": "CONTROL",
        "outcome": "ORIGINATED",
        "note_rate_bps": 700,
        "loan_amount_cents": 30_000_000,
        "credit_score": 700 + (seq % 40),
        "dti_pct": 36.0,
        "application_date": "2026-01-05",
        "decision_date": "2026-01-20",
    }
    payload.update(overrides)
    return get_success_data(
        api_client.create_application(payload, TEST_USERS["data_ops_headers"])
    )


def create_application_rows(market_id, branch_id, officer_id, rows):
    """Create and VALIDATE a batch of applications described by row dicts.

    Each row dict may set: applicant_group, outcome, note_rate_bps,
    credit_score, dti_pct, application_date, decision_date, product_type.
    Returns the list of created application dicts (after validation).
    """
    created = []
    for idx, row in enumerate(rows):
        app = create_application(
            market_id,
            branch_id,
            officer_id,
            application_date=row.get("application_date", f"2026-01-{(idx % 27) + 1:02d}"),
            decision_date=row.get("decision_date", f"2026-01-{(idx % 27) + 1:02d}"),
            **{k: v for k, v in row.items()
               if k in ("applicant_group", "outcome", "note_rate_bps",
                        "credit_score", "dti_pct", "product_type")},
        )
        created.append(app)
    return created


def validate_applications(application_ids):
    """Validate each application; returns the validated dicts."""
    out = []
    for app_id in application_ids:
        out.append(
            get_success_data(
                api_client.validate_application(app_id, TEST_USERS["data_ops_headers"])
            )
        )
    return out


# ---------------------------------------------------------------------------
# Tier 2: analysis-run lifecycle
# ---------------------------------------------------------------------------

def create_analysis_run(market_id, **overrides):
    payload = {
        "market_id": market_id,
        "product_type": "CONVENTIONAL",
        "prohibited_basis": "RACE",
        "period_start": Q1_2026_START,
        "period_end": Q1_2026_END,
    }
    payload.update(overrides)
    return get_success_data(
        api_client.create_analysis_run(payload, TEST_USERS["analyst_headers"])
    )


def create_locked_run(market_id, **overrides):
    """Create an analysis run and lock it (scope must hold >= 1 VALIDATED app)."""
    run = create_analysis_run(market_id, **overrides)
    get_success_data(api_client.lock_analysis_run(run["id"], TEST_USERS["analyst_headers"]))
    return get_success_data(api_client.get_analysis_run(run["id"], TEST_USERS["analyst_headers"]))


def create_computed_run(market_id, **overrides):
    """Create -> lock -> compute. Returns the COMPUTED run dict."""
    run = create_analysis_run(market_id, **overrides)
    get_success_data(api_client.lock_analysis_run(run["id"], TEST_USERS["analyst_headers"]))
    get_success_data(api_client.compute_analysis_run(run["id"], TEST_USERS["analyst_headers"]))
    return get_success_data(api_client.get_analysis_run(run["id"], TEST_USERS["analyst_headers"]))


# ---------------------------------------------------------------------------
# Tier 3: findings and matched-pair reviews
# ---------------------------------------------------------------------------

def create_manual_finding(run_id, kind="PRICING_DISPARITY", notes="manual",
                          creator_user_id="analyst-creator", **overrides):
    payload = {"analysis_run_id": run_id, "kind": kind, "notes": notes}
    payload.update(overrides)
    return get_success_data(
        api_client.create_finding(payload, make_analyst_headers(creator_user_id))
    )


def make_analyst_headers(user_id):
    """Local import indirection kept private to the fixtures module."""
    from .test_users import make_analyst_headers as _mk
    return _mk(user_id)


def make_officer_headers(user_id):
    from .test_users import make_officer_headers as _mk
    return _mk(user_id)


def make_director_headers(user_id):
    from .test_users import make_director_headers as _mk
    return _mk(user_id)


def make_specialist_headers(user_id):
    from .test_users import make_specialist_headers as _mk
    return _mk(user_id)


def create_finding_under_review(run_id, kind="PRICING_DISPARITY",
                                creator_user_id="analyst-creator", **overrides):
    """Manual finding walked FLAGGED -> UNDER_REVIEW. Returns the finding."""
    finding = create_manual_finding(run_id, kind=kind,
                                    creator_user_id=creator_user_id, **overrides)
    get_success_data(
        api_client.begin_review_finding(finding["id"], TEST_USERS["analyst_headers"])
    )
    return get_success_data(api_client.get_finding(finding["id"], TEST_USERS["analyst_headers"]))


def create_substantiated_finding(run_id, harmed_application_ids,
                                 kind="PRICING_DISPARITY",
                                 creator_user_id="analyst-creator",
                                 substantiator_user_id="officer-sub"):
    """Manual finding walked FLAGGED -> UNDER_REVIEW -> SUBSTANTIATED.

    Returns the SUBSTANTIATED finding dict (carrying its current version).
    """
    finding = create_finding_under_review(run_id, kind=kind,
                                          creator_user_id=creator_user_id)
    return get_success_data(
        api_client.substantiate_finding(
            finding["id"],
            {"harmed_application_ids": list(harmed_application_ids)},
            make_officer_headers(substantiator_user_id),
        )
    )


def create_matched_pair(finding, target_application_id,
                        control_application_id=None,
                        analyst_user_id="analyst-1"):
    """Create a matched-pair review against the finding's CURRENT version.

    `finding` may be a dict (with version) or an id; the current version is
    always re-read so the OCC precondition passes. Returns the review dict.
    """
    finding_id = finding["id"] if isinstance(finding, dict) else finding
    current = get_success_data(
        api_client.get_finding(finding_id, TEST_USERS["analyst_headers"])
    )
    payload = {
        "finding_id": finding_id,
        "target_application_id": target_application_id,
        "expected_finding_version": current["version"],
    }
    if control_application_id is not None:
        payload["control_application_id"] = control_application_id
    return get_success_data(
        api_client.create_matched_pair_review(payload, TEST_USERS["analyst_headers"])
    )


def submit_initial(review_id, outcome="DIFFERENTIAL_TREATMENT",
                   notes="initial review", reviewer_user_id="analyst-1"):
    return get_success_data(
        api_client.submit_initial_review(
            review_id, {"outcome": outcome, "notes": notes},
            make_analyst_headers(reviewer_user_id),
        )
    )


def create_confirmed_matched_pair(finding, target_application_id,
                                  control_application_id=None,
                                  reviewer_user_id="analyst-1",
                                  confirmer_user_id="officer-1"):
    """Review walked PENDING -> INITIAL_REVIEWED -> CONFIRMED."""
    review = create_matched_pair(finding, target_application_id, control_application_id)
    submit_initial(review["id"], reviewer_user_id=reviewer_user_id)
    get_success_data(
        api_client.confirm_matched_pair_review(
            review["id"], make_officer_headers(confirmer_user_id)
        )
    )
    return get_success_data(
        api_client.get_matched_pair_review(review["id"], TEST_USERS["analyst_headers"])
    )


# ---------------------------------------------------------------------------
# Tier 4: corrective action plans and remediation payments
# ---------------------------------------------------------------------------

def create_cap(finding, pool_cents=10_000, title="remediation",
               due_date="2026-06-30"):
    """Create a DRAFT CAP against the finding's CURRENT version."""
    finding_id = finding["id"] if isinstance(finding, dict) else finding
    current = get_success_data(
        api_client.get_finding(finding_id, TEST_USERS["analyst_headers"])
    )
    payload = {
        "finding_id": finding_id,
        "title": title,
        "pool_cents": pool_cents,
        "due_date": due_date,
        "expected_finding_version": current["version"],
    }
    return get_success_data(
        api_client.create_corrective_action_plan(payload, TEST_USERS["analyst_headers"])
    )


def create_submitted_cap(finding, pool_cents=10_000, **kwargs):
    cap = create_cap(finding, pool_cents=pool_cents, **kwargs)
    get_success_data(
        api_client.submit_corrective_action_plan(cap["id"], TEST_USERS["analyst_headers"])
    )
    return get_success_data(
        api_client.get_corrective_action_plan(cap["id"], TEST_USERS["analyst_headers"])
    )


def create_executing_cap(finding, pool_cents=10_000, approver_user_id="officer-1",
                         approver_role="officer", **kwargs):
    """DRAFT -> SUBMITTED -> EXECUTING. Returns the EXECUTING CAP dict."""
    cap = create_submitted_cap(finding, pool_cents=pool_cents, **kwargs)
    headers = (make_officer_headers(approver_user_id) if approver_role == "officer"
               else make_director_headers(approver_user_id))
    get_success_data(api_client.approve_corrective_action_plan(cap["id"], headers))
    return get_success_data(
        api_client.get_corrective_action_plan(cap["id"], TEST_USERS["analyst_headers"])
    )


def list_payments_for_cap(cap_id):
    data, _meta = _list_payments(cap_id)
    return data


def _list_payments(cap_id, params=None):
    from prd_bench_local_runner.testing import validate_paginated
    query = {"corrective_action_plan_id": cap_id}
    if params:
        query.update(params)
    resp = api_client.list_remediation_payments(
        TEST_USERS["specialist_headers"], params=query
    )
    return validate_paginated(resp)


def get_payment_for_application(cap_id, application_id):
    """Return the single payment of `cap_id` allocated to `application_id`."""
    payments, _meta = _list_payments(cap_id, {"application_id": application_id})
    assert len(payments) == 1, (
        f"expected exactly 1 payment for application {application_id}, got {len(payments)}"
    )
    return payments[0]


# ---------------------------------------------------------------------------
# Tier 5: board reports, self-tests, clock
# ---------------------------------------------------------------------------

def create_board_report(period_start=Q1_2026_START, period_end=Q1_2026_END):
    return get_success_data(
        api_client.create_board_report(
            {"period_start": period_start, "period_end": period_end},
            TEST_USERS["analyst_headers"],
        )
    )


def create_self_test(market_id, analysis_run_id=None, window_start="2026-01-01",
                     window_end="2026-03-31"):
    payload = {"market_id": market_id, "window_start": window_start,
               "window_end": window_end}
    if analysis_run_id is not None:
        payload["analysis_run_id"] = analysis_run_id
    return get_success_data(
        api_client.create_self_test(payload, TEST_USERS["analyst_headers"])
    )


def set_clock(to_iso8601):
    return get_success_data(
        api_client.set_clock(to_iso8601, TEST_USERS["bank_admin_headers"])
    )


def run_monitoring_cycle():
    return get_success_data(
        api_client.run_monitoring_cycle(TEST_USERS["director_headers"])
    )


# ---------------------------------------------------------------------------
# Officer risk-score composite fixtures
# ---------------------------------------------------------------------------

def create_confirmed_override(application_id, officer_id, **overrides):
    payload = {
        "application_id": application_id,
        "original_decision": "DENY",
        "overridden_decision": "APPROVE",
        "justification": "compensating factors",
    }
    payload.update(overrides)
    override = get_success_data(
        api_client.create_underwriting_override(
            payload, make_loan_officer_headers(officer_id)
        )
    )
    get_success_data(
        api_client.confirm_underwriting_override(
            override["id"], TEST_USERS["officer_headers"]
        )
    )
    return get_success_data(
        api_client.get_underwriting_override(override["id"], TEST_USERS["officer_headers"])
    )


def create_pricing_exception(application_id, officer_id, **overrides):
    payload = {
        "application_id": application_id,
        "kind": "FEE_WAIVER",
        "requested_rate_bps": 700,
        "justification": "fee concession",
    }
    payload.update(overrides)
    return get_success_data(
        api_client.create_pricing_exception(payload, make_loan_officer_headers(officer_id))
    )


def setup_officer_with_ten_apps_dispersion_70():
    """Officer O1 with exactly 10 VALIDATED applications; the ORIGINATED rows
    span 700bps..770bps (pricing dispersion 70).

    Composition: CONTROL x5 (4 ORIGINATED @700 + 1 DENIED @700),
    PROTECTED_1 x5 (ORIGINATED @700, ORIGINATED @770, DENIED @700,
    2 WITHDRAWN @700). Returns (market, branch, officer, apps_by_key).
    """
    market, branch, officer = setup_market_branch_officer()
    rows = [
        {"applicant_group": "CONTROL", "outcome": "ORIGINATED", "note_rate_bps": 700,
         "credit_score": 720},
        {"applicant_group": "CONTROL", "outcome": "ORIGINATED", "note_rate_bps": 700,
         "credit_score": 721},
        {"applicant_group": "CONTROL", "outcome": "ORIGINATED", "note_rate_bps": 700,
         "credit_score": 722},
        {"applicant_group": "CONTROL", "outcome": "ORIGINATED", "note_rate_bps": 700,
         "credit_score": 723},
        {"applicant_group": "CONTROL", "outcome": "DENIED", "note_rate_bps": 700,
         "credit_score": 640},
        {"applicant_group": "PROTECTED_1", "outcome": "ORIGINATED", "note_rate_bps": 700,
         "credit_score": 715},
        {"applicant_group": "PROTECTED_1", "outcome": "ORIGINATED", "note_rate_bps": 770,
         "credit_score": 716},
        {"applicant_group": "PROTECTED_1", "outcome": "DENIED", "note_rate_bps": 700,
         "credit_score": 645},
        {"applicant_group": "PROTECTED_1", "outcome": "WITHDRAWN", "note_rate_bps": 700,
         "credit_score": 700},
        {"applicant_group": "PROTECTED_1", "outcome": "WITHDRAWN", "note_rate_bps": 700,
         "credit_score": 701},
    ]
    apps = create_application_rows(market["id"], branch["id"], officer["id"], rows)
    validate_applications([a["id"] for a in apps])
    keys = ["a1", "a2", "a3", "a4", "a5", "a6", "a7", "a8", "a9", "a10"]
    return market, branch, officer, dict(zip(keys, apps))


def setup_officer_at_watch_65():
    """Officer at score 65.00 / WATCH: 10 VALIDATED apps (dispersion 70)
    plus 2 CONFIRMED overrides (override_rate 0.20).

    Returns (market, branch, officer, apps_by_key, overrides).
    """
    market, branch, officer, apps = setup_officer_with_ten_apps_dispersion_70()
    ov1 = create_confirmed_override(apps["a1"]["id"], officer["id"])
    ov2 = create_confirmed_override(apps["a2"]["id"], officer["id"])
    return market, branch, officer, apps, [ov1, ov2]


# ---------------------------------------------------------------------------
# Run-with-findings composite fixtures
# ---------------------------------------------------------------------------

def setup_run_with_substantiated_finding(harmed_keys=("p1",), pool_cents=10_000,
                                         kind="PRICING_DISPARITY"):
    """COMPUTED run + SUBSTANTIATED manual finding over a small originated
    fixture (1 CONTROL + len(harmed_keys) PROTECTED_1 rows, all @700bps).

    `harmed_keys` selects which protected applications are recorded in
    harmed_application_ids (creation order preserved). Returns a dict with
    market/branch/officer/run/finding/apps. No CAP is created.
    """
    market, branch, officer = setup_market_branch_officer()
    rows = [{"applicant_group": "CONTROL", "outcome": "ORIGINATED",
             "note_rate_bps": 700, "credit_score": 720}]
    for i in range(len(harmed_keys)):
        rows.append({"applicant_group": "PROTECTED_1", "outcome": "ORIGINATED",
                     "note_rate_bps": 700, "credit_score": 715 + i})
    apps_list = create_application_rows(market["id"], branch["id"], officer["id"], rows)
    validate_applications([a["id"] for a in apps_list])
    apps = {"c1": apps_list[0]}
    for key, app in zip(harmed_keys, apps_list[1:]):
        apps[key] = app
    run = create_computed_run(market["id"])
    finding = create_substantiated_finding(
        run["id"], [apps[k]["id"] for k in harmed_keys], kind=kind,
    )
    return {
        "market": market, "branch": branch, "officer": officer,
        "run": run, "finding": finding, "apps": apps,
    }


def setup_executing_cap(harmed_keys=("p1",), pool_cents=10_000,
                        approver_user_id="officer-1", approver_role="officer",
                        **cap_kwargs):
    """Full ladder: computed run -> substantiated finding -> EXECUTING CAP
    with AUTO_ALLOCATED PENDING payments. Returns the composite dict.

    Extra keyword arguments (e.g. due_date) are forwarded to the CAP
    creation ladder."""
    ctx = setup_run_with_substantiated_finding(harmed_keys=harmed_keys,
                                               pool_cents=pool_cents)
    cap = create_executing_cap(
        ctx["finding"], pool_cents=pool_cents,
        approver_user_id=approver_user_id, approver_role=approver_role,
        **cap_kwargs,
    )
    ctx["cap"] = cap
    return ctx


def setup_adverse_run():
    """3-row fixture computing to ADVERSE: CONTROL 1 DENIED (control net rate
    0.0 -> ratio 0.0); PROTECTED_1 1 ORIGINATED + 1 DENIED.

    Returns (market, branch, officer, run, findings) with the auto finding.
    """
    market, branch, officer = setup_market_branch_officer()
    rows = [
        {"applicant_group": "CONTROL", "outcome": "DENIED", "note_rate_bps": 700,
         "credit_score": 640},
        {"applicant_group": "PROTECTED_1", "outcome": "ORIGINATED", "note_rate_bps": 700,
         "credit_score": 715},
        {"applicant_group": "PROTECTED_1", "outcome": "DENIED", "note_rate_bps": 700,
         "credit_score": 645},
    ]
    apps = create_application_rows(market["id"], branch["id"], officer["id"], rows)
    validate_applications([a["id"] for a in apps])
    run = create_computed_run(market["id"])
    from prd_bench_local_runner.testing import validate_paginated
    findings, _meta = validate_paginated(
        api_client.list_findings(TEST_USERS["analyst_headers"],
                                 params={"analysis_run_id": run["id"]})
    )
    return market, branch, officer, run, findings
