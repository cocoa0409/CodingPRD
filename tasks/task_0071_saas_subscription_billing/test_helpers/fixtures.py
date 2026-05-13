"""Composite setup helpers for the SaaS Subscription Billing test suite.

Most interesting test claims require the system to be in a specific
state reached through 5–15 API calls (jurisdiction → package → tenant →
subscription → convert → usage → invoice → payment → dunning runs). These
helpers encapsulate those preambles so test bodies stay focused on
assertions.

Identity threading (PRD §2.1):
- TenantAdmin is ENTITY-BACKED: 'When X-User-Role is TenantAdmin...
  X-User-ID is the id of the acting Tenant.' Every ownership-gated call
  by a TenantAdmin principal MUST use make_tenant_admin_headers(
  tenant['id']), never a shared fallback string.
- PlatformAdmin and BillingOperator are OPAQUE.

Setup helpers use get_success_data (lenient), so a broken precondition
surfaces as a clear setup error rather than a confusing assertion
failure inside the test body.
"""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_paginated,
)

from .api_client import api_client
from .factories import (
    archive_run_payload,
    clock_advance_payload,
    convert_subscription_payload,
    create_credit_note_payload,
    create_jurisdiction_payload,
    create_package_payload,
    create_payment_payload,
    create_subscription_payload,
    create_tenant_payload,
    downgrade_subscription_payload,
    ingest_usage_payload,
    make_addon,
    make_tiered_bracket,
    unique_external_reference,
    unique_idempotency_key,
    unique_jurisdiction_code,
    unique_package_code,
    update_invoice_payload,
    update_tenant_payload,
    upgrade_subscription_payload,
)
from .test_users import (
    TEST_USERS,
    make_tenant_admin_headers,
)


# ===========================================================================
# Shared role-header constants (opaque roles, safe as module constants)
# ===========================================================================
PA = TEST_USERS["platform_admin_headers"]
PA_ALT = TEST_USERS["platform_admin_headers_alt"]
BO = TEST_USERS["billing_operator_headers"]
BO_ALT = TEST_USERS["billing_operator_headers_alt"]


# ===========================================================================
# ISO 8601 helpers (PRD §2.4: ISO 8601 UTC with three fractional digits)
# ===========================================================================
def iso_z(dt: datetime) -> str:
    """ISO 8601 UTC with millisecond precision, Z-suffixed."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def iso_at(year: int, month: int, day: int,
           hour: int = 0, minute: int = 0, second: int = 0) -> str:
    return iso_z(datetime(year, month, day, hour, minute, second,
                          tzinfo=timezone.utc))


# ===========================================================================
# Test-harness drivers (PRD §3.14)
# ===========================================================================
def advance_clock(seconds: int,
                  headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """PRD §3.14: 'A clock-advance capability accepts a seconds delta in
    its body and advances the logical clock by that delta.'"""
    return get_success_data(api_client.clock_advance(
        clock_advance_payload(seconds=seconds), headers or PA,
    ))


