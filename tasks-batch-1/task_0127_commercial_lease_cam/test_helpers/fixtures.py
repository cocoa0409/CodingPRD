"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) internally so setup failures produce
clear "Setup step failed" errors rather than confusing assertion failures.

Identity threading: the Tenant role is entity_backed. After a fixture creates a
Tenant, any ownership-gated call (dispute, estoppel respond) uses
make_tenant_headers(tenant["id"]) — never the shared TEST_USERS constant.
The PropertyManager/Accountant submit/post flows pin distinct opaque ids so the
segregation-of-duties guard is satisfied on the happy path.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_property_payload, create_tenant_payload, create_expense_pool_payload,
    create_line_item_payload, create_lease_payload, create_sales_report_payload,
    create_ti_draw_payload, create_reconciliation_payload, create_estoppel_payload,
)
from .test_users import (
    TEST_USERS, make_tenant_headers, make_property_manager_headers,
    make_accountant_headers,
)

# Pinned distinct opaque ids for the segregation-of-duties happy path.
PM_ID = "pm-001"
ACCT_ID = "acct-001"
PM_HEADERS = make_property_manager_headers(PM_ID)
ACCT_HEADERS = make_accountant_headers(ACCT_ID)


# ─── Primitive creators ───────────────────────────────────────────────────

def create_property(total_rentable_sqft=10000, gross_up_occupancy_pct=None, name="Prop"):
    payload = create_property_payload(name=name, total_rentable_sqft=total_rentable_sqft)
    if gross_up_occupancy_pct is not None:
        payload["gross_up_occupancy_pct"] = gross_up_occupancy_pct
    return get_success_data(api_client.create_property(payload, PM_HEADERS))


def create_tenant(legal_name="Tenant Co", contact_email="t@x.com"):
    return get_success_data(api_client.create_tenant(
        create_tenant_payload(legal_name=legal_name, contact_email=contact_email),
        PM_HEADERS))


def create_lease(property_id, tenant_id, leased_sqft=1000, base_rent_cents_annual=0,
                 **lease_overrides):
    payload = create_lease_payload(
        property_id, tenant_id,
        leased_sqft=leased_sqft, base_rent_cents_annual=base_rent_cents_annual,
        **lease_overrides)
    return get_success_data(api_client.create_lease(payload, PM_HEADERS))


def create_active_lease(property_id, tenant_id, leased_sqft=1000,
                        base_rent_cents_annual=0, **lease_overrides):
    """Create a lease and activate it. Returns the activated lease."""
    lease = create_lease(property_id, tenant_id, leased_sqft=leased_sqft,
                         base_rent_cents_annual=base_rent_cents_annual, **lease_overrides)
    return get_success_data(api_client.activate_lease(lease["id"], PM_HEADERS))


def create_pool(property_id, pool_year=2025, pro_rata_denominator=None, admin_fee_pct=0):
    payload = create_expense_pool_payload(property_id, pool_year=pool_year,
                                          admin_fee_pct=admin_fee_pct)
    if pro_rata_denominator is not None:
        payload["pro_rata_denominator"] = pro_rata_denominator
    return get_success_data(api_client.create_expense_pool(payload, ACCT_HEADERS))


def add_line_item(pool_id, category, amount_cents, recoverability="RECOVERABLE",
                  is_variable=False):
    payload = create_line_item_payload(category=category, amount_cents=amount_cents,
                                       recoverability=recoverability, is_variable=is_variable)
    return get_success_data(api_client.add_line_item(pool_id, payload, ACCT_HEADERS))


# ─── Reconciliation lifecycle ──────────────────────────────────────────────

def create_reconciliation(lease_id, pool_id, recon_year=2025):
    return get_success_data(api_client.create_reconciliation(
        create_reconciliation_payload(lease_id, pool_id, recon_year), PM_HEADERS))


def submit_reconciliation(recon_id, submitter_id=PM_ID):
    return get_success_data(api_client.submit_reconciliation(
        recon_id, make_property_manager_headers(submitter_id)))


def post_reconciliation(recon_id, expected_version, poster_id=ACCT_ID):
    return get_success_data(api_client.post_reconciliation(
        recon_id, {"expected_reconciliation_version": expected_version},
        make_accountant_headers(poster_id)))


