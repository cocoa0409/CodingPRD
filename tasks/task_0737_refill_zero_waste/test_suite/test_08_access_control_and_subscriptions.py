"""Access control (authentication and role authorization) and subscription-run
concurrency guards.

One Corner/cross_cutting_complexity_layers OCC instance, one Corner/state_machines
subscription instance, one Corner/validations auth instance, and two Corner/rbac
role-denial instances.
"""
from test_helpers import (
    fixtures, factories, validate_success, validate_error, ApiErrorId,
    make_member_headers,
)
from test_helpers.test_users import TEST_USERS

CLERK = TEST_USERS["store_clerk_headers"]
IM = TEST_USERS["inventory_manager_headers"]
ANON = TEST_USERS["anonymous_headers"]


def test_second_run_with_stale_version_rejected(api):
    """PRD §2.10: "If that value does not equal the subscription's current
    `version` — because an earlier run has already advanced it since the client
    last read the subscription — the run is rejected with `ERR_STALE_VERSION`
    (HTTP 412)."
    PRD §2.10: "A successful run increments the subscription's `version` by one."

    Design: Corner/cross_cutting_complexity_layers/corner_occ_subscription_run_stale_version
    """
    member = fixtures.create_member(api)
    product = fixtures.create_product(api)
    station = fixtures.create_station(api)
    sub = fixtures.create_subscription(api, member_id=member["id"],
                                       product_id=product["id"], station_id=station["id"])
    first_version = sub["version"]
    # First run succeeds and bumps version (first_version -> first_version + 1).
    validate_success(
        api.run_subscription(sub["id"], {"expected_subscription_version": first_version}, CLERK),
        201)
    # Second run still carries the now-stale first_version.
    resp = api.run_subscription(
        sub["id"], {"expected_subscription_version": first_version}, CLERK)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)


def test_run_cancelled_subscription_rejected(api):
    """PRD §2.9: "the checks are evaluated in a fixed priority order and the first
    failure wins; lower-priority-number checks are decided before higher ones."
    PRD §2.9: "**State** — the target resource is in a status permitting the
    requested transition, else one of `ERR_INVALID_ORDER_STATE`,
    `ERR_INVALID_CONTAINER_STATE`, or `ERR_INVALID_STATE` (all 409)."

    Design: Corner/state_machines/corner_subscription_run_after_cancel_rejected
    """
    member = fixtures.create_member(api)
    product = fixtures.create_product(api)
    station = fixtures.create_station(api)
    sub = fixtures.create_subscription(api, member_id=member["id"],
                                       product_id=product["id"], station_id=station["id"])
    validate_success(api.cancel_subscription(sub["id"], CLERK), 200)  # ACTIVE -> CANCELLED
    # The CANCELLED subscription fails the state precondition (priority 4), which
    # is decided before the OCC version guard (priority 10).
    resp = api.run_subscription(
        sub["id"], {"expected_subscription_version": sub["version"]}, CLERK)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_create_product_without_auth_rejected(api):
    """PRD §2.1: "If either header is missing, or `X-User-Role` is not one of the
    recognized roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP
    401)."

    Design: Corner/validations/corner_err_products_missing_auth_returns_401
    """
    resp = api.create_product(factories.create_product_payload(), ANON)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


def test_member_cannot_create_product(api):
    """PRD §2.1: "When the headers are well-formed but the role is not permitted to
    perform the requested operation — or a member attempts to act on a resource
    they do not own — the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §2.1: "The inventory manager exclusively manages products, stations, bins,
    bin recounts, restock completions, delivery vehicles, and the logical clock".

    Design: Corner/rbac/corner_member_cannot_create_product_returns_403
    """
    member = fixtures.create_member(api)
    resp = api.create_product(factories.create_product_payload(),
                              make_member_headers(member["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_clerk_cannot_recount_bin(api):
    """PRD §2.1: "When the headers are well-formed but the role is not permitted to
    perform the requested operation ... the request is rejected with
    `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §2.1: "The inventory manager exclusively manages products, stations, bins,
    bin recounts, restock completions, delivery vehicles, and the logical clock".

    Design: Corner/rbac/corner_storeclerk_cannot_recount_bin_returns_403
    """
    product = fixtures.create_product(api)
    station = fixtures.create_station(api)
    bin_ = fixtures.create_bin(api, product_id=product["id"], station_id=station["id"],
                               reorder_threshold_g=100, last_recount_g=5000)
    resp = api.recount_bin(bin_["id"], {"physical_g": 4900}, CLERK)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)
