"""
Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) so setup failures surface as clear
"Setup failed" errors instead of confusing assertion failures.

Identity threading: the Tenant role is entity-backed (PRD §2.1), so every
tenant-scoped call threads the owning Tenant record's id through
make_tenant_headers(tenant["id"]) — never the shared fallback constant.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_acdbe_review_payload,
    create_audit_payload,
    create_enplanement_snapshot_payload,
    create_lease_payload,
    create_payment_payload,
    create_sales_report_payload,
    create_settlement_payload,
    create_tenant_payload,
    create_ti_draw_payload,
    create_violation_payload,
    create_waiver_payload,
)
from .test_users import TEST_USERS, make_tenant_headers

ADMIN = TEST_USERS["admin_headers"]
ANALYST = TEST_USERS["analyst_headers"]
AUDITOR = TEST_USERS["auditor_headers"]

# Clock instant used to close settlement year 2026 (PRD §3.5: invoice requires the
# current date to be later than the last day of the period year).
YEAR_2026_CLOSED_CLOCK = "2027-01-15T00:00:00Z"


# ─── Tier 1: single-entity creation ──────────────────────────────────

def create_tenant(**overrides):
    """Register a concessionaire. Returns the Tenant."""
    res = api_client.create_tenant(create_tenant_payload(**overrides), ADMIN)
    return get_success_data(res)


def create_draft_lease(tenant, **overrides):
    """Create a lease in DRAFT for the given tenant. Returns the Lease."""
    res = api_client.create_lease(create_lease_payload(tenant["id"], **overrides), ADMIN)
    return get_success_data(res)


def activate_lease(lease):
    """Drive DRAFT -> ACTIVE. Returns the updated Lease."""
    res = api_client.transition_lease(lease["id"], {"action": "ACTIVATE"}, ADMIN)
    return get_success_data(res)


def get_lease(lease_id, headers=ADMIN):
    return get_success_data(api_client.get_lease(lease_id, headers))


def get_settlement(settlement_id, headers=ANALYST):
    return get_success_data(api_client.get_settlement(settlement_id, headers))


def advance_clock(to_iso8601):
    """Set the logical clock (runs the lease expiry and overdue sweeps)."""
    res = api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN)
    return get_success_data(res)


# ─── Tier 2: active lease scenario ───────────────────────────────────

def setup_active_lease(**lease_overrides):
    """Tenant + lease driven to ACTIVE. Returns {"tenant", "lease"}."""
    tenant = create_tenant(**lease_overrides.pop("tenant_overrides", {}))
    lease = create_draft_lease(tenant, **lease_overrides)
    lease = activate_lease(lease)
    return {"tenant": tenant, "lease": lease}


# ─── Tier 3: sales report lifecycle shortcuts ────────────────────────

def file_sales_report(lease, tenant, period_month, gross_sales_cents):
    """Tenant files a report; it is born DRAFT. Returns the SalesReport."""
    res = api_client.create_sales_report(
        create_sales_report_payload(
            lease["id"],
            period_month=period_month,
            gross_sales_cents=gross_sales_cents,
        ),
        make_tenant_headers(tenant["id"]),
    )
    return get_success_data(res)


def submit_sales_report(report, tenant):
    """DRAFT/DISPUTED -> SUBMITTED by the owning tenant."""
    res = api_client.transition_sales_report(
        report["id"], {"action": "SUBMIT"}, make_tenant_headers(tenant["id"])
    )
    return get_success_data(res)


def accept_sales_report(report):
    """SUBMITTED -> ACCEPTED by the analyst."""
    res = api_client.transition_sales_report(report["id"], {"action": "ACCEPT"}, ANALYST)
    return get_success_data(res)


def dispute_sales_report(report):
    """SUBMITTED -> DISPUTED by the analyst."""
    res = api_client.transition_sales_report(report["id"], {"action": "DISPUTE"}, ANALYST)
    return get_success_data(res)


def file_and_accept_report(lease, tenant, period_month, gross_sales_cents):
    """File -> SUBMIT -> ACCEPT. Returns the ACCEPTED SalesReport."""
    report = file_sales_report(lease, tenant, period_month, gross_sales_cents)
    report = submit_sales_report(report, tenant)
    return accept_sales_report(report)


# ─── Tier 3: settlement lifecycle shortcuts ──────────────────────────

def create_settlement(lease, period_year=2026):
    """Open the annual settlement; it is born ACCRUING (PROVISIONAL)."""
    res = api_client.create_settlement(
        create_settlement_payload(lease["id"], period_year=period_year), ADMIN
    )
    return get_success_data(res)


def setup_settlement_with_reports(report_specs, period_year=2026, **lease_overrides):
    """
    ACTIVE lease + ACCRUING settlement + one ACCEPTED report per
    (period_month, gross_sales_cents) in report_specs.
    Returns {"tenant", "lease", "settlement", "reports"}.
    """
    sc = setup_active_lease(**lease_overrides)
    settlement = create_settlement(sc["lease"], period_year=period_year)
    reports = [
        file_and_accept_report(sc["lease"], sc["tenant"], month, gross)
        for month, gross in report_specs
    ]
    return {
        "tenant": sc["tenant"],
        "lease": sc["lease"],
        "settlement": settlement,
        "reports": reports,
    }


def setup_invoiced_settlement(
    report_specs=(), period_year=2026, close_clock=YEAR_2026_CLOSED_CLOCK,
    **lease_overrides,
):
    """
    Full setup through INVOICED: active lease + ACCRUING settlement + the given
    ACCEPTED reports, then the clock is advanced past the settlement year's end
    and the settlement is invoiced (FINAL recalculation).
    Returns {"tenant", "lease", "settlement", "reports"}.
    """
    sc = setup_settlement_with_reports(
        report_specs, period_year=period_year, **lease_overrides
    )
    advance_clock(close_clock)
    res = api_client.invoice_settlement(sc["settlement"]["id"], ANALYST)
    sc["settlement"] = get_success_data(res)
    return sc


def setup_paid_settlement(
    report_specs=(), period_year=2026, close_clock=YEAR_2026_CLOSED_CLOCK,
    **lease_overrides,
):
    """
    Full setup through PAID: INVOICED settlement paid in full by the tenant.
    Returns {"tenant", "lease", "settlement", "reports", "payment"}.
    """
    sc = setup_invoiced_settlement(
        report_specs, period_year=period_year, close_clock=close_clock, **lease_overrides
    )
    settlement = sc["settlement"]
    res = api_client.create_payment(
        settlement["id"],
        create_payment_payload(amount_cents=settlement["balance_due_cents"]),
        make_tenant_headers(sc["tenant"]["id"]),
    )
    sc["payment"] = get_success_data(res)
    sc["settlement"] = get_settlement(settlement["id"])
    return sc


# ─── Tier 3: TI draws, waivers, violations, audits, reviews ──────────

def create_draw(lease, tenant, amount_cents, milestone="DESIGN"):
    """Tenant requests a buildout draw; it is born REQUESTED."""
    res = api_client.create_ti_draw(
        create_ti_draw_payload(lease["id"], amount_cents=amount_cents, milestone=milestone),
        make_tenant_headers(tenant["id"]),
    )
    return get_success_data(res)


def transition_draw(draw, action, headers):
    return get_success_data(
        api_client.transition_ti_draw(draw["id"], {"action": action}, headers)
    )


def approve_draw(draw):
    return transition_draw(draw, "APPROVE", ADMIN)


def disburse_draw(draw):
    return transition_draw(draw, "DISBURSE", ADMIN)


def cancel_draw(draw, tenant):
    return transition_draw(draw, "CANCEL", make_tenant_headers(tenant["id"]))


def create_waiver(lease, tenant, closure_start_date, closure_end_date, reason="renovation"):
    """Tenant requests a closure window; it is born REQUESTED."""
    res = api_client.create_waiver(
        create_waiver_payload(
            lease["id"],
            closure_start_date=closure_start_date,
            closure_end_date=closure_end_date,
            reason=reason,
        ),
        make_tenant_headers(tenant["id"]),
    )
    return get_success_data(res)


def transition_waiver(waiver, action):
    return get_success_data(
        api_client.transition_waiver(waiver["id"], {"action": action}, ADMIN)
    )


def create_violation(lease, **overrides):
    """Analyst records a policy violation against an ACTIVE lease."""
    res = api_client.create_violation(
        create_violation_payload(lease["id"], **overrides), ANALYST
    )
    return get_success_data(res)


def create_audit(lease, period_start_month="2026-01", period_end_month="2026-03"):
    """Auditor opens an audit case; it is born OPENED."""
    res = api_client.create_audit(
        create_audit_payload(
            lease["id"],
            period_start_month=period_start_month,
            period_end_month=period_end_month,
        ),
        AUDITOR,
    )
    return get_success_data(res)


def create_acdbe_review(lease, period_year=2026):
    """Analyst schedules the annual participation review; it is born SCHEDULED."""
    res = api_client.create_acdbe_review(
        create_acdbe_review_payload(lease["id"], period_year=period_year), ANALYST
    )
    return get_success_data(res)


def create_enplanement_snapshot(month, enplanements):
    """Admin publishes a month's enplanement count."""
    res = api_client.create_enplanement_snapshot(
        create_enplanement_snapshot_payload(month=month, enplanements=enplanements),
        ADMIN,
    )
    return get_success_data(res)


# ─── Tier 4: performance-review scenario ─────────────────────────────

def setup_spe_scenario():
    """
    ACTIVE lease (min_spe_cents 1000) with three ACCEPTED reports and matching
    enplanement snapshots, arranged so the trailing-twelve-month and
    year-to-date windows disagree (PRD §3.8):
      reports    2025-12: 100,000 | 2026-06: 300,000 | 2026-07: 900,000
      snapshots  2025-12: 200,000 | 2026-06: 100,000 | 2026-07: 150,000
    The logical clock is left at its startup default (2026-08-01).
    Returns {"tenant", "lease", "reports"}.
    """
    sc = setup_active_lease(term_start_date="2025-11-01")
    reports = [
        file_and_accept_report(sc["lease"], sc["tenant"], "2025-12", 100_000),
        file_and_accept_report(sc["lease"], sc["tenant"], "2026-06", 300_000),
        file_and_accept_report(sc["lease"], sc["tenant"], "2026-07", 900_000),
    ]
    create_enplanement_snapshot("2025-12", 200_000)
    create_enplanement_snapshot("2026-06", 100_000)
    create_enplanement_snapshot("2026-07", 150_000)
    return {"tenant": sc["tenant"], "lease": sc["lease"], "reports": reports}
