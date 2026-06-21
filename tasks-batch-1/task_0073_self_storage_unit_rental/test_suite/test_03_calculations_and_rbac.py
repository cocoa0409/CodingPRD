"""Tier lookups, payment allocation, ownership isolation, OCC, derived reconciliation.

Queue B (Corner) translations: calculations, rbac, cross_cutting_complexity_layers.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId,
    TEST_USERS, make_tenant_headers,
    setup_activated, setup_delinquent_past_90,
    create_facility, create_unit, create_tenant, create_lease, set_clock, pay,
    api_client,
)

FM = TEST_USERS["facility_manager_headers"]
LIEN = TEST_USERS["lien_administrator_headers"]


def test_insurance_premium_by_tier_lookup(api):
    """PRD §3.7: "The `monthly_premium_cents` is 1000 for `BASIC`, 1500 for `STANDARD`,
    and 2500 for `PREMIUM`. The `coverage_limit_cents` is 200000 for `BASIC`, 500000 for
    `STANDARD`, and 1500000 for `PREMIUM`."

    Design: Corner/calculations/insurance_premium_by_tier_lookup_correct
    """
    fac = create_facility(name="FC1", state_code="CA", climate_premium_pct=0.20)
    unit = create_unit(fac["id"], unit_number="Z-11", monthly_rate_cents=10000)
    ten = create_tenant(email="fc1@x.com", full_name="F C1", state_code="CA")
    set_clock("2026-04-01T00:00:00Z")
    lease = create_lease(unit["id"], ten["id"])
    resp = api.create_insurance_policy(
        {"lease_id": lease["id"], "coverage_tier": "PREMIUM",
         "coverage_start": "2026-04-01T00:00:00Z"}, FM)
    data = validate_success(resp, 201)
    assert data["monthly_premium_cents"] == 2500
    assert data["coverage_limit_cents"] == 1500000
    assert data["status"] == "ACTIVE"


def test_payment_waterfall_oldest_due_first(api):
    """PRD §3.6: "The lease's invoices in `OPEN`, `PARTIAL`, or `OVERDUE` status are
    ordered by `due_date` ascending, with ties broken by `created_at` ascending — never
    by id. The payment amount is consumed across that ordered list: each invoice receives
    the smaller of the remaining payment and that invoice's own unpaid remainder."

    Design: Corner/calculations/payment_waterfall_oldest_due_first_allocation
    """
    # Climate lease @10000 -> Apr invoice (due 04-01) + May invoice (due 05-01). The
    # 05-01 billing cycle assesses a 2000 late fee on the Apr invoice (30 days past the
    # 5-day grace), so Apr now totals 14000 while May is the full-month 12000.
    ctx = setup_activated(unit_overrides={"climate_controlled": True,
                                          "monthly_rate_cents": 10000})
    set_clock("2026-05-01T00:00:00Z")
    validate_success(api.run_billing_cycle(ctx["facility"]["id"], FM), 200)
    invoices, _ = validate_paginated(
        api.list_invoices(FM, params={"lease_id": ctx["lease"]["id"]}))
    by_due = sorted(invoices, key=lambda i: i["due_date"])
    apr, may = by_due[0], by_due[1]
    apr_total = apr["total_amount_cents"]
    # Pay exactly the OLDER invoice's full remainder; oldest-first allocation must fully
    # clear Apr and leave the newer May untouched.
    payment = pay(ctx["lease"]["id"], apr_total, ctx["tenant"]["id"])
    assert payment["overpay_credit_cents"] == 0
    invoices, _ = validate_paginated(
        api.list_invoices(FM, params={"lease_id": ctx["lease"]["id"]}))
    by_due = sorted(invoices, key=lambda i: i["due_date"])
    apr, may = by_due[0], by_due[1]
    assert apr["status"] == "PAID", f"oldest (Apr) must be PAID, got {apr['status']}"
    assert may["status"] == "OPEN", f"newer (May) untouched, got {may['status']}"


def test_tenant_cannot_open_auction(api):
    """PRD §2.1: "When the headers are well-formed but the role is not permitted to
    perform the requested operation ... the request is rejected with `ERR_FORBIDDEN`
    (HTTP 403)."
    PRD §4: "POST `/auction-proceedings` ... Open a lien/auction proceeding ...
    LienAdministrator."

    Design: Corner/rbac/tenant_cannot_open_auction
    """
    ctx = setup_delinquent_past_90(climate=True, rate=10000,
                                   past_due_date="2026-07-02T00:00:00Z")
    resp = api.create_auction_proceeding(
        {"lease_id": ctx["lease"]["id"], "expected_lease_version": ctx["lease_version"]},
        make_tenant_headers(ctx["tenant"]["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


def test_tenant_cannot_pay_other_tenants_lease(api):
    """PRD §2.1: "A tenant may read and act only on leases whose `tenant_id` equals their
    own `id` ... A tenant acting on another tenant's lease is rejected with
    `ERR_FORBIDDEN`."

    Design: Corner/rbac/tenant_cannot_pay_other_tenants_lease
    """
    fac = create_facility(name="FR2", state_code="CA", climate_premium_pct=0.20)
    unit = create_unit(fac["id"], unit_number="Q-7", climate_controlled=True,
                       monthly_rate_cents=10000)
    ten_a = create_tenant(email="fr2a@x.com", full_name="F R2 A", state_code="CA")
    ten_b = create_tenant(email="fr2b@x.com", full_name="F R2 B", state_code="CA")
    set_clock("2026-04-01T00:00:00Z")
    lease = create_lease(unit["id"], ten_a["id"])
    validate_success(api.activate_lease(lease["id"], FM), 200)
    # Tenant B pays Tenant A's lease.
    resp = api.create_payment(
        {"lease_id": lease["id"], "amount_cents": 12000}, make_tenant_headers(ten_b["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


def test_auction_open_with_stale_lease_version_rejected(api):
    """PRD §2.7: "When a request to open an auction proceeding arrives,
    `expected_lease_version` must equal the target lease's current `version`. If another
    writer has advanced the lease's version since the client last read it ... the request
    is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_auction_open_stale_lease_version_conflict
    """
    ctx = setup_delinquent_past_90(climate=True, rate=10000,
                                   past_due_date="2026-07-02T00:00:00Z")
    current = validate_success(api.get_lease(ctx["lease"]["id"], LIEN), 200)
    stale_version = current["version"] - 1
    resp = api.create_auction_proceeding(
        {"lease_id": ctx["lease"]["id"], "expected_lease_version": stale_version}, LIEN)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)


def test_occupied_unit_count_reconciles_after_close(api):
    """PRD §3.1: "it is always the number of units belonging to the facility whose
    `status` equals `OCCUPIED`, and it is recomputed from scratch on every unit status
    change — activation, transfer completion, auction sale, and lease close."

    Design: Corner/cross_cutting_complexity_layers/derived_occupied_unit_count_reconciles_after_close
    """
    ctx = setup_activated(unit_overrides={"climate_controlled": True,
                                          "monthly_rate_cents": 10000})
    pay(ctx["lease"]["id"], 12000, ctx["tenant"]["id"])
    fac_active = validate_success(api.get_facility(ctx["facility"]["id"], FM), 200)
    assert fac_active["occupied_unit_count"] == 1
    validate_success(api.close_lease(ctx["lease"]["id"], FM), 200)
    fac_closed = validate_success(api.get_facility(ctx["facility"]["id"], FM), 200)
    assert fac_closed["occupied_unit_count"] == 0
