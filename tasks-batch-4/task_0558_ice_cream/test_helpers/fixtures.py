"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) internally so setup failures surface
as clear "Setup failed" errors rather than confusing assertion failures. Every
helper builds its preconditions from scratch — each test runs against an empty
database with the logical clock at its 2026-05-01T00:00:00Z startup default.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_flavor_payload, create_size_option_payload, create_topping_payload,
    create_event_cart_payload, create_decorating_station_payload, create_batch_payload,
    create_waste_event_payload, create_loyalty_account_payload, create_drawer_payload,
    create_order_payload, create_order_line_payload, create_pre_order_payload,
    create_catering_booking_payload,
)
from .test_users import TEST_USERS

MGR = TEST_USERS["manager_headers"]
LEAD = TEST_USERS["shift_lead_headers"]
SCOOP = TEST_USERS["scooper_headers"]
BAKER = TEST_USERS["baker_headers"]


# ─── Clock ────────────────────────────────────────────
def set_clock(iso: str):
    return get_success_data(api_client.set_clock({"to_iso8601": iso}, MGR))


# ─── Tier 1: single-entity builders ───────────────────
def make_flavor(**overrides) -> dict:
    return get_success_data(api_client.create_flavor(create_flavor_payload(**overrides), MGR))


def make_size(**overrides) -> dict:
    return get_success_data(api_client.create_size_option(create_size_option_payload(**overrides), MGR))


def make_topping(**overrides) -> dict:
    return get_success_data(api_client.create_topping(create_topping_payload(**overrides), MGR))


def make_event_cart(**overrides) -> dict:
    return get_success_data(api_client.create_event_cart(create_event_cart_payload(**overrides), MGR))


def make_station(**overrides) -> dict:
    return get_success_data(api_client.create_decorating_station(create_decorating_station_payload(**overrides), MGR))


def make_loyalty(**overrides) -> dict:
    return get_success_data(api_client.create_loyalty_account(create_loyalty_account_payload(**overrides), MGR))


def make_batch(flavor_id: str, release: bool = True, **overrides) -> dict:
    """Produce a batch (PREP). When release=True, also release it to AVAILABLE."""
    batch = get_success_data(api_client.create_batch(create_batch_payload(flavor_id, **overrides), BAKER))
    if release:
        batch = get_success_data(api_client.release_batch(batch["id"], BAKER))
    return batch


def open_drawer(opening_float_cents: int = 10000) -> dict:
    return get_success_data(api_client.create_drawer(create_drawer_payload(opening_float_cents=opening_float_cents), LEAD))


def open_order(drawer_id: str, loyalty_account_id: str = None) -> dict:
    payload = create_order_payload(drawer_id)
    if loyalty_account_id is not None:
        payload["loyalty_account_id"] = loyalty_account_id
    return get_success_data(api_client.create_order(payload, SCOOP))


def add_line(order_id: str, size_option_id: str, flavor_id: str, **overrides) -> dict:
    return get_success_data(api_client.add_line(
        order_id, create_order_line_payload(size_option_id, flavor_id, **overrides), SCOOP))


def pay(order_id: str, payment_method: str = "CARD", tendered_cash_cents: int = None) -> dict:
    payload = {"payment_method": payment_method}
    if tendered_cash_cents is not None:
        payload["tendered_cash_cents"] = tendered_cash_cents
    return get_success_data(api_client.pay_order(order_id, payload, SCOOP))


def make_pre_order(flavor_id: str, station_id: str, **overrides) -> dict:
    return get_success_data(api_client.create_pre_order(
        create_pre_order_payload(flavor_id, station_id, **overrides), SCOOP))


def make_booking(event_cart_id: str, requested_items, **overrides) -> dict:
    return get_success_data(api_client.create_catering_booking(
        create_catering_booking_payload(event_cart_id, requested_items, **overrides), MGR))


# ─── Tier 2: composite POS scenarios ──────────────────
def setup_pos_line_scenario(flavor_overrides=None, size_overrides=None, batch_overrides=None,
                            loyalty_account_id=None):
    """Active flavor + released batch + size option + OPEN drawer + OPEN order.

    Returns dict with keys: flavor, size, batch, drawer, order. No line added yet.
    """
    flavor = make_flavor(**(flavor_overrides or {}))
    size = make_size(**(size_overrides or {}))
    batch = make_batch(flavor["id"], **(batch_overrides or {}))
    drawer = open_drawer()
    order = open_order(drawer["id"], loyalty_account_id=loyalty_account_id)
    return {"flavor": flavor, "size": size, "batch": batch, "drawer": drawer, "order": order}


