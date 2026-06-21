"""Composite setup helpers for multi-step test prerequisites (Rent-To-Own Home).

The test harness restarts the server (empty DB) before every test, so every fixture
builds its preconditions from scratch using only PRD-declared endpoints.

Identity threading: Landlord and Tenant are entity-backed roles (§2.1). After a
fixture creates a Landlord/Tenant entity, every ownership-gated call uses
make_landlord_headers(landlord["id"]) / make_tenant_headers(tenant["id"]) — never the
shared TEST_USERS fallback — so ownership checks see X-User-ID == the owning entity id.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_landlord_payload,
    create_tenant_payload,
    create_property_payload,
    create_agreement_payload,
    create_rent_payment_payload,
    create_maintenance_ticket_payload,
    create_option_exercise_payload,
    create_mortgage_payload,
)
from .test_users import make_landlord_headers, make_tenant_headers, make_escrow_headers


# ─── Party / Property primitives ──────────────────────────────────────────────

def create_landlord(**overrides):
    """Register a Landlord. Returns the entity. Uses a fresh self-owned X-User-ID."""
    res = api_client.create_landlord(
        create_landlord_payload(**overrides),
        make_landlord_headers("bootstrap-landlord"),
    )
    return get_success_data(res)


def create_tenant(**overrides):
    """Register a Tenant. Returns the entity."""
    res = api_client.create_tenant(
        create_tenant_payload(**overrides),
        make_tenant_headers("bootstrap-tenant"),
    )
    return get_success_data(res)


def create_property(landlord, **overrides):
    """List a Property owned by `landlord`. Ownership-gated on landlord_id (§3.1)."""
    res = api_client.create_property(
        create_property_payload(landlord["id"], **overrides),
        make_landlord_headers(landlord["id"]),
    )
    return get_success_data(res)


def create_parties_and_property(landlord_overrides=None, tenant_overrides=None,
                                property_overrides=None):
    """Bootstrap a Landlord, a Tenant, and an AVAILABLE Property.
    Returns (landlord, tenant, property)."""
    landlord = create_landlord(**(landlord_overrides or {}))
    tenant = create_tenant(**(tenant_overrides or {}))
    prop = create_property(landlord, **(property_overrides or {}))
    return landlord, tenant, prop


# ─── Tier 1: Agreement state progression ──────────────────────────────────────

def create_draft_agreement(landlord=None, tenant=None, prop=None, **agreement_overrides):
    """Create a DRAFT Agreement (default parties/property if not supplied).
    Returns (landlord, tenant, property, agreement)."""
    if landlord is None or tenant is None or prop is None:
        landlord, tenant, prop = create_parties_and_property()
    res = api_client.create_agreement(
        create_agreement_payload(prop["id"], tenant["id"], **agreement_overrides),
        make_landlord_headers(landlord["id"]),
    )
    agreement = get_success_data(res)
    return landlord, tenant, prop, agreement


def activate_agreement(landlord, prop, agreement):
    """Activate a DRAFT agreement using the property's current version.
    Returns the activated agreement."""
    prop_now = get_success_data(
        api_client.get_property(prop["id"], make_landlord_headers(landlord["id"]))
    )
    res = api_client.activate_agreement(
        agreement["id"],
        {"expected_property_version": prop_now["version"]},
        make_landlord_headers(landlord["id"]),
    )
    return get_success_data(res)


def create_active_agreement(landlord=None, tenant=None, prop=None, **agreement_overrides):
    """Create + activate an Agreement. Returns (landlord, tenant, property, agreement)."""
    landlord, tenant, prop, agreement = create_draft_agreement(
        landlord, tenant, prop, **agreement_overrides
    )
    agreement = activate_agreement(landlord, prop, agreement)
    return landlord, tenant, prop, agreement


# ─── Tier 2: RentPayment helpers ──────────────────────────────────────────────

def schedule_payment(landlord, agreement, period_index, due_date, **overrides):
    """Schedule one RentPayment row (Landlord-only, §3.3). Returns the payment."""
    res = api_client.create_rent_payment(
        agreement["id"],
        create_rent_payment_payload(period_index, due_date, **overrides),
        make_landlord_headers(landlord["id"]),
    )
    return get_success_data(res)


def record_payment(tenant, payment, paid_at):
    """Tenant records a payment (§3.4). Returns the updated payment."""
    res = api_client.record_rent_payment(
        payment["id"], {"paid_at": paid_at}, make_tenant_headers(tenant["id"])
    )
    return get_success_data(res)


def forfeit_payment(landlord, payment):
    """Landlord forfeits a payment (§3.4). Returns the updated payment."""
    res = api_client.forfeit_rent_payment(
        payment["id"], make_landlord_headers(landlord["id"])
    )
    return get_success_data(res)


def cure_payment(landlord, payment):
    """Landlord cures a LATE payment (§3.4). Returns the updated payment."""
    res = api_client.cure_rent_payment(
        payment["id"], make_landlord_headers(landlord["id"])
    )
    return get_success_data(res)


def setup_agreement_with_paid_payments(num_paid, monthly_payment_cents=200000,
                                       credit_pct=0.30, **agreement_overrides):
    """Active agreement with `num_paid` on-time PAID RentPayments (one per month
    Feb..). Returns (landlord, tenant, property, agreement, [payments])."""
    agreement_overrides.setdefault("monthly_payment_cents", monthly_payment_cents)
    agreement_overrides.setdefault("credit_pct", credit_pct)
    landlord, tenant, prop, agreement = create_active_agreement(**agreement_overrides)
    payments = []
    for i in range(1, num_paid + 1):
        due = f"2026-{i + 1:02d}-01T00:00:00Z"
        paid = f"2026-{i + 1:02d}-03T00:00:00Z"  # 2 days after due → on time
        pay = schedule_payment(landlord, agreement, i, due)
        pay = record_payment(tenant, pay, paid)
        payments.append(pay)
    return landlord, tenant, prop, agreement, payments


def setup_agreement_with_forfeited_payments(num_forfeited, **agreement_overrides):
    """Active agreement with `num_forfeited` FORFEITED RentPayments
    (missed_payment_count == num_forfeited). Returns
    (landlord, tenant, property, agreement, [payments])."""
    landlord, tenant, prop, agreement = create_active_agreement(**agreement_overrides)
    payments = []
    for i in range(1, num_forfeited + 1):
        due = f"2026-{i + 1:02d}-01T00:00:00Z"
        pay = schedule_payment(landlord, agreement, i, due)
        pay = forfeit_payment(landlord, pay)
        payments.append(pay)
    return landlord, tenant, prop, agreement, payments


def setup_agreement_with_late_payment(due_date="2026-02-01T00:00:00Z",
                                      paid_at="2026-02-20T00:00:00Z",
                                      period_index=1, **agreement_overrides):
    """Active agreement with one RentPayment recorded LATE (paid past the grace
    stretch). Returns (landlord, tenant, property, agreement, payment)."""
    landlord, tenant, prop, agreement = create_active_agreement(**agreement_overrides)
    pay = schedule_payment(landlord, agreement, period_index, due_date)
    pay = record_payment(tenant, pay, paid_at)
    return landlord, tenant, prop, agreement, pay


def setup_two_drafts_on_one_property(**agreement_overrides):
    """One AVAILABLE Property with two DRAFT agreements (A1, A2). A1 is then
    activated (property becomes UNDER_AGREEMENT). Returns
    (landlord, tenant, property, agreement1, agreement2, property_version_before_a1).

    property_version_before_a1 is the property's version observed BEFORE A1's
    activation (i.e. the stale value); the caller can also re-GET the property for
    the fresh value after A1 activated.
    """
    landlord, tenant, prop = create_parties_and_property()
    ver_before = prop["version"]
    a1 = get_success_data(api_client.create_agreement(
        create_agreement_payload(prop["id"], tenant["id"], **agreement_overrides),
        make_landlord_headers(landlord["id"]),
    ))
    a2 = get_success_data(api_client.create_agreement(
        create_agreement_payload(prop["id"], tenant["id"], **agreement_overrides),
        make_landlord_headers(landlord["id"]),
    ))
    a1 = api_client.activate_agreement(
        a1["id"], {"expected_property_version": ver_before},
        make_landlord_headers(landlord["id"]),
    )
    a1 = get_success_data(a1)
    return landlord, tenant, prop, a1, a2, ver_before


# ─── Tier 3: Maintenance helpers ──────────────────────────────────────────────

def file_ticket(tenant, agreement, **overrides):
    """Tenant files a MaintenanceTicket on their agreement (§3.5). Returns the ticket."""
    res = api_client.create_maintenance_ticket(
        agreement["id"],
        create_maintenance_ticket_payload(**overrides),
        make_tenant_headers(tenant["id"]),
    )
    return get_success_data(res)


def approve_ticket(landlord, ticket):
    res = api_client.approve_maintenance_ticket(
        ticket["id"], make_landlord_headers(landlord["id"])
    )
    return get_success_data(res)


def resolve_ticket(landlord, ticket, actual_cost_cents):
    res = api_client.resolve_maintenance_ticket(
        ticket["id"], {"actual_cost_cents": actual_cost_cents},
        make_landlord_headers(landlord["id"]),
    )
    return get_success_data(res)


def setup_approved_ticket(estimated_cost_cents=80000, maintenance_threshold_cents=50000,
                          **agreement_overrides):
    """Active agreement + one APPROVED MaintenanceTicket.
    Returns (landlord, tenant, property, agreement, ticket)."""
    agreement_overrides.setdefault("maintenance_threshold_cents", maintenance_threshold_cents)
    landlord, tenant, prop, agreement = create_active_agreement(**agreement_overrides)
    ticket = file_ticket(tenant, agreement, estimated_cost_cents=estimated_cost_cents)
    ticket = approve_ticket(landlord, ticket)
    return landlord, tenant, prop, agreement, ticket


# ─── Tier 4: Option exercise + mortgage lifecycle ─────────────────────────────

def set_clock(landlord, to_iso8601):
    """Set the server clock (any authenticated role, §2.10)."""
    return get_success_data(
        api_client.set_clock(to_iso8601, make_landlord_headers(landlord["id"]))
    )


def exercise_option(tenant, agreement, exercised_at):
    """Tenant exercises the option (§3.6). Returns the SETTLED OptionExercise."""
    res = api_client.create_option_exercise(
        agreement["id"],
        create_option_exercise_payload(exercised_at),
        make_tenant_headers(tenant["id"]),
    )
    return get_success_data(res)


def setup_exercised_agreement(num_paid=3, monthly_payment_cents=200000, credit_pct=0.30,
                              exercised_at="2026-06-01T00:00:00Z",
                              clock="2026-06-01T00:00:00Z", **agreement_overrides):
    """Active agreement with `num_paid` PAID payments, clock advanced before deadline,
    option exercised → Agreement EXERCISED + SETTLED OptionExercise.
    Returns (landlord, tenant, property, agreement, exercise)."""
    landlord, tenant, prop, agreement, _ = setup_agreement_with_paid_payments(
        num_paid, monthly_payment_cents=monthly_payment_cents,
        credit_pct=credit_pct, **agreement_overrides
    )
    set_clock(landlord, clock)
    exercise = exercise_option(tenant, agreement, exercised_at)
    return landlord, tenant, prop, agreement, exercise


def convert_to_mortgage(agreement, exercise, **overrides):
    """EscrowAgent converts an EXERCISED agreement into a Mortgage (§3.7).
    Returns the Mortgage."""
    res = api_client.create_mortgage(
        agreement["id"],
        create_mortgage_payload(exercise["id"], **overrides),
        make_escrow_headers(),
    )
    return get_success_data(res)


# ─── Read-back convenience ────────────────────────────────────────────────────

def get_agreement(landlord, agreement_id):
    return get_success_data(
        api_client.get_agreement(agreement_id, make_landlord_headers(landlord["id"]))
    )


def get_property_state(landlord, property_id):
    return get_success_data(
        api_client.get_property(property_id, make_landlord_headers(landlord["id"]))
    )