def get_reconciliation_version(recon_id):
    recon = get_success_data(api_client.get_reconciliation(recon_id, ACCT_HEADERS))
    return recon["version"]


def create_in_review_reconciliation(lease_id, pool_id, recon_year=2025, submitter_id=PM_ID):
    """Create + submit a reconciliation. Returns the IN_REVIEW reconciliation."""
    recon = create_reconciliation(lease_id, pool_id, recon_year)
    submit_reconciliation(recon["id"], submitter_id)
    return get_success_data(api_client.get_reconciliation(recon["id"], ACCT_HEADERS))


def create_posted_reconciliation(lease_id, pool_id, recon_year=2025,
                                 submitter_id=PM_ID, poster_id=ACCT_ID):
    """Create → submit → post. Returns the POSTED reconciliation."""
    recon = create_reconciliation(lease_id, pool_id, recon_year)
    submit_reconciliation(recon["id"], submitter_id)
    version = get_reconciliation_version(recon["id"])
    return post_reconciliation(recon["id"], version, poster_id)


# ─── Example-B configuration (true_up == +70000) ───────────────────────────
# Property total 10000, occupied 9500 (filler 7000 + subject 2500), gross-up
# factor 1.0; pool admin 0, TOTAL_RENTABLE; RECOVERABLE variable 800000 + fixed
# 200000 -> total_recoverable 1000000; subject lease share 0.25 -> reconciled
# 250000; estimated 12*15000 = 180000; true_up 70000.

def setup_example_b_reconciliation():
    """Build the canonical true_up=+70000 scenario through IN_REVIEW.

    Returns dict with keys: prop, anchor_tenant, subject_tenant, anchor_lease,
    subject_lease, pool, recon (IN_REVIEW), recon_version.
    """
    prop = create_property(total_rentable_sqft=10000, gross_up_occupancy_pct=0.95, name="Plaza")
    anchor_tenant = create_tenant("Anchor Co", "anchor@x.com")
    subject_tenant = create_tenant("Subject Co", "subject@x.com")
    anchor_lease = create_active_lease(prop["id"], anchor_tenant["id"],
                                       leased_sqft=7000, base_rent_cents_annual=0)
    subject_lease = create_active_lease(prop["id"], subject_tenant["id"],
                                        leased_sqft=2500, base_rent_cents_annual=0,
                                        estimated_cam_cents_monthly=15000)
    pool = create_pool(prop["id"], pool_year=2025,
                       pro_rata_denominator="TOTAL_RENTABLE", admin_fee_pct=0)
    add_line_item(pool["id"], "UTILITIES", 800000, "RECOVERABLE", is_variable=True)
    add_line_item(pool["id"], "INSURANCE", 200000, "RECOVERABLE", is_variable=False)
    recon = create_in_review_reconciliation(subject_lease["id"], pool["id"], 2025)
    return {
        "prop": prop,
        "anchor_tenant": anchor_tenant,
        "subject_tenant": subject_tenant,
        "anchor_lease": anchor_lease,
        "subject_lease": subject_lease,
        "pool": pool,
        "recon": recon,
        "recon_version": recon["version"],
    }


def setup_example_b_posted():
    """Example-B configuration driven all the way to POSTED.

    Returns the same dict as setup_example_b_reconciliation plus the posted recon
    under key 'posted_recon'.
    """
    ctx = setup_example_b_reconciliation()
    posted = post_reconciliation(ctx["recon"]["id"], ctx["recon_version"], ACCT_ID)
    ctx["posted_recon"] = posted
    return ctx


def setup_example_b_disputed():
    """Example-B configuration POSTED then tenant-disputed (VOID-eligible).

    The subject tenant disputes its own reconciliation via make_tenant_headers.
    Returns the dict with 'posted_recon' and the recon set to DISPUTED.
    """
    ctx = setup_example_b_posted()
    recon_id = ctx["recon"]["id"]
    tenant_id = ctx["subject_tenant"]["id"]
    get_success_data(api_client.dispute_reconciliation(
        recon_id, make_tenant_headers(tenant_id)))
    return ctx


