"""Recording rent payments: on-time grace boundary, null-paid handling, and the
optimistic-concurrency guard on Lease.version.

Covers the on-time grace boundary, null-paid handling, the OCC guard on
Lease.version, and role gating of the furnish action.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS, make_tenant_headers, make_landlord_headers,
    create_rent_payment_payload,
    reset_clock_default, create_tenant, create_landlord,
    create_verified_lease, current_lease_version,
)

ANALYST = TEST_USERS["analyst_headers"]


# --------------------------------------------------------------------------
# Difficulty: boundary_precision_check / on_time inclusive at exactly GRACE_DAYS
# --------------------------------------------------------------------------
def test_on_time_true_at_exactly_grace_boundary_on_create(api):
    """PRD §3.4: "the payment is on time exactly when the paid date falls on or
    before the due date plus a five-day grace period, compared at whole-day
    granularity — a payment made on the fifth day after the due date is still on
    time".

    Design: Difficulty/boundary_precision_check/on_time_inclusive_at_exactly_grace_days
    """
    reset_clock_default(api)
    tenant = create_tenant(api, full_name="Gina Border", email="grace@x.com")
    landlord = create_landlord(api)
    th = make_tenant_headers(tenant["id"])
    lh = make_landlord_headers(landlord["id"])
    lease = get_success_data(api.create_lease(th, {
        "tenant_id": tenant["id"], "landlord_id": landlord["id"],
        "property_address": "6 Fir Blvd", "rent_amount_cents": 120000,
        "monthly_due_day": 5, "lease_start": "2026-01-01T00:00:00Z",
        "lease_end": "2027-01-01T00:00:00Z"}))
    payload = create_rent_payment_payload(
        lease["id"], lease["version"], period_month="2026-04",
        due_date="2026-04-05T00:00:00Z", paid_date="2026-04-10T00:00:00Z")
    data = validate_success(api.create_rent_payment(lh, payload), 201)
    assert data["on_time"] is True


def test_on_time_boundary_persists_on_fetch(api):
    """PRD §3.4: "a payment made on the fifth day after the due date is still on
    time, and only a payment later than that is late."

    Design: Difficulty/boundary_precision_check/on_time_inclusive_at_exactly_grace_days
    """
    reset_clock_default(api)
    tenant = create_tenant(api, full_name="Gil Border", email="gil@x.com")
    landlord = create_landlord(api)
    th = make_tenant_headers(tenant["id"])
    lh = make_landlord_headers(landlord["id"])
    lease = get_success_data(api.create_lease(th, {
        "tenant_id": tenant["id"], "landlord_id": landlord["id"],
        "property_address": "7 Fir Blvd", "rent_amount_cents": 120000,
        "monthly_due_day": 5, "lease_start": "2026-01-01T00:00:00Z",
        "lease_end": "2027-01-01T00:00:00Z"}))
    payload = create_rent_payment_payload(
        lease["id"], lease["version"], period_month="2026-04",
        due_date="2026-04-05T00:00:00Z", paid_date="2026-04-10T00:00:00Z")
    created = validate_success(api.create_rent_payment(lh, payload), 201)
    fetched = validate_success(api.get_rent_payment(lh, created["id"]), 200)
    assert fetched["on_time"] is True


# --------------------------------------------------------------------------
# Corner: on_time false when paid_date null
# --------------------------------------------------------------------------
def test_on_time_false_when_paid_date_null(api):
    """PRD §3.4: "If no `paid_date` was supplied, the payment is not on time."

    Design: Corner/calculations/on_time_false_when_paid_date_null
    """
    reset_clock_default(api)
    tenant = create_tenant(api, full_name="Nell Null", email="nell@x.com")
    landlord = create_landlord(api)
    th = make_tenant_headers(tenant["id"])
    lh = make_landlord_headers(landlord["id"])
    lease = get_success_data(api.create_lease(th, {
        "tenant_id": tenant["id"], "landlord_id": landlord["id"],
        "property_address": "36 Null Dr", "rent_amount_cents": 120000,
        "monthly_due_day": 5, "lease_start": "2026-01-01T00:00:00Z",
        "lease_end": "2027-01-01T00:00:00Z"}))
    # omit paid_date entirely
    resp = api.create_rent_payment(lh, {
        "lease_id": lease["id"], "period_month": "2026-04",
        "due_date": "2026-04-05T00:00:00Z", "amount_paid_cents": 0,
        "expected_lease_version": lease["version"]})
    data = validate_success(resp, 201)
    assert data["on_time"] is False


# --------------------------------------------------------------------------
# Corner: optimistic concurrency on Lease.version
# --------------------------------------------------------------------------
def test_stale_lease_version_on_payment_rejected(api):
    """PRD §2.6: "When that value does not equal the lease's current `version`,
    the write is rejected with `ERR_STALE_VERSION` (HTTP 412), and no payment is
    created. A successful recording itself advances the lease's `version` by one".

    Design: Corner/cross_cutting_complexity_layers/occ_stale_lease_version_on_payment_rejected
    """
    reset_clock_default(api)
    tenant = create_tenant(api, full_name="Occ Tenant", email="occ@x.com")
    landlord = create_landlord(api)
    lease = create_verified_lease(api, tenant["id"], landlord["id"], property_address="60 OCC Rd")
    stale_version = lease["version"]
    lh = make_landlord_headers(landlord["id"])
    # first payment consumes the captured version and advances Lease.version
    validate_success(api.create_rent_payment(lh, create_rent_payment_payload(
        lease["id"], stale_version, period_month="2026-05",
        due_date="2026-05-05T00:00:00Z", paid_date="2026-05-05T00:00:00Z")), 201)
    # second payment re-uses the now-stale version
    resp = api.create_rent_payment(lh, create_rent_payment_payload(
        lease["id"], stale_version, period_month="2026-06",
        due_date="2026-06-05T00:00:00Z", paid_date="2026-06-05T00:00:00Z"))
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value, 412)


def test_correct_lease_version_on_payment_succeeds_and_advances_version(api):
    """PRD §2.6: "A successful recording itself advances the lease's `version` by
    one, so a client recording two payments in sequence must re-read the lease".

    Design: Corner/cross_cutting_complexity_layers/occ_correct_lease_version_on_payment_succeeds
    """
    reset_clock_default(api)
    tenant = create_tenant(api, full_name="Ok Tenant", email="ok@x.com")
    landlord = create_landlord(api)
    lease = create_verified_lease(api, tenant["id"], landlord["id"], property_address="61 OK Rd")
    lh = make_landlord_headers(landlord["id"])
    resp = api.create_rent_payment(lh, create_rent_payment_payload(
        lease["id"], lease["version"], period_month="2026-06",
        due_date="2026-06-05T00:00:00Z", paid_date="2026-06-05T00:00:00Z"))
    validate_success(resp, 201)
    # created(1) -> verified(2) -> payment(3)
    assert current_lease_version(api, landlord["id"], lease["id"]) == 3


# --------------------------------------------------------------------------
# RBAC: tenant cannot furnish a payment (ComplianceAnalyst-exclusive)
# --------------------------------------------------------------------------
def test_tenant_cannot_report_payment(api):
    """PRD §2.1: "If the headers are well-formed but the acting role is not
    permitted to perform the requested operation — or an ownership check fails —
    the request is rejected with `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/tenant_cannot_report_payment_returns_unauthorized
    """
    reset_clock_default(api)
    tenant = create_tenant(api, full_name="Toby Tent", email="toby@x.com")
    landlord = create_landlord(api)
    th = make_tenant_headers(tenant["id"])
    lh = make_landlord_headers(landlord["id"])
    lease = get_success_data(api.create_lease(th, {
        "tenant_id": tenant["id"], "landlord_id": landlord["id"],
        "property_address": "51 Role Ave", "rent_amount_cents": 120000,
        "monthly_due_day": 5, "lease_start": "2026-01-01T00:00:00Z",
        "lease_end": "2027-01-01T00:00:00Z"}))
    payment = get_success_data(api.create_rent_payment(lh, create_rent_payment_payload(
        lease["id"], lease["version"], period_month="2026-06",
        due_date="2026-06-05T00:00:00Z", paid_date="2026-06-05T00:00:00Z")))
    resp = api.report_rent_payment(th, payment["id"])
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value, 403)
