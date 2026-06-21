"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) internally so setup failures
produce clear "setup failed" errors rather than confusing assertion failures.

IDENTITY THREADING: Customer is an entity-backed role. Every ownership-gated
call (reservation create / confirm / cancel / supplies / addons by the holder)
uses make_customer_headers(customer["id"]) — never the shared constant — so
X-User-ID equals the reservation's customer_id.
"""
import itertools

from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_location_payload, create_equipment_class_payload, create_coverage_plan_payload,
    create_supply_payload, create_customer_payload, create_equipment_payload,
    create_reservation_payload, create_supply_line_payload, create_addon_payload,
    create_damage_report_payload, create_transfer_payload, return_payload,
    dispatch_payload, settle_payload,
)
from .test_users import TEST_USERS, make_customer_headers

FM = TEST_USERS["fleet_manager_headers"]
LA = TEST_USERS["location_agent_headers"]

# Unique-suffix generator so codes/skus/emails never collide within one test.
_counter = itertools.count(1)


def _alpha_suffix(n: int) -> str:
    """Encode a positive integer as an uppercase-letter token (A, B, ... Z, AA...).

    CoveragePlan codes are validated as letters-only ("uppercase", PRD §3.1),
    while EquipmentClass codes additionally allow digits/underscores; a
    letters-only suffix satisfies both, so the shared generator never trips a
    code-charset rule.
    """
    letters = ""
    while True:
        n, rem = divmod(n - 1, 26)
        letters = chr(ord("A") + rem) + letters
        if n == 0:
            return letters


def _uniq(prefix: str) -> str:
    return f"{prefix}{_alpha_suffix(next(_counter))}"


# ─── Tier 0: Singleton catalog rows ──────────────────────────────────────
def create_equipment_class(**overrides):
    """Create an EquipmentClass. Unique code by default. Returns the class.

    The payload factory carries a static default `code`; that default would
    otherwise collide across two classes created within one test. Inject a
    unique code unless the caller explicitly pinned one in overrides.
    """
    overrides.setdefault("code", _uniq("CLS"))
    payload = create_equipment_class_payload(**overrides)
    return get_success_data(api_client.create_equipment_class(payload, FM))


def create_location(**overrides):
    """Create a RentalLocation. Returns the location."""
    payload = create_location_payload(**overrides)
    return get_success_data(api_client.create_location(payload, FM))


def create_coverage_plan(**overrides):
    """Create a CoveragePlan. Unique code by default. Returns the plan."""
    overrides.setdefault("code", _uniq("COV"))
    payload = create_coverage_plan_payload(**overrides)
    return get_success_data(api_client.create_coverage_plan(payload, FM))


def create_supply(**overrides):
    """Create a MovingSupply catalog item. Unique sku by default. Returns the supply.

    The payload factory carries a static default `sku`; injecting the unique
    value into overrides (before the factory runs) is what actually overrides
    it, so two supplies created within one test do not collide on `sku`.
    """
    overrides.setdefault("sku", _uniq("SKU"))
    payload = create_supply_payload(**overrides)
    return get_success_data(api_client.create_supply(payload, FM))


def create_customer(**overrides):
    """Create a Customer. Unique email by default. Returns the customer.

    Inject the unique email into overrides (before the factory runs) so the
    factory's static default email cannot collide across two customers created
    within one test.
    """
    overrides.setdefault("email", f"{_uniq('cust')}@x.com")
    payload = create_customer_payload(**overrides)
    return get_success_data(api_client.create_customer(payload, FM))


def create_equipment(equipment_class_id, home_location_id, **overrides):
    """Create one Equipment unit homed at a location. Returns the unit."""
    payload = create_equipment_payload(equipment_class_id, home_location_id, **overrides)
    return get_success_data(api_client.create_equipment(payload, FM))


# ─── Tier 1: Reservation in a target booking/fulfillment state ──────────
def create_reservation(customer, equipment_class_id, pickup_id, dropoff_id, **overrides):
    """Create a PENDING reservation owned by `customer`. Returns the reservation."""
    payload = create_reservation_payload(
        customer["id"], equipment_class_id, pickup_id, dropoff_id, **overrides
    )
    return get_success_data(
        api_client.create_reservation(payload, make_customer_headers(customer["id"]))
    )


def confirm_reservation(reservation_id, customer):
    """Confirm a PENDING reservation as its owner. Returns the confirmed reservation."""
    return get_success_data(
        api_client.confirm_reservation(reservation_id, make_customer_headers(customer["id"]))
    )


def dispatch_reservation(reservation_id, expected_version):
    """Dispatch a CONFIRMED reservation as LocationAgent. Returns the created contract."""
    return get_success_data(
        api_client.dispatch_reservation(
            reservation_id, dispatch_payload(expected_version), LA
        )
    )


def return_contract(contract_id, return_odometer_miles, return_fuel_eighths, actual_return_at):
    """Check a unit in as LocationAgent. Returns the (returned) contract."""
    return get_success_data(
        api_client.return_contract(
            contract_id,
            return_payload(return_odometer_miles, return_fuel_eighths, actual_return_at),
            LA,
        )
    )


def settle_contract(contract_id, expected_version):
    """Settle a returned contract as LocationAgent. Returns the settled contract."""
    return get_success_data(
        api_client.settle_contract(contract_id, settle_payload(expected_version), LA)
    )


# ─── Tier 2: Standard fleet setup ────────────────────────────────────────
def setup_class_location_unit(class_overrides=None, location_overrides=None,
                              equipment_overrides=None):
    """One EquipmentClass + one RentalLocation (HUB) + one Equipment homed there.

    Returns (cls, location, equipment).
    """
    cls = create_equipment_class(**(class_overrides or {}))
    loc = create_location(**(location_overrides or {"name": "HUB"}))
    eq = create_equipment(cls["id"], loc["id"], **(equipment_overrides or {}))
    return cls, loc, eq


def setup_round_trip_confirmed(class_overrides=None, location_overrides=None,
                               equipment_overrides=None, customer_overrides=None,
                               reservation_overrides=None):
    """Class + HUB + one unit + verified customer + a CONFIRMED round-trip reservation.

    Returns dict(cls, loc, eq, customer, reservation) where reservation is the
    post-confirm view (so reservation["version"] is the value to pass as the
    dispatch OCC expected_reservation_version).
    """
    cls, loc, eq = setup_class_location_unit(
        class_overrides, location_overrides or {"name": "HUB"}, equipment_overrides
    )
    cust = create_customer(**(customer_overrides or {}))
    resv = create_reservation(
        cust, cls["id"], loc["id"], loc["id"], **(reservation_overrides or {})
    )
    confirmed = confirm_reservation(resv["id"], cust)
    return {"cls": cls, "loc": loc, "eq": eq, "customer": cust, "reservation": confirmed}


def setup_round_trip_dispatched(class_overrides=None, location_overrides=None,
                                equipment_overrides=None, customer_overrides=None,
                                reservation_overrides=None):
    """Round-trip reservation walked all the way to DISPATCHED (contract ACTIVE).

    Returns dict(cls, loc, eq, customer, reservation, contract).
    """
    s = setup_round_trip_confirmed(
        class_overrides, location_overrides, equipment_overrides,
        customer_overrides, reservation_overrides,
    )
    contract = dispatch_reservation(s["reservation"]["id"], s["reservation"]["version"])
    s["contract"] = contract
    return s


def setup_round_trip_returned(return_odometer_miles=0, return_fuel_eighths=8,
                              actual_return_at="2026-07-02T09:00:00Z",
                              class_overrides=None, equipment_overrides=None,
                              customer_overrides=None, reservation_overrides=None):
    """Round-trip reservation dispatched then RETURNED (clean unless damage filed).

    Returns dict(cls, loc, eq, customer, reservation, contract) where contract is
    the post-return view (so contract["version"] is the settle OCC expected value).
    """
    s = setup_round_trip_dispatched(
        class_overrides=class_overrides,
        equipment_overrides=equipment_overrides,
        customer_overrides=customer_overrides,
        reservation_overrides=reservation_overrides,
    )
    returned = return_contract(
        s["contract"]["id"], return_odometer_miles, return_fuel_eighths, actual_return_at
    )
    s["contract"] = returned
    return s


# ─── Tier 3: One-way path ────────────────────────────────────────────────
def setup_one_way_dispatched(pick_overrides=None, drop_overrides=None,
                             class_overrides=None, equipment_overrides=None,
                             customer_overrides=None, reservation_overrides=None):
    """PICK + DROP (accepts one-way) + one unit homed at PICK + verified customer +
    one-way reservation PICK->DROP CONFIRMED then DISPATCHED (contract ACTIVE).

    Returns dict(cls, pick, drop, eq, customer, reservation, contract).
    """
    cls = create_equipment_class(**(class_overrides or {}))
    pick = create_location(**(pick_overrides or {"name": "PICK", "state_code": "CA"}))
    drop_kwargs = drop_overrides or {
        "name": "DROP", "state_code": "NV", "accepts_one_way_dropoff": True,
    }
    drop_kwargs.setdefault("accepts_one_way_dropoff", True)
    drop = create_location(**drop_kwargs)
    eq = create_equipment(cls["id"], pick["id"], **(equipment_overrides or {}))
    cust = create_customer(**(customer_overrides or {}))
    resv = create_reservation(
        cust, cls["id"], pick["id"], drop["id"], **(reservation_overrides or {})
    )
    confirmed = confirm_reservation(resv["id"], cust)
    contract = dispatch_reservation(confirmed["id"], confirmed["version"])
    return {
        "cls": cls, "pick": pick, "drop": drop, "eq": eq,
        "customer": cust, "reservation": confirmed, "contract": contract,
    }


# ─── Tier 4: Transfers ───────────────────────────────────────────────────
def setup_transfer_requested(from_overrides=None, to_overrides=None,
                             class_overrides=None, reason="FLEET_REBALANCE",
                             filler_at_to=False):
    """FROM location holding one AVAILABLE unit + TO location; a REQUESTED transfer
    FROM->TO opened for the unit. Optionally pre-fill TO with one unit.

    Returns dict(cls, from_loc, to_loc, eq, transfer) (+ filler when filler_at_to).
    """
    cls = create_equipment_class(**(class_overrides or {}))
    from_loc = create_location(**(from_overrides or {"name": "FROM", "state_code": "CA"}))
    to_loc = create_location(**(to_overrides or {"name": "TO", "state_code": "NV"}))
    result = {"cls": cls, "from_loc": from_loc, "to_loc": to_loc}
    if filler_at_to:
        result["filler"] = create_equipment(cls["id"], to_loc["id"])
    eq = create_equipment(cls["id"], from_loc["id"])
    result["eq"] = eq
    transfer = get_success_data(
        api_client.create_transfer(
            create_transfer_payload(eq["id"], to_loc["id"], reason=reason), FM
        )
    )
    result["transfer"] = transfer
    return result


# ─── Tier 5: Damage / settlement helpers ─────────────────────────────────
def file_damage(contract_id, assessed_cost_cents=50000, description="Assessed damage"):
    """File a DamageReport against an ACTIVE contract. Returns the report."""
    return get_success_data(
        api_client.file_damage_report(
            contract_id,
            create_damage_report_payload(assessed_cost_cents, description),
            LA,
        )
    )


def add_supply_line(reservation_id, customer, supply_id, quantity):
    """Add a SupplyLineItem to a PENDING reservation as its owner. Returns the line."""
    return get_success_data(
        api_client.add_supply(
            reservation_id, create_supply_line_payload(supply_id, quantity),
            make_customer_headers(customer["id"]),
        )
    )


def add_addon_line(reservation_id, customer, addon_type, quantity):
    """Add an EquipmentAddOn to a PENDING reservation as its owner. Returns the add-on."""
    return get_success_data(
        api_client.add_addon(
            reservation_id, create_addon_payload(addon_type, quantity),
            make_customer_headers(customer["id"]),
        )
    )


def get_ledger(contract_id):
    """Return the list of ChargeLedgerEntry rows for a contract."""
    return get_success_data(api_client.list_ledger(contract_id, LA))


def get_location(location_id):
    """Return the current RentalLocation view (for on_lot_count assertions)."""
    return get_success_data(api_client.get_location(location_id, FM))


def get_equipment(equipment_id):
    """Return the current Equipment view."""
    return get_success_data(api_client.get_equipment(equipment_id, FM))


def get_reservation(reservation_id, customer):
    """Return the current Reservation view, read as its owner."""
    return get_success_data(
        api_client.get_reservation(reservation_id, make_customer_headers(customer["id"]))
    )


def get_supply(supply_id):
    """Return the current MovingSupply view (for stock_qty assertions)."""
    return get_success_data(api_client.get_supply(supply_id, FM))
