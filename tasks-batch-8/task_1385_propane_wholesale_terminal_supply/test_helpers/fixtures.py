"""Composite setup helpers.

Every helper builds preconditions from scratch using only PRD-declared
endpoints (each test runs against a freshly restarted server with an empty
database). Setup calls use get_success_data so failures surface as clear
"Setup failed" errors. DealerUser calls always thread the acting dealer's id
through make_dealer_user_headers (entity-backed identity, PRD section 2.1).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import DEFAULT_CLOCK_ISO, INDEX_BASIS, TEST_DEFAULTS as D
from .factories import (
    create_allocation_run_payload,
    create_cold_snap_event_payload,
    create_dealer_contract_payload,
    create_dealer_payload,
    create_dealer_payment_payload,
    create_delivery_order_payload,
    create_freight_zone_payload,
    create_price_index_publication_payload,
    create_rail_shipment_payload,
    create_supply_contract_payload,
    create_terminal_payload,
    create_truck_payload,
    schedule_order_payload,
)
from .test_users import TEST_USERS, make_dealer_user_headers

SUPPLY_ADMIN = TEST_USERS["supply_admin_headers"]
SUPPLY_PLANNER = TEST_USERS["supply_planner_headers"]
PRICING_DESK = TEST_USERS["pricing_desk_headers"]
CREDIT_MANAGER = TEST_USERS["credit_manager_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]
SYSTEM_ADMIN = TEST_USERS["system_admin_headers"]


def _ok(step, resp):
    try:
        return get_success_data(resp)
    except AssertionError as exc:
        raise AssertionError(
            f"Setup failed at {step}: HTTP {resp.status_code} {resp.text}"
        ) from exc


# ---------------------------------------------------------------------------
# Tier 1 — clock, terminals, physical estate
# ---------------------------------------------------------------------------

def set_clock(to_iso8601=DEFAULT_CLOCK_ISO):
    """Pin the server logical clock (startup default is 2026-08-01T00:00:00Z)."""
    return _ok("set_clock", api_client.set_clock({"to_iso8601": to_iso8601},
                                                 SYSTEM_ADMIN))


def create_terminal(name="T-1", rack_bay_count=D["RACK_BAY_COUNT"], **overrides):
    resp = api_client.create_terminal(
        create_terminal_payload(name=name, rack_bay_count=rack_bay_count,
                                **overrides),
        SUPPLY_ADMIN,
    )
    return _ok("create_terminal", resp)


def create_zone(terminal_id, zone_code="Z1", **overrides):
    resp = api_client.create_freight_zone(
        create_freight_zone_payload(terminal_id, zone_code=zone_code,
                                    **overrides),
        SUPPLY_ADMIN,
    )
    return _ok("create_freight_zone", resp)


def create_truck(terminal_id, unit_number="U-01", **overrides):
    resp = api_client.create_truck(
        create_truck_payload(terminal_id, unit_number=unit_number, **overrides),
        SUPPLY_ADMIN,
    )
    return _ok("create_truck", resp)


# ---------------------------------------------------------------------------
# Tier 2 — upstream supply: contract + rail unload => terminal inventory
# ---------------------------------------------------------------------------

def create_supply_contract(terminal_id, **overrides):
    resp = api_client.create_supply_contract(
        create_supply_contract_payload(terminal_id, **overrides),
        SUPPLY_ADMIN,
    )
    return _ok("create_supply_contract", resp)


def activate_supply_contract(contract_id):
    return _ok("activate_supply_contract",
               api_client.activate_supply_contract(contract_id, SUPPLY_ADMIN))


def tender_shipment(supply_contract_id, **overrides):
    resp = api_client.create_rail_shipment(
        create_rail_shipment_payload(supply_contract_id, **overrides),
        SUPPLY_ADMIN,
    )
    return _ok("create_rail_shipment", resp)


def advance_shipment(shipment_id, to_state):
    return _ok(f"transition_rail_shipment({to_state})",
               api_client.transition_rail_shipment(
                   shipment_id, {"to_state": to_state}, SUPPLY_ADMIN))


def stock_terminal(terminal_id, volume_gal=D["STOCK_GAL"], **contract_overrides):
    """ACTIVE supply contract + one shipment driven TENDERED -> UNLOADED.

    Returns (supply_contract, rail_shipment). Terminal gains volume_gal on hand.
    """
    contract = create_supply_contract(terminal_id, **contract_overrides)
    activate_supply_contract(contract["id"])
    shipment = tender_shipment(contract["id"], volume_gal=volume_gal)
    advance_shipment(shipment["id"], "IN_TRANSIT")
    advance_shipment(shipment["id"], "ARRIVED")
    advance_shipment(shipment["id"], "UNLOADED")
    return contract, shipment


# ---------------------------------------------------------------------------
# Tier 2 — dealer book: dealer, contract, OCC-safe activation, index
# ---------------------------------------------------------------------------

def create_dealer(legal_name="Dealer Co", credit_limit_cents=D["DEALER_CREDIT_LIMIT_CENTS"]):
    resp = api_client.create_dealer(
        create_dealer_payload(legal_name=legal_name,
                              credit_limit_cents=credit_limit_cents),
        CREDIT_MANAGER,
    )
    return _ok("create_dealer", resp)


def get_dealer(dealer_id):
    return _ok("get_dealer", api_client.get_dealer(dealer_id, CREDIT_MANAGER))


def publish_index(price_mc_per_gal=D["BASE_INDEX_MC_PER_GAL"],
                  effective_date=D["BASE_INDEX_EFFECTIVE_DATE"],
                  index_name=INDEX_BASIS):
    resp = api_client.create_price_index_publication(
        create_price_index_publication_payload(
            index_name=index_name, effective_date=effective_date,
            price_mc_per_gal=price_mc_per_gal),
        PRICING_DESK,
    )
    return _ok("create_price_index_publication", resp)


def create_dealer_contract(dealer_id, terminal_id, **overrides):
    resp = api_client.create_dealer_contract(
        create_dealer_contract_payload(dealer_id, terminal_id, **overrides),
        CREDIT_MANAGER,
    )
    return _ok("create_dealer_contract", resp)


def activate_dealer_contract(contract_id, dealer_id):
    """Activate with the dealer's CURRENT version (PRD section 2.6 OCC)."""
    version = get_dealer(dealer_id)["version"]
    return _ok(
        "activate_dealer_contract",
        api_client.activate_dealer_contract(
            contract_id, {"expected_dealer_version": version}, CREDIT_MANAGER),
    )


