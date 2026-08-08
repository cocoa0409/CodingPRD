"""Monitoring visits, the critical-finding cascade, single audits, findings, and risk scoring."""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    setup_active_subaward,
    setup_active_subaward_with_drawdown,
    setup_active_subaward_with_scheduled_visit,
    conduct_visit_with_finding,
    get_subaward,
    create_nonprofit,
    create_monitoring_visit_payload,
    create_single_audit_payload,
    make_grants_manager_headers,
    make_subrecipient_headers,
    make_program_officer_headers,
)


def test_monitoring_visit_interior_overlap_rejected(api):
    """PRD §3.8: "The system rejects a window that overlaps another visit already scheduled by
    the same monitor, treating each window as half-open over its start up to but not including
    its end, so two windows that merely touch at an endpoint are allowed but any interior
    overlap is rejected with ERR_VISIT_OVERLAP."

    Design: Difficulty/resource_temporal_overlap/monitoring_visit_same_monitor_half_open_overlap
    """
    ctx = setup_active_subaward_with_scheduled_visit(
        scheduled_start="2026-07-10T09:00:00Z", scheduled_end="2026-07-10T12:00:00Z", monitor="gm-1"
    )
    res = api.create_monitoring_visit(
        ctx["sub_id"],
        create_monitoring_visit_payload("2026-07-10T11:00:00Z", "2026-07-10T13:00:00Z"),
        make_grants_manager_headers("gm-1"),
    )
    validate_error(res, "ERR_VISIT_OVERLAP")


def test_monitoring_visit_touching_endpoint_allowed(api):
    """PRD §3.8: "treating each window as half-open over its start up to but not including its
    end, so two windows that merely touch at an endpoint are allowed but any interior overlap
    is rejected with ERR_VISIT_OVERLAP."

    Design: Difficulty/resource_temporal_overlap/monitoring_visit_same_monitor_half_open_overlap
    """
    ctx = setup_active_subaward_with_scheduled_visit(
        scheduled_start="2026-07-10T09:00:00Z", scheduled_end="2026-07-10T12:00:00Z", monitor="gm-1"
    )
    res = api.create_monitoring_visit(
        ctx["sub_id"],
        create_monitoring_visit_payload("2026-07-10T12:00:00Z", "2026-07-10T13:00:00Z"),
        make_grants_manager_headers("gm-1"),
    )
    visit = validate_success(res, 201)
    assert visit["status"] == "SCHEDULED"


def test_critical_finding_suspends_subaward_and_returns_drawdown(api):
    """PRD §3.8: "When the raised finding's severity is CRITICAL, the system cascades a
    suspension onto the subaward, transitioning it from ACTIVE to SUSPENDED, which in turn
    returns that subaward's pending drawdowns."

    Design: Difficulty/transitive_cascade/critical_finding_suspends_subaward_and_returns_drawdown
    """
    ctx = setup_active_subaward_with_drawdown(drawdown_amount=5_000_000)
    visit = validate_success(
        api.create_monitoring_visit(
            ctx["sub_id"],
            create_monitoring_visit_payload("2026-07-10T09:00:00Z", "2026-07-10T12:00:00Z"),
            make_grants_manager_headers("gm-1"),
        ),
        201,
    )
    validate_success(
        api.conduct_visit(visit["id"], {"outcome": "DEFICIENT", "finding_severity": "CRITICAL"},
                          make_grants_manager_headers("gm-1")),
        200,
    )
    assert get_subaward(ctx["sub_id"])["status"] == "SUSPENDED"
    dd = validate_success(api.get_drawdown(ctx["dd_id"], make_program_officer_headers()), 200)
    assert dd["status"] == "RETURNED"


def test_critical_finding_cascade_releases_obligation(api):
    """PRD §2.7: "Each of these cascades also reconciles the subaward's obligation ledger,
    crediting back amounts that are no longer obligated."
    PRD §3.9: "Suspension — whether requested directly or cascaded from a CRITICAL finding —
    transitions each of the subaward's drawdowns that is currently SUBMITTED to RETURNED,
    crediting the subaward's obligated_cents back by each returned drawdown's prior provisional
    amount."

    Design: Difficulty/transitive_cascade/critical_finding_suspends_subaward_and_returns_drawdown
    """
    ctx = setup_active_subaward_with_drawdown(drawdown_amount=5_000_000)
    visit = validate_success(
        api.create_monitoring_visit(
            ctx["sub_id"],
            create_monitoring_visit_payload("2026-07-10T09:00:00Z", "2026-07-10T12:00:00Z"),
            make_grants_manager_headers("gm-1"),
        ),
        201,
    )
    validate_success(
        api.conduct_visit(visit["id"], {"outcome": "DEFICIENT", "finding_severity": "CRITICAL"},
                          make_grants_manager_headers("gm-1")),
        200,
    )
    assert get_subaward(ctx["sub_id"])["obligated_cents"] == 0