def run_dunning(headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """PRD §3.14: 'A dunning sweep capability runs the scan that advances
    payment_status tiers.'"""
    return get_success_data(api_client.dunning_run(headers or PA))


def run_archive(cutoff_iso: str,
                headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """PRD §3.14: 'An archive sweep capability accepts a cutoff_iso ISO
    8601 timestamp.'"""
    return get_success_data(api_client.archive_run(
        archive_run_payload(cutoff_iso=cutoff_iso), headers or PA,
    ))


# ===========================================================================
# Jurisdictions
# ===========================================================================
def create_jurisdiction(*, jurisdiction_code: Optional[str] = None,
                        tax_rate_bps: int = 0,
                        rounding_mode: str = "TOTAL") -> Dict[str, Any]:
    """PRD §3.13: 'A PlatformAdmin defines new jurisdictions.'"""
    return get_success_data(api_client.create_jurisdiction(
        create_jurisdiction_payload(
            jurisdiction_code=jurisdiction_code or unique_jurisdiction_code(),
            tax_rate_bps=tax_rate_bps,
            rounding_mode=rounding_mode,
        ),
        PA,
    ))


# ===========================================================================
# Packages
# ===========================================================================
def create_package(**overrides: Any) -> Dict[str, Any]:
    """PRD §3.1: 'a PlatformAdmin populates the catalog of available
    offerings.'"""
    return get_success_data(api_client.create_package(
        create_package_payload(**overrides), PA,
    ))


# ===========================================================================
# Tenants
# ===========================================================================
def create_tenant(*, jurisdiction_code: Optional[str] = None,
                  currency: str = "USD",
                  billing_entity_type: str = "INDEPENDENT",
                  parent_tenant_id: Optional[str] = None,
                  trial_expires_at: Optional[str] = None,
                  **overrides: Any) -> Dict[str, Any]:
    """PRD §3.2: 'A PlatformAdmin creates a new tenant.'

    The fixture ensures a Jurisdiction with the supplied code exists by
    auto-creating one if no code is supplied. Returns the persisted
    Tenant.
    """
    if jurisdiction_code is None:
        # Default jurisdiction with no tax, TOTAL rounding.
        j = create_jurisdiction()
        jurisdiction_code = j["jurisdiction_code"]
    kwargs: Dict[str, Any] = dict(
        currency=currency,
        jurisdiction_code=jurisdiction_code,
        billing_entity_type=billing_entity_type,
    )
    if parent_tenant_id is not None:
        kwargs["parent_tenant_id"] = parent_tenant_id
    if trial_expires_at is not None:
        kwargs["trial_expires_at"] = trial_expires_at
    kwargs.update(overrides)
    return get_success_data(api_client.create_tenant(
        create_tenant_payload(**kwargs), PA,
    ))


def get_tenant(tenant_id: str,
               headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api_client.get_tenant(
        tenant_id, headers or PA,
    ))


def patch_tenant(tenant_id: str,
                 headers: Optional[Dict[str, str]] = None,
                 **fields: Any) -> Dict[str, Any]:
    return get_success_data(api_client.update_tenant(
        tenant_id, update_tenant_payload(**fields),
        headers or PA,
    ))


# ===========================================================================
# Subscriptions
# ===========================================================================
def create_subscription(tenant: Dict[str, Any], *, package_code: str,
                        selected_addons: Optional[List[str]] = None,
                        ) -> Dict[str, Any]:
    """PRD §3.3: 'A subscription begins life when a TenantAdmin (or a
    PlatformAdmin) creates a new subscription on a tenant that is
    currently in TRIAL.' Uses the entity-backed TenantAdmin header for
    the tenant whose id is being acted on.
    """
    payload_kwargs: Dict[str, Any] = {"package_code": package_code}
    if selected_addons is not None:
        payload_kwargs["selected_addons"] = selected_addons
    return get_success_data(api_client.create_subscription(
        tenant["id"], create_subscription_payload(**payload_kwargs),
        make_tenant_admin_headers(tenant["id"]),
    ))


def convert_subscription(tenant: Dict[str, Any],
                         subscription: Dict[str, Any],
                         version: Optional[int] = None) -> Dict[str, Any]:
    """PRD §3.3: 'Trial conversion advances the subscription from TRIAL
    to ACTIVE.'"""
    payload_kwargs: Dict[str, Any] = {}
    if version is not None:
        payload_kwargs["version"] = version
    return get_success_data(api_client.convert_subscription(
        tenant["id"], subscription["id"],
        make_tenant_admin_headers(tenant["id"]),
        convert_subscription_payload(**payload_kwargs),
    ))


def upgrade_subscription(tenant: Dict[str, Any],
                         subscription: Dict[str, Any],
                         *, target_package_code: str,
                         version: Optional[int] = None) -> Dict[str, Any]:
    """PRD §3.4: 'Upgrading requires the subscription to be in ACTIVE...
    the target PackageVersion.base_price_cents to be strictly greater
    than the current package's base_price_cents.'"""
    payload_kwargs: Dict[str, Any] = {
        "target_package_code": target_package_code,
    }
    if version is not None:
        payload_kwargs["version"] = version
    return get_success_data(api_client.upgrade_subscription(
        tenant["id"], subscription["id"],
        upgrade_subscription_payload(**payload_kwargs),
        make_tenant_admin_headers(tenant["id"]),
    ))


def downgrade_subscription(tenant: Dict[str, Any],
                           subscription: Dict[str, Any],
                           *, target_package_code: str,
                           mode: str,
                           version: Optional[int] = None) -> Dict[str, Any]:
    """PRD §3.4: 'The downgrade endpoint additionally takes a mode query
    parameter whose value is either END_OF_CYCLE or IMMEDIATE_REFUND.'"""
    payload_kwargs: Dict[str, Any] = {
        "target_package_code": target_package_code,
        "mode": mode,
    }
    if version is not None:
        payload_kwargs["version"] = version
    return get_success_data(api_client.downgrade_subscription(
        tenant["id"], subscription["id"],
        downgrade_subscription_payload(**payload_kwargs),
        make_tenant_admin_headers(tenant["id"]),
    ))


def list_subscription_changes(tenant: Dict[str, Any],
                              subscription: Dict[str, Any],
                              limit: int = 100) -> List[Dict[str, Any]]:
    """PRD §4: 'GET /tenants/{tenant_id}/subscriptions/{id}/changes'."""
    resp = api_client.list_subscription_changes(
        tenant["id"], subscription["id"],
        make_tenant_admin_headers(tenant["id"]),
        params={"limit": limit, "offset": 0},
    )
    data, _ = validate_paginated(resp)
    return data


def get_subscription(tenant: Dict[str, Any],
                     subscription: Dict[str, Any]) -> Dict[str, Any]:
    return get_success_data(api_client.get_subscription(
        tenant["id"], subscription["id"],
        make_tenant_admin_headers(tenant["id"]),
    ))


# ===========================================================================
# Invoices
# ===========================================================================
def list_invoices(tenant: Dict[str, Any],
                  limit: int = 100,
                  invoice_status: Optional[str] = None,
                  ) -> List[Dict[str, Any]]:
    params: Dict[str, Any] = {"limit": limit, "offset": 0}
    if invoice_status is not None:
        params["invoice_status"] = invoice_status
    resp = api_client.list_invoices(
        tenant["id"], make_tenant_admin_headers(tenant["id"]),
        params=params,
    )
    data, _ = validate_paginated(resp)
    return data


def get_invoice(tenant: Dict[str, Any],
                invoice_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_invoice(
        tenant["id"], invoice_id,
        make_tenant_admin_headers(tenant["id"]),
    ))


def issue_invoice(tenant: Dict[str, Any], invoice_id: str,
                  version: Optional[int] = None) -> Dict[str, Any]:
    """PRD §3.9: 'Issuance is performed by a PlatformAdmin or
    BillingOperator explicitly.'"""
    payload: Dict[str, Any] = {}
    if version is not None:
        payload["version"] = version
    return get_success_data(api_client.issue_invoice(
        tenant["id"], invoice_id, BO, payload,
    ))


def patch_invoice(tenant: Dict[str, Any], invoice_id: str,
                  *, discount_cents: Optional[int] = None,
                  version: Optional[int] = None) -> Dict[str, Any]:
    """PRD §3.9: discount adjustment on DRAFT invoices."""
    payload_kwargs: Dict[str, Any] = {}
    if discount_cents is not None:
        payload_kwargs["discount_cents"] = discount_cents
    if version is not None:
        payload_kwargs["version"] = version
    return get_success_data(api_client.update_invoice(
        tenant["id"], invoice_id,
        update_invoice_payload(**payload_kwargs), BO,
    ))


def pay_invoice(tenant: Dict[str, Any], invoice_id: str,
                *, amount_cents: int,
                currency: str = "USD",
                external_reference: Optional[str] = None,
                ) -> Dict[str, Any]:
    """PRD §3.11: 'A payment posts cash against exactly one invoice.'

    Uses the TenantAdmin role with the tenant-owned X-User-ID so the
    ownership check in PRD §2.1 passes for this tenant's own invoice.
    """
    return get_success_data(api_client.create_payment(
        tenant["id"], invoice_id,
        create_payment_payload(
            amount_cents=amount_cents, currency=currency,
            external_reference=(
                external_reference or unique_external_reference()
            ),
        ),
        make_tenant_admin_headers(tenant["id"]),
    ))


# ===========================================================================
# Credit notes
# ===========================================================================
def issue_credit_note(tenant: Dict[str, Any], *,
                      origin: str = "MANUAL_ADJUSTMENT",
                      amount_cents: int = 1000,
                      applied_to_invoice_id: Optional[str] = None,
                      ) -> Dict[str, Any]:
    """PRD §3.11: 'A BillingOperator or PlatformAdmin may issue a credit
    note manually.'"""
    kwargs: Dict[str, Any] = {"origin": origin, "amount_cents": amount_cents}
    if applied_to_invoice_id is not None:
        kwargs["applied_to_invoice_id"] = applied_to_invoice_id
    return get_success_data(api_client.create_credit_note(
        tenant["id"], create_credit_note_payload(**kwargs), BO,
    ))


def list_credit_notes(tenant: Dict[str, Any]) -> List[Dict[str, Any]]:
    resp = api_client.list_credit_notes(
        tenant["id"], make_tenant_admin_headers(tenant["id"]),
        params={"limit": 100, "offset": 0},
    )
    data, _ = validate_paginated(resp)
    return data


# ===========================================================================
# Usage
# ===========================================================================
def ingest_usage(tenant: Dict[str, Any], subscription: Dict[str, Any],
                 *, metric: str = "API_CALL", quantity: int = 1,
                 event_timestamp: Optional[str] = None,
                 ingestion_mode: str = "REALTIME",
                 idempotency_key: Optional[str] = None,
                 ) -> Dict[str, Any]:
    """PRD §3.7: 'Each usage submission carries a caller-supplied
    idempotency_key...'"""
    payload_kwargs: Dict[str, Any] = {
        "metric": metric, "quantity": quantity,
        "ingestion_mode": ingestion_mode,
        "idempotency_key": idempotency_key or unique_idempotency_key(),
    }
    if event_timestamp is not None:
        payload_kwargs["event_timestamp"] = event_timestamp
    return get_success_data(api_client.ingest_usage(
        tenant["id"], subscription["id"],
        ingest_usage_payload(**payload_kwargs),
        make_tenant_admin_headers(tenant["id"]),
    ))


def list_usage(tenant: Dict[str, Any], subscription: Dict[str, Any],
               **params: Any) -> List[Dict[str, Any]]:
    p: Dict[str, Any] = {"limit": 100, "offset": 0}
    p.update(params)
    resp = api_client.list_usage(
        tenant["id"], subscription["id"],
        make_tenant_admin_headers(tenant["id"]),
        params=p,
    )
    data, _ = validate_paginated(resp)
    return data


# ===========================================================================
# Sync events / Audit logs
# ===========================================================================
def list_sync_events(tenant: Dict[str, Any],
                     **params: Any) -> List[Dict[str, Any]]:
    p: Dict[str, Any] = {"limit": 100, "offset": 0}
    p.update(params)
    resp = api_client.list_sync_events(tenant["id"], PA, params=p)
    data, _ = validate_paginated(resp)
    return data


def list_audit_logs(tenant: Dict[str, Any],
                    **params: Any) -> List[Dict[str, Any]]:
    p: Dict[str, Any] = {"limit": 100, "offset": 0}
    p.update(params)
    resp = api_client.list_audit_logs(
        tenant["id"], make_tenant_admin_headers(tenant["id"]),
        params=p,
    )
    data, _ = validate_paginated(resp)
    return data


# ===========================================================================
# Composite Tier 2: jurisdiction + tenant + package(s) ready to subscribe
# ===========================================================================
def setup_tenant_with_jurisdiction(
    *,
    tax_rate_bps: int = 0,
    rounding_mode: str = "TOTAL",
    currency: str = "USD",
    billing_entity_type: str = "INDEPENDENT",
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Create one Jurisdiction and a fresh Tenant attached to it."""
    j = create_jurisdiction(
        tax_rate_bps=tax_rate_bps, rounding_mode=rounding_mode,
    )
    t = create_tenant(
        jurisdiction_code=j["jurisdiction_code"], currency=currency,
        billing_entity_type=billing_entity_type,
    )
    return t, j


def setup_basic_monthly_package(
    *,
    base_price_cents: int = 3000,
    currency: str = "USD",
    pricing_model: str = "PREPAID",
    package_type: str = "TIERED",
    included_quotas: Optional[Dict[str, int]] = None,
    tiered_brackets: Optional[List[Dict[str, Any]]] = None,
    overage_rates: Optional[Dict[str, int]] = None,
    addons: Optional[List[Dict[str, Any]]] = None,
    effective_from: str = "2020-01-01T00:00:00.000Z",
    package_code: Optional[str] = None,
) -> Dict[str, Any]:
    return create_package(
        package_code=package_code,
        package_type=package_type,
        base_price_cents=base_price_cents,
        currency=currency,
        billing_cycle="MONTHLY",
        pricing_model=pricing_model,
        effective_from=effective_from,
        included_quotas=included_quotas or {},
        tiered_brackets=tiered_brackets or [],
        overage_rates=overage_rates or {},
        addons=addons or [],
    )


# ===========================================================================
# Composite Tier 3: full conversion to ACTIVE Subscription with a fresh
# prepaid Invoice (PRD §3.3)
# ===========================================================================
def setup_active_subscription(
    *,
    base_price_cents: int = 3000,
    currency: str = "USD",
    tax_rate_bps: int = 0,
    rounding_mode: str = "TOTAL",
    package_type: str = "TIERED",
    pricing_model: str = "PREPAID",
    included_quotas: Optional[Dict[str, int]] = None,
    tiered_brackets: Optional[List[Dict[str, Any]]] = None,
    overage_rates: Optional[Dict[str, int]] = None,
    addons: Optional[List[Dict[str, Any]]] = None,
    selected_addons: Optional[List[str]] = None,
    package_code: Optional[str] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Tenant + PackageVersion + Subscription transitioned to ACTIVE.

    Returns (tenant, package, subscription_active). The subscription has
    an associated freshly-issued PREPAID Invoice from trial conversion
    (PRD §3.3).
    """
    tenant, _j = setup_tenant_with_jurisdiction(
        tax_rate_bps=tax_rate_bps, rounding_mode=rounding_mode,
        currency=currency,
    )
    pkg = setup_basic_monthly_package(
        base_price_cents=base_price_cents,
        currency=currency,
        pricing_model=pricing_model,
        package_type=package_type,
        included_quotas=included_quotas,
        tiered_brackets=tiered_brackets,
        overage_rates=overage_rates,
        addons=addons,
        package_code=package_code,
    )
    sub = create_subscription(
        tenant, package_code=pkg["package_code"],
        selected_addons=selected_addons,
    )
    sub_active = convert_subscription(tenant, sub)
    return tenant, pkg, sub_active


# ===========================================================================
# Composite Tier 4: upgrade / downgrade pre-staged ladders.
# Difficulty design Rule 1 #1 and Rule 9 #1 require two packages
# (low base + high base) in the same currency.
# ===========================================================================
def setup_upgrade_ladder(
    *,
    low_base_cents: int = 3000,
    high_base_cents: int = 6000,
    currency: str = "USD",
    pkg_low_code: str = "BASIC",
    pkg_high_code: str = "PRO",
    tax_rate_bps: int = 0,
    rounding_mode: str = "TOTAL",
    pricing_model_low: str = "PREPAID",
    pricing_model_high: str = "PREPAID",
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Pre-stage two PackageVersions (low + high) plus an ACTIVE
    subscription on the LOW package. Returns (tenant, pkg_low, pkg_high,
    subscription_active)."""
    # Unique-ify codes so independent calls do not collide.
    low_code = f"{pkg_low_code}_{unique_package_code()[:10]}"
    high_code = f"{pkg_high_code}_{unique_package_code()[:10]}"
    tenant, _j = setup_tenant_with_jurisdiction(
        tax_rate_bps=tax_rate_bps, rounding_mode=rounding_mode,
        currency=currency,
    )
    pkg_low = setup_basic_monthly_package(
        package_code=low_code, currency=currency,
        base_price_cents=low_base_cents,
        pricing_model=pricing_model_low,
    )
    pkg_high = setup_basic_monthly_package(
        package_code=high_code, currency=currency,
        base_price_cents=high_base_cents,
        pricing_model=pricing_model_high,
    )
    sub = create_subscription(tenant, package_code=low_code)
    sub_active = convert_subscription(tenant, sub)
    return tenant, pkg_low, pkg_high, sub_active


# ===========================================================================
# Composite Tier 4: dunning ladder helpers (needs clock + dunning runs)
# ===========================================================================
def setup_unpaid_invoice_at_due_date(
    *,
    base_price_cents: int = 10_000,
    currency: str = "USD",
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Tenant + ACTIVE Subscription + ISSUED Invoice (the prepaid invoice
    from trial conversion). The invoice has total_cents == base_price_cents
    and is unpaid. Returns (tenant, subscription, invoice).
    """
    tenant, _pkg, sub = setup_active_subscription(
        base_price_cents=base_price_cents, currency=currency,
        package_type="TIERED", pricing_model="PREPAID",
    )
    invoices = list_invoices(tenant)
    # Pick the most recent ISSUED invoice for this subscription
    issued = [
        i for i in invoices
        if i.get("subscription_id") == sub["id"]
        and i.get("invoice_status") in ("ISSUED",)
    ]
    assert issued, (
        "Setup failed: expected at least one ISSUED invoice after "
        "trial conversion (PRD §3.3: 'issues a PREPAID Invoice when the "
        "resolved package's pricing_model is PREPAID or HYBRID.')"
    )
    issued.sort(key=lambda i: i["created_at"])
    return tenant, sub, issued[-1]


def setup_overdue_tier3_suspended(
    *,
    base_price_cents: int = 10_000,
    currency: str = "USD",
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Drive Tenant to SUSPENDED via dunning: clock past every tier,
    /_dunning/run, ending with Tenant.tenant_status=SUSPENDED,
    Subscription.payment_status=OVERDUE_TIER3, Invoice.invoice_status=
    OVERDUE.
    """
    tenant, sub, invoice = setup_unpaid_invoice_at_due_date(
        base_price_cents=base_price_cents, currency=currency,
    )
    # Advance the clock by a very large delta (e.g., 180 days) so each
    # call to /_dunning/run can promote tiers. PRD §3.12 enforces that
    # tier advancement requires elapsed days past due_at; one big jump
    # plus repeated sweeps is the deterministic way to reach TIER3.
    advance_clock(180 * 86400)
    # Run dunning until SUSPENDED is reached (sweep is idempotent and
    # advances at most one tier per scan per subscription on some
    # implementations — call enough times to ensure progression).
    for _ in range(6):
        run_dunning()
    return tenant, sub, invoice


def setup_overdue_due_to_dunning_run(
    *,
    base_price_cents: int = 10_000,
    currency: str = "USD",
    extra_seconds_past_due: int = 60 * 86400,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Advance the clock so the prepaid invoice is well past due_at, then
    run a single dunning sweep — useful for cascade-depth tests."""
    tenant, sub, invoice = setup_unpaid_invoice_at_due_date(
        base_price_cents=base_price_cents, currency=currency,
    )
    advance_clock(extra_seconds_past_due)
    run_dunning()
    return tenant, sub, invoice