def dealer_with_active_contract(terminal_id, legal_name="Dealer Co",
                                credit_limit_cents=D["DEALER_CREDIT_LIMIT_CENTS"],
                                pricing_mode="FIXED",
                                fixed_price_mc_per_gal=D["FIXED_PRICE_MC_PER_GAL"],
                                volume_committed_gal=D["CONTRACT_COMMITTED_GAL"],
                                window_start=D["CONTRACT_WINDOW_START"],
                                window_end=D["CONTRACT_WINDOW_END"]):
    """Dealer + one contract activated (OCC threaded). Returns (dealer, contract)."""
    dealer = create_dealer(legal_name=legal_name,
                           credit_limit_cents=credit_limit_cents)
    contract = create_dealer_contract(
        dealer["id"], terminal_id, pricing_mode=pricing_mode,
        fixed_price_mc_per_gal=fixed_price_mc_per_gal,
        volume_committed_gal=volume_committed_gal,
        window_start=window_start, window_end=window_end,
    )
    activate_dealer_contract(contract["id"], dealer["id"])
    return dealer, contract


# ---------------------------------------------------------------------------
# Tier 3 — order lifecycle walks
# ---------------------------------------------------------------------------

def create_order(dealer_id, terminal_id, zone_id, requested_gal,
                 dealer_contract_id=None):
    """DealerUser creates an order as itself (entity-backed identity)."""
    resp = api_client.create_delivery_order(
        create_delivery_order_payload(terminal_id, zone_id, requested_gal,
                                      dealer_contract_id=dealer_contract_id),
        make_dealer_user_headers(dealer_id),
    )
    return _ok("create_delivery_order", resp)


def schedule_order(order_id, truck_id,
                   planned_load_start="2026-08-03T08:00:00Z",
                   planned_load_end="2026-08-03T10:00:00Z"):
    resp = api_client.schedule_delivery_order(
        order_id,
        schedule_order_payload(truck_id, planned_load_start, planned_load_end),
        DISPATCHER,
    )
    return _ok("schedule_delivery_order", resp)


def unschedule_order(order_id):
    return _ok("unschedule_delivery_order",
               api_client.unschedule_delivery_order(order_id, DISPATCHER))


def load_order(order_id):
    return _ok("load_delivery_order",
               api_client.load_delivery_order(order_id, DISPATCHER))


def deliver_order(order_id):
    return _ok("deliver_delivery_order",
               api_client.deliver_delivery_order(order_id, DISPATCHER))


