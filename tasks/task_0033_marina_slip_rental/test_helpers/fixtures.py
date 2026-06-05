"""Composite setup helpers for the marina-slip-rental benchmark.

Each fixture builds its preconditions from scratch through PRD-declared
endpoints (see PRD §3.x). The runner restarts the API server before every
individual pytest test, so each fixture starts from an empty database — no
entities, no clock state.

Fixtures use `get_success_data()` (lenient validator) so setup failures
surface as clear "Setup failed" traces rather than cryptic assertion failures.

Identity threading: the Tenant role is entity-backed (PRD §2.1). Any
ownership-gated tenant call must use `make_tenant_headers(tenant["id"])`,
never the shared `TEST_USERS["tenant_headers"]` fallback (which carries a
fake X-User-ID that never matches a real Tenant row).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_marina_payload,
    create_slip_payload,
    create_tenant_payload,
    create_vessel_payload,
    liveaboard_application_payload,
    liveaboard_approve_payload,
    liveaboard_revoke_payload,
    create_lease_payload,
    create_pump_out_request_payload,
    create_transfer_waitlist_payload,
    set_clock_payload,
)
from .test_users import (
    TEST_USERS,
    make_tenant_headers,
)


_HM = TEST_USERS["harbor_master_headers"]
_MS = TEST_USERS["marina_staff_headers"]


# ─── Tier 0: clock control (PRD §2.10) ──────────────────────────


def set_clock(iso8601: str) -> dict:
    """Pin the server's logical UTC clock (PRD §2.10)."""
    return get_success_data(api_client.set_clock(set_clock_payload(iso8601), _HM))


# ─── Tier 1: leaf creators ──────────────────────────────────────


def create_marina(
    name: str = "Test Marina",
    liveaboard_cap: int = 3,
    **overrides,
) -> dict:
    """Create a marina (PRD §3.1). Returns the persisted entity."""
    res = api_client.create_marina(
        create_marina_payload(
            name=name,
            liveaboard_cap=liveaboard_cap,
            **overrides,
        ),
        _HM,
    )
    return get_success_data(res)


def create_slip(
    marina_id: str,
    slip_number: str = "A-1",
    length_ft: float = 50,
    beam_ft: float = 15,
    power_amp: str = "A50",
    base_daily_rate_cents: int = 5000,
    pumpout_available: bool = False,
    liveaboard_allowed: bool = False,
    **overrides,
) -> dict:
    """Create a slip under a marina (PRD §3.1). Returns the persisted entity."""
    payload = create_slip_payload(
        slip_number=slip_number,
        length_ft=length_ft,
        beam_ft=beam_ft,
        power_amp=power_amp,
        base_daily_rate_cents=base_daily_rate_cents,
        pumpout_available=pumpout_available,
        liveaboard_allowed=liveaboard_allowed,
        **overrides,
    )
    res = api_client.create_slip(marina_id, payload, _HM)
    return get_success_data(res)


def create_tenant(
    email: str = None,
    full_name: str = "Test Tenant",
    **overrides,
) -> dict:
    """Register a tenant (PRD §3.2). Returns the persisted entity."""
    res = api_client.create_tenant(
        create_tenant_payload(email=email, full_name=full_name, **overrides),
        _HM,
    )
    return get_success_data(res)


def create_vessel(
    tenant_id: str,
    name: str = "Test Vessel",
    loa_ft: float = 40,
    beam_ft: float = 12,
    insurance_policy_number: str = "POL-001",
    insurance_expires_on: str = "2027-01-01",
    insurance_coverage_cents: int = 6_000_000,
    **overrides,
) -> dict:
    """Create a vessel under a tenant (PRD §3.2). Uses the owning tenant's headers."""
    res = api_client.create_vessel(
        create_vessel_payload(
            tenant_id=tenant_id,
            name=name,
            loa_ft=loa_ft,
            beam_ft=beam_ft,
            insurance_policy_number=insurance_policy_number,
            insurance_expires_on=insurance_expires_on,
            insurance_coverage_cents=insurance_coverage_cents,
            **overrides,
        ),
        make_tenant_headers(tenant_id),
    )
    return get_success_data(res)


# ─── Tier 2: liveaboard policy progression (PRD §3.3) ───────────


def apply_liveaboard(tenant_id: str, marina_id: str) -> dict:
    """Tenant submits a liveaboard application (PRD §3.3). Tenant -> PENDING."""
    res = api_client.apply_liveaboard(
        tenant_id,
        liveaboard_application_payload(marina_id),
        make_tenant_headers(tenant_id),
    )
    return get_success_data(res)


def approve_liveaboard(tenant_id: str, marina_id: str) -> dict:
    """HarborMaster approves (PRD §3.3). Tenant PENDING -> APPROVED."""
    res = api_client.approve_liveaboard(
        tenant_id,
        liveaboard_approve_payload(marina_id),
        _HM,
    )
    return get_success_data(res)


