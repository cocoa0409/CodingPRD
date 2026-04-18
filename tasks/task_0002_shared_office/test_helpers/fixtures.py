"""Composite setup helpers for multi-step Shared Office API test prerequisites.

Uses get_success_data() (lenient validator) internally so setup failures surface as
"Setup failed" errors rather than obscure assertion failures downstream.

Identity threading (mandatory per PRD §2.1): whenever a fixture creates a Member,
any ownership-gated downstream call issued as that member MUST use
`make_tenant_admin_headers(member["id"])` or `make_tenant_member_headers(member["id"])`
— never fall back to the shared TEST_USERS constants, because those constants carry
an X-User-ID that does not match any real Member's id, and every ownership check
would reject the request.

Segregation of duties (PRD §3.6): lease `finalize-termination` requires the acting
PlatformAdmin's X-User-ID to differ from the PlatformAdmin who performed
`begin-review`. The fixtures in this file use two distinct PlatformAdmin identities
whenever they need to walk a lease all the way through to TERMINATED.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    add_hours,
    add_minutes,
    create_access_badge_payload,
    create_access_event_payload,
    create_lease_payload,
    create_member_payload,
    create_reservation_payload,
    create_resource_payload,
    create_tenant_payload,
    create_visitor_payload,
    iso_utc,
)
from .test_users import (
    TEST_USERS,
    make_billing_officer_headers,
    make_payment_clerk_headers,
    make_platform_admin_headers,
    make_receptionist_headers,
    make_tenant_admin_headers,
    make_tenant_member_headers,
)


# ──────────────────────────────────────────────────────────
# Clock helpers (PRD §2.6 / §2.10): /_clock/advance and /_sweep/run are PlatformAdmin
# endpoints. Advancing the clock does NOT run the sweep per PRD; the two must be
# invoked separately.
# ──────────────────────────────────────────────────────────


def advance_clock_to(to_timestamp: str) -> None:
    """Advance the virtual clock to the given ISO 8601 UTC timestamp (PRD §2.6).

    Per PRD, /_clock/advance does not run sweeps; sweeps must be invoked separately
    via run_sweep() below.
    """
    get_success_data(api_client.advance_clock(to_timestamp, TEST_USERS["admin_headers"]))


def run_sweep() -> Dict[str, Any]:
    """Invoke the deterministic sweep (PRD §2.6): reservations, visitors, bills, and
    Tenant.access_posture are recomputed in a fixed order."""
    return get_success_data(api_client.run_sweep(TEST_USERS["admin_headers"]))


# ──────────────────────────────────────────────────────────
# Tier 1: State progression — create + walk entities to their testable state.
# ──────────────────────────────────────────────────────────


def create_tenant(**overrides: Any) -> Dict[str, Any]:
    """Create a Tenant (PlatformAdmin-only per PRD §3.1)."""
    return get_success_data(
        api_client.create_tenant(create_tenant_payload(**overrides), TEST_USERS["admin_headers"])
    )


def create_member(tenant: Dict[str, Any], **overrides: Any) -> Dict[str, Any]:
    """Create a Member under the given tenant (PlatformAdmin or TenantAdmin per PRD §3.1)."""
    return get_success_data(
        api_client.create_member(
            create_member_payload(tenant["id"], **overrides), TEST_USERS["admin_headers"]
        )
    )


def create_draft_lease(
    tenant: Dict[str, Any],
    billing_plan: str = "DAILY",
    term_start_date: str = "2026-01-01",
    term_end_date: str = "2026-12-31",
    **overrides: Any,
) -> Dict[str, Any]:
    """Create a DRAFT lease (PRD §3.1: PlatformAdmin-only)."""
    return get_success_data(
        api_client.create_lease(
            create_lease_payload(
                tenant["id"],
                billing_plan=billing_plan,
                term_start_date=term_start_date,
                term_end_date=term_end_date,
                **overrides,
            ),
            TEST_USERS["admin_headers"],
        )
    )


def create_active_lease(
    tenant: Dict[str, Any],
    billing_plan: str = "DAILY",
    term_start_date: str = "2026-01-01",
    term_end_date: str = "2026-12-31",
    **overrides: Any,
) -> Dict[str, Any]:
    """Create a DRAFT lease and activate it (PRD §3.1 activate transition).

    Per PRD §3.1, activation requires the tenant to be ACTIVE and term_start_date
    not after term_end_date.
    """
    lease = create_draft_lease(
        tenant,
        billing_plan=billing_plan,
        term_start_date=term_start_date,
        term_end_date=term_end_date,
        **overrides,
    )
    return get_success_data(
        api_client.activate_lease(lease["id"], TEST_USERS["admin_headers"])
    )


def create_resource(kind: str = "WORKSTATION", **overrides: Any) -> Dict[str, Any]:
    """Create a bookable Resource (PRD §3.2: PlatformAdmin-only)."""
    return get_success_data(
        api_client.create_resource(
            create_resource_payload(kind=kind, **overrides), TEST_USERS["admin_headers"]
        )
    )


def issue_access_badge(member: Dict[str, Any], **overrides: Any) -> Dict[str, Any]:
    """Issue an AccessBadge to the given member (PRD §3.5)."""
    return get_success_data(
        api_client.create_access_badge(
            create_access_badge_payload(member["id"], **overrides), TEST_USERS["admin_headers"]
        )
    )


# ──────────────────────────────────────────────────────────
# Tier 2: Entity hierarchy — tenant + member + badge (+ optional resource / lease).
# ──────────────────────────────────────────────────────────


def setup_tenant_with_member(
    *,
    credit_limit_cents: Optional[int] = None,
    role_in_tenant: str = "STAFF",
    **tenant_overrides: Any,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Create Tenant + one Member under it. Returns (tenant, member).

    PRD §3.1: TenantMember is the default role for ownership-gated reservation
    flows; callers that need a TenantAdmin should pass role_in_tenant='ADMIN'.
    """
    tenant_kwargs = dict(tenant_overrides)
    if credit_limit_cents is not None:
        tenant_kwargs["credit_limit_cents"] = credit_limit_cents
    tenant = create_tenant(**tenant_kwargs)
    member = create_member(tenant, role_in_tenant=role_in_tenant)
    return tenant, member


