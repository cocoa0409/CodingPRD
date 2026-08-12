"""The bench: farriers, shoe SKUs, the two kinds of bucket and stock transfers."""

from test_helpers import *  # noqa: F401,F403


def test_shoe_sku_creation_mints_shop_and_van_buckets(api, admin):
    """PRD §3.2: "There is exactly one `SHOP` bucket per SKU, and its `farrier_id`
    is null; there is one `VAN` bucket per farrier per SKU, and its `farrier_id`
    names that farrier."
    PRD §3.2: "Every freshly minted bucket has `on_hand_pairs`, `available_pairs`
    and `reserved_pairs` all at 0 and, because the flag is recomputed on every
    write **including creation**, a `replenishment_flag` of true."

    Both farriers on file are `ACTIVE`, so the per-existing-farrier and
    per-ACTIVE-farrier readings of the minting rule name the same two farriers.

    Design: Corner/entities/corner_shoe_sku_creation_mints_shop_and_van_buckets
    """
    first = create_farrier(display_name="Kenji Mori")
    second = create_farrier(
        display_name="Rina Sato", certification_level="APPRENTICE"
    )
    assert first["status"] == "ACTIVE" and second["status"] == "ACTIVE"

    sku = validate_success(
        api.create_shoe_sku(shoe_sku_payload(sku_code="ST-1"), admin), 201
    )

    rows, _meta = validate_paginated(
        api.list_inventory_buckets(admin, params={"sku_id": sku["id"]})
    )
    assert len(rows) == 3, "one SHOP bucket plus one VAN bucket per farrier"
    shop_rows = [row for row in rows if row["location_kind"] == "SHOP"]
    assert len(shop_rows) == 1
    assert shop_rows[0]["farrier_id"] is None, "the SHOP bucket's farrier_id is null"

    for farrier in (first, second):
        vans, _m = validate_paginated(
            api.list_inventory_buckets(
                admin,
                params={
                    "sku_id": sku["id"],
                    "farrier_id": farrier["id"],
                    "location_kind": "VAN",
                },
            )
        )
        assert len(vans) == 1, "exactly one VAN bucket per farrier per SKU"

    for row in rows:
        assert_inventory_bucket(row)
        assert row["on_hand_pairs"] == 0
        assert row["available_pairs"] == 0
        assert row["reserved_pairs"] == 0
        assert row["replenishment_flag"] is True


def test_farrier_creation_mints_a_van_bucket_per_existing_sku(api, admin):
    """PRD §3.2: "Buckets are minted automatically and never by hand: creating a
    farrier mints one `VAN` bucket for each existing SKU, and creating a SKU mints
    its one `SHOP` bucket plus one `VAN` bucket per existing farrier."

    Design: Corner/entities/corner_farrier_creation_mints_a_van_bucket_per_existing_sku
    """
    create_sku(sku_code="ST-1", material="STEEL")
    create_sku(sku_code="AL-1", material="ALUMINUM", price_cents_per_pair=9100)

    farrier = validate_success(api.create_farrier(farrier_payload(), admin), 201)

    assert_farrier(farrier)
    assert farrier["status"] == "ACTIVE"
    vans, _meta = validate_paginated(
        api.list_inventory_buckets(admin, params={"farrier_id": farrier["id"]})
    )
    assert len(vans) == 2, "one VAN bucket per existing SKU"
    assert {row["location_kind"] for row in vans} == {"VAN"}
    assert len({row["sku_id"] for row in vans}) == 2, "one per SKU"

    shops, _m = validate_paginated(
        api.list_inventory_buckets(admin, params={"location_kind": "SHOP"})
    )
    assert len(shops) == 2, "the two SHOP buckets are untouched"


def test_reactivate_cannot_clear_a_decertified_farrier(api, admin):
    """PRD §3.2: "A `reason` of `VOLUNTARY` moves `ACTIVE` to `INACTIVE`; a `reason`
    of `CERT_EXPIRED` moves `ACTIVE` to `DECERTIFIED`."
    PRD §3.2: "Reactivation returns `INACTIVE` to `ACTIVE` and increments `version`
    by 1, and it is refused with `ERR_INVALID_STATE` for a farrier who is
    `DECERTIFIED` or already `ACTIVE`."

    Design: Corner/state_machines/corner_reactivate_cannot_clear_a_decertified_farrier
    """
    farrier = create_farrier()
    stood_down = validate_success(
        api.deactivate_farrier(farrier["id"], {"reason": "CERT_EXPIRED"}, admin)
    )
    assert stood_down["status"] == "DECERTIFIED"

    response = api.reactivate_farrier(farrier["id"], admin)

    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value)
    assert response.status_code == 409
    assert read_farrier(farrier["id"])["status"] == "DECERTIFIED"


def test_recertify_returns_a_decertified_farrier_to_active(api, admin):
    """PRD §3.2: "Recertification is the only way out of `DECERTIFIED`: it accepts a
    fresh `certification_level` and `cert_expires_on`, requires that the supplied
    expiry be on or after the logical clock date, writes both values, sets `status`
    to `ACTIVE` and increments `version` by 1."

    Design: Corner/state_machines/corner_recertify_returns_a_decertified_farrier_to_active
    """
    set_clock("2026-05-04T08:00:00Z")
    farrier = create_farrier(certification_level="APPRENTICE")
    get_success_data(
        api.deactivate_farrier(farrier["id"], {"reason": "CERT_EXPIRED"}, admin)
    )

    data = validate_success(
        api.recertify_farrier(
            farrier["id"],
            {
                "certification_level": "CERTIFIED_THERAPEUTIC",
                "cert_expires_on": "2028-06-30",
            },
            admin,
        )
    )

    assert_farrier(data)
    assert data["status"] == "ACTIVE"
    assert data["certification_level"] == "CERTIFIED_THERAPEUTIC"
    assert_same_date(data["cert_expires_on"], "2028-06-30")


