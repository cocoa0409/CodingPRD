"""Composite setup helpers.

Multi-step arrangements used across the suite. All setup calls use the lenient
`get_success_data` validator so a setup failure surfaces as a clear
"Setup failed" message rather than a confusing assertion error.

Ordering note: billing rows are created as DRAFT before activation (the
activation gate accepts a DRAFT or ISSUED billing for the current fiscal
year, PRD §3.3) and are issued only after the lease is ACTIVE, because
issuing a DRAFT billing requires the lease's status to be ACTIVE (PRD §3.5).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import DEFAULT_CLOCK_ISO, TEST_DEFAULTS
from .factories import (
    create_amendment_payload,
    create_audit_right_payload,
    create_compliance_doc_payload,
    create_critical_date_payload,
    create_lease_payload,
    create_property_payload,
    create_reconciliation_payload,
    create_recovery_billing_payload,
    create_recovery_pool_payload,
    create_rent_schedule_line_payload,
    create_tenant_challenge_payload,
)
from .test_users import TEST_USERS

ADMIN = TEST_USERS["platform_admin_headers"]
PM = TEST_USERS["portfolio_manager_headers"]
PROP_MGR = TEST_USERS["property_manager_headers"]
ACCT = TEST_USERS["lease_accountant_headers"]
ABSTRACTOR = TEST_USERS["abstractor_headers"]
CERTIFIER = TEST_USERS["certifier_headers"]


def setup_failed(step: str, resp):
    raise AssertionError(f"Setup failed at {step}: {resp.status_code} {resp.text}")


# ---------------------------------------------------------------------------
# Tier 1: atomic builders
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str = DEFAULT_CLOCK_ISO):
    """Drive the logical clock (PRD §2.7). Returns the response data."""
    resp = api_client.set_clock(to_iso8601, ADMIN)
    return get_success_data(resp)


def create_property(**overrides) -> dict:
    resp = api_client.create_property(create_property_payload(**overrides), ADMIN)
    if resp.status_code >= 400:
        setup_failed("create_property", resp)
    return get_success_data(resp)


def create_lease(property_id: str, **overrides) -> dict:
    """Create a Lease (begins DRAFT / PENDING / CURRENT, PRD §3.1)."""
    resp = api_client.create_lease(property_id, create_lease_payload(**overrides), PM)
    if resp.status_code >= 400:
        setup_failed("create_lease", resp)
    return get_success_data(resp)


def certify_lease(lease_id: str, abstractor_headers=None, certifier_headers=None) -> dict:
    """Walk abstraction_status PENDING -> ABSTRACTED -> CERTIFIED (PRD §3.2).

    Uses two distinct operator ids by default so the segregation-of-duties
    rule (PRD §2.9) is satisfied.
    """
    resp = api_client.abstract_lease(lease_id, abstractor_headers or ABSTRACTOR)
    if resp.status_code >= 400:
        setup_failed("abstract_lease", resp)
    resp = api_client.certify_lease(lease_id, certifier_headers or CERTIFIER)
    if resp.status_code >= 400:
        setup_failed("certify_lease", resp)
    return get_success_data(resp)


def create_certified_lease(property_id: str, **overrides) -> dict:
    lease = create_lease(property_id, **overrides)
    certify_lease(lease["id"])
    return get_success_data(api_client.get_lease(lease["id"], PM))


def add_schedule_line(lease_id: str, **overrides) -> dict:
    resp = api_client.create_rent_schedule_line(
        lease_id, create_rent_schedule_line_payload(**overrides), PM,
    )
    if resp.status_code >= 400:
        setup_failed("create_rent_schedule_line", resp)
    return get_success_data(resp)


def create_pool(property_id: str, **overrides) -> dict:
    resp = api_client.create_recovery_pool(
        property_id, create_recovery_pool_payload(**overrides), ACCT,
    )
    if resp.status_code >= 400:
        setup_failed("create_recovery_pool", resp)
    return get_success_data(resp)


def record_actuals(pool_id: str, actual_cents: int, headers=None) -> dict:
    resp = api_client.record_pool_actuals(
        pool_id, {"actual_cents": actual_cents}, headers or ACCT,
    )
    if resp.status_code >= 400:
        setup_failed("record_pool_actuals", resp)
    return get_success_data(resp)


def create_billing(lease_id: str, pool_id: str, **overrides) -> dict:
    payload = create_recovery_billing_payload(pool_id=pool_id, **overrides)
    resp = api_client.create_recovery_billing(lease_id, payload, ACCT)
    if resp.status_code >= 400:
        setup_failed("create_recovery_billing", resp)
    return get_success_data(resp)


def issue_billing(billing_id: str) -> dict:
    resp = api_client.issue_recovery_billing(billing_id, ACCT)
    if resp.status_code >= 400:
        setup_failed("issue_recovery_billing", resp)
    return get_success_data(resp)


def mark_billing_paid(billing_id: str) -> dict:
    resp = api_client.mark_recovery_billing_paid(billing_id, ACCT)
    if resp.status_code >= 400:
        setup_failed("mark_recovery_billing_paid", resp)
    return get_success_data(resp)


def activate_lease(lease_id: str) -> dict:
    resp = api_client.activate_lease(lease_id, PM)
    if resp.status_code >= 400:
        setup_failed("activate_lease", resp)
    return get_success_data(resp)


def get_lease(lease_id: str) -> dict:
    return get_success_data(api_client.get_lease(lease_id, PM))


# ---------------------------------------------------------------------------
# Tier 2: the standard active-lease arrangement
# ---------------------------------------------------------------------------

def setup_active_lease(
    clock: str = DEFAULT_CLOCK_ISO,
    fiscal_year: int = TEST_DEFAULTS["FISCAL_YEAR"],
    budgeted_cents: int = TEST_DEFAULTS["BUDGETED_CENTS"],
    pool_category: str = TEST_DEFAULTS["POOL_CATEGORY"],
    gross_up_floor_pct_bps=None,
    issue_billing_after_activation: bool = True,
    schedule_overrides: dict = None,
    **lease_overrides,
) -> dict:
    """Property + CERTIFIED Lease + full-term schedule line + RecoveryPool +
    one DRAFT RecoveryBilling + activation (gate met by the DRAFT billing),
    then optionally the billing is issued once the lease is ACTIVE (PRD §3.5).

    Returns a dict with property, lease (freshly re-read), pool, billing, and
    schedule_line entries.
    """
    set_clock(clock)
    prop = create_property()
    lease = create_lease(prop["id"], **lease_overrides)
    certify_lease(lease["id"])
    line = add_schedule_line(lease["id"], **(schedule_overrides or {}))
    pool_kwargs = {"category": pool_category, "fiscal_year": fiscal_year,
                   "budgeted_cents": budgeted_cents}
    if gross_up_floor_pct_bps is not None:
        pool_kwargs["gross_up_floor_pct_bps"] = gross_up_floor_pct_bps
    pool = create_pool(prop["id"], **pool_kwargs)
    billing = create_billing(lease["id"], pool["id"], fiscal_year=fiscal_year,
                             period_index=1)
    lease = activate_lease(lease["id"])
    if issue_billing_after_activation:
        billing = issue_billing(billing["id"])
    lease = get_lease(lease["id"])
    return {
        "property": prop,
        "lease": lease,
        "pool": pool,
        "billing": billing,
        "schedule_line": line,
    }


# ---------------------------------------------------------------------------
# Tier 3: reconciliation lifecycle shortcuts
# ---------------------------------------------------------------------------

def setup_posted_reconciliation(
    actual_cents: int = TEST_DEFAULTS["BUDGETED_CENTS"],
    poster_headers=None,
    **kwargs,
) -> dict:
    """Active lease + pool actuals recorded + Reconciliation OPEN -> POSTED."""
    ctx = setup_active_lease(**kwargs)
    record_actuals(ctx["pool"]["id"], actual_cents, headers=poster_headers)
    resp = api_client.create_reconciliation(
        ctx["lease"]["id"], create_reconciliation_payload(), ACCT,
    )
    if resp.status_code >= 400:
        setup_failed("create_reconciliation", resp)
    recon = get_success_data(resp)
    resp = api_client.post_reconciliation(recon["id"], poster_headers or ACCT)
    if resp.status_code >= 400:
        setup_failed("post_reconciliation", resp)
    ctx["reconciliation"] = get_success_data(resp)
    return ctx


def setup_approved_reconciliation(
    actual_cents: int = TEST_DEFAULTS["BUDGETED_CENTS"],
    poster_headers=None,
    approver_headers=None,
    **kwargs,
) -> dict:
    """Full path through APPROVED. Poster and approver default to distinct
    operator ids so reconciliation segregation (PRD §2.9) is satisfied."""
    ctx = setup_posted_reconciliation(
        actual_cents=actual_cents, poster_headers=poster_headers, **kwargs,
    )
    resp = api_client.approve_reconciliation(
        ctx["reconciliation"]["id"], approver_headers or PM,
    )
    if resp.status_code >= 400:
        setup_failed("approve_reconciliation", resp)
    ctx["reconciliation"] = get_success_data(resp)
    return ctx


def setup_closed_reconciliation(
    actual_cents: int = TEST_DEFAULTS["BUDGETED_CENTS"],
    close_clock: str = None,
    **kwargs,
) -> dict:
    """Full path through CLOSED (optionally after advancing the clock)."""
    ctx = setup_approved_reconciliation(actual_cents=actual_cents, **kwargs)
    if close_clock is not None:
        set_clock(close_clock)
    resp = api_client.close_reconciliation(ctx["reconciliation"]["id"], PM)
    if resp.status_code >= 400:
        setup_failed("close_reconciliation", resp)
    ctx["reconciliation"] = get_success_data(resp)
    return ctx


# ---------------------------------------------------------------------------
# Tier 4: child-entity builders on top of an existing lease
# ---------------------------------------------------------------------------

def create_critical_date_on(lease_id: str, **overrides) -> dict:
    resp = api_client.create_critical_date(
        lease_id, create_critical_date_payload(**overrides), PROP_MGR,
    )
    if resp.status_code >= 400:
        setup_failed("create_critical_date", resp)
    return get_success_data(resp)


def create_compliance_doc_on(lease_id: str, **overrides) -> dict:
    resp = api_client.create_compliance_doc(
        lease_id, create_compliance_doc_payload(**overrides), PROP_MGR,
    )
    if resp.status_code >= 400:
        setup_failed("create_compliance_doc", resp)
    return get_success_data(resp)


def review_compliance_doc(doc_id: str) -> dict:
    resp = api_client.start_compliance_doc_review(doc_id, PROP_MGR)
    if resp.status_code >= 400:
        setup_failed("start_compliance_doc_review", resp)
    return get_success_data(resp)


def accept_compliance_doc_on(doc_id: str) -> dict:
    resp = api_client.accept_compliance_doc(doc_id, PROP_MGR)
    if resp.status_code >= 400:
        setup_failed("accept_compliance_doc", resp)
    return get_success_data(resp)


def create_amendment_on(lease_id: str, **overrides) -> dict:
    resp = api_client.create_amendment(
        lease_id, create_amendment_payload(**overrides), PM,
    )
    if resp.status_code >= 400:
        setup_failed("create_amendment", resp)
    return get_success_data(resp)


def approve_amendment_on(amendment_id: str, expected_lease_version: int) -> dict:
    resp = api_client.approve_amendment(
        amendment_id, {"expected_lease_version": expected_lease_version}, PM,
    )
    if resp.status_code >= 400:
        setup_failed("approve_amendment", resp)
    return get_success_data(resp)


def apply_amendment_on(amendment_id: str) -> dict:
    resp = api_client.apply_amendment(amendment_id, PM)
    if resp.status_code >= 400:
        setup_failed("apply_amendment", resp)
    return get_success_data(resp)


def create_challenge_on(lease_id: str, reconciliation_id: str, **overrides) -> dict:
    resp = api_client.create_tenant_challenge(
        lease_id,
        create_tenant_challenge_payload(reconciliation_id=reconciliation_id, **overrides),
        PROP_MGR,
    )
    if resp.status_code >= 400:
        setup_failed("create_tenant_challenge", resp)
    return get_success_data(resp)


def create_audit_right_on(lease_id: str, reconciliation_id: str, **overrides) -> dict:
    resp = api_client.create_audit_right(
        lease_id,
        create_audit_right_payload(reconciliation_id=reconciliation_id, **overrides),
        PROP_MGR,
    )
    if resp.status_code >= 400:
        setup_failed("create_audit_right", resp)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 5: composite domain scenarios
# ---------------------------------------------------------------------------

def setup_lease_with_approved_recon_and_challenge(
    challenge_overrides: dict = None, **kwargs,
) -> dict:
    """APPROVED reconciliation plus one OPEN TenantChallenge against it."""
    ctx = setup_approved_reconciliation(**kwargs)
    challenge = create_challenge_on(
        ctx["lease"]["id"], ctx["reconciliation"]["id"], **(challenge_overrides or {}),
    )
    ctx["challenge"] = challenge
    return ctx
