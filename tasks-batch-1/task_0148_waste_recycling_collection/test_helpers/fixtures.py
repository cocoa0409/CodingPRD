"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient 2xx validator) internally so setup failures
produce clear "Setup step failed" errors rather than confusing assertion failures.

Identity threading: ResidentAccount is entity-backed by ServiceAccount, so any
ownership-gated resident call uses make_resident_headers(account["id"]) — never the
shared fallback constant.

Default ISO windows used throughout:
  MAY  = [2026-05-01, 2026-06-01)   billing / diversion window
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_account_payload,
    create_cart_payload,
    create_service_plan_payload,
    create_route_payload,
    create_stop_payload,
    create_pickup_payload,
    complete_pickup_payload,
    miss_pickup_payload,
    create_weight_ticket_payload,
    create_contamination_tag_payload,
    create_invoice_payload,
    create_special_pickup_payload,
    create_diversion_period_payload,
)
from .test_users import TEST_USERS, make_resident_headers

DISPATCHER = TEST_USERS["dispatcher_headers"]
DRIVER = TEST_USERS["driver_headers"]
BILLING = TEST_USERS["billing_headers"]

MAY_START = "2026-05-01T00:00:00Z"
MAY_END = "2026-06-01T00:00:00Z"


# ─── Tier 0: atomic creators ──────────────────────────

def create_account(rate_class="RESIDENTIAL", diversion_floor_pct=None, address="1 Test St"):
    """Create a fresh PENDING_SETUP account. Returns the account dict."""
    payload = create_account_payload(service_address=address, rate_class=rate_class)
    if diversion_floor_pct is not None:
        payload["diversion_floor_pct"] = diversion_floor_pct
    return get_success_data(api_client.create_account(payload, DISPATCHER))


def create_cart(account_id, stream="TRASH", size_gallons=65, tare_weight_lbs=None):
    """Create a cart (status ASSIGNED). Returns the cart dict."""
    kwargs = {"stream": stream, "size_gallons": size_gallons}
    if tare_weight_lbs is not None:
        kwargs["tare_weight_lbs"] = tare_weight_lbs
    return get_success_data(
        api_client.create_cart(create_cart_payload(account_id, **kwargs), DISPATCHER)
    )


def create_active_cart(account_id, stream="TRASH", size_gallons=96, tare_weight_lbs=0):
    """Create + activate a cart. Returns the activated cart dict (status ACTIVE)."""
    cart = create_cart(account_id, stream=stream, size_gallons=size_gallons,
                        tare_weight_lbs=tare_weight_lbs)
    return get_success_data(api_client.activate_cart(cart["id"], DISPATCHER))


def create_active_plan(account_id, stream="TRASH", base_monthly_fee_cents=1000,
                       frequency="WEEKLY"):
    """Create + activate a service plan (requires a matching-stream cart to exist).
    Returns the activated plan dict (status ACTIVE)."""
    plan = get_success_data(api_client.create_service_plan(
        create_service_plan_payload(account_id, stream=stream, frequency=frequency,
                                    base_monthly_fee_cents=base_monthly_fee_cents),
        DISPATCHER))
    return get_success_data(api_client.activate_service_plan(plan["id"], DISPATCHER))


# ─── Tier 1: account lifecycle progression ────────────

def setup_active_account(rate_class="RESIDENTIAL", diversion_floor_pct=None,
                         base_monthly_fee_cents=1000, address="1 Test St",
                         stream="TRASH"):
    """Account driven to ACTIVE with one ACTIVE cart + one ACTIVE plan of `stream`.

    Returns (account, cart, plan), all post-activation. The returned account is the
    GET-fresh account so its `version` reflects every activation increment.
    """
    account = create_account(rate_class=rate_class, diversion_floor_pct=diversion_floor_pct,
                             address=address)
    cart = create_active_cart(account["id"], stream=stream)
    plan = create_active_plan(account["id"], stream=stream,
                              base_monthly_fee_cents=base_monthly_fee_cents)
    account = get_success_data(api_client.activate_account(account["id"], DISPATCHER))
    return account, cart, plan


