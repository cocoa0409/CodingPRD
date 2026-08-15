"""Composite setup helpers for the rent-collection domain.

Every helper builds its preconditions from scratch using only PRD-declared
endpoints: the test harness restarts the server before every test, so nothing
is carried over between tests. Setup calls use get_success_data() so failures
surface as clear "Setup failed" errors rather than confusing assertions.
"""
from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CLOCK_DEFAULT_DATE
from .factories import (
    create_charge_payload,
    create_lease_payload,
    create_notice_payload,
    create_payment_payload,
    create_payment_plan_payload,
    create_property_payload,
    create_tenant_payload,
)
from .test_users import TEST_USERS, make_tenant_headers

PM = TEST_USERS["property_manager_headers"]
AGENT = TEST_USERS["leasing_agent_headers"]
OPS = TEST_USERS["system_ops_headers"]


# ---------------------------------------------------------------------------
# Tier 1: basic hierarchy and state progression
# ---------------------------------------------------------------------------


def create_property(**overrides) -> Dict[str, Any]:
    """Create a property with the canonical policy constants. Returns Property."""
    return get_success_data(api_client.create_property(create_property_payload(**overrides), PM))


def create_tenant(email: str = "terry@example.com", **overrides) -> Dict[str, Any]:
    """Register a tenant. Returns Tenant."""
    return get_success_data(
        api_client.create_tenant(create_tenant_payload(email=email, **overrides), AGENT)
    )


def create_lease(
    property_id: str,
    tenant_id: str,
    unit_label: str = "101",
    activate: bool = False,
    **overrides,
) -> Dict[str, Any]:
    """Create a lease (DRAFT); optionally activate it. Returns the latest Lease body."""
    lease = get_success_data(
        api_client.create_lease(create_lease_payload(property_id, tenant_id, unit_label=unit_label, **overrides), PM)
    )
    if activate:
        lease = get_success_data(
            api_client.transition_lease(lease["id"], {"action": "ACTIVATE"}, PM)
        )
    return lease


