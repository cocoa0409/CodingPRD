"""Endpoint actions/reads, error fallbacks, RBAC, OCC happy path, and consistency
(breadth queue B — endpoints / errors / rbac / cross_cutting / consistency_model).
"""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated, get_success_data,
    setup_example_b_reconciliation, setup_example_b_posted, post_reconciliation,
    setup_lease_with_sales, setup_minimal_reconciliation,
    create_property, create_tenant, create_active_lease, create_pool, add_line_item,
    create_reconciliation, create_in_review_reconciliation, submit_reconciliation,
    get_reconciliation_version,
    make_property_manager_headers, make_accountant_headers, make_tenant_headers,
    build_user_headers,
    PM_HEADERS, ACCT_HEADERS,
)


# ─── endpoints section ──────────────────────────────────────────────────────

def test_payment_posts_negative_ledger_entry(api):
    """PRD §3.9: "A tenant payment is recorded by a PropertyManager or Accountant as
    an amount_cents; it posts a PAYMENT ledger entry of minus that amount,
    recomputes outstanding_balance_cents, and advances the lease's version."

    Design: Corner/endpoints/payment_endpoint_posts_negative_ledger
    """
    prop = create_property(total_rentable_sqft=10000)
    tenant = create_tenant()
    lease = create_active_lease(prop["id"], tenant["id"], leased_sqft=1000,
                                base_rent_cents_annual=10000000)
    validate_success(api.create_payment(lease["id"], {"amount_cents": 1500000}, ACCT_HEADERS), 201)
    after = validate_success(api.get_lease(lease["id"], PM_HEADERS), 200)
    assert after["outstanding_balance_cents"] == 8500000


def test_preview_matches_post_without_mutating_status(api):
    """PRD §3.7: "A read-only preview computes and returns the same four figures
    without posting, as a dry run for the property manager or accountant."

    Design: Corner/endpoints/preview_computed_read_matches_post
    """
    # DRAFT reconciliation for the Example-B config (true_up +70000).
    prop = create_property(total_rentable_sqft=10000, gross_up_occupancy_pct=0.95)
    anc = create_tenant("Anc", "anc@x.com")
    sub = create_tenant("Sub", "sub@x.com")
    create_active_lease(prop["id"], anc["id"], leased_sqft=7000, base_rent_cents_annual=0)
    sub_lease = create_active_lease(prop["id"], sub["id"], leased_sqft=2500,
                                    base_rent_cents_annual=0, estimated_cam_cents_monthly=15000)
    pool = create_pool(prop["id"], pool_year=2025,
                       pro_rata_denominator="TOTAL_RENTABLE", admin_fee_pct=0)
    add_line_item(pool["id"], "UTILITIES", 800000, "RECOVERABLE", is_variable=True)
    add_line_item(pool["id"], "INSURANCE", 200000, "RECOVERABLE", is_variable=False)
    recon = create_reconciliation(sub_lease["id"], pool["id"], 2025)
    preview = validate_success(api.preview_reconciliation(recon["id"], ACCT_HEADERS), 200)
    assert preview["reconciled_cam_cents"] == 250000
    assert preview["true_up_cents"] == 70000
    assert preview["status"] == "DRAFT"


def test_ledger_reverse_reachability_after_activation(api):
    """PRD §3.3: "a BASE_RENT ledger entry of plus the lease's base_rent_cents_annual
    is posted, refreshing outstanding_balance_cents."
    PRD §3.9: "The ledger is listable per lease in chronological order — created_at
    ascending"

    Design: Corner/endpoints/ledger_reverse_reachability_ordered
    """
    prop = create_property(total_rentable_sqft=10000)
    tenant = create_tenant()
    lease = create_active_lease(prop["id"], tenant["id"], leased_sqft=1000,
                                base_rent_cents_annual=10000000)
    data, meta = validate_paginated(api.list_ledger(lease["id"], PM_HEADERS))
    assert len(data) == 1
    assert data[0]["amount_cents"] == 10000000


