"""Composite setup helpers for the Food Bank Pantry Distribution API.

These encapsulate the multi-step preambles (cold storage -> lot -> agency ->
cycle -> order -> approve -> household -> certify -> event -> pack -> finalize)
that the test scenarios repeatedly require. Each fixture builds its
preconditions from scratch using only PRD-declared endpoints and uses
get_success_data() so setup failures surface clearly.

Identity threading: the AgencyCoordinator role is entity-backed by Agency, so
every ownership-gated call uses make_agency_coordinator_headers(agency_id)
with the real Agency id (PRD §2.1).
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import (
    TEST_USERS,
    make_agency_coordinator_headers,
)
from . import factories

OP = TEST_USERS["food_bank_operator_headers"]
MGR = TEST_USERS["allocation_manager_headers"]
AUD = TEST_USERS["compliance_auditor_headers"]


# ---------------------------------------------------------------------------
# Tier 1: primitives
# ---------------------------------------------------------------------------

def create_cold_storage_unit(name="Cooler", temp_zone="REFRIGERATED", capacity_lbs=5000):
    """Create a cold storage unit. Returns the unit dict."""
    resp = api_client.create_cold_storage_unit(
        factories.create_cold_storage_unit_payload(
            name=name, temp_zone=temp_zone, capacity_lbs=capacity_lbs,
        ),
        OP,
    )
    return get_success_data(resp)


def create_inventory_lot(unit_id, food_category="PRODUCE", source_type="DONATION",
                         intake_lbs=100, expiration_date="2026-07-01T00:00:00.000Z",
                         unit_cost_cents=None):
    """Intake a lot into a unit. Returns the lot dict."""
    payload = factories.create_inventory_lot_payload(
        unit_id, food_category=food_category, source_type=source_type,
        intake_lbs=intake_lbs, expiration_date=expiration_date,
    )
    if unit_cost_cents is not None:
        payload["unit_cost_cents"] = unit_cost_cents
    resp = api_client.create_inventory_lot(payload, OP)
    return get_success_data(resp)


def create_agency(name="Test Pantry", service_area="County-Test", fair_share_weight=1,
                  status=None):
    """Register an agency. Returns the agency dict."""
    payload = factories.create_agency_payload(
        name=name, service_area=service_area, fair_share_weight=fair_share_weight,
    )
    if status is not None:
        payload["status"] = status
    resp = api_client.create_agency(payload, MGR)
    return get_success_data(resp)


def create_open_cycle(label="2026-W01", total_pool_lbs=10000):
    """Create and open an allocation cycle (freezes total_fair_share_weight).
    Requires at least one ACTIVE agency to already exist. Returns the OPEN cycle."""
    cycle = get_success_data(api_client.create_allocation_cycle(
        factories.create_allocation_cycle_payload(label=label, total_pool_lbs=total_pool_lbs),
        MGR,
    ))
    opened = get_success_data(api_client.open_allocation_cycle(cycle["id"], MGR))
    return opened


def submit_order(agency_id, cycle_id, lines=None):
    """Submit an order on behalf of the agency (entity-backed coordinator).
    Returns the SUBMITTED order dict."""
    resp = api_client.create_agency_order(
        factories.create_agency_order_payload(agency_id, cycle_id, lines=lines),
        make_agency_coordinator_headers(agency_id),
    )
    return get_success_data(resp)


def create_household(agency_id, household_size=1, monthly_income_cents=100000):
    """Register a household under an agency. Returns the household dict (PENDING)."""
    resp = api_client.create_client_household(
        factories.create_client_household_payload(
            agency_id, household_size=household_size,
            monthly_income_cents=monthly_income_cents,
        ),
        make_agency_coordinator_headers(agency_id),
    )
    return get_success_data(resp)


def certify_household(hh_id):
    """Certify (or deny) a household via the auditor. Returns the household dict."""
    return get_success_data(api_client.certify_client_household(hh_id, AUD))


# ---------------------------------------------------------------------------
# Tier 2/3: composite scenarios
# ---------------------------------------------------------------------------

def setup_approved_order(
    requested_lbs=200,
    intake_lbs=300,
    food_category="PRODUCE",
    source_type="DONATION",
    temp_zone="REFRIGERATED",
    capacity_lbs=5000,
    expiration_date="2026-07-01T00:00:00.000Z",
    fair_share_weight=1,
    total_pool_lbs=10000,
    label="2026-W01",
):
    """Cold unit + single lot + agency + open cycle + single-line order, approved
    via FEFO (OCC pinned to the lot's current version).

    Returns dict with: unit, lot, agency, cycle, order (post-approve).
    """
    unit = create_cold_storage_unit(temp_zone=temp_zone, capacity_lbs=capacity_lbs)
    lot = create_inventory_lot(
        unit["id"], food_category=food_category, source_type=source_type,
        intake_lbs=intake_lbs, expiration_date=expiration_date,
    )
    agency = create_agency(fair_share_weight=fair_share_weight)
    cycle = create_open_cycle(label=label, total_pool_lbs=total_pool_lbs)
    order = submit_order(
        agency["id"], cycle["id"],
        lines=[{"food_category": food_category, "requested_lbs": requested_lbs}],
    )
    approved = get_success_data(api_client.approve_agency_order(
        order["id"], {"expected_lot_version": lot["version"]}, MGR,
    ))
    return {
        "unit": unit, "lot": lot, "agency": agency, "cycle": cycle,
        "order": approved,
    }


def setup_planned_event(
    requested_lbs=200,
    intake_lbs=300,
    household_size=1,
    monthly_income_cents=100000,
    certify=True,
    **order_overrides,
):
    """Approved single-line order + household (optionally certified) + a PLANNED
    distribution event linking them.

    Returns dict: unit, lot, agency, cycle, order, household, event.
    """
    ctx = setup_approved_order(requested_lbs=requested_lbs, intake_lbs=intake_lbs,
                               **order_overrides)
    agency_id = ctx["agency"]["id"]
    household = create_household(
        agency_id, household_size=household_size,
        monthly_income_cents=monthly_income_cents,
    )
    if certify:
        household = certify_household(household["id"])
    event = get_success_data(api_client.create_distribution_event(
        factories.create_distribution_event_payload(ctx["order"]["id"], household["id"]),
        make_agency_coordinator_headers(agency_id),
    ))
    ctx["household"] = household
    ctx["event"] = event
    return ctx


def setup_packed_event(requested_lbs=200, intake_lbs=300, **kwargs):
    """A PACKED distribution event (household certified). planned_lbs set.

    Returns the same dict as setup_planned_event, with event = post-pack.
    """
    ctx = setup_planned_event(requested_lbs=requested_lbs, intake_lbs=intake_lbs,
                              certify=True, **kwargs)
    agency_id = ctx["agency"]["id"]
    packed = get_success_data(api_client.pack_distribution_event(
        ctx["event"]["id"], make_agency_coordinator_headers(agency_id),
    ))
    ctx["event"] = packed
    return ctx


def setup_finalized_event(requested_lbs=200, intake_lbs=300, actual_distributed_lbs=200,
                          **kwargs):
    """A FINALIZED distribution event (cascade complete: lot depleted, order
    fulfilled, agency ledger bumped).

    Returns the same dict, with event = post-finalize.
    """
    ctx = setup_packed_event(requested_lbs=requested_lbs, intake_lbs=intake_lbs, **kwargs)
    agency_id = ctx["agency"]["id"]
    finalized = get_success_data(api_client.finalize_distribution_event(
        ctx["event"]["id"], {"actual_distributed_lbs": actual_distributed_lbs},
        make_agency_coordinator_headers(agency_id),
    ))
    ctx["event"] = finalized
    return ctx


def setup_two_line_donation_tefap_order(
    donation_lbs=100, tefap_lbs=50,
    donation_exp="2026-07-01T00:00:00.000Z",
    tefap_exp="2026-08-01T00:00:00.000Z",
    household_size=2, monthly_income_cents=200000,
):
    """Order with a DONATION PRODUCE line (FEFO-earlier) and a TEFAP DRY_GOODS line
    (FEFO-later), approved and packed. Used for the TEFAP-split waterfall.

    Returns dict: cooler, dry_unit, lot_donation, lot_tefap, agency, cycle,
    order, household, event (PACKED).
    """
    cooler = create_cold_storage_unit(name="Cooler", temp_zone="REFRIGERATED", capacity_lbs=5000)
    dry_unit = create_cold_storage_unit(name="DryShelf", temp_zone="DRY", capacity_lbs=5000)
    lot_donation = create_inventory_lot(
        cooler["id"], food_category="PRODUCE", source_type="DONATION",
        intake_lbs=donation_lbs, expiration_date=donation_exp,
    )
    lot_tefap = create_inventory_lot(
        dry_unit["id"], food_category="DRY_GOODS", source_type="TEFAP",
        intake_lbs=tefap_lbs, expiration_date=tefap_exp, unit_cost_cents=120,
    )
    agency = create_agency()
    cycle = create_open_cycle()
    order = submit_order(
        agency["id"], cycle["id"],
        lines=[
            {"food_category": "PRODUCE", "requested_lbs": donation_lbs},
            {"food_category": "DRY_GOODS", "requested_lbs": tefap_lbs},
        ],
    )
    get_success_data(api_client.approve_agency_order(
        order["id"], {"expected_lot_version": lot_donation["version"]}, MGR,
    ))
    household = create_household(agency["id"], household_size=household_size,
                                monthly_income_cents=monthly_income_cents)
    household = certify_household(household["id"])
    event = get_success_data(api_client.create_distribution_event(
        factories.create_distribution_event_payload(order["id"], household["id"]),
        make_agency_coordinator_headers(agency["id"]),
    ))
    event = get_success_data(api_client.pack_distribution_event(
        event["id"], make_agency_coordinator_headers(agency["id"]),
    ))
    return {
        "cooler": cooler, "dry_unit": dry_unit,
        "lot_donation": lot_donation, "lot_tefap": lot_tefap,
        "agency": agency, "cycle": cycle, "order": order,
        "household": household, "event": event,
    }