def setup_property_tenant_lease(
    activate: bool = True,
    unit_label: str = "101",
    property_overrides: Optional[Dict[str, Any]] = None,
    lease_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Most common setup: property + tenant + one lease.

    Returns {"property": ..., "tenant": ..., "lease": ...}.
    """
    prop = create_property(**(property_overrides or {}))
    tenant = create_tenant()
    lease = create_lease(prop["id"], tenant["id"], unit_label=unit_label, activate=activate, **(lease_overrides or {}))
    return {"property": prop, "tenant": tenant, "lease": lease}


def add_charge(
    lease_id: str,
    headers=None,
    **overrides,
) -> Dict[str, Any]:
    """Manually create a charge on a lease. Returns LedgerCharge."""
    return get_success_data(
        api_client.create_charge(lease_id, create_charge_payload(**overrides), headers or AGENT)
    )


def get_lease(lease_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_lease(lease_id, PM))


def lease_version(lease_id: str) -> int:
    return get_lease(lease_id)["version"]


# ---------------------------------------------------------------------------
# Tier 2: notices, plans, payments
# ---------------------------------------------------------------------------


def create_notice(lease_id: str, charge_ids: List[str], headers=None) -> Dict[str, Any]:
    """Create a DRAFT notice, reading the current lease version first."""
    lv = lease_version(lease_id)
    return get_success_data(
        api_client.create_notice(create_notice_payload(lease_id, charge_ids, lv), headers or PM)
    )


def issue_notice(notice_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.transition_notice(notice_id, {"action": "ISSUE"}, PM))


def serve_notice(notice_id: str, service_method: str, served_date: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.transition_notice(
            notice_id,
            {"action": "SERVE", "service_method": service_method, "served_date": served_date},
            PM,
        )
    )


def create_plan(
    lease_id: str,
    charge_ids: List[str],
    headers=None,
    **overrides,
) -> Dict[str, Any]:
    """Create a DRAFT payment plan, reading the current lease version first."""
    lv = lease_version(lease_id)
    return get_success_data(
        api_client.create_payment_plan(
            create_payment_plan_payload(lease_id, charge_ids, lv, **overrides), headers or AGENT
        )
    )


def approve_plan(plan_id: str, headers=None) -> Dict[str, Any]:
    return get_success_data(
        api_client.transition_payment_plan(plan_id, {"action": "APPROVE"}, headers or PM)
    )


def record_payment(lease_id: str, tenant_id: str, headers=None, **overrides) -> Dict[str, Any]:
    """Record a PENDING payment. Returns Payment."""
    return get_success_data(
        api_client.create_payment(create_payment_payload(lease_id, tenant_id, **overrides), headers or AGENT)
    )


def post_payment(payment_id: str, headers=None) -> Dict[str, Any]:
    return get_success_data(
        api_client.transition_payment(payment_id, {"action": "POST"}, headers or AGENT)
    )


def return_payment(payment_id: str, nsf_fee_cents: int, reason_code: str = "NSF", headers=None) -> Dict[str, Any]:
    return get_success_data(
        api_client.transition_payment(
            payment_id,
            {"action": "RETURN", "reason_code": reason_code, "nsf_fee_cents": nsf_fee_cents},
            headers or AGENT,
        )
    )


def record_and_post_payment(lease_id: str, tenant_id: str, headers=None, **overrides) -> Dict[str, Any]:
    """Record a payment and post it (running the waterfall). Returns POSTED Payment."""
    payment = record_payment(lease_id, tenant_id, headers=headers, **overrides)
    return post_payment(payment["id"], headers=headers)


# ---------------------------------------------------------------------------
# Tier 3: lifecycle shortcuts
# ---------------------------------------------------------------------------


def move_out_lease(lease_id: str, move_out_date: str) -> Dict[str, Any]:
    """ACTIVE -> ENDED via MOVE_OUT (runs the end-of-term cascade). Returns Lease."""
    return get_success_data(
        api_client.transition_lease(
            lease_id, {"action": "MOVE_OUT", "move_out_date": move_out_date}, PM
        )
    )


def setup_ended_lease_with_referral(
    charge_amount_cents: int = 15000,
    move_out_date: str = "2026-08-20",
    charge_overrides: Optional[Dict[str, Any]] = None,
    property_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Active lease with one unpaid damage charge, moved out; the cascade has
    created a PENDING collections referral. Returns the context dict with the
    referral list attached."""
    ctx = setup_property_tenant_lease(property_overrides=property_overrides)
    charge = add_charge(
        ctx["lease"]["id"],
        kind="DAMAGE_FEE",
        amount_cents=charge_amount_cents,
        **(charge_overrides or {}),
    )
    set_clock(f"{move_out_date}T00:00:00Z")
    lease = move_out_lease(ctx["lease"]["id"], move_out_date)
    referrals = list_referrals(lease["id"])
    ctx.update({"lease": lease, "charge": charge, "referrals": referrals})
    return ctx


def file_dispute(lease_id: str, charge_id: str, tenant_id: str, reason: str = "contested") -> Dict[str, Any]:
    """Tenant files a dispute on their own lease (entity-backed identity)."""
    from .factories import create_dispute_payload

    return get_success_data(
        api_client.create_dispute(
            create_dispute_payload(lease_id, charge_id, tenant_id, reason=reason),
            make_tenant_headers(tenant_id),
        )
    )


def resolve_dispute(dispute_id: str, outcome: str = "UPHELD", **overrides) -> Dict[str, Any]:
    payload = {"action": "RESOLVE", "outcome": outcome}
    payload.update(overrides)
    return get_success_data(api_client.transition_dispute(dispute_id, payload, PM))


def reopen_dispute(dispute_id: str, tenant_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.transition_dispute(dispute_id, {"action": "REOPEN"}, make_tenant_headers(tenant_id))
    )


# ---------------------------------------------------------------------------
# Tier 4: sweep and clock
# ---------------------------------------------------------------------------


def set_clock(to_iso8601: str) -> Dict[str, Any]:
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, OPS))


def run_sweep() -> Dict[str, Any]:
    return get_success_data(api_client.run_delinquency_sweep(OPS))


# ---------------------------------------------------------------------------
# Tier 5: collection readers
# ---------------------------------------------------------------------------


def list_charges(lease_id: str, params: Optional[Dict] = None) -> List[Dict[str, Any]]:
    return get_success_data(api_client.list_charges(lease_id, PM, params=params))


def list_notices(lease_id: str, params: Optional[Dict] = None) -> List[Dict[str, Any]]:
    return get_success_data(api_client.list_notices(lease_id, PM, params=params))


def list_plans(lease_id: str, params: Optional[Dict] = None) -> List[Dict[str, Any]]:
    return get_success_data(api_client.list_payment_plans(lease_id, PM, params=params))


def list_referrals(lease_id: str, params: Optional[Dict] = None) -> List[Dict[str, Any]]:
    return get_success_data(api_client.list_referrals(lease_id, PM, params=params))


def list_allocations(params: Optional[Dict] = None) -> List[Dict[str, Any]]:
    return get_success_data(api_client.list_allocations(PM, params=params))


def get_plan(plan_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_payment_plan(plan_id, PM))


def get_payment(payment_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_payment(payment_id, PM))


def get_ledger(lease_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_lease_ledger(lease_id, PM))