# ─── TI-draw scenarios ──────────────────────────────────────────────────────

def setup_lease_with_ti_allowance(ti_allowance_cents=1000000, base_rent_cents_annual=0,
                                  activate=True):
    """Active (or DRAFT) lease with a TI allowance. Returns (prop, tenant, lease)."""
    prop = create_property(total_rentable_sqft=10000)
    tenant = create_tenant()
    if activate:
        lease = create_active_lease(prop["id"], tenant["id"], leased_sqft=1000,
                                    base_rent_cents_annual=base_rent_cents_annual,
                                    ti_allowance_cents=ti_allowance_cents)
    else:
        lease = create_lease(prop["id"], tenant["id"], leased_sqft=1000,
                             base_rent_cents_annual=base_rent_cents_annual,
                             ti_allowance_cents=ti_allowance_cents)
    return prop, tenant, lease


def request_ti_draw(lease_id, amount_cents):
    return get_success_data(api_client.create_ti_draw(
        create_ti_draw_payload(lease_id, amount_cents=amount_cents), PM_HEADERS))


def approve_ti_draw(draw_id):
    return get_success_data(api_client.approve_ti_draw(draw_id, ACCT_HEADERS))


# ─── Percentage-rent scenarios ──────────────────────────────────────────────

def setup_lease_with_sales(pct_rent_rate=0.06, pct_rent_breakpoint_cents=3000000,
                           gross_sales_cents=5000000, period_year=2025):
    """Active lease configured for percentage rent + one filed SalesReport.

    Returns (prop, tenant, lease, sales_report).
    """
    prop = create_property(total_rentable_sqft=100000)
    tenant = create_tenant()
    lease = create_active_lease(prop["id"], tenant["id"], leased_sqft=1000,
                                base_rent_cents_annual=0,
                                pct_rent_rate=pct_rent_rate,
                                pct_rent_breakpoint_cents=pct_rent_breakpoint_cents)
    sr = get_success_data(api_client.create_sales_report(
        create_sales_report_payload(lease["id"], period_year=period_year,
                                    gross_sales_cents=gross_sales_cents),
        PM_HEADERS))
    return prop, tenant, lease, sr


# ─── Estoppel scenarios ──────────────────────────────────────────────────────

def setup_issued_estoppel(asserted_balance_cents=0, base_rent_cents_annual=0,
                          asserted_base_rent_cents_annual=0):
    """Active lease + ISSUED estoppel. Returns (prop, tenant, lease, estoppel)."""
    prop = create_property(total_rentable_sqft=10000)
    tenant = create_tenant()
    lease = create_active_lease(prop["id"], tenant["id"], leased_sqft=1000,
                                base_rent_cents_annual=base_rent_cents_annual)
    est = get_success_data(api_client.create_estoppel(
        create_estoppel_payload(lease["id"],
                                asserted_balance_cents=asserted_balance_cents,
                                asserted_base_rent_cents_annual=asserted_base_rent_cents_annual),
        PM_HEADERS))
    return prop, tenant, lease, est


# ─── Single-lease minimal reconciliation (small recoverable pool) ──────────

def setup_minimal_reconciliation(recoverable_cents=500000, estimated_cam_cents_monthly=0,
                                 recon_year=2025, pool_year=2025):
    """One active lease + a pool with a single fixed RECOVERABLE item + a DRAFT
    reconciliation. Returns dict with prop, tenant, lease, pool, recon.

    Used by validation/RBAC corner cases that need a reconciliation but do not
    care about precise true-up figures.
    """
    prop = create_property(total_rentable_sqft=10000)
    tenant = create_tenant()
    lease = create_active_lease(prop["id"], tenant["id"], leased_sqft=1000,
                                base_rent_cents_annual=0,
                                estimated_cam_cents_monthly=estimated_cam_cents_monthly)
    pool = create_pool(prop["id"], pool_year=pool_year, admin_fee_pct=0)
    add_line_item(pool["id"], "UTILITIES", recoverable_cents, "RECOVERABLE",
                  is_variable=False)
    recon = create_reconciliation(lease["id"], pool["id"], recon_year)
    return {"prop": prop, "tenant": tenant, "lease": lease, "pool": pool, "recon": recon}