def setup_paid_double_order(flavor_par=500, batch_initial=180, batch_unit_cost=1.80,
                            payment_method="CARD", tendered_cash_cents=None):
    """Flavor + DOUBLE size + one released batch + drawer + order with a single
    DOUBLE line, then PAY. Returns dict: flavor, size, batch, drawer, order (paid), line_id.
    """
    scenario = setup_pos_line_scenario(
        flavor_overrides={"par_level_ml": flavor_par},
        size_overrides={"code": "DOUBLE", "scoop_count": 2, "base_price_cents": 550},
        batch_overrides={"initial_volume_ml": batch_initial, "unit_cost_cents_per_ml": batch_unit_cost},
    )
    line = add_line(scenario["order"]["id"], scenario["size"]["id"], scenario["flavor"]["id"])
    order = pay(scenario["order"]["id"], payment_method=payment_method, tendered_cash_cents=tendered_cash_cents)
    scenario["line_id"] = line["id"]
    scenario["order"] = order
    return scenario


# ─── Tier 3: PreOrder lifecycle shortcuts ─────────────
def setup_preorder(flavor_overrides=None, station_name="Station 1", with_batch=False,
                   preorder_overrides=None):
    """Flavor (+ optional released batch) + station + a QUOTED pre-order.

    Returns dict: flavor, station, pre_order (and batch if with_batch).
    """
    flavor = make_flavor(**(flavor_overrides or {}))
    result = {"flavor": flavor}
    if with_batch:
        result["batch"] = make_batch(flavor["id"], initial_volume_ml=500)
    station = make_station(name=station_name)
    pre_order = make_pre_order(flavor["id"], station["id"], **(preorder_overrides or {}))
    result["station"] = station
    result["pre_order"] = pre_order
    return result


def drive_preorder_to(pre_order_id: str, target: str):
    """Walk a QUOTED pre-order forward to a target state via the lifecycle triggers.

    Supported targets: CONFIRMED, IN_PRODUCTION, FULFILLED.
    """
    if target in ("CONFIRMED", "IN_PRODUCTION", "FULFILLED"):
        get_success_data(api_client.confirm_pre_order(pre_order_id, SCOOP))
    if target in ("IN_PRODUCTION", "FULFILLED"):
        get_success_data(api_client.start_production(pre_order_id, BAKER))
    if target == "FULFILLED":
        get_success_data(api_client.fulfill_pre_order(pre_order_id, SCOOP))
    return get_success_data(api_client.get_pre_order(pre_order_id, MGR))


# ─── Tier 4: Catering scenario ────────────────────────
def setup_booking(flavor_volume_ml=500, batch_initial=1000, cart_capacity=5000,
                  event_start="2026-05-02T10:00:00Z", event_end="2026-05-02T12:00:00Z"):
    """Vanilla flavor + released batch + event cart + one BOOKED booking.

    Returns dict: flavor, batch, cart, booking.
    """
    flavor = make_flavor(par_level_ml=300)
    batch = make_batch(flavor["id"], initial_volume_ml=batch_initial,
                       expiry_at="2026-05-30T00:00:00Z")
    cart = make_event_cart(capacity_ml=cart_capacity)
    booking = make_booking(
        cart["id"],
        [{"flavor_id": flavor["id"], "volume_ml": flavor_volume_ml}],
        event_start_utc=event_start, event_end_utc=event_end,
    )
    return {"flavor": flavor, "batch": batch, "cart": cart, "booking": booking}


# ─── Fresh-read convenience wrappers ──────────────────
def get_flavor(flavor_id: str) -> dict:
    return get_success_data(api_client.get_flavor(flavor_id, MGR))


def get_batch(batch_id: str) -> dict:
    return get_success_data(api_client.get_batch(batch_id, MGR))


def get_order(order_id: str) -> dict:
    return get_success_data(api_client.get_order(order_id, MGR))


def get_order_line(line_id: str) -> dict:
    return get_success_data(api_client.get_order_line(line_id, MGR))


def get_drawer(drawer_id: str) -> dict:
    return get_success_data(api_client.get_drawer(drawer_id, MGR))


def get_loyalty(account_id: str) -> dict:
    return get_success_data(api_client.get_loyalty_account(account_id, MGR))


def get_pre_order(pre_order_id: str) -> dict:
    return get_success_data(api_client.get_pre_order(pre_order_id, MGR))


def get_booking(booking_id: str) -> dict:
    return get_success_data(api_client.get_catering_booking(booking_id, MGR))
