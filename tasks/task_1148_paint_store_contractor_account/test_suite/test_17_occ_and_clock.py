"""Optimistic concurrency control on the contractor account (PRD §2.7) and
the fixed default logical clock (PRD §2.4)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_account,
    create_delivery_payload,
    create_order_payload,
    get_account_version,
    place_order,
    setup_account_job_product,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
ASSOCIATE = TEST_USERS["associate_headers"]
MANAGER = TEST_USERS["manager_headers"]


def test_occ_patch_succeeds_once_with_fresh_version(api):
    """PRD §2.7: "Two write operations are guarded by optimistic concurrency
    control on the contractor account: updating a contractor account's mutable
    fields, and creating an order. Both requests must carry
    `expected_contractor_account_version`, a non-optional field holding the
    account `version` the caller last observed. If that value does not match
    the account's current `version` — because another write, such as an order
    creation, a payment, or a tier evaluation, has advanced the account since
    — the request is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    The first PATCH with the observed version succeeds and advances the
    account's version.

    Design: Corner/complexity_layers/occ_stale_version_on_account_patch
    """
    account = create_account(company_name="Occ Co", credit_limit_cents=1000)
    resp = api.patch_contractor_account(
        account["id"],
        {"expected_contractor_account_version": account["version"],
         "credit_limit_cents": 70_000},
        ADMIN)
    patched = validate_success(resp, expected_status=200)
    assert patched["version"] == account["version"] + 1
    assert patched["credit_limit_cents"] == 70_000


def test_occ_patch_replay_rejected_stale(api):
    """PRD §2.7: "Two write operations are guarded by optimistic concurrency
    control on the contractor account: updating a contractor account's mutable
    fields, and creating an order. Both requests must carry
    `expected_contractor_account_version`, a non-optional field holding the
    account `version` the caller last observed. If that value does not match
    the account's current `version` — because another write, such as an order
    creation, a payment, or a tier evaluation, has advanced the account since
    — the request is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Replaying the pre-mutation version after the first patch advanced it is
    stale.

    Design: Corner/complexity_layers/occ_stale_version_on_account_patch
    """
    account = create_account(company_name="Occ Co", credit_limit_cents=1000)
    validate_success(api.patch_contractor_account(
        account["id"],
        {"expected_contractor_account_version": account["version"],
         "credit_limit_cents": 70_000},
        ADMIN))
    resp = api.patch_contractor_account(
        account["id"],
        {"expected_contractor_account_version": account["version"],
         "credit_limit_cents": 80_000},
        ADMIN)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
    after = validate_success(api.get_contractor_account(account["id"], ADMIN))
    assert after["credit_limit_cents"] == 70_000, (
        "the rejected replay must not overwrite the first writer's change")


def _setup_occ_order_scenario(api):
    """Account, job, product; the account version captured at creation."""
    account, _, job, product = setup_account_job_product(
        company_name="Occ2 Co", credit_limit_cents=1_000_000,
        jurisdiction_code="KY-OPEN", jurisdiction_name="Kentucky",
        sku="P-OCC2", list_price_cents=5000)
    return account, job, product


def test_order_create_with_fresh_version_succeeds(api):
    """PRD §2.7: "Two write operations are guarded by optimistic concurrency
    control on the contractor account: updating a contractor account's mutable
    fields, and creating an order. Both requests must carry
    `expected_contractor_account_version`, a non-optional field holding the
    account `version` the caller last observed. If that value does not match
    the account's current `version` — because another write, such as an order
    creation, a payment, or a tier evaluation, has advanced the account since
    — the request is rejected with `ERR_STALE_VERSION` (HTTP 412)." PRD §3.6:
    "A created order starts `UNPAID` and `PENDING` with `refunded_cents` zero
    and `paid_at` null; its creation recomputes the account's
    `outstanding_balance_cents` and increments the account's `version`."

    The first create with the captured version succeeds and bumps the
    account's version.

    Design: Corner/complexity_layers/occ_stale_version_on_order_create
    """
    account, job, product = _setup_occ_order_scenario(api)
    captured = account["version"]
    resp = api.create_order(
        create_order_payload(account["id"], job["id"], captured,
                             [{"product_id": product["id"], "quantity": 1}]),
        ASSOCIATE)
    order = validate_success(resp, expected_status=201)
    assert order["id"]
    after = validate_success(api.get_contractor_account(account["id"], ADMIN))
    assert after["version"] == captured + 1, (
        "order creation increments the account's version")


def test_order_create_replay_rejected_stale(api):
    """PRD §2.7: "If that value does not match the account's current `version`
    — because another write, such as an order creation, a payment, or a tier
    evaluation, has advanced the account since — the request is rejected with
    `ERR_STALE_VERSION` (HTTP 412). The check exists because domain state
    alone would let both writes through: the account stays `ACTIVE`, so
    nothing else prevents a caller from overwriting changes it never observed,
    or from pricing an order against a tier and balance basis that has already
    moved. Endpoints not named here take no version field at all."

    The replayed create with the pre-first-create version is stale.

    Design: Corner/complexity_layers/occ_stale_version_on_order_create
    """
    account, job, product = _setup_occ_order_scenario(api)
    captured = account["version"]
    validate_success(api.create_order(
        create_order_payload(account["id"], job["id"], captured,
                             [{"product_id": product["id"], "quantity": 1}]),
        ASSOCIATE), expected_status=201)
    resp = api.create_order(
        create_order_payload(account["id"], job["id"], captured,
                             [{"product_id": product["id"], "quantity": 1}]),
        ASSOCIATE)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
    data = validate_success(
        api.list_orders(ASSOCIATE, params={"contractor_account_id": account["id"]}))
    assert len(data) == 1, (
        f"only the first order may exist after the stale replay, got {len(data)}")


def test_clock_default_governs_window_past_check(api):
    """PRD §2.4: "All time in the system is read from a single **logical
    clock**, never from the server's wall clock. At startup the logical clock
    reads exactly 2026-05-01T00:00:00Z. Every server-produced timestamp —
    `created_at`, `paid_at`, `dispatched_at`, `delivered_at`, `published_at`,
    `effected_at`, `approved_at`, rebate period math, mistint decay windows,
    and delivery-window checks — derives from this clock. An admin-only
    test-driving capability advances the logical clock to a supplied instant:
    the request carries `to_iso8601`, succeeds with HTTP 204, mutates no
    entity, and is restricted to `CorporateAdmin`. Once set, the clock holds
    the supplied value until set again; the server never falls back to
    wall-clock time." PRD §3.8: "the `window_start` must not lie before the
    logical clock now (`ERR_DELIVERY_WINDOW_PAST`, HTTP 422)".

    Without any clock call, a 2026-04-30 window is in the past under the
    fixed default instant.

    Design: Corner/complexity_layers/clock_default_is_fixed_instant
    """
    account, _, job, product = setup_account_job_product(
        company_name="Clk Co", credit_limit_cents=1_000_000,
        jurisdiction_code="SD-OPEN", jurisdiction_name="South Dakota",
        sku="P-CLK", list_price_cents=5000)
    order = place_order(account["id"], job["id"],
                        [{"product_id": product["id"], "quantity": 1}])
    resp = api.create_delivery(
        create_delivery_payload(order["id"], job["id"],
                                window_start="2026-04-30T09:00:00Z",
                                window_end="2026-04-30T10:00:00Z"),
        MANAGER)
    validate_error(resp, ApiErrorId.ERR_DELIVERY_WINDOW_PAST)
