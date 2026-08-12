"""Denial impact ratio (net/raw variants), pricing spread, penetration index,
and dataset-staleness compute gate."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_analysis_run,
    create_application,
    create_application_rows,
    set_clock,
    setup_market_branch_officer,
    validate_applications,
    validate_error,
    validate_paginated,
    validate_success,
)


def _build_denial_divergence_fixture(api):
    """24-row fixture: CONTROL 8 ORIGINATED + 2 DENIED;
    PROTECTED_1 7 ORIGINATED + 3 DENIED + 4 WITHDRAWN. All VALIDATED, Q1."""
    market, branch, officer = setup_market_branch_officer()
    rows = (
        [{"applicant_group": "CONTROL", "outcome": "ORIGINATED",
          "note_rate_bps": 700, "credit_score": 720 + i} for i in range(8)]
        + [{"applicant_group": "CONTROL", "outcome": "DENIED",
            "note_rate_bps": 700, "credit_score": 640 + i} for i in range(2)]
        + [{"applicant_group": "PROTECTED_1", "outcome": "ORIGINATED",
            "note_rate_bps": 700, "credit_score": 715 + i} for i in range(7)]
        + [{"applicant_group": "PROTECTED_1", "outcome": "DENIED",
            "note_rate_bps": 700, "credit_score": 645 + i} for i in range(3)]
        + [{"applicant_group": "PROTECTED_1", "outcome": "WITHDRAWN",
            "note_rate_bps": 700, "credit_score": 700 + i} for i in range(4)]
    )
    apps = create_application_rows(market["id"], branch["id"], officer["id"], rows)
    validate_applications([a["id"] for a in apps])
    run = create_analysis_run(market["id"])
    validate_success(
        api.lock_analysis_run(run["id"], TEST_USERS["analyst_headers"])
    )
    return market, run


def _compute(api, run_id):
    return validate_success(
        api.compute_analysis_run(run_id, TEST_USERS["analyst_headers"])
    )


def test_denial_ratio_net_and_raw_values(api):
    """PRD §3.3: "For the net variant, each cohort's denominator counts only
    rows with outcome `ORIGINATED` or `DENIED`".
    PRD §3.3: "For the raw variant, denominators additionally count
    `WITHDRAWN` and `APPROVED_NOT_ACCEPTED` rows, so `impact_ratio_raw` is
    the protected originated share of all protected rows divided by the
    control originated share of all control rows."

    Design: Difficulty/dual_variant_calc/denial_ratio_net_vs_raw_divergence
    """
    _market, run = _build_denial_divergence_fixture(api)
    computed = _compute(api, run["id"])
    # net rates: protected 7/10 = 0.7, control 8/10 = 0.8; ratio 0.7/0.8 = 0.8750
    assert computed["approval_rate_protected_net"] == pytest.approx(0.70, abs=1e-4)
    assert computed["approval_rate_control_net"] == pytest.approx(0.80, abs=1e-4)
    assert computed["impact_ratio_net"] == pytest.approx(0.8750, abs=1e-4)
    # raw: protected 7/14 vs control 8/10 -> 0.6250
    assert computed["impact_ratio_raw"] == pytest.approx(0.6250, abs=1e-4)
    assert abs(computed["impact_ratio_net"] - computed["impact_ratio_raw"]) > 0.01, (
        "the two variants diverge because the raw denominators include the "
        "4 WITHDRAWN protected rows"
    )
    # pricing spread over identical 700bps originations is exactly zero.
    assert computed["pricing_disparity_unadjusted_bps"] == pytest.approx(0.0, abs=1e-4)


def test_denial_ratio_variants_diverge_classification_flag_and_auto_finding(api):
    """PRD §3.3: "`adverse_classification` keys off the net ratio: at least
    0.90 is `NONE`, at least 0.80 but below 0.90 is `MARGINAL`, and below
    0.80 is `ADVERSE`."
    PRD §3.3: "When `screening_flag` is true, a `DisparityFinding` of kind
    `DENIAL_DISPARITY` appears with `source` `AUTO`, `status` `FLAGGED`,
    `metric_value` set to `impact_ratio_raw`, `threshold_value` 0.80,
    `created_by_user_id` recorded as the string `system`, and the run's
    `open_finding_count` incremented."

    Design: Difficulty/dual_variant_calc/denial_ratio_net_vs_raw_divergence
    """
    _market, run = _build_denial_divergence_fixture(api)
    computed = _compute(api, run["id"])
    assert computed["adverse_classification"] == "MARGINAL", (
        "classification keys off the net variant (0.8750)"
    )
    assert computed["screening_flag"] is True, (
        "raw variant 0.6250 is strictly below 0.80"
    )
    assert computed["open_finding_count"] == 1
    findings, meta = validate_paginated(
        api.list_findings(TEST_USERS["analyst_headers"],
                          params={"analysis_run_id": run["id"]})
    )
    assert meta["total_count"] == 1, f"exactly one auto finding, got {meta['total_count']}"
    finding = findings[0]
    assert finding["kind"] == "DENIAL_DISPARITY"
    assert finding["source"] == "AUTO"
    assert finding["status"] == "FLAGGED"
    assert finding["metric_value"] == pytest.approx(0.6250, abs=1e-4)
    assert finding["threshold_value"] == pytest.approx(0.80, abs=1e-9)


def _build_four_fifths_fixture(api):
    """CONTROL 10 ORIGINATED; PROTECTED_1 8 ORIGINATED + 2 DENIED (ratio 0.8)."""
    market, branch, officer = setup_market_branch_officer(
        market_name="Metro Two", msa_code="M002"
    )
    rows = (
        [{"applicant_group": "CONTROL", "outcome": "ORIGINATED",
          "note_rate_bps": 700, "credit_score": 720 + i} for i in range(10)]
        + [{"applicant_group": "PROTECTED_1", "outcome": "ORIGINATED",
            "note_rate_bps": 700, "credit_score": 715 + i} for i in range(8)]
        + [{"applicant_group": "PROTECTED_1", "outcome": "DENIED",
            "note_rate_bps": 700, "credit_score": 640 + i} for i in range(2)]
    )
    apps = create_application_rows(market["id"], branch["id"], officer["id"], rows)
    validate_applications([a["id"] for a in apps])
    run = create_analysis_run(market["id"])
    validate_success(
        api.lock_analysis_run(run["id"], TEST_USERS["analyst_headers"])
    )
    return market, run


def test_impact_ratio_exactly_four_fifths_classifies_marginal(api):
    """PRD §3.3: "`adverse_classification` keys off the net ratio: at least
    0.90 is `NONE`, at least 0.80 but below 0.90 is `MARGINAL`, and below
    0.80 is `ADVERSE`."

    Design: Difficulty/boundary_precision_check/impact_ratio_exactly_four_fifths_no_flag
    """
    _market, run = _build_four_fifths_fixture(api)
    computed = _compute(api, run["id"])
    assert computed["impact_ratio_net"] == pytest.approx(0.8000, abs=1e-4), (
        f"protected 0.8 / control 1.0, got {computed['impact_ratio_net']}"
    )
    assert computed["adverse_classification"] == "MARGINAL", (
        "0.80 <= ratio < 0.90 classifies MARGINAL"
    )


def test_impact_ratio_exactly_four_fifths_sets_no_screening_flag(api):
    """PRD §3.3: "`screening_flag` is true exactly when the smaller of
    `impact_ratio_net` and `impact_ratio_raw` is strictly below 0.80 — a
    ratio of exactly 0.80 does not flag."

    Design: Difficulty/boundary_precision_check/impact_ratio_exactly_four_fifths_no_flag
    """
    _market, run = _build_four_fifths_fixture(api)
    computed = _compute(api, run["id"])
    assert computed["screening_flag"] is False, (
        "strictly-below rule: exactly 0.80 does NOT flag"
    )
    assert computed["open_finding_count"] == 0
    findings, meta = validate_paginated(
        api.list_findings(TEST_USERS["analyst_headers"],
                          params={"analysis_run_id": run["id"]})
    )
    assert meta["total_count"] == 0, "no auto-finding at the boundary"


def test_pricing_disparity_threshold_and_auto_finding(api):
    """PRD §3.3: "Independently, when `pricing_disparity_unadjusted_bps` is
    strictly greater than 15 basis points (exactly 15 does not flag), a
    second auto-finding of kind `PRICING_DISPARITY` appears with
    `metric_value` the unadjusted spread and `threshold_value` 15, again
    incrementing `open_finding_count`."

    Design: Corner/calculations/pricing_disparity_threshold_and_auto_finding
    """
    market_a, branch_a, officer_a = setup_market_branch_officer(
        market_name="Metro A", msa_code="MA01"
    )
    market_b = validate_success(
        api.create_market(
            {"name": "Metro B", "msa_code": "MB01",
             "protected_group_population_share": 0.30, "peer_group_code": "PG4"},
            TEST_USERS["bank_admin_headers"],
        ),
        expected_status=201,
    )
    branch_b = validate_success(
        api.create_branch(
            {"market_id": market_b["id"], "name": "B Main",
             "tract_minority_pct": 25.0, "opened_on": "2020-01-15"},
            TEST_USERS["bank_admin_headers"],
        ),
        expected_status=201,
    )
    officer_b = validate_success(
        api.create_loan_officer(
            {"branch_id": branch_b["id"], "full_name": "Officer B"},
            TEST_USERS["bank_admin_headers"],
        ),
        expected_status=201,
    )
    # Market A: spread 50 bps; Market B: spread exactly 15 bps.
    rows_a = [
        {"applicant_group": "CONTROL", "outcome": "ORIGINATED",
         "note_rate_bps": 700, "credit_score": 720},
        {"applicant_group": "PROTECTED_1", "outcome": "ORIGINATED",
         "note_rate_bps": 750, "credit_score": 715},
    ]
    rows_b = [
        {"applicant_group": "CONTROL", "outcome": "ORIGINATED",
         "note_rate_bps": 700, "credit_score": 720},
        {"applicant_group": "PROTECTED_1", "outcome": "ORIGINATED",
         "note_rate_bps": 715, "credit_score": 715},
    ]
    apps_a = create_application_rows(market_a["id"], branch_a["id"], officer_a["id"], rows_a)
    apps_b = create_application_rows(market_b["id"], branch_b["id"], officer_b["id"], rows_b)
    validate_applications([a["id"] for a in apps_a] + [a["id"] for a in apps_b])
    run_a = create_analysis_run(market_a["id"])
    run_b = create_analysis_run(market_b["id"])
    validate_success(api.lock_analysis_run(run_a["id"], TEST_USERS["analyst_headers"]))
    validate_success(api.lock_analysis_run(run_b["id"], TEST_USERS["analyst_headers"]))
    computed_a = _compute(api, run_a["id"])
    computed_b = _compute(api, run_b["id"])
    assert computed_a["pricing_disparity_unadjusted_bps"] == pytest.approx(50.0, abs=1e-4)
    assert computed_a["open_finding_count"] == 1
    findings, meta = validate_paginated(
        api.list_findings(TEST_USERS["analyst_headers"],
                          params={"analysis_run_id": run_a["id"],
                                  "kind": "PRICING_DISPARITY"})
    )
    assert meta["total_count"] == 1
    assert findings[0]["metric_value"] == pytest.approx(50.0, abs=1e-4)
    assert findings[0]["threshold_value"] == pytest.approx(15, abs=1e-9)
    assert findings[0]["source"] == "AUTO"
    assert findings[0]["status"] == "FLAGGED"
    assert computed_b["pricing_disparity_unadjusted_bps"] == pytest.approx(15.0, abs=1e-4)
    assert computed_b["open_finding_count"] == 0, (
        "exactly 15 does NOT flag (strictly-greater rule)"
    )


def test_zero_control_rate_division_rule(api):
    """PRD §3.3: "but if the control rate is exactly 0 with non-empty
    denominators, the ratio is defined as 0.0 when the protected rate
    exceeds 0 and 1.0 when both rates are 0."
    PRD §3.3: "If either cohort has zero originated rows, both fields are
    null and no pricing auto-finding is considered."

    Design: Corner/calculations/zero_control_rate_division_rule
    """
    market, branch, officer = setup_market_branch_officer(
        market_name="Metro C", msa_code="MC01"
    )
    rows = [
        {"applicant_group": "CONTROL", "outcome": "DENIED", "note_rate_bps": 700,
         "credit_score": 640},
        {"applicant_group": "CONTROL", "outcome": "DENIED", "note_rate_bps": 700,
         "credit_score": 641},
        {"applicant_group": "PROTECTED_1", "outcome": "ORIGINATED",
         "note_rate_bps": 700, "credit_score": 715},
        {"applicant_group": "PROTECTED_1", "outcome": "DENIED", "note_rate_bps": 700,
         "credit_score": 645},
    ]
    apps = create_application_rows(market["id"], branch["id"], officer["id"], rows)
    validate_applications([a["id"] for a in apps])
    run = create_analysis_run(market["id"])
    validate_success(api.lock_analysis_run(run["id"], TEST_USERS["analyst_headers"]))
    computed = _compute(api, run["id"])
    assert computed["approval_rate_control_net"] == pytest.approx(0.0, abs=1e-9)
    assert computed["impact_ratio_net"] == pytest.approx(0.0, abs=1e-9), (
        "zero control rate with protected rate > 0 defines the ratio as 0.0"
    )
    assert computed["adverse_classification"] == "ADVERSE"
    findings, meta = validate_paginated(
        api.list_findings(TEST_USERS["analyst_headers"],
                          params={"analysis_run_id": run["id"],
                                  "kind": "DENIAL_DISPARITY"})
    )
    assert meta["total_count"] == 1, "ADVERSE classification auto-flags one finding"
    assert computed["pricing_disparity_unadjusted_bps"] is None, (
        "zero ORIGINATED control rows -> unadjusted spread null"
    )
    assert computed["pricing_disparity_adjusted_bps"] is None


def _build_penetration_fixture(api):
    """Q2 2026 fixture: CONTROL 12 ORIGINATED; PROTECTED_1 8 ORIGINATED +
    4 DENIED + 4 WITHDRAWN; peer benchmark rate 0.625 for the quarter."""
    market, branch, officer = setup_market_branch_officer()
    rows = (
        [{"applicant_group": "CONTROL", "outcome": "ORIGINATED",
          "note_rate_bps": 700, "credit_score": 720 + i,
          "application_date": "2026-04-01", "decision_date": "2026-04-10"}
         for i in range(12)]
        + [{"applicant_group": "PROTECTED_1", "outcome": "ORIGINATED",
            "note_rate_bps": 700, "credit_score": 715 + i,
            "application_date": "2026-04-13", "decision_date": "2026-04-22"}
           for i in range(8)]
        + [{"applicant_group": "PROTECTED_1", "outcome": "DENIED",
            "note_rate_bps": 700, "credit_score": 640 + i,
            "application_date": "2026-04-21", "decision_date": "2026-05-01"}
           for i in range(4)]
        + [{"applicant_group": "PROTECTED_1", "outcome": "WITHDRAWN",
            "note_rate_bps": 700, "credit_score": 700 + i,
            "application_date": "2026-04-25", "decision_date": "2026-05-05"}
           for i in range(4)]
    )
    apps = create_application_rows(market["id"], branch["id"], officer["id"], rows)
    validate_applications([a["id"] for a in apps])
    benchmark = validate_success(
        api.create_peer_benchmark(
            {"market_id": market["id"], "period_start": "2026-04-01",
             "period_end": "2026-07-01", "peer_protected_origination_rate": 0.625,
             "peer_origination_count": 5000, "source": "HMDA aggregate 2026"},
            TEST_USERS["data_ops_headers"],
        ),
        expected_status=201,
    )
    return market, benchmark


def _penetration_report(api, market_id, start="2026-04-01", end="2026-07-01"):
    return validate_success(
        api.get_penetration_report(
            market_id, {"period_start": start, "period_end": end},
            TEST_USERS["analyst_headers"],
        )
    )


def test_penetration_branch_weighted_and_peer_relative_values(api):
    """PRD §3.7: "The branch-weighted variant,
    `penetration_index_branch_weighted`, divides that share by the market's
    `protected_group_population_share`, benchmarking originations against
    the population the branch footprint actually serves."
    PRD §3.7: "The peer-relative variant, `penetration_index_peer_relative`,
    first computes the bank's protected origination rate — protected
    `ORIGINATED` rows over protected `VALIDATED` rows in the period — then
    divides by the matching benchmark's `peer_protected_origination_rate`;
    the matched `peer_benchmark_id` is returned alongside".

    Design: Difficulty/dual_variant_calc/penetration_branch_weighted_vs_peer_relative
    """
    market, benchmark = _build_penetration_fixture(api)
    report = _penetration_report(api, market["id"])
    # share = 8 protected of 20 originations.
    assert report["bank_protected_origination_share"] == pytest.approx(0.40, abs=1e-4)
    # branch_weighted = 0.40 / 0.40.
    assert report["penetration_index_branch_weighted"] == pytest.approx(1.0, abs=1e-4)
    # peer_relative = (8 / 16) / 0.625.
    assert report["penetration_index_peer_relative"] == pytest.approx(0.80, abs=1e-4)
    assert report["peer_benchmark_id"] == benchmark["id"]


def test_penetration_variants_diverge_on_identical_data(api):
    """PRD §3.7: "Over the market's `VALIDATED` applications decided in the
    period, it reports `bank_protected_origination_share` — the
    protected-cohort share of all `ORIGINATED` rows — and two index
    variants, each to 4 decimal places round-half-up."

    Design: Difficulty/dual_variant_calc/penetration_branch_weighted_vs_peer_relative
    """
    market, _benchmark = _build_penetration_fixture(api)
    report = _penetration_report(api, market["id"])
    weighted = report["penetration_index_branch_weighted"]
    relative = report["penetration_index_peer_relative"]
    assert weighted == pytest.approx(1.0, abs=1e-4)
    assert relative == pytest.approx(0.80, abs=1e-4)
    assert abs(weighted - relative) > 0.01, (
        f"variants must diverge on identical data: {weighted} vs {relative}"
    )


def test_penetration_peer_relative_null_without_benchmark(api):
    """PRD §3.7: "the matched `peer_benchmark_id` is returned alongside, and
    when no benchmark exactly matches the requested period the index and the
    id are null."

    Design: Corner/calculations/penetration_peer_relative_null_without_benchmark
    """
    market, branch, officer = setup_market_branch_officer()
    rows = [
        {"applicant_group": "CONTROL", "outcome": "ORIGINATED", "note_rate_bps": 700,
         "credit_score": 720, "application_date": "2026-07-01",
         "decision_date": "2026-07-10"},
        {"applicant_group": "CONTROL", "outcome": "ORIGINATED", "note_rate_bps": 700,
         "credit_score": 721, "application_date": "2026-07-02",
         "decision_date": "2026-07-11"},
        {"applicant_group": "PROTECTED_1", "outcome": "ORIGINATED",
         "note_rate_bps": 700, "credit_score": 715,
         "application_date": "2026-07-03", "decision_date": "2026-07-12"},
    ]
    apps = create_application_rows(market["id"], branch["id"], officer["id"], rows)
    validate_applications([a["id"] for a in apps])
    report = _penetration_report(api, market["id"], "2026-07-01", "2026-10-01")
    # share = 1/3 over population share 0.40 -> 0.8333 (4dp round-half-up).
    assert report["penetration_index_branch_weighted"] == pytest.approx(0.8333, abs=1e-4)
    assert report["penetration_index_peer_relative"] is None
    assert report["peer_benchmark_id"] is None


def test_stale_dataset_blocks_compute(api, analyst_headers, data_ops_headers,
                                      bank_admin_headers):
    """PRD §3.3: "First the dataset-staleness precondition is checked: if
    any in-scope application's `updated_at` is strictly later than
    `locked_at` (millisecond precision), compute is rejected with
    `ERR_STALE_DATASET` and the analyst must unlock and re-lock."

    Design: Corner/calculations/stale_dataset_blocks_compute
    """
    market, branch, officer = setup_market_branch_officer()
    app = create_application(market["id"], branch["id"], officer["id"],
                             credit_score=720)
    validated = validate_applications([app["id"]])[0]
    run = create_analysis_run(market["id"])
    validate_success(api.lock_analysis_run(run["id"], analyst_headers))
    set_clock("2026-05-01T01:00:00Z")
    corrected = validate_success(
        api.correct_application(
            app["id"],
            {"note_rate_bps": 705,
             "expected_application_version": validated["version"]},
            data_ops_headers,
        )
    )
    assert corrected["status"] == "RECEIVED", (
        "correction of a VALIDATED row reverts it to RECEIVED"
    )
    resp = api.compute_analysis_run(run["id"], analyst_headers)
    validate_error(resp, ApiErrorId.ERR_STALE_DATASET, expected_status=409)
    validate_success(api.unlock_analysis_run(run["id"], analyst_headers))
    validate_applications([app["id"]])
    validate_success(api.lock_analysis_run(run["id"], analyst_headers))
    computed = validate_success(api.compute_analysis_run(run["id"], analyst_headers))
    assert computed["status"] == "COMPUTED"
