"""Leases: verification lifecycle, half-open overlap, ownership, and the
cross-entity report-blocked-until-verified dependency.

Covers the half-open overlap rule, the report-requires-verified dependency, and
lease verification lifecycle and ownership.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS, make_tenant_headers, make_landlord_headers,
    create_lease_payload,
    reset_clock_default, create_tenant, create_landlord, create_plan,
    activate_enrollment, create_verified_lease, record_payment,
)

ADMIN = TEST_USERS["admin_headers"]
ANALYST = TEST_USERS["analyst_headers"]


# --------------------------------------------------------------------------
# Corner: verify lifecycle
# --------------------------------------------------------------------------
def test_verify_reject_sets_rejected_status(api):
    """PRD §3.3: "a `REJECTED` decision moves it to `REJECTED`; either way the
    lease's `version` increments by one."

    Design: Corner/state_machines/lease_verify_reject_sets_rejected
    """
    reset_clock_default(api)
    tenant = create_tenant(api, full_name="Ray Rej", email="ray@x.com")
    landlord = create_landlord(api)
    th = make_tenant_headers(tenant["id"])
    lh = make_landlord_headers(landlord["id"])
    lease = get_success_data(api.create_lease(th, create_lease_payload(
        tenant["id"], landlord["id"], property_address="34 Rej Blvd")))
    resp = api.verify_lease(lh, lease["id"], {"decision": "REJECTED", "note": "docs missing"})
    data = validate_success(resp, 200)
    assert data["verification_status"] == "REJECTED"


def test_verify_already_verified_returns_already_verified(api):
    """PRD §3.3: "Verification is only valid from `PENDING_VERIFICATION` —
    attempting it on a lease already `VERIFIED`, `REJECTED`, or `TERMINATED` is
    rejected with `ERR_ALREADY_VERIFIED`."

    Design: Corner/state_machines/verify_already_verified_returns_already_verified
    """
    reset_clock_default(api)
    tenant = create_tenant(api, full_name="Vic Verify", email="vic@x.com")
    landlord = create_landlord(api)
    lease = create_verified_lease(api, tenant["id"], landlord["id"], property_address="30 Verify St")
    lh = make_landlord_headers(landlord["id"])
    resp = api.verify_lease(lh, lease["id"], {"decision": "VERIFIED"})
    validate_error(resp, ApiErrorId.ERR_ALREADY_VERIFIED.value, 409)


# --------------------------------------------------------------------------
# RBAC: landlord ownership on verify
# --------------------------------------------------------------------------
def test_landlord_cannot_verify_unowned_lease(api):
    """PRD §3.3: "the acting landlord's `X-User-ID` must equal the lease's
    `landlord_id`."
    PRD §2.1: "Ownership checks compare a lease's `landlord_id` to `X-User-ID`: a
    landlord may verify only the leases they are named on".

    Design: Corner/rbac/landlord_cannot_verify_unowned_lease_returns_unauthorized
    """
    reset_clock_default(api)
    tenant = create_tenant(api, full_name="Ted Ten", email="ted@x.com")
    ll1 = create_landlord(api, company_name="PM One", email="pm1@x.com")
    ll2 = create_landlord(api, company_name="PM Two", email="pm2@x.com")
    th = make_tenant_headers(tenant["id"])
    lease = get_success_data(api.create_lease(th, create_lease_payload(
        tenant["id"], ll1["id"], property_address="50 Peer St")))
    resp = api.verify_lease(make_landlord_headers(ll2["id"]), lease["id"], {"decision": "VERIFIED"})
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value, 403)


# --------------------------------------------------------------------------
# Difficulty: resource_temporal_overlap / lease continuous half-open interval
# --------------------------------------------------------------------------
def test_overlapping_lease_same_tenant_address_rejected(api):
    """PRD §3.3: "A new lease is refused if its term overlaps any existing
    non-terminal lease sharing the same combination of `tenant_id` and
    `property_address`; because the interval is half-open, a new lease whose
    `lease_start` equals a prior lease's `lease_end` does not overlap, but any true
    overlap is rejected with `ERR_LEASE_DATE_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/lease_continuous_daterange_overlap_rejected
    """
    reset_clock_default(api)
    tenant = create_tenant(api, full_name="Ola Overlap", email="ola@x.com")
    landlord = create_landlord(api)
    th = make_tenant_headers(tenant["id"])
    get_success_data(api.create_lease(th, create_lease_payload(
        tenant["id"], landlord["id"], property_address="20 Overlap St",
        lease_start="2026-01-01T00:00:00Z", lease_end="2027-01-01T00:00:00Z")))
    resp = api.create_lease(th, create_lease_payload(
        tenant["id"], landlord["id"], property_address="20 Overlap St",
        rent_amount_cents=130000,
        lease_start="2026-06-01T00:00:00Z", lease_end="2026-12-01T00:00:00Z"))
    validate_error(resp, ApiErrorId.ERR_LEASE_DATE_OVERLAP.value, 409)


def test_adjacent_lease_at_prior_end_is_not_overlap(api):
    """PRD §3.3: "because the interval is half-open, a new lease whose
    `lease_start` equals a prior lease's `lease_end` does not overlap".

    Design: Difficulty/resource_temporal_overlap/lease_continuous_daterange_overlap_rejected
    """
    reset_clock_default(api)
    tenant = create_tenant(api, full_name="Abe Adjacent", email="abe@x.com")
    landlord = create_landlord(api)
    th = make_tenant_headers(tenant["id"])
    get_success_data(api.create_lease(th, create_lease_payload(
        tenant["id"], landlord["id"], property_address="21 Adjacent St",
        lease_start="2025-01-01T00:00:00Z", lease_end="2026-01-01T00:00:00Z")))
    # second lease starts exactly where the first ends -> half-open, no overlap
    resp = api.create_lease(th, create_lease_payload(
        tenant["id"], landlord["id"], property_address="21 Adjacent St",
        lease_start="2026-01-01T00:00:00Z", lease_end="2027-01-01T00:00:00Z"))
    data = validate_success(resp, 201)
    assert data["verification_status"] == "PENDING_VERIFICATION"


# --------------------------------------------------------------------------
# Difficulty: cross_entity_state_dependency / report blocked until lease VERIFIED
# --------------------------------------------------------------------------
def test_report_blocked_when_lease_not_verified(api):
    """PRD §3.5: "the lease must be `VERIFIED`, otherwise `ERR_LEASE_NOT_VERIFIED`".

    Design: Difficulty/cross_entity_state_dependency/report_blocked_until_lease_verified
    """
    reset_clock_default(api)
    plan = create_plan(api)
    tenant = create_tenant(api, full_name="Van Verify", email="van@x.com")
    landlord = create_landlord(api)
    activate_enrollment(api, tenant["id"], plan["id"])
    th = make_tenant_headers(tenant["id"])
    # lease left PENDING_VERIFICATION (never verified)
    lease = get_success_data(api.create_lease(th, create_lease_payload(
        tenant["id"], landlord["id"], property_address="11 Ash Pl")))
    payment = record_payment(api, landlord["id"], lease["id"],
                             period_month="2026-06", due_date="2026-06-05T00:00:00Z",
                             paid_date="2026-06-05T00:00:00Z")
    resp = api.report_rent_payment(ANALYST, payment["id"])
    validate_error(resp, ApiErrorId.ERR_LEASE_NOT_VERIFIED.value, 409)


def test_report_blocked_leaves_payment_recorded(api):
    """PRD §3.5: "As the tradeline is created, the payment moves from `RECORDED`
    to `REPORTED`" — so a furnish rejected because "the lease must be `VERIFIED`,
    otherwise `ERR_LEASE_NOT_VERIFIED`" leaves the payment still `RECORDED`.

    Design: Difficulty/cross_entity_state_dependency/report_blocked_until_lease_verified
    """
    reset_clock_default(api)
    plan = create_plan(api)
    tenant = create_tenant(api, full_name="Win Verify", email="win@x.com")
    landlord = create_landlord(api)
    activate_enrollment(api, tenant["id"], plan["id"])
    th = make_tenant_headers(tenant["id"])
    lh = make_landlord_headers(landlord["id"])
    lease = get_success_data(api.create_lease(th, create_lease_payload(
        tenant["id"], landlord["id"], property_address="12 Ash Pl")))
    payment = record_payment(api, landlord["id"], lease["id"],
                             period_month="2026-06", due_date="2026-06-05T00:00:00Z",
                             paid_date="2026-06-05T00:00:00Z")
    validate_error(api.report_rent_payment(ANALYST, payment["id"]),
                   ApiErrorId.ERR_LEASE_NOT_VERIFIED.value, 409)
    after = validate_success(api.get_rent_payment(lh, payment["id"]), 200)
    assert after["status"] == "RECORDED"
