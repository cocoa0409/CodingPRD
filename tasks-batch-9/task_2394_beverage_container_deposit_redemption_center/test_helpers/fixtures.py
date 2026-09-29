"""Composite state builders and pytest fixtures.

The server is restarted before every single test, so every fixture here builds
its state from scratch through the API's own endpoints — there is no seeded
data and no shared session state. Helpers are plain functions so a test can
compose a variant of any chain, and the fixtures wrap the chains that recur.

Tiers, roughly in order of depth:

1. Single-resource creation (distributor, centre, account, period, retailer).
2. Entity hierarchies (registered label, operational centre with a machine).
3. Lifecycle shortcuts (a counted visit, a counted bag, a baled batch).
4. Accumulation and threshold targeting (a visit whose lots breach a cap, an
   account one strike from being flagged).
5. Finalisation and terminal state (a paid visit, a reconciled quarter, a
   closed centre).
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import pytest
from prd_bench_local_runner.testing import get_success_data

from .api_client import ApiClient
from . import factories as f
from .test_users import (
    ADMIN_HEADERS,
    PLANT_COUNTER_HEADERS,
    make_account_headers,
    make_center_headers,
    make_distributor_headers,
    make_retailer_headers,
)

# The instant every composite chain starts from unless a test moves the clock.
SHARED_WORLD_INSTANT = "2026-08-05T09:00:00Z"
SHARED_WORLD_DATE = "2026-08-05"


# ─── Tier 1: single-resource helpers ────────────────────────────────────────


def set_clock(api: ApiClient, to_iso8601: str) -> None:
    """Move the logical clock; every stamped instant follows it."""
    response = api.set_clock(to_iso8601, ADMIN_HEADERS)
    get_success_data(response)


def create_distributor(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    response = api.create_distributor(
        f.create_distributor_payload(**overrides), ADMIN_HEADERS
    )
    return get_success_data(response)


def create_draft_product(
    api: ApiClient, distributor_id: str, **overrides: Any
) -> Dict[str, Any]:
    response = api.create_beverage_product(
        f.create_beverage_product_payload(distributor_id, **overrides),
        make_distributor_headers(distributor_id),
    )
    return get_success_data(response)


def submit_product(
    api: ApiClient, product_id: str, distributor_id: str
) -> Dict[str, Any]:
    response = api.post_registration_action(
        product_id,
        f.registration_action_payload("SUBMIT"),
        make_distributor_headers(distributor_id),
    )
    return get_success_data(response)


def approve_product(api: ApiClient, product_id: str) -> Dict[str, Any]:
    response = api.post_registration_action(
        product_id, f.registration_action_payload("APPROVE"), ADMIN_HEADERS
    )
    return get_success_data(response)


def create_registered_product(
    api: ApiClient, distributor_id: str, **overrides: Any
) -> Dict[str, Any]:
    """Create a label and walk it DRAFT → SUBMITTED → REGISTERED."""
    product = create_draft_product(api, distributor_id, **overrides)
    submit_product(api, product["id"], distributor_id)
    return approve_product(api, product["id"])


def create_center(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    response = api.create_redemption_center(
        f.create_redemption_center_payload(**overrides), ADMIN_HEADERS
    )
    return get_success_data(response)


def install_machine(
    api: ApiClient, center_id: str, **overrides: Any
) -> Dict[str, Any]:
    response = api.create_machine(
        center_id, f.create_machine_payload(**overrides), ADMIN_HEADERS
    )
    return get_success_data(response)


def activate_center(api: ApiClient, center_id: str) -> Dict[str, Any]:
    response = api.post_center_status_change(
        center_id, f.center_status_change_payload("ACTIVATE"), ADMIN_HEADERS
    )
    return get_success_data(response)


def create_account(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    response = api.create_redeemer_account(
        f.create_redeemer_account_payload(**overrides), ADMIN_HEADERS
    )
    return get_success_data(response)


def create_period(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    response = api.create_program_period(
        f.create_program_period_payload(**overrides), ADMIN_HEADERS
    )
    return get_success_data(response)


def create_retailer(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    response = api.create_retailer(
        f.create_retailer_payload(**overrides), ADMIN_HEADERS
    )
    return get_success_data(response)


# ─── Tier 2: entity hierarchies ─────────────────────────────────────────────


def create_operational_center(
    api: ApiClient,
    center_overrides: Optional[Dict[str, Any]] = None,
    machine_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Create a centre, install one machine and activate it.

    Returns {"center": ..., "machine": ...} with both rows re-read after
    activation so their counters and drawer are current.
    """
    center = create_center(api, **(center_overrides or {}))
    machine = install_machine(api, center["id"], **(machine_overrides or {}))
    center = activate_center(api, center["id"])
    machine = read_machine(api, machine["id"], make_center_headers(center["id"]))
    return {"center": center, "machine": machine}


