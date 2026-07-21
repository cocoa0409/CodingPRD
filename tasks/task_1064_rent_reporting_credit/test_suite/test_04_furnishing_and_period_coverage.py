"""Furnishing tradelines: discrete month-coverage collisions, the enrollment-active
gate, and list/filter endpoints.

Covers discrete month-coverage collisions, the enrollment-active furnish gate,
and the list/filter endpoints.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId, TEST_USERS, make_tenant_headers, make_landlord_headers,
    create_rent_payment_payload,
    reset_clock_default, create_tenant, create_landlord, create_plan,
    activate_enrollment, create_verified_lease, record_payment, report_payment,
    current_lease_version, setup_reported_item,
)

ANALYST = TEST_USERS["analyst_headers"]


# --------------------------------------------------------------------------
# Difficulty: resource_temporal_overlap / reported-month discrete coverage
# --------------------------------------------------------------------------
def test_second_report_same_lease_month_rejected(api):
    """PRD §3.5: "the same lease-and-month must not already be covered by a
    non-retracted tradeline, otherwise `ERR_PERIOD_ALREADY_COVERED`".

    Design: Difficulty/resource_temporal_overlap/reported_month_discrete_coverage_collision_rejected
    """
    reset_clock_default(api)
    plan = create_plan(api)
    tenant = create_tenant(api, full_name="Mo Month", email="mo@x.com")
    landlord = create_landlord(api)
    activate_enrollment(api, tenant["id"], plan["id"])
    lease = create_verified_lease(api, tenant["id"], landlord["id"], property_address="22 Dup St")
    pay1 = record_payment(api, landlord["id"], lease["id"], period_month="2026-06",
                          due_date="2026-06-05T00:00:00Z", paid_date="2026-06-05T00:00:00Z")
    pay2 = record_payment(api, landlord["id"], lease["id"], period_month="2026-06",
                          due_date="2026-06-05T00:00:00Z", paid_date="2026-06-06T00:00:00Z")
    report_payment(api, pay1["id"])  # covers 2026-06
    resp = api.report_rent_payment(ANALYST, pay2["id"])
    validate_error(resp, ApiErrorId.ERR_PERIOD_ALREADY_COVERED.value, 409)


def test_collision_leaves_second_payment_recorded(api):
    """PRD §3.5: "the same lease-and-month must not already be covered by a
    non-retracted tradeline, otherwise `ERR_PERIOD_ALREADY_COVERED`".
    PRD §3.5: "As the tradeline is created, the payment moves from `RECORDED` to
    `REPORTED`, and the tenant's `reported_on_time_rate_pct` and
    `effective_reported_items` are recomputed." — a rejected furnish leaves the
    second payment still `RECORDED`.

    Design: Difficulty/resource_temporal_overlap/reported_month_discrete_coverage_collision_rejected
    """
    reset_clock_default(api)
    plan = create_plan(api)
    tenant = create_tenant(api, full_name="Moe Month", email="moe@x.com")
    landlord = create_landlord(api)
    activate_enrollment(api, tenant["id"], plan["id"])
    lease = create_verified_lease(api, tenant["id"], landlord["id"], property_address="23 Dup St")
    lh = make_landlord_headers(landlord["id"])
    pay1 = record_payment(api, landlord["id"], lease["id"], period_month="2026-06",
                          due_date="2026-06-05T00:00:00Z", paid_date="2026-06-05T00:00:00Z")
    pay2 = record_payment(api, landlord["id"], lease["id"], period_month="2026-06",
                          due_date="2026-06-05T00:00:00Z", paid_date="2026-06-06T00:00:00Z")
    report_payment(api, pay1["id"])
    validate_error(api.report_rent_payment(ANALYST, pay2["id"]),
                   ApiErrorId.ERR_PERIOD_ALREADY_COVERED.value, 409)
    after = validate_success(api.get_rent_payment(lh, pay2["id"]), 200)
    assert after["status"] == "RECORDED"


# --------------------------------------------------------------------------
# Corner: report requires enrollment ACTIVE
# --------------------------------------------------------------------------
def test_report_requires_enrollment_active(api):
    """PRD §3.5: "and the tenant's enrolment must be `ACTIVE`, otherwise
    `ERR_ENROLLMENT_INACTIVE`. Only when all four hold does furnishing proceed."

    Design: Corner/validations/report_requires_enrollment_active_returns_error
    """
    reset_clock_default(api)
    plan = create_plan(api)
    tenant = create_tenant(api, full_name="Ina Inactive", email="ina@x.com")
    landlord = create_landlord(api)
    th = make_tenant_headers(tenant["id"])
    # enrollment created but NOT paid -> stays PENDING_PAYMENT
    get_success_data(api.create_enrollment(th, {"tenant_id": tenant["id"], "plan_id": plan["id"]}))
    lease = create_verified_lease(api, tenant["id"], landlord["id"], property_address="43 Inact Rd")
    payment = record_payment(api, landlord["id"], lease["id"], period_month="2026-06",
                             due_date="2026-06-05T00:00:00Z", paid_date="2026-06-05T00:00:00Z")
    resp = api.report_rent_payment(ANALYST, payment["id"])
    validate_error(resp, ApiErrorId.ERR_ENROLLMENT_INACTIVE.value, 402)


# --------------------------------------------------------------------------
# Corner: reported-items filter by tenant
# --------------------------------------------------------------------------
def test_reported_items_filter_by_tenant_returns_list(api):
    """PRD §3.5: "Reported items can be listed and filtered by `rent_payment_id`,
    `tenant_id`, `lease_id`, `supersedes_item_id`, or `status`."

    Design: Corner/endpoints/reported_items_filter_by_tenant_returns_list
    """
    ctx = setup_reported_item(api, property_address="52 List Ln")
    th = make_tenant_headers(ctx["tenant"]["id"])
    resp = api.list_reported_items(th, params={"tenant_id": ctx["tenant"]["id"]})
    data, _meta = validate_paginated(resp)
    assert len(data) >= 1
    assert data[0]["tenant_id"] == ctx["tenant"]["id"]


# --------------------------------------------------------------------------
# Corner: leases list envelope + pagination
# --------------------------------------------------------------------------
def test_leases_list_returns_array_with_pagination_meta(api):
    """PRD §2.3: "Every list response reports the pagination state inside the
    `meta` object of the envelope through four fields: `limit`, `offset`,
    `total_count`, and `has_more`."

    Design: Corner/endpoints/leases_list_returns_array_envelope_with_pagination
    """
    reset_clock_default(api)
    tenant = create_tenant(api, full_name="Page Tenant", email="page@x.com")
    landlord = create_landlord(api)
    th = make_tenant_headers(tenant["id"])
    get_success_data(api.create_lease(th, {
        "tenant_id": tenant["id"], "landlord_id": landlord["id"],
        "property_address": "53 Page Way", "rent_amount_cents": 120000,
        "monthly_due_day": 5, "lease_start": "2026-01-01T00:00:00Z",
        "lease_end": "2027-01-01T00:00:00Z"}))
    resp = api.list_leases(th, params={"tenant_id": tenant["id"]})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 1
    assert meta["has_more"] is False
    assert len(data) == 1