# ─── Tier 2: route / stop / pickup setup ──────────────

def setup_route_in_progress(account_id, stream="TRASH", driver="drv-1",
                            num_stops=1, service_date="2026-05-04T00:00:00Z"):
    """Create a route with `num_stops` PENDING stops, dispatch it, and start it
    (status IN_PROGRESS). Returns (route, [stop, ...])."""
    route = get_success_data(api_client.create_route(
        create_route_payload(service_date=service_date, stream=stream,
                             assigned_driver_id=driver), DISPATCHER))
    stops = []
    for seq in range(1, num_stops + 1):
        stop = get_success_data(api_client.create_stop(
            route["id"], create_stop_payload(account_id, seq), DISPATCHER))
        stops.append(stop)
    get_success_data(api_client.dispatch_route(route["id"], DISPATCHER))
    get_success_data(api_client.start_route(route["id"], DRIVER))
    return route, stops


def schedule_pickup(stop_id, cart_id):
    """Schedule one SCHEDULED pickup for `cart_id` at `stop_id`. Returns the pickup."""
    return get_success_data(api_client.create_pickup(
        stop_id, create_pickup_payload(cart_id), DISPATCHER))


def complete_pickup_with_ticket(pickup_id, cart_version, gross_weight_lbs, diverted):
    """Complete a SCHEDULED pickup (OCC on cart) then record its weight ticket.
    Returns (completed_pickup, weight_ticket)."""
    pickup = get_success_data(api_client.complete_pickup(
        pickup_id, complete_pickup_payload(cart_version), DRIVER))
    ticket = get_success_data(api_client.create_weight_ticket(
        pickup_id, create_weight_ticket_payload(gross_weight_lbs, diverted), DRIVER))
    return pickup, ticket


def setup_completed_pickup(account_id, stream="TRASH", tare_weight_lbs=0,
                           gross_weight_lbs=250, diverted=False,
                           service_date="2026-05-04T00:00:00Z"):
    """One ACTIVE cart on a fresh IN_PROGRESS route, one COMPLETED pickup with a
    weight ticket. Returns (cart, route, stop, pickup, ticket).

    The account is assumed to already exist; the cart is created here so its tare and
    stream can be controlled per test.
    """
    cart = create_active_cart(account_id, stream=stream, size_gallons=96,
                              tare_weight_lbs=tare_weight_lbs)
    route, stops = setup_route_in_progress(account_id, stream=stream,
                                           service_date=service_date)
    stop = stops[0]
    pickup = schedule_pickup(stop["id"], cart["id"])
    pickup, ticket = complete_pickup_with_ticket(
        pickup["id"], cart["version"], gross_weight_lbs, diverted)
    return cart, route, stop, pickup, ticket


# ─── Tier 3: weighed-pickup billing setup ─────────────

def setup_account_with_trash_weights(rate_class, weights, base_monthly_fee_cents=0,
                                     tare_weight_lbs=0):
    """ACTIVE account + ACTIVE TRASH plan/cart, one IN_PROGRESS route, and one
    COMPLETED TRASH pickup with a weight ticket per entry in `weights`.

    `weights` is a list of gross pound readings (all non-diverted / TRASH).
    Returns (account, cart, route, [pickup, ...]). The account is re-read so its
    version reflects all prior increments.
    """
    account, cart, _plan = setup_active_account(
        rate_class=rate_class, base_monthly_fee_cents=base_monthly_fee_cents,
        stream="TRASH")
    # Re-create the cart with the desired tare (the activation cart has default tare).
    # Use a dedicated controllable cart for the weighed pickups.
    weigh_cart = create_active_cart(account["id"], stream="TRASH", size_gallons=96,
                                    tare_weight_lbs=tare_weight_lbs)
    route, stops = setup_route_in_progress(account["id"], stream="TRASH",
                                           num_stops=len(weights))
    pickups = []
    cart_version = weigh_cart["version"]
    for stop, gross in zip(stops, weights):
        pk = schedule_pickup(stop["id"], weigh_cart["id"])
        completed = get_success_data(api_client.complete_pickup(
            pk["id"], complete_pickup_payload(cart_version), DRIVER))
        # Completing bumps the cart's version; the next completion must carry it.
        cart_version = get_success_data(api_client.get_cart(weigh_cart["id"], DRIVER))["version"]
        get_success_data(api_client.create_weight_ticket(
            pk["id"], create_weight_ticket_payload(gross, False), DRIVER))
        pickups.append(completed)
    account = get_success_data(api_client.get_account(account["id"], BILLING))
    return account, weigh_cart, route, pickups


