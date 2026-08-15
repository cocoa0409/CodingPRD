"""Composite setup helpers (PRD §3 workflows).

Every fixture builds its preconditions from scratch via PRD-declared endpoints;
the harness restarts the server before each test, so nothing is shared.
Setup calls use get_success_data() so failures surface as clear setup errors.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import DEPART_CLOCK_ISO, TRAVEL_WINDOW_END, TRAVEL_WINDOW_START
from .factories import (
    create_crane_appointment_payload,
    create_customer_payload,
    create_escort_booking_payload,
    create_fine_payload,
    create_load_payload,
    create_permit_payload,
    create_scale_ticket_payload,
    create_securement_plan_payload,
    grant_permit_payload,
    plan_load_payload,
    resolve_fine_payload,
    survey_load_payload,
)
from .test_users import TEST_USERS, make_shipper_headers

ADMIN = TEST_USERS["platform_admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]
PERMIT_CLERK = TEST_USERS["permit_clerk_headers"]
STATE_AUTHORITY = TEST_USERS["state_authority_headers"]
SAFETY = TEST_USERS["safety_manager_headers"]
DRIVER = TEST_USERS["driver_headers"]
BILLING = TEST_USERS["billing_clerk_headers"]


# ---------------------------------------------------------------------------
# Tier 1: state progression primitives
# ---------------------------------------------------------------------------

def create_customer(company_name="Test Shipper Co", credit_limit_cents=100_000_000):
    """Register a customer (PRD §3.1). Returns the Customer dict."""
    resp = api_client.create_customer(
        create_customer_payload(
            company_name=company_name, credit_limit_cents=credit_limit_cents
        ),
        ADMIN,
    )
    return get_success_data(resp)


def create_load_for_customer(customer_id, **overrides):
    """Create a DRAFT load owned by the given customer (PRD §3.2)."""
    resp = api_client.create_load(
        create_load_payload(**overrides), make_shipper_headers(customer_id)
    )
    return get_success_data(resp)


def plan_load(load_id, **overrides):
    """Plan a load (PRD §3.2). Returns the updated Load dict."""
    resp = api_client.plan_load(load_id, plan_load_payload(**overrides), DISPATCHER)
    return get_success_data(resp)


def survey_load(load_id, **overrides):
    """Survey a load (PRD §3.3). Returns the updated Load dict."""
    resp = api_client.survey_load(
        load_id, survey_load_payload(**overrides), DISPATCHER
    )
    return get_success_data(resp)


def create_and_plan_load(customer_id, load_overrides=None, plan_overrides=None):
    """DRAFT load -> PLANNED. Returns the planned Load dict."""
    load = create_load_for_customer(customer_id, **(load_overrides or {}))
    return plan_load(load["id"], **(plan_overrides or {}))


def create_planned_and_surveyed_load(customer_id, load_overrides=None,
                                     plan_overrides=None, survey_overrides=None):
    """Load walked DRAFT -> PLANNED -> SURVEYED with a passing survey.
    Returns the surveyed Load dict."""
    planned = create_and_plan_load(customer_id, load_overrides, plan_overrides)
    return survey_load(planned["id"], **(survey_overrides or {}))


# ---------------------------------------------------------------------------
# Tier 2/3: child-resource helpers and lifecycle shortcuts
# ---------------------------------------------------------------------------

def get_load_version(load_id):
    return get_success_data(api_client.get_load(load_id, DISPATCHER))["version"]


def create_permit_for_load(load_id, state_code, permit_type,
                           expected_load_version=None):
    """Create a DRAFT permit with OCC on the (current or given) load version."""
    if expected_load_version is None:
        expected_load_version = get_load_version(load_id)
    resp = api_client.create_permit(
        load_id,
        create_permit_payload(
            state_code=state_code, permit_type=permit_type,
            expected_load_version=expected_load_version,
        ),
        PERMIT_CLERK,
    )
    return get_success_data(resp)


def file_permit(permit_id):
    return get_success_data(api_client.file_permit(permit_id, PERMIT_CLERK))


def grant_permit(permit_id, window_start=TRAVEL_WINDOW_START,
                 window_end=TRAVEL_WINDOW_END):
    resp = api_client.grant_permit(
        permit_id,
        grant_permit_payload(
            travel_window_start=window_start, travel_window_end=window_end
        ),
        STATE_AUTHORITY,
    )
    return get_success_data(resp)


def create_filed_and_granted_permit(load_id, state_code, permit_type,
                                    window_start=TRAVEL_WINDOW_START,
                                    window_end=TRAVEL_WINDOW_END):
    """DRAFT -> FILED -> GRANTED in one helper. Returns the granted Permit."""
    permit = create_permit_for_load(load_id, state_code, permit_type)
    file_permit(permit["id"])
    return grant_permit(permit["id"], window_start, window_end)


def book_escort(load_id, provider_name="Test Pilot Co", position="REAR",
                start="2026-08-12T08:00:00Z", end="2026-08-12T12:00:00Z",
                rate_per_hour_cents=12000, expected_load_version=None):
    """Book a CONFIRMED escort (PRD §3.6). Returns the EscortBooking dict."""
    if expected_load_version is None:
        expected_load_version = get_load_version(load_id)
    resp = api_client.create_escort_booking(
        load_id,
        create_escort_booking_payload(
            provider_name=provider_name, position=position,
            scheduled_start=start, scheduled_end=end,
            rate_per_hour_cents=rate_per_hour_cents,
            expected_load_version=expected_load_version,
        ),
        DISPATCHER,
    )
    return get_success_data(resp)


def schedule_crane(load_id, site="ORIGIN", crane_id=None,
                   window_start=None, window_end=None):
    """Schedule a SCHEDULED crane appointment (PRD §3.6)."""
    resp = api_client.create_crane_appointment(
        load_id,
        create_crane_appointment_payload(
            site=site, crane_id=crane_id,
            **({"window_start": window_start} if window_start else {}),
            **({"window_end": window_end} if window_end else {}),
        ),
        DISPATCHER,
    )
    return get_success_data(resp)


def schedule_both_cranes(load_id):
    """One ORIGIN and one DESTINATION crane appointment (gate condition 4)."""
    origin = schedule_crane(load_id, site="ORIGIN", crane_id="CRANE-A")
    dest = schedule_crane(load_id, site="DESTINATION", crane_id="CRANE-B")
    return origin, dest


def file_and_approve_securement(load_id, method="CHAINS", tiedown_count=4,
                                wll_per_tiedown_lbs=15000):
    """File a securement plan and approve it (PRD §3.4). Returns the plan."""
    resp = api_client.create_securement_plan(
        load_id,
        create_securement_plan_payload(
            method=method, tiedown_count=tiedown_count,
            wll_per_tiedown_lbs=wll_per_tiedown_lbs,
        ),
        DISPATCHER,
    )
    plan = get_success_data(resp)
    return get_success_data(api_client.approve_securement_plan(plan["id"], SAFETY))


def set_clock(to_iso8601=DEPART_CLOCK_ISO):
    """Advance the logical clock (PRD §2.8)."""
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


# ---------------------------------------------------------------------------
# Tier 3: full clearance chains
# ---------------------------------------------------------------------------

def setup_standard_load_cleared(company_name="Std Co",
                                credit_limit_cents=100_000_000,
                                route_miles=100, trailer_type="FLATBED"):
    """STANDARD load (40000 lbs, 100x50x400 in — no permits, no escorts)
    walked to CLEARED: plan -> survey -> both cranes -> securement approved.
    Returns (customer, load)."""
    customer = create_customer(company_name, credit_limit_cents)
    load = create_planned_and_surveyed_load(
        customer["id"],
        load_overrides={
            "gross_weight_lbs": 40000, "width_in": 100,
            "height_in": 50, "length_in": 400,
        },
        plan_overrides={
            "trailer_type": trailer_type,
            "trailer_axle_count": 2,
            "driver_oversize_endorsed": False,
        },
        survey_overrides={
            "route_miles": route_miles, "states_crossed": ["OR"],
            "min_bridge_clearance_in": 200, "max_bridge_weight_lbs": 80000,
        },
    )
    schedule_both_cranes(load["id"])
    file_and_approve_securement(
        load["id"], method="STRAPS", tiedown_count=2, wll_per_tiedown_lbs=10000
    )
    load = get_success_data(api_client.get_load(load["id"], DISPATCHER))
    return customer, load


def setup_standard_load_in_transit(**kwargs):
    """STANDARD load CLEARED -> clock set -> departed. Returns (customer, load)."""
    customer, load = setup_standard_load_cleared(**kwargs)
    set_clock(DEPART_CLOCK_ISO)
    load = get_success_data(api_client.depart_load(load["id"], DRIVER))
    return customer, load


def setup_standard_load_delivered(**kwargs):
    """STANDARD load through DELIVERED. Returns (customer, load)."""
    customer, load = setup_standard_load_in_transit(**kwargs)
    load = get_success_data(api_client.arrive_load(load["id"], DRIVER))
    return customer, load


def setup_ca_oversize_overweight_cleared(
    company_name="CA Heavy Co",
    credit_limit_cents=100_000_000,
    route_miles=500,
    gross_weight_lbs=96000,
    width_in=150,
    escort_provider="Test Pilot Co",
    escort_rate_per_hour_cents=12000,
    escort_window=("2026-08-12T08:00:00Z", "2026-08-12T12:00:00Z"),
):
    """96000-lb, 150-in wide load in CA: OVERSIZE + OVERWEIGHT permits GRANTED,
    REAR escort CONFIRMED, both cranes SCHEDULED, securement APPROVED, so the
    readiness gate has advanced the load to CLEARED.

    Returns a dict with customer, load, permits, escort booking, and cranes.
    """
    customer = create_customer(company_name, credit_limit_cents)
    load = create_planned_and_surveyed_load(
        customer["id"],
        load_overrides={
            "gross_weight_lbs": gross_weight_lbs, "width_in": width_in,
            "height_in": 100, "length_in": 400,
        },
        plan_overrides={
            "trailer_type": "EXTENDABLE_DOUBLE_DROP",
            "trailer_axle_count": 6,
            "driver_oversize_endorsed": True,
        },
        survey_overrides={
            "route_miles": route_miles, "states_crossed": ["CA"],
            "min_bridge_clearance_in": 200, "max_bridge_weight_lbs": 120000,
        },
    )
    load_id = load["id"]
    p_os = create_filed_and_granted_permit(load_id, "CA", "OVERSIZE")
    p_ow = create_filed_and_granted_permit(load_id, "CA", "OVERWEIGHT")
    escort = book_escort(
        load_id, provider_name=escort_provider, position="REAR",
        start=escort_window[0], end=escort_window[1],
        rate_per_hour_cents=escort_rate_per_hour_cents,
    )
    cranes = schedule_both_cranes(load_id)
    plan = file_and_approve_securement(load_id)
    load = get_success_data(api_client.get_load(load_id, DISPATCHER))
    return {
        "customer": customer,
        "load": load,
        "permit_oversize": p_os,
        "permit_overweight": p_ow,
        "escort": escort,
        "cranes": cranes,
        "securement_plan": plan,
    }


def setup_ca_load_in_transit(**kwargs):
    """CA oversize+overweight scenario CLEARED -> clock -> IN_TRANSIT."""
    ctx = setup_ca_oversize_overweight_cleared(**kwargs)
    set_clock(DEPART_CLOCK_ISO)
    ctx["load"] = get_success_data(
        api_client.depart_load(ctx["load"]["id"], DRIVER)
    )
    return ctx


def setup_ca_load_delivered(**kwargs):
    """CA oversize+overweight scenario through DELIVERED."""
    ctx = setup_ca_load_in_transit(**kwargs)
    ctx["load"] = get_success_data(
        api_client.arrive_load(ctx["load"]["id"], DRIVER)
    )
    return ctx


# ---------------------------------------------------------------------------
# Tier 4: fines / invoices
# ---------------------------------------------------------------------------

def report_and_resolve_fine(load_id, kind="DAMAGE", amount_cents=30000,
                            resolution="CUSTOMER_LIABLE",
                            description="Deck damage during loading",
                            reporter_headers=None):
    """Report a manual fine and resolve it (PRD §3.9). Returns the Fine."""
    resp = api_client.create_fine(
        load_id,
        create_fine_payload(
            kind=kind, amount_cents=amount_cents, description=description
        ),
        reporter_headers or SAFETY,
    )
    fine = get_success_data(resp)
    return get_success_data(
        api_client.resolve_fine(
            fine["id"], resolve_fine_payload(resolution=resolution), SAFETY
        )
    )


def issue_invoice(load_id):
    """Create the ISSUED invoice for a DELIVERED load (PRD §3.9)."""
    return get_success_data(api_client.create_invoice(load_id, BILLING))


def record_scale_violation(load_id, measured_gross_lbs=100000,
                           weighed_at="2026-08-12T13:00:00Z"):
    """Record a violating scale ticket (PRD §3.8). Returns the ScaleTicket."""
    resp = api_client.create_scale_ticket(
        load_id,
        create_scale_ticket_payload(
            measured_gross_lbs=measured_gross_lbs, weighed_at=weighed_at
        ),
        DRIVER,
    )
    return get_success_data(resp)
