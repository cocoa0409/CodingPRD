"""Reserving, paying, claiming and refunding a gift, and the cascades each drives."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_credit_conserved,
    assert_gift_order,
    assert_registry_units_conserved,
    list_credits_of,
    make_subscription,
    read_account,
    read_credit,
    read_cycle,
    read_gift_order,
    read_registry_item,
    set_clock,
    unique_code,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import (
    activate,
    allocate_cycle,
    charge_cycle,
    claim_gift,
    generate_cycle,
    gift_credit_of,
    make_registry,
    make_registry_item,
    make_sku,
    pay_gift,
    reserve_gift,
    setup_open_registry,
    setup_paid_gift,
    setup_registry_parties,
)

OPS = TEST_USERS["ops_admin_headers"]


def test_a_closed_registry_still_admits_the_owners_credit_claim(api):
    """PRD §3.9: "Closing with gifts in flight is entirely legal: gifts already paid or
    claimed are neither cancelled nor invalidated and remain claimable."
    PRD §3.9: "On the `CREDIT` branch the gift moves `PAID → CLAIMED_CREDIT`. `paid_cents` is
    left exactly as payment set it — a later price change on the SKU has no effect on it or on
    what is issued. A `Credit` of `credit_type` `GIFT` is created on the owner's account with
    `issued_cents` equal to `paid_cents`, `refundable` false and `expires_at` 730 days after
    the logical clock, and the owner's `available_credit_cents` is recomputed. No shipment is
    ever created on this branch."

    Design: Corner/state_machines/corner_closed_registry_still_lets_owner_claim_paid_gift
    """
    parties, registry, _item, gift = setup_paid_gift(api, quantity=1, requested_quantity=2)
    validate_success(api.close_registry(registry["id"], parties["owner_headers"]))

    claimed = validate_success(
        api.claim_gift_order(gift["id"], {"claim_mode": "CREDIT"}, parties["owner_headers"])
    )
    assert claimed["status"] == "CLAIMED_CREDIT"
    assert read_account(api, parties["owner_id"])["available_credit_cents"] == 1200

    credits = list_credits_of(api, parties["owner_id"], credit_type="GIFT")
    assert len(credits) == 1
    assert credits[0]["issued_cents"] == 1200
    assert credits[0]["refundable"] is False

    _shipments, meta = validate_paginated(
        api.list_shipments(OPS, {"gift_order_id": gift["id"]})
    )
    assert meta["total_count"] == 0, "the CREDIT branch never creates a shipment"


def test_paying_the_same_gift_twice_is_refused(api):
    """PRD §3.9: "A gift's `status` axis treats `REFUNDED` as terminal, and any operation
    whose from-state does not match is refused with `ERR_GIFT_ORDER_STATE_INVALID` (HTTP
    409)."
    PRD §3.9: "`paid_cents` is set to the gift's `quantity` multiplied by the effective
    per-pack price of the SKU *as it stands at the moment of payment* — the same base price
    plus 350-cent hypoallergenic surcharge formula used everywhere else — and `paid_at` is
    stamped with the logical clock."

    Design: Corner/state_machines/corner_gift_pay_twice_rejected
    """
    parties, _registry, item, gift = setup_paid_gift(api, quantity=1, requested_quantity=3)

    resp = api.pay_gift_order(gift["id"], parties["purchaser_headers"])
    validate_error(resp, ApiErrorId.ERR_GIFT_ORDER_STATE_INVALID.value, 409)

    after = read_gift_order(api, gift["id"], parties["purchaser_headers"])
    assert_gift_order(after)
    assert after["status"] == "PAID"
    assert after["paid_cents"] == 1200
    assert read_registry_item(api, item["id"], parties["owner_headers"])["fulfilled_quantity"] == 1


def test_a_gift_against_an_already_fulfilled_item_is_refused(api):
    """PRD §3.9: "The item must not already be `FULFILLED`, or the reservation is refused
    with `ERR_REGISTRY_ITEM_FULFILLED` (HTTP 409)."
    PRD §3.9: "a single gift covering the whole request moves it `REQUESTED → FULFILLED`"

    Design: Corner/state_machines/corner_gift_against_fulfilled_item_rejected
    """
    parties, _registry, item, _gift = setup_paid_gift(api, quantity=1, requested_quantity=1)
    fresh = read_registry_item(api, item["id"], parties["purchaser_headers"])
    assert fresh["status"] == "FULFILLED"

    resp = api.create_gift_order(
        {
            "registry_item_id": item["id"],
            "purchaser_account_id": parties["purchaser_id"],
            "quantity": 1,
            "expected_registry_item_version": fresh["version"],
        },
        parties["purchaser_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_REGISTRY_ITEM_FULFILLED.value, 409)

    assert read_registry_item(api, item["id"], parties["owner_headers"])["fulfilled_quantity"] == 1
    _gifts, meta = validate_paginated(
        api.list_gift_orders(parties["purchaser_headers"], {"registry_item_id": item["id"]})
    )
    assert meta["total_count"] == 1


def test_a_stale_registry_item_version_rejects_the_reservation(api):
    """PRD §2.7: "Creating a gift order against a registry item requires
    `expected_registry_item_version`, carrying the client's last observed `version` of that
    `RegistryItem`. If the item's current `version` differs, the create is rejected with
    `ERR_STALE_REGISTRY_ITEM_VERSION` (HTTP 412)."
    PRD §2.7: "Several purchasers buying different slices of a multi-quantity item is
    entirely normal, so the stale purchaser's view of the remaining quantity is invalidated by
    version rather than by quantity arithmetic."

    Design: Corner/cross_cutting_layers/corner_occ_stale_registry_item_version_rejects_gift
    """
    parties, _registry, item = setup_open_registry(api, requested_quantity=3)
    stale_version = item["version"]

    first = reserve_gift(api, parties, item, 1)
    pay_gift(api, parties, first["id"])

    resp = api.create_gift_order(
        {
            "registry_item_id": item["id"],
            "purchaser_account_id": parties["purchaser_id"],
            "quantity": 1,
            "expected_registry_item_version": stale_version,
        },
        parties["purchaser_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_STALE_REGISTRY_ITEM_VERSION.value, 412)

    assert read_registry_item(api, item["id"], parties["owner_headers"])["fulfilled_quantity"] == 1
    _gifts, meta = validate_paginated(
        api.list_gift_orders(parties["purchaser_headers"], {"registry_item_id": item["id"]})
    )
    assert meta["total_count"] == 1


def test_the_item_claim_reprices_at_the_claim_time_sku_price(api):
    """PRD §3.9: "On the `ITEM` branch the gift moves `PAID → CLAIMED_ITEM`."
    PRD §3.9: "`paid_cents` is *rewritten* using the SKU price in force at claim time, so a
    price change between payment and claim is observable on the gift order. Stock is
    decremented by the gift's `quantity`, and a one-off `Shipment` is created in `CREATED` with
    `gift_order_id` set, `cycle_id` null and `account_id` set to the registry's
    `owner_account_id`, honouring the optional `service_level` input in the same way a cycle
    dispatch does."

    Design: Corner/calculations/corner_gift_item_claim_reprices_at_claim_time_sku_price
    """
    parties, _registry, _item, gift = setup_paid_gift(
        api,
        quantity=1,
        requested_quantity=1,
        sku_overrides={"code": unique_code("S2-GIFT"), "name": "Stage 2 Gift Pack",
                       "pack_price_cents": 1000, "stock_packs": 5},
    )
    assert gift["paid_cents"] == 1000
    validate_success(api.update_sku(parties["sku"]["id"], {"pack_price_cents": 1800}, OPS))

    claimed = validate_success(
        api.claim_gift_order(
            gift["id"], {"claim_mode": "ITEM", "service_level": "STANDARD"},
            parties["owner_headers"],
        )
    )
    assert claimed["paid_cents"] == 1800
    assert claimed["status"] == "CLAIMED_ITEM"
    assert validate_success(api.get_sku(parties["sku"]["id"], OPS))["stock_packs"] == 4

    shipments, meta = validate_paginated(
        api.list_shipments(OPS, {"gift_order_id": gift["id"]})
    )
    assert meta["total_count"] == 1
    assert shipments[0]["status"] == "CREATED"
    assert shipments[0].get("cycle_id") is None

    assert not list_credits_of(api, parties["owner_id"], source_gift_order_id=gift["id"])


def test_a_claim_past_the_sixty_day_window_is_refused(api):
    """PRD §3.9: "Only the `RegistryOwner` may claim, and only within 60 days of `paid_at`,
    inclusive of the boundary day; a later attempt is refused with
    `ERR_GIFT_CLAIM_WINDOW_EXPIRED` (HTTP 409)."

    Design: Corner/validations/corner_gift_claim_after_sixty_day_window_rejected
    """
    parties, _registry, _item, gift = setup_paid_gift(
        api,
        quantity=1,
        requested_quantity=1,
        sku_overrides={"code": unique_code("S2-GIFT"), "name": "Stage 2 Gift Pack",
                       "pack_price_cents": 1000, "stock_packs": 5},
    )
    set_clock(api, "2026-08-05T00:00:00Z")

    resp = api.claim_gift_order(
        gift["id"], {"claim_mode": "CREDIT"}, parties["owner_headers"]
    )
    validate_error(resp, ApiErrorId.ERR_GIFT_CLAIM_WINDOW_EXPIRED.value, 409)

    after = read_gift_order(api, gift["id"], parties["owner_headers"])
    assert after["status"] == "PAID"
    assert after.get("claim_mode") is None
    assert not list_credits_of(api, parties["owner_id"])


# ==========================================================================
# The five-hop gift-refund cascade
# ==========================================================================
def _gift_credit_covering_a_planned_cycle(api):
    """A 3600-cent GIFT credit that fully covers the owner's first cycle."""
    parties = setup_registry_parties(api, with_plan=True)
    registry = make_registry(api, parties, title="Cascade Registry")
    item = make_registry_item(api, parties, registry["id"], requested_quantity=3)
    validate_success(api.open_registry(registry["id"], parties["owner_headers"]))

    gift = reserve_gift(api, parties, item, 3)
    gift = pay_gift(api, parties, gift["id"])
    claim_gift(api, parties, gift["id"], "CREDIT")
    credit = gift_credit_of(api, parties)

    subscription = make_subscription(
        api, parties["owner"], parties["plan"], parties["child"]
    )
    subscription = activate(api, parties["owner_id"], subscription["id"])
    cycle = generate_cycle(api, subscription["id"])
    allocate_cycle(api, cycle["id"])
    cycle = charge_cycle(api, cycle["id"])
    assert cycle["payment_status"] == "FULLY_COVERED"
    return parties, item, gift, credit, cycle


