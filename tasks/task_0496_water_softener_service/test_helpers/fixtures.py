"""Composite setup helpers for the Water Softener Service API.

Each test runs against a freshly restarted, empty server, so every fixture builds
its preconditions from scratch using only PRD-declared endpoints. Fixtures use
get_success_data() (lenient) internally so setup failures surface as clear
"Setup failed" errors. Identity is threaded: ownership-gated calls on entity-backed
resources use make_field_tech_headers / make_customer_headers with the real id.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from . import factories as F
from .test_users import (
    TEST_USERS,
    make_field_tech_headers,
    make_customer_headers,
)

SM = TEST_USERS["service_manager_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]
BILLING = TEST_USERS["billing_clerk_headers"]


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------
def set_clock(to_iso8601, headers=None):
    """Advance the logical clock. Any role authorized for the clock works."""
    headers = headers or SM
    return get_success_data(api_client.set_clock(to_iso8601, headers))


# ---------------------------------------------------------------------------
# Reference registrations
# ---------------------------------------------------------------------------
def create_customer(**overrides):
    return get_success_data(api_client.create_customer(F.create_customer_payload(**overrides), SM))


def create_field_tech(**overrides):
    return get_success_data(api_client.create_field_tech(F.create_field_tech_payload(**overrides), SM))


def create_account(customer_id, **overrides):
    return get_success_data(api_client.create_account(F.create_account_payload(customer_id, **overrides), BILLING))


# ---------------------------------------------------------------------------
# Tier 1 / Tier 2: account + accepted water test
# ---------------------------------------------------------------------------
def setup_account_with_accepted_test(service_zone="Z-NORTH", property_type="MUNICIPAL_WHOLE_HOUSE",
                                     hardness_gpg=15, iron_ppm=0, tds_ppm=200, household_size=4):
    """Customer + tech + account + a water test taken through DRAFT->RECOMMENDED->ACCEPTED.

    Returns a dict with customer, tech, account, water_test (the ACCEPTED test),
    and the per-instance header builders bound to the created ids.
    """
    customer = create_customer()
    tech = create_field_tech(home_zone=service_zone)
    account = create_account(customer["id"], service_zone=service_zone, property_type=property_type)
    tech_headers = make_field_tech_headers(tech["id"])
    cust_headers = make_customer_headers(customer["id"])

    wt = get_success_data(api_client.create_water_test(
        F.create_water_test_payload(account["id"], hardness_gpg=hardness_gpg, iron_ppm=iron_ppm,
                                    tds_ppm=tds_ppm, household_size=household_size),
        tech_headers))
    get_success_data(api_client.recommend_water_test(wt["id"], tech_headers))
    wt = get_success_data(api_client.accept_water_test(wt["id"], cust_headers))
    account = get_success_data(api_client.get_account(account["id"], SM))

    return {
        "customer": customer,
        "tech": tech,
        "account": account,
        "water_test": wt,
        "tech_headers": tech_headers,
        "cust_headers": cust_headers,
    }


def setup_active_system(acquisition_mode="PURCHASE", grain_capacity=32000,
                        service_zone="Z-NORTH", property_type="MUNICIPAL_WHOLE_HOUSE",
                        hardness_gpg=15, iron_ppm=0, tds_ppm=200, household_size=4,
                        install_at=None):
    """Full chain to an ACTIVE softener system.

    customer -> tech -> account -> water test (accepted) -> system ordered ->
    installed -> activated. If install_at is given, the clock is set to that
    instant before install so install_date is stamped deterministically.

    Returns a dict extending setup_account_with_accepted_test with `system`.
    """
    ctx = setup_account_with_accepted_test(
        service_zone=service_zone, property_type=property_type,
        hardness_gpg=hardness_gpg, iron_ppm=iron_ppm, tds_ppm=tds_ppm, household_size=household_size)
    tech_headers = ctx["tech_headers"]

    sys = get_success_data(api_client.create_system(
        F.create_system_payload(ctx["account"]["id"], ctx["water_test"]["id"],
                                acquisition_mode=acquisition_mode, grain_capacity=grain_capacity),
        SM))
    if install_at is not None:
        set_clock(install_at)
    get_success_data(api_client.install_system(sys["id"], tech_headers))
    sys = get_success_data(api_client.activate_system(sys["id"], tech_headers))

    ctx["system"] = sys
    return ctx


# ---------------------------------------------------------------------------
# Tier 3: rental contract lifecycle shortcuts
# ---------------------------------------------------------------------------
def setup_active_rental_contract(monthly_rate_cents=4500, term_months=12,
                                 start_date="2026-01-01T00:00:00Z", grain_capacity=32000,
                                 service_zone="Z-NORTH"):
    """ACTIVE rental contract on a RENTAL system on a GOOD-standing account.

    Returns a dict extending setup_active_system with `contract`.
    """
    ctx = setup_active_system(acquisition_mode="RENTAL", grain_capacity=grain_capacity,
                              service_zone=service_zone)
    contract = get_success_data(api_client.create_rental_contract(
        F.create_rental_contract_payload(ctx["account"]["id"], ctx["system"]["id"],
                                         monthly_rate_cents=monthly_rate_cents,
                                         term_months=term_months, start_date=start_date),
        BILLING))
    ctx["contract"] = contract
    return ctx


# ---------------------------------------------------------------------------
# Tier 2: route + stop setup
# ---------------------------------------------------------------------------
def setup_planned_route_with_active_system(capacity_stops=4, route_service_zone="Z-NORTH",
                                           account_service_zone="Z-NORTH"):
    """An ACTIVE system plus a PLANNED route (no stops yet).

    Returns a dict extending setup_active_system with `route`.
    The route's tech_id is the same FieldTech that owns the system chain.
    """
    ctx = setup_active_system(service_zone=account_service_zone)
    route = get_success_data(api_client.create_route(
        F.create_route_payload(ctx["tech"]["id"], service_zone=route_service_zone,
                               capacity_stops=capacity_stops),
        DISPATCHER))
    ctx["route"] = route
    return ctx


def setup_dispatched_route_with_stop(stop_type="INSPECTION", salt_bags_delivered=None,
                                     window_start="2026-06-01T09:00:00Z",
                                     window_end="2026-06-01T10:00:00Z",
                                     capacity_stops=4):
    """A DISPATCHED route holding one SCHEDULED stop on an ACTIVE system.

    Returns a dict extending setup_planned_route_with_active_system with `stop`.
    """
    ctx = setup_planned_route_with_active_system(capacity_stops=capacity_stops)
    payload = F.create_route_stop_payload(ctx["system"]["id"], stop_type=stop_type,
                                          window_start=window_start, window_end=window_end)
    if salt_bags_delivered is not None:
        payload["salt_bags_delivered"] = salt_bags_delivered
    stop = get_success_data(api_client.add_route_stop(ctx["route"]["id"], payload, DISPATCHER))
    get_success_data(api_client.dispatch_route(ctx["route"]["id"], DISPATCHER))
    ctx["stop"] = stop
    return ctx


# ---------------------------------------------------------------------------
# Tier 1: cartridge schedule progression
# ---------------------------------------------------------------------------
def setup_cartridge_schedule(cartridge_type="RO_MEMBRANE", interval_days=180,
                             last_replaced_at="2026-01-01T00:00:00Z",
                             property_type="POINT_OF_USE", tds_ppm=600):
    """An ACTIVE system with one cartridge schedule (ON_TRACK).

    Returns a dict extending setup_active_system with `schedule`.
    """
    ctx = setup_active_system(property_type=property_type, tds_ppm=tds_ppm)
    schedule = get_success_data(api_client.create_cartridge_schedule(
        F.create_cartridge_schedule_payload(ctx["system"]["id"], cartridge_type=cartridge_type,
                                             interval_days=interval_days,
                                             last_replaced_at=last_replaced_at),
        SM))
    ctx["schedule"] = schedule
    return ctx


def setup_due_soon_cartridge(evaluate_at="2026-06-20T00:00:00Z", interval_days=180,
                             last_replaced_at="2026-01-01T00:00:00Z"):
    """A cartridge schedule evaluated into DUE_SOON at the given clock instant."""
    ctx = setup_cartridge_schedule(interval_days=interval_days, last_replaced_at=last_replaced_at)
    set_clock(evaluate_at, DISPATCHER)
    schedule = get_success_data(api_client.evaluate_cartridge_schedule(ctx["schedule"]["id"], DISPATCHER))
    ctx["schedule"] = schedule
    return ctx


# ---------------------------------------------------------------------------
# Tier 4: meter-reading / regen targeting
# ---------------------------------------------------------------------------
def setup_system_metered_due(gallons=2133, grain_capacity=32000, hardness_gpg=15):
    """ACTIVE system driven to regen_health DUE via a meter-reading.

    capacity_gallons = floor(grain_capacity / account.hardness_gpg).
    Returns a dict extending setup_active_system; `system` reflects post-reading state.
    """
    ctx = setup_active_system(grain_capacity=grain_capacity, hardness_gpg=hardness_gpg)
    sys = get_success_data(api_client.meter_reading(ctx["system"]["id"], {"gallons_since_regen": gallons},
                                                    ctx["tech_headers"]))
    ctx["system"] = sys
    return ctx


# ---------------------------------------------------------------------------
# Tier 5: warranty claim progression
# ---------------------------------------------------------------------------
def setup_triaged_claim(defect_class="VALVE_FAILURE", install_at="2026-01-01T00:00:00Z",
                        reported_at="2026-06-01T00:00:00Z", triage_at="2026-06-01T00:00:00Z",
                        acquisition_mode="PURCHASE"):
    """A warranty claim taken through FILED -> TRIAGED.

    The system is installed at install_at, the claim reported at reported_at, and
    triage performed at clock triage_at. Returns a dict extending setup_active_system
    with `claim` (post-triage).
    """
    ctx = setup_active_system(acquisition_mode=acquisition_mode, install_at=install_at)
    set_clock(triage_at)
    claim = get_success_data(api_client.create_warranty_claim(
        F.create_warranty_claim_payload(ctx["system"]["id"], defect_class=defect_class,
                                         reported_at=reported_at),
        ctx["tech_headers"]))
    claim = get_success_data(api_client.triage_warranty_claim(claim["id"], ctx["tech_headers"]))
    ctx["claim"] = claim
    return ctx


# ---------------------------------------------------------------------------
# Invoices / delinquency
# ---------------------------------------------------------------------------
def create_service_invoice(account_id, amount_overrides=None, **invoice_overrides):
    """Issue a stand-alone SERVICE_REPAIR invoice on the account (BillingClerk)."""
    payload = F.create_invoice_payload(account_id, **invoice_overrides)
    return get_success_data(api_client.create_invoice(payload, BILLING))


def setup_delinquent_account(service_zone="Z-NORTH", acquisition_mode="RENTAL",
                             due_offset_days=30, evaluate_at="2026-03-05T00:00:00Z"):
    """An ACTIVE system on an account driven DELINQUENT by a PAST_DUE invoice.

    Issues a SERVICE_REPAIR invoice with a short period, advances the clock past
    the due window, and evaluates it to PAST_DUE (cascading standing -> DELINQUENT).
    Returns a dict extending setup_active_system with `invoice`.
    """
    ctx = setup_active_system(acquisition_mode=acquisition_mode, service_zone=service_zone)
    invoice = create_service_invoice(
        ctx["account"]["id"], invoice_kind="SERVICE_REPAIR",
        period_start="2026-01-01T00:00:00Z", period_end="2026-02-01T00:00:00Z",
        due_offset_days=due_offset_days)
    set_clock(evaluate_at, BILLING)
    invoice = get_success_data(api_client.evaluate_invoice(invoice["id"], BILLING))
    ctx["account"] = get_success_data(api_client.get_account(ctx["account"]["id"], SM))
    ctx["invoice"] = invoice
    return ctx
