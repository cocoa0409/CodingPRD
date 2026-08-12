"""Temporal overlap semantics (runs half-open, self-tests closed), finding
supersession, matched-pair comparability, and the server selector."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_analysis_run,
    create_application,
    create_finding_under_review,
    create_matched_pair,
    create_self_test,
    setup_market_branch_officer,
    validate_applications,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_run_scope_half_open_adjacency(api, analyst_headers):
    """PRD §3.3: "Creation is rejected with `ERR_SCOPE_OVERLAP` (HTTP 409)
    when another run with the same market, product, and basis already exists
    with an overlapping half-open period — unless that other run is
    `ARCHIVED`, which releases the block. Mere adjacency, where one run's
    `period_end` equals another's `period_start`, is not an overlap."

    Design: Difficulty/resource_temporal_overlap/run_scope_half_open_adjacency
    """
    market = validate_success(
        api.create_market(
            {"name": "Metro One", "msa_code": "M001",
             "protected_group_population_share": 0.40, "peer_group_code": "PG7"},
            TEST_USERS["bank_admin_headers"],
        ),
        expected_status=201,
    )
    run1 = create_analysis_run(market["id"])
    assert run1["status"] == "DRAFT"
    adjacent = validate_success(
        api.create_analysis_run(
            {"market_id": market["id"], "product_type": "CONVENTIONAL",
             "prohibited_basis": "RACE", "period_start": "2026-04-01",
             "period_end": "2026-07-01"},
            TEST_USERS["analyst_headers"],
        ),
        expected_status=201,
    )
    assert adjacent["period_start"] == "2026-04-01"
    overlapping = api.create_analysis_run(
        {"market_id": market["id"], "product_type": "CONVENTIONAL",
         "prohibited_basis": "RACE", "period_start": "2026-03-31",
         "period_end": "2026-07-01"},
        TEST_USERS["analyst_headers"],
    )
    validate_error(overlapping, ApiErrorId.ERR_SCOPE_OVERLAP, expected_status=409)


def test_run_scope_overlap_key_includes_product(api, analyst_headers):
    """PRD §3.3: "Creation is rejected with `ERR_SCOPE_OVERLAP` (HTTP 409)
    when another run with the same market, product, and basis already exists
    with an overlapping half-open period".

    Design: Difficulty/resource_temporal_overlap/run_scope_half_open_adjacency
    """
    market = validate_success(
        api.create_market(
            {"name": "Metro One", "msa_code": "M001",
             "protected_group_population_share": 0.40, "peer_group_code": "PG7"},
            TEST_USERS["bank_admin_headers"],
        ),
        expected_status=201,
    )
    create_analysis_run(market["id"])
    other_product = validate_success(
        api.create_analysis_run(
            {"market_id": market["id"], "product_type": "FHA",
             "prohibited_basis": "RACE", "period_start": "2026-02-01",
             "period_end": "2026-05-01"},
            TEST_USERS["analyst_headers"],
        ),
        expected_status=201,
    )
    assert other_product["product_type"] == "FHA", (
        "same window under a different product_type is a different overlap key"
    )


def test_self_test_closed_interval_touching_overlap(api, analyst_headers):
    """PRD §2.7: "Self-test windows are **closed**: both `window_start` and
    `window_end` are inclusive, and two windows that touch at a boundary do
    count as overlapping."
    PRD §3.10: "Creation is rejected with `ERR_SELF_TEST_WINDOW_OVERLAP`
    (HTTP 409) when the window collides with any window of an `ACTIVE` or
    `CLOSED_VIOLATION` self-test of the same market".

    Design: Difficulty/resource_temporal_overlap/self_test_closed_interval_touching_overlap
    """
    market = validate_success(
        api.create_market(
            {"name": "Metro One", "msa_code": "M001",
             "protected_group_population_share": 0.40, "peer_group_code": "PG7"},
            TEST_USERS["bank_admin_headers"],
        ),
        expected_status=201,
    )
    create_self_test(market["id"], window_start="2026-01-01", window_end="2026-03-31")
    touching = api.create_self_test(
        {"market_id": market["id"], "window_start": "2026-03-31",
         "window_end": "2026-06-30"},
        TEST_USERS["analyst_headers"],
    )
    validate_error(touching, ApiErrorId.ERR_SELF_TEST_WINDOW_OVERLAP,
                   expected_status=409)


def test_self_test_window_starting_after_existing_end_accepted(api, analyst_headers):
    """PRD §2.7: "Self-test windows are **closed**: both `window_start` and
    `window_end` are inclusive, and two windows that touch at a boundary do
    count as overlapping."

    Design: Difficulty/resource_temporal_overlap/self_test_closed_interval_touching_overlap
    """
    market = validate_success(
        api.create_market(
            {"name": "Metro One", "msa_code": "M001",
             "protected_group_population_share": 0.40, "peer_group_code": "PG7"},
            TEST_USERS["bank_admin_headers"],
        ),
        expected_status=201,
    )
    create_self_test(market["id"], window_start="2026-01-01", window_end="2026-03-31")
    created = validate_success(
        api.create_self_test(
            {"market_id": market["id"], "window_start": "2026-04-01",
             "window_end": "2026-06-30"},
            TEST_USERS["analyst_headers"],
        ),
        expected_status=201,
    )
    assert created["status"] == "ACTIVE"


def test_finding_supersession_self_reference(api, analyst_headers, data_ops_headers):
    """PRD §3.4: "Manual drafting accepts an optional
    `supersedes_finding_id`: the named finding — whether `FLAGGED`,
    `UNDER_REVIEW`, or `REFUTED` — moves to `SUPERSEDED` with its
    `superseded_by_finding_id` pointer set, and when the superseded finding
    had been open (`FLAGGED` or `UNDER_REVIEW`) the run's
    `open_finding_count` is decremented accordingly."

    Design: Corner/entities/finding_supersession_self_reference
    """
    market, branch, officer = setup_market_branch_officer()
    app = create_application(market["id"], branch["id"], officer["id"])
    validate_applications([app["id"]])
    run = create_analysis_run(market["id"])
    validate_success(api.lock_analysis_run(run["id"], analyst_headers))
    validate_success(api.compute_analysis_run(run["id"], analyst_headers))
    first = create_finding_under_review(run["id"], kind="MANUAL",
                                        notes="first pass")
    second = validate_success(
        api.create_finding(
            {"analysis_run_id": run["id"], "kind": "MANUAL",
             "notes": "second pass supersedes",
             "supersedes_finding_id": first["id"]},
            TEST_USERS["analyst_headers"],
        ),
        expected_status=201,
    )
    stale = validate_success(api.get_finding(first["id"], analyst_headers))
    assert stale["status"] == "SUPERSEDED"
    assert stale["superseded_by_finding_id"] == second["id"]
    run_now = validate_success(api.get_analysis_run(run["id"], analyst_headers))
    assert run_now["open_finding_count"] == 1, (
        "F1's exit from the open set offsets F2's entry; count stays 1"
    )


def test_matched_pair_not_comparable_rejected(api, analyst_headers, data_ops_headers):
    """PRD §3.5: "when supplied, the pair must be comparable, meaning both
    applications share the same `market_id` and `product_type`, sit in the
    correct cohorts (target protected, comparator `CONTROL`), carry the
    correct outcome pairing (target `DENIED`, comparator `ORIGINATED`), and
    differ in `credit_score` by no more than 40 points; otherwise creation
    is rejected with `ERR_MATCH_NOT_COMPARABLE` (HTTP 422)."

    Design: Corner/validations/matched_pair_not_comparable_rejected
    """
    market, branch, officer = setup_market_branch_officer()
    target = create_application(
        market["id"], branch["id"], officer["id"],
        applicant_group="PROTECTED_1", outcome="DENIED", credit_score=741,
        dti_pct=40.0, application_date="2026-02-01", decision_date="2026-02-10",
    )
    control_a = create_application(
        market["id"], branch["id"], officer["id"],
        applicant_group="CONTROL", outcome="ORIGINATED", credit_score=700,
        application_date="2026-01-05", decision_date="2026-01-20",
    )
    control_b = create_application(
        market["id"], branch["id"], officer["id"],
        applicant_group="CONTROL", outcome="DENIED", credit_score=740,
        dti_pct=40.0, application_date="2026-01-06", decision_date="2026-01-21",
    )
    validate_applications([target["id"], control_a["id"], control_b["id"]])
    run = create_analysis_run(market["id"])
    validate_success(api.lock_analysis_run(run["id"], analyst_headers))
    validate_success(api.compute_analysis_run(run["id"], analyst_headers))
    finding = create_finding_under_review(run["id"], kind="DENIAL_DISPARITY")
    current = validate_success(api.get_finding(finding["id"], analyst_headers))
    resp1 = api.create_matched_pair_review(
        {"finding_id": finding["id"], "target_application_id": target["id"],
         "control_application_id": control_a["id"],
         "expected_finding_version": current["version"]},
        analyst_headers,
    )
    validate_error(resp1, ApiErrorId.ERR_MATCH_NOT_COMPARABLE, expected_status=422)
    current = validate_success(api.get_finding(finding["id"], analyst_headers))
    resp2 = api.create_matched_pair_review(
        {"finding_id": finding["id"], "target_application_id": target["id"],
         "control_application_id": control_b["id"],
         "expected_finding_version": current["version"]},
        analyst_headers,
    )
    validate_error(resp2, ApiErrorId.ERR_MATCH_NOT_COMPARABLE, expected_status=422)


def _build_selector_fixture(api):
    """Finding under review plus: target t1 (credit 720, dti 40, DENIED
    PROTECTED_1); controls cA (700/36), cB (740/38), cC (760/36); target t2
    (credit 500) with no eligible control."""
    market, branch, officer = setup_market_branch_officer()
    t1 = create_application(
        market["id"], branch["id"], officer["id"],
        applicant_group="PROTECTED_1", outcome="DENIED", credit_score=720,
        dti_pct=40.0, application_date="2026-02-01", decision_date="2026-02-10",
    )
    t2 = create_application(
        market["id"], branch["id"], officer["id"],
        applicant_group="PROTECTED_1", outcome="DENIED", credit_score=500,
        dti_pct=55.0, application_date="2026-02-02", decision_date="2026-02-11",
    )
    ca = create_application(
        market["id"], branch["id"], officer["id"],
        applicant_group="CONTROL", outcome="ORIGINATED", credit_score=700,
        dti_pct=36.0, application_date="2026-01-05", decision_date="2026-01-20",
    )
    cb = create_application(
        market["id"], branch["id"], officer["id"],
        applicant_group="CONTROL", outcome="ORIGINATED", credit_score=740,
        dti_pct=38.0, application_date="2026-01-06", decision_date="2026-01-21",
    )
    cc = create_application(
        market["id"], branch["id"], officer["id"],
        applicant_group="CONTROL", outcome="ORIGINATED", credit_score=760,
        dti_pct=36.0, application_date="2026-01-07", decision_date="2026-01-22",
    )
    validate_applications([t1["id"], t2["id"], ca["id"], cb["id"], cc["id"]])
    run = create_analysis_run(market["id"])
    validate_success(
        api.lock_analysis_run(run["id"], TEST_USERS["analyst_headers"])
    )
    validate_success(
        api.compute_analysis_run(run["id"], TEST_USERS["analyst_headers"])
    )
    finding = create_finding_under_review(run["id"], kind="DENIAL_DISPARITY")
    return {"market": market, "finding": finding, "t1": t1, "t2": t2,
            "ca": ca, "cb": cb, "cc": cc}


def test_matched_pair_selector_determinism(api, analyst_headers):
    """PRD §3.5: "When the comparator is omitted, the server selector picks
    it: candidates are `CONTROL`-group `ORIGINATED` `VALIDATED` applications
    of the same market and product within 40 credit-score points of the
    target, ranked by ascending absolute credit-score difference, then
    ascending absolute `dti_pct` difference, then ascending `created_at`".

    Design: Corner/endpoints/matched_pair_selector_determinism_and_empty_pool
    """
    ctx = _build_selector_fixture(api)
    review = create_matched_pair(ctx["finding"], ctx["t1"]["id"])
    assert review["selector_used"] is True
    assert review["control_application_id"] == ctx["cb"]["id"], (
        "credit diff ties at 20 for cA and cB; the dti tie-break picks cB "
        "(diff 2 beats 4); cC at diff 40 is eligible but ranks last"
    )


def test_matched_pair_selector_empty_pool(api, analyst_headers):
    """PRD §3.5: "an empty pool is rejected with `ERR_EMPTY_CONTROL_POOL`
    (HTTP 422), and a selector-chosen comparator sets `selector_used` to
    true."

    Design: Corner/endpoints/matched_pair_selector_determinism_and_empty_pool
    """
    ctx = _build_selector_fixture(api)
    first = create_matched_pair(ctx["finding"], ctx["t1"]["id"])
    assert first["status"] == "PENDING"
    current = validate_success(
        api.get_finding(ctx["finding"]["id"], analyst_headers)
    )
    resp = api.create_matched_pair_review(
        {"finding_id": ctx["finding"]["id"],
         "target_application_id": ctx["t2"]["id"],
         "expected_finding_version": current["version"]},
        analyst_headers,
    )
    validate_error(resp, ApiErrorId.ERR_EMPTY_CONTROL_POOL, expected_status=422)
    still_open = validate_success(
        api.get_matched_pair_review(first["id"], analyst_headers)
    )
    assert still_open["status"] == "PENDING", (
        "a failed selector creation does not supersede the open review"
    )
