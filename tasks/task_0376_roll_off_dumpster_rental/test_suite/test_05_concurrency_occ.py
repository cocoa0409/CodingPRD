"""Optimistic concurrency on shared fleet (Container.version) and route
(Route.version) state, plus the per-mutation version-increment guarantee. OCC's
version check at commit time makes these deterministic in sequential form.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
)
from test_helpers import fixtures
from test_helpers import factories


YARD_ADMIN = TEST_USERS["yard_admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]


def test_dispatch_with_stale_container_version_rejected(api):
    """PRD §2.5: "A delivery dispatch must carry expected_container_version, the
    version of the target Container as the dispatcher last observed it. If that
    value does not equal the container's current version — because the same can
    was committed to a different order, retired, or restored since the
    dispatcher read it — the request is rejected with ERR_STALE_CONTAINER_VERSION
    (HTTP 412)."

    The can is created (version 1), retired then restored (now IN_YARD at
    version 3); a dispatch carrying the stale version 1 is rejected.

    Design: Corner/cross_cutting_complexity_layers/occ_dispatch_stale_container_version
    """
    ct = fixtures.create_container_type()
    account = fixtures.create_account(business_name="Occ1")
    container = fixtures.create_container(ct["id"])  # version 1
    stale_version = container["version"]
    get_success_data(api.retire_asset(container["id"], YARD_ADMIN))   # -> 2
    get_success_data(api.restore_asset(container["id"], YARD_ADMIN))  # -> 3, IN_YARD
    order = fixtures.book_order(account["id"], ct["id"], site_address="30 Main")

    resp = api.dispatch_delivery(
        order["id"],
        factories.dispatch_delivery_payload(container["id"], stale_version),
        DISPATCHER,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_CONTAINER_VERSION.value)
    order_now = validate_success(api.get_rental_order(order["id"], DISPATCHER))
    assert order_now["logistics_status"] == "BOOKED"


def test_dispatch_with_fresh_container_version_succeeds(api):
    """PRD §2.5: "A delivery dispatch must carry expected_container_version, the
    version of the target Container as the dispatcher last observed it."
    PRD §3.5: "When all conditions hold, the order moves BOOKED -> SCHEDULED on
    its logistics axis. The container moves IN_YARD -> ASSIGNED, its
    current_order_id is set to the order's id, and its version increments."

    Re-reading the fresh version 3 after retire+restore and dispatching commits
    the can: the order is SCHEDULED and the container ASSIGNED to it.

    Design: Corner/cross_cutting_complexity_layers/occ_dispatch_fresh_container_version_succeeds
    """
    ct = fixtures.create_container_type()
    account = fixtures.create_account(business_name="Occ2")
    container = fixtures.create_container(ct["id"])
    get_success_data(api.retire_asset(container["id"], YARD_ADMIN))
    fresh = get_success_data(api.restore_asset(container["id"], YARD_ADMIN))
    order = fixtures.book_order(account["id"], ct["id"], site_address="31 Main")

    resp = api.dispatch_delivery(
        order["id"],
        factories.dispatch_delivery_payload(container["id"], fresh["version"]),
        DISPATCHER,
    )
    order_now = validate_success(resp)
    assert order_now["logistics_status"] == "SCHEDULED"
    cont = validate_success(api.get_container(container["id"], DISPATCHER))
    assert cont["status"] == "ASSIGNED"
    assert cont["current_order_id"] == order["id"]


def test_second_route_append_with_stale_route_version_rejected(api):
    """PRD §2.5: "Adding a stop must carry expected_route_version, the version of
    the target Route as last observed. If that value does not equal the route's
    current version — because another stop was appended to or cancelled from the
    route since, changing its stop_count and the next free sequence slot — the
    append is rejected with ERR_STALE_ROUTE_VERSION (HTTP 412)."

    After appending stop A (route version 1 -> 2), appending stop B still
    carrying version 1 is rejected; stop B stays UNASSIGNED.

    Design: Corner/cross_cutting_complexity_layers/occ_route_stale_version_on_second_append
    """
    ct = fixtures.create_container_type()
    account = fixtures.create_account(business_name="Occ3", credit_limit_cents=1000000)
    order1 = fixtures.book_order(account["id"], ct["id"], site_address="32 Main")
    stop1 = fixtures.get_delivery_stop(order1["id"])
    order2 = fixtures.book_order(account["id"], ct["id"], site_address="33 Main")
    stop2 = fixtures.get_delivery_stop(order2["id"])

    route = fixtures.create_route()
    stale_version = route["version"]  # 1
    get_success_data(api.append_stop(
        route["id"], factories.append_stop_payload(stop1["id"], stale_version), DISPATCHER))

    resp = api.append_stop(
        route["id"], factories.append_stop_payload(stop2["id"], stale_version), DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_STALE_ROUTE_VERSION.value)
    stop = validate_success(api.get_service_stop(stop2["id"], DISPATCHER))
    assert stop["status"] == "UNASSIGNED"


def test_container_version_increments_one_per_mutation(api):
    """PRD §2.4: "version, an integer that begins at 1 on creation and increments
    by exactly 1 on every mutation that changes the resource."
    PRD §3.1: "Each of these transitions increments the container's `version`."

    create -> 1, retire -> 2, restore -> 3.

    Design: Corner/cross_cutting_complexity_layers/version_increments_on_container_mutation
    """
    ct = fixtures.create_container_type()
    container = fixtures.create_container(ct["id"])
    assert container["version"] == 1
    retired = get_success_data(api.retire_asset(container["id"], YARD_ADMIN))
    assert retired["version"] == 2
    restored = get_success_data(api.restore_asset(container["id"], YARD_ADMIN))
    assert restored["version"] == 3
    assert restored["status"] == "IN_YARD"