def test_stock_transfer_abort_returns_the_pairs_to_the_shop_bucket(api, admin):
    """PRD §3.2: "Dispatching it requires the shop bucket to hold at least
    `quantity_pairs` in `available_pairs` — otherwise `ERR_SHOP_STOCK_INSUFFICIENT`
    — and then lowers the shop bucket's `on_hand_pairs` and `available_pairs` by
    that quantity, recomputes the shop bucket's flag, moves the transfer to
    `IN_TRANSIT` and increments its `version` by 1."
    PRD §3.2: "Aborting an `IN_TRANSIT` transfer returns the pairs to the shop
    bucket — `on_hand_pairs` and `available_pairs` both rise by the quantity —
    moves the transfer to `ABORTED` and increments its `version` by 1."

    Design: Corner/state_machines/corner_stock_transfer_abort_returns_the_pairs_to_the_shop_bucket
    """
    sku = create_sku()
    farrier = create_farrier()
    shop = shop_bucket(sku["id"])
    van = van_bucket(farrier["id"], sku["id"])
    adjust_bucket(shop["id"], 12)
    transfer = create_transfer(sku["id"], shop["id"], van["id"], quantity_pairs=5)
    get_success_data(api.dispatch_stock_transfer(transfer["id"], admin))

    before = read_bucket(shop["id"])
    assert before["on_hand_pairs"] == 7, "dispatch removed 5 of the 12 shop pairs"
    assert before["available_pairs"] == 7
    assert read_transfer(transfer["id"])["status"] == "IN_TRANSIT"
    assert before["on_hand_pairs"] + 5 == 12, "in-transit pairs conserve the system total"

    data = validate_success(api.abort_stock_transfer(transfer["id"], admin))

    assert_stock_transfer(data)
    assert data["status"] == "ABORTED"
    after_shop = read_bucket(shop["id"])
    assert after_shop["on_hand_pairs"] == 12
    assert after_shop["available_pairs"] == 12
    assert after_shop["reserved_pairs"] == 0
    assert_bucket_balance(after_shop)
    assert read_bucket(van["id"])["on_hand_pairs"] == 0, "no van bucket was touched"


def test_transfer_dispatch_beyond_shop_stock_is_rejected(api, admin):
    """PRD §3.2: "Dispatching it requires the shop bucket to hold at least
    `quantity_pairs` in `available_pairs` — otherwise `ERR_SHOP_STOCK_INSUFFICIENT`
    — and then lowers the shop bucket's `on_hand_pairs` and `available_pairs` by
    that quantity, recomputes the shop bucket's flag, moves the transfer to
    `IN_TRANSIT` and increments its `version` by 1."
    PRD §2.7: "(52) The shop bucket holds enough pairs, else
    `ERR_SHOP_STOCK_INSUFFICIENT` (HTTP 409); on transfer dispatch."

    Design: Corner/validations/corner_transfer_dispatch_beyond_shop_stock_is_rejected
    """
    sku = create_sku()
    farrier = create_farrier()
    shop = shop_bucket(sku["id"])
    van = van_bucket(farrier["id"], sku["id"])
    adjust_bucket(shop["id"], 3)
    transfer = create_transfer(sku["id"], shop["id"], van["id"], quantity_pairs=5)

    response = api.dispatch_stock_transfer(transfer["id"], admin)

    validate_error(response, ApiErrorId.ERR_SHOP_STOCK_INSUFFICIENT.value)
    assert response.status_code == 409
    assert read_transfer(transfer["id"])["status"] == "REQUESTED"
    unchanged = read_bucket(shop["id"])
    assert unchanged["on_hand_pairs"] == 3
    assert unchanged["available_pairs"] == 3


def test_replenishment_flag_flips_exactly_at_the_reorder_point(api, admin):
    """PRD §3.2: "The axis is a threshold, not a judgement: the flag is true exactly
    while `available_pairs` is less than or equal to 2 (`REORDER_POINT_PAIRS`). The
    comparison is inclusive, so a bucket holding exactly two available pairs **is**
    flagged and one holding three is not."
    PRD §3.2: "A stock-take reconciles a bucket against reality. It takes a single
    `delta_pairs`, which may be positive or negative, adds it to both
    `on_hand_pairs` and `available_pairs`, recomputes the replenishment flag, and
    increments the bucket's `version` by 1."

    Design: Corner/calculations/corner_replenishment_flag_flips_exactly_at_the_reorder_point
    """
    sku = create_sku()
    farrier = create_farrier()
    van = van_bucket(farrier["id"], sku["id"])
    at_three = adjust_bucket(van["id"], 3)
    assert at_three["available_pairs"] == 3
    assert at_three["replenishment_flag"] is False, "three available pairs is not flagged"

    data = validate_success(
        api.adjust_inventory_bucket(van["id"], {"delta_pairs": -1}, admin)
    )

    assert_inventory_bucket(data)
    assert data["available_pairs"] == REORDER_POINT_PAIRS
    assert data["on_hand_pairs"] == 2
    assert data["reserved_pairs"] == 0
    assert data["replenishment_flag"] is True, "exactly two available pairs is flagged"
