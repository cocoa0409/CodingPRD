"""Rebate-claim reimbursement: estimated vs audited amounts, the uptime gate,
work-order SLA, and four-eyes approval.

Difficulty: dual_variant_calc/rebate_estimated_vs_audited_amount,
boundary_precision_check/rebate_uptime_threshold_boundary_exactly_min_passes.
Corner: calculations/work_order_sla..., rbac/approve_rebate_by_submitter....
"""
from test_helpers import (
    validate_success, validate_error,
    admin_headers, make_admin_headers, tech_headers,
    new_site, new_station, new_port, set_clock, get_claim,
    setup_submitted_claim_with_downtime, setup_draft_grant_claim,
    setup_audited_compliant_claim,
)


# --------------------------------------------------------------------------- #
# dual_variant_calc / rebate_estimated_vs_audited_amount
# --------------------------------------------------------------------------- #
def test_audit_collapses_amount_when_measured_uptime_below_min(api):
    """PRD §3.7: "The `measured_uptime_pct` is 100 times the quantity one minus the
    ratio of critical downtime minutes to period minutes, rounded half-up to two decimal
    places and clamped to the range 0 through 100. If `measured_uptime_pct` is at least
    the grant's `min_uptime_pct`, the `audited_amount_cents` is set equal to
    `estimated_amount_cents` and `compliance_status` stays `COMPLIANT`; otherwise
    `audited_amount_cents` collapses to 0 and `compliance_status` becomes `NON_COMPLIANT`."

    Design: Difficulty/dual_variant_calc/rebate_estimated_vs_audited_amount
    """
    ctx = setup_submitted_claim_with_downtime()
    audited = validate_success(api.audit_rebate_claim(ctx["claim_id"], make_admin_headers("admin-2")), 200)
    assert audited["estimated_amount_cents"] == 20000
    assert audited["audited_amount_cents"] == 0
    assert audited["measured_uptime_pct"] == 93.55
    assert audited["compliance_status"] == "NON_COMPLIANT"


def test_submit_sets_positive_estimated_amount(api):
    """PRD §3.7: "On success the system sets the provisional `estimated_amount_cents` to
    the reported delivered energy `reported_energy_kwh` multiplied by the grant's
    `reimbursement_rate_cents_per_kwh`, rounded half-up to a whole cent and then capped
    so it never exceeds the grant's `reimbursement_cap_cents`; it sets `compliance_status`
    to `COMPLIANT` ... The estimated amount is always positive once the reported-uptime
    gate passes and ignores any audited downtime."

    Design: Difficulty/dual_variant_calc/rebate_estimated_vs_audited_amount
    """
    ctx = setup_submitted_claim_with_downtime()  # already SUBMITTED, not yet audited
    claim = get_claim(ctx["claim_id"])
    assert claim["status"] == "SUBMITTED"
    assert claim["estimated_amount_cents"] == 20000
    assert claim["compliance_status"] == "COMPLIANT"


# --------------------------------------------------------------------------- #
# boundary_precision_check / rebate_uptime_threshold_boundary_exactly_min_passes
# --------------------------------------------------------------------------- #
def test_submit_uptime_exactly_at_minimum_passes(api):
    """PRD §3.7: "Submitting a `DRAFT` claim into `SUBMITTED` passes a compliance gate:
    the `reported_uptime_pct` must be at least the grant's `min_uptime_pct` (a value
    exactly equal to the minimum passes), or the submission is refused with
    `ERR_UPTIME_BELOW_THRESHOLD`."

    Design: Difficulty/boundary_precision_check/rebate_uptime_threshold_boundary_exactly_min_passes
    """
    ctx = setup_draft_grant_claim(reported_uptime_pct=97.0)
    submitted = validate_success(api.submit_rebate_claim(ctx["claim_id"], make_admin_headers("admin-1")), 200)
    assert submitted["status"] == "SUBMITTED"
    assert submitted["estimated_amount_cents"] == 20000
    assert submitted["compliance_status"] == "COMPLIANT"


def test_submit_uptime_just_below_minimum_rejected(api):
    """PRD §3.7: "Submitting a `DRAFT` claim into `SUBMITTED` passes a compliance gate:
    the `reported_uptime_pct` must be at least the grant's `min_uptime_pct` (a value
    exactly equal to the minimum passes), or the submission is refused with
    `ERR_UPTIME_BELOW_THRESHOLD`."

    Design: Difficulty/boundary_precision_check/rebate_uptime_threshold_boundary_exactly_min_passes
    """
    ctx = setup_draft_grant_claim(reported_uptime_pct=96.99)
    res = api.submit_rebate_claim(ctx["claim_id"], make_admin_headers("admin-1"))
    validate_error(res, "ERR_UPTIME_BELOW_THRESHOLD")


# --------------------------------------------------------------------------- #
# Corner: calculations / work_order_sla_breached_when_resolved_after_due
# --------------------------------------------------------------------------- #
def test_critical_work_order_sla_breach_when_resolved_after_due(api):
    """PRD §3.6: "The service-level due time `sla_due_at` is `opened_at` plus a
    severity-dependent allowance: 4 hours for `CRITICAL`, 24 hours for `MEDIUM`, and 72
    hours for `LOW`. The `sla_breached` flag is true when the breach reference instant is
    strictly later than `sla_due_at`, where the breach reference is `resolved_at` once
    the order is `RESOLVED` and the current clock instant while it is still `OPEN`."

    Design: Corner/calculations/work_order_sla_breached_when_resolved_after_due
    """
    site = new_site()
    station = new_station(site["id"])
    port = new_port(station["id"], power_kw=180)
    set_clock("2026-05-06T00:00:00Z")
    wo = validate_success(
        api.create_work_order({"port_id": port["id"], "severity": "CRITICAL", "description": "fault"},
                              tech_headers()), 201)
    set_clock("2026-05-06T06:00:00Z")
    resolved = validate_success(api.resolve_work_order(wo["id"], tech_headers()), 200)
    assert resolved["sla_due_at"] == "2026-05-06T04:00:00.000Z"
    assert resolved["sla_breached"] is True


# --------------------------------------------------------------------------- #
# Corner: rbac / approve_rebate_by_submitter_returns_segregation_of_duties
# --------------------------------------------------------------------------- #
def test_approve_by_submitter_returns_segregation_of_duties(api):
    """PRD §3.7: "Approving an `AUDITED` claim into the terminal `APPROVED` state
    enforces a four-eyes segregation of duties: the approving administrator's `X-User-ID`
    must differ from `submitted_by_user_id`, or the approval is refused with
    `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/rbac/approve_rebate_by_submitter_returns_segregation_of_duties
    """
    ctx = setup_audited_compliant_claim(submitter="admin-1")
    res = api.approve_rebate_claim(ctx["claim_id"], make_admin_headers("admin-1"))
    validate_error(res, "ERR_SEGREGATION_OF_DUTIES")
