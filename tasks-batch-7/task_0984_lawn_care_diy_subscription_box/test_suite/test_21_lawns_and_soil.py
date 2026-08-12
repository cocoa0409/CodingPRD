"""Lawn creation, reverse lookup, pagination, soft-delete archiving, and the
soil-kit entry state (PRD 2.3, 3.3)."""
import test_helpers as th

ADMIN = th.TEST_USERS["platform_admin_headers"]


def test_lawn_create_and_reverse_lookup(api):
    """PRD 3.3: "A customer onboards a property by creating a lawn profile with a `customer_id` that must equal the caller's `X-User-ID`, a human `label` such as "Front yard", the `lawn_size_sqm` area in square meters — which must be greater than zero and which determines the pricing tier used later for shipments — a `grass_type` of `COOL_SEASON`, `WARM_SEASON`, or `MIXED`, and a `region` key that the weather gate will match against advisories."
    PRD 3.3: "List reads accept optional `customer_id` and `status` filters, and kit lists accept `lawn_id` and `status` filters."

    Design: Corner/entities/lawn_create_and_reverse_lookup
    """
    customer = th.register_customer(email="c2@x.com", full_name="C Two")
    headers = th.make_customer_headers(customer["id"])
    lawn = th.validate_success(
        api.create_lawn(th.lawn_payload(customer["id"]), headers), 201
    )
    th.assert_lawn(lawn)
    assert lawn["customer_id"] == customer["id"]
    assert lawn["label"] == "Front"
    assert lawn["lawn_size_sqm"] == 100
    assert lawn["status"] == "ACTIVE"

    data, meta = th.validate_paginated(
        api.list_lawns(ADMIN, params={"customer_id": customer["id"]})
    )
    assert len(data) == 1
    assert data[0]["id"] == lawn["id"]


def test_lawn_list_pagination_envelope(api):
    """PRD 2.3: "All list endpoints accept two query parameters: `limit` and `offset`. The `limit` parameter defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter defaults to 0. List responses are always sorted by `created_at` in ascending order. The `meta` object of a list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`, where `total_count` is the number of records matching the filters and `has_more` indicates whether further records exist beyond the returned page."

    Design: Corner/entities/lawn_list_pagination_envelope
    """
    customer = th.register_customer(email="c6@x.com", full_name="C Six")
    headers = th.make_customer_headers(customer["id"])
    for label, size in (("Front", 100), ("Back", 200)):
        th.validate_success(
            api.create_lawn(
                th.lawn_payload(customer["id"], label=label, lawn_size_sqm=size),
                headers,
            ),
            201,
        )

    page1, meta1 = th.validate_paginated(
        api.list_lawns(ADMIN, params={"customer_id": customer["id"], "limit": 1,
                                      "offset": 0})
    )
    assert len(page1) == 1
    assert meta1["total_count"] == 2
    assert meta1["has_more"] is True

    page2, meta2 = th.validate_paginated(
        api.list_lawns(ADMIN, params={"customer_id": customer["id"], "limit": 1,
                                      "offset": 1})
    )
    assert len(page2) == 1
    assert meta2["total_count"] == 2
    assert meta2["has_more"] is False
    assert page1[0]["id"] != page2[0]["id"], "the two pages partition the list"


def test_soil_test_initial_state(api):
    """PRD 3.3: "The kit ships immediately, entering `KIT_SHIPPED` status with `reship_count` at 0 and `rejection_reason` null."

    Design: Corner/entities/soil_test_initial_state
    """
    customer = th.register_customer(email="c5@x.com", full_name="C Five")
    lawn = th.create_lawn(customer)
    kit = th.order_soil_test(customer, lawn)
    th.assert_soil_test(kit)
    assert kit["status"] == "KIT_SHIPPED"
    assert kit["reship_count"] == 0
    assert kit["rejection_reason"] is None


def test_archived_lawn_blocks_soil_order(api):
    """PRD 3.3: "A customer orders a kit for a lawn by its `lawn_id`; the lawn must be `ACTIVE`, otherwise `ERR_LAWN_ARCHIVED` (HTTP 409)."
    PRD 3.3: "A lawn starts in `ACTIVE` status and can later be soft-deleted to `ARCHIVED`."

    Design: Corner/validations/archived_lawn_blocks_soil_order
    """
    customer = th.register_customer(email="v14@x.com")
    headers = th.make_customer_headers(customer["id"])
    lawn = th.create_lawn(customer)
    archived = th.validate_success(
        api.patch_lawn(lawn["id"], {"status": "ARCHIVED"}, headers)
    )
    assert archived["status"] == "ARCHIVED"

    th.validate_error(
        api.create_soil_test(th.soil_test_payload(lawn["id"]), headers),
        th.ApiErrorId.ERR_LAWN_ARCHIVED,
    )
    # Soft delete, not erasure: the lawn remains readable.
    fetched = th.validate_success(api.get_lawn(lawn["id"], ADMIN))
    assert fetched["status"] == "ARCHIVED"


def test_lawn_archive_blocked_by_open_applications(api):
    """PRD 3.3: "Archiving requires ownership and requires that no application task of the lawn sits in `SCHEDULED`, `FROZEN`, or `AWAITING_DELIVERY`; open applications block the archive with `ERR_LAWN_HAS_OPEN_APPLICATIONS` (HTTP 409)."

    Design: Corner/validations/lawn_archive_blocked_by_open_applications
    """
    ctx = th.setup_active_subscription(email="v15@x.com")
    box, _ = th.setup_delivered_box(ctx, lines=[th.shipment_line("FERT-01", 1)])
    th.validate_success(
        api.create_application(
            th.application_payload(ctx["subscription"]["id"], box["id"],
                                   product_sku="FERT-01",
                                   scheduled_date="2026-06-10"),
            ctx["customer_headers"],
        ),
        201,
    )
    th.validate_error(
        api.patch_lawn(ctx["lawn"]["id"], {"status": "ARCHIVED"},
                       ctx["customer_headers"]),
        th.ApiErrorId.ERR_LAWN_HAS_OPEN_APPLICATIONS,
    )
    lawn = th.validate_success(api.get_lawn(ctx["lawn"]["id"], ADMIN))
    assert lawn["status"] == "ACTIVE", "a blocked archive leaves the lawn ACTIVE"