def test_refunding_a_claimed_gift_revokes_the_credit_and_uncovers_the_cycle(api):
    """PRD §3.9: "Hop one: the gift moves `CLAIMED_CREDIT → REFUNDED`. Hop two: because the
    gift was refunded, the derived `GIFT` credit moves to `REVOKED`, its `remaining_cents`
    moving into `forfeited_cents`. Hop three: because that credit was revoked while a planned
    cycle had already consumed part of it, that cycle's `gift_credit_applied_cents` is reversed
    and its `total_due_cents` recomputed upward. Hop four: because the total rose above 0, the
    cycle's payment axis moves `FULLY_COVERED → UNCHARGED` — the back-edge that makes the
    payment axis re-entrant — and this applies to cycles whose `status` is `PLANNED` or
    `ALLOCATED`."
    PRD §2.9: "`issued_cents` itself is never mutated after issuance."

    Design: Difficulty/transitive_cascade/gift_refund_cascade_revokes_credit_and_uncovers_cycle
    """
    parties, _item, gift, credit, cycle = _gift_credit_covering_a_planned_cycle(api)

    validate_success(api.refund_gift_order(gift["id"], parties["purchaser_headers"]))

    assert read_gift_order(api, gift["id"], parties["purchaser_headers"])["status"] == "REFUNDED"

    after_credit = read_credit(api, credit["id"], parties["owner_id"])
    assert after_credit["status"] == "REVOKED"
    assert after_credit["issued_cents"] == 3600
    assert after_credit["remaining_cents"] == 0
    assert_credit_conserved(after_credit)

    after_cycle = read_cycle(api, cycle["id"])
    assert after_cycle["gift_credit_applied_cents"] == 0
    assert after_cycle["total_due_cents"] == 2999
    assert after_cycle["payment_status"] == "UNCHARGED"