def test_accept_audit_with_material_weakness_creates_finding(api):
    """PRD §3.8: "When the accepted audit's `material_weakness` is true, acceptance raises a
    `Finding` in `OPEN` whose `source_kind` is `SINGLE_AUDIT`, whose `origin_ref_id` points to
    this audit, and whose `severity` is `HIGH`, charged against a single selected subaward."

    Design: Corner/endpoints/single_audit_accept_material_weakness_creates_finding
    """
    ctx = setup_active_subaward()
    audit = validate_success(
        api.create_single_audit(
            ctx["np_id"],
            create_single_audit_payload(2026, 80_000_000, material_weakness=True,
                                        reported_finding_count=1),
            make_subrecipient_headers(ctx["np_id"]),
        ),
        201,
    )
    validate_success(api.accept_single_audit(audit["id"], make_grants_manager_headers("gm-1")), 200)

    data, meta = validate_paginated(
        api.list_findings(ctx["sub_id"], make_grants_manager_headers("gm-1"))
    )
    assert meta["total_count"] == 1
    assert data[0]["source_kind"] == "SINGLE_AUDIT"
    assert data[0]["severity"] == "HIGH"


def test_reject_cap_returns_finding_to_open(api):
    """PRD §3.8: "A `GrantsManager` either accepts the plan, moving it from `CAP_SUBMITTED` to
    `CAP_ACCEPTED`, or rejects it with an optional `reason`, moving it from `CAP_SUBMITTED` back
    to `OPEN` and clearing the stored `corrective_action_plan`."

    Design: Corner/state_machines/finding_reject_cap_returns_to_open_cycle
    """
    ctx = setup_active_subaward_with_scheduled_visit()
    finding = conduct_visit_with_finding(ctx["sub_id"], ctx["visit_id"], "MODERATE")
    validate_success(
        api.submit_cap(finding["id"], {"corrective_action_plan": "we will fix X"},
                       make_subrecipient_headers(ctx["np_id"])),
        200,
    )
    res = api.reject_cap(finding["id"], {"reason": "insufficient"}, make_grants_manager_headers("gm-1"))
    updated = validate_success(res, 200)
    assert updated["status"] == "OPEN"


def test_single_audit_required_at_exact_threshold(api):
    """PRD §3.8: "On submission the system computes audit_required, which is true exactly when
    total_federal_expenditures_cents is at least 750,000 dollars (75,000,000 cents):
    expenditures of exactly 75,000,000 cents require an audit, while 74,999,999 cents do not."

    Design: Difficulty/boundary_precision_check/single_audit_threshold_exact_boundary
    """
    np = create_nonprofit()
    res = api.create_single_audit(
        np["id"], create_single_audit_payload(2026, 75_000_000),
        make_subrecipient_headers(np["id"]),
    )
    audit = validate_success(res, 201)
    assert audit["audit_required"] is True


def test_single_audit_not_required_one_cent_below_threshold(api):
    """PRD §3.8: "expenditures of exactly 75,000,000 cents require an audit, while 74,999,999
    cents do not."

    Design: Difficulty/boundary_precision_check/single_audit_threshold_exact_boundary
    """
    np = create_nonprofit()
    res = api.create_single_audit(
        np["id"], create_single_audit_payload(2026, 74_999_999),
        make_subrecipient_headers(np["id"]),
    )
    audit = validate_success(res, 201)
    assert audit["audit_required"] is False


def test_risk_score_low_tier_computed(api):
    """PRD §3.7: "when there is no single audit on file and expenditures fall below that
    threshold, it is 10 ... The velocity_component reflects this subaward's disbursement pace as
    the ratio of its disbursed_cents to its total_budget_cents: the component is 20 when that
    ratio exceeds 0.90, 10 when it is at least 0.50 but not above 0.90, and 0 otherwise. The
    size_component is 10 when the subaward's total_budget_cents is at least 500,000 dollars
    (50,000,000 cents) and 5 otherwise."
    PRD §3.7: "The risk_tier is HIGH when the score is at least 60, MODERATE when it is at least
    30 but below 60, and LOW below 30."

    findings 0 + audit 10 + velocity 0 + size 5 = 15 -> LOW.

    Design: Corner/calculations/risk_score_low_tier_computed
    """
    ctx = setup_active_subaward()  # total 11000000, no findings/drawdowns/audit
    res = api.create_risk_assessment(ctx["sub_id"], make_grants_manager_headers("gm-1"))
    assessment = validate_success(res, 201)
    assert assessment["risk_score"] == 15
    assert assessment["risk_tier"] == "LOW"
