"""When a claim may be brought onto the file.

The claims-made window is half-open, the extended reporting deadline is
exclusive, and a circumstance report bought earlier relates its notice date back
across a boundary a direct notice cannot cross.
"""

import pytest
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ADJUSTER,
    ApiErrorId,
    COMPLIANCE,
    UNDERWRITER,
    assert_circumstance_report,
    assert_instant_equals,
    cancel_policy_payload,
    create_circumstance_report_payload,
    create_claim_payload,
    make_risk_manager_headers,
    mature_circumstance_report_payload,
    read_circumstance_reports,
    read_policy,
    set_clock,
    setup_bound_policy,
)


def _policy_never_swept():
    """A bound policy left in INCEPTED — no epoch advance is ever taken, so its
    coverage_status stays one the notice gate accepts however far the clock moves."""
    scenario = setup_bound_policy()
    scenario["headers"] = make_risk_manager_headers(scenario["insured"]["id"])
    return scenario


def test_the_lower_bound_of_the_claims_made_window_is_inclusive(api):
    """PRD 3.7: "The clock reading must fall inside the claims-made window: at or
    after `period_start` and strictly before `period_end` for a policy not in
    run-off". PRD 3.7: a claim clearing the gates "is created in `NOTICED` with
    `notice_date` set to the logical-clock reading and `retention_remaining_usd`
    initialised from the policy's `retention_usd`".

    Design: Difficulty/boundary_precision_check/notice_and_reporting_window_boundaries_are_half_open
    """
    scenario = _policy_never_swept()
    policy_id = scenario["policy"]["id"]

    set_clock("2026-08-31T23:59:59Z")
    validate_error(
        api.create_claim(
            policy_id, create_claim_payload(claimant_name="Probe A",
                                            alleged_damages_usd=1_000_000),
            scenario["headers"],
        ),
        ApiErrorId.ERR_NOTICE_OUTSIDE_PERIOD,
        422,
    )

    set_clock("2026-09-01T00:00:00Z")
    admitted = validate_success(
        api.create_claim(
            policy_id, create_claim_payload(claimant_name="Probe B",
                                            alleged_damages_usd=1_000_000),
            scenario["headers"],
        ),
        201,
    )
    assert admitted["status"] == "NOTICED"
    assert_instant_equals(admitted["notice_date"], "2026-09-01T00:00:00Z", "notice_date")
    assert admitted["retention_remaining_usd"] == pytest.approx(250_000, abs=0.01)


def test_the_upper_bound_of_the_claims_made_window_is_exclusive(api):
    """PRD 3.7: "The upper bound is exclusive, so a notice stamped exactly at
    `period_end` is outside the period and is refused with
    `ERR_NOTICE_OUTSIDE_PERIOD`." PRD 3.7: "The policy's `open_claim_count` and
    `version` each increase by 1" only for a claim that clears all five gates.

    Design: Difficulty/boundary_precision_check/notice_and_reporting_window_boundaries_are_half_open
    """
    scenario = _policy_never_swept()
    policy_id = scenario["policy"]["id"]

    set_clock("2027-08-31T23:59:59Z")
    last_second = validate_success(
        api.create_claim(
            policy_id, create_claim_payload(claimant_name="Probe C",
                                            alleged_damages_usd=1_000_000),
            scenario["headers"],
        ),
        201,
    )
    assert last_second["status"] == "NOTICED"

    set_clock("2027-09-01T00:00:00Z")
    validate_error(
        api.create_claim(
            policy_id, create_claim_payload(claimant_name="Probe D",
                                            alleged_damages_usd=1_000_000),
            scenario["headers"],
        ),
        ApiErrorId.ERR_NOTICE_OUTSIDE_PERIOD,
        422,
    )

    claims, meta = validate_paginated(
        api.list_claims(UNDERWRITER, params={"policy_id": policy_id})
    )
    assert meta["total_count"] == 1, "the refused notice left no trace"
    assert [claim["claimant_name"] for claim in claims] == ["Probe C"]
    policy = read_policy(policy_id)
    assert policy["open_claim_count"] == 1
    assert policy["version"] == 2


