"""Composite setup helpers.

Every test starts against an empty database (the runner restarts the server
before each test), so every fixture builds its preconditions from scratch using
only PRD-declared endpoints. All setup calls use the lenient get_success_data()
validator so a broken precondition surfaces as a clear "Setup failed".

Identity threading: after a fixture creates an entity-backed Tenant/Landlord,
ownership-gated calls use make_tenant_headers(tenant_id) / make_landlord_headers(
landlord_id) with the real entity id — never a shared constant.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import (
    TEST_USERS, make_tenant_headers, make_landlord_headers,
    make_analyst_headers, make_officer_headers,
    ANALYST_1, OFFICER_1,
)
from .factories import (
    create_tenant_payload, create_landlord_payload, create_plan_payload,
    create_enrollment_payload, create_lease_payload, create_rent_payment_payload,
    create_dispute_payload,
)

ADMIN = TEST_USERS["admin_headers"]
ANALYST = TEST_USERS["analyst_headers"]
OFFICER = TEST_USERS["officer_headers"]


# --------------------------------------------------------------------------
# Primitive helpers
# --------------------------------------------------------------------------
def set_clock(api, iso: str):
    """Advance the logical clock (PlatformAdmin only)."""
    return get_success_data(api.set_clock(ADMIN, {"to_iso8601": iso}))


def reset_clock_default(api):
    return set_clock(api, "2026-07-01T00:00:00Z")


def create_tenant(api, **overrides) -> dict:
    return get_success_data(api.create_tenant(ADMIN, create_tenant_payload(**overrides)))


def create_landlord(api, **overrides) -> dict:
    return get_success_data(api.create_landlord(ADMIN, create_landlord_payload(**overrides)))


def create_plan(api, **overrides) -> dict:
    return get_success_data(api.create_plan(ADMIN, create_plan_payload(**overrides)))


def create_enrollment(api, tenant_id, plan_id) -> dict:
    th = make_tenant_headers(tenant_id)
    return get_success_data(api.create_enrollment(th, create_enrollment_payload(tenant_id, plan_id)))


def subscription_invoice_for(api, tenant_id, enrollment_id) -> dict:
    th = make_tenant_headers(tenant_id)
    invs = get_success_data(api.list_invoices(th, params={"enrollment_id": enrollment_id, "kind": "SUBSCRIPTION"}))
    assert invs, "expected a SUBSCRIPTION invoice to have been raised at enrollment"
    return invs[0]


def back_report_invoice_for(api, tenant_id, br_id) -> dict:
    th = make_tenant_headers(tenant_id)
    invs = get_success_data(api.list_invoices(th, params={"back_report_request_id": br_id, "kind": "BACK_REPORT"}))
    assert invs, "expected a BACK_REPORT invoice to have been raised"
    return invs[0]


def pay_invoice(api, tenant_id, invoice_id) -> dict:
    th = make_tenant_headers(tenant_id)
    return get_success_data(api.pay_invoice(th, invoice_id))


def activate_enrollment(api, tenant_id, plan_id) -> dict:
    """Enroll + pay the first SUBSCRIPTION invoice -> enrollment ACTIVE."""
    en = create_enrollment(api, tenant_id, plan_id)
    inv = subscription_invoice_for(api, tenant_id, en["id"])
    pay_invoice(api, tenant_id, inv["id"])
    return get_success_data(api.get_enrollment(make_tenant_headers(tenant_id), en["id"]))


def create_verified_lease(api, tenant_id, landlord_id, **overrides) -> dict:
    """Create a lease then landlord-verify it -> VERIFIED (version advanced)."""
    th = make_tenant_headers(tenant_id)
    lh = make_landlord_headers(landlord_id)
    lease = get_success_data(api.create_lease(th, create_lease_payload(tenant_id, landlord_id, **overrides)))
    return get_success_data(api.verify_lease(lh, lease["id"], {"decision": "VERIFIED"}))


def current_lease_version(api, landlord_id, lease_id) -> int:
    lh = make_landlord_headers(landlord_id)
    return get_success_data(api.get_lease(lh, lease_id))["version"]


def record_payment(api, landlord_id, lease_id, **overrides) -> dict:
    """Record a rent payment, resolving the current lease version for the OCC guard."""
    lh = make_landlord_headers(landlord_id)
    version = current_lease_version(api, landlord_id, lease_id)
    payload = create_rent_payment_payload(lease_id, version, **overrides)
    return get_success_data(api.create_rent_payment(lh, payload))


def report_payment(api, payment_id, analyst_headers=None) -> dict:
    return get_success_data(api.report_rent_payment(analyst_headers or ANALYST, payment_id))


# --------------------------------------------------------------------------
# Tier 2/3: composite scenarios
# --------------------------------------------------------------------------
def setup_active_tenant(api, plan_overrides=None, tenant_overrides=None):
    """Clock at default; a plan, a landlord, and a tenant with an ACTIVE
    enrollment. Returns dict(plan, tenant, landlord, enrollment)."""
    reset_clock_default(api)
    plan = create_plan(api, **(plan_overrides or {}))
    landlord = create_landlord(api)
    tenant = create_tenant(api, **(tenant_overrides or {}))
    enrollment = activate_enrollment(api, tenant["id"], plan["id"])
    return {"plan": plan, "tenant": tenant, "landlord": landlord, "enrollment": enrollment}


def setup_reported_item(api, paid_date="2026-06-05T00:00:00Z", due_date="2026-06-05T00:00:00Z",
                        period_month="2026-06", plan_overrides=None, property_address="1 Furnish St",
                        amount_paid_cents=120000):
    """Full chain to a single REPORTED tradeline:
    active tenant -> verified lease -> recorded payment -> furnished ReportedItem.
    Returns dict(plan, tenant, landlord, enrollment, lease, payment, item)."""
    ctx = setup_active_tenant(api, plan_overrides=plan_overrides)
    lease = create_verified_lease(api, ctx["tenant"]["id"], ctx["landlord"]["id"],
                                  property_address=property_address)
    payment = record_payment(api, ctx["landlord"]["id"], lease["id"],
                             period_month=period_month, due_date=due_date,
                             paid_date=paid_date, amount_paid_cents=amount_paid_cents)
    item = report_payment(api, payment["id"])
    ctx.update({"lease": lease, "payment": payment, "item": item})
    return ctx


def setup_disputed_item(api, reason_code="PAID_ON_TIME", **kwargs):
    """A REPORTED item that has been disputed by the tenant (item now DISPUTED,
    dispute OPEN). Returns setup_reported_item ctx plus 'dispute'."""
    ctx = setup_reported_item(api, **kwargs)
    th = make_tenant_headers(ctx["tenant"]["id"])
    dispute = get_success_data(api.create_dispute(th, create_dispute_payload(ctx["item"]["id"], reason_code)))
    ctx["dispute"] = dispute
    return ctx


def setup_investigating_dispute(api, analyst_user_id=ANALYST_1, **kwargs):
    """A dispute in INVESTIGATING (opened by the given analyst id). Returns ctx
    with 'dispute' in INVESTIGATING and 'analyst_user_id'."""
    ctx = setup_disputed_item(api, **kwargs)
    ah = make_analyst_headers(analyst_user_id)
    dispute = get_success_data(api.investigate_dispute(ah, ctx["dispute"]["id"]))
    ctx["dispute"] = dispute
    ctx["analyst_user_id"] = analyst_user_id
    return ctx


def setup_active_enrollment_for_cancel(api, cancel_clock="2026-07-11T00:00:00Z",
                                       monthly_fee_cents=1499):
    """ACTIVE enrollment whose SUBSCRIPTION invoice is PAID, with the clock then
    advanced to `cancel_clock` (default day 10 of a 31-day July period). Returns
    dict(plan, tenant, enrollment). No lease is created."""
    reset_clock_default(api)
    plan = create_plan(api, monthly_fee_cents=monthly_fee_cents)
    tenant = create_tenant(api)
    enrollment = activate_enrollment(api, tenant["id"], plan["id"])
    set_clock(api, cancel_clock)
    return {"plan": plan, "tenant": tenant, "enrollment": enrollment}


def setup_pending_backreport(api, requested_months=None, included_months=0,
                             recorded_month="2026-05"):
    """ACTIVE enrollment, VERIFIED lease, one RECORDED payment for `recorded_month`,
    and a PENDING back-report over `requested_months` with a DUE BACK_REPORT fee
    invoice. Returns dict with tenant, lease, payment, back_report, fee_invoice."""
    requested_months = requested_months or [recorded_month]
    ctx = setup_active_tenant(api, plan_overrides={"back_reporting_included_months": included_months})
    lease = create_verified_lease(api, ctx["tenant"]["id"], ctx["landlord"]["id"],
                                  property_address="4 BackReport Way")
    payment = record_payment(api, ctx["landlord"]["id"], lease["id"],
                             period_month=recorded_month,
                             due_date=f"{recorded_month}-05T00:00:00Z",
                             paid_date=f"{recorded_month}-05T00:00:00Z")
    th = make_tenant_headers(ctx["tenant"]["id"])
    from .factories import create_back_report_payload
    br = get_success_data(api.create_back_report_request(
        th, create_back_report_payload(lease["id"], requested_months)))
    fee_invoice = back_report_invoice_for(api, ctx["tenant"]["id"], br["id"])
    ctx.update({"lease": lease, "payment": payment, "back_report": br, "fee_invoice": fee_invoice})
    return ctx
