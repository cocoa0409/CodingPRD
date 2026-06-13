"""Composite setup helpers.

Each test runs against a freshly-restarted, empty server, so every fixture builds
its preconditions from scratch using only PRD-declared endpoints. Fixtures use
get_success_data() (lenient) so setup failures surface as clear "Setup failed".

Role/identity threading: the only entity-backed role is Customer. Whenever a
fixture performs an ownership-gated Customer call (placing or cancelling that
customer's own order / claim), it threads the actual Customer.id through
make_customer_headers(customer_id). All operator calls use the shared headers.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import TEST_USERS, make_customer_headers
from .factories import (
    create_customer_payload,
    create_cut_type_payload,
    create_pricing_policy_payload,
    create_inventory_lot_payload,
    create_locker_payload,
    create_temp_reading_payload,
    create_animal_share_payload,
    create_share_claim_payload,
    create_holiday_window_payload,
    create_custom_order_payload,
    order_line_payload,
    create_sausage_batch_payload,
    add_batch_input_payload,
)

# Shared header shortcuts.
MGR = TEST_USERS["shift_manager_headers"]
CLERK = TEST_USERS["counter_clerk_headers"]
BUTCHER = TEST_USERS["butcher_headers"]
SAFETY = TEST_USERS["safety_officer_headers"]


# ===========================================================================
# Tier 0: primitives
# ===========================================================================
def ensure_pricing_policy(**overrides):
    """Create and activate a pricing policy. Returns the policy dict."""
    return get_success_data(
        api_client.create_pricing_policy(create_pricing_policy_payload(**overrides), MGR)
    )


def create_cut_type(**overrides):
    """Create a cut type. Returns the cut type dict."""
    return get_success_data(
        api_client.create_cut_type(create_cut_type_payload(**overrides), MGR)
    )


def create_customer(**overrides):
    """Register a customer. Returns the customer dict."""
    return get_success_data(
        api_client.create_customer(create_customer_payload(**overrides), CLERK)
    )


def receive_lot(cut_type_id, received_weight_g=5000, **overrides):
    """Receive an AVAILABLE InventoryLot. Returns the lot dict (with version)."""
    payload = create_inventory_lot_payload(
        cut_type_id=cut_type_id, received_weight_g=received_weight_g, **overrides
    )
    return get_success_data(api_client.create_inventory_lot(payload, BUTCHER))


def create_locker(**overrides):
    """Create an OPERATIONAL DryAgeLocker. Returns the locker dict."""
    return get_success_data(api_client.create_locker(create_locker_payload(**overrides), MGR))


def set_clock(to_iso8601):
    """Set the server's logical UTC clock."""
    return get_success_data(api_client.set_clock(to_iso8601, MGR))


def create_holiday_window(**overrides):
    """Create a holiday window. Returns the window dict."""
    return get_success_data(
        api_client.create_holiday_window(create_holiday_window_payload(**overrides), MGR)
    )


def create_animal_share(**overrides):
    """Open an AnimalShare. Returns the share dict."""
    return get_success_data(
        api_client.create_animal_share(create_animal_share_payload(**overrides), MGR)
    )


# ===========================================================================
# Tier 1: orders
# ===========================================================================
def place_order(customer_id, lines, order_kind="STANDARD", **overrides):
    """Place a custom order on behalf of `customer_id`.

    `lines` is a list of (cut_type_id, ordered_weight_g) tuples. Returns the
    order dict. Placement is performed via CounterClerk acting on the customer's
    behalf (PRD §3.5 allows the clerk to place on behalf of a customer).
    """
    line_payloads = [order_line_payload(ct, g) for (ct, g) in lines]
    payload = create_custom_order_payload(
        customer_id=customer_id, order_kind=order_kind, lines=line_payloads, **overrides
    )
    return get_success_data(api_client.create_custom_order(payload, CLERK))


def get_order_line_ids(order_id):
    """Return the ordered list of OrderLine ids for an order."""
    data, _ = _list(api_client.list_order_lines_for_order(order_id, CLERK))
    return [row["id"] for row in data]