def test_a_reported_circumstance_relates_its_notice_date_back_across_the_boundary(api):
    """PRD 3.7: a report's "`reporting_deadline` is derived as the end of the
    reporting window plus the policy's `erp_days` days ... The resulting instant
    keeps the time of day of the window end, and it is exclusive." PRD 3.7: "the new
    claim is created in `NOTICED` with `circumstance_report_id` pointing at the
    report and `notice_date` set to the report's own `notice_date` rather than the
    current clock reading — so a claim matured months after `period_end` still
    carries an in-period notice date." PRD 3.7: "the clock must be strictly earlier
    than the report's `reporting_deadline`, so maturing exactly at the deadline is
    refused with `ERR_REPORTING_WINDOW_CLOSED`."

    Design: Difficulty/boundary_precision_check/notice_and_reporting_window_boundaries_are_half_open
    """
    scenario = _policy_never_swept()
    policy_id = scenario["policy"]["id"]

    set_clock("2026-09-01T00:00:00Z")
    first = validate_success(
        api.create_circumstance_report(
            policy_id, create_circumstance_report_payload(), scenario["headers"]
        ),
        201,
    )
    second = validate_success(
        api.create_circumstance_report(
            policy_id,
            create_circumstance_report_payload(
                description="Whistleblower letter alleging channel stuffing",
                discovered_date="2026-08-25T00:00:00Z",
                potential_claimants="Former employees",
                estimated_exposure_usd=1_500_000,
            ),
            scenario["headers"],
        ),
        201,
    )
    for report in (first, second):
        assert_circumstance_report(report)
        assert report["status"] == "REPORTED"
        assert_instant_equals(report["notice_date"], "2026-09-01T00:00:00Z",
                              "notice_date")
        # period_end 2027-09-01 plus erp_days 90, keeping the time of day.
        assert_instant_equals(report["reporting_deadline"], "2027-11-30T00:00:00Z",
                              "reporting_deadline")

    set_clock("2027-11-29T23:59:59Z")
    matured = validate_success(
        api.mature_circumstance_report(
            first["id"],
            mature_circumstance_report_payload(claimant_name="Probe E",
                                               alleged_damages_usd=2_500_000),
            ADJUSTER,
        ),
        201,
    )
    assert matured["status"] == "NOTICED"
    assert matured["circumstance_report_id"] == first["id"]
    assert_instant_equals(matured["notice_date"], "2026-09-01T00:00:00Z", "notice_date")
    by_id = {r["id"]: r for r in read_circumstance_reports(policy_id)}
    assert by_id[first["id"]]["status"] == "MATURED"

    set_clock("2027-11-30T00:00:00Z")
    validate_error(
        api.mature_circumstance_report(
            second["id"],
            mature_circumstance_report_payload(claimant_name="Probe F",
                                               alleged_damages_usd=1_200_000),
            ADJUSTER,
        ),
        ApiErrorId.ERR_REPORTING_WINDOW_CLOSED,
        409,
    )
    after = {r["id"]: r for r in read_circumstance_reports(policy_id)}
    assert after[second["id"]]["status"] == "REPORTED"


def test_a_cancelled_policy_reports_its_state_rather_than_the_closed_window(api):
    """PRD 2.7: "checks are evaluated in ascending order and the first one violated
    determines the response ... The ordering is normative, not descriptive". PRD 3.7
    lists the state gate first: "The policy's `coverage_status` must be `INCEPTED`,
    `ACTIVE` or `RUNOFF`, or the notice is refused with `ERR_INVALID_POLICY_STATE`."

    Design: Difficulty/priority_pair_validation_conflict/cancelled_policy_and_notice_at_period_end_returns_state_error
    """
    scenario = _policy_never_swept()
    cancelled_id = scenario["policy"]["id"]

    cancelled = validate_success(
        api.cancel_policy(
            cancelled_id,
            cancel_policy_payload("2026-08-15T00:00:00Z", "INSURED_REQUEST"),
            COMPLIANCE,
        ),
        200,
    )
    assert cancelled["coverage_status"] == "CANCELLED"
    # 382 unexpired days clamped to 365, so the whole gross premium comes back.
    assert cancelled["return_premium_usd"] == pytest.approx(236_468.57, abs=0.01)

    # The clock is exactly at period_end, so the window rule is violated too.
    set_clock("2027-09-01T00:00:00Z")
    validate_error(
        api.create_claim(
            cancelled_id, create_claim_payload(), scenario["headers"]
        ),
        ApiErrorId.ERR_INVALID_POLICY_STATE,
        409,
    )

    _, meta = validate_paginated(
        api.list_claims(UNDERWRITER, params={"policy_id": cancelled_id})
    )
    assert meta["total_count"] == 0
    assert read_policy(cancelled_id)["open_claim_count"] == 0


def test_the_same_instant_on_a_live_policy_reports_the_closed_window_instead(api):
    """PRD 3.7: "The upper bound is exclusive, so a notice stamped exactly at
    `period_end` is outside the period and is refused with
    `ERR_NOTICE_OUTSIDE_PERIOD`." Isolating the temporal rule takes a policy whose
    `coverage_status` is still one the state gate accepts, and the two failures are
    distinguishable by HTTP status alone.

    Design: Difficulty/priority_pair_validation_conflict/cancelled_policy_and_notice_at_period_end_returns_state_error
    """
    scenario = _policy_never_swept()
    live_id = scenario["policy"]["id"]

    set_clock("2027-09-01T00:00:00Z")
    validate_error(
        api.create_claim(live_id, create_claim_payload(), scenario["headers"]),
        ApiErrorId.ERR_NOTICE_OUTSIDE_PERIOD,
        422,
    )

    # Both rules pass once the reading is inside [period_start, period_end).
    set_clock("2026-09-02T00:00:00Z")
    noticed = validate_success(
        api.create_claim(live_id, create_claim_payload(), scenario["headers"]), 201
    )
    assert noticed["status"] == "NOTICED"
    assert_instant_equals(noticed["notice_date"], "2026-09-02T00:00:00Z", "notice_date")
    assert noticed["retention_remaining_usd"] == pytest.approx(250_000, abs=0.01)
