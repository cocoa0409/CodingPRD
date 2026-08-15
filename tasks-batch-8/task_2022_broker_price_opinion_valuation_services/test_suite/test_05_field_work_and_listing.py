"""Field work: comparable adjustment cap boundary, adjusted-value floor, radius
floor, photo-evidence record shape, and the order listing filter."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_comparable,
    add_photo,
    assert_comparable,
    assert_photo_evidence,
    create_comparable_payload,
    dispatch_to_broker,
    drive_order_to_in_progress,
    new_order,
    setup_market,
    submit_order,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
)

OPS = TEST_USERS["operations_manager_headers"]


class TestComparableAdjustmentCap:
    def test_adjustment_at_exactly_25_percent_cap_accepted(self, api):
        """PRD §3.5: "the absolute value of `adjustment_cents` must not exceed 25
        percent of `sale_price_cents`, with the cap itself computed in integer
        cents rounded half-up; a breach is rejected with
        `ERR_ADJUSTMENT_EXCEEDS_CAP`."
        PRD §3.5: "its read-only `adjusted_value_cents` is always the sum of
        `sale_price_cents` and `adjustment_cents`."

        Design: Difficulty/boundary_precision_check/comparable_adjustment_cap_at_exactly_25_percent
        """
        env = setup_market("IL", client_code="CLK", broker_code="BRKK")
        order = drive_order_to_in_progress(env)

        # cap = round_half_up(0.25 * 40000001) = round_half_up(10000000.25)
        #     = 10000000; |10000000| <= cap passes.
        comp = add_comparable(env, order, sale_price_cents=40000001,
                              adjustment_cents=10000000)
        assert_comparable(comp)
        assert comp["status"] == "DRAFT"
        assert comp["adjusted_value_cents"] == 50000001

    def test_adjustment_one_cent_over_cap_rejected(self, api):
        """PRD §3.5: "the absolute value of `adjustment_cents` must not exceed 25
        percent of `sale_price_cents`, with the cap itself computed in integer
        cents rounded half-up; a breach is rejected with
        `ERR_ADJUSTMENT_EXCEEDS_CAP`."

        Design: Difficulty/boundary_precision_check/comparable_adjustment_cap_at_exactly_25_percent
        """
        env = setup_market("IL", client_code="CLK", broker_code="BRKK")
        order = drive_order_to_in_progress(env)

        # cap == 10000000; |10000001| > cap must be rejected.
        payload = create_comparable_payload(
            source_property_id=env["comp_properties"][0]["id"],
            sale_price_cents=40000001, distance_miles=1.5,
            adjustment_cents=10000001)
        resp = api.create_comparable(order["id"], payload, env["broker_headers"])
        validate_error(resp, ApiErrorId.ERR_ADJUSTMENT_EXCEEDS_CAP)


class TestAdjustedValueFloor:
    def test_adjustment_nonpositive_rejected(self, api):
        """PRD §3.5: "Second, the adjusted value must remain positive — if
        `sale_price_cents` plus `adjustment_cents` is zero or less, the rejection
        is `ERR_ADJUSTMENT_NONPOSITIVE`."
        (With sale_price_cents > 0 this always co-occurs with the 25-percent cap
        breach, which PRD §3.5 evaluates first; either error discharge carries
        HTTP 422.)

        Design: Corner/validations/adjustment_nonpositive_rejected
        """
        env = setup_market("CT", client_code="CAN", broker_code="BAN")
        order = drive_order_to_in_progress(env)

        payload = create_comparable_payload(
            source_property_id=env["comp_properties"][0]["id"],
            sale_price_cents=30000000, distance_miles=1.5,
            adjustment_cents=-30000000)
        resp = api.create_comparable(order["id"], payload, env["broker_headers"])
        assert resp.status_code == 422, (
            f"Expected 422, got {resp.status_code}: {resp.text}")
        validate_error_is_one_of(
            resp, [ApiErrorId.ERR_ADJUSTMENT_NONPOSITIVE,
                   ApiErrorId.ERR_ADJUSTMENT_EXCEEDS_CAP])


class TestComparableRadiusFloor:
    def test_error_comparable_radius_violation(self, api):
        """PRD §3.5: "`distance_miles` must be at least the state regulation's
        `min_driveby_radius_miles` for a `DRIVE_BY` order, or its
        `min_interior_radius_miles` for an `INTERIOR` order, else
        `ERR_COMPARABLE_RADIUS_VIOLATION`."

        Design: Corner/errors/error_comparable_radius_violation
        """
        env = setup_market("ID", client_code="CRV", broker_code="BRV",
                           reg_overrides={"min_driveby_radius_miles": 2.0})
        order = drive_order_to_in_progress(env)

        payload = create_comparable_payload(
            source_property_id=env["comp_properties"][0]["id"],
            sale_price_cents=30000000, distance_miles=1.0, adjustment_cents=0)
        resp = api.create_comparable(order["id"], payload, env["broker_headers"])
        validate_error(resp, ApiErrorId.ERR_COMPARABLE_RADIUS_VIOLATION)


class TestPhotoEvidenceRecord:
    def test_photo_evidence_immutable_no_version_field(self, api):
        """PRD §2.4: "`PhotoEvidence` rows, `QCRevisionRequest` rows, and
        `VolumeForecast` rows carry only `id` and `created_at`; both `updated_at`
        and `version` are absent on these three types"
        PRD §3.5: "The uploading broker's identity is stamped onto the row's
        `uploaded_by_broker_id` from `X-User-ID`."

        Design: Corner/entities/photo_evidence_immutable_no_version_field
        """
        env = setup_market("KS", client_code="CIM", broker_code="BIM")
        order = drive_order_to_in_progress(env)
        photo = add_photo(env, order, "FRONT")
        assert_photo_evidence(photo)
        assert photo["uploaded_by_broker_id"] == env["broker"]["id"]
        assert photo["order_id"] == order["id"]

        photos, _meta = validate_paginated(
            api.list_photos(order["id"], env["broker_headers"]))
        assert len(photos) == 1
        assert_photo_evidence(photos[0])
        assert photos[0]["id"] == photo["id"]


class TestOrderListingFilter:
    def test_list_orders_filter_by_fulfillment_status(self, api):
        """PRD §3.8: "Orders, finally, are listable by `PlatformAdmin`,
        `OperationsManager`, `DispatchCoordinator`, `BillingClerk`, `QCReviewer`,
        `ClientAdmin`, and `Broker`, with optional filters on `fulfillment_status`,
        `payment_status`, `client_id`, `assigned_broker_id`, and `property_id`"

        Design: Corner/endpoints/list_orders_filter_by_fulfillment_status
        """
        env = setup_market("RI", client_code="CFLT", broker_code="BFLT")
        intake = new_order(env)
        dispatched = new_order(env)
        dispatched = submit_order(env, dispatched)
        dispatched = dispatch_to_broker(env, dispatched)

        filtered, meta = validate_paginated(
            api.list_valuation_orders(OPS, params={"fulfillment_status": "DISPATCHED"}))
        filtered_ids = {o["id"] for o in filtered}
        assert dispatched["id"] in filtered_ids, (
            "Filtered list must contain the DISPATCHED order")
        assert intake["id"] not in filtered_ids, (
            "Filtered list must not contain the INTAKE order")
        for order in filtered:
            assert order["fulfillment_status"] == "DISPATCHED"

        unfiltered, _ = validate_paginated(api.list_valuation_orders(OPS))
        unfiltered_ids = {o["id"] for o in unfiltered}
        assert intake["id"] in unfiltered_ids
        assert dispatched["id"] in unfiltered_ids