def place_and_confirm_order(customer_id, lines, order_kind="STANDARD", **overrides):
    """Place an order and advance it to CONFIRMED.

    Returns (order_dict, line_ids). The confirm is a CounterClerk operation.
    """
    order = place_order(customer_id, lines, order_kind=order_kind, **overrides)
    line_ids = get_order_line_ids(order["id"])
    get_success_data(api_client.confirm_order(order["id"], CLERK))
    return order, line_ids


def setup_standard_order_ready_to_draw(
    cut_type_overrides=None, ordered_weight_g=2000, customer_overrides=None
):
    """Active policy + cut type + customer + a CONFIRMED single-line STANDARD order.

    Returns dict with keys: cut_type, customer, order, line_id. No lot is
    created here (the caller controls the lot weight/state under test).
    """
    ensure_pricing_policy()
    cut_type = create_cut_type(**(cut_type_overrides or {}))
    customer = create_customer(**(customer_overrides or {}))
    order, line_ids = place_and_confirm_order(
        customer["id"], [(cut_type["id"], ordered_weight_g)]
    )
    return {
        "cut_type": cut_type,
        "customer": customer,
        "order": order,
        "line_id": line_ids[0],
    }


# ===========================================================================
# Tier 2: aging / lockers
# ===========================================================================
def start_aging(lot_id, locker_id):
    """Move an AVAILABLE lot into a locker (AVAILABLE -> AGING). Returns the lot."""
    return get_success_data(
        api_client.start_aging(lot_id, {"locker_id": locker_id}, BUTCHER)
    )


def setup_aging_lot(
    cut_overrides=None,
    locker_overrides=None,
    received_weight_g=5000,
    aging_target_days=7,
    aging_started_iso="2026-06-01T00:00:00Z",
):
    """A requires_dry_age cut, an OPERATIONAL locker, and one AGING lot inside it.

    Sets the clock to aging_started_iso before start-aging so aging_started_at is
    deterministic. Returns dict: cut_type, locker, lot (post-start-aging).
    """
    cut_defaults = {"code": "DRY_RIBEYE", "base_price_cents_per_kg": 6000, "requires_dry_age": True}
    cut_defaults.update(cut_overrides or {})
    cut_type = create_cut_type(**cut_defaults)
    locker = create_locker(**(locker_overrides or {}))
    set_clock(aging_started_iso)
    lot = receive_lot(cut_type["id"], received_weight_g=received_weight_g,
                      aging_target_days=aging_target_days)
    lot = start_aging(lot["id"], locker["id"])
    return {"cut_type": cut_type, "locker": locker, "lot": lot}


def setup_quarantined_locker_with_held_lot(
    cut_overrides=None,
    locker_overrides=None,
    received_weight_g=5000,
    aging_target_days=7,
    excursion_temp_c=10.0,
    reading_at="2026-06-02T00:00:00Z",
    aging_started_iso="2026-06-01T00:00:00Z",
):
    """An AGING lot, then an out-of-band reading that quarantines the locker and
    holds the lot (AGING -> ON_HOLD).

    Returns dict: cut_type, locker (QUARANTINED), lot (ON_HOLD), reading.
    """
    base = setup_aging_lot(
        cut_overrides=cut_overrides,
        locker_overrides=locker_overrides,
        received_weight_g=received_weight_g,
        aging_target_days=aging_target_days,
        aging_started_iso=aging_started_iso,
    )
    reading = get_success_data(
        api_client.create_temp_reading(
            base["locker"]["id"],
            create_temp_reading_payload(temp_c=excursion_temp_c, reading_at=reading_at),
            SAFETY,
        )
    )
    locker = get_success_data(api_client.get_locker(base["locker"]["id"], MGR))
    lot = get_success_data(api_client.get_inventory_lot(base["lot"]["id"], BUTCHER))
    return {"cut_type": base["cut_type"], "locker": locker, "lot": lot, "reading": reading}


# ===========================================================================
# Tier 3: shares / claims
# ===========================================================================
def claim_share(share_id, customer_id, fraction):
    """Place a ShareClaim on behalf of the customer (clerk on behalf). Returns claim."""
    payload = create_share_claim_payload(
        animal_share_id=share_id, customer_id=customer_id, fraction=fraction
    )
    return get_success_data(api_client.create_share_claim(payload, CLERK))


