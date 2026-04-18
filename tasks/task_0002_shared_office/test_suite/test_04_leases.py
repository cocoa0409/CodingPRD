"""Lease lifecycle tests.

Covers PRD §3.1 (draft → activate) and §3.6 (request-termination / withdraw /
begin-review / finalize / reject cycle and SoD).
"""

import pytest

from test_helpers import (
    PLATFORM_ADMIN_FINALIZER_ID,
    PLATFORM_ADMIN_REVIEWER_ID,
    TEST_USERS,
    advance_clock_to,
    assert_lease,
    begin_review_with_reviewer,
    create_active_lease,
    create_draft_lease,
    create_member,
    create_tenant,
    finalize_termination_with_different_admin,
    make_platform_admin_headers,
    make_tenant_admin_headers,
    request_termination_as_tenant_admin,
    setup_tenant_with_tenant_admin,
    validate_error,
    validate_success,
    withdraw_termination_as_tenant_admin,
)


def test_create_draft_lease(api, admin_headers):
    """PRD §3.1: "A `PlatformAdmin` drafts a `Lease` by naming the `tenant_id`,
    declaring the `billing_plan` as one of `HOURLY`, `DAILY`, or `MONTHLY`, optionally
    supplying the `monthly_rate_cents` (meaningful only when `billing_plan` is
    `MONTHLY`; zero or positive; defaults to 0), and providing inclusive
    `term_start_date` and `term_end_date` in `YYYY-MM-DD` form. The lease enters
    `DRAFT`."

    Claim: POST /leases under a PlatformAdmin returns Lease with status DRAFT.
    """
    tenant = create_tenant()
    lease = create_draft_lease(tenant, billing_plan="MONTHLY")
    assert_lease(lease)
    assert lease["status"] == "DRAFT"
    assert lease["billing_plan"] == "MONTHLY"


def test_activate_draft_lease(api, admin_headers):
    """PRD §3.1: "Activation, performed by a `PlatformAdmin`, transitions the
    lease from `DRAFT` to `ACTIVE` provided the tenant is itself `ACTIVE` and the
    `term_start_date` is not after the `term_end_date`."

    Claim: POST /leases/{id}/activate on a DRAFT lease → ACTIVE.
    """
    tenant = create_tenant()
    active = create_active_lease(tenant)
    assert active["status"] == "ACTIVE"
    # PRD §2.4: every mutation increments version by exactly 1.
    assert active["version"] >= 2


def test_activate_already_active_lease_rejected(api, admin_headers):
    """PRD §3.1: "Activation, performed by a `PlatformAdmin`, transitions the
    lease from `DRAFT` to `ACTIVE` provided the tenant is itself `ACTIVE` and the
    `term_start_date` is not after the `term_end_date`."
    PRD §2.8: "an illegal state transition yields the per-entity state error
    (`ERR_INVALID_RESERVATION_STATE`, `ERR_INVALID_BILL_STATE`,
    `ERR_INVALID_LEASE_STATE`, or `ERR_INVALID_VISITOR_STATE`, as applicable)."

    Claim: calling activate on a lease not in DRAFT → ERR_INVALID_LEASE_STATE.
    """
    tenant = create_tenant()
    active = create_active_lease(tenant)
    res = api.activate_lease(active["id"], admin_headers)
    validate_error(res, "ERR_INVALID_LEASE_STATE", expected_status=409)


def test_request_termination_cycles_back_on_withdraw(api, admin_headers):
    """PRD §3.6: "The same `TenantAdmin` may withdraw the request at any time
    before the platform takes review: withdrawing transitions the lease from
    `TERMINATION_REQUESTED` back to `ACTIVE`, forming the reversible cycle `ACTIVE`
    → `TERMINATION_REQUESTED` → `ACTIVE`."

    Claim: withdraw-termination from TERMINATION_REQUESTED → ACTIVE.
    """
    tenant, lease, admin_member, _badge = setup_tenant_with_tenant_admin()
    requested = request_termination_as_tenant_admin(lease, admin_member)
    assert requested["status"] == "TERMINATION_REQUESTED"
    withdrawn = withdraw_termination_as_tenant_admin(requested, admin_member)
    assert withdrawn["status"] == "ACTIVE"


def test_begin_review_transitions_to_reviewing(api, admin_headers):
    """PRD §3.6: "A `PlatformAdmin` takes review by transitioning the lease from
    `TERMINATION_REQUESTED` to `TERMINATION_REVIEWING`. The server records the
    reviewing admin's `X-User-ID` on the lease as its `reviewer_user_id` — this is
    the identity that the later finalization step must differ from."

    Claim: POST /leases/{id}/begin-review on TERMINATION_REQUESTED → TERMINATION_REVIEWING.
    """
    tenant, lease, admin_member, _badge = setup_tenant_with_tenant_admin()
    requested = request_termination_as_tenant_admin(lease, admin_member)
    reviewing = begin_review_with_reviewer(requested)
    assert reviewing["status"] == "TERMINATION_REVIEWING"