def test_the_gift_refund_cascade_reaches_the_estimate_and_the_registry_item(api):
    """PRD §3.9: "Hop five: because the cycle became `UNCHARGED`, the household's
    `next_charge_estimate_cents` is recomputed. The item's `fulfilled_quantity` is decremented
    exactly as in the simpler case."
    PRD §3.9: "Hop two: because the gift was refunded, the item's `fulfilled_quantity` is
    decremented by the refunded quantity, driving the item `FULFILLED → PARTIALLY_FULFILLED`
    when some coverage survives, or `PARTIALLY_FULFILLED → REQUESTED` when the fulfilled
    quantity falls to 0."

    Design: Difficulty/transitive_cascade/gift_refund_cascade_revokes_credit_and_uncovers_cycle
    """
    parties, item, gift, _credit, _cycle = _gift_credit_covering_a_planned_cycle(api)

    validate_success(api.refund_gift_order(gift["id"], parties["purchaser_headers"]))

    assert read_account(api, parties["owner_id"])["next_charge_estimate_cents"] == 2999

    after_item = read_registry_item(api, item["id"], parties["owner_headers"])
    assert after_item["fulfilled_quantity"] == 0
    assert after_item["status"] == "REQUESTED"


# ==========================================================================
# Registry units are conserved across pay and refund
# ==========================================================================
def _two_paid_gifts_on_one_item(api):
    parties, _registry, item = setup_open_registry(api, requested_quantity=3)
    first = reserve_gift(api, parties, item, 2)
    first = pay_gift(api, parties, first["id"])
    after_first = read_registry_item(api, item["id"], parties["purchaser_headers"])

    second = reserve_gift(api, parties, item, 1)
    second = pay_gift(api, parties, second["id"])
    return parties, item, first, second, after_first