def setup_share_with_claims(carcass_weight_g=100000, deposit_cents=8000, claims=None):
    """An AnimalShare plus one customer-and-claim per entry in `claims`.

    `claims` is a list of fraction strings ("QUARTER"/"HALF"). For each, a new
    customer is created and a claim placed. Returns dict:
      share, customers (list), claims (list of claim dicts).
    """
    share = create_animal_share(carcass_weight_g=carcass_weight_g, deposit_cents=deposit_cents)
    customers = []
    claim_rows = []
    for i, fraction in enumerate(claims or []):
        cust = create_customer(full_name=f"Claimant {i}", phone=f"555-90{i:02d}")
        customers.append(cust)
        claim_rows.append(claim_share(share["id"], cust["id"], fraction))
    share = get_success_data(api_client.get_animal_share(share["id"], MGR))
    return {"share": share, "customers": customers, "claims": claim_rows}


# ===========================================================================
# Tier 4: sausage batches
# ===========================================================================
def setup_reserved_batch(grind_overrides=None, input_lots=None, planned_output_g=5000,
                         recipe_name="Test Recipe"):
    """A grind output cut, input lots, a batch with those inputs, RESERVED.

    `input_lots` is a list of (cut_type_id_or_None, weight_received, weight_input)
    tuples. When the cut id is None a default non-grind PORK_TRIM cut is created
    once and shared. Returns dict:
      output_cut, trim_cut, lots (list), batch (RESERVED).
    """
    ensure_pricing_policy()
    grind_defaults = {"code": "GROUND_BLEND", "species": "PORK",
                      "base_price_cents_per_kg": 1200, "is_grind": True}
    grind_defaults.update(grind_overrides or {})
    output_cut = create_cut_type(**grind_defaults)
    trim_cut = create_cut_type(code="PORK_TRIM", species="PORK", base_price_cents_per_kg=800)

    lots = []
    inputs = []
    for (recv, inp) in (input_lots or []):
        lot = receive_lot(trim_cut["id"], received_weight_g=recv)
        lots.append(lot)
        inputs.append((lot["id"], inp))

    batch = get_success_data(
        api_client.create_sausage_batch(
            create_sausage_batch_payload(
                recipe_name=recipe_name,
                output_cut_type_id=output_cut["id"],
                planned_output_g=planned_output_g,
            ),
            BUTCHER,
        )
    )
    for (lot_id, weight_g) in inputs:
        get_success_data(
            api_client.add_batch_input(
                batch["id"],
                add_batch_input_payload(inventory_lot_id=lot_id, weight_g=weight_g),
                BUTCHER,
            )
        )
    batch = get_success_data(api_client.reserve_batch(batch["id"], BUTCHER))
    return {"output_cut": output_cut, "trim_cut": trim_cut, "lots": lots, "batch": batch}


# ===========================================================================
# Tier 5: holiday orders
# ===========================================================================
def setup_holiday_window_before_cutoff(
    capacity_g=100000,
    cutoff_at="2026-11-20T00:00:00Z",
    now_iso="2026-11-19T00:00:00Z",
    pickup_date="2026-11-26T00:00:00Z",
    name="THANKSGIVING_2026",
):
    """Active policy + RIBEYE cut + a holiday window, clock set before cutoff.

    Returns dict: cut_type, window.
    """
    ensure_pricing_policy()
    cut_type = create_cut_type(code="RIBEYE", species="BEEF", base_price_cents_per_kg=4000)
    set_clock(now_iso)
    window = create_holiday_window(
        name=name, pickup_date=pickup_date, capacity_g=capacity_g, cutoff_at=cutoff_at
    )
    return {"cut_type": cut_type, "window": window}


def place_holiday_order(customer_id, window_id, lines, pickup_date="2026-11-26T00:00:00Z"):
    """Place a HOLIDAY order on the customer's behalf. Returns the order dict."""
    return place_order(
        customer_id,
        lines,
        order_kind="HOLIDAY",
        holiday_window_id=window_id,
        pickup_date=pickup_date,
    )


# ===========================================================================
# Helpers
# ===========================================================================
def _list(response):
    """Unpack a paginated list response into (data, meta) using lenient parse."""
    body = response.json()
    return body["data"], body.get("meta", {})


def make_customer_headers_for(customer):
    """Convenience: entity-backed Customer headers for the given customer dict."""
    return make_customer_headers(customer["id"])
