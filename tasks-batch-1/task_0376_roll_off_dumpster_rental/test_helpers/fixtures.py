"""Composite setup helpers for the Roll-Off Dumpster Rental API.

These encapsulate the multi-step sequences needed to drive an order through its
logistics + billing lifecycle so that test functions can focus on assertions.

Every helper builds its preconditions from scratch (the server DB is empty at
the start of each test). Setup calls use get_success_data() so a setup failure
produces a clear "Setup failed" error rather than a confusing assertion failure.

Contractor is entity-backed: any ownership-gated contractor call threads the
acting ContractorAccount.id via make_contractor_headers(account["id"]).
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import TEST_USERS, make_contractor_headers
from . import factories


# ---------------------------------------------------------------------------
# Header shortcuts
# ---------------------------------------------------------------------------
def _admin():
    return TEST_USERS["yard_admin_headers"]


def _dispatcher():
    return TEST_USERS["dispatcher_headers"]


def _scale():
    return TEST_USERS["scale_operator_headers"]


def _permit():
    return TEST_USERS["permit_officer_headers"]


def _billing():
    return TEST_USERS["billing_clerk_headers"]


# ---------------------------------------------------------------------------
# Tier 0: clock + master data primitives
# ---------------------------------------------------------------------------
def set_clock(current_date: str):
    """Set the server business date (YardAdmin)."""
    return get_success_data(
        api_client.set_current_date(factories.set_clock_payload(current_date), _admin())
    )


def create_container_type(**overrides) -> dict:
    return get_success_data(
        api_client.create_container_type(
            factories.create_container_type_payload(**overrides), _admin()
        )
    )


def create_account(**overrides) -> dict:
    return get_success_data(
        api_client.create_contractor_account(
            factories.create_contractor_account_payload(**overrides), _admin()
        )
    )


def create_container(container_type_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_container(
            factories.create_container_payload(container_type_id, **overrides), _admin()
        )
    )


def create_route(**overrides) -> dict:
    return get_success_data(
        api_client.create_route(factories.create_route_payload(**overrides), _dispatcher())
    )


def book_order(account_id, container_type_id, **overrides) -> dict:
    """Book a rental order as the owning contractor (ownership-threaded)."""
    return get_success_data(
        api_client.create_rental_order(
            factories.create_rental_order_payload(account_id, container_type_id, **overrides),
            make_contractor_headers(account_id),
        )
    )


def get_delivery_stop(order_id) -> dict:
    """Fetch the auto-created DELIVERY stop for an order."""
    data, _meta = _list(
        api_client.list_service_stops(_dispatcher(), params={"order_id": order_id, "stop_type": "DELIVERY"})
    )
    assert data, f"Setup failed: no DELIVERY stop found for order {order_id}"
    return data[0]


def request_permit(order_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_street_permit(
            factories.create_street_permit_payload(order_id, **overrides), _permit()
        )
    )


def approve_permit(permit_id) -> dict:
    return get_success_data(api_client.approve_permit(permit_id, _permit()))


def record_weigh_ticket(order_id, service_stop_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_weigh_ticket(
            factories.create_weigh_ticket_payload(order_id, service_stop_id, **overrides), _scale()
        )
    )


def _list(response):
    """Lenient pull of (data, meta) from a list response for setup use."""
    body = response.json()
    return body["data"], body["meta"]


# ---------------------------------------------------------------------------
# Tier 1/2: order scheduled + delivered
# ---------------------------------------------------------------------------
def dispatch_and_sequence_delivery(order, container, route_overrides=None):
    """Dispatch the delivery (commit container) and append the DELIVERY stop to
    a fresh PLANNING route, then dispatch that route. Returns (route, del_stop)
    with the route in DISPATCHED status so the delivery stop is completable."""
    del_stop = get_delivery_stop(order["id"])
    get_success_data(
        api_client.dispatch_delivery(
            order["id"],
            factories.dispatch_delivery_payload(container["id"], container["version"]),
            _dispatcher(),
        )
    )
    route = create_route(**(route_overrides or {}))
    get_success_data(
        api_client.append_stop(
            route["id"],
            factories.append_stop_payload(del_stop["id"], route["version"]),
            _dispatcher(),
        )
    )
    get_success_data(api_client.dispatch_route(route["id"], _dispatcher()))
    return route, del_stop


def setup_on_site_order(ct_overrides=None, account_overrides=None,
                        order_overrides=None, delivery_date="2026-06-01"):
    """Build an order delivered and ON_SITE (logistics_status=ON_SITE,
    billing_status=UNBILLED). Returns dict with ct, account, container, order,
    route, del_stop. Closes the delivery route so it is out of the way."""
    set_clock(delivery_date)
    ct = create_container_type(**(ct_overrides or {}))
    account = create_account(**(account_overrides or {}))
    container = create_container(ct["id"])
    order = book_order(account["id"], ct["id"], **(order_overrides or {}))
    route, del_stop = dispatch_and_sequence_delivery(
        order, container, route_overrides={"service_date": delivery_date}
    )
    get_success_data(api_client.complete_stop(del_stop["id"], _dispatcher()))
    get_success_data(api_client.close_route(route["id"], _dispatcher()))
    order = get_success_data(api_client.get_rental_order(order["id"], _dispatcher()))
    container = get_success_data(api_client.get_container(container["id"], _dispatcher()))
    return {
        "ct": ct, "account": account, "container": container, "order": order,
        "route": route, "del_stop": del_stop,
    }


# ---------------------------------------------------------------------------
# Tier 3/4: full lifecycle through PICKUP-complete (finalize + invoice)
# ---------------------------------------------------------------------------
def setup_pickup_ready(ct_overrides=None, account_overrides=None,
                       order_overrides=None,
                       delivery_date="2026-06-01", pickup_date="2026-06-10",
                       estimated_weight_lbs=5000, weigh_ticket_overrides=None,
                       permit_overrides=None, approve=False):
    """Drive an order to the point where the PICKUP stop is ASSIGNED on a
    DISPATCHED route and its WeighTicket exists — i.e. one POST
    /service-stops/{pu_stop}/complete away from FINALIZED.

    Returns dict with ct, account, container, order, pu_stop, weigh_ticket, and
    (if a permit was requested) permit.

    If permit_overrides is provided, a permit is requested before dispatch;
    approve=True approves it (required for dispatch when requires_street_permit).
    """
    set_clock(delivery_date)
    ct = create_container_type(**(ct_overrides or {}))
    account = create_account(**(account_overrides or {}))
    container = create_container(ct["id"])
    order = book_order(account["id"], ct["id"], **(order_overrides or {}))

    permit = None
    if permit_overrides is not None:
        permit = request_permit(order["id"], **permit_overrides)
        if approve:
            approve_permit(permit["id"])

    # dispatch delivery + sequence + dispatch route + complete delivery + close
    route1, del_stop = dispatch_and_sequence_delivery(
        order, container, route_overrides={"service_date": delivery_date}
    )
    get_success_data(api_client.complete_stop(del_stop["id"], _dispatcher()))
    get_success_data(api_client.close_route(route1["id"], _dispatcher()))

    # advance clock, create pickup stop, sequence onto a 2nd route, dispatch
    set_clock(pickup_date)
    pu_stop = get_success_data(
        api_client.create_pickup_stop(
            order["id"], {"estimated_weight_lbs": estimated_weight_lbs}, _dispatcher()
        )
    )
    route2 = create_route(service_date=pickup_date)
    get_success_data(
        api_client.append_stop(
            route2["id"],
            factories.append_stop_payload(pu_stop["id"], route2["version"]),
            _dispatcher(),
        )
    )
    get_success_data(api_client.dispatch_route(route2["id"], _dispatcher()))

    weigh_ticket = record_weigh_ticket(
        order["id"], pu_stop["id"], **(weigh_ticket_overrides or {})
    )

    return {
        "ct": ct, "account": account, "container": container, "order": order,
        "route1": route1, "del_stop": del_stop, "route2": route2,
        "pu_stop": pu_stop, "weigh_ticket": weigh_ticket, "permit": permit,
    }


def setup_completed_order(**kwargs) -> dict:
    """Full lifecycle through PICKUP-complete: order FINALIZED + COMPLETED,
    Invoice ISSUED. Returns the setup_pickup_ready dict plus 'order' refreshed
    and 'invoice' (the issued invoice)."""
    ctx = setup_pickup_ready(**kwargs)
    get_success_data(api_client.complete_stop(ctx["pu_stop"]["id"], _dispatcher()))
    ctx["order"] = get_success_data(
        api_client.get_rental_order(ctx["order"]["id"], _dispatcher())
    )
    data, _meta = _list(
        api_client.list_order_invoice(ctx["order"]["id"], _billing())
    )
    ctx["invoice"] = data[0] if data else None
    ctx["account"] = get_success_data(
        api_client.get_contractor_account(ctx["account"]["id"], _admin())
    )
    return ctx


# ---------------------------------------------------------------------------
# Scheduled-order helpers (BOOKED -> SCHEDULED, route still PLANNING)
# ---------------------------------------------------------------------------
def setup_scheduled_order_planning_route(ct_overrides=None, account_overrides=None,
                                         order_overrides=None):
    """Order dispatched (SCHEDULED) with its DELIVERY stop appended to a route
    that is still PLANNING (stop_count=1, route NOT dispatched).
    Returns dict with ct, account, container, order, route, del_stop."""
    ct = create_container_type(**(ct_overrides or {}))
    account = create_account(**(account_overrides or {}))
    container = create_container(ct["id"])
    order = book_order(account["id"], ct["id"], **(order_overrides or {}))
    del_stop = get_delivery_stop(order["id"])
    get_success_data(
        api_client.dispatch_delivery(
            order["id"],
            factories.dispatch_delivery_payload(container["id"], container["version"]),
            _dispatcher(),
        )
    )
    route = create_route()
    get_success_data(
        api_client.append_stop(
            route["id"],
            factories.append_stop_payload(del_stop["id"], route["version"]),
            _dispatcher(),
        )
    )
    return {
        "ct": ct, "account": account, "container": container, "order": order,
        "route": route, "del_stop": del_stop,
    }


def setup_booked_order_with_container(ct_overrides=None, account_overrides=None,
                                      order_overrides=None):
    """A BOOKED order with a valid IN_YARD container of the matching type ready
    to dispatch. Returns dict with ct, account, container, order."""
    ct = create_container_type(**(ct_overrides or {}))
    account = create_account(**(account_overrides or {}))
    container = create_container(ct["id"])
    order = book_order(account["id"], ct["id"], **(order_overrides or {}))
    return {"ct": ct, "account": account, "container": container, "order": order}
