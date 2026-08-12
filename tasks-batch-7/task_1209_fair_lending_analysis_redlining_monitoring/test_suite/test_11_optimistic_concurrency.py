"""Optimistic concurrency control on the three version-guarded writes."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_analysis_run,
    create_application,
    create_cap,
    create_finding_under_review,
    create_matched_pair,
    setup_market_branch_officer,
    setup_run_with_substantiated_finding,
    validate_applications,
    validate_error,
    validate_success,
)


def test_put_correction_rejected_with_stale_version(api, data_ops_headers):
    """PRD §2.6: "Correcting an application record requires
    `expected_application_version` matching the application's current
    `version`; a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412),
    so a correction never silently overwrites another writer's
    validate-or-correct."
    PRD §2.4: "an integer `version` that starts at 1 and increments by one
    on every mutation."
    PRD §3.2: "If the application was `VALIDATED` at the time of
    correction, it reverts to `RECEIVED` and the officer's
    `validated_application_count` is decremented (risk recomputed)".

    Design: Corner/cross_cutting_complexity_layers/put_correction_rejected_with_stale_version
    """
    market, branch, officer = setup_market_branch_officer()
    created = create_application(market["id"], branch["id"], officer["id"])
    assert created["version"] == 1
    validated = validate_applications([created["id"]])[0]
    assert validated["version"] == 2, "validate is a mutation and bumps version"
    resp = api.correct_application(
        created["id"],
        {"note_rate_bps": 705, "expected_application_version": 1},
        data_ops_headers,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION, expected_status=412)
    current = validate_success(api.get_application(created["id"], data_ops_headers))
    assert current["version"] == 2, "rejected correction leaves version unchanged"
    corrected = validate_success(
        api.correct_application(
            created["id"],
            {"note_rate_bps": 705, "expected_application_version": 2},
            data_ops_headers,
        )
    )
    assert corrected["status"] == "RECEIVED", "VALIDATED rows revert on correction"
    assert corrected["version"] == 3, "version increments on the accepted mutation"


def test_cap_create_occ_stale_then_supersedes(api, analyst_headers):
    """PRD §2.6: "Creating a corrective action plan against a finding
    requires `expected_finding_version` matching the target finding's
    current `version`. If another writer has advanced the finding's version
    since the client last read it — legitimately, for example, because a
    newer plan already superseded the finding's prior draft — the create is
    rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client
    from drafting against a finding it has not observed."
    PRD §3.8: "Drafting supersedes the finding's prior `DRAFT` or
    `RETURNED` plans, increments the finding's `version`, and lands the new
    plan in `DRAFT` with `remaining_cents` equal to `pool_cents` and
    `disbursed_cents` at 0."

    Design: Corner/cross_cutting_complexity_layers/cap_create_occ_stale_then_supersedes
    """
    ctx = setup_run_with_substantiated_finding(harmed_keys=("p1",))
    finding = ctx["finding"]
    stale_version = finding["version"]
    cap1 = create_cap(finding, pool_cents=5_000, title="cap one")
    assert cap1["status"] == "DRAFT"
    resp = api.create_corrective_action_plan(
        {"finding_id": finding["id"], "title": "cap two stale",
         "pool_cents": 7_000, "due_date": "2026-07-31",
         "expected_finding_version": stale_version},
        analyst_headers,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION, expected_status=412)
    current = validate_success(api.get_finding(finding["id"], analyst_headers))
    cap2 = validate_success(
        api.create_corrective_action_plan(
            {"finding_id": finding["id"], "title": "cap two",
             "pool_cents": 7_000, "due_date": "2026-07-31",
             "expected_finding_version": current["version"]},
            analyst_headers,
        ),
        expected_status=201,
    )
    assert cap2["status"] == "DRAFT"
    cap1_now = validate_success(
        api.get_corrective_action_plan(cap1["id"], analyst_headers)
    )
    assert cap1_now["status"] == "SUPERSEDED", (
        "the successful second draft supersedes the finding's prior DRAFT plan"
    )


def test_matched_pair_create_occ_stale_then_supersedes(api, analyst_headers):
    """PRD §2.6: "Creating a matched-pair review against a finding likewise
    requires `expected_finding_version` matching the finding's current
    `version`; a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412)."
    PRD §3.5: "Creation supersedes the finding's currently open review: any
    existing review of the same finding in `PENDING`, `INITIAL_REVIEWED`,
    or `DISPUTED` moves to `SUPERSEDED`, and the finding's `version`
    increments by one."

    Design: Corner/cross_cutting_complexity_layers/matched_pair_create_occ_stale_then_supersedes
    """
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
    validate_success(api.lock_analysis_run(run["id"], analyst_headers))
    validate_success(api.compute_analysis_run(run["id"], analyst_headers))
    finding = create_finding_under_review(run["id"], kind="DENIAL_DISPARITY")
    stale_version = finding["version"]
    review1 = create_matched_pair(finding, target_app["id"], control_app["id"])
    assert review1["status"] == "PENDING"
    resp = api.create_matched_pair_review(
        {"finding_id": finding["id"], "target_application_id": target_app["id"],
         "control_application_id": control_app["id"],
         "expected_finding_version": stale_version},
        analyst_headers,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION, expected_status=412)
    current = validate_success(api.get_finding(finding["id"], analyst_headers))
    review2 = validate_success(
        api.create_matched_pair_review(
            {"finding_id": finding["id"],
             "target_application_id": target_app["id"],
             "control_application_id": control_app["id"],
             "expected_finding_version": current["version"]},
            analyst_headers,
        ),
        expected_status=201,
    )
    assert review2["status"] == "PENDING"
    review1_now = validate_success(
        api.get_matched_pair_review(review1["id"], analyst_headers)
    )
    assert review1_now["status"] == "SUPERSEDED", (
        "the fresh create supersedes the finding's open PENDING review"
    )
