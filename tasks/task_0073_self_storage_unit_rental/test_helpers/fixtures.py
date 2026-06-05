"""Composite setup helpers for multi-step test prerequisites.

Every fixture builds its preconditions from scratch (the server DB is empty before
each test). Fixtures use get_success_data() (lenient) so setup failures surface as
clear "Setup failed" errors. Tenant ownership is threaded via make_tenant_headers(id).

The dominant chain in this domain is:
  facility -> unit -> tenant -> set clock -> create lease -> activate
then optionally: advance clock -> billing-cycle -> open auction -> file-lien -> schedule.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_facility_payload,
    create_unit_payload,
    create_tenant_payload,
    create_lease_payload,
    create_payment_payload,
    create_insurance_policy_payload,
    create_auction_proceeding_payload,
    create_transfer_order_payload,
)
from .test_users import TEST_USERS, make_tenant_headers

FM = TEST_USERS["facility_manager_headers"]
LIEN = TEST_USERS["lien_administrator_headers"]


# ─── Low-level builders ────────────────────────────────────────────────

def set_clock(to_iso8601: str):
    """Advance the server logical clock (PRD §2.9)."""
    return get_success_data(api_client.set_clock(to_iso8601, FM))


def create_facility(**overrides):
    return get_success_data(api_client.create_facility(create_facility_payload(**overrides), FM))


def create_unit(facility_id, **overrides):
    return get_success_data(api_client.create_unit(create_unit_payload(facility_id, **overrides), FM))


def create_tenant(**overrides):
    return get_success_data(api_client.create_tenant(create_tenant_payload(**overrides), FM))


def create_lease(unit_id, tenant_id, **overrides):
    return get_success_data(api_client.create_lease(create_lease_payload(unit_id, tenant_id, **overrides), FM))


def create_insurance_policy(lease_id, **overrides):
    return get_success_data(
        api_client.create_insurance_policy(create_insurance_policy_payload(lease_id, **overrides), FM)
    )


def pay(lease_id, amount_cents, tenant_id):
    """Tenant pays their own lease (ownership-threaded)."""
    return get_success_data(
        api_client.create_payment(create_payment_payload(lease_id, amount_cents),
                                  make_tenant_headers(tenant_id))
    )


# ─── Tier 1/2: Base scenario (facility + unit + tenant + lease) ─────────

def setup_base(unit_overrides=None, lease_overrides=None, facility_overrides=None,
               tenant_overrides=None, start_date="2026-04-01T00:00:00Z"):
    """Create facility, unit, tenant, set clock to start_date, create PENDING lease.

    Returns dict(facility, unit, tenant, lease). Climate flag / rate / insurance are
    controlled through the *_overrides dicts.
    """
    facility = create_facility(**(facility_overrides or {}))
    unit = create_unit(facility["id"], **(unit_overrides or {}))
    tenant = create_tenant(**(tenant_overrides or {}))
    set_clock(start_date)
    lov = dict(start_date=start_date)
    lov.update(lease_overrides or {})
    lease = create_lease(unit["id"], tenant["id"], **lov)
    return {"facility": facility, "unit": unit, "tenant": tenant, "lease": lease}


def setup_activated(unit_overrides=None, lease_overrides=None, facility_overrides=None,
                    tenant_overrides=None, start_date="2026-04-01T00:00:00Z",
                    with_insurance=None):
    """Base scenario + lease activation. Returns dict with the activated lease.

    with_insurance: a coverage_tier string (e.g. "STANDARD") to bind an ACTIVE policy
    before activation; required when lease_overrides sets insurance_required=True.
    Adds 'policy' to the returned dict when a policy is created.
    """
    ctx = setup_base(unit_overrides, lease_overrides, facility_overrides,
                     tenant_overrides, start_date)
    if with_insurance is not None:
        ctx["policy"] = create_insurance_policy(
            ctx["lease"]["id"], coverage_tier=with_insurance, coverage_start=start_date
        )
    ctx["lease"] = get_success_data(api_client.activate_lease(ctx["lease"]["id"], FM))
    return ctx


# ─── Tier 3: Delinquency progression ───────────────────────────────────

def setup_delinquent_past_90(climate=True, rate=10000, with_insurance=None,
                             past_due_date="2026-07-02T00:00:00Z",
                             start_date="2026-04-01T00:00:00Z"):
    """Activated lease driven >= 90 days past due (PRE_LIEN) via a billing-cycle.

    Defaults: invoice due 2026-04-01, clock advanced to 2026-07-02 (>= 90 days past
    due-date), then a billing-cycle run flips ACTIVE->DELINQUENT->PRE_LIEN.
    Returns dict(facility, unit, tenant, lease, lease_version[, policy]).
    """
    ov = {"climate_controlled": climate, "monthly_rate_cents": rate}
    lov = {"billing_day": 1, "insurance_required": with_insurance is not None}
    ctx = setup_activated(unit_overrides=ov, lease_overrides=lov,
                          start_date=start_date, with_insurance=with_insurance)
    set_clock(past_due_date)
    get_success_data(api_client.run_billing_cycle(ctx["facility"]["id"], FM))
    ctx["lease"] = get_success_data(api_client.get_lease(ctx["lease"]["id"], FM))
    ctx["lease_version"] = ctx["lease"]["version"]
    return ctx


def setup_auction_opened(climate=True, rate=10000, with_insurance=None,
                         past_due_date="2026-07-02T00:00:00Z"):
    """Delinquent lease with an open AuctionProceeding (NOTICE_SENT; lease LIEN).

    Returns dict adding 'auction' and refreshed 'lease'.
    """
    ctx = setup_delinquent_past_90(climate=climate, rate=rate,
                                   with_insurance=with_insurance,
                                   past_due_date=past_due_date)
    auction = get_success_data(api_client.create_auction_proceeding(
        create_auction_proceeding_payload(ctx["lease"]["id"], ctx["lease_version"]), LIEN
    ))
    ctx["auction"] = auction
    ctx["lease"] = get_success_data(api_client.get_lease(ctx["lease"]["id"], FM))
    return ctx


def setup_auction_scheduled(climate=True, rate=10000, with_insurance=None,
                            past_due_date="2026-07-02T00:00:00Z",
                            file_lien_date="2026-07-16T00:00:00Z",
                            scheduled_sale_date="2026-08-01T00:00:00Z"):
    """Auction opened -> lien filed (after notice window) -> sale scheduled.

    Lease is AUCTION_SCHEDULED; proceeding is SCHEDULED. Returns dict with refreshed
    'auction' and 'lease'.
    """
    ctx = setup_auction_opened(climate=climate, rate=rate,
                               with_insurance=with_insurance,
                               past_due_date=past_due_date)
    set_clock(file_lien_date)
    get_success_data(api_client.file_lien(ctx["auction"]["id"], LIEN))
    ctx["auction"] = get_success_data(api_client.schedule_auction(
        ctx["auction"]["id"], {"scheduled_sale_date": scheduled_sale_date}, LIEN
    ))
    ctx["lease"] = get_success_data(api_client.get_lease(ctx["lease"]["id"], FM))
    return ctx


# ─── Tier 4: Transfer setup ────────────────────────────────────────────

def setup_transfer_requested(from_rate=10000, to_rate=18000, to_climate=False,
                             start_date="2026-04-01T00:00:00Z"):
    """ACTIVE lease on U1 + AVAILABLE U2 + a REQUESTED transfer order L1->U2.

    Returns dict(facility, u1, u2, tenant, lease, transfer, lease_version_after).
    """
    facility = create_facility()
    u1 = create_unit(facility["id"], unit_number="U1", monthly_rate_cents=from_rate)
    u2 = create_unit(facility["id"], unit_number="U2", monthly_rate_cents=to_rate,
                     size_class="SIZE_10X20", climate_controlled=to_climate)
    tenant = create_tenant()
    set_clock(start_date)
    lease = create_lease(u1["id"], tenant["id"], start_date=start_date)
    lease = get_success_data(api_client.activate_lease(lease["id"], FM))
    transfer = get_success_data(api_client.create_transfer_order(
        create_transfer_order_payload(lease["id"], u2["id"], lease["version"]), FM
    ))
    return {
        "facility": facility, "u1": u1, "u2": u2, "tenant": tenant,
        "lease": lease, "transfer": transfer,
    }