def test_recon_ledger_entries_reverse_reachability(api):
    """PRD §3.9: "the entries sourced by a particular reconciliation are separately
    listable."
    PRD §3.7: "a CAM_TRUEUP ledger entry of the signed true_up_cents is posted with
    its source_reconciliation_id set to this reconciliation's id"

    Design: Corner/endpoints/recon_ledger_entries_reverse_reachability
    """
    ctx = setup_example_b_reconciliation()
    recon_id = ctx["recon"]["id"]
    post_reconciliation(recon_id, ctx["recon_version"])
    data, meta = validate_paginated(
        api.list_reconciliation_ledger_entries(recon_id, ACCT_HEADERS))
    assert len(data) == 1
    assert data[0]["amount_cents"] == 70000
    assert data[0]["entry_type"] == "CAM_TRUEUP"


def test_sales_reports_filtered_list(api):
    """PRD §3.5: "Reports are listable and individually retrievable, optionally
    filtered by lease_id and period_year."

    Design: Corner/endpoints/sales_reports_filtered_list
    """
    prop, tenant, lease, sr = setup_lease_with_sales(
        gross_sales_cents=100000, period_year=2025)
    data, meta = validate_paginated(
        api.list_sales_reports(PM_HEADERS, params={"lease_id": lease["id"]}))
    assert len(data) == 1


# ─── errors section ─────────────────────────────────────────────────────────

def test_percentage_rent_run_without_sales_report(api):
    """PRD §3.5: "The system locates the latest SalesReport for that lease and year"
    PRD §2.9: "ERR_VALIDATION (HTTP 422) is the generic fallback for a business-rule
    violation that no more specific error covers."

    Design: Corner/errors/pct_rent_run_without_sales_report_validation
    """
    prop = create_property(total_rentable_sqft=100000)
    tenant = create_tenant()
    lease = create_active_lease(prop["id"], tenant["id"], leased_sqft=1000,
                                base_rent_cents_annual=0,
                                pct_rent_rate=0.06, pct_rent_breakpoint_cents=3000000)
    res = api.run_percentage_rent(lease["id"], {"period_year": 2025}, PM_HEADERS)
    validate_error(res, "ERR_VALIDATION", expected_status=422)


def test_stale_version_on_post_after_return(api):
    """PRD §2.7: "The server compares it to the reconciliation's current version; if
    they do not match, the post is rejected with ERR_STALE_VERSION (HTTP 412)."
    PRD §2.7: "A post that carries the pre-cycle version is operating on a stale view
    of the reconciliation's contents ... so it is rejected"

    Design: Corner/errors/stale_version_on_post_after_return
    """
    prop = create_property(total_rentable_sqft=10000)
    tenant = create_tenant()
    lease = create_active_lease(prop["id"], tenant["id"], leased_sqft=1000,
                                base_rent_cents_annual=0, estimated_cam_cents_monthly=0)
    pool = create_pool(prop["id"], pool_year=2025, admin_fee_pct=0)
    add_line_item(pool["id"], "UTILITIES", 500000, "RECOVERABLE", is_variable=False)
    recon = create_reconciliation(lease["id"], pool["id"], 2025)
    pre_return_version = recon["version"]  # version 1
    submit_reconciliation(recon["id"], "pm-001")
    get_success_data(api.return_reconciliation(recon["id"], make_accountant_headers("acct-001")))
    submit_reconciliation(recon["id"], "pm-001")  # version now advanced
    res = api.post_reconciliation(
        recon["id"], {"expected_reconciliation_version": pre_return_version},
        make_accountant_headers("acct-001"))
    validate_error(res, "ERR_STALE_VERSION", expected_status=412)
    after = validate_success(api.get_reconciliation(recon["id"], ACCT_HEADERS), 200)
    assert after["status"] == "IN_REVIEW"


# ─── rbac section ───────────────────────────────────────────────────────────

def test_property_manager_cannot_post_reconciliation(api):
    """PRD §2.1: "When the headers are valid but the role is not permitted to invoke
    the requested operation, the request is rejected with ERR_UNAUTHORIZED."
    PRD §4: "POST /reconciliations/{id}/post ... Accountant"

    Design: Corner/rbac/property_manager_cannot_post_reconciliation
    """
    ctx = setup_minimal_reconciliation(recoverable_cents=500000)
    recon = ctx["recon"]
    submit_reconciliation(recon["id"], "pm-001")
    version = get_reconciliation_version(recon["id"])
    res = api.post_reconciliation(
        recon["id"], {"expected_reconciliation_version": version},
        make_property_manager_headers("pm-001"))
    validate_error(res, "ERR_UNAUTHORIZED", expected_status=403)
    after = validate_success(api.get_reconciliation(recon["id"], ACCT_HEADERS), 200)
    assert after["status"] == "IN_REVIEW"


