"""State registration windows, the three-way capacity split and its conservation."""

from test_helpers import (
    ApiErrorId,
    assert_blue_sky_registration,
    assert_registration_capacity,
    assert_registration_capacity_identity,
    capture_purchase,
    create_blue_sky_registration_payload,
    create_purchase_payload,
    money,
    only_position,
    price_trade,
    read_registration,
    read_share_class,
    settle_trade,
    setup_capacity_identity_desk,
    setup_exact_capacity_registration,
    setup_single_registration_window,
    shares,
    validate_error,
    validate_paginated,
    validate_success,
    TEST_USERS,
)

OPERATOR = TEST_USERS["operator_headers"]
COMPLIANCE = TEST_USERS["compliance_headers"]


class TestRegistrationWindowOverlap:
    def test_a_window_starting_on_the_incumbent_expiration_date_is_accepted(self, api):
        """PRD §3.4: "The window is half-open: the `effective_date` is inside it and the
        `expiration_date` is outside it."
        PRD §3.4: "For a given share class and state, a new window may not intersect the
        window of an existing registration whose `status` is `ACTIVE` or `EXHAUSTED`;
        because the interval is half-open, touching endpoints do not intersect, so a new
        registration whose `effective_date` equals an existing registration's
        `expiration_date` is accepted, while any genuine overlap is refused with
        `ERR_BLUE_SKY_WINDOW_OVERLAP`."
        PRD §3.4: "A new filing starts with `reserved_amount` and `consumed_amount` at
        `0.00`, `remaining_amount` equal to `registered_amount`, and `status` `ACTIVE`."

        Design: Difficulty/resource_temporal_overlap/blue_sky_windows_are_half_open_so_touching_endpoints_do_not_collide
        """
        setup = setup_single_registration_window()

        response = api.create_blue_sky_registration(
            create_blue_sky_registration_payload(
                setup["share_class"]["id"], state_code="CA",
                registered_amount=600000.00,
                effective_date="2026-09-01", expiration_date="2027-01-01",
            ),
            COMPLIANCE,
        )
        adjacent = validate_success(response, 201)
        assert_blue_sky_registration(adjacent)
        assert adjacent["status"] == "ACTIVE"
        assert adjacent["remaining_amount"] == money(600000.00)
        assert adjacent["reserved_amount"] == money(0.00)
        assert adjacent["consumed_amount"] == money(0.00)

    def test_a_window_starting_inside_the_incumbent_is_refused(self, api):
        """PRD §3.4: "For a given share class and state, a new window may not intersect
        the window of an existing registration whose `status` is `ACTIVE` or `EXHAUSTED`;
        because the interval is half-open, touching endpoints do not intersect, so a new
        registration whose `effective_date` equals an existing registration's
        `expiration_date` is accepted, while any genuine overlap is refused with
        `ERR_BLUE_SKY_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/blue_sky_windows_are_half_open_so_touching_endpoints_do_not_collide
        """
        setup = setup_single_registration_window()
        validate_success(
            api.create_blue_sky_registration(
                create_blue_sky_registration_payload(
                    setup["share_class"]["id"], state_code="CA",
                    registered_amount=600000.00,
                    effective_date="2026-09-01", expiration_date="2027-01-01",
                ),
                COMPLIANCE,
            ),
            201,
        )

        response = api.create_blue_sky_registration(
            create_blue_sky_registration_payload(
                setup["share_class"]["id"], state_code="CA",
                registered_amount=100000.00,
                effective_date="2026-08-15", expiration_date="2026-12-01",
            ),
            COMPLIANCE,
        )
        assert response.status_code == 409
        validate_error(response, ApiErrorId.ERR_BLUE_SKY_WINDOW_OVERLAP.value)

        _, meta = validate_paginated(
            api.list_share_class_blue_sky_registrations(
                setup["share_class"]["id"], COMPLIANCE, params={"state_code": "CA"}
            )
        )
        assert meta["total_count"] == 2, "only the two non-intersecting windows survive"