def test_refunding_one_of_two_gifts_leaves_the_units_conserved(api):
    """PRD §2.9: "Registry units are conserved: a `RegistryItem`'s `fulfilled_quantity`
    always equals the sum of `quantity` over the gift orders on that item whose `status` is
    `PAID`, `CLAIMED_CREDIT`, `CLAIMED_ITEM` or `FULFILLED`. Paying a gift increments it;
    refunding a gift decrements it. The item's `requested_quantity` is never mutated by gift
    activity, and `fulfilled_quantity` never exceeds `requested_quantity`."

    Design: Difficulty/compensating_invariant/registry_gift_units_conserved_across_pay_and_refund
    """
    parties, item, first, _second, after_first = _two_paid_gifts_on_one_item(api)
    assert after_first["fulfilled_quantity"] == 2

    validate_success(api.refund_gift_order(first["id"], parties["purchaser_headers"]))

    final_item = read_registry_item(api, item["id"], parties["owner_headers"])
    assert final_item["requested_quantity"] == 3
    assert final_item["fulfilled_quantity"] == 1
    assert final_item["status"] == "PARTIALLY_FULFILLED"

    gifts, _meta = validate_paginated(
        api.list_gift_orders(parties["purchaser_headers"], {"registry_item_id": item["id"]})
    )
    assert_registry_units_conserved(final_item, gifts)


def test_the_refunded_gift_keeps_its_paid_face_value_and_the_survivor_is_untouched(api):
    """PRD §3.9: "Refunding a gift that is still merely `PAID` runs three hops. Hop one: the
    gift moves `PAID → REFUNDED` and a `Refund` is created in `REQUESTED` with `reason`
    `GIFT_REFUND`, `requested_cents` equal to `paid_cents` and `restock_fee_cents` 0."
    PRD §3.9: "`paid_cents` is set to the gift's `quantity` multiplied by the effective
    per-pack price of the SKU *as it stands at the moment of payment*"

    Design: Difficulty/compensating_invariant/registry_gift_units_conserved_across_pay_and_refund
    """
    parties, _item, first, second, _after_first = _two_paid_gifts_on_one_item(api)

    validate_success(api.refund_gift_order(first["id"], parties["purchaser_headers"]))

    refunded = read_gift_order(api, first["id"], parties["purchaser_headers"])
    assert refunded["status"] == "REFUNDED"
    assert refunded["paid_cents"] == 2400

    survivor = read_gift_order(api, second["id"], parties["purchaser_headers"])
    assert survivor["status"] == "PAID"
    assert survivor["paid_cents"] == 1200
