"""Composite setup helpers (PRD §3 workflows).

Each helper builds preconditions from scratch using only PRD-declared
endpoints; every test runs against a fresh server. Setup calls use the
lenient get_success_data() validator so failures surface as clear
"Setup step failed" errors.

Common composite preambles:
  setup_stop_received          — plant (+category, +customer) through pickup + receive
  setup_batch                  — sort batch with classification rows
  setup_finished_load          — full pipeline through a FINISHED wash load
  setup_delivery_delivered     — through a DELIVERED delivery
  setup_discrepancy_approved   — through an APPROVED discrepancy
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client as _api
from .factories import (
    create_plant_payload, create_linen_category_payload, create_customer_payload,
    create_route_payload, create_stop_payload, pickup_payload,
    create_sort_batch_payload, create_sort_item_payload, create_wash_load_payload,
    create_finish_run_payload, register_garment_payload, create_delivery_payload,
    mark_delivered_payload, file_dispute_payload, generate_invoice_payload,
    create_utility_reading_payload,
)
from .test_users import TEST_USERS, make_customer_contact_headers

ADMIN = TEST_USERS["plant_admin_headers"]
DRIVER = TEST_USERS["route_driver_headers"]
OPERATOR = TEST_USERS["plant_operator_headers"]
CSR = TEST_USERS["csr_headers"]
CLERK = TEST_USERS["billing_clerk_headers"]


# ---------------------------------------------------------------------------
# Tier 1: single-resource creators
# ---------------------------------------------------------------------------

def create_plant(**overrides):
    resp = _api.create_plant(create_plant_payload(**overrides), ADMIN)
    return get_success_data(resp)


def create_linen_category(plant_id, **overrides):
    resp = _api.create_linen_category(plant_id, create_linen_category_payload(**overrides), ADMIN)
    return get_success_data(resp)


def create_customer(plant_id, **overrides):
    resp = _api.create_customer(plant_id, create_customer_payload(**overrides), ADMIN)
    return get_success_data(resp)


def create_route(plant_id, **overrides):
    resp = _api.create_route(plant_id, create_route_payload(**overrides), DRIVER)
    return get_success_data(resp)


def create_stop(route_id, customer_id, **overrides):
    resp = _api.create_stop(route_id, create_stop_payload(customer_id, **overrides), DRIVER)
    return get_success_data(resp)


def set_par_level(customer_id, category_id, par_pieces):
    resp = _api.upsert_par_level(customer_id, category_id, {"par_pieces": par_pieces}, ADMIN)
    return get_success_data(resp)


def register_garment(customer_id, category_id, chip_code):
    resp = _api.register_garment(
        register_garment_payload(customer_id, category_id, chip_code), ADMIN
    )
    return get_success_data(resp)


def post_utility_reading(plant_id, **overrides):
    resp = _api.create_utility_reading(
        plant_id, create_utility_reading_payload(**overrides), CLERK
    )
    return get_success_data(resp)


def set_logical_clock(to_iso8601):
    resp = _api.set_clock({"to_iso8601": to_iso8601}, ADMIN)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 1.5: readers
# ---------------------------------------------------------------------------

def get_customer(customer_id, headers=CLERK):
    return get_success_data(_api.get_customer(customer_id, headers))


def get_customer_version(customer_id, headers=CLERK):
    return get_customer(customer_id, headers)["version"]


def get_stop(stop_id, headers=DRIVER):
    return get_success_data(_api.get_stop(stop_id, headers))


def list_carts(stop_id, headers=OPERATOR):
    return get_success_data(_api.list_carts(stop_id, headers))


def find_cart_by_tag(carts, cart_tag):
    """Pick a cart out of a stop's cart list by its physical tag (list order
    is created_at-based, and carts created in one pickup share a timestamp)."""
    matches = [c for c in carts if c.get("cart_tag") == cart_tag]
    assert len(matches) == 1, f"expected exactly one cart tagged {cart_tag!r}"
    return matches[0]


def get_sort_batch(batch_id, headers=OPERATOR):
    return get_success_data(_api.get_sort_batch(batch_id, headers))


def get_wash_load(load_id, headers=OPERATOR):
    return get_success_data(_api.get_wash_load(load_id, headers))


def get_garment(garment_id, headers=OPERATOR):
    return get_success_data(_api.get_garment(garment_id, headers))


def get_delivery(delivery_id, headers=DRIVER):
    return get_success_data(_api.get_delivery(delivery_id, headers))


def get_discrepancy(discrepancy_id, headers=CLERK):
    return get_success_data(_api.get_discrepancy(discrepancy_id, headers))


def get_invoice(invoice_id, headers=CLERK):
    return get_success_data(_api.get_invoice(invoice_id, headers))


def list_par_levels(customer_id, headers=DRIVER):
    return get_success_data(_api.list_par_levels(customer_id, headers))


def get_on_site_pieces(customer_id, category_id, headers=DRIVER):
    rows = list_par_levels(customer_id, headers)
    matches = [r for r in rows if r.get("category_id") == category_id]
    assert len(matches) == 1, f"expected one par row for category {category_id}"
    return matches[0]["current_on_site_pieces"]


# ---------------------------------------------------------------------------
# Tier 2: route/stop progression
# ---------------------------------------------------------------------------

def create_route_with_stop(plant_id, customer_id, route_overrides=None, stop_overrides=None):
    route = create_route(plant_id, **(route_overrides or {}))
    stop = create_stop(route["id"], customer_id, **(stop_overrides or {}))
    return route, stop


def dispatch_route(route_id):
    return get_success_data(_api.dispatch_route(route_id, DRIVER))


def arrive_stop(stop_id):
    return get_success_data(_api.arrive_stop(stop_id, DRIVER))


def pickup_stop(stop_id, carts=None):
    return get_success_data(_api.pickup_stop(stop_id, pickup_payload(carts), DRIVER))


def receive_cart(cart_id):
    return get_success_data(_api.receive_cart(cart_id, OPERATOR))


def receive_stop_carts(stop_id):
    carts = list_carts(stop_id)
    for cart in carts:
        receive_cart(cart["id"])
    # Re-list so callers observe the post-receive state (RECEIVED), not the
    # stale pre-receive snapshot.
    return list_carts(stop_id)


def drive_stop_to_picked_up(stop_id, carts=None):
    arrive_stop(stop_id)
    return pickup_stop(stop_id, carts)


# ---------------------------------------------------------------------------
# Tier 2.5: the canonical pipeline context
# ---------------------------------------------------------------------------

def setup_stop_received(
    plant_overrides=None,
    category_overrides=None,
    customer_overrides=None,
    route_overrides=None,
    stop_overrides=None,
    carts=None,
    with_category=True,
):
    """Plant (+ category, + customer) -> route -> stop -> dispatch -> arrive
    -> pickup -> receive every cart. Returns a context dict."""
    ctx = {}
    ctx["plant"] = create_plant(**(plant_overrides or {}))
    if with_category:
        ctx["category"] = create_linen_category(
            ctx["plant"]["id"], **(category_overrides or {})
        )
    else:
        ctx["category"] = None
    ctx["customer"] = create_customer(
        ctx["plant"]["id"], **(customer_overrides or {})
    )
    ctx["route"], ctx["stop"] = create_route_with_stop(
        ctx["plant"]["id"], ctx["customer"]["id"],
        route_overrides=route_overrides, stop_overrides=stop_overrides,
    )
    dispatch_route(ctx["route"]["id"])
    drive_stop_to_picked_up(ctx["stop"]["id"], carts)
    ctx["carts"] = receive_stop_carts(ctx["stop"]["id"])
    ctx["stop"] = get_stop(ctx["stop"]["id"])
    return ctx


# ---------------------------------------------------------------------------
# Tier 3: sort batches and wash loads
# ---------------------------------------------------------------------------

def create_batch(stop_id):
    return get_success_data(
        _api.create_sort_batch(create_sort_batch_payload(stop_id), OPERATOR)
    )


def add_sort_item(batch_id, category_id, pieces, disposition="ACCEPTED", reject_reason=None):
    payload = create_sort_item_payload(category_id, pieces, disposition)
    if reject_reason is not None:
        payload["reject_reason"] = reject_reason
    return get_success_data(_api.create_sort_item(batch_id, payload, OPERATOR))


def create_batch_with_items(stop_id, items):
    """items: list of dicts with keys category_id, pieces, disposition,
    reject_reason (optional)."""
    batch = create_batch(stop_id)
    for item in items:
        add_sort_item(
            batch["id"],
            item["category_id"],
            item["pieces"],
            item.get("disposition", "ACCEPTED"),
            item.get("reject_reason"),
        )
    return batch


def lock_batch(batch_id):
    return get_success_data(_api.lock_sort_batch(batch_id, OPERATOR))


def post_batch(batch_id):
    return get_success_data(_api.post_sort_batch(batch_id, OPERATOR))


def create_batch_locked(stop_id, items):
    batch = create_batch_with_items(stop_id, items)
    lock_batch(batch["id"])
    return get_sort_batch(batch["id"])


def create_batch_posted(stop_id, items):
    batch = create_batch_locked(stop_id, items)
    post_batch(batch["id"])
    return get_sort_batch(batch["id"])


def stage_wash_load(batch_id, category_id, **overrides):
    resp = _api.create_wash_load(
        create_wash_load_payload(batch_id, category_id, **overrides), OPERATOR
    )
    return get_success_data(resp)


def drive_load_to_finished(load_id, hygienic_test_required=False):
    """STAGED -> RUNNING -> AWAITING_TEST -> TESTED_PASS -> FINISHED."""
    get_success_data(_api.start_wash_load(load_id, OPERATOR))
    get_success_data(_api.finish_cycle_wash_load(load_id, OPERATOR))
    if hygienic_test_required:
        get_success_data(
            _api.record_test_wash_load(load_id, {"outcome": "PASS"}, OPERATOR)
        )
    else:
        get_success_data(_api.bypass_test_wash_load(load_id, OPERATOR))
    get_success_data(_api.unload_wash_load(load_id, OPERATOR))
    return get_wash_load(load_id)


def setup_finished_load(
    pieces=100,
    plant_overrides=None,
    category_overrides=None,
    customer_overrides=None,
    route_overrides=None,
    stop_overrides=None,
    carts=None,
    load_overrides=None,
    clock_iso=None,
):
    """Full pipeline through one FINISHED wash load of `pieces` ACCEPTED.
    `clock_iso`, when given, sets the logical clock before unload so the
    unload timestamp lands in a chosen month. Returns a context dict."""
    ctx = setup_stop_received(
        plant_overrides=plant_overrides,
        category_overrides=category_overrides,
        customer_overrides=customer_overrides,
        route_overrides=route_overrides,
        stop_overrides=stop_overrides,
        carts=carts,
    )
    ctx["batch"] = create_batch_posted(
        ctx["stop"]["id"],
        [{"category_id": ctx["category"]["id"], "pieces": pieces}],
    )
    ctx["load"] = stage_wash_load(
        ctx["batch"]["id"], ctx["category"]["id"], **(load_overrides or {})
    )
    get_success_data(_api.start_wash_load(ctx["load"]["id"], OPERATOR))
    get_success_data(_api.finish_cycle_wash_load(ctx["load"]["id"], OPERATOR))
    if ctx["category"]["hygienic_test_required"]:
        get_success_data(
            _api.record_test_wash_load(ctx["load"]["id"], {"outcome": "PASS"}, OPERATOR)
        )
    else:
        get_success_data(_api.bypass_test_wash_load(ctx["load"]["id"], OPERATOR))
    if clock_iso is not None:
        set_logical_clock(clock_iso)
    get_success_data(_api.unload_wash_load(ctx["load"]["id"], OPERATOR))
    ctx["load"] = get_wash_load(ctx["load"]["id"])
    return ctx


# ---------------------------------------------------------------------------
# Tier 4: deliveries and disputes
# ---------------------------------------------------------------------------

def manifest_delivery(stop_id, category_id, pieces_promised):
    return get_success_data(
        _api.create_delivery(
            stop_id, create_delivery_payload(category_id, pieces_promised), DRIVER
        )
    )


def mark_delivery_delivered(delivery_id, pieces_delivered, expected_customer_version):
    return get_success_data(
        _api.mark_delivered(
            delivery_id,
            mark_delivered_payload(pieces_delivered, expected_customer_version),
            DRIVER,
        )
    )


def setup_delivery_delivered(
    pieces_promised=10,
    pieces_delivered=8,
    plant_overrides=None,
    category_overrides=None,
    customer_overrides=None,
    carts=None,
):
    """Pipeline through a DELIVERED delivery (carts received first).
    Returns a context dict including ctx['delivery']."""
    ctx = setup_stop_received(
        plant_overrides=plant_overrides,
        category_overrides=category_overrides,
        customer_overrides=customer_overrides,
        carts=carts,
    )
    version = get_customer_version(ctx["customer"]["id"])
    ctx["delivery"] = manifest_delivery(
        ctx["stop"]["id"], ctx["category"]["id"], pieces_promised
    )
    mark_delivery_delivered(ctx["delivery"]["id"], pieces_delivered, version)
    ctx["delivery"] = get_delivery(ctx["delivery"]["id"])
    return ctx


def file_dispute(delivery_id, claimed_shortfall_pieces, customer_id):
    headers = make_customer_contact_headers(customer_id)
    return get_success_data(
        _api.file_dispute(delivery_id, file_dispute_payload(claimed_shortfall_pieces), headers)
    )


def setup_discrepancy_approved(
    pieces_promised=10,
    pieces_delivered=8,
    claimed=2,
    approved=2,
    plant_overrides=None,
    category_overrides=None,
    customer_overrides=None,
):
    """Pipeline through an APPROVED discrepancy. Returns ctx including
    ctx['discrepancy'] (APPROVED) and ctx['delivery'] (DISPUTED)."""
    ctx = setup_delivery_delivered(
        pieces_promised=pieces_promised,
        pieces_delivered=pieces_delivered,
        plant_overrides=plant_overrides,
        category_overrides=category_overrides,
        customer_overrides=customer_overrides,
    )
    ctx["discrepancy"] = file_dispute(
        ctx["delivery"]["id"], claimed, ctx["customer"]["id"]
    )
    get_success_data(_api.start_review_discrepancy(ctx["discrepancy"]["id"], CSR))
    get_success_data(
        _api.approve_discrepancy(
            ctx["discrepancy"]["id"], {"approved_shortfall_pieces": approved}, CSR
        )
    )
    ctx["discrepancy"] = get_discrepancy(ctx["discrepancy"]["id"])
    ctx["delivery"] = get_delivery(ctx["delivery"]["id"])
    return ctx


# ---------------------------------------------------------------------------
# Tier 5: billing
# ---------------------------------------------------------------------------

def generate_invoice(customer_id, **overrides):
    return get_success_data(
        _api.generate_invoice(customer_id, generate_invoice_payload(**overrides), CLERK)
    )


def issue_invoice(invoice_id, expected_customer_version):
    return get_success_data(
        _api.issue_invoice(
            invoice_id, {"expected_customer_version": expected_customer_version}, CLERK
        )
    )


def billing_preview(customer_id, period_start, period_end, **extra_params):
    params = {
        "billing_period_start": period_start,
        "billing_period_end": period_end,
    }
    params.update(extra_params)
    return get_success_data(_api.billing_preview(customer_id, CLERK, params=params))