def revoke_liveaboard(tenant_id: str, marina_id: str) -> dict:
    """HarborMaster revokes (PRD §3.3). Tenant APPROVED -> REVOKED."""
    res = api_client.revoke_liveaboard(
        tenant_id,
        liveaboard_revoke_payload(marina_id),
        _HM,
    )
    return get_success_data(res)


def make_tenant_approved_for_liveaboard(tenant_id: str, marina_id: str) -> None:
    """Walk the tenant from NONE → PENDING → APPROVED for the named marina (PRD §3.3)."""
    apply_liveaboard(tenant_id, marina_id)
    approve_liveaboard(tenant_id, marina_id)


# ─── Tier 3: lease lifecycle (PRD §3.4, §3.5, §3.8) ─────────────


def reserve_lease(
    marina_id: str,
    slip_id: str,
    tenant_id: str,
    vessel_id: str,
    start_date: str,
    end_date: str,
    expected_slip_version: int,
    is_liveaboard: bool = False,
) -> dict:
    """Create a lease in RESERVED state (PRD §3.4)."""
    res = api_client.create_lease(
        create_lease_payload(
            marina_id=marina_id,
            slip_id=slip_id,
            tenant_id=tenant_id,
            vessel_id=vessel_id,
            start_date=start_date,
            end_date=end_date,
            expected_slip_version=expected_slip_version,
            is_liveaboard=is_liveaboard,
        ),
        make_tenant_headers(tenant_id),
    )
    return get_success_data(res)


def check_in_lease(lease_id: str) -> dict:
    """MarinaStaff check-in (PRD §3.5). Lease RESERVED -> ACTIVE."""
    res = api_client.check_in_lease(lease_id, _MS)
    return get_success_data(res)


def check_out_lease(lease_id: str) -> dict:
    """MarinaStaff check-out (PRD §3.8). Lease ACTIVE -> ENDED, triggers cascade."""
    res = api_client.check_out_lease(lease_id, _MS)
    return get_success_data(res)


def cancel_lease(lease_id: str, tenant_id: str) -> dict:
    """Tenant cancels a RESERVED lease (PRD §3.8). Lease RESERVED -> CANCELLED."""
    res = api_client.cancel_lease(lease_id, make_tenant_headers(tenant_id))
    return get_success_data(res)


# ─── Tier 4: composite scenarios used across multiple tests ─────


def setup_simple_marina_with_slip(
    liveaboard_cap: int = 3,
    pumpout_available: bool = False,
    liveaboard_allowed: bool = False,
    base_daily_rate_cents: int = 5000,
    length_ft: float = 50,
    beam_ft: float = 15,
    **marina_overrides,
) -> dict:
    """Create a marina and one default slip (PRD §3.1).

    Returns dict with keys: marina, slip.
    """
    marina = create_marina(liveaboard_cap=liveaboard_cap, **marina_overrides)
    slip = create_slip(
        marina_id=marina["id"],
        pumpout_available=pumpout_available,
        liveaboard_allowed=liveaboard_allowed,
        base_daily_rate_cents=base_daily_rate_cents,
        length_ft=length_ft,
        beam_ft=beam_ft,
    )
    return {"marina": marina, "slip": slip}


def setup_tenant_with_vessel(
    insurance_expires_on: str = "2027-01-01",
    insurance_coverage_cents: int = 6_000_000,
    loa_ft: float = 40,
    beam_ft: float = 12,
    **tenant_overrides,
) -> dict:
    """Create a tenant + a valid vessel (PRD §3.2).

    Returns dict with keys: tenant, vessel.
    """
    tenant = create_tenant(**tenant_overrides)
    vessel = create_vessel(
        tenant_id=tenant["id"],
        insurance_expires_on=insurance_expires_on,
        insurance_coverage_cents=insurance_coverage_cents,
        loa_ft=loa_ft,
        beam_ft=beam_ft,
    )
    return {"tenant": tenant, "vessel": vessel}


def setup_full_reservation(
    base_daily_rate_cents: int = 5000,
    pumpout_available: bool = False,
    liveaboard_allowed: bool = False,
    liveaboard_cap: int = 3,
    length_ft: float = 50,
    beam_ft: float = 15,
    loa_ft: float = 40,
    vessel_beam_ft: float = 12,
    start_date: str = "2026-07-10",
    end_date: str = "2026-07-15",
    initial_clock: str = "2026-07-01T00:00:00Z",
    is_liveaboard: bool = False,
    insurance_expires_on: str = "2027-01-01",
    insurance_coverage_cents: int = 6_000_000,
) -> dict:
    """Build a full chain to a RESERVED lease (PRD §3.1, §3.2, §3.4).

    Steps: marina -> slip -> tenant -> vessel -> (optional liveaboard approval) ->
    clock -> lease (RESERVED).
    Returns dict with keys: marina, slip, tenant, vessel, lease, slip_version_at_reserve.
    """
    base = setup_simple_marina_with_slip(
        liveaboard_cap=liveaboard_cap,
        pumpout_available=pumpout_available,
        liveaboard_allowed=liveaboard_allowed,
        base_daily_rate_cents=base_daily_rate_cents,
        length_ft=length_ft,
        beam_ft=beam_ft,
    )
    marina = base["marina"]
    slip = base["slip"]
    tv = setup_tenant_with_vessel(
        insurance_expires_on=insurance_expires_on,
        insurance_coverage_cents=insurance_coverage_cents,
        loa_ft=loa_ft,
        beam_ft=vessel_beam_ft,
    )
    tenant = tv["tenant"]
    vessel = tv["vessel"]
    if is_liveaboard:
        make_tenant_approved_for_liveaboard(tenant["id"], marina["id"])
    set_clock(initial_clock)
    slip_version = slip["version"]
    lease = reserve_lease(
        marina_id=marina["id"],
        slip_id=slip["id"],
        tenant_id=tenant["id"],
        vessel_id=vessel["id"],
        start_date=start_date,
        end_date=end_date,
        expected_slip_version=slip_version,
        is_liveaboard=is_liveaboard,
    )
    return {
        "marina": marina,
        "slip": slip,
        "tenant": tenant,
        "vessel": vessel,
        "lease": lease,
        "slip_version_at_reserve": slip_version,
    }