def read_center(api: ApiClient, center_id: str, headers: Dict[str, str]) -> Dict[str, Any]:
    return get_success_data(api.get_redemption_center(center_id, headers))


def read_machine(api: ApiClient, machine_id: str, headers: Dict[str, str]) -> Dict[str, Any]:
    return get_success_data(api.get_machine(machine_id, headers))


def read_account(api: ApiClient, account_id: str, headers: Dict[str, str]) -> Dict[str, Any]:
    return get_success_data(api.get_redeemer_account(account_id, headers))


def read_visit(api: ApiClient, visit_id: str, headers: Dict[str, str]) -> Dict[str, Any]:
    return get_success_data(api.get_redemption_visit(visit_id, headers))


def read_bag_drop(api: ApiClient, bag_drop_id: str, headers: Dict[str, str]) -> Dict[str, Any]:
    return get_success_data(api.get_bag_drop(bag_drop_id, headers))


def read_batch(api: ApiClient, batch_id: str, headers: Dict[str, str]) -> Dict[str, Any]:
    return get_success_data(api.get_commodity_batch(batch_id, headers))


def read_period(api: ApiClient, period_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_program_period(period_id, ADMIN_HEADERS))


def read_retailer(api: ApiClient, retailer_id: str, headers: Dict[str, str]) -> Dict[str, Any]:
    return get_success_data(api.get_retailer(retailer_id, headers))


def visit_version(api: ApiClient, visit_id: str, headers: Dict[str, str]) -> int:
    """Re-read a visit purely to refresh the version a lot addition must carry."""
    return read_visit(api, visit_id, headers)["version"]


def account_version(api: ApiClient, account_id: str, headers: Dict[str, str]) -> int:
    return read_account(api, account_id, headers)["version"]


def bag_drop_version(api: ApiClient, bag_drop_id: str, headers: Dict[str, str]) -> int:
    return read_bag_drop(api, bag_drop_id, headers)["version"]


# ─── Tier 3: visits, lots and lifecycle shortcuts ───────────────────────────


def open_center_machine_visit(
    api: ApiClient,
    center_id: str,
    machine_id: str,
    account_id: Optional[str] = None,
) -> Dict[str, Any]:
    response = api.create_redemption_visit(
        f.center_machine_visit_payload(center_id, machine_id, account_id),
        make_center_headers(center_id),
    )
    return get_success_data(response)


def open_center_hand_visit(
    api: ApiClient, center_id: str, account_id: Optional[str] = None
) -> Dict[str, Any]:
    response = api.create_redemption_visit(
        f.center_hand_visit_payload(center_id, account_id),
        make_center_headers(center_id),
    )
    return get_success_data(response)


def open_retailer_visit(
    api: ApiClient, retailer_id: str, account_id: Optional[str] = None
) -> Dict[str, Any]:
    response = api.create_redemption_visit(
        f.retailer_visit_payload(retailer_id, account_id),
        make_retailer_headers(retailer_id),
    )
    return get_success_data(response)


def add_lot(
    api: ApiClient,
    visit_id: str,
    product_id: str,
    presented_quantity: int,
    headers: Dict[str, str],
    out_of_state_marked_quantity: Optional[int] = None,
    contaminated_quantity: Optional[int] = None,
    expected_visit_version: Optional[int] = None,
) -> Dict[str, Any]:
    """Add one lot, refreshing the visit version first unless one is supplied."""
    if expected_visit_version is None:
        expected_visit_version = visit_version(api, visit_id, headers)
    payload = f.create_lot_payload(
        product_id,
        presented_quantity,
        expected_visit_version,
        out_of_state_marked_quantity=out_of_state_marked_quantity,
        contaminated_quantity=contaminated_quantity,
    )
    return get_success_data(api.create_container_lot(visit_id, payload, headers))


def add_lots(
    api: ApiClient,
    visit_id: str,
    product_id: str,
    quantities: List[int],
    headers: Dict[str, str],
) -> List[Dict[str, Any]]:
    """Add several lots in order, re-reading the visit version between each."""
    return [
        add_lot(api, visit_id, product_id, quantity, headers)
        for quantity in quantities
    ]


