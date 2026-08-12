"""Publishing, closing, reopening and archiving a registry, and listing its items."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_registry,
    assert_registry_item,
    make_registry_owner_headers,
    read_registry,
    read_registry_item,
    register_and_verify_account,
    unique_code,
    unique_email,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import (
    make_child,
    make_registry,
    make_registry_item,
    make_sku,
    pay_gift,
    reserve_gift,
    set_clock,
    setup_open_registry,
    setup_paid_gift,
    setup_registry_parties,
)

OPS = TEST_USERS["ops_admin_headers"]


def test_a_fresh_registry_item_starts_unfulfilled(api):
    """PRD §3.9: "An item's `fulfilled_quantity` starts at 0 and its `status` starts at
    `REQUESTED`, moving to `PARTIALLY_FULFILLED` and `FULFILLED` as gifts are paid for."
    PRD §3.9: "A registry's `completion_pct` is the sum of `fulfilled_quantity` across all of
    its items divided by the sum of `requested_quantity` across all of its items, with no
    status filter on either sum, rounded half up to four decimal places; when nothing is
    requested at all the value is 0."
    PRD §3.9: "A `Registry` is created in `DRAFT` by naming `owner_account_id` — the identity
    that will edit and claim — a `child_id` the registry is for, and a `title`."

    Design: Corner/entities/corner_registry_item_fulfilled_quantity_starts_zero
    """
    parties = setup_registry_parties(api)
    registry = make_registry(api, parties, title="Fresh Registry")
    data = validate_success(
        api.create_registry_item(
            registry["id"],
            {"sku_id": parties["sku"]["id"], "requested_quantity": 4},
            parties["owner_headers"],
        ),
        201,
    )
    assert_registry_item(data)
    assert data["fulfilled_quantity"] == 0
    assert data["status"] == "REQUESTED"

    after = read_registry(api, registry["id"], parties["owner_headers"])
    assert_registry(after)
    assert after["completion_pct"] == 0
    assert after["status"] == "DRAFT"


def test_publishing_an_empty_registry_is_refused(api):
    """PRD §3.9: "Publishing moves it `DRAFT → OPEN` and requires at least one item to
    already be listed; publishing an empty registry is refused with `ERR_REGISTRY_EMPTY`
    (HTTP 409)."

    Design: Corner/state_machines/corner_open_empty_registry_rejected
    """
    parties = setup_registry_parties(api)
    registry = make_registry(api, parties, title="Empty Registry")

    resp = api.open_registry(registry["id"], parties["owner_headers"])
    validate_error(resp, ApiErrorId.ERR_REGISTRY_EMPTY.value, 409)
    assert read_registry(api, registry["id"], parties["owner_headers"])["status"] == "DRAFT"


def test_a_second_reopen_hits_the_reopen_cap(api):
    """PRD §3.9: "A closed registry may be reopened, moving `CLOSED → OPEN` and incrementing
    `reopen_count` — but at most once; a second reopen is refused with
    `ERR_REGISTRY_REOPEN_CAP` (HTTP 409)."

    Design: Corner/state_machines/corner_reopen_second_time_hits_cap
    """
    parties, registry, _item = setup_open_registry(api)
    validate_success(api.close_registry(registry["id"], parties["owner_headers"]))
    validate_success(api.reopen_registry(registry["id"], parties["owner_headers"]))
    validate_success(api.close_registry(registry["id"], parties["owner_headers"]))

    resp = api.reopen_registry(registry["id"], parties["owner_headers"])
    validate_error(resp, ApiErrorId.ERR_REGISTRY_REOPEN_CAP.value, 409)

    after = read_registry(api, registry["id"], parties["owner_headers"])
    assert after["status"] == "CLOSED"
    assert after["reopen_count"] == 1


def test_archiving_a_registry_with_a_gift_in_flight_is_refused(api):
    """PRD §3.9: "Archiving moves the registry `CLOSED → ARCHIVED` and requires
    `inflight_gift_count` to be exactly 0; archiving with a gift still in flight is refused
    with `ERR_REGISTRY_HAS_INFLIGHT_GIFTS` (HTTP 409)."
    PRD §3.9: "Closing moves the registry `OPEN → CLOSED` and recomputes
    `inflight_gift_count`, the number of gift orders on that registry whose `status` is
    `PAID`, `CLAIMED_CREDIT` or `CLAIMED_ITEM`."

    Design: Corner/state_machines/corner_archive_registry_with_inflight_gift_rejected
    """
    parties, registry, _item, gift = setup_paid_gift(api, quantity=1, requested_quantity=2)
    closed = validate_success(api.close_registry(registry["id"], parties["owner_headers"]))
    assert closed["inflight_gift_count"] == 1

    resp = api.archive_registry(registry["id"], parties["owner_headers"])
    validate_error(resp, ApiErrorId.ERR_REGISTRY_HAS_INFLIGHT_GIFTS.value, 409)

    after = read_registry(api, registry["id"], parties["owner_headers"])
    assert after["status"] == "CLOSED"
    assert after["inflight_gift_count"] == 1
    assert validate_success(
        api.get_gift_order(gift["id"], parties["owner_headers"])
    )["status"] == "PAID"


def test_deleting_an_item_that_carries_gift_activity_is_refused(api):
    """PRD §3.9: "The owner may revise `requested_quantity` on an item, and may delete an
    item that carries no gift activity — an item with at least one gift order in any status
    other than `REFUNDED` is refused with `ERR_REGISTRY_ITEM_HAS_GIFTS` (HTTP 409)."

    Design: Corner/state_machines/corner_delete_registry_item_with_paid_gift_rejected
    """
    parties, registry, item, _gift = setup_paid_gift(api, quantity=1, requested_quantity=3)

    resp = api.delete_registry_item(registry["id"], item["id"], parties["owner_headers"])
    validate_error(resp, ApiErrorId.ERR_REGISTRY_ITEM_HAS_GIFTS.value, 409)

    after = read_registry_item(api, item["id"], parties["owner_headers"])
    assert after["fulfilled_quantity"] == 1
    assert after["status"] == "PARTIALLY_FULFILLED"


def test_addressing_an_item_through_the_wrong_registry_is_refused(api):
    """PRD §3.9: "Because both of those operations address the item through its registry, the
    item must actually belong to the registry named in the path; a mismatch is refused with
    `ERR_REGISTRY_ITEM_MISMATCH` (HTTP 422)."

    Design: Corner/validations/corner_registry_item_from_another_registry_rejected
    """
    parties = setup_registry_parties(api)
    first = make_registry(api, parties, title="Registry One")
    second = make_registry(api, parties, title="Registry Two")
    item = make_registry_item(api, parties, first["id"], requested_quantity=2)

    resp = api.update_registry_item(
        second["id"], item["id"], {"requested_quantity": 5}, parties["owner_headers"]
    )
    validate_error(resp, ApiErrorId.ERR_REGISTRY_ITEM_MISMATCH.value, 422)

    after = read_registry_item(api, item["id"], parties["owner_headers"])
    assert after["requested_quantity"] == 2
    assert after["registry_id"] == first["id"]


def test_a_discontinued_sku_cannot_be_listed_on_a_registry(api):
    """PRD §3.9: "The named SKU must be `ACTIVE`; listing a discontinued one is refused with
    `ERR_SKU_DISCONTINUED` (HTTP 409)."

    Design: Corner/validations/corner_discontinued_sku_cannot_be_added_to_registry
    """
    parties = setup_registry_parties(
        api, sku_overrides={"code": unique_code("S2-OLD"), "name": "Stage 2 Retired"}
    )
    validate_success(api.update_sku(parties["sku"]["id"], {"status": "DISCONTINUED"}, OPS))
    registry = make_registry(api, parties, title="Discontinued Registry")

    resp = api.create_registry_item(
        registry["id"],
        {"sku_id": parties["sku"]["id"], "requested_quantity": 2},
        parties["owner_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_SKU_DISCONTINUED.value, 409)

    _items, meta = validate_paginated(
        api.list_registry_items(parties["owner_headers"], {"registry_id": registry["id"]})
    )
    assert meta["total_count"] == 0


# ==========================================================================
# Gate precedence around the registry
# ==========================================================================
def test_a_stranger_reopening_a_draft_registry_gets_the_ownership_error(api):
    """PRD §2.1: "When `X-User-Role` is `RegistryOwner`, `X-User-ID` is likewise the `id` of
    the acting `Account`, and it is compared against the addressed registry's
    `owner_account_id` — including when the addressed resource is a registry item or a gift
    order that hangs beneath that registry; a mismatch is `ERR_NOT_REGISTRY_OWNER` (HTTP
    403)."
    PRD §2.6: "5. **Ownership** — the acting identity is authorised on this specific
    instance, including the pipeline-specific refund-actor rules and segregation of duties
    (rungs 12 through 17)."
    PRD §2.6: "7. **Lifecycle** — the resource's state machine admits this transition from
    its current state (rungs 20 through 34)."

    Design: Difficulty/priority_pair_validation_conflict/not_registry_owner_beats_registry_state_invalid
    """
    parties = setup_registry_parties(api)
    stranger = register_and_verify_account(api, email=unique_email("stranger"))
    registry = make_registry(api, parties, title="Draft Registry")
    make_registry_item(api, parties, registry["id"], requested_quantity=2)

    resp = api.reopen_registry(registry["id"], make_registry_owner_headers(stranger["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_REGISTRY_OWNER.value, 403)

    after = read_registry(api, registry["id"], parties["owner_headers"])
    assert after["status"] == "DRAFT"
    assert after["reopen_count"] == 0


def test_the_owner_reopening_a_draft_registry_gets_the_lifecycle_error(api):
    """PRD §3.9: "Its `status` runs over `DRAFT`, `OPEN`, `CLOSED` and `ARCHIVED`, with
    `ARCHIVED` terminal, and any attempt whose from-state does not match is refused with
    `ERR_REGISTRY_STATE_INVALID` (HTTP 409)."
    PRD §3.9: "A closed registry may be reopened, moving `CLOSED → OPEN` and incrementing
    `reopen_count` — but at most once"

    Design: Difficulty/priority_pair_validation_conflict/not_registry_owner_beats_registry_state_invalid
    """
    parties = setup_registry_parties(api)
    registry = make_registry(api, parties, title="Draft Registry")
    make_registry_item(api, parties, registry["id"], requested_quantity=2)

    resp = api.reopen_registry(registry["id"], parties["owner_headers"])
    validate_error(resp, ApiErrorId.ERR_REGISTRY_STATE_INVALID.value, 409)

    after = read_registry(api, registry["id"], parties["owner_headers"])
    assert after["status"] == "DRAFT"
    assert after["reopen_count"] == 0


def test_a_closed_registry_outranks_an_over_large_gift_quantity(api):
    """PRD §3.9: "Only *new* purchases are blocked, and a create or a payment against a
    registry that is not `OPEN` is refused with `ERR_REGISTRY_CLOSED` (HTTP 409)."
    PRD §2.6: "The consequence a reader must internalise is that a request which is wrong in
    two ways reports the earlier gate."
    PRD §2.6: "9. **Policy and fiscal capacity** — domain policy first (allergen safety, then
    caps and allowances, then referential coherence), fiscal capacity last (rungs 45 through
    71, in ascending priority order)."

    Design: Difficulty/priority_pair_validation_conflict/registry_closed_beats_gift_quantity_exceeds_remaining
    """
    parties, registry, item = setup_open_registry(api, requested_quantity=1)
    validate_success(api.close_registry(registry["id"], parties["owner_headers"]))

    fresh = read_registry_item(api, item["id"], parties["purchaser_headers"])
    resp = api.create_gift_order(
        {
            "registry_item_id": item["id"],
            "purchaser_account_id": parties["purchaser_id"],
            "quantity": 5,
            "expected_registry_item_version": fresh["version"],
        },
        parties["purchaser_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_REGISTRY_CLOSED.value, 409)

    assert read_registry_item(api, item["id"], parties["owner_headers"])["fulfilled_quantity"] == 0
    _gifts, meta = validate_paginated(
        api.list_gift_orders(parties["purchaser_headers"], {"registry_item_id": item["id"]})
    )
    assert meta["total_count"] == 0


def test_an_over_large_gift_quantity_on_an_open_registry_reports_its_own_error(api):
    """PRD §3.9: "The quantity may not exceed the item's `requested_quantity` minus its
    `fulfilled_quantity`, or the reservation is refused with
    `ERR_GIFT_QUANTITY_EXCEEDS_REMAINING` (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/registry_closed_beats_gift_quantity_exceeds_remaining
    """
    parties, _registry, item = setup_open_registry(api, requested_quantity=1)

    fresh = read_registry_item(api, item["id"], parties["purchaser_headers"])
    resp = api.create_gift_order(
        {
            "registry_item_id": item["id"],
            "purchaser_account_id": parties["purchaser_id"],
            "quantity": 5,
            "expected_registry_item_version": fresh["version"],
        },
        parties["purchaser_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_GIFT_QUANTITY_EXCEEDS_REMAINING.value, 422)

    assert read_registry_item(api, item["id"], parties["owner_headers"])["fulfilled_quantity"] == 0