def setup_tenant_member_badge(
    *,
    credit_limit_cents: Optional[int] = None,
    billing_plan: str = "DAILY",
    monthly_rate_cents: Optional[int] = None,
    term_start_date: str = "2026-01-01",
    term_end_date: str = "2026-12-31",
    role_in_tenant: str = "STAFF",
    **tenant_overrides: Any,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Create Tenant + ACTIVE Lease + Member + ACTIVE Badge.

    Returns (tenant, lease, member, badge).

    PRD §3.3: the lease's billing_plan governs the provisional pricing for
    workstation reservations made by this tenant's members.
    """
    tenant, member = setup_tenant_with_member(
        credit_limit_cents=credit_limit_cents, role_in_tenant=role_in_tenant, **tenant_overrides
    )
    lease_overrides: Dict[str, Any] = {}
    if monthly_rate_cents is not None:
        lease_overrides["monthly_rate_cents"] = monthly_rate_cents
    lease = create_active_lease(
        tenant,
        billing_plan=billing_plan,
        term_start_date=term_start_date,
        term_end_date=term_end_date,
        **lease_overrides,
    )
    badge = issue_access_badge(member)
    return tenant, lease, member, badge


def setup_tenant_with_tenant_admin(
    **kwargs: Any,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Create Tenant + ACTIVE Lease + TenantAdmin Member + Badge.

    Returns (tenant, lease, admin_member, badge). Intended for tests of lease
    request-termination / withdraw-termination which are TenantAdmin-only per PRD §3.6.
    """
    return setup_tenant_member_badge(role_in_tenant="ADMIN", **kwargs)


# ──────────────────────────────────────────────────────────
# Tier 3: Reservation lifecycle shortcuts — create / confirm / check-in / check-out.
# ──────────────────────────────────────────────────────────


def create_reservation(
    tenant: Dict[str, Any],
    member: Dict[str, Any],
    resource: Dict[str, Any],
    start_at: str,
    end_at: str,
    **overrides: Any,
) -> Dict[str, Any]:
    """Create a PENDING reservation (PRD §3.3).

    Uses make_tenant_member_headers(member["id"]) so the identity passes PRD §2.1's
    Member-backed identity rule on reservation creation.
    """
    headers = make_tenant_member_headers(member["id"])
    return get_success_data(
        api_client.create_reservation(
            create_reservation_payload(
                tenant["id"], member["id"], resource["id"], start_at, end_at, **overrides
            ),
            headers,
        )
    )


def confirm_reservation(reservation: Dict[str, Any], member: Dict[str, Any]) -> Dict[str, Any]:
    """Transition PENDING → CONFIRMED (PRD §3.3 confirmation; computes provisional fee)."""
    headers = make_tenant_member_headers(member["id"])
    return get_success_data(api_client.confirm_reservation(reservation["id"], headers))


def create_and_confirm_reservation(
    tenant: Dict[str, Any],
    member: Dict[str, Any],
    resource: Dict[str, Any],
    start_at: str,
    end_at: str,
) -> Dict[str, Any]:
    """Create PENDING + confirm to CONFIRMED with provisional_fee_cents set."""
    pending = create_reservation(tenant, member, resource, start_at, end_at)
    return confirm_reservation(pending, member)


def check_in_reservation(
    reservation: Dict[str, Any], member: Dict[str, Any], badge: Dict[str, Any]
) -> Dict[str, Any]:
    """Drive CONFIRMED → IN_USE via /access-events with kind=CHECK_IN (PRD §3.3)."""
    headers = make_tenant_member_headers(member["id"])
    return get_success_data(
        api_client.create_access_event(
            create_access_event_payload(
                kind="CHECK_IN",
                reservation_id=reservation["id"],
                badge_id=badge["id"],
            ),
            headers,
        )
    )


def check_out_reservation(
    reservation: Dict[str, Any], member: Dict[str, Any], badge: Dict[str, Any]
) -> Dict[str, Any]:
    """Drive IN_USE → COMPLETED via /access-events with kind=CHECK_OUT (PRD §3.3)."""
    headers = make_tenant_member_headers(member["id"])
    return get_success_data(
        api_client.create_access_event(
            create_access_event_payload(
                kind="CHECK_OUT",
                reservation_id=reservation["id"],
                badge_id=badge["id"],
            ),
            headers,
        )
    )


def get_reservation(reservation_id: str) -> Dict[str, Any]:
    """Fetch the latest Reservation state as a PlatformAdmin (who can read any)."""
    return get_success_data(
        api_client.get_reservation(reservation_id, TEST_USERS["admin_headers"])
    )


def run_full_reservation_lifecycle(
    tenant: Dict[str, Any],
    member: Dict[str, Any],
    resource: Dict[str, Any],
    badge: Dict[str, Any],
    start_at: str,
    end_at: str,
    *,
    clock_at_checkin: Optional[str] = None,
    clock_at_checkout: Optional[str] = None,
) -> Dict[str, Any]:
    """Create → confirm → check-in → check-out, advancing the clock as specified.

    Returns the post-checkout Reservation record (COMPLETED).

    clock_at_checkin defaults to start_at.
    clock_at_checkout defaults to end_at.
    """
    reservation = create_and_confirm_reservation(tenant, member, resource, start_at, end_at)
    advance_clock_to(clock_at_checkin or start_at)
    check_in_reservation(reservation, member, badge)
    advance_clock_to(clock_at_checkout or end_at)
    check_out_reservation(reservation, member, badge)
    return get_reservation(reservation["id"])


# ──────────────────────────────────────────────────────────
# Tier 3b: Visitor lifecycle shortcuts.
# ──────────────────────────────────────────────────────────


def register_visitor(
    member: Dict[str, Any],
    expected_arrival_at: str,
    expected_departure_at: str,
    **overrides: Any,
) -> Dict[str, Any]:
    """Register a visitor under the given host Member (PRD §3.4)."""
    headers = make_tenant_member_headers(member["id"])
    return get_success_data(
        api_client.create_visitor(
            create_visitor_payload(
                member["id"], expected_arrival_at, expected_departure_at, **overrides
            ),
            headers,
        )
    )


def visitor_check_in(visitor: Dict[str, Any]) -> Dict[str, Any]:
    """Drive REGISTERED → CHECKED_IN as a Receptionist (PRD §3.4)."""
    return get_success_data(
        api_client.create_access_event(
            create_access_event_payload(
                kind="VISITOR_CHECK_IN", visitor_id=visitor["id"]
            ),
            TEST_USERS["receptionist_headers"],
        )
    )


def visitor_check_out(visitor: Dict[str, Any]) -> Dict[str, Any]:
    """Drive CHECKED_IN → CHECKED_OUT as a Receptionist; computes overstay_fee_cents
    (PRD §3.4)."""
    return get_success_data(
        api_client.create_access_event(
            create_access_event_payload(
                kind="VISITOR_CHECK_OUT", visitor_id=visitor["id"]
            ),
            TEST_USERS["receptionist_headers"],
        )
    )


def get_visitor(visitor_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_visitor(visitor_id, TEST_USERS["admin_headers"]))


# ──────────────────────────────────────────────────────────
# Tier 4: Accumulation / threshold targeting — bring system to an exact cumulative
# state so boundary-precision tests can assert the threshold behaviour cleanly.
# ──────────────────────────────────────────────────────────


def find_draft_bill_for_tenant(tenant: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """List bills for the tenant and return the current DRAFT bill, or None."""
    data = get_success_data(
        api_client.list_bills(
            TEST_USERS["admin_headers"],
            params={"tenant_id": tenant["id"], "status": "DRAFT", "limit": 100},
        )
    )
    # list_bills returns list under data; paginated envelope is handled by lenient getter.
    if isinstance(data, list):
        bills = data
    else:
        bills = []
    return bills[0] if bills else None


def get_bill(bill_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_bill(bill_id, TEST_USERS["admin_headers"]))


def issue_bill_as_officer(bill: Dict[str, Any]) -> Dict[str, Any]:
    """Issue a DRAFT bill using BillingOfficer headers (PRD §3.7)."""
    return get_success_data(
        api_client.issue_bill(bill["id"], TEST_USERS["billing_officer_headers"])
    )


def pay_bill_as_clerk(bill: Dict[str, Any]) -> Dict[str, Any]:
    """Pay an ISSUED or OVERDUE bill using PaymentClerk headers (PRD §3.7)."""
    return get_success_data(
        api_client.pay_bill(bill["id"], TEST_USERS["payment_clerk_headers"])
    )


def void_bill_as_admin(bill: Dict[str, Any]) -> Dict[str, Any]:
    """Void a DRAFT bill using PlatformAdmin headers (PRD §3.7)."""
    return get_success_data(api_client.void_bill(bill["id"], TEST_USERS["admin_headers"]))


def get_tenant(tenant_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_tenant(tenant_id, TEST_USERS["admin_headers"]))


def setup_tenant_at_outstanding_balance(
    target_balance_cents: int,
    *,
    credit_limit_cents: int = 500_000,
    base_date: str = "2026-05-01",
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Bring a tenant to a specific outstanding_balance_cents value by completing one
    workstation reservation whose final_fee_cents plus tax lands on the target sum,
    then issuing the resulting Bill.

    Returns (tenant, member, resource, issued_bill).

    Per PRD §2.10 / §3.7, Tenant.outstanding_balance_cents is the sum of total_due_cents
    for bills of the tenant in ISSUED or OVERDUE; issuing a DRAFT bill enters it into
    that sum and causes access_posture to flip RESTRICTED when the new balance reaches
    credit_limit_cents.
    """
    # Pick workstation hourly rate so that 1 hour * rate + 8.25% tax ≈ target_balance.
    # Given integer cents and sum-then-round tax, we'll overshoot slightly rather than
    # miss — callers typically want "at or above the credit limit", not exact match.
    # Solve: floor(target / 1.0825) — start from that to cover credit limits cleanly.
    hourly_rate = max(1, round(target_balance_cents / 1.0825))
    tenant, lease, member, badge = setup_tenant_member_badge(
        credit_limit_cents=credit_limit_cents,
        billing_plan="HOURLY",
    )
    resource = create_resource(
        kind="WORKSTATION",
        hourly_rate_cents=hourly_rate,
        daily_rate_cents=hourly_rate * 100,  # deliberately uncompetitive so hourly wins
    )
    start = f"{base_date}T09:00:00.000Z"
    end = f"{base_date}T10:00:00.000Z"
    advance_clock_to(f"{base_date}T08:00:00.000Z")
    run_full_reservation_lifecycle(
        tenant, member, resource, badge, start, end, clock_at_checkin=start, clock_at_checkout=end
    )
    bill = find_draft_bill_for_tenant(tenant)
    assert bill is not None, "Setup failed: no DRAFT bill was created by reservation completion"
    issued = issue_bill_as_officer(bill)
    return tenant, member, resource, issued


# ──────────────────────────────────────────────────────────
# Tier 5: Lease termination lifecycle — walk ACTIVE → TERMINATION_REQUESTED →
# TERMINATION_REVIEWING → TERMINATED / REJECTED. Uses two distinct PlatformAdmin
# identities so PRD §3.6 segregation of duties is satisfied on finalize-termination.
# ──────────────────────────────────────────────────────────


PLATFORM_ADMIN_REVIEWER_ID = "test-platform-admin-reviewer"
PLATFORM_ADMIN_FINALIZER_ID = "test-platform-admin-finalizer"


def request_termination_as_tenant_admin(
    lease: Dict[str, Any], admin_member: Dict[str, Any]
) -> Dict[str, Any]:
    """TenantAdmin requests termination (PRD §3.6)."""
    headers = make_tenant_admin_headers(admin_member["id"])
    return get_success_data(api_client.request_lease_termination(lease["id"], headers))


def withdraw_termination_as_tenant_admin(
    lease: Dict[str, Any], admin_member: Dict[str, Any]
) -> Dict[str, Any]:
    """TenantAdmin withdraws a pending termination request (PRD §3.6 cycle)."""
    headers = make_tenant_admin_headers(admin_member["id"])
    return get_success_data(api_client.withdraw_lease_termination(lease["id"], headers))


def begin_review_with_reviewer(
    lease: Dict[str, Any], reviewer_user_id: str = PLATFORM_ADMIN_REVIEWER_ID
) -> Dict[str, Any]:
    """PlatformAdmin begins review; server records X-User-ID as reviewer_user_id
    (PRD §3.6). Returns the Lease in TERMINATION_REVIEWING."""
    headers = make_platform_admin_headers(reviewer_user_id)
    return get_success_data(api_client.begin_lease_review(lease["id"], headers))


def finalize_termination_with_different_admin(
    lease: Dict[str, Any], finalizer_user_id: str = PLATFORM_ADMIN_FINALIZER_ID
) -> Dict[str, Any]:
    """PlatformAdmin (different X-User-ID from the reviewer) finalizes termination.

    PRD §3.6 enforces segregation of duties: the finalizer's X-User-ID must differ
    from the reviewer_user_id set at begin-review, otherwise ERR_SEGREGATION_OF_DUTIES.
    """
    headers = make_platform_admin_headers(finalizer_user_id)
    return get_success_data(api_client.finalize_lease_termination(lease["id"], headers))


def reject_termination_with_reviewer(
    lease: Dict[str, Any], admin_user_id: str = PLATFORM_ADMIN_REVIEWER_ID
) -> Dict[str, Any]:
    """PlatformAdmin rejects termination from TERMINATION_REVIEWING (PRD §3.6)."""
    headers = make_platform_admin_headers(admin_user_id)
    return get_success_data(api_client.reject_lease_termination(lease["id"], headers))


def setup_lease_in_termination_reviewing(
    *,
    billing_plan: str = "MONTHLY",
    monthly_rate_cents: int = 90_000,
    term_start_date: str = "2026-01-01",
    term_end_date: str = "2026-09-30",
    credit_limit_cents: Optional[int] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Build a tenant + ACTIVE Lease + TenantAdmin member + ACTIVE Badge, then walk
    the lease through request-termination and begin-review so it sits in
    TERMINATION_REVIEWING.

    Returns (tenant, lease, admin_member, badge) with lease.status ==
    TERMINATION_REVIEWING.
    """
    tenant, lease, admin_member, badge = setup_tenant_with_tenant_admin(
        credit_limit_cents=credit_limit_cents,
        billing_plan=billing_plan,
        monthly_rate_cents=monthly_rate_cents,
        term_start_date=term_start_date,
        term_end_date=term_end_date,
    )
    request_termination_as_tenant_admin(lease, admin_member)
    reviewing = begin_review_with_reviewer(lease)
    return tenant, reviewing, admin_member, badge


# ──────────────────────────────────────────────────────────
# Misc utilities used by the difficulty-coverage tests.
# ──────────────────────────────────────────────────────────


def next_monday_0900_utc(anchor: Optional[datetime] = None) -> str:
    """Return the next Monday at 09:00 UTC after `anchor` (default: now).

    Useful for picking reservation windows that definitely do not fall on a weekend
    — the event-area weekend discount would otherwise apply (PRD §3.3).
    """
    now = anchor or datetime.now(tz=timezone.utc)
    days_until_monday = (7 - now.weekday()) % 7 or 7
    target = (now + timedelta(days=days_until_monday)).replace(
        hour=9, minute=0, second=0, microsecond=0
    )
    return iso_utc(target)


def next_saturday_0900_utc(anchor: Optional[datetime] = None) -> str:
    """Return the next Saturday at 09:00 UTC after `anchor`. Useful for exercising
    the event-area full-weekend discount (PRD §3.3)."""
    now = anchor or datetime.now(tz=timezone.utc)
    days_until_saturday = (5 - now.weekday()) % 7 or 7
    target = (now + timedelta(days=days_until_saturday)).replace(
        hour=9, minute=0, second=0, microsecond=0
    )
    return iso_utc(target)