class TestCapacityBoundary:
    def test_a_purchase_for_exactly_the_remaining_capacity_exhausts_the_registration(self, api):
        """PRD §3.4: "For a `PURCHASE`, the order's `gross_amount` must be less than or
        equal to that registration's `remaining_amount` — equality is accepted and drives
        the registration straight to `EXHAUSTED` — and an amount above it is refused with
        `ERR_BLUE_SKY_CAPACITY_EXCEEDED`; on success `reserved_amount` increases by
        `gross_amount`."
        PRD §3.4: "The selected registration's identifier is recorded on the order as
        `blue_sky_registration_id`, which stays null for orders that consume no capacity at
        all."

        Design: Difficulty/boundary_precision_check/blue_sky_capacity_accepts_exact_remaining_and_rejects_one_cent_more
        """
        desk = setup_exact_capacity_registration()

        response = api.create_trade(
            create_purchase_payload(
                desk["account"]["id"], desk["share_class"]["id"], 50000.00
            ),
            OPERATOR,
        )
        trade = validate_success(response, 201)
        assert trade["blue_sky_registration_id"] == desk["registration"]["id"]

        registration = read_registration(desk["registration"]["id"])
        assert_registration_capacity(
            registration, reserved=50000.00, consumed=0.00,
            remaining=0.00, status="EXHAUSTED",
        )

    def test_one_cent_beyond_the_remaining_capacity_is_refused(self, api):
        """PRD §3.4: "For a `PURCHASE`, the order's `gross_amount` must be less than or
        equal to that registration's `remaining_amount` — equality is accepted and drives
        the registration straight to `EXHAUSTED` — and an amount above it is refused with
        `ERR_BLUE_SKY_CAPACITY_EXCEEDED`; on success `reserved_amount` increases by
        `gross_amount`."
        PRD §3.4: "Whenever `remaining_amount` reaches exactly `0.00` the registration
        moves `ACTIVE → EXHAUSTED`, and whenever it rises back above `0.00` after a
        cancellation or a reversal it moves `EXHAUSTED → ACTIVE`, so the two states cycle
        freely."

        Design: Difficulty/boundary_precision_check/blue_sky_capacity_accepts_exact_remaining_and_rejects_one_cent_more
        """
        desk = setup_exact_capacity_registration()
        capture_purchase(desk["account"]["id"], desk["share_class"]["id"], 50000.00)

        response = api.create_trade(
            create_purchase_payload(
                desk["account"]["id"], desk["share_class"]["id"], 0.01
            ),
            OPERATOR,
        )
        assert response.status_code == 422
        validate_error(response, ApiErrorId.ERR_BLUE_SKY_CAPACITY_EXCEEDED.value)

        registration = read_registration(desk["registration"]["id"])
        assert registration["reserved_amount"] == money(50000.00)
        assert registration["status"] == "EXHAUSTED"
        assert_registration_capacity_identity(registration)


class TestCapacityConservation:
    def test_capture_then_settlement_moves_reserved_capacity_into_consumption(self, api):
        """PRD §3.4: "Capacity is a three-way split that must always reconcile:
        `remaining_amount` is `registered_amount` less `reserved_amount` less
        `consumed_amount`, and that identity holds after every step of the workflow."
        PRD §3.6: "A settling `PURCHASE` increases the position's `cost_basis_amount` by
        the order's `gross_amount`, and converts its state-registration hold into permanent
        use: the selected registration's `reserved_amount` decreases by `gross_amount` while
        its `consumed_amount` increases by the same figure."

        Design: Difficulty/compensating_invariant/capture_settle_cancel_reverse_conserve_registration_capacity_identity
        """
        desk = setup_capacity_identity_desk()
        registration_id = desk["registration"]["id"]

        first = capture_purchase(
            desk["account"]["id"], desk["share_class"]["id"], 20000.00
        )
        after_capture = read_registration(registration_id)
        assert_registration_capacity(
            after_capture, reserved=20000.00, consumed=0.00,
            remaining=30000.00, status="ACTIVE",
        )

        price_trade(first["id"])
        settle_trade(first["id"])
        after_settle = read_registration(registration_id)
        assert_registration_capacity(
            after_settle, reserved=0.00, consumed=20000.00,
            remaining=30000.00, status="ACTIVE",
        )

    def test_cancellation_and_reversal_return_the_registration_to_full_capacity(self, api):
        """PRD §3.6: "Cancelling releases whatever state-registration capacity the order
        was holding: the registration's `reserved_amount` decreases by the order's
        `gross_amount`, and if that lifts the registration's `remaining_amount` above `0.00`
        while its `status` was `EXHAUSTED`, the registration returns to `ACTIVE`."
        PRD §3.6: "Reversing a `PURCHASE` additionally decreases the position's
        `cost_basis_amount` by the order's `gross_amount` and decreases the registration's
        `consumed_amount` by the same amount; if that lifts `remaining_amount` above `0.00`
        while the registration was `EXHAUSTED`, it returns to `ACTIVE`."

        Design: Difficulty/compensating_invariant/capture_settle_cancel_reverse_conserve_registration_capacity_identity
        """
        desk = setup_capacity_identity_desk()
        registration_id = desk["registration"]["id"]

        settled = capture_purchase(
            desk["account"]["id"], desk["share_class"]["id"], 20000.00
        )
        price_trade(settled["id"])
        settle_trade(settled["id"])

        second = capture_purchase(
            desk["account"]["id"], desk["share_class"]["id"], 30000.00
        )
        after_second_capture = read_registration(registration_id)
        assert_registration_capacity(
            after_second_capture, reserved=30000.00, consumed=20000.00,
            remaining=0.00, status="EXHAUSTED",
        )

        validate_success(
            api.cancel_trade(
                second["id"], {"cancel_reason": "Client withdrew the subscription"},
                OPERATOR,
            )
        )
        after_cancel = read_registration(registration_id)
        assert_registration_capacity(
            after_cancel, reserved=0.00, consumed=20000.00,
            remaining=30000.00, status="ACTIVE",
        )

        validate_success(
            api.reverse_trade(
                settled["id"], {"reversal_reason": "Wire never funded"}, COMPLIANCE
            )
        )
        after_reverse = read_registration(registration_id)
        assert_registration_capacity(
            after_reverse, reserved=0.00, consumed=0.00,
            remaining=50000.00, status="ACTIVE",
        )

        assert only_position(desk["account"]["id"])["shares"] == shares(0.000)
        assert read_share_class(desk["share_class"]["id"])[
            "total_shares_outstanding"
        ] == shares(0.000)
