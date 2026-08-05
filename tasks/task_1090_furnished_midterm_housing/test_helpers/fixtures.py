"""Composite setup helpers.

Because the harness restarts the server (empty database) before every test,
every helper here builds its preconditions from scratch using only
PRD-declared endpoints. Setup calls use get_success_data() (lenient) so that a
broken precondition surfaces as a clear "Setup failed" rather than a confusing
assertion mismatch downstream.

Identity threading: Host and Tenant are entity_backed, so ownership-gated calls
use make_host_headers(host_id) / make_tenant_headers(tenant_id) with the real
entity id — never the shared TEST_USERS constant.
"""
from prd_bench_local_runner.testing import get_success_data
from .test_users import (
    TEST_USERS,
    ANONYMOUS_HEADERS,
    make_host_headers,
    make_tenant_headers,
    make_admin_headers,
)
from .factories import (
    create_host_payload,
    create_tenant_payload,
    create_verification_payload,
    create_unit_payload,
    create_booking_payload,
)

REVIEWER = TEST_USERS["compliance_reviewer_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]


# ---- Logical clock ---------------------------------------------------------

def set_clock(api, to_iso8601):
    """Advance the server logical clock (PlatformAdmin only)."""
    return get_success_data(api.set_clock(to_iso8601, ADMIN))


# ---- Onboarding building blocks --------------------------------------------

def register_host(api, verify_payout=True, **overrides):
    """Register a host; optionally flip payout_account_status to VERIFIED."""
    host = get_success_data(api.create_host(create_host_payload(**overrides), ANONYMOUS_HEADERS))
    if verify_payout:
        host = get_success_data(api.verify_host_payout(host["id"], REVIEWER))
    return host


def register_tenant(api, verified=True, tenant_type="TRAVEL_NURSE", **overrides):
    """Register a tenant. When verified=True, submit and approve one
    GOVERNMENT_ID verification so verification_status becomes VERIFIED."""
    tenant = get_success_data(
        api.create_tenant(create_tenant_payload(tenant_type=tenant_type, **overrides), ANONYMOUS_HEADERS)
    )
    tid = tenant["id"]
    if verified:
        ver = get_success_data(
            api.create_verification(create_verification_payload(tid, document_ref=f"doc-{tid[:8]}"),
                                    make_tenant_headers(tid))
        )
        get_success_data(api.transition_verification(ver["id"], {"to_status": "APPROVED"}, REVIEWER))
        tenant = get_success_data(api.get_tenant(tid, REVIEWER))
    return tenant


def register_tenant_with_pending_verification(api, tenant_type="TRAVEL_NURSE"):
    """Return (tenant, verification) with one PENDING (un-adjudicated) doc."""
    tenant = get_success_data(api.create_tenant(create_tenant_payload(tenant_type=tenant_type), ANONYMOUS_HEADERS))
    tid = tenant["id"]
    ver = get_success_data(
        api.create_verification(create_verification_payload(tid), make_tenant_headers(tid))
    )
    return tenant, ver


def register_tenant_with_rejected_verification(api):
    """Return (tenant, verification) with one REJECTED doc."""
    tenant, ver = register_tenant_with_pending_verification(api)
    ver = get_success_data(
        api.transition_verification(ver["id"], {"to_status": "REJECTED", "reviewer_note": "blurry"}, REVIEWER)
    )
    return tenant, ver


def create_unit(api, host_id, listed=True, **overrides):
    """Create a unit owned by host_id; optionally transition DRAFT -> LISTED."""
    unit = get_success_data(
        api.create_unit(create_unit_payload(host_id, **overrides), make_host_headers(host_id))
    )
    if listed:
        unit = get_success_data(
            api.transition_unit(unit["id"], {"to_status": "LISTED"}, make_host_headers(host_id))
        )
    return unit


def request_booking(api, unit_id, tenant_id, start_date, end_date):
    """Create a REQUESTED booking as the owning tenant."""
    return get_success_data(
        api.create_booking(
            create_booking_payload(unit_id, tenant_id, start_date, end_date),
            make_tenant_headers(tenant_id),
        )
    )


def confirm_booking(api, booking_id, host_id):
    return get_success_data(
        api.transition_booking(booking_id, {"to_status": "CONFIRMED"}, make_host_headers(host_id))
    )


def activate_booking(api, booking_id):
    return get_success_data(
        api.transition_booking(booking_id, {"to_status": "ACTIVE"}, ADMIN)
    )


def complete_booking(api, booking_id):
    return get_success_data(
        api.transition_booking(booking_id, {"to_status": "COMPLETED"}, ADMIN)
    )


# ---- Child-resource discovery (cascade-created) ----------------------------

def get_deposit_for_booking(api, booking_id):
    data, _ = _list(api.list_deposits, {"booking_id": booking_id})
    return data[0] if data else None


def get_payout_for_booking(api, booking_id):
    data, _ = _list(api.list_payouts, {"booking_id": booking_id})
    return data[0] if data else None


def get_tax_for_booking(api, booking_id):
    data, _ = _list(api.list_tax_assessments, {"booking_id": booking_id})
    return data[0] if data else None


def get_turnover_for_booking(api, booking_id):
    data, _ = _list(api.list_turnovers, {"booking_id": booking_id})
    return data[0] if data else None


def count_for_booking(api, list_method, booking_id):
    _, meta = _list(list_method, {"booking_id": booking_id})
    return meta["total_count"]


def _list(list_method, params):
    from prd_bench_local_runner.testing import validate_paginated
    resp = list_method(ADMIN, params=params)
    return validate_paginated(resp)


# ---- Composite scenarios ---------------------------------------------------

def setup_confirmed_booking(api, *, unit_overrides=None, start_date="2026-06-01",
                            end_date="2026-07-01", tenant_type="TRAVEL_NURSE"):
    """Verified host + verified tenant + LISTED unit + CONFIRMED booking.

    Returns dict: host, tenant, unit, booking (the confirmed booking as returned
    by the confirm transition). Confirmation has spawned Deposit + Payout +
    TaxAssessment per PRD §3.4.
    """
    unit_overrides = dict(unit_overrides or {})
    unit_overrides.setdefault("cleaning_included", True)
    host = register_host(api, verify_payout=True)
    tenant = register_tenant(api, verified=True, tenant_type=tenant_type)
    unit = create_unit(api, host["id"], listed=True, **unit_overrides)
    booking = request_booking(api, unit["id"], tenant["id"], start_date, end_date)
    booking = confirm_booking(api, booking["id"], host["id"])
    return {"host": host, "tenant": tenant, "unit": unit, "booking": booking}


def setup_active_booking(api, *, unit_overrides=None, start_date="2026-06-01",
                         end_date="2026-07-01", activate_clock="2026-06-15"):
    """Extend setup_confirmed_booking to ACTIVE. activate_clock must be >=
    start_date. Returns the same dict with booking now ACTIVE."""
    ctx = setup_confirmed_booking(api, unit_overrides=unit_overrides,
                                  start_date=start_date, end_date=end_date)
    if activate_clock:
        set_clock(api, f"{activate_clock}T00:00:00Z")
    ctx["booking"] = activate_booking(api, ctx["booking"]["id"])
    return ctx


def setup_completed_booking(api, *, unit_overrides=None, start_date="2026-06-01",
                            end_date="2026-07-01", activate_clock="2026-06-15",
                            complete_clock="2026-07-01"):
    """Full lifecycle through COMPLETED (rent finalized, payout finalized,
    turnover scheduled). Returns the dict with booking now COMPLETED."""
    ctx = setup_active_booking(api, unit_overrides=unit_overrides,
                               start_date=start_date, end_date=end_date,
                               activate_clock=activate_clock)
    if complete_clock:
        set_clock(api, f"{complete_clock}T00:00:00Z")
    ctx["booking"] = complete_booking(api, ctx["booking"]["id"])
    return ctx