def close_count(
    api: ApiClient, visit_id: str, headers: Dict[str, str]
) -> Dict[str, Any]:
    return get_success_data(api.close_count(visit_id, headers))


def payout_action(
    api: ApiClient,
    visit_id: str,
    action: str,
    headers: Dict[str, str],
    reason: Optional[str] = None,
) -> Dict[str, Any]:
    return get_success_data(
        api.post_payout_action(
            visit_id, f.payout_action_payload(action, reason), headers
        )
    )


def create_counted_center_visit(
    api: ApiClient,
    center_id: str,
    machine_id: str,
    product_id: str,
    quantities: List[int],
    account_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Open a machine-counted centre visit, add lots and close the count."""
    headers = make_center_headers(center_id)
    visit = open_center_machine_visit(api, center_id, machine_id, account_id)
    add_lots(api, visit["id"], product_id, quantities, headers)
    return close_count(api, visit["id"], headers)


def create_paid_center_visit(
    api: ApiClient,
    center_id: str,
    machine_id: str,
    product_id: str,
    quantities: List[int],
    account_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Walk a centre visit all the way to PAID."""
    headers = make_center_headers(center_id)
    visit = create_counted_center_visit(
        api, center_id, machine_id, product_id, quantities, account_id
    )
    payout_action(api, visit["id"], "APPROVE", headers)
    return payout_action(api, visit["id"], "PAY", headers)


# ─── Tier 3: machine sessions and jams ──────────────────────────────────────


def machine_event(
    api: ApiClient,
    machine_id: str,
    event_type: str,
    headers: Dict[str, str],
    visit_id: Optional[str] = None,
    note: Optional[str] = None,
) -> Dict[str, Any]:
    return get_success_data(
        api.post_machine_event(
            machine_id, f.machine_event_payload(event_type, visit_id, note), headers
        )
    )


def open_session(
    api: ApiClient, machine_id: str, visit_id: str, headers: Dict[str, str]
) -> Dict[str, Any]:
    return machine_event(api, machine_id, "SESSION_OPEN", headers, visit_id=visit_id)


def report_jam(
    api: ApiClient,
    machine_id: str,
    visit_id: str,
    headers: Dict[str, str],
    note: Optional[str] = None,
) -> Dict[str, Any]:
    return machine_event(
        api, machine_id, "JAM_REPORTED", headers, visit_id=visit_id, note=note
    )


def clear_jam(
    api: ApiClient, machine_id: str, visit_id: str, headers: Dict[str, str]
) -> Dict[str, Any]:
    return machine_event(api, machine_id, "JAM_CLEARED", headers, visit_id=visit_id)


# ─── Tier 3: bag drops ──────────────────────────────────────────────────────


def create_bag_drop(
    api: ApiClient, account_id: str, center_id: str, **overrides: Any
) -> Dict[str, Any]:
    response = api.create_bag_drop(
        f.create_bag_drop_payload(account_id, center_id, **overrides),
        make_center_headers(center_id),
    )
    return get_success_data(response)


def submit_bag_count(
    api: ApiClient,
    bag_drop_id: str,
    counted_quantities: List[int],
    expected_version: Optional[int] = None,
) -> Dict[str, Any]:
    if expected_version is None:
        expected_version = bag_drop_version(api, bag_drop_id, PLANT_COUNTER_HEADERS)
    payload = f.bag_drop_count_payload(counted_quantities, expected_version)
    return get_success_data(
        api.post_bag_drop_count_result(bag_drop_id, payload, PLANT_COUNTER_HEADERS)
    )


def settle_bag(
    api: ApiClient,
    bag_drop_id: str,
    action: str,
    headers: Dict[str, str],
    reason: Optional[str] = None,
) -> Dict[str, Any]:
    return get_success_data(
        api.post_bag_drop_settlement_action(
            bag_drop_id, f.bag_drop_settlement_payload(action, reason), headers
        )
    )


def create_counted_bag_drop(
    api: ApiClient,
    account_id: str,
    center_id: str,
    counted_quantities: List[int],
    **overrides: Any,
) -> Dict[str, Any]:
    """Accept a bag and submit its plant count, leaving it COUNTED."""
    bag = create_bag_drop(api, account_id, center_id, **overrides)
    return submit_bag_count(api, bag["id"], counted_quantities)


# ─── Tier 3: commodity batches ──────────────────────────────────────────────


def create_batch(
    api: ApiClient, center_id: str, container_count: int, **overrides: Any
) -> Dict[str, Any]:
    response = api.create_commodity_batch(
        f.create_commodity_batch_payload(center_id, container_count, **overrides),
        make_center_headers(center_id),
    )
    return get_success_data(response)


def sort_batch(
    api: ApiClient, batch_id: str, contamination_pct: float
) -> Dict[str, Any]:
    return get_success_data(
        api.post_batch_processing_action(
            batch_id, f.sort_action_payload(contamination_pct), PLANT_COUNTER_HEADERS
        )
    )


def bale_batch(
    api: ApiClient, batch_id: str, bale_weights_kg: List[float]
) -> Dict[str, Any]:
    return get_success_data(
        api.post_batch_processing_action(
            batch_id, f.bale_action_payload(bale_weights_kg), PLANT_COUNTER_HEADERS
        )
    )


def sell_batch(
    api: ApiClient,
    batch_id: str,
    center_id: str,
    pricing_mode: str,
    quoted_price_cents_per_tonne: int,
    period_id: str,
) -> Dict[str, Any]:
    payload = f.batch_sale_payload(
        pricing_mode, quoted_price_cents_per_tonne, period_id
    )
    return get_success_data(
        api.sell_commodity_batch(batch_id, payload, make_center_headers(center_id))
    )


def create_baled_batch(
    api: ApiClient,
    center_id: str,
    container_count: int,
    contamination_pct: float,
    bale_weights_kg: List[float],
    **overrides: Any,
) -> Dict[str, Any]:
    """Draw a batch and walk it ACCUMULATING → SORTED → BALED."""
    batch = create_batch(api, center_id, container_count, **overrides)
    sort_batch(api, batch["id"], contamination_pct)
    return bale_batch(api, batch["id"], bale_weights_kg)


# ─── Tier 4/5: deposits, credits and period settlement ──────────────────────


def initiate_deposits(
    api: ApiClient,
    distributor_id: str,
    product_id: str,
    container_count: int,
    period_id: str,
) -> Dict[str, Any]:
    payload = f.deposit_initiation_payload(product_id, container_count, period_id)
    return get_success_data(
        api.create_deposit_initiation(
            distributor_id, payload, make_distributor_headers(distributor_id)
        )
    )


def post_credit_action(
    api: ApiClient,
    account_id: str,
    action: str,
    amount_cents: int,
    headers: Dict[str, str],
    expected_version: Optional[int] = None,
    memo: Optional[str] = None,
) -> Dict[str, Any]:
    if expected_version is None:
        expected_version = account_version(api, account_id, headers)
    payload = f.credit_action_payload(action, amount_cents, expected_version, memo)
    return get_success_data(api.post_credit_action(account_id, payload, headers))


def account_status_change(
    api: ApiClient, account_id: str, action: str, reason: Optional[str] = None
) -> Dict[str, Any]:
    return get_success_data(
        api.post_account_status_change(
            account_id, f.account_status_change_payload(action, reason), ADMIN_HEADERS
        )
    )


def center_status_change(
    api: ApiClient,
    center_id: str,
    action: str,
    headers: Optional[Dict[str, str]] = None,
    reason: Optional[str] = None,
) -> Dict[str, Any]:
    return get_success_data(
        api.post_center_status_change(
            center_id,
            f.center_status_change_payload(action, reason),
            headers or ADMIN_HEADERS,
        )
    )


def exemption_action(
    api: ApiClient, retailer_id: str, action: str, headers: Dict[str, str]
) -> Dict[str, Any]:
    return get_success_data(
        api.post_exemption_action(
            retailer_id, f.exemption_action_payload(action), headers
        )
    )


def period_action(
    api: ApiClient, period_id: str, action: str, reason: Optional[str] = None
) -> Dict[str, Any]:
    return get_success_data(
        api.post_period_action(
            period_id, f.period_action_payload(action, reason), ADMIN_HEADERS
        )
    )


def list_ledger(api: ApiClient, period_id: str, **params: Any) -> List[Dict[str, Any]]:
    response = api.list_ledger_entries(period_id, ADMIN_HEADERS, params or None)
    return get_success_data(response)


def list_credit_journal(
    api: ApiClient, account_id: str, headers: Dict[str, str], **params: Any
) -> List[Dict[str, Any]]:
    response = api.list_credit_entries(account_id, headers, params or None)
    return get_success_data(response)


def list_lots(
    api: ApiClient, visit_id: str, headers: Dict[str, str], **params: Any
) -> List[Dict[str, Any]]:
    response = api.list_visit_lots(visit_id, headers, params or None)
    return get_success_data(response)


# ─── The shared world ───────────────────────────────────────────────────────


@dataclass
class World:
    """The base world most chains start from.

    Clock at 2026-08-05T09:00:00Z; an ACTIVE distributor with one REGISTERED
    500 ml PET water label; an OPERATIONAL centre at the grid origin with a
    300-container daily account cap, 50000 cents of opening cash and one IDLE
    PET machine; an ACTIVE bag-drop-enrolled account; and an OPEN 2026Q3
    reporting quarter.
    """

    distributor: Dict[str, Any]
    product: Dict[str, Any]
    center: Dict[str, Any]
    machine: Dict[str, Any]
    account: Dict[str, Any]
    period: Dict[str, Any]

    @property
    def distributor_id(self) -> str:
        return self.distributor["id"]

    @property
    def product_id(self) -> str:
        return self.product["id"]

    @property
    def center_id(self) -> str:
        return self.center["id"]

    @property
    def machine_id(self) -> str:
        return self.machine["id"]

    @property
    def account_id(self) -> str:
        return self.account["id"]

    @property
    def period_id(self) -> str:
        return self.period["id"]

    @property
    def center_headers(self) -> Dict[str, str]:
        return make_center_headers(self.center_id)

    @property
    def distributor_headers(self) -> Dict[str, str]:
        return make_distributor_headers(self.distributor_id)

    @property
    def account_headers(self) -> Dict[str, str]:
        return make_account_headers(self.account_id)


def build_world(
    api: ApiClient,
    instant: str = SHARED_WORLD_INSTANT,
    center_overrides: Optional[Dict[str, Any]] = None,
    machine_overrides: Optional[Dict[str, Any]] = None,
    account_overrides: Optional[Dict[str, Any]] = None,
    period_overrides: Optional[Dict[str, Any]] = None,
) -> World:
    """Build the shared world, letting a caller vary any single dimension."""
    set_clock(api, instant)
    distributor = create_distributor(api)
    product = create_registered_product(api, distributor["id"])
    center_payload = {
        "site_name": "Cascade Redemption Center",
        "daily_account_cap_containers": 300,
        "opening_cash_cents": 50000,
    }
    center_payload.update(center_overrides or {})
    fleet = create_operational_center(api, center_payload, machine_overrides)
    account_payload = {"bag_drop_enrolled": True}
    account_payload.update(account_overrides or {})
    account = create_account(api, **account_payload)
    period = create_period(api, **(period_overrides or {}))
    return World(
        distributor=distributor,
        product=product,
        center=fleet["center"],
        machine=fleet["machine"],
        account=account,
        period=period,
    )


# ─── Pytest fixtures ────────────────────────────────────────────────────────


@pytest.fixture
def world(api: ApiClient) -> World:
    """The shared world described on :class:`World`."""
    return build_world(api)


@pytest.fixture
def distributor(api: ApiClient) -> Dict[str, Any]:
    set_clock(api, SHARED_WORLD_INSTANT)
    return create_distributor(api)


@pytest.fixture
def registered_product(api: ApiClient, distributor: Dict[str, Any]) -> Dict[str, Any]:
    return create_registered_product(api, distributor["id"])


@pytest.fixture
def operational_center(api: ApiClient) -> Dict[str, Any]:
    """An OPERATIONAL centre with one IDLE PET machine and 50000 cents of cash."""
    set_clock(api, SHARED_WORLD_INSTANT)
    return create_operational_center(
        api,
        {"daily_account_cap_containers": 300, "opening_cash_cents": 50000},
    )


@pytest.fixture
def open_period(api: ApiClient) -> Dict[str, Any]:
    return create_period(api)


@pytest.fixture
def enrolled_account(api: ApiClient) -> Dict[str, Any]:
    return create_account(api, bag_drop_enrolled=True)


@pytest.fixture
def obligated_retailer(api: ApiClient) -> Dict[str, Any]:
    return create_retailer(api)


@pytest.fixture
def counted_visit(api: ApiClient, world: World) -> Dict[str, Any]:
    """An attributed machine-counted centre visit closed with one 100-lot."""
    return create_counted_center_visit(
        api,
        world.center_id,
        world.machine_id,
        world.product_id,
        [100],
        world.account_id,
    )


@pytest.fixture
def counted_bag_drop(api: ApiClient, world: World) -> Dict[str, Any]:
    """A bag declared at 100 containers and counted as [60, 40]."""
    return create_counted_bag_drop(api, world.account_id, world.center_id, [60, 40])