def drive_order_to_delivered(order_id, truck_id,
                             planned_load_start="2026-08-03T08:00:00Z",
                             planned_load_end="2026-08-03T10:00:00Z"):
    """Walk an ALLOCATED order through SCHEDULED -> LOADED -> DELIVERED."""
    schedule_order(order_id, truck_id, planned_load_start, planned_load_end)
    load_order(order_id)
    return deliver_order(order_id)


# ---------------------------------------------------------------------------
# Tier 4 — scarcity: cold snaps and allocation runs
# ---------------------------------------------------------------------------

def declare_cold_snap(terminal_id, severity="WARNING", start_date="2026-08-01",
                      end_date="2026-08-20"):
    resp = api_client.create_cold_snap_event(
        create_cold_snap_event_payload(terminal_id, severity=severity,
                                       start_date=start_date, end_date=end_date),
        SUPPLY_PLANNER,
    )
    return _ok("create_cold_snap_event", resp)


def activate_cold_snap(event_id):
    return _ok("activate_cold_snap",
               api_client.activate_cold_snap(event_id, SUPPLY_PLANNER))


def curtail_terminal(terminal_id, **snap_overrides):
    """Declare + activate a cold snap; terminal ends CURTAILED."""
    snap = declare_cold_snap(terminal_id, **snap_overrides)
    activate_cold_snap(snap["id"])
    return snap


def terminal_version(terminal_id):
    return _ok("get_terminal",
               api_client.get_terminal(terminal_id, SUPPLY_PLANNER))["version"]


def create_allocation_run(terminal_id):
    """Create a run with the terminal's CURRENT version (PRD section 2.6 OCC)."""
    version = terminal_version(terminal_id)
    resp = api_client.create_allocation_run(
        create_allocation_run_payload(terminal_id, version),
        SUPPLY_PLANNER,
    )
    return _ok("create_allocation_run", resp)


# ---------------------------------------------------------------------------
# Tier 5 — composite base fixtures shared across the suite
# ---------------------------------------------------------------------------

def base_terminal_fixture(name="T-B", rack_bay_count=D["RACK_BAY_COUNT"],
                          truck_count=1, stock_gal=D["STOCK_GAL"],
                          zone_code="Z1", one_way_drive_minutes=D["ZONE_ONE_WAY_MINUTES"],
                          clock=DEFAULT_CLOCK_ISO,
                          truck_capacity_gal=D["TRUCK_CAPACITY_GAL"],
                          **terminal_overrides):
    """Clock pinned + terminal + stocked inventory + zone (+ trucks).

    Returns dict(terminal, supply_contract, shipment, zone, trucks).
    """
    if clock is not None:
        set_clock(clock)
    terminal = create_terminal(name=name, rack_bay_count=rack_bay_count,
                               **terminal_overrides)
    contract, shipment = stock_terminal(terminal["id"], volume_gal=stock_gal)
    zone = create_zone(terminal["id"], zone_code=zone_code,
                       one_way_drive_minutes=one_way_drive_minutes)
    trucks = [
        create_truck(terminal["id"], unit_number=f"U-{i + 1:02d}",
                     capacity_gal=truck_capacity_gal)
        for i in range(truck_count)
    ]
    return {
        "terminal": terminal,
        "supply_contract": contract,
        "shipment": shipment,
        "zone": zone,
        "trucks": trucks,
    }


def base_order_fixture(name="T-O", dealer_name="Dealer Co",
                       credit_limit_cents=D["DEALER_CREDIT_LIMIT_CENTS"],
                       pricing_mode="FIXED",
                       fixed_price_mc_per_gal=D["FIXED_PRICE_MC_PER_GAL"],
                       volume_committed_gal=D["CONTRACT_COMMITTED_GAL"],
                       **base_kwargs):
    """base_terminal_fixture + dealer with an ACTIVE contract.

    Returns the base dict plus dealer and dealer_contract.
    """
    ctx = base_terminal_fixture(name=name, **base_kwargs)
    dealer, contract = dealer_with_active_contract(
        ctx["terminal"]["id"], legal_name=dealer_name,
        credit_limit_cents=credit_limit_cents, pricing_mode=pricing_mode,
        fixed_price_mc_per_gal=fixed_price_mc_per_gal,
        volume_committed_gal=volume_committed_gal,
    )
    ctx["dealer"] = dealer
    ctx["dealer_contract"] = contract
    return ctx


def post_payment(dealer_id, amount_cents, method="ACH"):
    resp = api_client.create_dealer_payment(
        create_dealer_payment_payload(dealer_id, amount_cents, method=method),
        CREDIT_MANAGER,
    )
    return _ok("create_dealer_payment", resp)