def setup_active_lease(
    base_daily_rate_cents: int = 5000,
    pumpout_available: bool = False,
    liveaboard_allowed: bool = False,
    liveaboard_cap: int = 3,
    length_ft: float = 50,
    beam_ft: float = 15,
    loa_ft: float = 40,
    vessel_beam_ft: float = 12,
    start_date: str = "2026-07-10",
    end_date: str = "2026-07-15",
    initial_clock: str = "2026-07-01T00:00:00Z",
    checkin_clock: str = "2026-07-10T00:00:00Z",
    is_liveaboard: bool = False,
    insurance_expires_on: str = "2027-01-01",
    insurance_coverage_cents: int = 6_000_000,
) -> dict:
    """Build a full chain to an ACTIVE lease (PRD §3.4 + §3.5).

    Reserves, advances clock to check-in, then checks in.
    Returns dict with keys: marina, slip, tenant, vessel, lease (after check-in).
    """
    ctx = setup_full_reservation(
        base_daily_rate_cents=base_daily_rate_cents,
        pumpout_available=pumpout_available,
        liveaboard_allowed=liveaboard_allowed,
        liveaboard_cap=liveaboard_cap,
        length_ft=length_ft,
        beam_ft=beam_ft,
        loa_ft=loa_ft,
        vessel_beam_ft=vessel_beam_ft,
        start_date=start_date,
        end_date=end_date,
        initial_clock=initial_clock,
        is_liveaboard=is_liveaboard,
        insurance_expires_on=insurance_expires_on,
        insurance_coverage_cents=insurance_coverage_cents,
    )
    set_clock(checkin_clock)
    active_lease = check_in_lease(ctx["lease"]["id"])
    ctx["lease"] = active_lease
    return ctx


def setup_ended_lease(
    base_daily_rate_cents: int = 5000,
    pumpout_available: bool = False,
    is_liveaboard: bool = False,
    start_date: str = "2026-07-10",
    end_date: str = "2026-07-12",
    initial_clock: str = "2026-07-01T00:00:00Z",
    checkin_clock: str = "2026-07-10T00:00:00Z",
) -> dict:
    """Build a fully completed lease (ENDED) per PRD §3.8.

    Returns dict with keys: marina, slip, tenant, vessel, lease (ENDED).
    """
    ctx = setup_active_lease(
        base_daily_rate_cents=base_daily_rate_cents,
        pumpout_available=pumpout_available,
        is_liveaboard=is_liveaboard,
        start_date=start_date,
        end_date=end_date,
        initial_clock=initial_clock,
        checkin_clock=checkin_clock,
    )
    ended_lease = check_out_lease(ctx["lease"]["id"])
    ctx["lease"] = ended_lease
    return ctx


# ─── Tier 5: pump-out request helpers (PRD §3.6) ────────────────


def create_pump_out_request(lease_id: str, tenant_id: str) -> dict:
    """Tenant requests pump-out against ACTIVE lease (PRD §3.6)."""
    res = api_client.create_pump_out_request(
        create_pump_out_request_payload(lease_id),
        make_tenant_headers(tenant_id),
    )
    return get_success_data(res)


def complete_pump_out_request(request_id: str) -> dict:
    """MarinaStaff completes a PENDING pump-out (PRD §3.6)."""
    res = api_client.complete_pump_out_request(request_id, _MS)
    return get_success_data(res)


# ─── Tier 6: transfer waitlist helpers (PRD §3.9) ───────────────


def create_transfer_waitlist_entry(
    marina_id: str,
    tenant_id: str,
    from_lease_id: str,
    target_slip_id: str,
) -> dict:
    """Tenant requests transfer to a different slip in same marina (PRD §3.9)."""
    res = api_client.create_transfer_waitlist_entry(
        create_transfer_waitlist_payload(
            marina_id=marina_id,
            tenant_id=tenant_id,
            from_lease_id=from_lease_id,
            target_slip_id=target_slip_id,
        ),
        make_tenant_headers(tenant_id),
    )
    return get_success_data(res)