def test_tenant_disputes_other_tenants_recon_denied(api):
    """PRD §2.1: "A tenant acting on a lease it does not own is rejected with
    ERR_NOT_LEASE_OWNER."
    PRD §3.8: "Disputing is exclusive to the Tenant, who must own the referenced
    lease (its tenant_id equal to the caller's X-User-ID, else ERR_NOT_LEASE_OWNER)"

    Design: Corner/rbac/tenant_disputes_other_tenants_recon_denied
    """
    prop = create_property(total_rentable_sqft=10000, gross_up_occupancy_pct=0.95)
    ten_a = create_tenant("TenantA", "ta@x.com")
    ten_b = create_tenant("TenantB", "tb@x.com")
    lease_b = create_active_lease(prop["id"], ten_b["id"], leased_sqft=7000,
                                  base_rent_cents_annual=0, estimated_cam_cents_monthly=0)
    pool = create_pool(prop["id"], pool_year=2025,
                       pro_rata_denominator="TOTAL_RENTABLE", admin_fee_pct=0)
    add_line_item(pool["id"], "UTILITIES", 500000, "RECOVERABLE", is_variable=False)
    recon = create_in_review_reconciliation(lease_b["id"], pool["id"], 2025)
    post_reconciliation(recon["id"], recon["version"], "acct-001")
    # Tenant A disputes tenant B's posted reconciliation.
    res = api.dispute_reconciliation(recon["id"], make_tenant_headers(ten_a["id"]))
    validate_error(res, "ERR_NOT_LEASE_OWNER", expected_status=403)
    after = validate_success(api.get_reconciliation(recon["id"], ACCT_HEADERS), 200)
    assert after["status"] == "POSTED"


def test_missing_auth_headers_unauthenticated(api):
    """PRD §2.1: "If either header is missing, or X-User-Role is not one of these
    three known roles, the request is rejected with ERR_UNAUTHENTICATED."

    Design: Corner/rbac/missing_auth_headers_unauthenticated
    """
    prop = create_property(total_rentable_sqft=10000)
    res = api.get_property(prop["id"], build_user_headers("ghost-1", "Ghost"))
    validate_error(res, "ERR_UNAUTHENTICATED", expected_status=401)


# ─── cross_cutting_complexity_layers section ────────────────────────────────

def test_occ_correct_version_post_succeeds(api):
    """PRD §2.7: "The request to post an IN_REVIEW reconciliation must carry
    expected_reconciliation_version, a non-optional field, whose value is the
    version of the target Reconciliation that the client last observed. The server
    compares it to the reconciliation's current version; if they do not match, the
    post is rejected with ERR_STALE_VERSION (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_correct_version_post_succeeds
    """
    ctx = setup_minimal_reconciliation(recoverable_cents=500000)
    recon = ctx["recon"]
    submit_reconciliation(recon["id"], "pm-001")
    version = get_reconciliation_version(recon["id"])
    posted = post_reconciliation(recon["id"], version, "acct-001")
    assert posted["status"] == "POSTED"


# ─── consistency_model section ──────────────────────────────────────────────

def test_post_response_immediately_carries_trueup(api):
    """PRD §3.7: "When all guards pass, the post computes and snapshots four
    figures, then cascades."
    PRD §3.7: "The true-up, true_up_cents, is reconciled_cam_cents minus
    estimated_cam_billed_cents"

    Design: Corner/consistency_model/immediate_visibility_of_trueup_in_post_response
    """
    ctx = setup_example_b_reconciliation()
    posted = post_reconciliation(ctx["recon"]["id"], ctx["recon_version"])
    assert posted["true_up_cents"] == 70000
    assert posted["reconciled_cam_cents"] == 250000
