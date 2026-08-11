"""Labels and shipments — the machinery both pipelines share outright."""

from test_helpers import (
    LOGISTICS,
    WAREHOUSE,
    ApiErrorId,
    assert_same_instant,
    assert_shipment,
    assert_shipping_label,
    allocate_unit,
    create_box,
    create_open_cycle,
    create_shipment_payload,
    create_style,
    create_unit,
    get_box_item,
    get_label,
    get_shipment,
    make_member_headers,
    mint_label,
    set_clock,
    setup_plan_and_member,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestLabelLifecycle:
    def test_a_labels_expiry_and_its_reissued_successor(self, api):
        """PRD §3.5: "A minted label is `ISSUED`, records `issued_at` at the
        logical clock, carries a `tracking_code` minted with it, starts with
        `reissue_count` at 0 and `replaces_label_id` null, and expires at
        `issued_at` plus `LABEL_VALID_DAYS`, fourteen days."
        PRD §3.5: "Reissue does not resurrect the old row: it mints a **new**
        label with `status` `ISSUED`, `replaces_label_id` pointing at the
        predecessor, `reissue_count` equal to the predecessor's `reissue_count`
        plus one, and `expires_at` re-derived as fourteen days from the
        *current* logical clock; the predecessor stays in its terminal `VOIDED`
        or `EXPIRED` status."

        Design: Corner/entities/corner_shipping_label_expiry_and_reissue_self_reference
        """
        _, member = setup_plan_and_member()
        first = mint_label(member["id"], "RETURN")
        assert_shipping_label(first)
        validate_success(api.void_shipping_label(first["id"], LOGISTICS))

        successor = validate_success(
            api.reissue_shipping_label(first["id"], LOGISTICS), 201
        )
        predecessor = get_label(first["id"])
        assert_same_instant(predecessor["expires_at"], "2026-05-15T00:00:00.000Z",
                            "ShippingLabel.expires_at")
        assert predecessor["status"] == "VOIDED"
        assert predecessor["reissue_count"] == 0
        assert successor["status"] == "ISSUED"
        assert successor["reissue_count"] == 1
        assert successor["replaces_label_id"] == first["id"]
        assert successor["direction"] == "RETURN"

    def test_the_reissue_chain_terminates_at_the_declared_cap(self, api):
        """PRD §3.5: "Because the count is carried forward along the
        `replaces_label_id` chain and `LABEL_REISSUE_CAP` is 2, the chain
        terminates: a reissue attempted on a label whose `reissue_count` has
        already reached 2 is refused with `ERR_LABEL_REISSUE_CAP_REACHED`."
        PRD §2.6 rung 50: "A label's `reissue_count` must be strictly below two.
        Otherwise `ERR_LABEL_REISSUE_CAP_REACHED` (409). Applies to
        `POST /kidswear/shipping-labels/{label_id}/reissue`. Shared by both
        pipelines."

        Design: Corner/state_machines/corner_sm_label_reissue_beyond_cap_is_rejected
        """
        _, member = setup_plan_and_member()
        label_zero = mint_label(member["id"], "RETURN")
        validate_success(api.void_shipping_label(label_zero["id"], LOGISTICS))
        label_one = validate_success(api.reissue_shipping_label(label_zero["id"], LOGISTICS), 201)
        validate_success(api.void_shipping_label(label_one["id"], LOGISTICS))
        label_two = validate_success(api.reissue_shipping_label(label_one["id"], LOGISTICS), 201)
        validate_success(api.void_shipping_label(label_two["id"], LOGISTICS))

        resp = api.reissue_shipping_label(label_two["id"], LOGISTICS)
        validate_error(resp, ApiErrorId.ERR_LABEL_REISSUE_CAP_REACHED.value, 409)

        final = get_label(label_two["id"])
        assert final["reissue_count"] == 2
        assert final["status"] == "VOIDED"
        _, meta = validate_paginated(api.list_shipping_labels(
            LOGISTICS, {"member_id": member["id"], "limit": 100, "offset": 0}))
        assert meta["total_count"] == 3

    def test_voiding_a_voided_label_is_an_invalid_label_state(self, api):
        """PRD §2.6 rung 29: "`ShippingLabel.status` is a declared from-state for
        the requested label transition. Otherwise `ERR_LABEL_INVALID_STATE`
        (409). Applies to label transition endpoints and to departure and box
        shipping. This one rung governs `OUTBOUND`, `RETURN`,
        `TRADE_IN_INBOUND` and `REJECT_RETURN` labels alike."
        PRD §3.5: "An unused `ISSUED` label may be **voided** by the
        coordinator, but only when no shipment referencing it has reached
        `IN_TRANSIT` or `DELIVERED`."

        Design: Corner/errors/corner_err_voiding_an_already_voided_label_is_rejected
        """
        _, member = setup_plan_and_member()
        label = mint_label(member["id"], "RETURN")
        validate_success(api.void_shipping_label(label["id"], LOGISTICS))

        resp = api.void_shipping_label(label["id"], LOGISTICS)
        validate_error(resp, ApiErrorId.ERR_LABEL_INVALID_STATE.value, 409)

        after = get_label(label["id"])
        assert after["status"] == "VOIDED"
        assert after["reissue_count"] == 0

    def test_expiring_a_label_before_its_window_closes_is_refused(self, api):
        """PRD §3.5: "An `ISSUED` label whose window has passed may be
        **expired**, and only then: expiring a label at or before its
        `expires_at` is refused with `ERR_LABEL_NOT_EXPIRED`."

        Design: Corner/errors/corner_err_label_expired_before_its_validity_ends_is_rejected
        """
        _, member = setup_plan_and_member()
        label = mint_label(member["id"], "RETURN")
        set_clock("2026-05-10T00:00:00Z")

        resp = api.expire_shipping_label(label["id"], LOGISTICS)
        validate_error(resp, ApiErrorId.ERR_LABEL_NOT_EXPIRED.value, 409)

        after = get_label(label["id"])
        assert after["status"] == "ISSUED"
        assert_same_instant(after["expires_at"], "2026-05-15T00:00:00.000Z",
                            "ShippingLabel.expires_at")

    def test_a_departure_after_the_label_has_expired_is_refused(self, api):
        """PRD §2.6 rung 37: "A shipping label may authorise a departure only
        while the logical clock is on or before its `expires_at`; the boundary
        is **inclusive**. Otherwise `ERR_LABEL_EXPIRED` (409). Applies to
        `POST /kidswear/shipments/{shipment_id}/depart`,
        `POST /kidswear/boxes/{box_id}/ship` and
        `POST /kidswear/box-items/{box_item_id}/start-return`. Shared by both
        pipelines."
        PRD §3.5: "**Departure** moves it `CREATED → IN_TRANSIT`, requires the
        label to be `ISSUED` and unexpired, sets `shipped_at` to the logical
        clock, sets `ever_scanned` true, and advances the label `ISSUED →
        IN_TRANSIT`."

        Design: Corner/state_machines/corner_sm_label_departure_after_expiry_is_rejected
        """
        _, member = setup_plan_and_member()
        label = mint_label(member["id"], "TRADE_IN_INBOUND")
        shipment = validate_success(
            api.create_shipment(
                create_shipment_payload(member["id"], label["id"], "TRADE_IN_INBOUND", 0),
                LOGISTICS,
            ),
            201,
        )
        set_clock("2026-05-16T00:00:00Z")

        resp = api.depart_shipment(shipment["id"], LOGISTICS)
        validate_error(resp, ApiErrorId.ERR_LABEL_EXPIRED.value, 409)

        after_label = get_label(label["id"])
        assert after_label["status"] == "ISSUED"
        assert_same_instant(after_label["expires_at"], "2026-05-15T00:00:00.000Z",
                            "ShippingLabel.expires_at")
        assert get_shipment(shipment["id"])["status"] == "CREATED"


class TestShipmentLifecycle:
    def test_a_second_departure_does_not_restamp_the_scan(self, api):
        """PRD §2.6 rung 28: "`Shipment.status` is a declared from-state for the
        requested shipment transition. Otherwise `ERR_SHIPMENT_INVALID_STATE`
        (409). Applies to shipment transition endpoints."
        PRD §3.5: "**Departure** moves it `CREATED → IN_TRANSIT`, requires the
        label to be `ISSUED` and unexpired, sets `shipped_at` to the logical
        clock, sets `ever_scanned` true, and advances the label `ISSUED →
        IN_TRANSIT`."

        Design: Corner/state_machines/corner_sm_shipment_second_departure_is_rejected
        """
        _, member = setup_plan_and_member()
        label = mint_label(member["id"], "RETURN")
        shipment = validate_success(
            api.create_shipment(
                create_shipment_payload(member["id"], label["id"], "RETURN", 0), LOGISTICS
            ),
            201,
        )
        assert_shipment(shipment)
        validate_success(api.depart_shipment(shipment["id"], LOGISTICS))

        resp = api.depart_shipment(shipment["id"], LOGISTICS)
        validate_error(resp, ApiErrorId.ERR_SHIPMENT_INVALID_STATE.value, 409)

        after = get_shipment(shipment["id"])
        assert after["status"] == "IN_TRANSIT"
        assert_same_instant(after["shipped_at"], "2026-05-01T00:00:00.000Z",
                            "Shipment.shipped_at")
        assert after["ever_scanned"] is True

    def test_return_to_sender_is_reserved_for_reject_return_parcels(self, api):
        """PRD §3.5: "Separately, a `REJECT_RETURN` shipment carrying rejected
        trade-in garments back to the household moves `IN_TRANSIT →
        RETURNED_TO_SENDER`, advancing its label to `DELIVERED` and leaving each
        covered item's `RETURN_TO_MEMBER` disposition intact; attempting that
        operation on a shipment of any other direction is refused with
        `ERR_SHIPMENT_DIRECTION_MISMATCH`, and any shipment transition attempted
        from an undeclared from-state is refused with
        `ERR_SHIPMENT_INVALID_STATE`."

        Design: Corner/errors/corner_err_return_to_sender_on_a_return_shipment_is_rejected
        """
        _, member = setup_plan_and_member()
        label = mint_label(member["id"], "RETURN")
        shipment = validate_success(
            api.create_shipment(
                create_shipment_payload(member["id"], label["id"], "RETURN", 0), LOGISTICS
            ),
            201,
        )
        validate_success(api.depart_shipment(shipment["id"], LOGISTICS))

        resp = api.return_shipment_to_sender(shipment["id"], LOGISTICS)
        validate_error(resp, ApiErrorId.ERR_SHIPMENT_DIRECTION_MISMATCH.value, 409)
        assert get_shipment(shipment["id"])["status"] == "IN_TRANSIT"

    def test_an_allocated_item_may_not_start_a_return(self, api):
        """PRD §3.6: "It requires the item's `fulfillment_status` to be `SHIPPED`
        or `WITH_MEMBER`, its `settlement_status` to still be `OPEN`, and the
        return label to be `ISSUED` with the logical clock on or before its
        `expires_at`."
        PRD §3.6: "An item addressed in a fulfillment state that does not
        declare the transition is refused with
        `ERR_BOX_ITEM_INVALID_FULFILLMENT_STATE`."

        Design: Corner/errors/corner_err_start_return_on_an_unshipped_item_is_rejected
        """
        _, member = setup_plan_and_member(plan={"slots_per_box": 2})
        style = create_style(sku="SKU-Y3-5", name="State Three Tee", size_code="5")
        unit = create_unit(style["id"], acquired_at="2026-02-01T00:00:00Z")
        cycle = create_open_cycle(member["id"])
        box = create_box(cycle["id"])
        item = allocate_unit(box["id"], unit_id=unit["id"])
        label = mint_label(member["id"], "RETURN")
        shipment = validate_success(
            api.create_shipment(
                create_shipment_payload(member["id"], label["id"], "RETURN", 1), LOGISTICS
            ),
            201,
        )

        resp = api.start_return(item["id"], {"return_shipment_id": shipment["id"]},
                                make_member_headers(member["id"]))
        validate_error(resp, ApiErrorId.ERR_BOX_ITEM_INVALID_FULFILLMENT_STATE.value, 409)

        after = get_box_item(item["id"])
        assert after["fulfillment_status"] == "ALLOCATED"
        assert after["settlement_status"] == "OPEN"
        assert after["return_shipment_id"] is None
