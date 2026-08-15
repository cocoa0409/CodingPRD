"""Composite setup helpers.

Every fixture builds its preconditions from scratch using only PRD-declared
endpoints (the harness restarts the server before each test, so the database
starts empty). Setup calls use get_success_data() so setup failures surface as
clear "Setup failed" errors.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_agreement_payload,
    create_audit_finding_payload,
    create_audit_payload,
    create_distribution_run_payload,
    create_licensee_payload,
    create_milestone_payload,
    create_royalty_report_payload,
    create_sublicense_grant_payload,
    make_report_line,
)
from .test_users import (
    make_analyst_headers,
    make_counsel_headers,
    make_finance_headers,
    make_ipadmin_headers,
    make_licensee_headers,
)

ANALYST = make_analyst_headers("ana-1")
COUNSEL_1 = make_counsel_headers("counsel-1")
COUNSEL_2 = make_counsel_headers("counsel-2")
FIN_1 = make_finance_headers("fin-1")
FIN_2 = make_finance_headers("fin-2")
FIN_3 = make_finance_headers("fin-3")
IPADMIN = make_ipadmin_headers("ipadmin-1")


# ----------------------------------------------------------------------
# Tier 1: state progression
# ----------------------------------------------------------------------

def create_licensee(**overrides):
    """Create one ACTIVE licensee. Returns the licensee dict."""
    resp = api_client.create_licensee(create_licensee_payload(**overrides), ANALYST)
    data = get_success_data(resp)
    assert resp.status_code == 201, f"Setup failed (create licensee): {resp.text}"
    return data


def licensee_headers_for(licensee):
    return make_licensee_headers(licensee["id"])


def create_draft_agreement(licensee, **overrides):
    """Create a DRAFT agreement for the given licensee."""
    resp = api_client.create_agreement(create_agreement_payload(licensee["id"], **overrides), ANALYST)
    data = get_success_data(resp)
    assert resp.status_code == 201, f"Setup failed (create agreement): {resp.text}"
    return data


def activate_agreement(agreement_id):
    resp = api_client.agreement_lifecycle(agreement_id, {"action": "ACTIVATE"}, ANALYST)
    data = get_success_data(resp)
    assert resp.status_code == 200, f"Setup failed (activate agreement): {resp.text}"
    return data


def create_active_agreement(licensee=None, **overrides):
    """Create licensee (if not given) + agreement, then ACTIVATE.

    Returns (licensee, agreement).
    """
    if licensee is None:
        licensee = create_licensee()
    agreement = create_draft_agreement(licensee, **overrides)
    agreement = activate_agreement(agreement["id"])
    return licensee, agreement


def suspend_agreement(agreement_id):
    resp = api_client.agreement_lifecycle(agreement_id, {"action": "SUSPEND"}, ANALYST)
    data = get_success_data(resp)
    assert resp.status_code == 200, f"Setup failed (suspend agreement): {resp.text}"
    return data


def terminate_agreement(agreement_id):
    resp = api_client.agreement_lifecycle(agreement_id, {"action": "TERMINATE"}, ANALYST)
    data = get_success_data(resp)
    assert resp.status_code == 200, f"Setup failed (terminate agreement): {resp.text}"
    return data


def suspend_licensee(licensee_id):
    resp = api_client.licensee_lifecycle(licensee_id, {"action": "SUSPEND"}, ANALYST)
    data = get_success_data(resp)
    assert resp.status_code == 200, f"Setup failed (suspend licensee): {resp.text}"
    return data


# ----------------------------------------------------------------------
# Tier 2: entity hierarchy
# ----------------------------------------------------------------------

def submit_report(agreement, licensee, *, period_start="2026-03-01T00:00:00Z",
                  period_end="2026-03-31T00:00:00Z", lines=None, **overrides):
    """Licensee submits a royalty report; returns the SUBMITTED report."""
    if lines is None:
        lines = [make_report_line()]
    payload = create_royalty_report_payload(
        agreement["id"], licensee["id"],
        period_start=period_start, period_end=period_end, lines=lines, **overrides,
    )
    resp = api_client.create_royalty_report(payload, licensee_headers_for(licensee))
    data = get_success_data(resp)
    assert resp.status_code == 201, f"Setup failed (submit report): {resp.text}"
    return data


def validate_report(report_id, benchmark_net_sales_cents=0):
    resp = api_client.validate_report(
        report_id, {"benchmark_net_sales_cents": benchmark_net_sales_cents}, ANALYST
    )
    data = get_success_data(resp)
    assert resp.status_code == 200, f"Setup failed (validate report): {resp.text}"
    return data


def accept_report(report_id, payload=None):
    resp = api_client.accept_report(report_id, payload or {}, ANALYST)
    data = get_success_data(resp)
    assert resp.status_code == 200, f"Setup failed (accept report): {resp.text}"
    return data


def create_validated_report(agreement, licensee, *, benchmark_net_sales_cents=0, **kwargs):
    """Submit + validate. Returns the report in VALIDATED (benchmark 0) or FLAGGED."""
    report = submit_report(agreement, licensee, **kwargs)
    return validate_report(report["id"], benchmark_net_sales_cents)


def create_accepted_report(agreement, licensee, *, benchmark_net_sales_cents=0,
                           accept_payload=None, **kwargs):
    """Submit + validate + accept. Returns the accepted report."""
    report = create_validated_report(
        agreement, licensee, benchmark_net_sales_cents=benchmark_net_sales_cents, **kwargs
    )
    return accept_report(report["id"], accept_payload)


def create_approved_grant(agreement, licensee, **overrides):
    """Request + approve a sublicense grant. Returns the APPROVED grant."""
    resp = api_client.create_sublicense_grant(
        create_sublicense_grant_payload(agreement["id"], **overrides),
        licensee_headers_for(licensee),
    )
    grant = get_success_data(resp)
    assert resp.status_code == 201, f"Setup failed (create grant): {resp.text}"
    resp = api_client.sublicense_decision(grant["id"], {"decision": "APPROVED"}, ANALYST)
    grant = get_success_data(resp)
    assert resp.status_code == 200, f"Setup failed (approve grant): {resp.text}"
    return grant


def create_milestone(agreement_id, **overrides):
    resp = api_client.create_milestone(create_milestone_payload(agreement_id, **overrides), ANALYST)
    data = get_success_data(resp)
    assert resp.status_code == 201, f"Setup failed (create milestone): {resp.text}"
    return data


# ----------------------------------------------------------------------
# Tier 3: audit / finding / dispute lifecycle shortcuts
# ----------------------------------------------------------------------

def create_audit(agreement, *, scope_period_start="2026-03-01T00:00:00Z",
                 scope_period_end="2026-03-31T00:00:00Z", opener_headers=None):
    resp = api_client.create_audit(
        create_audit_payload(
            agreement["id"],
            scope_period_start=scope_period_start,
            scope_period_end=scope_period_end,
        ),
        opener_headers or ANALYST,
    )
    data = get_success_data(resp)
    assert resp.status_code == 201, f"Setup failed (create audit): {resp.text}"
    return data


def advance_audit(audit_id, to_state):
    resp = api_client.advance_audit(audit_id, {"to_state": to_state}, ANALYST)
    data = get_success_data(resp)
    assert resp.status_code == 200, f"Setup failed (advance audit to {to_state}): {resp.text}"
    return data


def create_fieldwork_audit(agreement, **kwargs):
    """Audit created and advanced to FIELDWORK."""
    audit = create_audit(agreement, **kwargs)
    return advance_audit(audit["id"], "FIELDWORK")


def create_finding(audit_id, report_id, **overrides):
    resp = api_client.create_audit_finding(
        create_audit_finding_payload(audit_id, report_id, **overrides), ANALYST
    )
    data = get_success_data(resp)
    assert resp.status_code == 201, f"Setup failed (create finding): {resp.text}"
    return data


def setup_flagged_report(*, gross_sales_cents=100_000, benchmark_net_sales_cents=200_000,
                         tolerance_bp=1000, audit_window_months=24, **agreement_overrides):
    """Full chain: licensee + ACTIVE agreement + one FLAGGED report.

    Default numbers: reported net 100000 < round(200000 * 9000/10000) = 180000,
    so the report is FLAGGED. Returns dict with licensee, agreement, report.
    """
    licensee, agreement = create_active_agreement(
        underreport_tolerance_bp=tolerance_bp,
        audit_window_months=audit_window_months,
        **agreement_overrides,
    )
    report = submit_report(
        agreement, licensee,
        lines=[make_report_line(gross_sales_cents=gross_sales_cents)],
    )
    report = validate_report(report["id"], benchmark_net_sales_cents)
    assert report["status"] == "FLAGGED", (
        f"Setup failed: expected FLAGGED, got {report['status']}"
    )
    return {"licensee": licensee, "agreement": agreement, "report": report}


def setup_open_finding(audited_base_cents=180_000, opener_headers=None, **flagged_kwargs):
    """Flagged report + audit in FIELDWORK + one OPEN finding.

    Returns dict with licensee, agreement, report, audit, finding.
    """
    ctx = setup_flagged_report(**flagged_kwargs)
    audit = create_fieldwork_audit(ctx["agreement"], opener_headers=opener_headers)
    finding = create_finding(audit["id"], ctx["report"]["id"],
                             audited_base_cents=audited_base_cents)
    ctx.update({"audit": audit, "finding": finding})
    return ctx


def setup_open_dispute(opener_headers=None, **flagged_kwargs):
    """OPEN finding disputed by the owning licensee -> Dispute OPEN.

    Returns dict with licensee, agreement, report, audit, finding, dispute.
    """
    ctx = setup_open_finding(opener_headers=opener_headers, **flagged_kwargs)
    resp = api_client.dispute_finding(
        ctx["finding"]["id"], licensee_headers_for(ctx["licensee"])
    )
    dispute = get_success_data(resp)
    assert resp.status_code == 201, f"Setup failed (dispute finding): {resp.text}"
    ctx["dispute"] = dispute
    return ctx


def setup_dispute_in_negotiation(offer_amount_cents=30_000, counsel_headers=None, **kwargs):
    """Dispute with a PENDING counsel offer -> NEGOTIATION."""
    ctx = setup_open_dispute(**kwargs)
    dispute = ctx["dispute"]
    resp = api_client.submit_offer(
        dispute["id"],
        {"amount_cents": offer_amount_cents, "expected_dispute_version": dispute["version"]},
        counsel_headers or COUNSEL_1,
    )
    dispute = get_success_data(resp)
    assert resp.status_code == 201, f"Setup failed (counsel offer): {resp.text}"
    assert dispute["status"] == "NEGOTIATION"
    ctx["dispute"] = dispute
    return ctx


def setup_ratification_pending(**kwargs):
    """Counsel offer accepted by the licensee -> RATIFICATION_PENDING."""
    ctx = setup_dispute_in_negotiation(**kwargs)
    resp = api_client.accept_offer(
        ctx["dispute"]["id"], licensee_headers_for(ctx["licensee"])
    )
    dispute = get_success_data(resp)
    assert resp.status_code == 200, f"Setup failed (accept offer): {resp.text}"
    assert dispute["status"] == "RATIFICATION_PENDING"
    ctx["dispute"] = dispute
    return ctx


def setup_settled_dispute(ratifier_headers=None, **kwargs):
    """Full lifecycle through SETTLED."""
    ctx = setup_ratification_pending(**kwargs)
    resp = api_client.ratify_dispute(ctx["dispute"]["id"], ratifier_headers or COUNSEL_1)
    dispute = get_success_data(resp)
    assert resp.status_code == 200, f"Setup failed (ratify): {resp.text}"
    assert dispute["status"] == "SETTLED"
    ctx["dispute"] = dispute
    return ctx


# ----------------------------------------------------------------------
# Tier 4: accumulation / threshold targeting
# ----------------------------------------------------------------------

def setup_agreement_with_pool(*, royalty_cents=5000, base_rate_bp=500, **agreement_overrides):
    """ACTIVE agreement whose undistributed pool holds exactly royalty_cents.

    With the default 500 bp rate and no floor, an accepted report whose net
    sales equal royalty_cents * 10000 / base_rate_bp posts exactly
    royalty_cents. Returns dict with licensee, agreement, report.
    """
    net_sales = royalty_cents * 10000 // base_rate_bp
    licensee, agreement = create_active_agreement(
        base_rate_bp=base_rate_bp, **agreement_overrides
    )
    report = create_accepted_report(
        agreement, licensee,
        lines=[make_report_line(gross_sales_cents=net_sales)],
    )
    return {"licensee": licensee, "agreement": agreement, "report": report}


def create_draft_run(agreement, pool_cents, creator_headers=None, **overrides):
    resp = api_client.create_distribution_run(
        create_distribution_run_payload(agreement["id"], pool_cents=pool_cents, **overrides),
        creator_headers or FIN_1,
    )
    data = get_success_data(resp)
    assert resp.status_code == 201, f"Setup failed (create run): {resp.text}"
    return data


def approve_run(run_id, approver_headers=None):
    resp = api_client.approve_distribution_run(run_id, approver_headers or FIN_2)
    data = get_success_data(resp)
    assert resp.status_code == 200, f"Setup failed (approve run): {resp.text}"
    return data


def setup_posted_run(*, pool_cents=5000, **pool_kwargs):
    """Agreement with pool + a POSTED distribution run consuming pool_cents."""
    ctx = setup_agreement_with_pool(**pool_kwargs)
    run = create_draft_run(ctx["agreement"], pool_cents)
    run = approve_run(run["id"])
    ctx["run"] = run
    return ctx


# ----------------------------------------------------------------------
# Tier 5: clock / terminal state
# ----------------------------------------------------------------------

def set_clock(to_iso8601):
    resp = api_client.set_clock(to_iso8601, IPADMIN)
    data = get_success_data(resp)
    assert resp.status_code == 200, f"Setup failed (set clock): {resp.text}"
    return data


def get_agreement(agreement_id, headers=None):
    resp = api_client.get_agreement(agreement_id, headers or ANALYST)
    data = get_success_data(resp)
    assert resp.status_code == 200, f"Setup failed (get agreement): {resp.text}"
    return data


def get_licensee(licensee_id, headers=None):
    resp = api_client.get_licensee(licensee_id, headers or ANALYST)
    data = get_success_data(resp)
    assert resp.status_code == 200, f"Setup failed (get licensee): {resp.text}"
    return data


def get_milestone(milestone_id, headers=None):
    resp = api_client.get_milestone(milestone_id, headers or ANALYST)
    data = get_success_data(resp)
    assert resp.status_code == 200, f"Setup failed (get milestone): {resp.text}"
    return data


def get_finding(finding_id, headers=None):
    resp = api_client.get_audit_finding(finding_id, headers or ANALYST)
    data = get_success_data(resp)
    assert resp.status_code == 200, f"Setup failed (get finding): {resp.text}"
    return data