def create_draft_invoice(account_id, period_start=MAY_START, period_end=MAY_END):
    """Read the account's current version, then create a DRAFT invoice (OCC on the
    account). Returns the draft invoice dict."""
    acct = get_success_data(api_client.get_account(account_id, BILLING))
    return get_success_data(api_client.create_invoice(
        account_id, create_invoice_payload(period_start, period_end, acct["version"]),
        BILLING))


def issue_invoice(invoice_id):
    """Issue a DRAFT invoice. Returns the issued invoice dict."""
    return get_success_data(api_client.issue_invoice(invoice_id, BILLING))


# ─── Tier 4: special-pickup lifecycle ─────────────────

def request_special_pickup(account_id, kind="BULK", hazard_class=None,
                           requested_date="2026-05-10T00:00:00Z"):
    """ResidentAccount requests a special pickup on its own account (REQUESTED).
    Returns the special-pickup dict."""
    kwargs = {}
    if hazard_class is not None:
        kwargs["hazard_class"] = hazard_class
    return get_success_data(api_client.create_special_pickup(
        account_id, create_special_pickup_payload(kind, requested_date, **kwargs),
        make_resident_headers(account_id)))


def setup_scheduled_special_pickup(account_id, kind="BULK", hazard_class=None):
    """Request → approve → schedule a special pickup (status SCHEDULED).
    Returns the special-pickup dict (post-schedule, carries quoted_fee_cents)."""
    sp = request_special_pickup(account_id, kind=kind, hazard_class=hazard_class)
    get_success_data(api_client.approve_special_pickup(sp["id"], DISPATCHER))
    return get_success_data(api_client.schedule_special_pickup(sp["id"], DISPATCHER))


# ─── Tier 5: credit + diversion setup ─────────────────

def setup_pending_credit_from_miss(account_id, miss_reason="MISSED_BY_CREW",
                                   service_date="2026-05-20T00:00:00Z"):
    """Drive one SCHEDULED pickup to MISSED with a carrier-fault reason, auto-creating
    one PENDING MissedPickupCredit. Returns (pickup, credit).

    The account is assumed to exist already (no plan needed for the miss itself).
    """
    cart = create_active_cart(account_id, stream="TRASH", size_gallons=65,
                              tare_weight_lbs=0)
    route, stops = setup_route_in_progress(account_id, stream="TRASH",
                                           service_date=service_date)
    pk = schedule_pickup(stops[0]["id"], cart["id"])
    missed = get_success_data(api_client.miss_pickup(
        pk["id"], miss_pickup_payload(miss_reason), DRIVER))
    credits = get_success_data(api_client.list_credits(
        BILLING, params={"source_pickup_id": pk["id"]}))
    credit = credits[0] if credits else None
    return missed, credit


def finalize_diversion_period(account_id, period_start=MAY_START, period_end=MAY_END):
    """Open + finalize a diversion window for the account. Returns the finalized period."""
    dp = get_success_data(api_client.create_diversion_period(
        account_id, create_diversion_period_payload(period_start, period_end), BILLING))
    return get_success_data(api_client.finalize_diversion_period(dp["id"], BILLING))


def add_contamination_tag(pickup_id, severity, note=None):
    """Tag a COMPLETED pickup's load. Returns the tag dict."""
    kwargs = {}
    if note is not None:
        kwargs["note"] = note
    return get_success_data(api_client.create_contamination_tag(
        pickup_id, create_contamination_tag_payload(severity, **kwargs), DRIVER))
