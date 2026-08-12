"""Monitoring cycle effects, self-test privilege, board report lifecycle."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_analysis_run,
    create_application,
    create_board_report,
    create_executing_cap,
    create_finding_under_review,
    create_manual_finding,
    create_pricing_exception,
    create_self_test,
    create_substantiated_finding,
    create_submitted_cap,
    get_payment_for_application,
    is_iso8601_timestamp,
    make_director_headers,
    make_officer_headers,
    run_monitoring_cycle,
    set_clock,
    setup_executing_cap,
    setup_market_branch_officer,
    setup_run_with_substantiated_finding,
    validate_applications,
    validate_error,
    validate_success,
)


def test_exception_expiry_strictly_after_30_days(api, data_ops_headers):
    """PRD §3.12: "First, exception expiry: every pricing exception still
    in `REQUESTED` or `ESCALATED` whose `created_at` is strictly more than
    30 days before the current logical time moves to `EXPIRED`, restoring
    its application's `has_exception` to `NONE`; an exception exactly 30
    days old does not expire."
    PRD §3.12: "The response summarizes the sweep as `cycle_index` plus the
    lists `expired_exception_ids`, `overdue_cap_ids`, and
    `privilege_lost_self_test_ids`."

    Design: Corner/cross_cutting_complexity_layers/exception_expiry_strictly_after_30_days
    """
    market, branch, officer = setup_market_branch_officer()
    app = create_application(market["id"], branch["id"], officer["id"])
    validate_applications([app["id"]])
    # Created under the startup clock reading 2026-05-01T00:00:00Z.
    exception = create_pricing_exception(app["id"], officer["id"])
    # Exactly 30 days later: does not expire.
    set_clock("2026-05-31T00:00:00Z")
    cycle1 = run_monitoring_cycle()
    assert exception["id"] not in cycle1["expired_exception_ids"]
    still = validate_success(
        api.get_pricing_exception(exception["id"], TEST_USERS["officer_headers"])
    )
    assert still["status"] == "REQUESTED", "strictly-more-than-30-days rule"
    # One second past 30 days: expires.
    set_clock("2026-05-31T00:00:01Z")
    cycle2 = run_monitoring_cycle()
    assert exception["id"] in cycle2["expired_exception_ids"]
    expired = validate_success(
        api.get_pricing_exception(exception["id"], TEST_USERS["officer_headers"])
    )
    assert expired["status"] == "EXPIRED"
    app_now = validate_success(api.get_application(app["id"], data_ops_headers))
    assert app_now["has_exception"] == "NONE", "expiry restores has_exception"


def test_cap_overdue_extension_cycle(api, specialist_headers):
    """PRD §3.8: "when the current logical date is strictly later than the
    plan's `due_date` and at least one payment remains `PENDING`, the
    monitoring cycle flips `EXECUTING` → `OVERDUE` (a due date equal to
    today does not flip). A `ComplianceDirector` may extend an overdue plan
    by supplying a `new_due_date` strictly later than the current logical
    date — anything else is `ERR_INVALID_REQUEST` (HTTP 400) — returning
    the plan to `EXECUTING` with `due_date` updated."

    Design: Corner/cross_cutting_complexity_layers/cap_overdue_extension_cycle
    """
    ctx = setup_executing_cap(harmed_keys=("p1",), pool_cents=1_000,
                              approver_user_id="officer-1", due_date="2026-06-30")
    cap_id = ctx["cap"]["id"]
    # On the due date itself the plan does not flip.
    set_clock("2026-06-30T00:00:00Z")
    cycle1 = run_monitoring_cycle()
    assert cap_id not in cycle1["overdue_cap_ids"], (
        "due_date equal to today does NOT flip"
    )
    # The next day it flips.
    set_clock("2026-07-01T00:00:00Z")
    cycle2 = run_monitoring_cycle()
    assert cap_id in cycle2["overdue_cap_ids"]
    overdue = validate_success(
        api.get_corrective_action_plan(cap_id, specialist_headers)
    )
    assert overdue["status"] == "OVERDUE"
    # Extension must name a date later than the current logical date.
    resp = api.extend_corrective_action_plan(
        cap_id, {"new_due_date": "2026-05-01"}, TEST_USERS["director_headers"]
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)
    extended = validate_success(
        api.extend_corrective_action_plan(
            cap_id, {"new_due_date": "2026-09-30"}, TEST_USERS["director_headers"]
        )
    )
    assert extended["status"] == "EXECUTING"
    assert extended["due_date"] == "2026-09-30"


def test_cap_director_threshold_equality(api, analyst_headers, officer_headers):
    """PRD §2.9: "The three heightened cases are approving a pricing
    exception whose owning officer sits in the `RED` monitoring tier,
    approving an exception already in `ESCALATED` status, and approving a
    corrective action plan whose `pool_cents` is at least 25000000 cents.
    Any other actor attempting one of these is rejected with
    `ERR_DIRECTOR_APPROVAL_REQUIRED` (HTTP 403)."

    Design: Corner/cross_cutting_complexity_layers/cap_director_threshold_equality
    """
    market, branch, officer = setup_market_branch_officer()
    control_app = create_application(
        market["id"], branch["id"], officer["id"],
        applicant_group="CONTROL", outcome="ORIGINATED", credit_score=720,
        application_date="2026-01-05", decision_date="2026-01-20",
    )
    p1 = create_application(
        market["id"], branch["id"], officer["id"],
        applicant_group="PROTECTED_1", outcome="ORIGINATED", credit_score=715,
        application_date="2026-02-01", decision_date="2026-02-10",
    )
    p2 = create_application(
        market["id"], branch["id"], officer["id"],
        applicant_group="PROTECTED_1", outcome="ORIGINATED", credit_score=716,
        application_date="2026-02-02", decision_date="2026-02-11",
    )
    validate_applications([control_app["id"], p1["id"], p2["id"]])
    run = create_analysis_run(market["id"])
    validate_success(api.lock_analysis_run(run["id"], analyst_headers))
    validate_success(api.compute_analysis_run(run["id"], analyst_headers))
    finding1 = create_substantiated_finding(run["id"], [p1["id"]])
    finding2 = create_substantiated_finding(run["id"], [p2["id"]])
    cap1 = create_submitted_cap(finding1, pool_cents=24_999_999, title="small pool")
    cap2 = create_submitted_cap(finding2, pool_cents=25_000_000,
                                title="threshold pool")
    approved1 = validate_success(
        api.approve_corrective_action_plan(cap1["id"],
                                           make_officer_headers("officer-1"))
    )
    assert approved1["status"] == "EXECUTING", "below the threshold an officer approves"
    resp = api.approve_corrective_action_plan(
        cap2["id"], make_officer_headers("officer-1")
    )
    validate_error(resp, ApiErrorId.ERR_DIRECTOR_APPROVAL_REQUIRED,
                   expected_status=403)
    approved2 = validate_success(
        api.approve_corrective_action_plan(cap2["id"],
                                           make_director_headers("director-3"))
    )
    assert approved2["status"] == "EXECUTING", "exactly at the threshold: director only"
    payment = get_payment_for_application(cap2["id"], p2["id"])
    assert payment["amount_cents"] == 25_000_000


def test_board_report_publish_gate(api, analyst_headers, officer_headers):
    """PRD §3.11: "Publication moves `APPROVED` → `PUBLISHED`, but only
    when every analysis run overlapping the report period is `FINALIZED` or
    `ARCHIVED`, else `ERR_REPORT_NOT_READY` (HTTP 409); success stamps
    `published_at` and freezes the aggregate counts permanently."

    Design: Corner/state_machines/board_report_publish_gate
    """
    market, branch, officer = setup_market_branch_officer()
    app = create_application(market["id"], branch["id"], officer["id"])
    validate_applications([app["id"]])
    run = create_analysis_run(market["id"])
    validate_success(api.lock_analysis_run(run["id"], analyst_headers))
    validate_success(api.compute_analysis_run(run["id"], analyst_headers))
    finding = create_finding_under_review(run["id"], kind="MANUAL",
                                          notes="open item")
    report = create_board_report()
    validate_success(
        api.submit_board_report(report["id"], make_officer_headers("officer-9"))
    )
    validate_success(
        api.approve_board_report(report["id"], make_director_headers("director-3"))
    )
    resp = api.publish_board_report(report["id"], make_director_headers("director-3"))
    validate_error(resp, ApiErrorId.ERR_REPORT_NOT_READY, expected_status=409)
    validate_success(
        api.refute_finding(finding["id"], {"reason": "not reproducible"},
                           officer_headers)
    )
    validate_success(api.finalize_analysis_run(run["id"], officer_headers))
    published = validate_success(
        api.publish_board_report(report["id"], make_director_headers("director-3"))
    )
    assert published["status"] == "PUBLISHED"
    assert published.get("published_at"), "published_at stamped on publication"
    assert is_iso8601_timestamp(published["published_at"])


def test_self_test_close_violation_requires_substantiated_finding(
    api, analyst_headers, officer_headers
):
    """PRD §3.10: "`VIOLATION_FOUND` requires the linked run to be present
    and to hold at least one finding in `SUBSTANTIATED` or `CLOSED`, else
    `ERR_NO_SUBSTANTIATED_FINDING` (HTTP 409); the self-test then moves to
    `CLOSED_VIOLATION` with `cycles_open` reset to 0 and the remediation
    clock started."
    PRD §3.10: "From there, marking remediated requires a `COMPLETED`
    corrective action plan on a finding of the linked run — else
    `ERR_REMEDIATION_OUTSTANDING` (HTTP 409) — and moves the self-test to
    terminal `REMEDIATED` with privilege preserved."

    Design: Corner/state_machines/self_test_close_violation_requires_substantiated_finding
    """
    market, branch, officer = setup_market_branch_officer()
    app = create_application(market["id"], branch["id"], officer["id"])
    validate_applications([app["id"]])
    run = create_analysis_run(market["id"])
    validate_success(api.lock_analysis_run(run["id"], analyst_headers))
    validate_success(api.compute_analysis_run(run["id"], analyst_headers))
    finding = create_finding_under_review(run["id"], kind="PRICING_DISPARITY")
    self_test = create_self_test(market["id"], analysis_run_id=run["id"])
    resp = api.close_self_test(self_test["id"], {"outcome": "VIOLATION_FOUND"},
                               officer_headers)
    validate_error(resp, ApiErrorId.ERR_NO_SUBSTANTIATED_FINDING,
                   expected_status=409)
    validate_success(
        api.substantiate_finding(
            finding["id"], {"harmed_application_ids": [app["id"]]},
            make_officer_headers("officer-sub"),
        )
    )
    closed = validate_success(
        api.close_self_test(self_test["id"], {"outcome": "VIOLATION_FOUND"},
                            officer_headers)
    )
    assert closed["status"] == "CLOSED_VIOLATION"
    assert closed["cycles_open"] == 0
    resp2 = api.mark_self_test_remediated(self_test["id"], officer_headers)
    validate_error(resp2, ApiErrorId.ERR_REMEDIATION_OUTSTANDING,
                   expected_status=409)


def test_privilege_gate_blocks_finalize(api, analyst_headers, officer_headers,
                                        director_headers):
    """PRD §3.3: "From `COMPUTED`, the only gate is the privilege gate: if
    any self-test whose `analysis_run_id` names this run currently has
    `disclosure_status` `PRIVILEGED` while still `ACTIVE`, finalize is
    rejected with `ERR_PRIVILEGE_GATE` (HTTP 409)."
    PRD §3.10: "A `ComplianceDirector` may designate an `ACTIVE` self-test
    privileged — a field-mutation self-transition that leaves `status` at
    `ACTIVE` while setting `privileged` true and `disclosure_status`
    `PRIVILEGED`."

    Design: Corner/state_machines/privilege_gate_blocks_finalize
    """
    market, branch, officer = setup_market_branch_officer()
    app = create_application(market["id"], branch["id"], officer["id"])
    validate_applications([app["id"]])
    run = create_analysis_run(market["id"])
    validate_success(api.lock_analysis_run(run["id"], analyst_headers))
    validate_success(api.compute_analysis_run(run["id"], analyst_headers))
    self_test = create_self_test(market["id"], analysis_run_id=run["id"])
    designated = validate_success(
        api.designate_self_test_privileged(self_test["id"], director_headers)
    )
    assert designated["privileged"] is True
    assert designated["disclosure_status"] == "PRIVILEGED"
    assert designated["status"] == "ACTIVE"
    resp = api.finalize_analysis_run(run["id"], officer_headers)
    validate_error(resp, ApiErrorId.ERR_PRIVILEGE_GATE, expected_status=409)
    validate_success(
        api.close_self_test(self_test["id"], {"outcome": "NO_VIOLATION"},
                            officer_headers)
    )
    finalized = validate_success(api.finalize_analysis_run(run["id"], officer_headers))
    assert finalized["status"] == "FINALIZED", (
        "closing the self-test lifts the privilege gate"
    )


def test_board_report_privilege_exclusion_and_restoration(
    api, analyst_headers, officer_headers, director_headers
):
    """PRD §3.11: "`substantiated_finding_count` counts findings in
    `SUBSTANTIATED` or `CLOSED` on those runs, excluding any finding whose
    run is linked to a self-test whose `disclosure_status` is `PRIVILEGED`;
    `privileged_exclusion_count` separately counts exactly those excluded
    findings, keeping the privilege effect visible to the board without
    revealing the findings themselves."
    PRD §3.10: "The forfeiture path runs through the monitoring cycle: each
    cycle increments `cycles_open` of every `CLOSED_VIOLATION` self-test,
    and when the counter reaches 2 the self-test moves to terminal
    `PRIVILEGE_LOST`, `disclosure_status` flips to `DISCLOSABLE`, and its
    previously excluded findings become countable in board reports."

    Design: Corner/calculations/board_report_privilege_exclusion_and_restoration
    """
    market, branch, officer = setup_market_branch_officer()
    c1 = create_application(
        market["id"], branch["id"], officer["id"],
        product_type="CONVENTIONAL", applicant_group="CONTROL",
        outcome="ORIGINATED", credit_score=720,
        application_date="2026-01-05", decision_date="2026-01-20",
    )
    c2 = create_application(
        market["id"], branch["id"], officer["id"],
        product_type="FHA", applicant_group="CONTROL", outcome="ORIGINATED",
        note_rate_bps=710, loan_amount_cents=20_000_000, credit_score=700,
        dti_pct=38.0, application_date="2026-01-06", decision_date="2026-01-21",
    )
    validate_applications([c1["id"], c2["id"]])
    run1 = create_analysis_run(market["id"], product_type="CONVENTIONAL")
    run2 = create_analysis_run(market["id"], product_type="FHA")
    validate_success(api.lock_analysis_run(run1["id"], analyst_headers))
    validate_success(api.lock_analysis_run(run2["id"], analyst_headers))
    validate_success(api.compute_analysis_run(run1["id"], analyst_headers))
    validate_success(api.compute_analysis_run(run2["id"], analyst_headers))
    create_substantiated_finding(run1["id"], [c1["id"]])
    create_substantiated_finding(run2["id"], [c2["id"]])
    self_test = create_self_test(market["id"], analysis_run_id=run2["id"])
    validate_success(
        api.designate_self_test_privileged(self_test["id"], director_headers)
    )
    closed = validate_success(
        api.close_self_test(self_test["id"], {"outcome": "VIOLATION_FOUND"},
                            officer_headers)
    )
    assert closed["status"] == "CLOSED_VIOLATION"
    report = create_board_report()
    first = validate_success(api.refresh_board_report(report["id"], analyst_headers))
    assert first["substantiated_finding_count"] == 1, (
        "only the non-privileged run's finding counts"
    )
    assert first["privileged_exclusion_count"] == 1
    assert first["caps_executing_count"] == 0
    assert first["red_officer_count"] == 0
    run_monitoring_cycle()
    mid = validate_success(api.get_self_test(self_test["id"], director_headers))
    assert mid["cycles_open"] == 1
    assert mid["status"] == "CLOSED_VIOLATION", "forfeiture at 2 cycles, not 1"
    cycle2 = run_monitoring_cycle()
    assert self_test["id"] in cycle2["privilege_lost_self_test_ids"]
    end = validate_success(api.get_self_test(self_test["id"], director_headers))
    assert end["status"] == "PRIVILEGE_LOST"
    assert end["disclosure_status"] == "DISCLOSABLE"
    second = validate_success(api.refresh_board_report(report["id"], analyst_headers))
    assert second["substantiated_finding_count"] == 2, (
        "previously excluded finding restored once privilege is lost"
    )
    assert second["privileged_exclusion_count"] == 0


def test_board_report_tiling_quarter_rules(api, analyst_headers):
    """PRD §3.11: "An analyst creates one by supplying `period_start` and
    `period_end` that must span exactly one calendar quarter — anything
    else is `ERR_PERIOD_NOT_QUARTER` (HTTP 422) — and must neither overlap
    an existing report's period (`ERR_PERIOD_OVERLAP`, HTTP 409) nor leave
    a gap against the latest existing report's `period_end`
    (`ERR_PERIOD_GAP`, HTTP 409); the very first report is exempt from the
    gap check."

    Design: Corner/validations/board_report_tiling_quarter_rules
    """
    first = validate_success(
        api.create_board_report(
            {"period_start": "2026-07-01", "period_end": "2026-10-01"},
            analyst_headers,
        ),
        expected_status=201,
    )
    assert first["status"] == "DRAFT", "first report: gap check vacuous"
    second = validate_success(
        api.create_board_report(
            {"period_start": "2026-10-01", "period_end": "2027-01-01"},
            analyst_headers,
        ),
        expected_status=201,
    )
    assert second["status"] == "DRAFT", "contiguous quarter accepted"
    resp_gap = api.create_board_report(
        {"period_start": "2027-02-01", "period_end": "2027-05-01"},
        analyst_headers,
    )
    validate_error(resp_gap, ApiErrorId.ERR_PERIOD_GAP, expected_status=409)
    resp_ovl = api.create_board_report(
        {"period_start": "2026-09-01", "period_end": "2027-01-01"},
        analyst_headers,
    )
    validate_error(resp_ovl, ApiErrorId.ERR_PERIOD_OVERLAP, expected_status=409)
    resp_q = api.create_board_report(
        {"period_start": "2027-01-01", "period_end": "2027-03-01"},
        analyst_headers,
    )
    validate_error(resp_q, ApiErrorId.ERR_PERIOD_NOT_QUARTER, expected_status=422)
    third = validate_success(
        api.create_board_report(
            {"period_start": "2027-01-01", "period_end": "2027-04-01"},
            analyst_headers,
        ),
        expected_status=201,
    )
    assert third["status"] == "DRAFT", "exactly contiguous quarter accepted"