def test_finalize_by_same_admin_as_reviewer_violates_sod(api, admin_headers):
    """PRD §3.6: "Finalization enforces segregation of duties: the acting
    `PlatformAdmin`'s `X-User-ID` must not equal the `reviewer_user_id` recorded at
    `begin-review`; if they match, the request is rejected with
    `ERR_SEGREGATION_OF_DUTIES`."

    Claim: same X-User-ID for begin-review and finalize-termination →
    ERR_SEGREGATION_OF_DUTIES (422).
    """
    tenant, lease, admin_member, _badge = setup_tenant_with_tenant_admin()
    requested = request_termination_as_tenant_admin(lease, admin_member)
    begin_review_with_reviewer(requested, reviewer_user_id="same-admin-99")
    # Finalize with the SAME X-User-ID as reviewer.
    same_headers = make_platform_admin_headers("same-admin-99")
    res = api.finalize_lease_termination(requested["id"], same_headers)
    validate_error(res, "ERR_SEGREGATION_OF_DUTIES", expected_status=422)


def test_finalize_with_open_reservations_blocked(api, admin_headers):
    """PRD §3.6: "Finalization also requires a clean tenant: every reservation
    of the tenant whose `status` is `PENDING`, `CONFIRMED`, or `IN_USE` must be
    cancelled or completed first, otherwise `ERR_HAS_OPEN_RESERVATIONS`."

    Claim: leaving an IN_USE reservation under the tenant → ERR_HAS_OPEN_RESERVATIONS.
    """
    # Build tenant + lease + member + badge + resource; create + confirm + check-in
    # a reservation so it sits in IN_USE. Then walk the lease into TERMINATION_REVIEWING
    # and attempt finalize.
    from test_helpers import (
        check_in_reservation,
        create_and_confirm_reservation,
        create_resource,
        setup_tenant_member_badge,
    )

    tenant, lease, member, badge = setup_tenant_member_badge(
        role_in_tenant="ADMIN", billing_plan="MONTHLY", monthly_rate_cents=50_000,
        term_start_date="2026-01-01", term_end_date="2026-12-31",
    )
    resource = create_resource(kind="WORKSTATION")
    # Advance the clock so the reservation window is in the accepted horizon.
    advance_clock_to("2026-06-01T08:00:00.000Z")
    reservation = create_and_confirm_reservation(
        tenant, member, resource,
        "2026-06-01T09:00:00.000Z", "2026-06-01T10:00:00.000Z",
    )
    advance_clock_to("2026-06-01T09:00:00.000Z")
    check_in_reservation(reservation, member, badge)
    # Now transition lease into TERMINATION_REVIEWING.
    requested = request_termination_as_tenant_admin(lease, member)
    reviewing = begin_review_with_reviewer(requested, reviewer_user_id="reviewer-open-resv")
    finalizer_headers = make_platform_admin_headers("finalizer-open-resv")
    res = api.finalize_lease_termination(reviewing["id"], finalizer_headers)
    validate_error(res, "ERR_HAS_OPEN_RESERVATIONS", expected_status=422)


def test_reject_termination_is_terminal(api, admin_headers):
    """PRD §3.6: "Alternatively, the `PlatformAdmin` may reject the termination,
    transitioning the lease from `TERMINATION_REVIEWING` to `REJECTED`, which is
    terminal and has no further side effects."

    Claim: reject-termination from TERMINATION_REVIEWING → REJECTED.
    """
    from test_helpers import reject_termination_with_reviewer
    tenant, lease, admin_member, _badge = setup_tenant_with_tenant_admin()
    requested = request_termination_as_tenant_admin(lease, admin_member)
    reviewing = begin_review_with_reviewer(requested, reviewer_user_id="reviewer-reject")
    rejected = reject_termination_with_reviewer(reviewing, admin_user_id="reviewer-reject")
    assert rejected["status"] == "REJECTED"


def test_request_termination_cascade_cancels_future_reservations(api, admin_headers):
    """PRD §3.6: "As a side effect, every `Reservation` of the same tenant whose
    `status` is `PENDING` or `CONFIRMED` and whose `start_at` is strictly after the
    current clock is cascade-cancelled to `CANCELLED`, and each of these cascades
    in turn clears `provisional_fee_cents` on the affected reservation."

    Claim: request-termination cascade-cancels future PENDING/CONFIRMED
    reservations and clears their provisional_fee_cents.
    """
    from test_helpers import (
        create_and_confirm_reservation,
        create_resource,
        get_reservation,
        setup_tenant_member_badge,
    )

    tenant, lease, admin_member, _badge = setup_tenant_member_badge(
        role_in_tenant="ADMIN", billing_plan="HOURLY",
        term_start_date="2026-01-01", term_end_date="2026-12-31",
    )
    resource = create_resource(kind="WORKSTATION")
    advance_clock_to("2026-06-01T08:00:00.000Z")
    future_reservation = create_and_confirm_reservation(
        tenant, admin_member, resource,
        "2026-06-15T09:00:00.000Z", "2026-06-15T10:00:00.000Z",
    )
    assert future_reservation["status"] == "CONFIRMED"
    assert future_reservation["provisional_fee_cents"] > 0
    request_termination_as_tenant_admin(lease, admin_member)
    post = get_reservation(future_reservation["id"])
    assert post["status"] == "CANCELLED", (
        "PRD §3.6: future CONFIRMED reservations must cascade-cancel on request-termination"
    )
    assert post["provisional_fee_cents"] == 0, (
        "PRD §3.6: cascade-cancel clears provisional_fee_cents"
    )
